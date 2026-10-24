#!/usr/bin/env python3
"""
Builds the website in docs/ from the saved digests in data/digests/ (and the
issue briefs in data/briefs/, written by brief.py).

The digests (one JSON file per day) are the permanent archive; everything in
docs/ is regenerated from them on every run, so the design can be changed and
the whole site rebuilt at any time with:   python site_builder.py
"""
import csv
import datetime as dt
import html
import json
import math
import os
import re
import shutil
import traceback
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

import exports
import report

ROOT = Path(__file__).resolve().parent
DIGESTS = ROOT / "data" / "digests"
BRIEFS = ROOT / "data" / "briefs"
CHANGELOG = ROOT / "data" / "changelog.yaml"
DOCS = ROOT / "docs"
ASSETS = ROOT / "assets"
esc = html.escape

USES = ["News brief", "Feature lead", "Academia-to-Industry topic", "Regional insight", "Watch only"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
COUNTRIES = {
    "GB": "United Kingdom", "US": "United States", "IN": "India", "AU": "Australia",
    "ZA": "South Africa", "SG": "Singapore", "AE": "United Arab Emirates", "FR": "France",
    "SN": "Senegal", "EG": "Egypt", "ES": "Spain", "MX": "Mexico", "BR": "Brazil",
    "DE": "Germany", "IT": "Italy", "TR": "Türkiye", "ID": "Indonesia", "CN": "China",
    "JP": "Japan", "VN": "Vietnam", "IR": "Iran", "KR": "South Korea", "RU": "Russia",
    "PL": "Poland", "CO": "Colombia", "CL": "Chile", "PE": "Peru", "AR": "Argentina",
}
CSV_FIELDS = ["Digest date", "Issue window", "Theme", "Relevance (1-5)", "Suggested use",
              "Headline (English)", "Original headline", "Magazine angle", "Source", "Country", "Place",
              "Google News edition", "Published", "Developing story", "Link", "Keywords"]

# Colour and icon for each magazine theme (themes added later in config.yaml
# take the spare colours in turn).
THEME_STYLE = {
    "Sustainability & the Energy Transition": ("#1f9d63", "leaf"),
    "Digital Geotechnics": ("#6b4fd6", "chip"),
    "Hazards & Resilience": ("#e04f2c", "alert"),
    "Ground Improvement & Innovation": ("#d38b00", "layers"),
    "Infrastructure & the Underground City": ("#2563d6", "tunnel"),
    "Offshore, Coasts & Water": ("#0b97a5", "wave"),
    "Characterisation & Modelling": ("#c23d7b", "chart"),
    "Geotechnics & Society": ("#8a5a2b", "people"),
    "General": ("#64748b", "dot"),
}
SPARE_COLORS = ["#0f766e", "#b45309", "#7c3aed", "#be123c", "#15803d", "#1d4ed8"]
ICONS = {
    "leaf": "<path d='M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.5 19 2c1 2 2 4.2 2 8 0 5.5-4.8 10-10 10Z'/><path d='M2 21c0-3 1.9-5.4 5.1-6C9.5 14.5 12 13 13 12'/>",
    "chip": "<rect x='5' y='5' width='14' height='14' rx='2'/><rect x='9' y='9' width='6' height='6'/><path d='M9 2v3M15 2v3M9 19v3M15 19v3M19 9h3M19 15h3M2 9h3M2 15h3'/>",
    "alert": "<path d='M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z'/><path d='M12 9v4M12 17h.01'/>",
    "layers": "<path d='m12 2 10 5-10 5L2 7l10-5z'/><path d='m2 17 10 5 10-5'/><path d='m2 12 10 5 10-5'/>",
    "tunnel": "<path d='M3 21V11a9 9 0 0 1 18 0v10'/><path d='M8 21v-8a4 4 0 0 1 8 0v8'/><path d='M1 21h22'/>",
    "wave": "<path d='M2 7c2 0 2 2 4 2s2-2 4-2 2 2 4 2 2-2 4-2 2 2 4 2'/><path d='M2 13c2 0 2 2 4 2s2-2 4-2 2 2 4 2 2-2 4-2 2 2 4 2'/><path d='M2 19c2 0 2 2 4 2s2-2 4-2 2 2 4 2 2-2 4-2 2 2 4 2'/>",
    "chart": "<path d='M3 3v18h18'/><path d='m7 15 4-4 3 3 6-7'/>",
    "people": "<circle cx='9' cy='7' r='4'/><path d='M2 21v-2a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2'/><path d='M16 3.1a4 4 0 0 1 0 7.8M22 21v-2a4 4 0 0 0-3-3.9'/>",
    "dot": "<circle cx='12' cy='12' r='5'/>",
    "scan": "<path d='M21 12a9 9 0 1 1-2.6-6.4L21 8'/><path d='M21 3v5h-5'/>",
    "gear": "<circle cx='12' cy='12' r='3'/><path d='M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z'/>",
    "download": "<path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/><path d='m7 10 5 5 5-5M12 15V3'/>",
    "sheet": "<rect x='3' y='3' width='18' height='18' rx='2'/><path d='M3 9h18M3 15h18M9 3v18'/>",
    "doc": "<path d='M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z'/><path d='M14 2v6h6M8 13h8M8 17h6'/>",
    "spark": "<path d='M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z'/><path d='M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9z'/>",
    "clip": "<path d='m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5'/>",
    "send": "<path d='m22 2-7 20-4-9-9-4z'/><path d='M22 2 11 13'/>",
    "print": "<path d='M6 9V2h12v7'/><rect x='6' y='14' width='12' height='8'/><path d='M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2'/>",
    "search": "<circle cx='11' cy='11' r='7'/><path d='m21 21-4.3-4.3'/>",
    "book": "<path d='M4 19.5A2.5 2.5 0 0 1 6.5 17H20'/><path d='M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z'/>",
    "pin": "<path d='M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z'/><circle cx='12' cy='10' r='3'/>",
    "globe": "<circle cx='12' cy='12' r='10'/><path d='M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z'/>",
}
FAVICON = (ASSETS / "favicon.svg").read_text(encoding="utf-8") if (ASSETS / "favicon.svg").exists() else ""


# ------------------------------------------------------------------ data
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def safe_url(url):
    """Only web links are published; anything else (javascript:, data:, ...) becomes '#'."""
    url = str(url or "").strip()
    return url if re.match(r"https?://", url, re.I) else "#"


def tidy(story):
    """Feed text is untrusted: strip control characters (they break the Excel and Word files)
    and neutralise non-web links before anything is built from it."""
    for k, v in story.items():
        if isinstance(v, str):
            story[k] = CONTROL_CHARS.sub("", v)
        elif isinstance(v, list):
            story[k] = [CONTROL_CHARS.sub("", x) if isinstance(x, str) else x for x in v]
    story["link"] = safe_url(story.get("link"))
    return story


def load_digests():
    out = [json.loads(p.read_text(encoding="utf-8")) for p in DIGESTS.glob("*.json")]
    for d in out:
        d["stories"] = [tidy(s) for s in d.get("stories", [])]
        d["papers"] = [tidy(p) for p in d.get("papers", [])]
    return sorted(out, key=lambda d: d["date"], reverse=True)


WINDOW_KEY = re.compile(r"^\d{4}-Q[1-4]$")


def tidy_all(value, key=""):
    """tidy() for nested data: every string cleaned, every "link" a web link or '#'."""
    if isinstance(value, dict):
        return {k: tidy_all(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [tidy_all(v) for v in value]
    if isinstance(value, str):
        return safe_url(value) if key == "link" else CONTROL_CHARS.sub("", value)
    return value


def load_briefs():
    """Issue briefs written by brief.py (data/briefs/<window key>.json), by window key.
    A file that cannot be read is reported and left out, so a hand edit gone wrong
    never stops the site from being built."""
    out = {}
    for p in sorted(BRIEFS.glob("*.json")):
        if not WINDOW_KEY.match(p.stem):
            continue
        try:
            b = tidy_all(json.loads(p.read_text(encoding="utf-8")))
            dt.datetime.fromisoformat(b["generated"])  # every page that shows the brief gives this date
            out[p.stem] = b
        except (ValueError, KeyError, TypeError) as ex:
            print(f"Issue brief {p.name} left out: it is not a readable brief ({type(ex).__name__}: {ex}).")
    return out


def issue_window(date_str, start_month=1):
    """Three-month window (matching the magazine's quarterly cycle) containing date."""
    d = dt.date.fromisoformat(date_str[:10])
    offset = (d.month - start_month) % 12
    first = (start_month - 1 + offset // 3 * 3) % 12 + 1
    year = d.year if first <= d.month else d.year - 1
    last = (first + 1) % 12 + 1
    last_year = year + (1 if last < first else 0)
    n = offset // 3 + 1
    cycle = d.year if d.month >= start_month else d.year - 1  # year the magazine's cycle began
    span = (f"{MONTHS[first - 1]} – {MONTHS[last - 1]} {year}" if last_year == year
            else f"{MONTHS[first - 1]} {year} – {MONTHS[last - 1]} {last_year}")
    return {"key": f"{cycle}-Q{n}", "label": f"Q{n} {cycle}", "span": span}


def window_range(key, start_month=1):
    """First and last day of the issue window with this key (e.g. 2026-Q4)."""
    cycle, n = int(key[:4]), int(key[-1])
    month = (start_month - 1 + (n - 1) * 3) % 12 + 1
    year = cycle if month >= start_month else cycle + 1
    after = dt.date(year + (month + 2) // 12, (month + 2) % 12 + 1, 1)  # first day of the next window
    return dt.date(year, month, 1), after - dt.timedelta(days=1)


def nice_date(iso, weekday=False):
    """'24 Oct 2026' ("" for anything that is not a date, e.g. a feed's mangled time)."""
    try:
        d = dt.date.fromisoformat(str(iso or "")[:10])
    except ValueError:
        return ""
    return f"{d:%A} {d.day} {d:%B %Y}" if weekday else f"{d.day} {d:%b %Y}"


def site_url(cfg):
    url = os.environ.get("SITE_URL") or (cfg.get("magazine") or {}).get("site_url", "")
    owner_repo = repository(cfg)
    if not url and "/" in owner_repo:
        owner, repo = owner_repo.split("/", 1)
        url = f"https://{owner.lower()}.github.io/{repo}/"
    return url.rstrip("/") + "/" if url else ""


def repository(cfg):
    return os.environ.get("GITHUB_REPOSITORY") or (cfg.get("magazine") or {}).get("repository", "")


def assistant_endpoint(cfg):
    """Web address of the assistant connector (assistant/bridge.gs deployed in Google Apps Script)."""
    return str((cfg.get("assistant") or {}).get("endpoint") or "").strip()


_theme_colors = {}


def theme_color(theme):
    if theme in THEME_STYLE:
        return THEME_STYLE[theme][0]
    if theme not in _theme_colors:
        _theme_colors[theme] = SPARE_COLORS[len(_theme_colors) % len(SPARE_COLORS)]
    return _theme_colors[theme]


def icon(name, cls="ico"):
    return (f"<svg class='{cls}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
            f"stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>{ICONS[name]}</svg>")


def theme_icon(theme):
    return icon(THEME_STYLE.get(theme, ("", "dot"))[1])


def feature(module, name):
    """A function of one of the feature modules (geomap, storylines, events, notify), or None when it
    is missing. They import this module, so they are imported here only when a page needs them."""
    try:
        return getattr(__import__(module), name, None)
    except ImportError:
        return None


def optional(module, name, *args, default=None, **kw):
    """module.name(*args), or default when the function is missing or fails: a fault in one feature
    leaves its part of a page out (with a message), never the page or the scan."""
    fn = feature(module, name)
    if not callable(fn):
        return default
    try:
        return fn(*args, **kw)
    except Exception as ex:
        print(f"{module}.{name} failed ({type(ex).__name__}: {ex}); that part of the page is left out.")
        return default


def country_label(code):
    """English name of an ISO country code: the world map's list (every code), else the short list above."""
    code = str(code or "").strip().upper()
    if not code:
        return ""
    fn = feature("geomap", "country_name")
    try:
        name = fn(code) if callable(fn) else ""
    except Exception:
        name = ""
    return name or COUNTRIES.get(code, code)


def place_text(s):
    """Where a story happened, as Claude read it: 'Moniquirá, Boyacá, Colombia' ("" when not located or global)."""
    place = " ".join(str(s.get("place") or "").split())
    country = country_label(s.get("country"))
    if country and country.lower() in place.lower():
        country = ""
    return ", ".join(x for x in (place, country) if x)


# ------------------------------------------------------------------ page parts
def page(cfg, title, body, root, active, description="", head=""):
    mag = (cfg.get("magazine") or {}).get("name", "ISSMGE Magazine")
    # (page, label, shorter label for narrow screens, key); style.css shows one of the two labels
    nav = [("index.html", "Latest", "", "latest"), ("archive.html", "Archive", "", "archive"),
           ("search.html", "Search", "", "search"), ("developing.html", "Developing stories", "Developing", "developing"),
           ("map.html", "World map", "Map", "map"), ("events.html", "Events", "", "events"),
           ("trends.html", "Trends", "", "trends"), ("assistant.html", "AI assistant", "Assistant", "assistant"),
           ("about.html", "Method & sources", "Method", "about")]
    current = " class='active' aria-current='page'"
    links = "".join(f"<a href='{root}{href}'{current if key == active else ''}>"
                    + (f"<span class='nav-l'>{esc(label)}</span><span class='nav-s'>{esc(short)}</span>" if short else esc(label))
                    + "</a>" for href, label, short, key in nav)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} · Geotechnical News Desk</title>
<meta name="description" content="{esc(description or 'Geotechnical news digest for the ' + mag)}">
<meta name="theme-color" content="#16324f">
<link rel="icon" href="{root}assets/favicon.svg" type="image/svg+xml">
<link rel="icon" href="{root}assets/favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="{root}assets/apple-touch-icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{root}assets/style.css">{head}
</head><body data-root="{root}" data-repo="{esc(repository(cfg))}" data-assistant="{esc(assistant_endpoint(cfg))}">
<header class="masthead"><div class="wrap masthead-inner">
<a class="brand" href="{root}index.html"><span class="brand-mark" aria-hidden="true">{FAVICON}</span>
<span><span class="brand-name">Geotechnical News Desk</span><span class="brand-sub">{esc(mag)} · editorial monitoring</span></span></a>
<nav class="nav" aria-label="Main">{links}</nav>
<div class="mast-actions"><button type="button" class="scan-btn" id="scan-btn" title="Start a new scan on GitHub">{icon('scan')}<span>Scan now</span></button></div>
</div></header>
<main class="wrap">{body}</main>
<footer class="foot"><div class="wrap foot-inner"><span>Headlines link to the original publishers. Treat every story as a lead and verify with the primary source before publishing.
Ratings, themes and angles are machine-assisted suggestions for the editorial team.</span>
<a href="{root}reports/site-report.docx" download>{icon('doc')} Website report (Word)</a></div></footer>
<div id="toast" class="toast" role="status" hidden></div>
<script src="{root}assets/app.js"></script>
</body></html>"""


def rating(s):
    rel = s.get("relevance") or 0
    if not rel:
        return f"<span class='rel rel-kw' title='Not AI-rated; ranked by keyword score'>Score {s.get('score', 0)}</span>"
    return f"<span class='rel rel-{rel}' title='Geotechnical relevance: {rel} of 5'>{'<i></i>' * 5}<b>{rel}/5</b></span>"


def story_card(s, show_theme=False, root=None):
    shown = s.get("title_en") or s["title"]
    when = nice_date(s.get("published") or s.get("_digest", ""))
    region = COUNTRIES.get(s.get("region", ""), s.get("region", ""))
    where = place_text(s)  # where it happened (Claude), which the Google News edition is not
    sl = s.get("_storyline")  # set by storylines.annotate() when the story belongs to a developing story
    search_text = " ".join([shown, s["title"], s.get("angle", ""), s["source"], region, where,
                            " ".join(s.get("keywords", [])), sl["title"] if sl else ""]).lower()
    meta = [f"<span class='src'>{esc(s['source'])}</span>"]
    if when:
        meta.append(f"<time>{esc(when)}</time>")
    if where:
        meta.append(f"<span class='loc'>{icon('pin')}{esc(where)}</span>")
    if region and not (s.get("region") and s.get("region") == s.get("country")):  # "Colombia · Colombia edition" says it twice
        meta.append(f"<span>{esc(region)} edition</span>")
    parts = [f"<article class='story' style='--tc:{theme_color(s['theme'])}' data-rel='{s.get('relevance') or 0}' "
             f"data-use='{esc(s.get('use', ''))}' data-text='{esc(search_text)}'"
             + (f" data-sl='{esc(sl['id'])}'" if sl else "") + ">",
             "<div class='story-top'>",
             f"<a class='story-title' href='{esc(s['link'])}' target='_blank' rel='noopener' dir='auto'>{esc(shown)}</a>",
             rating(s), "</div>"]
    if s.get("title_en"):
        parts.append(f"<div class='orig' dir='auto'>Original: {esc(s['title'])}</div>")
    if s.get("angle"):
        parts.append(f"<p class='angle'><span>Magazine angle</span>{esc(s['angle'])}</p>")
    elif s.get("summary"):
        parts.append(f"<p class='summary'>{esc(s['summary'][:260])}…</p>")
    parts.append("<div class='story-meta'>")
    if sl:
        # "Developing story · 4 reports", and for a follow-up the stage it reports. Cards appear on pages at the
        # top of the site and one folder down (digests/, issues/): without a root both links are written and
        # style.css shows the one that fits the page (body data-root), so every existing call keeps working.
        label = f"Developing story · {sl['size']} reports" + (f" · {sl['stage']}" if s.get("storyline") == sl["id"] else "")
        for r, cls in ([(root, "")] if root is not None else [("", " sl-top"), ("../", " sl-up")]):
            parts.append(f"<a class='sl-chip{cls}' href='{r}developing.html#{esc(sl['id'])}' "
                         f"title='{esc(sl['title'])}'>{esc(label)}</a>")
    if s.get("use"):
        slug_ = s["use"].split()[0].lower().strip("-")
        parts.append(f"<span class='use use-{esc(slug_)}'>{esc(s['use'])}</span>")
    if show_theme:
        parts.append(f"<span class='theme-tag'>{theme_icon(s['theme'])}{esc(s['theme'])}</span>")
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


def filtered(uses, sections):
    """The filter bar and the story sections it filters, in one box: the sticky bar ends with the stories,
    so it does not cover New research or the rest of the page."""
    return f"<div class='filter-scope'>{filter_bar(uses)}{sections}</div>"


def theme_sections(stories, order=None, show_theme=False):
    by_theme = {}
    for s in stories:
        by_theme.setdefault(s["theme"], []).append(s)
    if order is None:  # strongest theme first
        order = sorted(by_theme, key=lambda t: (-max(i["rank"] for i in by_theme[t]), t))
    toc = "".join(f"<a href='#{slug(t)}' style='--tc:{theme_color(t)}'>{theme_icon(t)}{esc(t)} <b>{len(by_theme[t])}</b></a>"
                  for t in order if t in by_theme)
    out = [f"<nav class='theme-toc' aria-label='Themes'>{toc}</nav>"]
    for t in order:
        if t not in by_theme:
            continue
        items = sorted(by_theme[t], key=lambda s: (-(s.get("relevance") or 0), -s["rank"]))
        out.append(f"<section class='theme-section' id='{slug(t)}' style='--tc:{theme_color(t)}'>"
                   f"<h2><span class='ticon'>{theme_icon(t)}</span>{esc(t)} <span class='count'>{len(items)}</span></h2>")
        out += [story_card(s, show_theme) for s in items]
        out.append("</section>")
    return "".join(out)


A2I = "Academia-to-Industry topic"


def doi_of(link):
    """The DOI in a https://doi.org/... link ('' for other links)."""
    return unquote(link.split("doi.org/", 1)[1]) if "doi.org/" in link else ""


def paper_rank(p):
    """Claude's rating for practice first, then the number of keyword concepts."""
    return (p.get("relevance") or 0) * 100 + len(p.get("keywords", []))


def paper_card(p):
    rel = p.get("relevance") or 0
    rating_ = (f"<span class='rel rel-{rel}' title='Use in practice: {rel} of 5'>{'<i></i>' * 5}<b>{rel}/5</b></span>"
               if rel else "<span class='rel rel-kw' title='Not AI-rated; ranked by keyword score'>Not rated</span>")
    parts = [f"<article class='story paper' style='--tc:{theme_color(p['theme'])}'>",
             "<div class='story-top'>",
             f"<a class='story-title' href='{esc(p['link'])}' target='_blank' rel='noopener' dir='auto'>{esc(p['title'])}</a>",
             rating_, "</div>"]
    if p.get("authors"):
        parts.append(f"<div class='orig' dir='auto'>{esc(p['authors'])}</div>")
    if p.get("angle"):
        parts.append(f"<p class='angle'><span>Why it matters in practice</span>{esc(p['angle'])}</p>")
    elif p.get("abstract"):
        parts.append(f"<p class='summary'>{esc(p['abstract'][:300])}…</p>")
    meta = [f"<span class='src'>{esc(p.get('journal', ''))}</span>"]
    if p.get("published"):
        meta.append(f"<time>{esc(nice_date(p['published']))}</time>")
    doi = doi_of(p["link"])
    if doi:
        meta.append(f"<a href='{esc(p['link'])}' target='_blank' rel='noopener'>doi:{esc(doi)}</a>")
    parts.append(f"<div class='story-meta'><span class='use use-academia'>Academia-to-Industry</span>"
                 f"<span class='theme-tag'>{theme_icon(p['theme'])}{esc(p['theme'])}</span>" + " · ".join(meta) + "</div>")
    if p.get("keywords"):
        parts.append("<div class='kw'>" + "".join(f"<span>{esc(k)}</span>" for k in p["keywords"][:5]) + "</div>")
    parts.append("</article>")
    return "".join(parts)


def research_section(papers, hint, limit=None):
    """'New research': papers best rated for practice first, then newest. Kept
    outside the theme sections, so the story filters leave it alone."""
    if not papers:
        return ""
    ordered = sorted(papers, key=lambda p: p.get("published") or "", reverse=True)
    ordered.sort(key=lambda p: -(p.get("relevance") or 0))
    shown = ordered[:limit] if limit else ordered
    return (f"<section class='research' id='research'><h2 class='section-h'>New research "
            f"<span class='h1-sub'>{len(papers)} {'paper' if len(papers) == 1 else 'papers'}</span></h2>"
            f"<p class='hint'>{hint}</p>" + "".join(paper_card(p) for p in shown) + "</section>")


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def stat(value, label):
    return f"<div class='stat'><b>{value}</b><span>{esc(label)}</span></div>"


def hero(eyebrow, title, lede="", stats="", extra="", small=False):
    return (f"<section class='hero{' hero-sm' if small else ''}'><div class='hero-inner'>"
            f"<p class='eyebrow'>{eyebrow}</p><h1>{title}</h1>"
            + (f"<p class='lede'>{lede}</p>" if lede else "")
            + (f"<div class='stats'>{stats}</div>" if stats else "") + extra + "</div></section>")


def theme_strip(stories, order):
    """Horizontal stacked bar of stories per theme."""
    n = len(stories) or 1
    counts = {}
    for s in stories:
        counts[s["theme"]] = counts.get(s["theme"], 0) + 1
    segs = "".join(f"<i style='--tc:{theme_color(t)};flex:{counts[t]}' title='{esc(t)}: {counts[t]}'></i>"
                   for t in order if t in counts)
    return f"<div class='strip' aria-hidden='true'>{segs}</div>" if stories else ""


# ------------------------------------------------------------------ pages
def digest_body(d, cfg, root, uses, prev_d=None, next_d=None, latest=False, brief=None, side="", week=None):
    """A daily digest page. On the Latest page, side is the column beside the news (this week, upcoming
    events and deadlines, developing stories) and week the {"key", "label"} of the week's summary page."""
    win = issue_window(d["date"], start_month(cfg))
    stories, papers = d["stories"], d.get("papers", [])
    themes = len({s["theme"] for s in stories})
    eyebrow = (f"{'Latest digest' if latest else 'Daily digest'} · "
               f"<a href='{root}issues/{win['key']}.html'>{win['label']} issue window</a>"
               + (f" · <a href='{root}weekly/{week['key']}.html'>{esc(week['label'])} summary</a>" if week else ""))
    stats = (stat(len(stories), "stories selected") + stat(d.get("new_items", 0), "new items scanned")
             + stat(themes, "themes") + stat("AI" if d.get("ai_used") else "Keywords", "triage method"))
    if papers:
        stats += stat(len(papers), "new research papers")
    extra = theme_strip(stories, theme_order(cfg))
    head = [hero(eyebrow, esc(nice_date(d["date"], weekday=True)), stats=stats, extra=extra)]
    if latest:
        head.append(f"<a class='callout' href='{root}issues/{win['key']}.html'>{icon('sheet')}<span><b>Building the "
                    f"{win['label']} issue?</b> Every story found {win['span']} is collected in one place, by theme, "
                    f"with an Excel workbook"
                    + (f" and the {'final' if brief.get('status') == 'final' else 'draft'} issue brief" if brief else "")
                    + " →</span></a>")
    news = [("<p class='empty'>No new geotechnical stories met the threshold in this period.</p>" if not stories
             else filtered(uses, theme_sections(stories))),
            research_section(papers, "Papers that geotechnical journals published in the last few days, for the "
                                     "Academia-to-Industry pages, best rated for use in practice first. Titles open "
                                     "the paper through its DOI.")]
    if side:  # beside the news on wide screens, after it on phones
        head.append(f"<div class='with-side'><div class='main-col'>{''.join(news)}</div>"
                    f"<div class='side-col'>{side}</div></div>")
    else:
        head += news
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


def count(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def brief_file(key):
    return f"briefs/{key}-issue-brief.docx"


def brief_card(win, b, cfg, current, root, opts):
    """Issue page card: the brief's overview and line-up headlines, its Word file and
    a button that starts the brief workflow on GitHub. opts come from brief.settings()."""
    key = win["key"]
    gen = (f"<button type='button' class='btn brief-btn' id='brief-btn' data-window='{key}' "
           f"data-current='{'1' if current else ''}'>{icon('spark')}<span>Generate / update brief</span></button>")
    if not b:
        if current:
            start = window_range(key, start_month(cfg))[1] - dt.timedelta(days=opts["days_before_end"] - 1)
            then = (f"refreshes the draft every {count(opts['refresh_days'], 'day')} "
                    "and writes the final brief the day after the quarter closes.")
            text = (f"Claude drafts it automatically in the last {opts['days_before_end']} days of the quarter "
                    f"(from {nice_date(start.isoformat())}), {then} You can also generate a draft now."
                    if dt.date.today() < start else
                    f"The draft is due: it appears with the next daily scan, or you can generate it now. Claude then {then}")
        else:
            text = ("The final brief is written by the first daily scan after a quarter closes. To write one for this "
                    f"window, press <b>Generate / update brief</b> and enter <code>{key}</code> on the GitHub page.")
        return (f"<section class='brief brief-none' id='brief'><div class='brief-head'><span class='brief-mark'>{icon('doc')}</span>"
                f"<div><p class='eyebrow'>Issue brief</p><h2>No brief yet for {win['label']}</h2><p class='brief-meta'>{text}</p>"
                f"</div></div><div class='actions'>{gen}</div></section>")
    final = b.get("status") == "final"
    papers = b.get("papers_considered") or 0
    meta = (f"Drafted by Claude on {esc(nice_date(b['generated']))} from "
            f"{count(b.get('stories_considered') or 0, 'story', 'stories')}"
            + (f" and {count(papers, 'paper')}" if papers else "") + " · check every story at its source before publishing")
    picks = []
    for entry in b.get("lineup") or []:
        chosen = [p for p in entry.get("picks") or [] if p.get("story")]
        if not chosen:
            continue
        s, t = chosen[0]["story"], entry.get("theme", "General")
        more = f" · +{len(chosen) - 1} more in the brief" if len(chosen) > 1 else ""
        picks.append(f"<li style='--tc:{theme_color(t)}'><span class='lt'>{theme_icon(t)}{esc(t)}</span>"
                     f"<a href='{esc(s.get('link', '#'))}' target='_blank' rel='noopener' dir='auto'>"
                     f"{esc(s.get('title_en') or s.get('title', ''))}</a>"
                     f"<span class='lf'>{esc(chosen[0].get('format', ''))} · {esc(s.get('source', ''))}{more}</span></li>")
    also = ", ".join(count(len(b.get(k) or []), one) for k, one in
                     (("feature_leads", "feature lead"), ("a2i_topics", "Academia-to-Industry topic"), ("gaps", "gap")))
    status = "final" if final else "draft"
    return (f"<section class='brief {status}' id='brief'><div class='brief-head'><span class='brief-mark'>{icon('doc')}</span>"
            f"<div><p class='eyebrow'>Issue brief <span class='badge {status}'>{status.title()}</span></p>"
            f"<h2>Proposed line-up for {win['label']}</h2><p class='brief-meta'>{meta}</p></div></div>"
            f"<p class='brief-overview'>{esc(b.get('overview', ''))}</p>"
            + (f"<ul class='lineup'>{''.join(picks)}</ul>" if picks else "")
            + f"<p class='brief-also'>Also in the Word file: {also}, a regional-balance check, a watch list"
            + (", the window's developing stories and the events and deadlines ahead." if "developing" in b else ".") + "</p>"
            f"<div class='actions'><a class='btn primary' href='{root}{brief_file(key)}' download>{icon('download')}"
            f"Issue brief (Word)</a>{gen}</div></section>")


# ------------------------------------------------------------------ the map, developing stories, events and weekly summaries on the main pages
WEEK = re.compile(r"^(\d{4})-W(\d{2})$")


def week_span(key):
    """'19–25 Oct 2026' for the ISO week 2026-W43 (as on the weekly summary pages)."""
    m = WEEK.match(key)
    mon = dt.date.fromisocalendar(int(m[1]), int(m[2]), 1)
    sun = mon + dt.timedelta(days=6)
    if mon.year != sun.year:
        return f"{mon.day} {MONTHS[mon.month - 1]} {mon.year} – {sun.day} {MONTHS[sun.month - 1]} {sun.year}"
    if mon.month != sun.month:
        return f"{mon.day} {MONTHS[mon.month - 1]} – {sun.day} {MONTHS[sun.month - 1]} {sun.year}"
    return f"{mon.day}–{sun.day} {MONTHS[sun.month - 1]} {sun.year}"


def weeks_of(digests):
    """The archive's ISO weeks, newest first, as the weekly summary pages (notify.py) list them:
    [{"key", "label", "span", "digests", "stories", "top", "sent"}]; [] without notify.py."""
    week_key = feature("notify", "week_key")
    if not callable(week_key):
        return []
    record = optional("notify", "load_record", default={}) or {}
    sent = record.get("weekly") if isinstance(record.get("weekly"), dict) else {}
    out, by_key = [], {}
    for d in digests:  # newest first
        try:
            key = week_key(d["date"])
        except (TypeError, ValueError):
            continue
        if not WEEK.match(str(key)):
            continue
        if key not in by_key:
            by_key[key] = {"key": key, "label": f"Week {int(key[-2:])}", "span": week_span(key), "digests": 0,
                           "ids": set(), "top": 0, "sent": str(sent.get(key) or "")}
            out.append(by_key[key])
        w = by_key[key]
        w["digests"] += 1
        for s in d["stories"]:
            if s["id"] not in w["ids"]:
                w["ids"].add(s["id"])
                w["top"] += s.get("relevance") == 5
    for w in out:
        w["stories"] = len(w.pop("ids"))
    return out


def report_stage(s, sl):
    """The stage a report of a developing story reached (its first report is the event itself)."""
    return (s.get("stage") or "Update") if s.get("storyline") == sl else (s.get("stage") or "Event")


def side_column(weeks, groups, cfg, today):
    """Beside the news on the Latest page: this week and its summary, the events calendar's next calls for
    papers and events, and the developing stories with a new report in the last 30 days."""
    parts = []
    if weeks:
        w, last = weeks[0], (weeks[1] if len(weeks) > 1 else None)
        running = WEEK.match(w["key"]) and dt.date.fromisocalendar(int(w["key"][:4]), int(w["key"][-2:]), 7) >= today
        links = [f"<li><a href='weekly/{w['key']}.html'>{'This week' if running else w['label']}’s summary →</a></li>"]
        if last:
            links.append(f"<li><a href='weekly/{last['key']}.html'>{last['label']} · {esc(last['span'])}</a>"
                         + (" <span class='wk-chip ok'>E-mailed</span>" if last["sent"] else "") + "</li>")
        links.append("<li><a href='weekly/index.html'>All weekly summaries</a></li>")
        parts.append(f"<section class='side-card'><p class='eyebrow'>{icon('book')}{'This week' if running else 'Latest week'}</p>"
                     f"<h2><a href='weekly/{w['key']}.html'>{w['label']}</a> <span>{esc(w['span'])}</span></h2>"
                     f"<p class='side-figs'>{count(w['stories'], 'story', 'stories')} · {w['top']} rated 5 / 5 · "
                     f"{count(w['digests'], 'daily digest')}{' so far' if running else ''}</p>"
                     f"<ul class='side-links'>{''.join(links)}</ul></section>")
    parts.append(optional("events", "sidebar", cfg, "", today, limit=6, default="") or "")
    since = (today - dt.timedelta(days=30)).isoformat()
    recent = [g for g in groups if g["last"] >= since][:4]
    if recent:
        items = []
        for g in recent:
            s = g["stories"][-1]
            where = ", ".join(x for x in (g.get("place"), country_label(g.get("country"))) if x)
            items.append(f"<li style='--tc:{theme_color(g['theme'])}'><a href='developing.html#{esc(g['id'])}' dir='auto'>"
                         f"{esc(g['title'])}</a><small>" + " · ".join(esc(x) for x in (
                             where, count(len(g["stories"]), "report"),
                             f"{report_stage(s, g['id'])}, {nice_date(g['last'])}") if x) + "</small></li>")
        parts.append(f"<section class='side-card'><p class='eyebrow'>{icon('layers')}Developing stories</p>"
                     f"<ul class='side-dev'>{''.join(items)}</ul><a class='side-more' href='developing.html'>"
                     "All developing stories →</a></section>")
    return "".join(p for p in parts if p)


def coverage_line(stories, cfg, root, key):
    """Issue pages: stories per ISSMGE region and how many member-society countries have stories, linking to
    the world map of the window."""
    rows = optional("geomap", "coverage", stories, cfg)
    if not rows:
        return ""
    located = sum(r["stories"] for r in rows)
    members, covered = sum(r["members"] for r in rows), sum(r["members_covered"] for r in rows)
    waiting = sum(1 for s in stories if "country" not in s)
    if located:
        note = f"{covered} of {members} member-society countries have stories in this window"
    else:
        note = "No story in this window has a location yet"
    if waiting:
        note += f"; {count(waiting, 'story', 'stories')} still to be located after the next scan"
    regions = "".join(f"<li><span>{esc(r['region'])}</span><b>{r['stories']:,}</b></li>" for r in rows)
    return (f"<div class='cov-line'><h2>{icon('globe')}Regional coverage</h2><ul class='cov-regions'>{regions}</ul>"
            f"<p>{esc(note)}. <a href='{root}map.html#{esc(key)}'>The gaps on the world map →</a></p></div>")


def developing_section(groups, first, last, root, limit=6):
    """Issue pages: developing stories with a report in the window, the most recently active first."""
    lo, hi = first.isoformat(), last.isoformat()
    active = [(g, [s for s in g["stories"] if lo <= str(s.get("_digest", ""))[:10] <= hi]) for g in groups]
    active = [(g, inside) for g, inside in active if inside]
    if not active:
        return ""
    items = []
    for g, inside in active[:limit]:
        s = inside[-1]
        where = ", ".join(x for x in (g.get("place"), country_label(g.get("country"))) if x)
        meta = [esc(where), f"{count(len(g['stories']), 'report')}, <b>{len(inside)} in this window</b>",
                f"latest: {esc(report_stage(s, g['id']))} ({esc(nice_date(s.get('_date') or s['_digest']))})"]
        items.append(f"<li style='--tc:{theme_color(g['theme'])}'><a href='{root}developing.html#{esc(g['id'])}' dir='auto'>"
                     f"{esc(g['title'])}</a><span class='wk-meta'>{' · '.join(x for x in meta if x)}</span></li>")
    more = len(active) - limit
    return ("<section class='issue-dev' id='developing'><h2 class='section-h'>Developing stories "
            f"<span class='h1-sub'>{len(active)}</span></h2><p class='hint'>Events, projects and sites reported more than "
            "once, with a report in this window: the follow-ups (inquiries, repairs, court cases) often make the best "
            "features.</p>"
            f"<ul class='wk-list'>{''.join(items)}</ul>"
            + (f"<p class='hint wk-more'>…and {count(more, 'more developing story', 'more developing stories')} on the "
               f"<a href='{root}developing.html'>Developing stories</a> page.</p>" if more > 0 else "") + "</section>")


def weeks_section(weeks, cfg, root, limit=3):
    """Archive page: the latest weekly summaries, linking to all of them."""
    if not weeks:
        return ""
    opts = optional("notify", "settings", cfg, default={}) or {}
    day = opts.get("weekday", "Monday") if isinstance(opts, dict) else "Monday"
    cards = "".join(
        f"<a class='wk-card' href='{root}weekly/{w['key']}.html'><span class='wk-card-head'><span><b>{w['label']}</b>"
        f"<span class='wk-span'>{esc(w['span'])}</span></span>" + ("<span class='wk-chip ok'>E-mailed</span>" if w["sent"] else "")
        + f"</span><span class='wk-figs'>{count(w['stories'], 'story', 'stories')} · {w['top']} rated 5 / 5 · "
        f"{count(w['digests'], 'digest')}</span></a>" for w in weeks[:limit])
    return (f"<section class='weeks'><div class='section-row'><h2 class='section-h'>Weekly summaries</h2>"
            f"<a href='{root}weekly/index.html'>All {count(len(weeks), 'week')} →</a></div>"
            f"<p class='hint'>The summary the news desk e-mails to the editorial team every {esc(day)}: top stories, "
            "developing stories, regional coverage, events coming up and new research.</p>"
            f"<div class='wk-index'>{cards}</div></section>")


def issue_body(win, stories, digests, cfg, uses, current, brief=None, brief_opts=None, papers=(), extras=None):
    root = "../"
    order = theme_order(cfg)
    summ = window_summary(stories)
    counts = {}
    for s in stories:
        c = counts.setdefault(s["theme"], {"n": 0, "r5": 0, "r4": 0, "fl": 0, "a2i": 0, "papers": 0})
        c["n"] += 1
        c["r5"] += s.get("relevance") == 5
        c["r4"] += s.get("relevance") == 4
        c["fl"] += s.get("use") == "Feature lead"
        c["a2i"] += s.get("use") == "Academia-to-Industry topic"
    for p in papers:
        counts.setdefault(p["theme"], {"n": 0, "r5": 0, "r4": 0, "fl": 0, "a2i": 0, "papers": 0})["papers"] += 1
    peak = max((c["n"] for c in counts.values()), default=1) or 1
    name = {t: f"<span class='ticon sm'>{theme_icon(t)}</span>{esc(t)}" for t in counts}
    rows = "".join(
        f"<tr style='--tc:{theme_color(t)}'><th scope='row'>"
        + (f"<a href='#{slug(t)}'>{name[t]}</a>" if c["n"] else f"<span class='th-name'>{name[t]}</span>")  # papers only: no section
        + f"</th><td><span class='cellbar'><i style='width:{c['n'] / peak * 100:.0f}%'></i></span><b>{c['n']}</b></td><td>{c['r5']}</td>"
        f"<td>{c['r4']}</td><td>{c['fl']}</td><td>{c['a2i']}</td>" + (f"<td>{c['papers']}</td>" if papers else "") + "</tr>"
        for t in order if (c := counts.get(t)))
    best = sorted((s for s in stories if s.get("relevance") == 5 or s.get("use") == "Feature lead"),
                  key=lambda s: -s["rank"])[:12]
    dlist = "".join(f"<li><a href='{root}digests/{d['date']}.html'>{esc(nice_date(d['date']))}</a>"
                    f"<span>{len(d['stories'])} stories</span></li>" for d in digests)
    eyebrow = (f"<a href='{root}archive.html'>Archive</a> · Issue window"
               + (" · <span class='badge'>In progress</span>" if current else ""))
    stats = (stat(summ["stories"], "stories") + stat(len(digests), "daily digests")
             + stat(summ["top"], "rated 5 / 5") + stat(summ["features"], "feature leads"))
    if papers:
        stats += stat(len(papers), "research papers")
    journals = len({p.get("journal") for p in papers})
    research = research_section(
        papers, f"{len(papers)} {'paper' if len(papers) == 1 else 'papers'} from {journals} "
                f"{'journal' if journals == 1 else 'journals'} in this window, for the Academia-to-Industry pages. "
                f"{'The 24 best rated for use in practice are shown; all' if len(papers) > 24 else 'All'} of them are "
                "in the Excel workbook (Research sheet) and on the Search page.", limit=24)
    actions = (f"<div class='actions'><a class='btn primary' href='{root}exports/{win['key']}.xlsx' download>{icon('sheet')}Excel workbook</a>"
               f"<a class='btn light' href='{root}exports/{win['key']}.csv' download>{icon('download')}CSV</a>"
               f"<a class='btn light' href='{root}search.html?q_window={win['key']}'>{icon('search')}Search this window</a>"
               f"<button class='btn light' type='button' onclick='window.print()'>{icon('print')}Print / PDF</button></div>")
    body = [hero(eyebrow, f"{win['label']} <span class='h1-sub'>{esc(win['span'])}</span>",
                 "Every story selected by the daily scans in this three-month window, grouped by the magazine's "
                 "cross-cutting themes and ordered by geotechnical relevance.",
                 stats, theme_strip(stories, order) + actions)]
    if not stories:
        body.append("<p class='empty'>No stories yet in this window.</p>")
        return "".join(body) + research
    if brief_opts:
        body.append(brief_card(win, brief, cfg, current, root, brief_opts))
    body.append("<h2 class='section-h'>Theme overview</h2><div class='table-wrap'><table class='overview'>"
                "<thead><tr><th scope='col'>Theme</th><th scope='col'>Stories</th><th scope='col'>Rated 5</th>"
                "<th scope='col'>Rated 4</th><th scope='col'>Feature leads</th><th scope='col'>Academia-to-Industry</th>"
                + ("<th scope='col'>Research papers</th>" if papers else "") + "</tr></thead>"
                f"<tbody>{rows}</tbody></table></div>")
    extras = extras or {}
    body.append(extras.get("coverage", ""))
    if best:
        body.append("<h2 class='section-h'>Strongest leads</h2><p class='hint'>Stories rated 5 / 5 or suggested as feature leads.</p>"
                    "<div class='shortlist'>" + "".join(story_card(s, show_theme=True) for s in best) + "</div>")
    body.append(extras.get("developing", ""))
    body.append(extras.get("events", ""))
    body.append("<h2 class='section-h'>All stories by theme</h2>")
    body.append(filtered(uses, theme_sections(stories, order=order)))
    body.append(research)
    body.append(f"<h2 class='section-h'>Daily digests in this window</h2><ul class='digest-list'>{dlist}</ul>")
    return "".join(body)


def archive_body(windows, cfg, current_key, briefs=None, weeks=()):
    root = ""
    briefs = briefs or {}
    order = theme_order(cfg)
    if not windows:
        return hero("Archive", "All digests") + "<p class='empty'>The archive is empty. It fills automatically after the first scan.</p>"
    total = sum(len(w["stories"]) for w in windows)
    stats = (stat(len(windows), "issue windows") + stat(sum(len(w["digests"]) for w in windows), "daily digests")
             + stat(total, "stories archived"))
    actions = (f"<div class='actions'><a class='btn primary' href='{root}exports/geotech-news-archive.xlsx' download>"
               f"{icon('sheet')}Whole archive (Excel)</a><a class='btn light' href='{root}reports/site-report.docx' download>"
               f"{icon('doc')}Website report (Word)</a></div>")
    out = [hero("Archive", "All digests",
                "Every daily digest is kept permanently. They are grouped into three-month issue windows that follow "
                "the magazine's publication cycle, so each issue can be planned from one page and one workbook.",
                stats, actions), weeks_section(list(weeks), cfg, root)]
    if weeks:
        out.append("<h2 class='section-h'>Issue windows</h2>")
    for w in windows:
        win, stories, digests = w["win"], w["stories"], w["digests"]
        summ = window_summary(stories)
        counts = {}
        for s in stories:
            counts[s["theme"]] = counts.get(s["theme"], 0) + 1
        peak = max(counts.values(), default=1)
        bars = "".join(
            f"<li style='--tc:{theme_color(t)}'><span>{theme_icon(t)}{esc(t)}</span><i style='--w:{counts[t] / peak * 100:.0f}%'></i><b>{counts[t]}</b></li>"
            for t in order if t in counts)
        days = "".join(f"<a href='digests/{d['date']}.html'>{dt.date.fromisoformat(d['date']).day} "
                       f"{MONTHS[int(d['date'][5:7]) - 1]}<span>{len(d['stories'])}</span></a>" for d in digests)
        b = briefs.get(win["key"])
        if b:
            brief_link = (f"<a class='btn' href='{root}{brief_file(win['key'])}' download>{icon('doc')}Issue brief"
                          f"{'' if b.get('status') == 'final' else ' (draft)'}</a>")
        else:
            brief_link = (f"<a class='btn ghost' href='{root}issues/{win['key']}.html#brief' title='No brief yet: "
                          f"generate one on the issue page'>{icon('doc')}Issue brief</a>")
        out.append(
            f"<section class='window'><div class='window-head'><div><h2>{win['label']}"
            f"{' <span class=badge>In progress</span>' if win['key'] == current_key else ''}</h2>"
            f"<p>{esc(win['span'])} · {summ['stories']} stories · {len(digests)} digests · "
            f"{summ['top']} rated 5 / 5 · {summ['features']} feature leads"
            + (f" · {len(w['papers'])} research papers" if w.get("papers") else "") + "</p></div>"
            f"<div class='actions'><a class='btn primary' href='{root}issues/{win['key']}.html'>Open issue collection</a>"
            f"<a class='btn' href='{root}exports/{win['key']}.xlsx' download>{icon('sheet')}Excel</a>{brief_link}</div></div>"
            f"{theme_strip(stories, order)}"
            f"<div class='window-body'><ul class='bars'>{bars}</ul>"
            f"<div class='days'><h3>Daily digests</h3><div class='day-grid'>{days}</div></div></div></section>")
    return "".join(out)


def search_body(cfg, uses, windows):
    themes = "".join(f"<option>{esc(t)}</option>" for t in theme_order(cfg))
    uopts = "".join(f"<option>{esc(u)}</option>" for u in uses)
    wopts = "".join(f"<option value='{w['win']['key']}'>{w['win']['label']} ({esc(w['win']['span'])})</option>" for w in windows)
    return hero("Archive search", "Search every story",
                "Search across all archived digests. Combine filters, then export the result as a spreadsheet.", small=True) + f"""
<div id="search-app" class="toolbar search-tools">
<label class="field grow"><span>Search</span><input type="search" id="q" placeholder="e.g. liquefaction, Riyadh, monopile, TBM…" autofocus></label>
<label class="field"><span>Issue window</span><select id="q_window"><option value="">All windows</option>{wopts}</select></label>
<label class="field"><span>Theme</span><select id="q_theme"><option value="">All themes</option>{themes}</select></label>
<label class="field"><span>Suggested use</span><select id="q_use"><option value="">All uses</option>{uopts}</select></label>
<label class="field"><span>Minimum rating</span><select id="q_rel"><option value="0">Any</option><option value="3">3 / 5+</option><option value="4">4 / 5+</option><option value="5">5 / 5</option></select></label>
<label class="field"><span>Sort</span><select id="q_sort"><option value="rel">Relevance</option><option value="new">Newest first</option></select></label>
</div>
<div class="result-bar"><span id="result-count" aria-live="polite">Loading archive…</span>
<button class="btn" type="button" id="export">{icon('download')}Export results (CSV)</button></div>
<div id="results"></div><div class="more-wrap"><button class="btn" type="button" id="more" hidden>Show more</button></div>"""


def assistant_body(cfg):
    suggestions = ["What are the strongest feature leads in the current issue window?",
                   "Find stories about liquefaction or ground improvement in Asia",
                   "Which conferences and call-for-papers deadlines are coming up?",
                   "Which developing stories had new reports recently?",
                   "Suggest a line-up of 6 stories for the next issue, one per theme",
                   "Which regions are under-represented this quarter?"]
    chips = "".join(f"<button type='button' class='chip-btn' data-q='{esc(q)}'>{esc(q)}</button>" for q in suggestions)
    return hero(f"{icon('spark')} AI assistant", "Ask the news desk",
                "Ask questions about the archive, get story recommendations for an issue, or attach a PDF or Word "
                "document to discuss it alongside the news.", small=True) + f"""
<div class="chat" id="chat-app">
<div class="chat-log" id="chat-log" aria-live="polite">
<div class="msg bot welcome"><div class="bubble"><p><b>Hello!</b> I can search every archived story, compare themes, quarters and regions,
follow developing stories, look up conferences and call-for-papers deadlines in the events calendar, recommend stories and angles for
the magazine, and read PDF or Word files you attach — for example a call for papers or an article draft.</p>
<div class="chips">{chips}</div></div></div>
</div>
<div class="chat-files" id="chat-files"></div>
<form class="chat-input" id="chat-form">
<label class="attach" title="Attach PDF or Word documents">{icon('clip')}<input type="file" id="chat-file" accept=".pdf,.docx,.txt,.md" multiple hidden></label>
<textarea id="chat-text" rows="1" placeholder="Ask about the news, or attach a PDF / Word document…" aria-label="Message"></textarea>
<button class="btn primary send" type="submit">{icon('send')}<span>Send</span></button>
</form>
<div class="chat-foot"><span id="chat-status"></span><span class="chat-opts"><label>Model <select id="chat-model">
<option value="claude-opus-5-5">Claude Opus 5.5 — best answers</option>
<option value="claude-sonnet-5-5">Claude Sonnet 5.5 — faster</option>
<option value="claude-haiku-5-5">Claude Haiku 5.5 — fastest</option></select></label>
<button type="button" id="chat-new" class="linkbtn">New conversation</button></span></div>
</div>"""


def features_html(cfg):
    """Method & sources: how locations are read, follow-ups linked, events found and e-mail sent, with the
    numbers from config.yaml (each feature's defaults when its module or section is missing)."""
    def opts(module):
        o = optional(module, "settings", cfg, default={})
        return o if isinstance(o, dict) else {}

    m, sl, ev, al = opts("geomap"), opts("storylines"), opts("events"), opts("notify")
    regions = optional("geomap", "region_info", cfg, default=[]) or []
    checking = [r["name"] for r in regions if isinstance(r, dict) and r.get("to_check")]
    level = "5 / 5" if al.get("min_relevance", 5) >= 5 else f"{al.get('min_relevance')} / 5 or higher"
    calendars = ev.get("calendars") or []
    items = [
        ("#0b97a5", "globe", "World map: where stories happen",
         "During triage Claude reads the country each story is about and the town, region or site it names: where the "
         "event, project or site is, not the outlet's country and not the Google News edition that found it. A story "
         "about several countries, or a general market or research result, counts as global. Stories saved before "
         f"locations were read (or whose triage failed) are located after each scan, newest first, up to "
         f"{m.get('locate_per_run', 300)} at a time. The <a href='map.html'>World map</a> plots the stories by country "
         "and compares them with the member-society countries of ISSMGE's six regions, so regions and member societies "
         "with no stories stand out."
         + (f" The member lists for {' and '.join(checking)} are still being checked against issmge.org." if checking else "")),
        ("#e04f2c", "layers", "Developing stories: follow-ups linked to the event",
         f"Each scan, Claude compares the day's new stories with the archive of the last {sl.get('lookback_days', 365)} "
         "days and links a story to an earlier one only when both are about the same event, project or site (the same "
         "landslide, dam or tunnel in the same place, not merely a similar hazard in the same country), and names the "
         "stage it reports: the event, response and recovery, investigation and inquiry, repair and reconstruction, "
         "legal and policy, or an update. Without Claude, a cautious headline match links reports found within "
         f"{sl.get('heuristic_days', 30)} days. Story cards carry a <b>Developing story</b> chip that leads to the "
         "timeline on <a href='developing.html'>Developing stories</a>. A link is a lead: check it at the source."),
        ("#d38b00", "book", "Events calendar: conferences and calls for papers",
         "The editors keep their own list of events in <code>data/events.yaml</code>. Every "
         f"{count(ev.get('refresh_days', 7), 'day')} Claude reads {count(len(calendars), 'organiser calendar')} "
         "(ISSMGE, ITA-AITES, the ASCE Geo-Institute and others) with web search and web fetch and adds the conferences, "
         f"courses and call-for-papers deadlines it finds in the next {ev.get('months_ahead', 24)} months; the "
         "<b>Refresh calendar</b> button on the Events page starts a refresh at any time. Every event found must link "
         "to a page Claude actually read, and predatory conference series are left out. An editors' entry always wins "
         "over the same event found by the refresh. The <a href='events.html'>Events</a> page offers the whole calendar "
         "as a feed (<code>events.ics</code>) for Outlook, Google or Apple Calendar."),
        ("#6b4fd6", "send", "Alerts and the weekly summary (e-mail)",
         (f"After each scan, one e-mail lists any new story rated {level}. " if al.get("story_alerts", True) else "")
         + (f"Every {al.get('weekday', 'Monday')} morning the editorial team receives the summary of the week before: "
            "the top stories of each theme, developing stories, regional coverage, events and deadlines in the next "
            f"{al.get('events_days', 60)} days, and new research. " if al.get("weekly_summary", True) else "")
         + "E-mail goes out through the AI assistant's Google connector or a mail server, as set up in the README; "
           "nothing is sent twice. Each week's summary is also on the website: <a href='weekly/index.html'>Weekly "
           "summaries</a>, linked from the Archive."),
    ]
    lis = "".join(f"<li style='--tc:{c}'><b><span class='ticon sm'>{icon(ic)}</span>{esc(title)}</b><p>{text}</p></li>"
                  for c, ic, title, text in items)
    return f"<h2 class='section-h'>Map, developing stories, events and e-mail</h2><ul class='about-features'>{lis}</ul>"


def about_body(cfg, latest, brief_opts):
    feeds = cfg.get("feeds", [])
    g = cfg.get("google_news") or {}
    editions = len(g.get("editions") or [1])
    n_core, n_extra = len(g.get("core_queries", [])), len(g.get("extra_queries", []))
    n_foreign = sum(1 for q in g.get("extra_queries", []) if isinstance(q, dict) and q.get("language", "en") != "en")
    # languages other than English: of the searches and of the websites that name one (es-419 is Spanish)
    languages = {str(q.get("language")).split("-")[0] for q in [*g.get("extra_queries", []), *feeds]
                 if isinstance(q, dict) and q.get("language")} - {"en"}
    ml = cfg.get("multilingual_keywords") or {}
    n_ml = sum(len(v.get("terms", [])) for v in ml.values())
    ccfg = cfg.get("claude", {})
    rcfg = cfg.get("research") or {}
    journals = (rcfg.get("journals") or []) if rcfg.get("enabled") is not False else []
    jrows = "".join(f"<tr><td>{esc(j['name'])}</td><td>{esc(str(j['issn']))}</td></tr>" for j in journals)
    research_step = (f"<li><b>Research.</b> New papers from {len(journals)} geotechnical journals, read from Crossref's "
                     f"free index (papers registered in the last {rcfg.get('lookback_days', 4)} days, each shown once). "
                     f"They are scored and themed with the same keywords; Claude rates each 1–5 for its use in practice "
                     f"and writes one sentence on why it matters to practitioners. Up to {rcfg.get('max_papers', 20)} "
                     "papers per digest appear under <b>New research</b>, for the Academia-to-Industry pages.</li>"
                     if journals else "")
    jtable = (f"<h2 class='section-h'>Journals read for new research</h2><div class='table-wrap'><table class='overview'>"
              f"<thead><tr><th>Journal</th><th>ISSN</th></tr></thead><tbody>{jrows}</tbody></table></div>"
              if journals else "")
    themes = "".join(f"<li style='--tc:{theme_color(t)}'><b><span class='ticon sm'>{theme_icon(t)}</span>{esc(t)}</b>"
                     f"<span>{esc(', '.join(w))}</span></li>" for t, w in cfg["themes"].items() if w)
    rows = "".join(
        f"<tr><td>{esc(f['name'])}</td><td>{esc(urlparse(f['url']).netloc.replace('www.', ''))}</td>"
        f"<td>{'+' + str(f['boost']) if f.get('boost') else '—'}</td></tr>" for f in feeds)
    failed = ""
    if latest and latest.get("failures"):
        failed = ("<h2 class='section-h'>Sources that failed on the latest run</h2><ul class='plain'>"
                  + "".join(f"<li><b>{esc(n)}</b>: {esc(e)}</li>" for n, e in latest["failures"]) + "</ul>")
    stats = (stat(len(feeds), "websites read directly") + stat(n_core * editions + n_extra, "news searches")
             + stat(n_foreign, "non-English searches") + stat(len(cfg["keywords"]) + n_ml, "weighted keywords"))
    actions = (f"<div class='actions'><a class='btn primary' href='reports/site-report.docx' download>{icon('doc')}"
               "Website report (Word)</a></div>")
    return hero("Method & sources", "How the digest is made",
                "A scheduled scan reads specialist, institutional and trade sources plus worldwide news searches, "
                "filters them for geotechnical substance, and files the result under the magazine's eight themes.",
                stats, actions) + f"""
<div class="prose">
<h2 class="section-h">Each run</h2><ol class="steps">
<li><b>Collect.</b> {len(feeds)} websites and {n_core * editions + n_extra} Google News searches ({n_core} core searches in {editions} English editions, plus {n_extra} further searches including {n_foreign} in other languages). The scan runs every day at 05:00 Cairo time, and on demand: <b>Scan now</b> opens the scan's page on GitHub, where you press <b>Run workflow</b>; the website then follows the scan and tells you when the new digest is ready. Each run looks back {cfg.get('lookback_hours', 60)} hours; stories already shown are remembered for 45 days and never repeated.</li>
<li><b>Score and categorise.</b> Headlines and summaries are scored against {len(cfg['keywords'])} English keywords and {n_ml} terms in {len(languages)} other languages. Each foreign term counts as its English equivalent (for example <i>glissement de terrain</i>, <i>deslizamiento</i>, <i>longsor</i> and <i>انهيار أرضي</i> all count as “landslide”), so every story is filed under an English theme. Specialist sources earn bonus points, noise terms lose points, near-identical headlines are merged. A story needs {cfg.get('min_keyword_score', 3)} points to go forward.</li>
<li><b>Triage.</b> Up to {ccfg.get('max_candidates', 80)} candidates go to Claude, which rates each 1–5 for geotechnical substance (below {ccfg.get('min_relevance', 3)} is dropped), confirms the theme, suggests a use, writes a one-sentence magazine angle, translates non-English headlines, and reads where each story happened (the country and the town, region or site). Claude then checks whether any new story follows up an earlier one (see below).</li>
{research_step}
<li><b>Publish & archive.</b> Up to {cfg.get('max_items', 40)} stories per digest. Every digest is stored permanently, grouped into three-month issue windows, and exported to Excel.</li>
<li><b>Issue brief.</b> In the last {brief_opts['days_before_end']} days of each quarter Claude reads the quarter's stories rated {brief_opts['min_relevance']} / 5 or higher (at most {brief_opts['max_per_theme']} per theme) and any research papers, and drafts the brief for the editorial meeting as a Word document: an overview, a proposed line-up per theme, feature leads with the kinds of experts to approach, Academia-to-Industry topics, a regional-balance check, gaps worth covering and a watch list. The draft is refreshed every {count(brief_opts['refresh_days'], 'day')} and the final brief is written the day after the quarter closes. <b>Generate / update brief</b> on an issue page starts one on GitHub at any time.</li></ol>
{features_html(cfg)}
<h2 class="section-h">Magazine themes</h2><p class="hint">Words that suggest each theme (English keywords found in any language count too).</p><ul class="theme-list">{themes}</ul>
<h2 class="section-h">Websites read directly</h2><p class="hint">Sites that block feed readers or publish no feed (among them ISSMGE, ICE, GEER, USGS and GeoEngineer) are read through Google News searches limited to the site.</p><div class="table-wrap"><table class="overview"><thead><tr><th>Source</th><th>Site</th><th>Bonus</th></tr></thead><tbody>{rows}</tbody></table></div>
{jtable}
{failed}
<h2 class="section-h">Known limits</h2><p>Coverage of a country depends on what its press publishes online in a language covered here. Google News favours recency and mainstream outlets, so a major landslide is picked up readily while a quiet technical advance may not be — which is why society and institutional feeds are read directly.</p>
</div>"""


# ------------------------------------------------------------------ trends page
# Chart shades (light mode, dark mode) for each theme: the THEME_STYLE hues, stepped so that neighbouring
# segments of a stacked column stay distinct for colour-blind readers (CVD ΔE ≥ 9.6, normal vision ≥ 15.9)
# and every mark clears 3:1 on the card surface in both modes (checked with the dataviz palette validator).
# Themes added later in config.yaml fall back to theme_color(); themes found only in old digests (no longer
# in config.yaml) take the General grey rather than an unvalidated spare hue.
CHART_SHADES = {
    "Sustainability & the Energy Transition": ("#1f9d63", "#1f9d63"),
    "Digital Geotechnics": ("#6b4fd6", "#7860e2"),
    "Hazards & Resilience": ("#c4361a", "#c4361a"),
    "Ground Improvement & Innovation": ("#c58000", "#c48517"),
    "Infrastructure & the Underground City": ("#2563d6", "#3370e2"),
    "Offshore, Coasts & Water": ("#0b97a5", "#18a6b5"),
    "Characterisation & Modelling": ("#b02e6d", "#c23d7b"),
    "Geotechnics & Society": ("#935a1c", "#a3682d"),
    "General": ("#7b8798", "#8592a3"),
}
# Suggested uses in order of editorial weight, as one ordinal ramp (light, dark): the darker the
# segment, the stronger the material; in dark mode the ramp flips so feature leads are the lightest.
USE_RAMP = [("Feature lead", "#013966", "#bedbfc"), ("Academia-to-Industry topic", "#16558c", "#94c6f9"),
            ("Regional insight", "#3772ac", "#79a9db"), ("News brief", "#5590cc", "#5e8dbe"),
            ("Watch only", "#73b0ee", "#4472a1")]
TREND_PERIODS = 24  # months shown in the monthly charts (the table and CSV keep them all)
# Heat-table cells mix the sequential blue into the card surface in OKLab (style.css: --viz-heat, --surface,
# --ink; keep these in step). Each cell's text colour is worked out here from the mixed shade, per mode.
HEAT = {"light": ("#16558c", "#ffffff", "#142033"), "dark": ("#94c6f9", "#171e27", "#e8ecf1")}
HEAT_TOP = 88  # the largest share of a column is shaded with 88% of the blue


def _linear(hex_):
    return [((c / 255 + 0.055) / 1.055) ** 2.4 if c / 255 > 0.04045 else c / 255 / 12.92
            for c in bytes.fromhex(hex_.lstrip("#"))]


def _oklab(hex_):
    r, g, b = _linear(hex_)
    lms = [(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b), (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b),
           (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)]
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in lms)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_, 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def _luminance_oklab(lab):
    """WCAG relative luminance of an OKLab colour (clipped to sRGB, as the browser shows it)."""
    L, a, b = lab
    l_, m_, s_ = L + 0.3963377774 * a + 0.2158037573 * b, L - 0.1055613458 * a - 0.0638541728 * b, L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    rgb = (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
           -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)
    r, g, b = (min(1.0, max(0.0, v)) for v in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(y1, y2):
    return (max(y1, y2) + 0.05) / (min(y1, y2) + 0.05)


def heat_text(p):
    """Text classes for a cell shaded p%: the ink while it keeps 4.6:1 on the shade (WCAG AA's 4.5 plus a margin for
    the browser's rounding), otherwise white or black, whichever contrasts more (one of them always reaches 4.58:1).
    l…/d… = light/dark mode, …w/…k = white/black."""
    out = []
    for mode, (heat, surface, ink) in HEAT.items():
        h, s = _oklab(heat), _oklab(surface)
        y = _luminance_oklab(tuple(s[i] + (h[i] - s[i]) * p / 100 for i in range(3)))
        if _contrast(y, _luminance_oklab(_oklab(ink))) < 4.6:
            out.append(mode[0] + ("w" if _contrast(y, 1.0) >= _contrast(y, 0.0) else "k"))
    return " ".join(out)


def viz_style(order, legacy=()):
    """Per-theme and per-use chart colours as CSS classes (vt-0…, vu-0…), light and dark."""
    light, dark = [], []
    for i, t in enumerate(order):
        lo, hi = CHART_SHADES["General"] if t in legacy else CHART_SHADES.get(t, (theme_color(t), theme_color(t)))
        light.append(f".vt-{i}{{--c:{lo}}}")
        dark.append(f".vt-{i}{{--c:{hi}}}")
    for i, (_, lo, hi) in enumerate(USE_RAMP):
        light.append(f".vu-{i}{{--c:{lo}}}")
        dark.append(f".vu-{i}{{--c:{hi}}}")
    return f"<style>{''.join(light)}@media (prefers-color-scheme: dark){{{''.join(dark)}}}</style>"


def _count(d, key, n=1):
    d[key] = d.get(key, 0) + n


def _period(**kw):
    return dict(kw, digests=0, stories=0, themes={}, uses={}, rated=0, rel=0, r5=0, regions={}, papers=0, journals={})


def _tally(p, d):
    p["digests"] += 1
    for s in d["stories"]:
        p["stories"] += 1
        _count(p["themes"], s["theme"])
        _count(p["regions"], s.get("region") or "")
        if s.get("use"):
            _count(p["uses"], s["use"])
        if s.get("relevance"):
            p["rated"] += 1
            p["rel"] += s["relevance"]
            p["r5"] += s["relevance"] == 5
    for x in d.get("papers") or []:
        p["papers"] += 1
        _count(p["journals"], str(x.get("journal") or "Unknown journal"))


def next_month(d):
    """The 1st of the month after date d."""
    return (d.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def window_start(d, start_month=1):
    """First day of the three-month issue window containing date d (same rule as issue_window)."""
    offset = (d.month - start_month) % 12
    first = (start_month - 1 + offset // 3 * 3) % 12 + 1
    return dt.date(d.year if first <= d.month else d.year - 1, first, 1)


def edition_name(code):
    return COUNTRIES.get(code, code) if code else "Direct feeds"


def trend_stats(digests, cfg):
    """Everything the trends page and its CSV show, counted by the date of the digest that found each story."""
    sm = start_month(cfg)
    days = sorted(digests, key=lambda d: d["date"])
    dates = [dt.date.fromisoformat(d["date"][:10]) for d in days]
    first, asof = dates[0], dates[-1]
    months, quarters = {}, {}
    y, m = first.year, first.month
    while (y, m) <= (asof.year, asof.month):
        key = f"{y}-{m:02d}"
        months[key] = _period(key=key, label=f"{MONTHS[m - 1]} {y}", mon=MONTHS[m - 1], year=y)
        win = issue_window(key + "-01", sm)
        quarters.setdefault(win["key"], _period(key=win["key"], label=win["label"], span=win["span"]))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    for d in days:
        _tally(months[d["date"][:7]], d)
        _tally(quarters[issue_window(d["date"], sm)["key"]], d)
    first_key, last_key = f"{first:%Y-%m}", f"{asof:%Y-%m}"
    if first.day > 1:
        months[first_key]["note"] = f"archive began {first.day} {MONTHS[first.month - 1]}"
    months[last_key]["note"] = f"to {asof.day} {MONTHS[asof.month - 1]}"
    quarters[issue_window(asof.isoformat(), sm)["key"]]["note"] = "in progress"

    def stories(a, b):
        return sum(len(d["stories"]) for d, x in zip(days, dates) if a <= x <= b)

    # this month and quarter so far, against the same stretch of the previous one
    m0 = asof.replace(day=1)
    p_end = m0 - dt.timedelta(days=1)
    p0 = p_end.replace(day=1)
    q0 = window_start(asof, sm)
    pq0 = window_start(q0 - dt.timedelta(days=1), sm)
    pq_same = min(pq0 + (asof - q0), q0 - dt.timedelta(days=1))
    rated = [s["relevance"] for d in days for s in d["stories"] if s.get("relevance")]
    rated30 = [s["relevance"] for d, x in zip(days, dates) if (asof - x).days < 30
               for s in d["stories"] if s.get("relevance")]
    kpi = {
        "month": stories(m0, asof), "prev_month": stories(p0, p0.replace(day=min(asof.day, p_end.day))),
        "prev_month_ok": first <= p0, "prev_label": f"1–{min(asof.day, p_end.day)} {MONTHS[p0.month - 1]}",
        "quarter": stories(q0, asof), "prev_quarter": stories(pq0, pq_same), "prev_quarter_ok": first <= pq0,
        "prev_q_label": issue_window(pq0.isoformat(), sm)["label"], "q_label": issue_window(asof.isoformat(), sm)["label"],
        "rel": sum(rated) / len(rated) if rated else 0, "rel30": sum(rated30) / len(rated30) if rated30 else 0,
    }

    # keywords: the last 30 days against the 90 days before them, and keywords never seen before
    a0, b0 = asof - dt.timedelta(days=29), asof - dt.timedelta(days=119)
    c_a, c_b, seen = {}, {}, {}
    n_a = n_b = 0
    for d, x in zip(days, dates):
        for s in d["stories"]:
            kws = {k.strip().lower() for k in s.get("keywords") or [] if isinstance(k, str) and k.strip()}
            for k in kws:
                seen.setdefault(k, x)
            if x >= a0:
                n_a += 1
                for k in kws:
                    _count(c_a, k)
            elif x >= b0:
                n_b += 1
                for k in kws:
                    _count(c_b, k)
    b_days = (a0 - max(first, b0)).days  # days of digests the comparison window really covers
    rising = []
    if b_days >= 28 and n_a and n_b:
        for k, a in c_a.items():
            ra, rb = 100 * a / n_a, 100 * c_b.get(k, 0) / n_b
            ratio = (ra + 1) / (rb + 1)  # smoothed, so a keyword going from 0 to 1 story does not top the list
            if a >= 3 and ra - rb >= 0.5 and ratio >= 1.2 and seen[k] < a0:
                rising.append({"k": k, "a": a, "b": c_b.get(k, 0), "ra": ra, "rb": rb, "x": ratio})
        rising.sort(key=lambda r: (-r["x"], -r["a"], r["k"]))
    new = (sorted(((k, a) for k, a in c_a.items() if seen[k] >= a0), key=lambda x: (-x[1], x[0]))
           if (a0 - first).days >= 30 else None)
    src, src90 = {}, {}
    for d, x in zip(days, dates):
        for s in d["stories"]:
            _count(src, s["source"])
            if (asof - x).days < 90:
                _count(src90, s["source"])
    return {"first": first, "asof": asof, "digests": len(days), "stories": sum(len(d["stories"]) for d in days),
            "months": list(months.values()), "quarters": list(quarters.values()), "kpi": kpi,
            "n_a": n_a, "n_b": n_b, "b_days": b_days, "rising": rising[:10], "new": new,
            "top_kw": sorted(c_a.items(), key=lambda x: (-x[1], x[0]))[:10],
            "sources": sorted(src.items(), key=lambda x: (-x[1], x[0]))[:12], "sources90": src90,
            "papers": sum(p["papers"] for p in months.values())}


def nice_ticks(top, n=4):
    """Round axis steps (1, 2, 2.5 or 5 times a power of ten, whole numbers) from 0 up to at least top."""
    top = max(top, 1)
    mag = 10 ** math.floor(math.log10(top / n))
    step = max(1, next(f * mag for f in (1, 2, 2.5, 5, 10) if f * mag >= top / n and (f * mag) % 1 == 0))
    return [int(i * step) for i in range(math.ceil(top / step - 1e-9) + 1)]


def compact(v):
    return f"{v / 1000:.1f}".rstrip("0").rstrip(".") + "K" if v >= 1000 else f"{v:g}"


def tip_data(head, rows, foot=""):
    """Tooltip content; rows are [colour class, value, label, series index]. trends.js builds it with textContent."""
    return {"h": head, "r": rows, "f": foot}


def tip(head, rows, foot=""):
    return esc(json.dumps(tip_data(head, rows, foot), ensure_ascii=False))


def change(now, before):
    if not before:
        return ""
    pct = round((now - before) / before * 100)
    return f"▲ {pct}%" if pct > 0 else f"▼ {-pct}%" if pct < 0 else "No change"


def kpi(value, label, note=""):
    return (f"<div class='stat'><b>{value}</b><span>{esc(label)}</span>"
            + (f"<small>{esc(note)}</small>" if note else "") + "</div>")


def legend(items):
    return "<ul class='viz-legend'>" + "".join(f"<li><i class='{c}'></i>{esc(n)}</li>" for c, n in items) + "</ul>"


def viz_table(head, rows):
    """Table view of a chart: head is a list of column names, rows lists of cells (first cell is the row name)."""
    th = "".join(f"<th scope='col'>{esc(h)}</th>" for h in head)
    body = "".join("<tr>" + f"<th scope='row'>{esc(str(r[0]))}</th>" + "".join(f"<td>{esc(str(c))}</td>" for c in r[1:])
                   + "</tr>" for r in rows)
    return f"<div class='table-wrap'><table class='overview viz-tbl'><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>"


def figure(title, sub, chart, table="", extra=""):
    toggle = ("<div class='viz-toggle' role='group' aria-label='View'><button type='button' aria-pressed='true' "
              "data-view='chart'>Chart</button><button type='button' aria-pressed='false' data-view='table'>Table</button></div>"
              if table else "")
    return (f"<figure class='viz'><div class='viz-head'><div><h3>{esc(title)}</h3>"
            + (f"<p>{sub}</p>" if sub else "") + f"</div>{toggle}</div><div class='viz-chart'>{extra}{chart}</div>"
            + (f"<div class='viz-table' hidden>{table}</div>" if table else "") + "</figure>")


def x_labels(cols, xs, vw):
    """Month labels under a time axis; fewer are shown on narrow screens (classes xd / xp), the newest always."""
    n = len(cols)
    d_step = 1 if n <= 16 else 2 if n <= 32 else 3
    p_step = 1 if n <= 6 else 2 if n <= 12 else 3 if n <= 18 else 6
    years = {"yd": set(), "yp": set()}  # the year is written under the first label shown in each year
    out = []
    for i, (c, x) in enumerate(zip(cols, xs)):
        shown = {"yd": (n - 1 - i) % d_step == 0, "yp": (n - 1 - i) % p_step == 0}
        cls = ("xd " if shown["yd"] else "") + ("xp" if shown["yp"] else "")
        ycls = []
        for k in ("yd", "yp"):
            if shown[k] and c.get("year") not in years[k]:
                years[k].add(c.get("year"))
                ycls.append(k)
        ycls = " ".join(ycls)
        year = f"<em class='{ycls}'>{c['year']}</em>" if ycls and c.get("year") else ""
        out.append(f"<span class='{cls.strip()}' style='left:{x / vw * 100:.2f}%'>{esc(c.get('mon') or c['label'])}{year}</span>")
    return f"<div class='viz-x'>{''.join(out)}</div>"


def y_labels(ticks, k, fmt=compact):
    return "<div class='viz-y'>" + "".join(f"<span style='bottom:{t * k:.1f}px'>{fmt(t)}</span>" for t in ticks) + "</div>"


def column_chart(cols, series, height=230, share=False, vw=1000, label="Stories"):
    """Stacked columns; cols carry 'values' {series index: count}. The SVG stretches across the card while
    labels stay HTML, so text keeps its size from phone to desktop."""
    n = len(cols)
    totals = [sum(c["values"].values()) for c in cols]
    ticks = [0, 25, 50, 75, 100] if share else nice_ticks(max(totals, default=0))
    k = height / ticks[-1]
    slot = vw / n
    w = min(24, slot * 0.62)
    xs = [slot * (i + 0.5) for i in range(n)]
    svg = [f"<line class='grid' x1='0' x2='{vw}' y1='{height - t * k:.1f}' y2='{height - t * k:.1f}' vector-effect='non-scaling-stroke'/>"
           for t in ticks[1:]]
    for i, c in enumerate(cols):
        tot, x = totals[i], xs[i] - w / 2
        vals = [c["values"].get(j, 0) * (100 / tot if share and tot else 1) for j in range(len(series))]
        hs = [v * k for v in vals]
        vis = [j for j, h in enumerate(hs) if h >= 3]
        segs, base = [], height
        for j, h in enumerate(hs):
            if j in vis:
                top_seg = j == vis[-1]
                dh, y = (h if top_seg else h - 2), base - h
                if top_seg:
                    r = min(4, w / 2, dh)
                    segs.append(f"<path class='seg {series[j][1]}' data-s='{j}' d='M{x:.1f},{y + dh:.1f}V{y + r:.1f}"
                                f"Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f}H{x + w - r:.1f}Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f}"
                                f"V{y + dh:.1f}Z'/>")
                else:
                    segs.append(f"<rect class='seg {series[j][1]}' data-s='{j}' x='{x:.1f}' y='{y + 2:.1f}' width='{w:.1f}' height='{dh:.1f}'/>")
            base -= h
        rows = [[series[j][1], (f"{round(vals[j])}%" if share else f"{c['values'][j]:,}"), series[j][0], j]
                for j in reversed(range(len(series))) if c["values"].get(j)]
        head = c["label"] + (f" ({c['note']})" if c.get("note") else "")
        foot = (f"{tot:,} {label.lower()}" if tot else ("No digests" if not c.get("digests") else f"No {label.lower()}"))
        svg.append(f"<g class='col' data-tip='{tip(head, rows, foot)}'><rect class='hit' x='{slot * i:.1f}' y='0' "
                   f"width='{slot:.1f}' height='{height}'/>{''.join(segs)}</g>")
    caps = ""
    if not share and n:
        last, peak = n - 1, max(range(n), key=lambda i: (totals[i], i))
        show = [last] + ([peak] if peak != last and totals[peak] and abs(peak - last) * slot >= 56 else [])
        caps = "".join(f"<span class='viz-cap{' np' if i != last and n > 8 else ''}' style='left:{xs[i] / vw * 100:.2f}%;"
                       f"bottom:{totals[i] * k + 4:.1f}px'>{totals[i]:,}</span>" for i in show if totals[i])
    return (f"<div class='viz-plot' tabindex='0' role='img' aria-label='{esc(label)} per period, stacked by category. "
            f"The Table button shows every number.' style='--h:{height}px'>"
            f"{y_labels(ticks, k, (lambda t: f'{t}%') if share else compact)}<div class='viz-area'>"
            f"<svg viewBox='0 0 {vw} {height}' preserveAspectRatio='none' aria-hidden='true'>{''.join(svg)}"
            f"<line class='base' x1='0' x2='{vw}' y1='{height}' y2='{height}' vector-effect='non-scaling-stroke'/></svg>"
            f"{caps}</div>{x_labels(cols, xs, vw)}</div>")


def line_xs(n, vw, pad=16):
    return [vw / 2] if n == 1 else [pad + i * (vw - 2 * pad) / (n - 1) for i in range(n)]


def line_path(xs, ys):
    """Path through the points, broken where a value is missing (None)."""
    out, pen = [], "M"
    for x, y in zip(xs, ys):
        if y is None:
            pen = "M"
            continue
        out.append(f"{pen}{x:.1f},{y:.1f}")
        pen = "L"
    return "".join(out)


def bar_rows(rows, top, cls="one", tips=None):
    """Horizontal bars (HTML): rows are (label html, segments [(class, value, series index)], total text)."""
    out = []
    for i, (lab, segs, total) in enumerate(rows):
        tot = sum(v for _, v, _ in segs)
        pct = tot / top * 100 if top else 0
        inner = "".join(f"<i class='{c}' data-s='{s}' style='width:{v / tot * 100:.3f}%'></i>" for c, v, s in segs if v) if tot else ""
        data = f" data-tip='{tips[i]}'" if tips else ""
        out.append(f"<div class='hb'{data}><span class='hb-l'>{lab}</span><span class='hb-track'>"
                   f"<span class='hb-bar {cls}' style='width:{pct:.2f}%'>{inner}</span>"
                   f"<b class='hb-v' style='left:{pct:.2f}%'>{esc(total)}</b></span></div>")
    return f"<div class='hbars' tabindex='0'>{''.join(out)}</div>"


def heat_table(row_names, cols, cells, label, units, folded=False):
    """Shaded table (one-hue sequential) of counts, shaded by each cell's share of its column so that an issue
    window still in progress reads like a full one. A folded 'Other' last row is listed but not shaded."""
    col_tot = [sum(r[j] for r in cells) for j in range(len(cols))]
    shades = cells[:-1] if folded else cells
    peak = max((v / col_tot[j] for r in shades for j, v in enumerate(r) if col_tot[j]), default=0) or 1
    head = "".join(f"<th scope='col'>{esc(c['label'])}{'<small>' + esc(c['note']) + '</small>' if c.get('note') else ''}</th>"
                   for c in cols)
    body = []
    for i, (name, r) in enumerate(zip(row_names, cells)):
        tds, other = [], folded and i == len(cells) - 1
        for j, v in enumerate(r):
            share = v / col_tot[j] if col_tot[j] else 0
            p = 0 if other else round(share / peak * HEAT_TOP)
            t = tip(f"{name} · {cols[j]['label']}",
                    [["", f"{v:,}", units[v != 1]], ["", f"{share * 100:.0f}%", f"of the window's {col_tot[j]:,}"]]
                    if v else [["", "0", units[1]]])
            tds.append(f"<td class='{heat_text(p)}' style='--p:{p}' data-tip='{t}'>{v:,}</td>" if v
                       else f"<td class='zero' data-tip='{t}'>–</td>")
        body.append(f"<tr{' class=other' if other else ''}><th scope='row'>{esc(name)}</th>{''.join(tds)}"
                    f"<td class='tot'>{sum(r):,}</td></tr>")
    return (f"<div class='table-wrap'><table class='overview heat' tabindex='0'><thead><tr><th scope='col'>{esc(label)}</th>"
            f"{head}<th scope='col'>Total</th></tr></thead><tbody>{''.join(body)}</tbody></table></div>")


def heat_rows(periods, field, names, limit=15):
    """Rows for a heat table: the busiest names first, the rest folded into 'Other' (returned flag)."""
    totals = {}
    for p in periods:
        for key, v in p[field].items():
            _count(totals, key, v)
    keys = sorted(totals, key=lambda k: (-totals[k], names(k)))
    shown, rest = keys[:limit], keys[limit:]
    if len(rest) == 1:
        shown, rest = keys, []
    rows = [names(k) for k in shown] + ([f"Other ({len(rest)})"] if rest else [])
    cells = [[p[field].get(k, 0) for p in periods] for k in shown]
    if rest:
        cells.append([sum(p[field].get(k, 0) for k in rest) for p in periods])
    return rows, cells, bool(rest)


NO_STORIES = "<p class='viz-empty'>No stories in the archive yet: the digests so far found none.</p>"


def trends_body(T, cfg, legacy=()):
    root = ""
    if not T:
        return (hero("Trends", "Trends", "Themes, keywords and regions month by month and quarter by quarter.")
                + "<p class='empty'>The archive is empty. Trends appear after the first scan.</p>")
    order = theme_order(cfg)
    series = [(t, f"vt-{i}") for i, t in enumerate(order)]
    idx = {t: i for i, t in enumerate(order)}
    K, asof, first = T["kpi"], T["asof"], T["first"]
    months, quarters = T["months"][-TREND_PERIODS:], T["quarters"][-8:]
    span_days = (asof - first).days + 1

    # key figures
    mon = MONTHS[asof.month - 1]
    if not K["prev_month_ok"]:
        m_note = ("First month in the archive" if first >= asof.replace(day=1)
                  else f"Archive began {nice_date(first.isoformat())}")
    else:
        m_note = (f"{change(K['month'], K['prev_month'])} vs {K['prev_label']} ({K['prev_month']:,})" if K["prev_month"]
                  else f"None in {K['prev_label']}")
    if not K["prev_quarter_ok"]:
        q_note = "First issue window in the archive" if first >= window_start(asof, start_month(cfg)) else "Previous window incomplete"
    else:
        q_note = (f"{change(K['quarter'], K['prev_quarter'])} vs {K['prev_q_label']} by the same day ({K['prev_quarter']:,})"
                  if K["prev_quarter"] else f"None in {K['prev_q_label']} by the same day")
    stats = (kpi(f"{K['month']:,}", f"Stories in {mon} so far", m_note)
             + kpi(f"{K['quarter']:,}", f"Stories in {K['q_label']} so far", q_note)
             + kpi(f"{T['stories']:,}", "Stories archived",
                   f"{T['digests']:,} daily digest{'s' if T['digests'] != 1 else ''} since {nice_date(first.isoformat())}")
             + kpi(f"{K['rel']:.1f}" if K["rel"] else "–", "Average relevance",
                   f"Out of 5 · last 30 days {K['rel30']:.1f}" if K["rel30"] else "No AI-rated stories yet"))
    actions = (f"<div class='actions'><a class='btn primary' href='{root}exports/trends.csv' download>{icon('download')}"
               f"Monthly and quarterly numbers (CSV)</a><a class='btn light' href='{root}archive.html'>{icon('sheet')}Archive and workbooks</a></div>")
    out = [viz_style(order, legacy), hero(f"Trends · as of {esc(nice_date(asof.isoformat()))}", "Trends",
                                          "Themes, rising keywords and regions month by month and issue window by issue "
                                          "window — for editorials and the magazine's year-in-review.", stats, actions)]
    if span_days < 42:
        # the key figure compares a month with the one before once that one is in the archive from its 1st
        whole = first if first.day == 1 else next_month(first)
        mom = next_month(whole)
        out.append(f"<div class='trend-note'>{icon('chart')}<p><b>Trends fill in after a few weeks.</b> The archive holds "
                   f"{T['digests']} daily digest{'s' if T['digests'] != 1 else ''} so far ({esc(nice_date(first.isoformat()))}"
                   f"{' – ' + esc(nice_date(asof.isoformat())) if first != asof else ''}). Every chart below already works and grows "
                   "with each morning's scan: "
                   + (f"month-on-month comparisons start in {MONTHS[mom.month - 1]} {mom.year}, and " if asof < mom else "")
                   + "rising keywords appear once there are about two months of digests (the last 30 days against up to "
                   "90 days before them).</p></div>")

    # stories by theme, per month and per issue window
    cols = [dict(m, values={idx[t]: v for t, v in m["themes"].items() if t in idx}) for m in months]
    m_table = viz_table(["Month"] + order + ["Total"],
                        [[m["label"] + (f" ({m['note']})" if m.get("note") else "")] + [m["themes"].get(t, 0) for t in order]
                         + [m["stories"]] for m in reversed(T["months"])])
    out.append("<h2 class='section-h'>Stories by theme</h2><p class='hint'>Counted by the date of the daily digest that found "
               "each story. Hover a column or bar for its numbers, or switch any chart to a table.</p>")
    out.append(legend([(c, n) for n, c in series if any(m["themes"].get(n) for m in T["months"])]))
    out.append(figure("Per month", f"Latest {len(months)} month{'s' if len(months) != 1 else ''} · stacked by theme",
                      column_chart(cols, series), m_table) if any(m["stories"] for m in months)
               else figure("Per month", "", NO_STORIES))
    q_top = max((q["stories"] for q in quarters), default=0)
    q_rows = [(f"{esc(q['label'])}<small>{esc(q.get('note') or q['span'])}</small>",
               [(f"vt-{idx[t]}", q["themes"].get(t, 0), idx[t]) for t in order], f"{q['stories']:,}") for q in reversed(quarters)]
    q_tips = [tip(q["label"] + (f" ({q['note']})" if q.get("note") else ""),
                  [[f"vt-{idx[t]}", f"{q['themes'][t]:,}", t, idx[t]] for t in order if q["themes"].get(t)],
                  f"{q['stories']:,} stories · {q['digests']} digests") for q in reversed(quarters)]
    q_table = viz_table(["Issue window"] + order + ["Total"],
                        [[q["label"]] + [q["themes"].get(t, 0) for t in order] + [q["stories"]] for q in reversed(T["quarters"])])
    out.append(figure("Per issue window", "Three-month windows that follow the magazine's cycle, newest first",
                      bar_rows(q_rows, q_top, "", q_tips), q_table) if q_top else figure("Per issue window", "", NO_STORIES))

    # theme share over time (small multiples on one shared scale)
    def n_stories(ms):
        return sum(m["stories"] for m in ms)

    last3, prev3 = T["months"][-3:], T["months"][-6:-3]
    shares = {t: [(m["themes"].get(t, 0) / m["stories"] * 100 if m["stories"] else None) for m in months] for t in order}
    present = [t for t in order if any(m["themes"].get(t) for m in T["months"])]
    s_ticks = nice_ticks(max((v for t in present for v in shares[t] if v is not None), default=0), 2)
    vw, hh = 300, 64
    xs = line_xs(len(months), vw, 6)
    month_tips = [{"x": x / vw * 100, "t": tip_data(
        m["label"] + (f" ({m['note']})" if m.get("note") else ""),
        [[f"vt-{idx[t]}", f"{shares[t][i]:.0f}%" if shares[t][i] is not None else "–", t, idx[t]] for t in present],
        f"{m['stories']:,} stories")} for i, (m, x) in enumerate(zip(months, xs))]
    panels = []
    for t in present:
        ys = [None if v is None else hh - v / s_ticks[-1] * hh for v in shares[t]]
        now = sum(m["themes"].get(t, 0) for m in last3) / (n_stories(last3) or 1) * 100
        before = sum(m["themes"].get(t, 0) for m in prev3) / n_stories(prev3) * 100 if n_stories(prev3) >= 20 else None
        delta = ("No comparison yet" if before is None else f"▲ {now - before:.1f} pts" if now - before >= 0.5
                 else f"▼ {before - now:.1f} pts" if before - now >= 0.5 else "Steady")
        pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
        area = (f"<path class='wash' d='{line_path(xs, ys)}V{hh}H{pts[0][0]:.1f}Z'/>" if len(pts) > 1 and None not in ys else "")
        end = (f"<i class='sm-dot' style='left:{pts[-1][0] / vw * 100:.2f}%;top:{pts[-1][1]:.1f}px'></i>" if pts else "")
        panels.append(
            f"<div class='smp vt-{idx[t]}' data-ys='{json.dumps([None if y is None else round(y, 1) for y in ys])}'>"
            f"<div class='sm-head'><span class='ticon sm'>{theme_icon(t)}</span><b>{esc(t)}</b></div>"
            f"<div class='sm-fig'><b>{now:.0f}%</b><span>{esc(delta)}</span></div>"
            f"<div class='sm-plot' style='--h:{hh}px'><span class='sm-top'>{s_ticks[-1]}%</span>"
            f"<svg viewBox='0 0 {vw} {hh}' preserveAspectRatio='none' aria-hidden='true'>"
            f"<line class='grid' x1='0' x2='{vw}' y1='0.5' y2='0.5' vector-effect='non-scaling-stroke'/>{area}"
            f"<line class='base' x1='0' x2='{vw}' y1='{hh}' y2='{hh}' vector-effect='non-scaling-stroke'/>"
            f"<path class='ln' d='{line_path(xs, ys)}' vector-effect='non-scaling-stroke'/></svg>{end}"
            "<i class='xh' hidden></i><i class='hd' hidden></i></div></div>")
    s_table = viz_table(["Month"] + present,
                        [[m["label"]] + [f"{m['themes'].get(t, 0) / m['stories'] * 100:.1f}%" if m["stories"] else "–" for t in present]
                         for m in reversed(T["months"])])
    span_lbl = f"{months[0]['label']} – {months[-1]['label']}" if len(months) > 1 else months[0]["label"]
    out.append("<h2 class='section-h'>Which themes are growing</h2><p class='hint'>Each theme's share of the month's stories, "
               f"on one shared scale ({esc(span_lbl)}). The large figure is the share over the last three months; the change "
               "compares it with the three months before"
               + (" and appears once the archive covers them." if len(T["months"]) < 6 else ".") + "</p>")
    out.append(figure("Theme share over time", "", f"<div class='sm-grid viz-line' tabindex='0' data-tips='{esc(json.dumps(month_tips, ensure_ascii=False))}'>"
                      f"{''.join(panels)}</div>", s_table) if panels else figure("Theme share over time", "", NO_STORIES))

    # keywords
    out.append("<h2 class='section-h'>Keywords</h2><p class='hint'>English keyword concepts found in the stories "
               "(foreign-language terms count as their English equivalent).</p>")
    kw_cards = []
    b_win = f"{T['b_days']} days"  # the comparison window: up to 90 days, fewer while the archive is young
    if T["rising"]:
        top = nice_ticks(max(max(r["ra"], r["rb"]) for r in T["rising"]), 2)[-1]
        rows = []
        for r in T["rising"]:
            t = tip(r["k"], [["db-b", f"{r['ra']:.1f}%", f"last 30 days · {r['a']:,} stories"],
                             ["db-a", f"{r['rb']:.1f}%", f"previous {b_win} · {r['b']:,} stories"]],
                    f"Share of stories ×{r['ra'] / r['rb']:.1f}" if r["rb"] else f"Not seen in the previous {b_win}")
            a, b = r["rb"] / top * 100, r["ra"] / top * 100
            rows.append(f"<div class='db' data-tip='{t}'><span class='db-k'>{esc(r['k'])}</span><span class='db-track'>"
                        f"<i class='db-line' style='left:{a:.2f}%;width:{b - a:.2f}%'></i><i class='db-a' style='left:{a:.2f}%'></i>"
                        f"<i class='db-b' style='left:{b:.2f}%'></i></span><span class='db-v'><b>{r['a']:,}</b> · {r['ra']:.1f}%"
                        f"<small>was {r['rb']:.1f}%</small></span></div>")
        axis = (f"<div class='db db-axis' aria-hidden='true'><span></span><span class='db-track'><em style='left:0'>0%</em>"
                f"<em style='left:50%'>{top / 2:g}%</em><em style='left:100%'>{top:g}%</em></span><span></span></div>")
        r_table = viz_table(["Keyword", "Last 30 days", "Share", f"Previous {b_win}", "Share", "Change"],
                            [[r["k"], r["a"], f"{r['ra']:.1f}%", r["b"], f"{r['rb']:.1f}%",
                              f"×{r['ra'] / r['rb']:.1f}" if r["rb"] else f"new in {b_win}"] for r in T["rising"]])
        kw_cards.append(figure("Rising keywords", f"Share of stories mentioning each keyword: the last 30 days "
                               f"({T['n_a']:,} stories) against the {b_win} before ({T['n_b']:,})",
                               f"<div class='dbs' tabindex='0'>{''.join(rows)}{axis}</div>", r_table,
                               legend([("db-a", f"Previous {b_win}"), ("db-b", "Last 30 days")])))
    else:
        why = ("Rising keywords need about two months of digests: the last 30 days are compared with up to 90 days "
               "before them. Until then, the most frequent keywords of the last 30 days:" if T["b_days"] < 28 else
               "No keyword rose clearly in the last 30 days. The most frequent keywords of the last 30 days:")
        tk = T["top_kw"]
        top = nice_ticks(max((v for _, v in tk), default=0))[-1]
        body = (bar_rows([(esc(k), [("one", v, 0)], f"{v:,}") for k, v in tk], top, "one",
                         [tip(k, [["one", f"{v:,}", "stories in the last 30 days"]]) for k, v in tk]) if tk
                else "<p class='viz-empty'>No keywords yet.</p>")
        kw_cards.append(figure("Most mentioned keywords", esc(why),
                               body, viz_table(["Keyword", "Stories in the last 30 days"], tk) if tk else ""))
    if T["new"] is None:
        new_body = ("<p class='viz-empty'>Shown once the archive is older than two months, so that “new” means "
                    "not seen in at least the previous 30 days.</p>")
    elif not T["new"]:
        new_body = "<p class='viz-empty'>No keyword appeared for the first time in the last 30 days.</p>"
    else:
        new_body = "<ul class='kw-new'>" + "".join(f"<li><span>{esc(k)}</span><b>{v:,}</b></li>" for k, v in T["new"][:16]) + "</ul>"
    kw_cards.append(figure("New this month", "Keywords first seen in the last 30 days, with the number of stories", new_body))
    out.append(f"<div class='viz-grid kwgrid'>{''.join(kw_cards)}</div>")

    # regions (and research papers by journal, when the digests carry them)
    rows, cells, folded = heat_rows(quarters, "regions", edition_name)
    out.append("<h2 class='section-h'>Regions</h2><p class='hint'>Stories by Google News edition (the country edition a "
               "search ran in) per issue window. Stories read directly from society, institutional and trade websites are "
               "listed as direct feeds. The stronger the shading, the larger that edition's share of the window — a quick "
               "regional-balance check.</p>")
    out.append(figure("Stories by edition and issue window", "",
                      heat_table(rows, quarters, cells, "Edition", ("story", "stories"), folded) if rows else NO_STORIES))
    if T["papers"]:
        pq = quarters[next(i for i, q in enumerate(quarters) if q["papers"]):] if any(q["papers"] for q in quarters) else quarters
        rows, cells, folded = heat_rows(pq, "journals", str)
        out.append(figure("Research papers by journal", "New papers for Academia-to-Industry, per issue window",
                          heat_table(rows, pq, cells, "Journal", ("paper", "papers"), folded)))

    # editorial mix: suggested uses and average relevance
    uses = [u for u, *_ in USE_RAMP]
    u_series = [(u, f"vu-{i}") for i, u in enumerate(uses)]
    u_cols = [dict(m, values={uses.index(u): v for u, v in m["uses"].items() if u in uses}) for m in months]
    u_table = viz_table(["Month"] + uses + ["Rated stories"],
                        [[m["label"]] + [f"{m['uses'].get(u, 0)} ({m['uses'].get(u, 0) / m['rated'] * 100:.0f}%)" if m["rated"] else "–"
                                         for u in uses] + [m["rated"]] for m in reversed(T["months"])])
    rv, rhh = 480, 160
    rel = [m["rel"] / m["rated"] if m["rated"] else None for m in months]
    lo = min(3, math.floor(min((v for v in rel if v is not None), default=3)))
    rk = rhh / (5 - lo)
    rxs = line_xs(len(months), rv, 18)
    rys = [None if v is None else rhh - (v - lo) * rk for v in rel]
    rel_tips = [{"x": x / rv * 100, "y": y, "t": tip_data(
        m["label"] + (f" ({m['note']})" if m.get("note") else ""),
        [["one", f"{rel[i]:.2f}" if rel[i] is not None else "–", "average relevance"],
         ["", f"{m['rated']:,}", "AI-rated stories"], ["", f"{m['r5']:,}", "rated 5 / 5"]])}
        for i, (m, x, y) in enumerate(zip(months, rxs, rys))]
    pts = [(x, y, v) for x, y, v in zip(rxs, rys, rel) if y is not None]
    end = (f"<i class='ln-dot' style='left:{pts[-1][0] / rv * 100:.2f}%;top:{pts[-1][1]:.1f}px'></i>"
           f"<span class='ln-end' style='left:{pts[-1][0] / rv * 100:.2f}%;top:{pts[-1][1]:.1f}px'>{pts[-1][2]:.2f}</span>") if pts else ""
    r_grid = "".join(f"<line class='grid' x1='0' x2='{rv}' y1='{rhh - (t - lo) * rk:.1f}' y2='{rhh - (t - lo) * rk:.1f}' "
                     "vector-effect='non-scaling-stroke'/>" for t in range(lo + 1, 6))
    r_chart = (f"<div class='viz-plot viz-line' tabindex='0' role='img' aria-label='Average relevance per month' style='--h:{rhh}px' "
               f"data-tips='{esc(json.dumps(rel_tips, ensure_ascii=False))}'>"
               + "<div class='viz-y'>" + "".join(f"<span style='bottom:{(t - lo) * rk:.1f}px'>{t}</span>" for t in range(lo, 6)) + "</div>"
               f"<div class='viz-area'><svg viewBox='0 0 {rv} {rhh}' preserveAspectRatio='none' aria-hidden='true'>{r_grid}"
               f"<line class='base' x1='0' x2='{rv}' y1='{rhh}' y2='{rhh}' vector-effect='non-scaling-stroke'/>"
               f"<path class='ln one' d='{line_path(rxs, rys)}' vector-effect='non-scaling-stroke'/></svg>{end}"
               f"<i class='xh' hidden></i><i class='hd' hidden></i></div>{x_labels(months, rxs, rv)}</div>")
    r_table = viz_table(["Month", "Average relevance", "AI-rated stories", "Rated 5 / 5"],
                        [[m["label"], f"{m['rel'] / m['rated']:.2f}" if m["rated"] else "–", m["rated"], m["r5"]] for m in reversed(T["months"])])
    out.append("<h2 class='section-h'>Editorial mix</h2><p class='hint'>What Claude suggested each story could become, and how "
               "relevant it rated them (only AI-rated stories count here).</p>")
    unrated = ("<p class='viz-empty'>No AI-rated stories in these months: stories selected by keywords alone "
               "carry no rating or suggested use.</p>")
    rated = any(m["rated"] for m in months)
    out.append("<div class='viz-grid'>"
               + (figure("Suggested use", "Share of each month's rated stories, strongest material at the base",
                         column_chart(u_cols, u_series, 200, share=True, vw=480, label="Rated stories"), u_table,
                         legend([(c, n) for n, c in u_series])) if rated else figure("Suggested use", "", unrated))
               + (figure("Average relevance", "Mean rating of the month's stories, on a scale of 1 to 5", r_chart, r_table)
                  if rated else figure("Average relevance", "", unrated))
               + "</div>")

    # top sources
    src = T["sources"]
    top = nice_ticks(max((v for _, v in src), default=0))[-1]
    s_rows = [(esc(n), [("one", v, 0)], f"{v:,}") for n, v in src]
    s_tips = [tip(n, [["one", f"{v:,}", "stories in the archive"], ["", f"{T['sources90'].get(n, 0):,}", "in the last 90 days"],
                      ["", f"{v / T['stories'] * 100:.1f}%", "of all stories"]]) for n, v in src]
    out.append("<h2 class='section-h'>Top sources</h2>")
    out.append(figure("Most frequent sources", f"The {len(src)} publishers with the most stories in the archive",
                      bar_rows(s_rows, top, "one", s_tips),
                      viz_table(["Source", "Stories", "Last 90 days", "Share"],
                                [[n, v, T["sources90"].get(n, 0), f"{v / T['stories'] * 100:.1f}%"] for n, v in src]))
               if src else figure("Most frequent sources", "", NO_STORIES))
    return "".join(out)


def write_trends_csv(path, T, order):
    """The monthly and quarterly numbers behind the trends page, one row per period."""
    uses = [u for u, *_ in USE_RAMP]
    regions = sorted({r for p in T["months"] for r in p["regions"]}, key=lambda r: (r == "", edition_name(r)))
    journals = sorted({j for p in T["months"] for j in p["journals"]})
    head = (["Period type", "Period", "Label", "Daily digests", "Stories", "AI-rated stories", "Average relevance", "Rated 5 / 5"]
            + [f"Theme: {t}" for t in order] + [f"Use: {u}" for u in uses] + ["Research papers"]
            + [csv_text(f"Journal: {j}") for j in journals] + [csv_text(f"Edition: {edition_name(r)}") for r in regions])
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(head)
        for kind, periods in (("Month", T["months"]), ("Issue window", T["quarters"])):
            for p in periods:
                w.writerow([kind, p["key"], p["label"], p["digests"], p["stories"], p["rated"],
                            f"{p['rel'] / p['rated']:.2f}" if p["rated"] else "", p["r5"]]
                           + [p["themes"].get(t, 0) for t in order] + [p["uses"].get(u, 0) for u in uses] + [p["papers"]]
                           + [p["journals"].get(j, 0) for j in journals] + [p["regions"].get(r, 0) for r in regions])


# ------------------------------------------------------------------ e-mail
def render_email(d, cfg):
    url = site_url(cfg)
    rows = []
    by_theme = {}
    for s in d["stories"]:
        by_theme.setdefault(s["theme"], []).append(s)
    for t in sorted(by_theme, key=lambda t: -max(i["rank"] for i in by_theme[t])):
        rows.append(f"<h2 style='font:600 15px Arial,sans-serif;color:{theme_color(t)};border-bottom:2px solid {theme_color(t)};"
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
    papers = sorted(d.get("papers", []), key=lambda p: -paper_rank(p))[:8]
    if papers:
        rows.append("<h2 style='font:600 15px Arial,sans-serif;color:#5137b0;border-bottom:2px solid #5137b0;"
                    "padding-bottom:4px;margin:26px 0 8px'>New research (Academia-to-Industry)</h2>")
        for p in papers:
            rel = f"{p['relevance']}/5 for practice · " if p.get("relevance") else ""
            rows.append(
                "<div style='margin:0 0 14px'>"
                f"<a href='{esc(safe_url(p['link']))}' style='font:600 15px Arial,sans-serif;color:#1b2430'>{esc(p['title'])}</a>"
                f"<div style='font:12px Arial,sans-serif;color:#5b6573;margin-top:2px'>{rel}{esc(p.get('journal', ''))}"
                f"{' · ' + esc(p['authors']) if p.get('authors') else ''}</div>"
                + (f"<div style='font:italic 14px Georgia,serif;color:#333;margin-top:4px'>{esc(p['angle'])}</div>" if p.get("angle") else "")
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


def csv_text(value):
    """Spreadsheets run cells starting with = + - @ as formulas; keep feed text as text."""
    return "'" + value if isinstance(value, str) and value[:1] in "=+-@" else value


def storyline_text(s):
    """'Moniquirá landslide, Colombia (Oct 2026) · Investigation & inquiry' for a report of a developing story."""
    sl = s.get("_storyline")
    return f"{sl['title']} · {sl['stage']}" if sl else ""


def export_rows(stories):
    for s in stories:
        yield {
            "Digest date": s["_digest"], "Issue window": s["_window"], "Theme": s["theme"],
            "Relevance (1-5)": s.get("relevance") or "", "Suggested use": s.get("use", ""),
            "Headline (English)": csv_text(s.get("title_en") or s["title"]),
            "Original headline": csv_text(s["title"]) if s.get("title_en") else "",
            "Magazine angle": csv_text(s.get("angle", "")), "Source": csv_text(s["source"]),
            "Country": s.get("_country", ""), "Place": csv_text(" ".join(str(s.get("place") or "").split())),
            "Google News edition": s["_region"], "Published": (s.get("published") or "")[:10],
            "Developing story": csv_text(storyline_text(s)), "Link": s["link"],
            "Keywords": csv_text(", ".join(s.get("keywords", []))),
        }


def build(cfg):
    import brief  # the issue brief's Word file (brief.py imports this module, so not at the top)

    use_list = USES
    digests = load_digests()
    optional("storylines", "annotate", digests)  # every story of a developing story gets "_storyline" for its card
    briefs, brief_opts = load_briefs(), brief.settings(cfg)
    # themes found in the archive but no longer in config.yaml still get pages and rows
    extra = sorted({s["theme"] for d in digests for s in d["stories"] + d["papers"]} - set(theme_order(cfg)))
    if extra:
        cfg = dict(cfg, themes={**cfg["themes"], **{t: [] for t in extra}})
    sm = start_month(cfg)
    today = dt.date.today()
    today_key = issue_window(today.isoformat(), sm)["key"]
    order = theme_order(cfg)

    # group digests into issue windows (newest first)
    windows, by_key, names = [], {}, {}
    for d in digests:
        win = issue_window(d["date"], sm)
        if win["key"] not in by_key:
            by_key[win["key"]] = {"win": win, "digests": [], "stories": [], "papers": []}
            windows.append(by_key[win["key"]])
        w = by_key[win["key"]]
        w["digests"].append(d)
        for s in d["stories"]:
            code = str(s.get("country") or "").strip().upper()
            if code and code not in names:
                names[code] = country_label(code)
            w["stories"].append(dict(s, _digest=d["date"], _window=win["key"], _country=names.get(code, ""),
                                     _region=COUNTRIES.get(s.get("region", ""), s.get("region", ""))))
        for p in d["papers"]:
            w["papers"].append(dict(p, _digest=d["date"], _window=win["key"]))

    # fresh output folder (the archive itself lives in data/digests/)
    for sub in ("digests", "issues", "exports", "assets", "reports", "briefs", "weekly"):
        shutil.rmtree(DOCS / sub, ignore_errors=True)
    shutil.copytree(ASSETS, DOCS / "assets")
    (DOCS / "exports").mkdir()
    (DOCS / "reports").mkdir()
    (DOCS / "briefs").mkdir()
    write(DOCS / ".nojekyll", "")

    # issue briefs, from their JSON alone; one that cannot be rendered (a hand edit gone
    # wrong) is left out with a message rather than stopping the build and the scan's save
    for key, b in list(briefs.items()):
        try:
            brief.write_docx(DOCS / brief_file(key), b, cfg, theme_color)
        except (AttributeError, KeyError, TypeError, ValueError) as ex:
            print(f"Issue brief {key} left out: it could not be rendered ({type(ex).__name__}: {ex}).")
            del briefs[key]

    dates = [d["date"] for d in digests]
    for i, d in enumerate(digests):
        older = dates[i + 1] if i + 1 < len(dates) else None
        newer = dates[i - 1] if i > 0 else None
        title = f"Digest {nice_date(d['date'])}"
        write(DOCS / "digests" / f"{d['date']}.html",
              page(cfg, title, digest_body(d, cfg, "../", use_list, older, newer), "../", "archive"))

    # the developing stories, the archive's weeks and the events calendar, for the main pages and the workbooks
    groups = optional("storylines", "groups", digests, default=[]) or []
    weeks = weeks_of(digests)
    ev_opts = optional("events", "settings", cfg, default={}) or {}
    horizon = round(ev_opts.get("months_ahead", 12) * 30.44) if isinstance(ev_opts, dict) else 365
    ev_coming = optional("events", "upcoming", cfg, today, days=horizon, default=[]) or []
    ev_calls = optional("events", "deadlines", cfg, today, days=horizon, default=[]) or []
    for e in ev_coming + [c.get("event") for c in ev_calls if isinstance(c, dict)]:
        if isinstance(e, dict):  # 'Lyon, France and online', for the workbooks
            where = ", ".join(x for x in (str(e.get("city") or ""), country_label(e.get("country"))) if x)
            e["_where"] = (f"{where} and online" if where else "Online") if e.get("online") else where

    if digests:
        latest = digests[0]
        body = digest_body(latest, cfg, "", use_list, dates[1] if len(dates) > 1 else None, None, latest=True,
                           brief=briefs.get(issue_window(latest["date"], sm)["key"]),
                           side=side_column(weeks, groups, cfg, today),
                           week={"key": weeks[0]["key"], "label": weeks[0]["label"]} if weeks else None)
    else:
        latest = None
        body = hero("Latest digest", "Welcome",
                    "The first digest will appear here after the first scan. Scans run automatically every morning "
                    "at 05:00 Cairo time; press <b>Scan now</b> at the top of the page to start one on GitHub.")
        body += optional("events", "sidebar", cfg, "", today, limit=6, default="") or ""
    write(DOCS / "index.html", page(cfg, "Latest digest", body, "", "latest"))

    for w in windows:
        key = w["win"]["key"]
        first, last = window_range(key, sm)
        extras = {"coverage": coverage_line(w["stories"], cfg, "../", key),
                  "developing": developing_section(groups, first, last, "../"),
                  # what is coming up belongs to the window being planned now, not to one already closed
                  "events": (optional("events", "sidebar", cfg, "../", today, limit=6, default="") or "")
                  if key == today_key else ""}
        write(DOCS / "issues" / f"{key}.html",
              page(cfg, f"{w['win']['label']} issue window",
                   issue_body(w["win"], w["stories"], w["digests"], cfg, use_list, key == today_key,
                              briefs.get(key), brief_opts, w["papers"], extras), "../", "archive"))
        ordered = sorted(w["stories"], key=lambda s: (s["theme"], -s["rank"]))
        with open(DOCS / "exports" / f"{key}.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(export_rows(ordered))
        exports.write_workbook(
            DOCS / "exports" / f"{key}.xlsx", f"Geotechnical News · {w['win']['label']}",
            f"Issue window {w['win']['span']}", w["stories"], order, theme_color,
            [(nice_date(d["date"]), len(d["stories"])) for d in reversed(w["digests"])], "daily digest",
            digest_count=len(w["digests"]), windows=[key], papers=w["papers"], events=ev_coming, deadlines=ev_calls,
            events_asof=today)
        compact = [{"d": s["_digest"], "w": key, "t": s["title"], "te": s.get("title_en", ""), "l": s["link"],
                    "s": s["source"], "c": s["_region"], "p": (s.get("published") or "")[:10], "th": s["theme"],
                    "r": s.get("relevance") or 0, "u": s.get("use", ""), "a": s.get("angle", ""),
                    "k": s.get("keywords", []), "x": s.get("summary", "")[:200] if not s.get("angle") else "",
                    "rk": s["rank"], "id": s["id"],
                    # where it happened (ISO code, "" = global; names in exports/countries.json) and the
                    # developing story it belongs to (its first report included), its name, size and stage
                    "cc": s.get("country", ""), "pl": s.get("place", ""),
                    **({"sl": s["_storyline"]["id"], "st": s["_storyline"]["title"], "sz": s["_storyline"]["size"],
                        "sg": s["_storyline"]["stage"]} if s.get("_storyline") else {"sl": "", "sg": s.get("stage", "")})}
                   for s in w["stories"]]
        # research papers in the same shape (source = journal), marked kind "paper", with their authors
        compact += [{"d": p["_digest"], "w": key, "t": p["title"], "te": "", "l": p["link"],
                     "s": p.get("journal", ""), "c": "", "p": (p.get("published") or "")[:10], "th": p["theme"],
                     "r": p.get("relevance") or 0, "u": A2I, "a": p.get("angle", ""), "k": p.get("keywords", []),
                     "x": p.get("abstract", "")[:200] if not p.get("angle") else "", "rk": paper_rank(p),
                     "kind": "paper", "au": p.get("authors", "")}
                    for p in w["papers"]]
        write(DOCS / "exports" / f"{key}.json", json.dumps(compact, ensure_ascii=False, separators=(",", ":")))
    write(DOCS / "exports" / "index.json",
          json.dumps([w["win"] | {"stories": len(w["stories"]), "papers": len(w["papers"])} for w in windows],
                     ensure_ascii=False))
    write(DOCS / "exports" / "countries.json", json.dumps(dict(sorted(names.items())), ensure_ascii=False))
    exports.write_workbook(
        DOCS / "exports" / "geotech-news-archive.xlsx", "Geotechnical News · Whole archive",
        f"All {len(windows)} issue windows", [s for w in windows for s in w["stories"]], order, theme_color,
        [(w["win"]["label"], len(w["stories"])) for w in reversed(windows)], "issue window",
        digest_count=len(digests), windows=[w["win"]["key"] for w in windows],
        papers=[p for w in windows for p in w["papers"]], events=ev_coming, deadlines=ev_calls, events_asof=today)
    report.write_report(DOCS / "reports" / "site-report.docx", cfg, digests, windows, theme_color,
                        site_url(cfg), CHANGELOG, groups=groups)

    write(DOCS / "archive.html", page(cfg, "Archive", archive_body(windows, cfg, today_key, briefs, weeks), "", "archive"))
    write(DOCS / "search.html", page(cfg, "Search the archive", search_body(cfg, use_list, windows), "", "search"))
    trends = trend_stats(digests, cfg) if digests else None
    if trends:
        write_trends_csv(DOCS / "exports" / "trends.csv", trends, order)
    write(DOCS / "trends.html", page(cfg, "Trends", trends_body(trends, cfg, extra), "", "trends",
                                     "Themes, rising keywords and regions month by month and quarter by quarter",
                                     head="<script src='assets/trends.js' defer></script>"))
    write(DOCS / "assistant.html", page(cfg, "AI assistant", assistant_body(cfg), "", "assistant"))
    write(DOCS / "about.html", page(cfg, "Method & sources", about_body(cfg, latest, brief_opts), "", "about"))

    # pages of their own modules (they import this one, so not at the top): the world map,
    # developing stories, the events calendar and the weekly summaries. A page that fails is reported and left as
    # it was, so the rest of the site (and the scan's save step, which rebuilds it) still goes through.
    ctx = {"cfg": cfg, "digests": digests, "windows": windows, "order": order, "today_key": today_key,
           "start_month": sm}
    for name in ("geomap", "storylines", "events", "notify"):
        try:
            __import__(name).build(ctx)
        except Exception as ex:
            print(f"The {name}.py page was not rebuilt: {type(ex).__name__}: {ex}")
            traceback.print_exc()


if __name__ == "__main__":
    config = Path(os.environ.get("SCANNER_CONFIG", ROOT / "config.yaml"))
    build(yaml.safe_load(config.read_text(encoding="utf-8")))
    print(f"Site rebuilt in {DOCS}")
