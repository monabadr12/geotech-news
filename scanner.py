#!/usr/bin/env python3
"""
ISSMGE Magazine — Geotechnical News Scanner
Reads trade-site feeds and Google News searches, scores stories for
geotechnical relevance, (optionally) asks Claude to triage them, and
writes an HTML digest to docs/ (GitHub Pages) with optional e-mail.
"""
import calendar
import datetime as dt
import difflib
import hashlib
import html
import json
import os
import re
import smtplib
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import feedparser
import requests
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("SCANNER_CONFIG", ROOT / "config.yaml"))
SEEN_FILE = ROOT / "data" / "seen.json"
DOCS = ROOT / "docs"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GeotechNewsScanner/1.0)"}
USES = ["News brief", "Feature lead", "Academia-to-Industry topic", "Regional insight", "Watch only"]


# ------------------------------------------------------------------ fetching
def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.content


FEED_TAG = re.compile(r"<link[^>]+type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>", re.I)
HREF = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)


def read_feed(url):
    """Return feed entries; if url is a web page, auto-discover its feed."""
    content = fetch(url)
    parsed = feedparser.parse(content)
    if parsed.entries:
        return parsed.entries
    page = content.decode("utf-8", "ignore")
    for tag in FEED_TAG.findall(page):
        m = HREF.search(tag)
        if not m:
            continue
        found = feedparser.parse(fetch(urljoin(url, html.unescape(m.group(1)))))
        if found.entries:
            return found.entries
    raise ValueError("no RSS/Atom feed found at this address")


def google_news_url(query, lang, country):
    q = quote_plus(f"{query} when:3d")
    return f"https://news.google.com/rss/search?q={q}&hl={lang}-{country}&gl={country}&ceid={country}:{lang}"


def google_sources(g):
    """Build one feed per (query, edition). Non-English queries carry a bonus so
    they survive the English keyword filter and are judged by Claude instead."""
    out = []
    dl, dc = g.get("language", "en"), g.get("country", "GB")
    editions = g.get("editions") or [{"language": dl, "country": dc}]
    for q in g.get("core_queries", []):
        for ed in editions:
            lang, country = ed.get("language", dl), ed.get("country", dc)
            out.append({"name": f"Google News {country}", "google": True, "bonus": 0,
                        "url": google_news_url(q, lang, country)})
    for item in g.get("extra_queries", []):
        if isinstance(item, str):
            item = {"q": item}
        lang, country = item.get("language", dl), item.get("country", dc)
        out.append({"name": f"Google News {country}", "google": True,
                    "bonus": int(item.get("bonus", 0)),
                    "url": google_news_url(item["q"], lang, country)})
    return out


# ------------------------------------------------------------------ helpers
def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def entry_time(e):
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return dt.datetime.fromtimestamp(calendar.timegm(t), dt.timezone.utc)
    return None


def term_regex(term):
    return re.compile(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?:s|es)?(?![a-z0-9])")


def keyword_score(text, cfg, compiled):
    low = text.lower()
    score, hits = 0, []
    for term, (rx, weight) in compiled.items():
        if rx.search(low):
            score += weight
            hits.append(term)
    for bad in cfg.get("exclude", []):
        if bad.lower() in low:
            score -= 5
    return score, hits


def guess_theme(text, themes):
    low = text.lower()
    best, best_n = "General", 0
    for theme, words in themes.items():
        n = sum(1 for w in words if re.search(r"(?<![a-z])" + re.escape(w.lower()), low))
        if n > best_n:
            best, best_n = theme, n
    return best


# ------------------------------------------------------------------ Claude triage
def claude_triage(items, cfg, notes):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or not items:
        return False
    themes = list(cfg["themes"].keys()) + ["General"]
    for start in range(0, len(items), 40):
        batch = items[start:start + 40]
        listing = "\n".join(
            f'{start + i}. [{it["source"]}] {it["title"]} :: {it["summary"][:350]}'
            for i, it in enumerate(batch))
        prompt = f"""You are the news-desk assistant of the ISSMGE magazine (International Society for Soil Mechanics and Geotechnical Engineering). Readers are practising geotechnical engineers and academics worldwide. The editor wants stories with real geotechnical substance, not general construction or politics.

For each story below return a JSON object with:
- "id": the number
- "relevance": 1-5 (5 = rich geotechnical lesson or major ground-related event; 3 = clear ground engineering element worth a brief; 1 = not geotechnical)
- "theme": exactly one of {json.dumps(themes)}
- "use": exactly one of {json.dumps(USES)}
- "angle": one sentence (max 30 words) stating the geotechnical question a magazine piece could explore, in your own words
- "title_en": if the headline is not in English, your English translation of it (max 20 words); otherwise ""

Respond ONLY with a JSON array, no other text.

Stories:
{listing}"""
        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                         "content-type": "application/json"},
                json={"model": cfg["claude"]["model"], "max_tokens": 6000,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=180)
            r.raise_for_status()
            text = "".join(b.get("text", "") for b in r.json().get("content", []))
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
            for d in json.loads(text):
                idx = int(d["id"])
                if 0 <= idx < len(items):
                    items[idx].update(
                        relevance=int(d.get("relevance", 0)),
                        theme=d.get("theme") if d.get("theme") in themes else items[idx]["theme"],
                        use=d.get("use") if d.get("use") in USES else "",
                        angle=str(d.get("angle", ""))[:300],
                        title_en=str(d.get("title_en", ""))[:200])
        except Exception as ex:  # fall back to keywords for this batch
            notes.append(f"AI triage failed for one batch ({str(ex)[:100]}); keyword ranking used.")
    return True


