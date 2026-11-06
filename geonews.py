#!/usr/bin/env python3
"""
Geo-News Weekly: the weekly news page for ISSMGE members (docs/geonews/), its archive of past
issues, and the LinkedIn post that goes with each issue.

How an issue is made
  1. After the Monday scan, a draft of the week before (Monday to Sunday) is written to
     data/geonews/<YYYY-Www>.yaml: the week's best stories (highlights), stories from the other
     regions (around the world), new research papers, and the events coming up (added by themselves).
     The editorial team is e-mailed a link to the draft's preview.
  2. The MPC editor opens the preview (geonews/preview/<week>.html, not linked from anywhere and
     hidden from search engines). It shows the issue as members will see it, every other story of
     the week with its code, and the LinkedIn post.
  3. The editor changes the file on GitHub (the "Edit this issue" button): swaps a story for another
     by its code, rewrites a text or headline, adds a photo. Every change rebuilds the preview.
  4. To publish, the editor changes  status: draft  to  status: approved. The issue then appears on
     geonews/index.html (newest issue) and in the archive (geonews/archive.html), and the LinkedIn
     post is e-mailed to the editorial team, ready to copy onto the ISSMGE LinkedIn page.

    python geonews.py --auto                 after each scan or edit: write last week's draft when it is
                                             missing, and send the e-mails not yet sent
    python geonews.py --draft [--week 2026-W44] [--force]
                                             write a draft now (--force replaces an existing draft file)

Photos: each story shows a drawing that matches its subject until the editor gives a photo: a web
link, or the name of a file uploaded to data/geonews/photos/. Use only photos ISSMGE may use (your own,
the society's, or free-licensed ones) and name the photographer under "credit".

data/geonews/sent.json records the e-mails sent: {"draft": {week: time}, "approved": {week: time}}.
"""
import argparse
import datetime as dt
import json
import re
import shutil
import sys
from pathlib import Path

import yaml

import site_builder

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "geonews"
PHOTOS = DATA / "photos"
SENT_FILE = DATA / "sent.json"
OUT = site_builder.DOCS / "geonews"
ICONS = json.loads((site_builder.ASSETS / "geonews-icons.json").read_text(encoding="utf-8"))
esc = site_builder.esc
KEY = re.compile(r"^\d{4}-W\d{2}$")
DEFAULTS = {"name": "Geo-News Weekly", "highlights": 5, "around": 8, "research": 3, "events_days": 60,
            "events_max": 6, "hashtags": "#Geotechnics #GeotechnicalEngineering #ISSMGE #CivilEngineering",
            "linkedin_page": ""}
INTRO = ("Dear colleagues, here are the geotechnical stories from around the world that caught our eye last week. "
         "We gather them from news sources in 20 languages, and the ISSMGE Magazine Presidential Committee (MPC) "
         "checks every issue before it is published.")
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
# drawings: the first keyword found in a story's keywords and headline picks the drawing, else its theme does
ICON_WORDS = [("liquef", "liq"), ("tailings", "dam"), ("dam ", "dam"), ("dams", "dam"), ("levee", "dam"),
              ("permafrost", "ice"), ("frost", "ice"), ("glacier", "ice"), ("landslide", "slide"), ("landslip", "slide"),
              ("rockfall", "slide"), ("mudslide", "slide"), ("debris flow", "slide"), ("slope", "slide"),
              ("sinkhole", "sink"), ("subsid", "sink"), ("sinking", "sink"), ("settlement", "sink"),
              ("subsea", "sea"), ("undersea", "sea"), ("underwater", "sea"), ("coast", "sea"), ("erosion", "sea"),
              ("river", "sea"), ("offshore", "wind"), ("wind", "wind"), ("seabed", "wind"), ("monopile", "wind"),
              ("metro", "metro"), ("subway", "metro"), ("railway", "metro"), ("rail", "metro"), ("tbm", "tbm"),
              ("tunnel", "tbm"), ("earthquake", "liq"), ("seism", "liq"), ("embankment", "dam"), ("retaining", "slide")]
THEME_ICON = {"Hazards & Resilience": "slide", "Infrastructure & the Underground City": "tbm",
              "Offshore, Coasts & Water": "wind", "Sustainability & the Energy Transition": "sink",
              "Digital Geotechnics": "map", "Ground Improvement & Innovation": "sink",
              "Characterisation & Modelling": "map", "Geotechnics & Society": "dam"}


def notify():
    import notify as n  # the e-mail channel, dates and event helpers of the weekly summary
    return n


def geomap():
    import geomap as g
    return g


def settings(cfg):
    out = dict(DEFAULTS)
    for k, v in ((cfg or {}).get("geonews") or {}).items():
        if k in out and v not in (None, ""):
            out[k] = type(out[k])(v) if isinstance(out[k], int) and str(v).isdigit() else v
    return out


def theme_color(theme):
    return site_builder.theme_color(theme or "General")


def flag(code):
    code = str(code or "").upper()
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in code) if re.match(r"^[A-Z]{2}$", code) else "🌍"


def title_of(s):
    return " ".join(str(s.get("title_en") or s.get("title") or "").split())


def week_span(key):
    n = notify()
    monday, sunday = n.week_range(key)
    return n.span_text(monday, sunday)


def week_no(key):
    return int(key[-2:])


