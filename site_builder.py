#!/usr/bin/env python3
"""
Builds the website in docs/ from the saved digests in data/digests/.

The digests (one JSON file per day) are the permanent archive; everything in
docs/ is regenerated from them on every run, so the design can be changed and
the whole site rebuilt at any time with:   python site_builder.py
"""
import csv
import datetime as dt
import html
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parent
DIGESTS = ROOT / "data" / "digests"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"
esc = html.escape

USES = ["News brief", "Feature lead", "Academia-to-Industry topic", "Regional insight", "Watch only"]
BADGE = "<span class='badge'>In progress</span>"
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
COUNTRIES = {
    "GB": "United Kingdom", "US": "United States", "IN": "India", "AU": "Australia",
    "ZA": "South Africa", "SG": "Singapore", "AE": "United Arab Emirates", "FR": "France",
    "SN": "Senegal", "EG": "Egypt", "ES": "Spain", "MX": "Mexico", "BR": "Brazil",
    "DE": "Germany", "IT": "Italy", "TR": "Türkiye", "ID": "Indonesia", "CN": "China",
    "JP": "Japan",
}
CSV_FIELDS = ["Digest date", "Issue window", "Theme", "Relevance (1-5)", "Suggested use",
              "Headline (English)", "Original headline", "Magazine angle", "Source",
              "Google News edition", "Published", "Link", "Keywords"]


# ------------------------------------------------------------------ data
def load_digests():
    out = [json.loads(p.read_text(encoding="utf-8")) for p in DIGESTS.glob("*.json")]
    return sorted(out, key=lambda d: d["date"], reverse=True)