# ------------------------------------------------------------------ output
CSS = """
:root{--bg:#f6f5f1;--card:#fff;--ink:#1d2327;--muted:#5f6b72;--line:#e2e0d8;--accent:#8a5a19;--chip:#f1e9dc}
@media (prefers-color-scheme:dark){:root{--bg:#15181b;--card:#1f2327;--ink:#e9ecee;--muted:#9aa6ad;--line:#30363b;--accent:#e0a95a;--chip:#2c2a25}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 Georgia,'Times New Roman',serif}
.wrap{max-width:860px;margin:0 auto;padding:28px 18px 60px}
header{border-bottom:3px double var(--line);margin-bottom:22px;padding-bottom:14px}
h1{font-size:1.9rem;margin:0 0 4px}h2{font-size:1.15rem;margin:34px 0 10px;color:var(--accent);font-family:Arial,sans-serif;letter-spacing:.02em}
.meta,.small{color:var(--muted);font:13px/1.5 Arial,sans-serif}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:10px 0}
.card a{color:var(--ink);font-weight:bold;text-decoration:none}.card a:hover{text-decoration:underline}
.angle{margin:8px 0 4px;font-style:italic}
.chip{display:inline-block;background:var(--chip);border-radius:20px;padding:1px 9px;margin:4px 4px 0 0;font:12px Arial,sans-serif;color:var(--muted)}
.chip.use{color:var(--accent);font-weight:bold}
details{margin-top:30px}summary{cursor:pointer}ul{padding-left:20px}
"""


def render(items, failures, notes, now, ai_used, total_seen, archive_links):
    esc = html.escape
    by_theme = {}
    for it in items:
        by_theme.setdefault(it["theme"], []).append(it)
    order = sorted(by_theme, key=lambda t: (-max(i["rank"] for i in by_theme[t]), t))
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>Geotechnical News Digest — {now:%d %b %Y}</title><style>{CSS}</style></head>"
             f"<body><div class='wrap'><header><h1>Geotechnical News Digest</h1>"
             f"<div class='meta'>ISSMGE Magazine news desk · {now:%A %d %B %Y, %H:%M} UTC · "
             f"{len(items)} stories selected from {total_seen} new items"
             f"{' · AI-triaged' if ai_used else ' · keyword-ranked'}</div></header>"]
    if not items:
        parts.append("<p>No new geotechnical stories met the threshold in this period.</p>")
    for theme in order:
        parts.append(f"<h2>{esc(theme)}</h2>")
        for it in sorted(by_theme[theme], key=lambda i: -i["rank"]):
            date = it["time"].strftime("%d %b") if it["time"] else "date n/a"
            stars = ("★" * it["relevance"] + "☆" * (5 - it["relevance"])) if it.get("relevance") else ""
            shown = it.get("title_en") or it["title"]
            parts.append("<div class='card'>"
                         f"<a href='{esc(it['link'])}' target='_blank' rel='noopener'>{esc(shown)}</a>"
                         + (f"<div class='small'>original: {esc(it['title'])}</div>"
                            if it.get('title_en') else ""))
            parts.append(
                f"<div class='small'>{esc(it['source'])} · {date} {('· ' + stars) if stars else ''}</div>")
            if it.get("angle"):
                parts.append(f"<div class='angle'>{esc(it['angle'])}</div>")
            elif it["summary"]:
                parts.append(f"<div class='small' style='margin-top:6px'>{esc(it['summary'][:260])}…</div>")
            if it.get("use"):
                parts.append(f"<span class='chip use'>{esc(it['use'])}</span>")
            for h in it["hits"][:5]:
                parts.append(f"<span class='chip'>{esc(h)}</span>")
            parts.append("</div>")
    if failures or notes:
        parts.append("<details><summary class='small'>Scanner notes and sources that failed</summary><ul class='small'>")
        parts += [f"<li>{esc(n)}</li>" for n in notes]
        parts += [f"<li><b>{esc(n)}</b>: {esc(e)}</li>" for n, e in failures]
        parts.append("</ul></details>")
    if archive_links:
        parts.append("<details><summary class='small'>Previous digests</summary><ul class='small'>")
        parts += [f"<li><a href='{esc(href)}'>{esc(label)}</a></li>" for label, href in archive_links]
        parts.append("</ul></details>")
    parts.append("<p class='small' style='margin-top:30px'>Headlines link to the original publishers. "
                 "Use them as leads; verify with the primary source before publishing.</p></div></body></html>")
    return "".join(parts)