# ------------------------------------------------------------------ the week's stories
def week_items(digests, key):
    """(stories, papers) saved Monday to Sunday of the week, each once (its best copy), with _digest."""
    monday, sunday = notify().week_range(key)
    stories, papers = {}, {}
    for d in digests:
        day = dt.date.fromisoformat(d["date"][:10])
        if not monday <= day <= sunday:
            continue
        for s in d.get("stories", []):
            s = dict(s, _digest=d["date"])
            old = stories.get(s["id"])
            if not old or (s.get("relevance") or 0) > (old.get("relevance") or 0):
                stories[s["id"]] = s
        for p in d.get("papers", []):
            p = dict(p, _digest=d["date"])
            pid = p.get("id") or p.get("link")
            if pid and pid not in papers:
                papers[pid] = dict(p, id=pid)
    return list(stories.values()), list(papers.values())


def all_items(digests):
    """Every story and paper of the archive by id, to find the ones an editor names."""
    stories, papers = {}, {}
    for d in digests:
        for s in d.get("stories", []):
            stories.setdefault(s["id"], dict(s, _digest=d["date"]))
        for p in d.get("papers", []):
            pid = p.get("id") or p.get("link")
            if pid:
                papers.setdefault(pid, dict(p, id=pid, _digest=d["date"]))
    return stories, papers


def region_of(code):
    g = geomap()
    try:
        known = g.world()["countries"].get(g.canonical(code))
    except Exception:  # the map's data missing: everything is one region
        known = None
    return known.get("g", "Global") if known else "Global"


def select(stories, papers, opts):
    """The draft's choice: highlights (the best stories, one per developing story, spread across themes and one
    per country), around the world (the best of each region in turn), and the research papers."""
    n = notify()
    good = [s for s in stories if (s.get("relevance") or 0) >= 4]
    if len(good) < opts["highlights"] + opts["around"]:
        good = [s for s in stories if (s.get("relevance") or 0) >= 3]
    lines, per_country, highlights = set(), {}, []
    for s in n.pick_top(good, len(good)):
        c = s.get("country") or ""
        if n.line_key(s) in lines or (c and per_country.get(c, 0) >= 1):
            continue
        highlights.append(s)
        lines.add(n.line_key(s))
        per_country[c] = per_country.get(c, 0) + 1
        if len(highlights) >= opts["highlights"]:
            break
    used_countries = {s.get("country") for s in highlights}
    queues, order = {}, []
    for s in n.by_rank(good):
        if n.line_key(s) in lines:
            continue
        r = region_of(s.get("country"))
        if r not in queues:
            queues[r], order = [], order + [r]
        queues[r].append(s)
    for r in order:  # a country not yet in the issue first
        queues[r].sort(key=lambda s: s.get("country") in used_countries)
    around = []
    while len(around) < opts["around"] and any(queues.values()):
        for r in order:
            while queues[r]:
                s = queues[r].pop(0)
                if n.line_key(s) in lines:
                    continue
                lines.add(n.line_key(s))
                around.append(s)
                break
            if len(around) >= opts["around"]:
                break
    research = sorted(papers, key=lambda p: -(p.get("relevance") or 0))[:opts["research"]]
    return highlights, around, research


# ------------------------------------------------------------------ the issue file
def q(text):
    """A YAML text in double quotes (JSON's quoting is valid YAML)."""
    return json.dumps(" ".join(str(text or "").split()), ensure_ascii=False)


def note(text):
    return " ".join(str(text or "").replace("#", "").split())[:110]


def draft_text(key, highlights, around, research, cfg):
    site = site_builder.site_url(cfg)
    n = notify()
    lines = [f"# {settings(cfg)['name']} · {week_span(key)} ({key})",
             "#",
             "# HOW TO EDIT THIS ISSUE (on GitHub: press the pencil, change the file, then press \"Commit changes\")",
             f"#  - See it as members will:   {site}geonews/preview/{key}.html",
             "#    That page also lists every other story of the week, each with its code.",
             "#  - Swap a story: replace its code (after story: or paper:) with another code from the preview page.",
             "#  - Change a headline or a text: write it between the quotes. An empty title keeps the original headline.",
             "#  - Add a photo: a web link to the photo, or upload it to data/geonews/photos/ and give its file name.",
             "#    Use only photos ISSMGE may use (your own, the society's, or free-licensed) and name the",
             "#    photographer under credit. Without a photo the story shows a drawing.",
             "#  - Remove a story: delete its lines (from the - to the line before the next -).",
             "#  - PUBLISH: change  status: draft  to  status: approved  and commit. The page goes public within a few",
             "#    minutes and the LinkedIn post is e-mailed to the editorial team.",
             "",
             "status: draft",
             f"intro: {q(INTRO)}",
             "",
             "# the big photo at the top of the first highlight (the story of the week)",
             'main_photo: ""',
             'main_photo_credit: ""',
             "",
             "highlights:   # the first one is the story of the week"]
    for s in highlights:
        lines += [f"  - story: {s['id']}   # {note(title_of(s))} ({note(n.country_name(s.get('country')) or 'global')})",
                  '    title: ""',
                  f"    text: {q(s.get('angle'))}",
                  '    photo: ""',
                  '    credit: ""']
    lines += ["", "around_the_world:"]
    for s in around:
        lines += [f"  - story: {s['id']}   # {note(title_of(s))} ({note(n.country_name(s.get('country')) or 'global')})",
                  '    title: ""',
                  '    text: ""   # optional: one line; empty shows the headline alone',
                  '    photo: ""',
                  '    credit: ""']
    lines += ["", "research:"]
    for p in research:
        lines += [f"  - paper: {q(p['id'])}   # {note(p.get('title'))}",
                  f"    text: {q(p.get('angle'))}"]
    lines += ["",
              "# events coming up are added by themselves from the events calendar; write  events: none  to leave them out",
              "events: auto",
              "",
              "# optional: a line about the latest ISSMGE Magazine issue, and its link (empty: no box)",
              'magazine_note: ""',
              'magazine_link: ""',
              ""]
    return "\n".join(lines)