def issue_window(date_str, start_month=1):
    """Three-month window (matching the magazine's quarterly cycle) containing date."""
    d = dt.date.fromisoformat(date_str[:10])
    offset = (d.month - start_month) % 12
    first = (start_month - 1 + offset // 3 * 3) % 12 + 1
    year = d.year if first <= d.month else d.year - 1
    last = (first + 1) % 12 + 1
    last_year = year + (1 if last < first else 0)
    n = offset // 3 + 1
    span = (f"{MONTHS[first - 1]} – {MONTHS[last - 1]} {year}" if last_year == year
            else f"{MONTHS[first - 1]} {year} – {MONTHS[last - 1]} {last_year}")
    return {"key": f"{year}-Q{n}", "label": f"Q{n} {year}", "span": span}


def nice_date(iso, weekday=False):
    if not iso:
        return ""
    d = dt.date.fromisoformat(iso[:10])
    return f"{d:%A} {d.day} {d:%B %Y}" if weekday else f"{d.day} {d:%b %Y}"


def site_url(cfg):
    url = os.environ.get("SITE_URL") or (cfg.get("magazine") or {}).get("site_url", "")
    if not url and "/" in os.environ.get("GITHUB_REPOSITORY", ""):
        owner, repo = os.environ["GITHUB_REPOSITORY"].split("/", 1)
        url = f"https://{owner.lower()}.github.io/{repo}/"
    return url.rstrip("/") + "/" if url else ""


# ------------------------------------------------------------------ page parts
def page(cfg, title, body, root, active, description=""):
    mag = (cfg.get("magazine") or {}).get("name", "ISSMGE Magazine")
    nav = [("index.html", "Latest", "latest"), ("archive.html", "Archive", "archive"),
           ("search.html", "Search", "search"), ("about.html", "Method & sources", "about")]
    current = " class='active' aria-current='page'"
    links = "".join(f"<a href='{root}{href}'{current if key == active else ''}>{label}</a>"
                    for href, label, key in nav)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · Geotechnical News Desk</title>
<meta name="description" content="{esc(description or 'Geotechnical news digest for the ' + mag)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{root}assets/style.css">
</head><body data-root="{root}">
<header class="masthead"><div class="wrap masthead-inner">
<a class="brand" href="{root}index.html"><span class="brand-mark" aria-hidden="true"></span>
<span><span class="brand-name">Geotechnical News Desk</span><span class="brand-sub">{esc(mag)} · editorial monitoring</span></span></a>
<nav class="nav">{links}</nav></div></header>
<main class="wrap">{body}</main>
<footer class="foot"><div class="wrap">Headlines link to the original publishers. Treat every story as a lead and verify with the primary source before publishing.
Ratings, themes and angles are machine-assisted suggestions for the editorial team.</div></footer>
<script src="{root}assets/app.js"></script>
</body></html>"""


def rating(s):
    rel = s.get("relevance") or 0
    if not rel:
        return f"<span class='rel rel-kw' title='Not AI-rated; ranked by keyword score'>Keyword score {s.get('score', 0)}</span>"
    bars = "<i></i>" * 5
    return f"<span class='rel rel-{rel}' title='Geotechnical relevance: {rel} of 5'>{bars}<b>{rel}/5</b></span>"


def story_card(s, show_theme=False):
    shown = s.get("title_en") or s["title"]
    when = nice_date(s.get("published") or s.get("_digest", ""))
    region = COUNTRIES.get(s.get("region", ""), s.get("region", ""))
    search_text = " ".join([shown, s["title"], s.get("angle", ""), s["source"], region,
                            " ".join(s.get("keywords", []))]).lower()
    meta = [f"<span class='src'>{esc(s['source'])}</span>"]
    if when:
        meta.append(f"<time>{esc(when)}</time>")
    if region:
        meta.append(f"<span>{esc(region)} edition</span>")
    parts = [f"<article class='story' data-rel='{s.get('relevance') or 0}' data-use='{esc(s.get('use', ''))}' "
             f"data-text='{esc(search_text)}'>",
             "<div class='story-top'>",
             f"<a class='story-title' href='{esc(s['link'])}' target='_blank' rel='noopener'>{esc(shown)}</a>",
             rating(s), "</div>"]
    if s.get("title_en"):
        parts.append(f"<div class='orig' dir='auto'>Original: {esc(s['title'])}</div>")
    if s.get("angle"):
        parts.append(f"<p class='angle'><span>Magazine angle</span>{esc(s['angle'])}</p>")
    elif s.get("summary"):
        parts.append(f"<p class='summary'>{esc(s['summary'][:260])}…</p>")
    parts.append("<div class='story-meta'>")
    if s.get("use"):
        slug = s["use"].split()[0].lower().strip("-")
        parts.append(f"<span class='use use-{esc(slug)}'>{esc(s['use'])}</span>")
    if show_theme:
        parts.append(f"<span class='theme-tag'>{esc(s['theme'])}</span>")
    parts.append(" · ".join(meta) + "</div>")
    if s.get("keywords"):
        parts.append("<div class='kw'>" + "".join(f"<span>{esc(k)}</span>" for k in s["keywords"][:5]) + "</div>")
    parts.append("</article>")
    return "".join(parts)


def filter_bar(uses):
    opts = "".join(f"<option>{esc(u)}</option>" for u in uses)
    return f"""<div class="toolbar js-filter" role="search">
<label class="field grow"><span>Filter</span><input type="search" class="f-text" placeholder="Keyword, place, source…"></label>
<label class="field"><span>Minimum rating</span><select class="f-rel"><option value="0">Any</option><option value="3">3 / 5 and above</option><option value="4">4 / 5 and above</option><option value="5">5 / 5 only</option></select></label>
<label class="field"><span>Suggested use</span><select class="f-use"><option value="">All uses</option>{opts}</select></label>
<span class="f-count" aria-live="polite"></span></div>"""


def theme_sections(stories, order=None, show_theme=False):
    by_theme = {}
    for s in stories:
        by_theme.setdefault(s["theme"], []).append(s)
    if order is None:  # strongest theme first
        order = sorted(by_theme, key=lambda t: (-max(i["rank"] for i in by_theme[t]), t))
    toc = "".join(f"<a href='#{slug(t)}'>{esc(t)} <b>{len(by_theme[t])}</b></a>" for t in order if t in by_theme)
    out = [f"<nav class='theme-toc' aria-label='Themes'>{toc}</nav>"]
    for t in order:
        if t not in by_theme:
            continue
        items = sorted(by_theme[t], key=lambda s: (-(s.get("relevance") or 0), -s["rank"]))
        out.append(f"<section class='theme-section' id='{slug(t)}'><h2>{esc(t)} <span class='count'>{len(items)}</span></h2>")
        out += [story_card(s, show_theme) for s in items]
        out.append("</section>")
    return "".join(out)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def stat(value, label):
    return f"<div class='stat'><b>{value}</b><span>{esc(label)}</span></div>"


# ------------------------------------------------------------------ pages
def digest_body(d, cfg, root, uses, prev_d=None, next_d=None, latest=False):
    win = issue_window(d["date"], start_month(cfg))
    stories = d["stories"]
    themes = len({s["theme"] for s in stories})
    head = [f"<div class='page-head'><p class='eyebrow'>{'Latest digest' if latest else 'Daily digest'} · "
            f"<a href='{root}issues/{win['key']}.html'>{win['label']} issue window</a></p>",
            f"<h1>{esc(nice_date(d['date'], weekday=True))}</h1>",
            "<div class='stats'>", stat(len(stories), "stories selected"),
            stat(d.get("new_items", 0), "new items scanned"), stat(themes, "themes"),
            stat("AI" if d.get("ai_used") else "Keywords", "triage method"), "</div></div>"]
    if latest:
        head.append(f"<a class='callout' href='{root}issues/{win['key']}.html'><b>Building the {win['label']} issue?</b> "
                    f"Every story found {win['span']} is collected in one place, by theme, with a spreadsheet export →</a>")
    if not stories:
        head.append("<p class='empty'>No new geotechnical stories met the threshold in this period.</p>")
    else:
        head.append(filter_bar(uses))
        head.append(theme_sections(stories))
    pager = ["<nav class='pager'>"]
    pager.append(f"<a href='{root}digests/{prev_d}.html'>← {esc(nice_date(prev_d))}</a>" if prev_d else "<span></span>")
    pager.append(f"<a href='{root}archive.html'>All digests</a>")
    pager.append(f"<a href='{root}digests/{next_d}.html'>{esc(nice_date(next_d))} →</a>" if next_d else "<span></span>")
    pager.append("</nav>")
    head += pager
    head.append(notes_panel(d))
    return "".join(head)


def notes_panel(d):
    if not d.get("failures") and not d.get("notes"):
        return ""
    rows = [f"<li>{esc(n)}</li>" for n in d.get("notes", [])]
    rows += [f"<li><b>{esc(n)}</b>: {esc(e)}</li>" for n, e in d.get("failures", [])]
    return (f"<details class='notes'><summary>Scanner notes and sources that failed "
            f"({len(d.get('failures', []))} sources)</summary>"
            "<p>These sites blocked the reader or have no feed. Replace their address in "
            "<code>config.yaml</code> with the site's RSS feed address.</p>"
            f"<ul>{''.join(rows)}</ul></details>")


def window_summary(stories):
    return {
        "stories": len(stories),
        "top": sum(1 for s in stories if s.get("relevance") == 5),
        "features": sum(1 for s in stories if s.get("use") == "Feature lead"),
    }


def issue_body(win, stories, digests, cfg, uses, current):
    root = "../"
    order = theme_order(cfg)
    summ = window_summary(stories)
    counts = {}
    for s in stories:
        c = counts.setdefault(s["theme"], {"n": 0, "r5": 0, "r4": 0, "fl": 0, "a2i": 0})
        c["n"] += 1
        c["r5"] += s.get("relevance") == 5
        c["r4"] += s.get("relevance") == 4
        c["fl"] += s.get("use") == "Feature lead"
        c["a2i"] += s.get("use") == "Academia-to-Industry topic"
    rows = "".join(
        f"<tr><th scope='row'><a href='#{slug(t)}'>{esc(t)}</a></th><td>{c['n']}</td><td>{c['r5']}</td>"
        f"<td>{c['r4']}</td><td>{c['fl']}</td><td>{c['a2i']}</td></tr>"
        for t in order if (c := counts.get(t)))
    best = sorted((s for s in stories if s.get("relevance") == 5 or s.get("use") == "Feature lead"),
                  key=lambda s: -s["rank"])[:12]
    dlist = "".join(f"<li><a href='{root}digests/{d['date']}.html'>{esc(nice_date(d['date']))}</a>"
                    f"<span>{len(d['stories'])} stories</span></li>" for d in digests)
    body = [f"<div class='page-head'><p class='eyebrow'><a href='{root}archive.html'>Archive</a> · Issue window"
            f"{' · ' + BADGE if current else ''}</p>",
            f"<h1>{win['label']} <span class='h1-sub'>{esc(win['span'])}</span></h1>",
            "<p class='lede'>Every story selected by the daily scans in this three-month window, "
            "grouped by the magazine's cross-cutting themes and ordered by geotechnical relevance.</p>",
            "<div class='stats'>", stat(summ["stories"], "stories"), stat(len(digests), "daily digests"),
            stat(summ["top"], "rated 5 / 5"), stat(summ["features"], "feature leads"), "</div>",
            f"<div class='actions'><a class='btn primary' href='{root}exports/{win['key']}.csv' download>Download spreadsheet (CSV)</a>"
            f"<a class='btn' href='{root}search.html?q_window={win['key']}'>Search this window</a>"
            f"<button class='btn' type='button' onclick='window.print()'>Print / save as PDF</button></div></div>"]
    if not stories:
        body.append("<p class='empty'>No stories yet in this window.</p>")
        return "".join(body)
    body.append("<h2 class='section-h'>Theme overview</h2><div class='table-wrap'><table class='overview'>"
                "<thead><tr><th scope='col'>Theme</th><th scope='col'>Stories</th><th scope='col'>Rated 5</th>"
                "<th scope='col'>Rated 4</th><th scope='col'>Feature leads</th><th scope='col'>Academia-to-Industry</th></tr></thead>"
                f"<tbody>{rows}</tbody></table></div>")
    if best:
        body.append("<h2 class='section-h'>Strongest leads</h2><p class='hint'>Stories rated 5 / 5 or suggested as feature leads.</p>"
                    "<div class='shortlist'>" + "".join(story_card(s, show_theme=True) for s in best) + "</div>")
    body.append("<h2 class='section-h'>All stories by theme</h2>")
    body.append(filter_bar(uses))
    body.append(theme_sections(stories, order=order))
    body.append(f"<h2 class='section-h'>Daily digests in this window</h2><ul class='digest-list'>{dlist}</ul>")
    return "".join(body)


def archive_body(windows, cfg, current_key):
    root = ""
    order = theme_order(cfg)
    if not windows:
        return ("<div class='page-head'><h1>Archive</h1></div><p class='empty'>The archive is empty. "
                "It fills automatically after the first scan.</p>")
    total = sum(len(w["stories"]) for w in windows)
    out = ["<div class='page-head'><p class='eyebrow'>Archive</p><h1>All digests</h1>",
           "<p class='lede'>Every daily digest is kept permanently. They are grouped into three-month "
           "issue windows that follow the magazine's publication cycle, so each issue can be planned "
           "from one page and one spreadsheet.</p><div class='stats'>",
           stat(len(windows), "issue windows"), stat(sum(len(w["digests"]) for w in windows), "daily digests"),
           stat(total, "stories archived"), "</div></div>"]
    for w in windows:
        win, stories, digests = w["win"], w["stories"], w["digests"]
        summ = window_summary(stories)
        counts = {}
        for s in stories:
            counts[s["theme"]] = counts.get(s["theme"], 0) + 1
        peak = max(counts.values(), default=1)
        bars = "".join(
            f"<li><span>{esc(t)}</span><i style='--w:{counts[t] / peak * 100:.0f}%'></i><b>{counts[t]}</b></li>"
            for t in order if t in counts)
        days = "".join(f"<a href='digests/{d['date']}.html'>{dt.date.fromisoformat(d['date']).day} "
                       f"{MONTHS[int(d['date'][5:7]) - 1]}<span>{len(d['stories'])}</span></a>" for d in digests)
        out.append(
            f"<section class='window'><div class='window-head'><div><h2>{win['label']}"
            f"{' ' + BADGE if win['key'] == current_key else ''}</h2>"
            f"<p>{esc(win['span'])} · {summ['stories']} stories · {len(digests)} digests · "
            f"{summ['top']} rated 5 / 5 · {summ['features']} feature leads</p></div>"
            f"<div class='actions'><a class='btn primary' href='{root}issues/{win['key']}.html'>Open issue collection</a>"
            f"<a class='btn' href='{root}exports/{win['key']}.csv' download>CSV</a></div></div>"
            f"<div class='window-body'><ul class='bars'>{bars}</ul>"
            f"<div class='days'><h3>Daily digests</h3><div class='day-grid'>{days}</div></div></div></section>")
    return "".join(out)


def search_body(cfg, uses, windows):
    themes = "".join(f"<option>{esc(t)}</option>" for t in theme_order(cfg))
    uopts = "".join(f"<option>{esc(u)}</option>" for u in uses)
    wopts = "".join(f"<option value='{w['win']['key']}'>{w['win']['label']} ({esc(w['win']['span'])})</option>" for w in windows)
    return f"""<div class="page-head"><p class="eyebrow">Archive search</p><h1>Search every story</h1>
<p class="lede">Search across all archived digests. Combine filters, then export the result as a spreadsheet.</p></div>
<div id="search-app" class="toolbar search-tools">
<label class="field grow"><span>Search</span><input type="search" id="q" placeholder="e.g. liquefaction, Riyadh, monopile, TBM…" autofocus></label>
<label class="field"><span>Issue window</span><select id="q_window"><option value="">All windows</option>{wopts}</select></label>
<label class="field"><span>Theme</span><select id="q_theme"><option value="">All themes</option>{themes}</select></label>
<label class="field"><span>Suggested use</span><select id="q_use"><option value="">All uses</option>{uopts}</select></label>
<label class="field"><span>Minimum rating</span><select id="q_rel"><option value="0">Any</option><option value="3">3 / 5+</option><option value="4">4 / 5+</option><option value="5">5 / 5</option></select></label>
<label class="field"><span>Sort</span><select id="q_sort"><option value="rel">Relevance</option><option value="new">Newest first</option></select></label>
</div>
<div class="result-bar"><span id="result-count" aria-live="polite">Loading archive…</span>
<button class="btn" type="button" id="export">Export results (CSV)</button></div>
<div id="results"></div><div class="more-wrap"><button class="btn" type="button" id="more" hidden>Show more</button></div>"""


def about_body(cfg, latest):
    feeds = cfg.get("feeds", [])
    g = cfg.get("google_news") or {}
    editions = len(g.get("editions") or [1])
    n_core, n_extra = len(g.get("core_queries", [])), len(g.get("extra_queries", []))
    n_foreign = sum(1 for q in g.get("extra_queries", []) if isinstance(q, dict) and q.get("language", "en") != "en")
    ccfg = cfg.get("claude", {})
    themes = "".join(f"<li><b>{esc(t)}</b><span>{esc(', '.join(w))}</span></li>" for t, w in cfg["themes"].items())
    rows = "".join(
        f"<tr><td>{esc(f['name'])}</td><td>{esc(urlparse(f['url']).netloc.replace('www.', ''))}</td>"
        f"<td>{'+' + str(f['boost']) if f.get('boost') else '—'}</td></tr>" for f in feeds)
    failed = ""
    if latest and latest.get("failures"):
        failed = ("<h2 class='section-h'>Sources that failed on the latest run</h2><ul class='plain'>"
                  + "".join(f"<li><b>{esc(n)}</b>: {esc(e)}</li>" for n, e in latest["failures"]) + "</ul>")
    return f"""<div class="page-head"><p class="eyebrow">Method & sources</p><h1>How the digest is made</h1>
<p class="lede">A scheduled scan reads specialist, institutional and trade sources plus worldwide news searches,
filters them for geotechnical substance, and files the result under the magazine's eight themes.</p>
<div class="stats">{stat(len(feeds), 'websites read directly')}{stat(n_core * editions + n_extra, 'news searches')}
{stat(n_foreign, 'non-English searches')}{stat(len(cfg['keywords']), 'weighted keywords')}</div></div>
<div class="prose">
<h2 class="section-h">Each run</h2><ol class="steps">
<li><b>Collect.</b> {len(feeds)} websites and {n_core * editions + n_extra} Google News searches ({n_core} core searches in {editions} English editions, plus {n_extra} further searches including {n_foreign} in other languages). Each run looks back {cfg.get('lookback_hours', 60)} hours; stories already shown are remembered for 45 days and never repeated.</li>
<li><b>Score.</b> Headlines and summaries are scored against {len(cfg['keywords'])} weighted geotechnical keywords; specialist and society sources earn bonus points, noise terms lose points, near-identical headlines are merged. A story needs {cfg.get('min_keyword_score', 3)} points to go forward.</li>
<li><b>Triage.</b> Up to {ccfg.get('max_candidates', 80)} candidates go to Claude, which rates each 1–5 for geotechnical substance (below {ccfg.get('min_relevance', 3)} is dropped), assigns a theme and a suggested use, writes a one-sentence magazine angle, and translates non-English headlines.</li>
<li><b>Publish & archive.</b> Up to {cfg.get('max_items', 40)} stories per digest. Every digest is stored permanently and grouped into three-month issue windows.</li></ol>
<h2 class="section-h">Magazine themes</h2><p class="hint">Words that suggest each theme when stories are keyword-ranked.</p><ul class="theme-list">{themes}</ul>
<h2 class="section-h">Websites read directly</h2><div class="table-wrap"><table class="overview"><thead><tr><th>Source</th><th>Site</th><th>Bonus</th></tr></thead><tbody>{rows}</tbody></table></div>
{failed}
<h2 class="section-h">Known limits</h2><p>Coverage of a country depends on what its press publishes online in a language covered here. Google News favours recency and mainstream outlets, so a major landslide is picked up readily while a quiet technical advance may not be — which is why society and institutional feeds are read directly.</p>
</div>"""


# ------------------------------------------------------------------ e-mail
def render_email(d, cfg):
    url = site_url(cfg)
    rows = []
    by_theme = {}
    for s in d["stories"]:
        by_theme.setdefault(s["theme"], []).append(s)
    for t in sorted(by_theme, key=lambda t: -max(i["rank"] for i in by_theme[t])):
        rows.append(f"<h2 style='font:600 15px Arial,sans-serif;color:#16324f;border-bottom:2px solid #c9a227;"
                    f"padding-bottom:4px;margin:26px 0 8px'>{esc(t)}</h2>")
        for s in sorted(by_theme[t], key=lambda s: -s["rank"]):
            rel = f"{s['relevance']}/5 · " if s.get("relevance") else ""
            rows.append(
                "<div style='margin:0 0 14px'>"
                f"<a href='{esc(s['link'])}' style='font:600 15px Arial,sans-serif;color:#1b2430'>{esc(s.get('title_en') or s['title'])}</a>"
                f"<div style='font:12px Arial,sans-serif;color:#5b6573;margin-top:2px'>{rel}{esc(s.get('use') or '')}"
                f"{' · ' if s.get('use') else ''}{esc(s['source'])}</div>"
                + (f"<div style='font:italic 14px Georgia,serif;color:#333;margin-top:4px'>{esc(s['angle'])}</div>" if s.get("angle") else "")
                + "</div>")
    link = (f"<p style='font:13px Arial,sans-serif'><a href='{url}digests/{d['date']}.html'>Open this digest on the website</a> · "
            f"<a href='{url}archive.html'>Archive</a></p>") if url else ""
    return ("<html><body style='margin:0;background:#f4f5f3'><div style='max-width:680px;margin:0 auto;background:#fff;padding:24px 26px'>"
            f"<div style='font:600 12px Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:#9a7b1c'>Geotechnical News Desk</div>"
            f"<h1 style='font:600 24px Georgia,serif;color:#16324f;margin:4px 0 6px'>{esc(nice_date(d['date'], weekday=True))}</h1>"
            f"<div style='font:13px Arial,sans-serif;color:#5b6573'>{len(d['stories'])} stories selected from {d.get('new_items', 0)} new items</div>"
            f"{link}{''.join(rows)}{link}</div></body></html>")


# ------------------------------------------------------------------ build
def start_month(cfg):
    return int((cfg.get("magazine") or {}).get("issue_start_month", 1))


def theme_order(cfg):
    return list(cfg["themes"].keys()) + ["General"]


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def export_rows(stories):
    for s in stories:
        yield {
            "Digest date": s["_digest"], "Issue window": s["_window"], "Theme": s["theme"],
            "Relevance (1-5)": s.get("relevance") or "", "Suggested use": s.get("use", ""),
            "Headline (English)": s.get("title_en") or s["title"],
            "Original headline": s["title"] if s.get("title_en") else "",
            "Magazine angle": s.get("angle", ""), "Source": s["source"],
            "Google News edition": COUNTRIES.get(s.get("region", ""), s.get("region", "")),
            "Published": (s.get("published") or "")[:10], "Link": s["link"],
            "Keywords": ", ".join(s.get("keywords", [])),
        }


def build(cfg):
    use_list = USES
    digests = load_digests()
    sm = start_month(cfg)
    today_key = issue_window(dt.date.today().isoformat(), sm)["key"]

    # group digests into issue windows (newest first)
    windows, by_key = [], {}
    for d in digests:
        win = issue_window(d["date"], sm)
        if win["key"] not in by_key:
            by_key[win["key"]] = {"win": win, "digests": [], "stories": []}
            windows.append(by_key[win["key"]])
        w = by_key[win["key"]]
        w["digests"].append(d)
        for s in d["stories"]:
            w["stories"].append(dict(s, _digest=d["date"], _window=win["key"]))

    # fresh output folder (the archive itself lives in data/digests/)
    for sub in ("digests", "issues", "exports", "assets"):
        shutil.rmtree(DOCS / sub, ignore_errors=True)
    shutil.copytree(ASSETS, DOCS / "assets")
    (DOCS / "exports").mkdir()
    write(DOCS / ".nojekyll", "")

    dates = [d["date"] for d in digests]
    for i, d in enumerate(digests):
        older = dates[i + 1] if i + 1 < len(dates) else None
        newer = dates[i - 1] if i > 0 else None
        title = f"Digest {nice_date(d['date'])}"
        write(DOCS / "digests" / f"{d['date']}.html",
              page(cfg, title, digest_body(d, cfg, "../", use_list, older, newer), "../", "archive"))

    if digests:
        latest = digests[0]
        body = digest_body(latest, cfg, "", use_list, dates[1] if len(dates) > 1 else None, None, latest=True)
    else:
        latest = None
        body = ("<div class='page-head'><p class='eyebrow'>Latest digest</p><h1>Welcome</h1>"
                "<p class='lede'>The first digest will appear here after the first scan. Scans run automatically "
                "every morning; to run one now open the repository's <b>Actions</b> tab, choose "
                "<b>Geotechnical news scan</b> and press <b>Run workflow</b>.</p></div>")
    write(DOCS / "index.html", page(cfg, "Latest digest", body, "", "latest"))

    for w in windows:
        key = w["win"]["key"]
        write(DOCS / "issues" / f"{key}.html",
              page(cfg, f"{w['win']['label']} issue window",
                   issue_body(w["win"], w["stories"], w["digests"], cfg, use_list, key == today_key), "../", "archive"))
        with open(DOCS / "exports" / f"{key}.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(export_rows(sorted(w["stories"], key=lambda s: (s["theme"], -s["rank"]))))
        compact = [{"d": s["_digest"], "w": key, "t": s["title"], "te": s.get("title_en", ""), "l": s["link"],
                    "s": s["source"], "c": COUNTRIES.get(s.get("region", ""), s.get("region", "")),
                    "p": (s.get("published") or "")[:10], "th": s["theme"], "r": s.get("relevance") or 0,
                    "u": s.get("use", ""), "a": s.get("angle", ""), "k": s.get("keywords", []),
                    "x": s.get("summary", "")[:200] if not s.get("angle") else "", "rk": s["rank"]}
                   for s in w["stories"]]
        write(DOCS / "exports" / f"{key}.json", json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
    write(DOCS / "exports" / "index.json",
          json.dumps([w["win"] | {"stories": len(w["stories"])} for w in windows], ensure_ascii=False))

    write(DOCS / "archive.html", page(cfg, "Archive", archive_body(windows, cfg, today_key), "", "archive"))
    write(DOCS / "search.html", page(cfg, "Search the archive", search_body(cfg, use_list, windows), "", "search"))
    write(DOCS / "about.html", page(cfg, "Method & sources", about_body(cfg, latest), "", "about"))


if __name__ == "__main__":
    config = Path(os.environ.get("SCANNER_CONFIG", ROOT / "config.yaml"))
    build(yaml.safe_load(config.read_text(encoding="utf-8")))
    print(f"Site rebuilt in {DOCS}")