def send_email(subject, body_html):
    host, to = os.environ.get("SMTP_HOST", "").strip(), os.environ.get("MAIL_TO", "").strip()
    if not host or not to:
        return "E-mail not configured (optional)."
    user, pwd = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
    port = int(os.environ.get("SMTP_PORT", "587") or 587)
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user or to, to
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    with smtplib.SMTP(host, port, timeout=60) as s:
        s.starttls()
        if user:
            s.login(user, pwd)
        s.sendmail(msg["From"], [a.strip() for a in to.split(",")], msg.as_string())
    return f"E-mail sent to {to}."


# ------------------------------------------------------------------ main
def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=cfg.get("lookback_hours", 60))
    seen = json.loads(SEEN_FILE.read_text()) if SEEN_FILE.exists() else {}
    compiled = {t: (term_regex(t), w) for t, w in cfg["keywords"].items()}

    sources = [dict(s) for s in cfg.get("feeds", [])]
    sources += google_sources(cfg.get("google_news") or {})

    items, failures, notes, new_count = [], [], [], 0
    for src in sources:
        try:
            entries = read_feed(src["url"])
        except Exception as ex:
            if not src.get("google"):
                failures.append((src["name"], str(ex)[:140]))
            continue
        for e in entries:
            link, title = e.get("link"), clean(e.get("title"))
            if not link or not title:
                continue
            uid = hashlib.sha1(link.encode()).hexdigest()[:16]
            if uid in seen:
                continue
            when = entry_time(e)
            if when and when < cutoff:
                continue
            seen[uid] = now.date().isoformat()
            new_count += 1
            source = src["name"]
            if src.get("google"):
                outlet = (e.get("source") or {}).get("title")
                if outlet:
                    source = outlet
                    title = re.sub(r"\s+-\s+" + re.escape(outlet) + r"$", "", title)
            summary = clean(e.get("summary"))
            if src.get("google"):
                summary = ""  # Google's summary just repeats the headline
            text = f"{title} {summary}"
            score, hits = keyword_score(text, cfg, compiled)
            score += src.get("boost", 0) if hits else 0
            score += src.get("bonus", 0)
            items.append(dict(title=title, link=link, source=source, summary=summary, time=when,
                              score=score, hits=hits, theme=guess_theme(text, cfg["themes"]),
                              relevance=0, use="", angle="", title_en=""))
        time.sleep(0.3)

    # remove near-duplicate headlines (same story from several outlets)
    items.sort(key=lambda i: -i["score"])
    unique = []
    for it in items:
        norm = re.sub(r"[^a-z0-9 ]", "", it["title"].lower())
        if any(difflib.SequenceMatcher(None, norm, u["_n"]).ratio() > 0.8 for u in unique):
            continue
        it["_n"] = norm
        unique.append(it)

    candidates = [i for i in unique if i["score"] >= cfg.get("min_keyword_score", 3)]
    candidates = candidates[: cfg["claude"].get("max_candidates", 80)]
    ai_used = claude_triage(candidates, cfg, notes)
    if ai_used:
        minrel = cfg["claude"].get("min_relevance", 3)
        candidates = [i for i in candidates if i["relevance"] >= minrel or i["relevance"] == 0]
    for i in candidates:
        i["rank"] = i["relevance"] * 100 + i["score"]
    selected = sorted(candidates, key=lambda i: -i["rank"])[: cfg.get("max_items", 40)]

    # prune memory older than 45 days
    limit = (now - dt.timedelta(days=45)).date().isoformat()
    seen = {k: v for k, v in seen.items() if v >= limit}
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen, indent=0))

    archive_dir = DOCS / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y-%m-%d")
    old = sorted((p for p in archive_dir.glob("*.html") if p.stem != stamp), reverse=True)[:60]
    links = [(p.stem, f"archive/{p.name}") for p in old]

    try:
        mail_note = None
        page = render(selected, failures, notes, now, ai_used, new_count, links)
        (archive_dir / f"{stamp}.html").write_text(
            render(selected, failures, notes, now, ai_used, new_count, []), encoding="utf-8")
        (DOCS / "index.html").write_text(page, encoding="utf-8")
        if selected:
            mail_note = send_email(f"Geotechnical News Digest — {now:%d %b %Y} ({len(selected)} stories)", page)
    except Exception as ex:
        mail_note = f"E-mail failed: {ex}"
    print(f"{new_count} new items, {len(selected)} selected, {len(failures)} failed sources. {mail_note or ''}")
    for n, e in failures:
        print(f"  failed: {n}: {e}")


if __name__ == "__main__":
    sys.exit(main())