def write_draft(digests, key, cfg, force=False):
    """Write data/geonews/<key>.yaml; False when it exists (and not force) or the week has no stories."""
    path = DATA / f"{key}.yaml"
    if path.exists() and not force:
        return False
    stories, papers = week_items(digests, key)
    if not stories:
        return False
    hl, ar, rs = select(stories, papers, settings(cfg))
    DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(draft_text(key, hl, ar, rs, cfg), encoding="utf-8")
    return True


def load_issue(path, stories, papers):
    """The issue in a file, resolved against the archive: {"key", "status", ..., "problems": [...]}.
    Raises ValueError (with the line) when the file is not readable YAML."""
    key = path.stem
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as ex:
        mark = getattr(ex, "problem_mark", None)
        where = f" near line {mark.line + 1}" if mark else ""
        raise ValueError(f"the file has a typing mistake{where} ({getattr(ex, 'problem', '') or ex})") from None
    if not isinstance(raw, dict):
        raise ValueError("the file is not laid out as an issue")
    problems = []

    def text(v):
        return " ".join(str(v or "").split())

    def items(name, kind, pool):
        out = []
        for i, it in enumerate(raw.get(name) or [], 1):
            if not isinstance(it, dict):
                problems.append(f"{name}, item {i}: not laid out as an item")
                continue
            code = text(it.get(kind))
            found = pool.get(code)
            if not found:
                problems.append(f"{name}, item {i}: no {kind} has the code {code or '(empty)'}")
                continue
            out.append({"s": found, "title": text(it.get("title")), "text": text(it.get("text")),
                        "photo": text(it.get("photo")), "credit": text(it.get("credit"))})
        return out

    status = text(raw.get("status")).lower() or "draft"
    if status not in ("draft", "approved"):
        problems.append(f"status is \"{status}\": write draft or approved")
    return {"key": key, "status": status, "intro": text(raw.get("intro")) or INTRO,
            "main_photo": text(raw.get("main_photo")), "main_credit": text(raw.get("main_photo_credit")),
            "highlights": items("highlights", "story", stories), "around": items("around_the_world", "story", stories),
            "research": items("research", "paper", papers),
            "events": text(raw.get("events")).lower() != "none",
            "magazine_note": text(raw.get("magazine_note")), "magazine_link": site_builder.safe_url(text(raw.get("magazine_link")))
            if text(raw.get("magazine_link")) else "", "problems": problems}


def issue_files():
    return sorted((p for p in DATA.glob("*.yaml") if KEY.match(p.stem)), reverse=True)


# ------------------------------------------------------------------ pictures
def icon_key(s):
    if s.get("_paper"):
        return "paper"
    hay = " ".join([title_of(s).lower(), " ".join(map(str, s.get("keywords") or [])).lower()]) + " "
    for word, k in ICON_WORDS:
        if word in hay:
            return k
    return THEME_ICON.get(s.get("theme"), "map")


def drawing(k, cls="pic"):
    return (f"<svg class='{cls}' viewBox='0 0 160 100' preserveAspectRatio='xMidYMax slice' aria-hidden='true'>"
            f"{ICONS.get(k, ICONS['map'])}</svg>")


def photo_src(value, root):
    """A photo's address on the page: a web link as given, or a file of data/geonews/photos/ (copied to the site)."""
    if re.match(r"^https?://", value, re.I):
        return site_builder.safe_url(value)
    name = Path(value).name
    if (PHOTOS / name).is_file() and Path(name).suffix.lower() in PHOTO_EXT:
        return f"{root}photos/{name}"
    return ""


def picture(it, root, cls="pic", photo=None, credit=None):
    photo = it.get("photo") if photo is None else photo
    credit = it.get("credit") if credit is None else credit
    src = photo_src(photo, root) if photo else ""
    if src:
        cr = f"<span class='credit'>{esc(credit)}</span>" if credit else ""
        return f"<img class='{cls}' src='{esc(src)}' alt='' loading='lazy'>{cr}"
    return drawing(icon_key(it["s"]), cls)


# ------------------------------------------------------------------ the world map
MAP_VIEW = (-2600, -1250, 5250, 2050)  # Equal Earth, without Antarctica


