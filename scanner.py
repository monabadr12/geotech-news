#!/usr/bin/env python3
"""
ISSMGE Magazine — Geotechnical News Scanner
Reads trade-site feeds and Google News searches, scores stories for
geotechnical relevance, (optionally) asks Claude to triage them, saves the
digest to data/digests/ (the permanent archive) and rebuilds the website in
docs/ (GitHub Pages). Optionally e-mails the digest.
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

import site_builder

ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("SCANNER_CONFIG", ROOT / "config.yaml"))
SEEN_FILE = ROOT / "data" / "seen.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GeotechNewsScanner/1.0)"}
USES = site_builder.USES


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
                        "region": country, "url": google_news_url(q, lang, country)})
    for item in g.get("extra_queries", []):
        if isinstance(item, str):
            item = {"q": item}
        lang, country = item.get("language", dl), item.get("country", dc)
        out.append({"name": f"Google News {country}", "google": True,
                    "bonus": int(item.get("bonus", 0)), "region": country,
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
def triage_schema(themes):
    story = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "relevance": {"type": "integer"},
            "theme": {"type": "string", "enum": themes},
            "use": {"type": "string", "enum": USES},
            "angle": {"type": "string"},
            "title_en": {"type": "string"},
        },
        "required": ["id", "relevance", "theme", "use", "angle", "title_en"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"stories": {"type": "array", "items": story}},
            "required": ["stories"], "additionalProperties": False}


def claude_triage(items, cfg, notes):
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or not items:
        return False
    import anthropic  # only needed when a key is configured

    client = anthropic.Anthropic(api_key=key, max_retries=3)
    ccfg = cfg["claude"]
    themes = list(cfg["themes"].keys()) + ["General"]
    schema = triage_schema(themes)
    for start in range(0, len(items), 40):
        batch = items[start:start + 40]
        listing = "\n".join(
            f'{start + i}. [{it["source"]}] {it["title"]} :: {it["summary"][:350]}'
            for i, it in enumerate(batch))
        prompt = f"""You are the news-desk assistant of the ISSMGE magazine (International Society for Soil Mechanics and Geotechnical Engineering). Readers are practising geotechnical engineers and academics worldwide. The editor wants stories with real geotechnical substance, not general construction or politics.

For each story below return an object with:
- "id": the number
- "relevance": 1-5 (5 = rich geotechnical lesson or major ground-related event; 3 = clear ground engineering element worth a brief; 1 = not geotechnical)
- "theme": the one magazine theme it fits best
- "use": the best editorial use
- "angle": one sentence (max 30 words) stating the geotechnical question a magazine piece could explore, in your own words
- "title_en": if the headline is not in English, your English translation of it (max 20 words); otherwise ""

Stories:
{listing}"""
        try:
            response = client.messages.create(
                model=ccfg["model"],
                max_tokens=16000,
                output_config={"effort": ccfg.get("effort", "low"),
                               "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": prompt}])
        except anthropic.AuthenticationError:
            notes.append("AI triage skipped: the ANTHROPIC_API_KEY secret was rejected. "
                         "Check the key in Settings → Secrets and variables → Actions.")
            return False
        except anthropic.APIError as ex:  # fall back to keywords for this batch
            notes.append(f"AI triage failed for one batch ({str(ex)[:100]}); keyword ranking used.")
            continue
        if response.stop_reason != "end_turn":
            notes.append(f"AI triage stopped early for one batch ({response.stop_reason}); keyword ranking used.")
            continue
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            results = json.loads(text)["stories"]
        except (ValueError, KeyError) as ex:
            notes.append(f"AI triage returned unreadable output for one batch ({str(ex)[:80]}).")
            continue
        for d in results:
            idx = int(d["id"])
            if 0 <= idx < len(items):
                items[idx].update(
                    relevance=max(1, min(5, int(d["relevance"]))),
                    theme=d["theme"] if d["theme"] in themes else items[idx]["theme"],
                    use=d["use"] if d["use"] in USES else "",
                    angle=d["angle"][:300],
                    title_en=d["title_en"][:200])
    return True


# ------------------------------------------------------------------ e-mail
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


# ------------------------------------------------------------------ archive
def save_digest(now, stories, failures, notes, ai_used, new_count):
    """Write today's digest to data/digests/YYYY-MM-DD.json. A second run on the
    same day adds its stories to the morning's file instead of replacing it."""
    path = site_builder.DIGESTS / f"{now:%Y-%m-%d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = {"date": f"{now:%Y-%m-%d}", "generated": now.isoformat(timespec="minutes"),
              "ai_used": ai_used, "new_items": new_count, "stories": stories,
              "failures": [list(f) for f in failures], "notes": notes}
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        known = {s["id"] for s in stories}
        digest["stories"] = stories + [s for s in old.get("stories", []) if s["id"] not in known]
        digest["new_items"] += old.get("new_items", 0)
        digest["ai_used"] = ai_used or old.get("ai_used", False)
    digest["stories"].sort(key=lambda s: -s["rank"])
    path.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
    return digest


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
            items.append(dict(id=uid, title=title, link=link, source=source, summary=summary,
                              time=when, region=src.get("region", ""), score=score, hits=hits,
                              bonus=src.get("bonus", 0),
                              theme=guess_theme(text, cfg["themes"]),
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
    else:
        # the language bonus only exists to get foreign headlines in front of
        # Claude; without Claude, rank everything on its keywords alone
        for i in candidates:
            i["score"] -= i["bonus"]
        candidates = [i for i in candidates if i["score"] >= cfg.get("min_keyword_score", 3)]
    for i in candidates:
        i["rank"] = i["relevance"] * 100 + i["score"]
    selected = sorted(candidates, key=lambda i: -i["rank"])[: cfg.get("max_items", 40)]

    # prune memory older than 45 days
    limit = (now - dt.timedelta(days=45)).date().isoformat()
    seen = {k: v for k, v in seen.items() if v >= limit}
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen, indent=0))

    stories = [{
        "id": i["id"], "title": i["title"], "title_en": i["title_en"], "link": i["link"],
        "source": i["source"], "region": i["region"], "summary": i["summary"][:400],
        "published": i["time"].isoformat(timespec="minutes") if i["time"] else "",
        "theme": i["theme"], "relevance": i["relevance"], "use": i["use"], "angle": i["angle"],
        "keywords": i["hits"][:6], "score": i["score"], "rank": i["rank"],
    } for i in selected]
    digest = save_digest(now, stories, failures, notes, ai_used, new_count)
    site_builder.build(cfg)

    try:
        mail_note = None
        if selected:
            mail_note = send_email(
                f"Geotechnical News Digest — {now:%d %b %Y} ({len(digest['stories'])} stories)",
                site_builder.render_email(digest, cfg))
    except Exception as ex:
        mail_note = f"E-mail failed: {ex}"
    print(f"{new_count} new items, {len(selected)} selected, {len(failures)} failed sources. {mail_note or ''}")
    for n, e in failures:
        print(f"  failed: {n}: {e}")


if __name__ == "__main__":
    sys.exit(main())