def map_svg(issue, cls="wmap", label=True):
    """The world: the issue's countries tinted, a numbered pin for each story (red: highlights, gold: around the world)."""
    g = geomap()
    w = g.world()
    numbered = list(enumerate(issue["highlights"] + issue["around"], 1))
    tint = {}
    for i, it in numbered:
        c = g.canonical(it["s"].get("country"))
        if c and c not in tint:
            tint[c] = "#f2c9c3" if i <= len(issue["highlights"]) else "#f3e2b0"
    paths = [f"<path d='{v['d']}' fill='{tint.get(k, '#e9e2dc')}'/>" for k, v in w["countries"].items() if v.get("d")]
    pins, seen = [], {}
    for i, it in numbered:
        pt = g.label_point(it["s"].get("country"))
        if not pt:
            continue
        cell = (round(pt[0] / 120), round(pt[1] / 120))
        k = seen.get(cell, 0)
        seen[cell] = k + 1
        x, y = pt[0] + 110 * k, pt[1] - 30 * k
        hl = i <= len(issue["highlights"])
        fill = "#a6242e" if hl else "#b9962e"
        r = 72 if hl else 60
        t = esc(title_of(it["s"]))
        pins.append(f"<a href='#s{i}' aria-label='Story {i}: {t}'><title>{i}. {t}</title>"
                    f"<circle cx='{x:.0f}' cy='{y:.0f}' r='{r}' fill='{fill}' stroke='#fff' stroke-width='12'/>"
                    + (f"<text x='{x:.0f}' y='{y + 26:.0f}' text-anchor='middle' font-size='{76 if hl else 64}' "
                       f"font-weight='bold' fill='#fff' font-family='Arial,sans-serif'>{i}</text>" if label else "")
                    + "</a>")
    vb = " ".join(map(str, MAP_VIEW))
    return (f"<svg class='{cls}' viewBox='{vb}' role='img' aria-label='World map of this week’s stories'>"
            f"<rect x='{MAP_VIEW[0]}' y='{MAP_VIEW[1]}' width='{MAP_VIEW[2]}' height='{MAP_VIEW[3]}' fill='#f6f1ea'/>"
            f"<g stroke='#fff' stroke-width='3'>{''.join(paths)}</g>{''.join(pins)}</svg>")


# ------------------------------------------------------------------ the page
def where_text(s):
    n = notify()
    place = n.country_name(s.get("country"))
    return f"{flag(s.get('country'))} {esc(place)}" if place else "🌍 Global"


def tag(s):
    t = s.get("theme") or "General"
    return f"<span class='tt' style='--c:{theme_color(t)}'>{esc(t)}</span>"


def headline_html(it):
    return esc(it["title"] or title_of(it["s"]))


def events_html(issue, cfg, opts):
    if not issue["events"]:
        return ""
    n = notify()
    sunday = n.week_range(issue["key"])[1]
    try:
        import events as ev
        coming = ev.upcoming(cfg, sunday + dt.timedelta(days=1), days=opts["events_days"])
    except Exception as ex:
        print(f"Geo-News: events left out ({type(ex).__name__}: {ex})")
        return ""
    if not coming:
        return ""
    rows = []
    for e in coming[:opts["events_max"]]:
        start = str(e.get("start") or "")
        try:
            d = dt.date.fromisoformat(start[:10])
            day, mon = (f"{d.day}", f"{d:%b}".upper())
        except ValueError:
            day, mon = "", start
        end = str(e.get("end") or "")
        if len(end) == 10 and end != start and end[:7] == start[:7]:
            day = f"{day}–{int(end[8:10])}"
        iss = bool(e.get("issmge"))
        url = site_builder.safe_url(e.get("url") or "")
        name = esc(e.get("short") or e.get("name") or "")
        if e.get("short") and e.get("name") and len(e["name"]) < 90:
            name = esc(e["name"])
        place = esc(n.event_place(e))
        rows.append(f"<li class='{'is' if iss else ''}'><div class='date'><b>{day}</b><span>{esc(mon)}</span></div><div>"
                    f"<a href='{esc(url)}'>{name}</a>" + (f"<div class='place'>{place}</div>" if place else "")
                    + ("<span class='badge'>ISSMGE</span>" if iss else "") + "</div></li>")
    return f"<h2>Coming up</h2><ul class='ev'>{''.join(rows)}</ul>"


def issue_html(issue, cfg, root, number=None):
    """The issue itself: header, map, highlights, around the world, research, events, magazine box."""
    opts = settings(cfg)
    hl, ar = issue["highlights"], issue["around"]
    out = [f"<header class='gn-head'><div class='mast'>{site_builder.MPC_MARK}<div>"
           f"<div class='kicker'>ISSMGE · Magazine Presidential Committee (MPC)</div><h1>{esc(opts['name'])}</h1></div></div>"
           f"<div class='chips'><span class='no'>Week {week_no(issue['key'])} · {issue['key'][:4]}</span>"
           f"<span>{esc(week_span(issue['key']))}</span>"
           + (f"<span>Issue {number}</span>" if number else "") + "</div></header><div class='stripe'></div><div class='gn-main'>",
           f"<p class='intro'>{esc(issue['intro'])}</p>"]
    if hl or ar:
        out.append(f"<section class='mapcard'><h2>This week on the map</h2>{map_svg(issue)}"
                   "<div class='mapkey'><span><i class='k1'></i>Highlights</span><span><i class='k2'></i>Around the world</span>"
                   "<span>Tap a number to read the story</span></div></section>")
    if hl:
        out.append("<h2>Highlights</h2>")
        lead = hl[0]
        s = lead["s"]
        out.append(f"<article class='lead' id='s1' style='--c:{theme_color(s.get('theme'))}'>"
                   f"<a class='hero' href='{esc(s['link'])}'>{picture(lead, root, 'pic', issue['main_photo'] or lead['photo'], issue['main_credit'] or lead['credit'])}</a>"
                   f"<div class='lead-k'><b class='num'>1</b> Story of the week</div>"
                   f"<h3><a href='{esc(s['link'])}'>{headline_html(lead)}</a></h3>"
                   f"<div class='meta'>{where_text(s)} · {esc(s.get('source', ''))}</div>"
                   + (f"<p>{esc(lead['text'])}</p>" if lead["text"] else "") + f"{tag(s)}</article>")
        for i, it in enumerate(hl[1:], 2):
            s = it["s"]
            out.append(f"<article class='card' id='s{i}' style='--c:{theme_color(s.get('theme'))}'>"
                       f"<a class='th' href='{esc(s['link'])}'>{picture(it, root)}</a><div class='body'>"
                       f"<div class='meta'><b class='num'>{i}</b> {where_text(s)} · {esc(s.get('source', ''))}</div>"
                       f"<h3><a href='{esc(s['link'])}'>{headline_html(it)}</a></h3>"
                       + (f"<p>{esc(it['text'])}</p>" if it["text"] else "") + f"{tag(s)}</div></article>")
    if ar:
        rows = []
        for i, it in enumerate(ar, len(hl) + 1):
            s = it["s"]
            rows.append(f"<li id='s{i}' style='--c:{theme_color(s.get('theme'))}'><a class='wth' href='{esc(s['link'])}'>{picture(it, root)}</a>"
                        f"<div><div class='meta'><b class='num g'>{i}</b> {where_text(s)}</div>"
                        f"<a class='hl' href='{esc(s['link'])}'>{headline_html(it)}</a>"
                        + (f"<div class='txt'>{esc(it['text'])}</div>" if it["text"] else "")
                        + f"<div class='src'>{esc(s.get('source', ''))}</div></div></li>")
        out.append(f"<h2>Around the world</h2><ul class='world'>{''.join(rows)}</ul>")
    if issue["research"]:
        rows = "".join(f"<li><a class='pth' href='{esc(p['s']['link'])}'>{drawing('paper')}</a><div>"
                       f"<a href='{esc(p['s']['link'])}'>{esc(p['title'] or p['s'].get('title', ''))}</a>"
                       f"<div class='j'>{esc(p['s'].get('journal', ''))}</div>"
                       + (f"<div>{esc(p['text'])}</div>" if p["text"] else "") + "</div></li>"
                       for p in issue["research"])
        out.append(f"<section class='papers'><h2>Research highlights</h2><ol>{rows}</ol></section>")
    out.append(events_html(issue, cfg, opts))
    if issue["magazine_note"]:
        link = (f" <a href='{esc(issue['magazine_link'])}'>Read it</a>" if issue["magazine_link"] else "")
        out.append(f"<div class='mag'><div class='ic'></div><div><b>From the ISSMGE Magazine</b> — "
                   f"{esc(issue['magazine_note'])}{link}</div></div>")
    out.append("</div>")
    return "".join(out)


def shell(cfg, title, body, root, description, extra_head="", noindex=False):
    site = site_builder.site_url(cfg)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
{'<meta name="robots" content="noindex,nofollow">' if noindex else ''}
<meta name="theme-color" content="#a6242e">
<link rel="icon" href="{root}../assets/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{root}../assets/geonews.css">{extra_head}
</head><body><div class="gn-wrap">
{body}
<footer class="gn-foot">Stories come from public news sources; each headline links to the original publisher. Please check
details with the original source.<br>
<a href="{root}index.html">Latest issue</a> · <a href="{root}archive.html">All issues</a> ·
<a href="{esc(site)}">Geotechnical News Desk</a><br>Prepared by the ISSMGE Magazine Presidential Committee (MPC)</footer>
</div></body></html>"""


def nav_html(key, approved, root):
    i = approved.index(key) if key in approved else -1
    older = approved[i + 1] if 0 <= i < len(approved) - 1 else None
    newer = approved[i - 1] if i > 0 else None
    return ("<nav class='gn-nav'>"
            + (f"<a href='{root}{older}.html'>← Week {week_no(older)}</a>" if older else "<span></span>")
            + f"<a href='{root}archive.html'>All issues</a>"
            + (f"<a href='{root}{newer}.html'>Week {week_no(newer)} →</a>" if newer else "<span></span>")
            + "</nav>")


def archive_html(issues, cfg, root):
    if not issues:
        return "<p class='empty'>No issue has been published yet.</p>"
    rows = []
    for issue in issues:
        first = issue["highlights"][0] if issue["highlights"] else None
        pic = picture(first, root, "pic", issue["main_photo"] or first["photo"], "") if first else drawing("map")
        heads = "".join(f"<li>{headline_html(it)}</li>" for it in issue["highlights"][:3])
        rows.append(f"<li><a class='arc' href='{root}{issue['key']}.html'><span class='ath'>{pic}</span>"
                    f"<span class='abody'><b>Week {week_no(issue['key'])} · {esc(week_span(issue['key']))}</b>"
                    f"<ul>{heads}</ul></span></a></li>")
    return f"<ul class='archive'>{''.join(rows)}</ul>"


# ------------------------------------------------------------------ LinkedIn
def page_url(cfg, key=None):
    return f"{site_builder.site_url(cfg)}geonews/{key + '.html' if key else 'index.html'}"


def linkedin_text(issue, cfg):
    opts = settings(cfg)
    lines = [f"🌍 {opts['name']} · {week_span(issue['key'])}", "",
             "What happened in geotechnics around the world last week:", ""]
    for it in issue["highlights"]:
        s = it["s"]
        place = notify().country_name(s.get("country"))
        lines.append(f"{flag(s.get('country'))} {it['title'] or title_of(s)}" + (f" ({place})" if place else ""))
    if issue["around"]:
        places = []
        for it in issue["around"]:
            p = notify().country_name(it["s"].get("country"))
            if p and p not in places:
                places.append(p)
        if places:
            lines += ["", "Also this week: news from " + ", ".join(places[:-1]) + (" and " if len(places) > 1 else "") + places[-1] + "."]
    if issue["research"]:
        lines.append(f"Plus {len(issue['research'])} new research papers and the events coming up.")
    lines += ["", f"Read the full round-up, with the world map: {page_url(cfg, issue['key'])}", "",
              "Prepared by the ISSMGE Magazine Presidential Committee (MPC).", "", opts["hashtags"]]
    return "\n".join(lines)


def linkedin_card(issue, cfg):
    """A 1200 × 627 picture for the LinkedIn post (SVG; the preview page saves it as PNG)."""
    opts = settings(cfg)
    heads = []
    for i, it in enumerate(issue["highlights"][:3], 1):
        words, line, out = (it["title"] or title_of(it["s"])).split(), "", []
        for w in words:
            if len(line) + len(w) + 1 > 34 and line:
                out.append(line)
                line = w
            else:
                line = (line + " " + w).strip()
        out.append(line)
        if len(out) > 2:
            out = out[:2]
            out[1] = out[1].rstrip(".,;:") + "…"
        heads.append((i, out))
    y, texts = 300, []
    for i, ls in heads:
        texts.append(f"<circle cx='62' cy='{y - 9}' r='17' fill='#a6242e'/><text x='62' y='{y - 2}' text-anchor='middle' "
                     f"font-size='20' font-weight='bold' fill='#fff' font-family='Arial,sans-serif'>{i}</text>")
        for j, l in enumerate(ls):
            texts.append(f"<text x='92' y='{y + j * 30}' font-size='25' fill='#2a2024' font-family='Georgia,serif'>{esc(l)}</text>")
        y += 30 * len(ls) + 26
    inner = map_svg(issue, "", label=True).replace("<svg class=''", "<svg x='470' y='150' width='710' height='400'", 1)
    return (f"<svg xmlns='http://www.w3.org/2000/svg' class='li-card' viewBox='0 0 1200 627' width='1200' height='627'>"
            f"<rect width='1200' height='627' fill='#fffdf8'/>"
            f"<rect width='1200' height='120' fill='#a6242e'/><rect y='120' width='1200' height='8' fill='#b9962e'/>"
            f"<text x='40' y='52' font-size='20' letter-spacing='3' fill='#f3d98b' font-family='Arial,sans-serif' font-weight='bold'>"
            f"ISSMGE · MAGAZINE PRESIDENTIAL COMMITTEE</text>"
            f"<text x='40' y='98' font-size='42' fill='#fff' font-family='Georgia,serif' font-weight='bold'>{esc(opts['name'])}</text>"
            f"<text x='1160' y='98' text-anchor='end' font-size='26' fill='#fff' font-family='Arial,sans-serif'>{esc(week_span(issue['key']))}</text>"
            f"<text x='40' y='200' font-size='22' letter-spacing='2' fill='#a6242e' font-family='Arial,sans-serif' font-weight='bold'>THIS WEEK'S HIGHLIGHTS</text>"
            f"<rect x='40' y='216' width='60' height='5' fill='#b9962e'/>"
            f"{''.join(texts)}{inner}"
            f"<text x='40' y='600' font-size='18' fill='#6b6066' font-family='Arial,sans-serif'>Full round-up: {esc(page_url(cfg, issue['key']))}</text>"
            f"</svg>")


# ------------------------------------------------------------------ preview (for the editor)
def alternatives_html(key, issue, digests, cfg):
    stories, papers = week_items(digests, key)
    used = {it["s"]["id"] for it in (issue["highlights"] + issue["around"])} if issue else set()
    used_p = {it["s"]["id"] for it in issue["research"]} if issue else set()
    n = notify()
    rows, small = [], []
    for s in n.by_rank(stories):
        if (s.get("relevance") or 0) < 3:
            continue
        mark = " class='in'" if s["id"] in used else ""
        (rows if (s.get("relevance") or 0) >= 4 or s["id"] in used else small).append(f"<tr{mark}><td><code>{esc(s['id'])}</code> <button type='button' class='copy' data-copy='{esc(s['id'])}'>Copy</button></td>"
                    f"<td><a href='{esc(s['link'])}'>{esc(title_of(s))}</a><div class='meta'>{where_text(s)} · {esc(s.get('source', ''))} · "
                    f"{esc(s.get('theme', ''))}</div></td><td class='r'>{s.get('relevance') or ''}/5</td></tr>")
    prow = []
    for p in sorted(papers, key=lambda p: -(p.get("relevance") or 0)):
        mark = " class='in'" if p["id"] in used_p else ""
        prow.append(f"<tr{mark}><td><code>{esc(p['id'])}</code> <button type='button' class='copy' data-copy='{esc(p['id'])}'>Copy</button></td>"
                    f"<td><a href='{esc(p['link'])}'>{esc(p.get('title', ''))}</a><div class='meta'>{esc(p.get('journal', ''))}</div></td>"
                    f"<td class='r'>{p.get('relevance') or ''}/5</td></tr>")
    return (f"<section class='tools'><h2>Other stories of this week</h2><p>Stories already in the issue are shaded. To swap one, "
            f"copy a code and paste it in place of a code in the issue file.</p>"
            f"<div class='tw'><table class='alt'><tr><th>Code</th><th>Story</th><th>Rating</th></tr>{''.join(rows)}</table></div>"
            + (f"<details><summary>{len(small)} more stories rated 3/5</summary><div class='tw'><table class='alt'>"
               f"{''.join(small)}</table></div></details>" if small else "")
            + (f"<h2>Research papers of this week</h2><div class='tw'><table class='alt'><tr><th>Code</th><th>Paper</th><th>Rating</th></tr>"
               f"{''.join(prow)}</table></div>" if prow else "") + "</section>")


def preview_html(key, issue, error, digests, cfg):
    repo = site_builder.repository(cfg)
    edit = f"https://github.com/{repo}/edit/main/data/geonews/{key}.yaml"
    upload = f"https://github.com/{repo}/upload/main/data/geonews/photos"
    if error:
        state = (f"<div class='bar err'><b>This issue cannot be shown:</b> {esc(error)}. Open the file, correct it and commit; "
                 f"the preview is rebuilt within a few minutes.</div>")
    elif issue["status"] == "approved":
        state = (f"<div class='bar ok'><b>Published.</b> Members see it at <a href='../{key}.html'>{esc(page_url(cfg, key))}</a>. "
                 f"Changes to the file update the published page too.</div>")
    else:
        state = ("<div class='bar draft'><b>Draft — not public yet.</b> Members cannot find this page. To publish, change "
                 "<code>status: draft</code> to <code>status: approved</code> in the issue file and commit.</div>")
    probs = ("".join(f"<li>{esc(p)}</li>" for p in issue["problems"]) if issue else "")
    problems = f"<div class='bar err'><b>Please check:</b><ul>{probs}</ul></div>" if probs else ""
    tools = (f"<div class='toolbar'><a class='btn' href='{esc(edit)}'>✏️ Edit this issue on GitHub</a>"
             f"<a class='btn alt' href='{esc(upload)}'>📷 Upload a photo</a>"
             f"<a class='btn alt' href='../archive.html'>All published issues</a></div>")
    parts = [f"<div class='editor'><div class='ed-k'>MPC editor · preview of week {week_no(key)}</div>{state}{problems}{tools}</div>"]
    if issue:
        parts.append(issue_html(issue, cfg, "../"))
        text = linkedin_text(issue, cfg)
        card = linkedin_card(issue, cfg)
        li = settings(cfg)["linkedin_page"]
        parts.append(f"<section class='tools'><h2>LinkedIn post</h2><p>Check the text, copy it, download the picture, and post both "
                     f"on the ISSMGE LinkedIn page" + (f" (<a href='{esc(li)}'>open it</a>)" if li else "") + ".</p>"
                     f"<textarea id='li-text' rows='14' readonly>{esc(text)}</textarea>"
                     f"<div class='toolbar'><button type='button' class='btn copy' data-copy-from='li-text'>Copy the text</button>"
                     f"<button type='button' class='btn alt' id='li-save' data-week='{key}'>Download the picture</button></div>"
                     f"<div class='li-wrap'>{card}</div></section>")
    parts.append(alternatives_html(key, issue, digests, cfg))
    return "".join(parts)


# ------------------------------------------------------------------ build
def build(ctx):
    """docs/geonews/: index.html (newest published issue), <week>.html for each published issue, archive.html,
    and preview/<week>.html for every issue file, draft or published."""
    cfg, digests = ctx["cfg"], ctx["digests"]
    stories, papers = all_items(digests)
    for p in papers.values():
        p["_paper"] = True
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "preview").mkdir(exist_ok=True)
    if PHOTOS.is_dir():
        (OUT / "photos").mkdir(exist_ok=True)
        for f in PHOTOS.iterdir():
            if f.is_file() and f.suffix.lower() in PHOTO_EXT:
                shutil.copy2(f, OUT / "photos" / f.name)
    loaded = []
    for path in issue_files():
        try:
            issue, error = load_issue(path, stories, papers), ""
        except ValueError as ex:
            issue, error = None, str(ex)
        loaded.append((path.stem, issue, error))
    published = [i for _, i, _ in loaded if i and i["status"] == "approved" and (i["highlights"] or i["around"])]
    keys = [i["key"] for i in published]
    count = len(keys)
    opts = settings(cfg)
    js = "<script src='../../assets/geonews.js' defer></script>"
    for key, issue, error in loaded:
        site_builder.write(OUT / "preview" / f"{key}.html",
                           shell(cfg, f"Preview · {opts['name']} · week {week_no(key)}", preview_html(key, issue, error, digests, cfg),
                                 "../", "Preview for the MPC editor", js, noindex=True))
    for n, issue in enumerate(published):
        body = issue_html(issue, cfg, "", number=count - n) + nav_html(issue["key"], keys, "")
        site_builder.write(OUT / f"{issue['key']}.html",
                           shell(cfg, f"{opts['name']} · {week_span(issue['key'])}", body, "",
                                 f"Geotechnical news from around the world, {week_span(issue['key'])}"))
    if published:
        latest = published[0]
        body = (issue_html(latest, cfg, "", number=count) + nav_html(latest["key"], keys, "")
                + ("<div class='gn-main'><h2>Past issues</h2>" + archive_html(published[1:5], cfg, "")
                   + (f"<p><a href='archive.html'>All {count} issues</a></p>" if count > 5 else "") + "</div>"
                   if count > 1 else ""))
    else:
        body = (f"<header class='gn-head'><div class='mast'>{site_builder.MPC_MARK}<div><div class='kicker'>ISSMGE · "
                f"Magazine Presidential Committee (MPC)</div><h1>{esc(opts['name'])}</h1></div></div></header>"
                "<div class='stripe'></div><div class='gn-main'><p class='intro'>Every week, the geotechnical news from around "
                "the world, chosen by the ISSMGE Magazine Presidential Committee (MPC). The first issue is coming soon.</p></div>")
    site_builder.write(OUT / "index.html", shell(cfg, f"{opts['name']} · ISSMGE", body, "",
                                                 "Geotechnical news from around the world, every week, for ISSMGE members"))
    arc = (f"<header class='gn-head'><div class='mast'>{site_builder.MPC_MARK}<div><div class='kicker'>ISSMGE · "
           f"Magazine Presidential Committee (MPC)</div><h1>{esc(opts['name'])}</h1></div></div>"
           f"<div class='chips'><span class='no'>All issues</span><span>{count} published</span></div></header>"
           f"<div class='stripe'></div><div class='gn-main'>{archive_html(published, cfg, '')}</div>")
    site_builder.write(OUT / "archive.html", shell(cfg, f"All issues · {opts['name']}", arc, "",
                                                   "Every issue of Geo-News Weekly"))


# ------------------------------------------------------------------ e-mails
def load_sent():
    try:
        d = json.loads(SENT_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    return {k: dict(d.get(k) or {}) for k in ("draft", "approved")}


def save_sent(rec):
    DATA.mkdir(parents=True, exist_ok=True)
    SENT_FILE.write_text(json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")


def email_draft(key, cfg):
    n = notify()
    site, repo = site_builder.site_url(cfg), site_builder.repository(cfg)
    prev = f"{site}geonews/preview/{key}.html"
    edit = f"https://github.com/{repo}/edit/main/data/geonews/{key}.yaml"
    body = (n.m_p(f"The draft of {esc(settings(cfg)['name'])} for {esc(week_span(key))} is ready.", 15, n.INK)
            + n.m_p("1. " + n.m_link(prev, "Look at the draft", n.LINK, 600) + " (it also lists the week's other stories).", 14, n.INK)
            + n.m_p("2. " + n.m_link(edit, "Change it on GitHub", n.LINK, 600)
                    + ": swap stories, edit texts, add photos.", 14, n.INK)
            + n.m_p("3. To publish, change <b>status: draft</b> to <b>status: approved</b> and commit. "
                    "The LinkedIn post then comes to you by e-mail.", 14, n.INK))
    html = n.m_shell(settings(cfg)["name"], f"Draft ready: week {week_no(key)}", esc(week_span(key)), body, cfg,
                     "You receive this because the weekly Geo-News page needs the MPC's approval.")
    return f"Geo-News Weekly draft ready for approval · {week_span(key)}", html


def email_approved(issue, cfg):
    n = notify()
    key = issue["key"]
    prev = f"{site_builder.site_url(cfg)}geonews/preview/{key}.html"
    text = esc(linkedin_text(issue, cfg)).replace("\n", "<br>")
    body = (n.m_p(f"Week {week_no(key)} is published: " + n.m_link(page_url(cfg, key), "open the page", n.LINK, 600) + ".", 15, n.INK)
            + n.m_p("The LinkedIn post for the ISSMGE page is below. The picture to go with it is on the "
                    + n.m_link(prev, "preview page", n.LINK, 600) + " (Download the picture).", 14, n.INK)
            + f"<div style='border:1px solid #e2e7ee;border-radius:8px;padding:12px 14px;font:14px/1.5 Arial,sans-serif;"
              f"color:#1b2430;background:#f6f8fb'>{text}</div>")
    html = n.m_shell(settings(cfg)["name"], f"Published: week {week_no(key)}", esc(week_span(key)), body, cfg,
                     "You receive this because a Geo-News Weekly issue was approved.")
    return f"Geo-News Weekly published · LinkedIn post ready · {week_span(key)}", html


def auto(cfg, today=None):
    n = notify()
    today = today or n.cairo_today()
    digests = site_builder.load_digests()
    key = n.last_week(today)
    if write_draft(digests, key, cfg):
        print(f"Geo-News: draft of {key} written to data/geonews/{key}.yaml")
    rec = load_sent()
    stories, papers = all_items(digests)
    changed = False
    for path in issue_files():
        try:
            issue = load_issue(path, stories, papers)
        except ValueError as ex:
            print(f"Geo-News: {path.name} cannot be read: {ex}")
            continue
        k = issue["key"]
        if issue["status"] == "draft" and k not in rec["draft"] and k not in rec["approved"]:
            subject, html = email_draft(k, cfg)
            label = "draft"
        elif issue["status"] == "approved" and k not in rec["approved"] and (issue["highlights"] or issue["around"]):
            subject, html = email_approved(issue, cfg)
            label = "approved"
        else:
            continue
        try:
            sent, status = n.deliver(subject, html, cfg)
        except n.NotifyError as ex:
            print(f"Geo-News: the {label} e-mail for {k} was not sent: {ex}")
            continue
        print(f"Geo-News: {label} e-mail for {k}: {status}")
        if sent:
            rec[label][k] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            changed = True
    if changed:
        save_sent(rec)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Geo-News Weekly: drafts, pages and e-mails.")
    ap.add_argument("--auto", action="store_true", help="write last week's draft if missing; send e-mails not yet sent")
    ap.add_argument("--draft", action="store_true", help="write a draft now")
    ap.add_argument("--week", help="with --draft: the week, e.g. 2026-W44 (default: last week)")
    ap.add_argument("--force", action="store_true", help="with --draft: replace an existing file")
    args = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(site_builder.ROOT / "config.yaml").read_text(encoding="utf-8"))
    if args.draft:
        key = args.week or notify().last_week(notify().cairo_today())
        if not KEY.match(key):
            ap.error("give the week as 2026-W44")
        ok = write_draft(site_builder.load_digests(), key, cfg, force=args.force)
        print(f"Draft of {key} " + ("written." if ok else "not written: it exists (use --force) or the week has no stories."))
        return 0
    if args.auto:
        auto(cfg)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
