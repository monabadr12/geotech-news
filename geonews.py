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
     by its code, rewrites a text or headline, the key number or the place. Every change rebuilds the preview.
  4. To publish, the editor changes  status: draft  to  status: approved. The issue then appears on
     geonews/index.html (newest issue) and in the archive (geonews/archive.html), and the LinkedIn
     post is e-mailed to the editorial team, ready to copy onto the ISSMGE LinkedIn page.

    python geonews.py --auto                 after each scan or edit: write last week's draft when it is
                                             missing, and send the e-mails not yet sent
    python geonews.py --draft [--week 2026-W44] [--force]
                                             write a draft now (--force replaces an existing draft file)

Pictures: no photos. Each story shows where it happened: a satellite view of the site (Sentinel-2 cloudless
by EOX, free with credit) when the place is known exactly, otherwise a small map of the country (Natural Earth).
Claude adds to each story of the draft the key number of its headline, where it happened (latitude and
longitude) and the language and web site of the outlet; the editor can change all of them.
Adverts: each week the home page of every outlet in the issues is read once (the result is kept for 30 days
in data/geonews/ads.json) and the advertising systems on it are counted; an outlet with many is marked
"This site may show many adverts". The editor can set adverts: yes or no for any story.

data/geonews/sent.json records the e-mails sent: {"draft": {week: time}, "approved": {week: time}}.
"""
import argparse
import datetime as dt
import json
import math
import re
import sys
from pathlib import Path

import yaml

import site_builder

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "geonews"
SENT_FILE = DATA / "sent.json"
OUT = site_builder.DOCS / "geonews"
ADS_FILE = DATA / "ads.json"
EDITS = DATA / "edits"   # saves from the story editor on the preview page: <week>--<time>.json, the newest wins
MPC_URL = "https://www.issmge.org/committees/presidential-committees/magazine-presidential-committee"
ADS_DAYS = 30        # how long the advert count of a site is kept
ADS_MANY = 3         # this many different advertising systems on a home page = "many adverts"
# advertising systems, by a piece of the address or code that appears on a page that uses them
AD_MARKERS = {"Google Ads": ("googlesyndication.com", "doubleclick.net", "adservice.google", "googletag", "pagead2"),
              "Amazon": ("amazon-adsystem.com",), "Taboola": ("taboola.com",), "Outbrain": ("outbrain.com",),
              "Criteo": ("criteo.com", "criteo.net"), "Prebid": ("prebid",), "PubMatic": ("pubmatic.com",),
              "Xandr": ("adnxs.com",), "Teads": ("teads.tv",), "MGID": ("mgid.com",), "Yandex": ("an.yandex.ru", "yandex.ru/ads"),
              "Media.net": ("media.net",), "Rubicon": ("rubiconproject.com",), "Index Exchange": ("casalemedia.com",),
              "OpenX": ("openx.net",), "Sovrn": ("lijit.com",), "Revcontent": ("revcontent.com",), "Ezoic": ("ezoic",),
              "AdSense auto ads": ("adsbygoogle",)}
# the magazine's eight theme accents (ISSMGE Magazine Visual Identity Guide)
GUIDE_COLORS = {"Sustainability & the Energy Transition": "#4F6B58", "Digital Geotechnics": "#456779",
                "Hazards & Resilience": "#96533F", "Ground Improvement & Innovation": "#3F7371",
                "Infrastructure & the Underground City": "#5B6573", "Offshore, Coasts & Water": "#286D82",
                "Characterisation & Modelling": "#80652F", "Geotechnics & Society": "#795F75"}
esc = site_builder.esc
KEY = re.compile(r"^\d{4}-W\d{2}$")
DEFAULTS = {"name": "Geo-News Weekly", "highlights": 5, "around": 8, "research": 3, "events_days": 60,
            "events_max": 6, "hashtags": "#Geotechnics #GeotechnicalEngineering #ISSMGE #CivilEngineering",
            "linkedin_page": "", "editor": ""}
INTRO = ("Dear colleagues, here are the geotechnical stories from around the world that caught our eye last week. "
         "We gather them from news sources in 20 languages, and the ISSMGE Magazine Presidential Committee (MPC) "
         "checks every issue before it is published.")
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
    return GUIDE_COLORS.get(theme or "", "#625C60")


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


# ------------------------------------------------------------------ key numbers, places, languages, adverts
SCRIPTS = [(r"[぀-ヿ]", "Japanese"), (r"[가-힯]", "Korean"), (r"[一-鿿]", "Chinese"),
           (r"[Ѐ-ӿ]", "Russian"), (r"[؀-ۿ]", "Arabic"), (r"[ऀ-ॿ]", "Hindi"),
           (r"[฀-๿]", "Thai"), (r"[Ͱ-Ͽ]", "Greek"), (r"[֐-׿]", "Hebrew")]


def guess_language(s):
    """The outlet's language when Claude is not available: English when the headline needed no translation,
    else from the alphabet of the original headline ("" = another language)."""
    if not s.get("title_en"):
        return "English"
    for pattern, name in SCRIPTS:
        if re.search(pattern, s.get("title") or ""):
            return name
    return ""


def domain_of(url):
    m = re.match(r"^https?://([^/:?#]+)", str(url or ""), re.I)
    host = m.group(1).lower() if m else ""
    return "" if host.endswith("news.google.com") else re.sub(r"^www\.", "", host)


def enrich(items, cfg):
    """{story id: {"number", "number_label", "language", "lat", "lon", "satellite", "site"}} from Claude, for the
    stories of a draft; {} without an Anthropic key or when the call fails (the draft then uses guesses)."""
    import os
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or not items:
        return {}
    try:
        import anthropic
    except ImportError:
        return {}
    listing = "\n".join(
        f'{i}. headline: {s.get("title")} | English: {title_of(s)} | outlet: {s.get("source")} | country: {s.get("country")} '
        f'| place: {s.get("place")} | link: {s.get("link") if "news.google" not in str(s.get("link")) else "(via Google News)"}'
        for i, s in enumerate(items))
    schema = {"type": "object", "properties": {"stories": {"type": "array", "items": {
        "type": "object", "properties": {
            "id": {"type": "integer"}, "number": {"type": "string"}, "number_label": {"type": "string"},
            "language": {"type": "string"}, "lat": {"type": "number"}, "lon": {"type": "number"},
            "satellite": {"type": "boolean"}, "site": {"type": "string"}},
        "required": ["id", "number", "number_label", "language", "lat", "lon", "satellite", "site"],
        "additionalProperties": False}}}, "required": ["stories"], "additionalProperties": False}
    prompt = f"""For each news story below, return:
- "number": the most striking figure stated in the headline itself (e.g. "96%", "4.5 km", "US$16.5 bn", "3"), copied from the headline; "" when the headline states no figure. Never compute, estimate or take a figure from elsewhere.
- "number_label": at most 8 words saying what the figure counts (e.g. "of strongly shaken sites liquefied again"); "" when number is "".
- "language": the language the outlet publishes this story in, as an English name (e.g. "English", "Japanese", "Spanish"), judged from the original headline.
- "lat", "lon": the latitude and longitude of the place the story is about, as exactly as the headline and place allow (the site, else the town, else the region, else the country's centre).
- "satellite": true only when lat/lon point at a specific site or town small enough for a satellite view at about 10 km across to show it (a dam, a tunnel, a landslide, a town); false for a region, a country or a general story.
- "site": the outlet's web address without "https://" or "www." (e.g. "japannews.yomiuri.co.jp"); "" if you do not know it.

Stories:
{listing}"""
    try:
        client = anthropic.Anthropic(api_key=key, max_retries=3)
        ccfg = cfg.get("claude") or {}
        r = client.messages.create(model=ccfg.get("model", "claude-haiku-5-5"), max_tokens=8000,
                                   output_config={"effort": ccfg.get("effort", "low"),
                                                  "format": {"type": "json_schema", "schema": schema}},
                                   messages=[{"role": "user", "content": prompt}])
        text = next((b.text for b in r.content if b.type == "text"), "")
        out = {}
        for d in json.loads(text)["stories"]:
            i = int(d["id"])
            if 0 <= i < len(items):
                out[items[i]["id"]] = d
        return out
    except Exception as ex:  # a draft without key numbers is still a draft
        print(f"Geo-News: Claude could not add key numbers and places ({type(ex).__name__}: {str(ex)[:120]})")
        return {}


def load_ads():
    try:
        return json.loads(ADS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def check_ads(sites, today=None):
    """Count the advertising systems on the home page of each site not checked in the last ADS_DAYS days;
    the results are kept in data/geonews/ads.json. True when the file changed."""
    import requests
    today = today or dt.date.today()
    rec, changed = load_ads(), False
    for site in sorted({x for x in sites if x}):
        old = rec.get(site) or {}
        try:
            fresh = (today - dt.date.fromisoformat(old.get("checked", "")[:10])).days < ADS_DAYS
        except ValueError:
            fresh = False
        if fresh:
            continue
        try:
            r = requests.get(f"https://{site}/", timeout=20, headers={"User-Agent": "Mozilla/5.0 (compatible; GeoNewsWeekly/1.0)"})
            page = r.text.lower()
            found = sorted(name for name, marks in AD_MARKERS.items() if any(m in page for m in marks))
            rec[site] = {"checked": today.isoformat(), "systems": found, "many": len(found) >= ADS_MANY}
        except Exception as ex:  # unreachable: unknown, tried again next time
            rec[site] = {"checked": "", "systems": [], "many": None, "error": type(ex).__name__}
        changed = True
        print(f"Geo-News: adverts on {site}: {', '.join(rec[site]['systems']) or rec[site].get('error') or 'none found'}")
    if changed:
        DATA.mkdir(parents=True, exist_ok=True)
        ADS_FILE.write_text(json.dumps(rec, indent=1, sort_keys=True), encoding="utf-8")
    return changed


# ------------------------------------------------------------------ the issue file
def q(text):
    """A YAML text in double quotes (JSON's quoting is valid YAML)."""
    return json.dumps(" ".join(str(text or "").split()), ensure_ascii=False)


def note(text):
    return " ".join(str(text or "").replace("#", "").split())[:110]


def item_lines(s, info, kind):
    """The lines of one story in the issue file: its code, headline (as a note) and the fields the editor may change."""
    n = notify()
    lat, lon = info.get("lat"), info.get("lon")
    lines = [f"  - story: {s['id']}   # {note(title_of(s))} ({note(n.country_name(s.get('country')) or 'global')})",
             '    title: ""   # empty keeps the headline above']
    lines.append(f"    text: {q(s.get('angle'))}" if kind == "highlights"
                 else '    text: ""   # optional: one line')
    lines += [f"    number: {q(info.get('number'))}   # the key number shown large; \"\" for none",
              f"    number_label: {q(info.get('number_label'))}",
              f"    language: {q(info.get('language', guess_language(s)))}   # the news site's language",
              f"    lat: {'' if lat is None else round(float(lat), 4)}",
              f"    lon: {'' if lon is None else round(float(lon), 4)}",
              f"    satellite: {'yes' if info.get('satellite') else 'no'}   # yes: satellite view of the place; no: map of the country",
              f"    site: {q(info.get('site') or domain_of(s.get('link')))}   # the news site, for the advert check",
              "    adverts: auto   # auto (checked each week), yes or no"]
    return lines


def draft_text(key, highlights, around, research, cfg, info=None):
    info = info or {}
    site = site_builder.site_url(cfg)
    lines = [f"# {settings(cfg)['name']} · {week_span(key)} ({key})",
             "#",
             "# HOW TO EDIT THIS ISSUE (on GitHub: press the pencil, change the file, then press \"Commit changes\")",
             f"#  - See it as members will:   {site}geonews/preview/{key}.html",
             "#    That page also lists every other story of the week, each with its code.",
             "#  - Swap a story: replace its code (after story: or paper:) with another code from the preview page.",
             "#    The other lines of that story (number, place, language) then belong to the old story: correct them",
             "#    or leave them empty (\"\") and the page uses the new story's country map and no key number.",
             "#  - Change a headline or a text: write it between the quotes. An empty title keeps the original headline.",
             "#  - Key number: the figure shown large (number) and what it counts (number_label); \"\" for none.",
             "#  - Place: lat and lon of the site; satellite: yes shows a satellite view of it, no a map of the country.",
             "#  - Remove a story: delete its lines (from the - to the line before the next -).",
             "#  - PUBLISH: change  status: draft  to  status: approved  and commit. The page goes public within a few",
             "#    minutes and the LinkedIn post is e-mailed to the editorial team.",
             "",
             "status: draft",
             f"intro: {q(INTRO)}",
             "",
             "highlights:   # the first one is the story of the week"]
    for s in highlights:
        lines += item_lines(s, info.get(s["id"], {}), "highlights")
    lines += ["", "around_the_world:"]
    for s in around:
        lines += item_lines(s, info.get(s["id"], {}), "around")
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
    info = enrich(hl + ar, cfg)
    DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(draft_text(key, hl, ar, rs, cfg, info), encoding="utf-8")
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
    edit, edited = latest_edit(key)
    if edit:
        raw = apply_edit(raw, edit)

    def text(v):
        return " ".join(str(v or "").split())

    def num(v, lo, hi):
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        return x if lo <= x <= hi else None

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
            entry = {"s": found, "title": text(it.get("title")), "text": text(it.get("text"))}
            if kind == "story":
                entry.update(number=text(it.get("number")), number_label=text(it.get("number_label")),
                             language=text(it.get("language")) or guess_language(found),
                             lat=num(it.get("lat"), -90, 90), lon=num(it.get("lon"), -180, 180),
                             satellite=it.get("satellite") in (True, "yes", "Yes", "true"),
                             site=text(it.get("site")) or domain_of(found.get("link")),
                             adverts={True: "yes", False: "no"}.get(it.get("adverts"), text(it.get("adverts")).lower() or "auto"))
                if entry["satellite"] and (entry["lat"] is None or entry["lon"] is None):
                    entry["satellite"] = False
            out.append(entry)
        return out

    status = text(raw.get("status")).lower() or "draft"
    if status not in ("draft", "approved"):
        problems.append(f"status is \"{status}\": write draft or approved")
    return {"key": key, "status": status, "intro": text(raw.get("intro")) or INTRO,
            "highlights": items("highlights", "story", stories), "around": items("around_the_world", "story", stories),
            "research": items("research", "paper", papers),
            "events": text(raw.get("events")).lower() != "none",
            "magazine_note": text(raw.get("magazine_note")), "magazine_link": site_builder.safe_url(text(raw.get("magazine_link")))
            if text(raw.get("magazine_link")) else "", "problems": problems, "edited": edited}


def latest_edit(key):
    """(the newest save of the story editor for a week, its file name's time) or (None, "")."""
    files = sorted(EDITS.glob(f"{key}--*.json")) if EDITS.is_dir() else []
    for f in reversed(files):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            print(f"Geo-News: {f.name} is not a readable save of the story editor; it is left out.")
            continue
        if isinstance(d, dict):
            return d, f.stem.split("--", 1)[1]
    return None, ""


def apply_edit(raw, edit):
    """The issue file with a save of the story editor applied: the stories in the editor's order, with its headlines,
    texts and key numbers; a story kept from the file keeps its place, language and advert note."""
    raw = dict(raw)
    base = {str(it.get("story")): it for name in ("highlights", "around_the_world")
            for it in (raw.get(name) or []) if isinstance(it, dict)}
    for name in ("highlights", "around_the_world"):
        if isinstance(edit.get(name), list):
            out = []
            for e in edit[name]:
                if not isinstance(e, dict) or not e.get("story"):
                    continue
                it = dict(base.get(str(e["story"]), {}))
                it["story"] = str(e["story"])
                for k in ("title", "text", "number", "number_label"):
                    if k in e:
                        it[k] = e[k]
                out.append(it)
            raw[name] = out
    for k in ("status", "intro"):
        if edit.get(k):
            raw[k] = edit[k]
    if isinstance(edit.get("research"), list):
        keep = {str(x) for x in edit["research"]}
        raw["research"] = [r for r in (raw.get("research") or []) if isinstance(r, dict) and str(r.get("paper")) in keep]
    return raw


def editor_data(key, issue, digests, cfg):
    """What the story editor on the preview page needs: the issue as it stands and the week's other stories."""
    n = notify()
    stories, _ = week_items(digests, key)
    pool = {s["id"]: s for s in stories if (s.get("relevance") or 0) >= 3}
    for it in issue["highlights"] + issue["around"]:
        pool.setdefault(it["s"]["id"], it["s"])

    def story(s):
        return {"t": title_of(s), "w": n.country_name(s.get("country")) or "Global", "f": flag(s.get("country")),
                "src": s.get("source", ""), "th": s.get("theme", ""), "r": s.get("relevance") or 0,
                "a": s.get("angle", ""), "l": s.get("link", "")}

    def entry(it):
        return {"story": it["s"]["id"], "title": it["title"], "text": it["text"], "number": it.get("number", ""),
                "number_label": it.get("number_label", "")}
    order = sorted(pool.values(), key=lambda s: (-(s.get("relevance") or 0), -(s.get("rank") or 0)))
    return {"week": key, "span": week_span(key), "repo": site_builder.repository(cfg), "status": issue["status"],
            "intro": issue["intro"], "highlights": [entry(it) for it in issue["highlights"]],
            "around_the_world": [entry(it) for it in issue["around"]],
            "research": [it["s"]["id"] for it in issue["research"]],
            "stories": {s["id"]: story(s) for s in order}, "order": [s["id"] for s in order]}


def issue_files():
    return sorted((p for p in DATA.glob("*.yaml") if KEY.match(p.stem)), reverse=True)


# ------------------------------------------------------------------ pictures: locator maps and satellite views
_BOXES = {}


def boxes():
    """The bounding box of each country's outline on the world map, in map units."""
    if not _BOXES:
        for k, v in geomap().world()["countries"].items():
            d = v.get("d")
            if not d:
                continue
            xs, ys, x, y = [], [], 0.0, 0.0
            for cmd, args in re.findall(r"([MLlmz])([^MLlmz]*)", d):
                nums = [float(t) for t in re.findall(r"-?\d+(?:\.\d+)?", args)]
                rel = cmd in "lm"
                if cmd in "Mm" and len(nums) >= 2:
                    x, y = (x + nums[0], y + nums[1]) if cmd == "m" else (nums[0], nums[1])
                    xs.append(x); ys.append(y); nums = nums[2:]
                elif cmd == "z":
                    continue
                for i in range(0, len(nums) - 1, 2):
                    x, y = (x + nums[i], y + nums[i + 1]) if rel else (nums[i], nums[i + 1])
                    xs.append(x); ys.append(y)
            if xs:
                _BOXES[k] = (min(xs), min(ys), max(xs), max(ys))
    return _BOXES


def locator(it, color, cls="loc", w_max=1000, aspect=4 / 3):
    """A small map of the story's country (and its neighbours) with the place marked."""
    g = geomap()
    s = it["s"]
    code = g.canonical(s.get("country"))
    if it.get("lat") is not None and it.get("lon") is not None:
        px, py = g.project(it["lon"], it["lat"])
    else:
        pt = g.label_point(code)
        if not pt:  # a global story: the whole world
            return (f"<svg class='{cls}' viewBox='-2600 -1250 5250 2050' preserveAspectRatio='xMidYMid slice' aria-hidden='true'>"
                    f"<rect x='-2600' y='-1250' width='5250' height='2050' fill='#dfe8ec'/>"
                    f"<path d='{g.world()['land']}' fill='#e9e5df'/>"
                    + "".join(f"<path d='{v['d']}' fill='#e9e5df'/>" for v in g.world()["countries"].values() if v.get("d"))
                    + "</svg>")
        px, py = pt
    b = boxes().get(code)
    if b:
        x0, y0, x1, y1 = b
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        w = max((x1 - x0) * 1.5, (y1 - y0) * 1.5 * aspect, 220)
        if w > w_max:
            w, cx, cy = w_max, px, py
    else:
        w, cx, cy = 400, px, py
    h = w / aspect
    vx, vy = cx - w / 2, cy - h / 2
    paths = []
    for k, v in g.world()["countries"].items():
        bb = boxes().get(k)
        if not bb or bb[2] < vx or bb[0] > vx + w or bb[3] < vy or bb[1] > vy + h:
            continue
        paths.append(f"<path d='{v['d']}' fill='{color if k == code else '#e9e5df'}'"
                     + (" fill-opacity='.55'" if k == code else "") + "/>")
    r = w / 28
    return (f"<svg class='{cls}' viewBox='{vx:.0f} {vy:.0f} {w:.0f} {h:.0f}' preserveAspectRatio='xMidYMid slice' aria-hidden='true'>"
            f"<rect x='{vx:.0f}' y='{vy:.0f}' width='{w:.0f}' height='{h:.0f}' fill='#dfe8ec'/>"
            f"<g stroke='#fff' stroke-width='{w / 250:.1f}'>{''.join(paths)}</g>"
            f"<circle cx='{px:.0f}' cy='{py:.0f}' r='{r * 1.9:.0f}' fill='{color}' fill-opacity='.25'/>"
            f"<circle cx='{px:.0f}' cy='{py:.0f}' r='{r:.0f}' fill='{color}' stroke='#fff' stroke-width='{r / 3:.0f}'/></svg>")


def satellite(lat, lon, z=13):
    """A satellite view (Sentinel-2 cloudless by EOX) of about 3 x 3 map tiles centred on the place."""
    n = 2 ** z
    fx = (lon + 180) / 360 * n
    lr = math.radians(lat)
    fy = (1 - math.log(math.tan(lr) + 1 / math.cos(lr)) / math.pi) / 2 * n
    tx, ty = int(fx), int(fy)
    imgs = "".join(
        f"<img src='https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{ty + dy}/{(tx + dx) % n}.jpg' alt='' "
        f"loading='lazy' onerror=\"this.style.visibility='hidden'\" style='left:{(dx + 1) * 256}px;top:{(dy + 1) * 256}px'>"
        for dy in (-1, 0, 1) for dx in (-1, 0, 1))
    ox, oy = (fx - tx + 1) * 256, (fy - ty + 1) * 256
    return (f"<div class='sat'><div class='tiles' style='left:calc(50% - {ox:.0f}px);top:calc(50% - {oy:.0f}px)'>{imgs}</div>"
            f"<span class='satpin'></span><span class='satlbl'>🛰 Satellite view</span><span class='satcr'>Sentinel-2 · EOX</span></div>")


def place_name(it):
    s = it["s"]
    return s.get("place") or notify().country_name(s.get("country")) or "Global"


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


def notes_html(it, ads, dark=False):
    """The small notes under a story: its language when not English, and many adverts on its site."""
    out = []
    lang = it.get("language", "English")
    if lang and lang.lower() != "english":
        out.append(f"<span class='nt'>🌐 In {esc(lang)} · use your browser's Translate</span>")
    elif not lang:
        out.append("<span class='nt'>🌐 Not in English · use your browser's Translate</span>")
    many = {"yes": True, "no": False}.get(it.get("adverts"), (ads.get(it.get("site")) or {}).get("many"))
    if many:
        out.append("<span class='nt ad'>📢 This site may show many adverts</span>")
    return f"<div class='nts{' dk' if dark else ''}'>{''.join(out)}</div>" if out else ""


def key_number(it, cls="kn"):
    if not it.get("number"):
        return ""
    return f"<div class='{cls}'><b>{esc(it['number'])}</b><span>{esc(it.get('number_label', ''))}</span></div>"


def masthead(cfg, root, chips):
    return (f"<header class='mh'><div class='mh-row'><div><div class='mh-k'>ISSMGE · <a href='{MPC_URL}'>Magazine Presidential Committee (MPC)</a></div>"
            f"<h1>{esc(settings(cfg)['name'])}</h1><div class='mh-t'>Ground engineering in a changing world</div></div>"
            f"<img class='mh-logo' src='{root}../assets/issmge-logo.png' alt='ISSMGE'></div><div class='mh-rule'></div>"
            + (f"<div class='mh-meta'>{chips}</div>" if chips else "") + "</header>")


TIPS = ("<aside class='before'><b>💡 Reading tips</b><ul>"
        "<li>🌐 Story in another language? Use your browser's <b>Translate</b>.</li>"
        "<li>📰 Headlines open the original news site; sites with many adverts are marked.</li></ul></aside>")


def issue_html(issue, cfg, root, number=None):
    """The issue itself: masthead, map, highlights, around the world, research, events, magazine box."""
    opts = settings(cfg)
    hl, ar = issue["highlights"], issue["around"]
    ads = load_ads()
    chips = (f"<span class='no'>Week {week_no(issue['key'])} · {issue['key'][:4]}</span><span>{esc(week_span(issue['key']))}</span>"
             + (f"<span>Issue {number}</span>" if number else ""))
    out = [masthead(cfg, root, chips), "<div class='gn-main'>", f"<p class='intro'>{esc(issue['intro'])}</p>"
           + (f"<p class='editor-line'>Edited by {esc(opts['editor'])}</p>" if opts["editor"] else ""), TIPS]
    if hl or ar:
        out.append(f"<section class='mapcard'><h2>This week on the map</h2>{map_svg(issue)}"
                   "<div class='mapkey'><span><i class='k1'></i>Highlights</span><span><i class='k2'></i>Around the world</span>"
                   "<span>Tap a number to read the story</span></div></section>")
    if hl:
        out.append("<h2>Highlights</h2>")
        lead = hl[0]
        s = lead["s"]
        c = theme_color(s.get("theme"))
        media = (satellite(lead["lat"], lead["lon"], 13) if lead.get("satellite") else locator(lead, c, "loc full"))
        mini = (f"<div class='cv-loc'>{locator(lead, c)}<span>{esc(place_name(lead))}</span></div>" if lead.get("satellite")
                else f"<span class='plc'>📍 {esc(place_name(lead))}</span>")
        out.append(f"<article class='cover' id='s1' style='--c:{c}'><div class='cv-text'>"
                   f"<div class='cv-k'><b class='num w'>1</b> Story of the week</div>{key_number(lead)}"
                   f"<h3><a href='{esc(s['link'])}'>{headline_html(lead)}</a></h3>"
                   f"<div class='cv-meta'>{where_text(s)} · {esc(s.get('source', ''))}</div>"
                   + (f"<p>{esc(lead['text'])}</p>" if lead["text"] else "") + notes_html(lead, ads, True)
                   + f"<span class='cv-tag'>{esc(s.get('theme') or '')}</span></div>"
                   f"<a class='cv-media' href='{esc(s['link'])}'>{media}{mini}</a></article>")
        for i, it in enumerate(hl[1:], 2):
            s = it["s"]
            c = theme_color(s.get("theme"))
            media = satellite(it["lat"], it["lon"], 12) if it.get("satellite") else locator(it, c)
            mini = f"<div class='mini'>{locator(it, c)}</div>" if it.get("satellite") else ""
            out.append(f"<article class='card2' id='s{i}' style='--c:{c}'><a class='m2' href='{esc(s['link'])}'>{media}{mini}"
                       f"<span class='plc'>📍 {esc(place_name(it))}</span></a><div class='b2'>"
                       f"<div class='meta'><b class='num'>{i}</b> {where_text(s)} · {esc(s.get('source', ''))}</div>"
                       f"{key_number(it, 'kn sm')}<h3><a href='{esc(s['link'])}'>{headline_html(it)}</a></h3>"
                       + (f"<p>{esc(it['text'])}</p>" if it["text"] else "") + notes_html(it, ads) + f"{tag(s)}</div></article>")
    if ar:
        rows = []
        for i, it in enumerate(ar, len(hl) + 1):
            s = it["s"]
            c = theme_color(s.get("theme"))
            kn = (f"<span class='kchip'><b>{esc(it['number'])}</b> {esc(it.get('number_label', ''))}</span>"
                  if it.get("number") else "")
            rows.append(f"<li id='s{i}' style='--c:{c}'><a class='wl' href='{esc(s['link'])}'>{locator(it, c, 'loc', 900, 1)}</a>"
                        f"<div><div class='meta'><b class='num g'>{i}</b> {where_text(s)}"
                        + (f" · {esc(s.get('place'))}" if s.get("place") else "") + "</div>"
                        f"<a class='hl' href='{esc(s['link'])}'>{headline_html(it)}</a>"
                        + (f"<div class='txt'>{esc(it['text'])}</div>" if it["text"] else "")
                        + f"{kn}<div class='src'>{esc(s.get('source', ''))}</div>{notes_html(it, ads)}</div></li>")
        out.append(f"<h2>Around the world</h2><ul class='world2'>{''.join(rows)}</ul>")
    if issue["research"]:
        rows = "".join(f"<li><a href='{esc(p['s']['link'])}'>{esc(p['title'] or p['s'].get('title', ''))}</a>"
                       f"<div class='j'>{esc(p['s'].get('journal', ''))}</div>"
                       + (f"<div>{esc(p['text'])}</div>" if p["text"] else "") + "</li>"
                       for p in issue["research"])
        out.append(f"<section class='papers'><h2>Research highlights</h2><ol>{rows}</ol></section>")
    out.append(events_html(issue, cfg, opts))
    if issue["magazine_note"]:
        link = (f" <a href='{esc(issue['magazine_link'])}'>Read it</a>" if issue["magazine_link"] else "")
        out.append(f"<div class='mag'><div class='ic'></div><div><b>From the ISSMGE Magazine</b> — "
                   f"{esc(issue['magazine_note'])}{link}</div></div>")
    out.append("</div>")
    return "".join(out)


def asset_version(name):
    """A short fingerprint of an asset, added to its address so browsers load a changed file at once."""
    import hashlib
    f = site_builder.ASSETS / name
    return hashlib.sha1(f.read_bytes()).hexdigest()[:8] if f.exists() else "1"


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
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{root}../assets/geonews.css?v={asset_version('geonews.css')}">{extra_head}
</head><body><div class="gn-wrap">
{body}
<footer class="gn-foot">Stories come from public news sources in many languages; each headline links to the original publisher,
whose site may be in another language and may show adverts. Please check details with the original source.<br>
Maps: Natural Earth. Satellite views: Sentinel-2 cloudless by EOX IT Services (contains modified Copernicus Sentinel data).<br>
<a href="{root}index.html">Latest issue</a> · <a href="{root}archive.html">All issues</a> ·
<a href="{esc(site)}">Geotechnical News Desk</a><br>Prepared by the ISSMGE <a href="{MPC_URL}">Magazine Presidential Committee (MPC)</a></footer>
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
        pic = locator(first, theme_color(first["s"].get("theme")), "loc", 900, 110 / 76) if first else ""
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


def logo_data():
    """The ISSMGE logo as a data address, so the LinkedIn picture carries it when saved as PNG."""
    import base64
    f = site_builder.ASSETS / "issmge-logo.png"
    return "data:image/png;base64," + base64.b64encode(f.read_bytes()).decode() if f.exists() else ""


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
            f"ISSMGE · MAGAZINE PRESIDENTIAL COMMITTEE (MPC)</text>"
            f"<text x='40' y='98' font-size='42' fill='#fff' font-family='Georgia,serif' font-weight='bold'>{esc(opts['name'])}</text>"
            f"<text x='1010' y='98' text-anchor='end' font-size='26' fill='#fff' font-family='Arial,sans-serif'>{esc(week_span(issue['key']))}</text>"
            f"<rect x='1036' y='14' width='146' height='94' rx='10' fill='#fff'/>"
            f"<image x='1046' y='20' width='126' height='82' href='{logo_data()}'/>"
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
    if error:
        state = (f"<div class='bar err'><b>This issue cannot be shown:</b> {esc(error)}. Open the file, correct it and commit; "
                 f"the preview is rebuilt within a few minutes.</div>")
    elif issue["status"] == "approved":
        state = (f"<div class='bar ok big'><b>✅ Published.</b> This issue is public. Members see it at "
                 f"<a href='../{key}.html'>{esc(page_url(cfg, key))}</a>.<div class='toolbar'>"
                 f"<a class='btn green' href='../{key}.html'>Open the published page</a></div>"
                 f"<small>To correct it, press ✏️ Change the stories below and save again; the published page updates too.</small></div>")
    else:
        state = ("<div class='bar draft'><b>Draft — not public yet.</b> Members cannot find this page. Change the stories "
                 "if you wish, then press <b>Approve and publish</b> in the story editor.</div>")
    probs = ("".join(f"<li>{esc(p)}</li>" for p in issue["problems"]) if issue else "")
    problems = f"<div class='bar err'><b>Please check:</b><ul>{probs}</ul></div>" if probs else ""
    tools = ("<div class='toolbar'>" + ("<button type='button' class='btn' id='ed-open'>✏️ Change the stories</button>" if issue else "")
             + f"<a class='btn alt' href='../archive.html'>All published issues</a>"
             f"<a class='btn alt small' href='{esc(edit)}'>Advanced: edit the file</a></div>")
    saved = ""
    if issue and issue.get("edited"):
        try:
            when = dt.datetime.strptime(issue["edited"][:15], "%Y%m%d-%H%M%S")
            saved = (f"<div class='ed-saved'>Last saved with the story editor: {when.day} {when:%b %Y}, "
                     f"{when:%H:%M} UTC</div>")
        except ValueError:
            pass
    data = ""
    if issue:
        blob = json.dumps(editor_data(key, issue, digests, cfg), ensure_ascii=False).replace("</", "<\\/")
        data = f"<script type='application/json' id='gn-data'>{blob}</script><div id='gn-editor'></div>"
    parts = [f"<div class='editor'><div class='ed-k'>MPC editor · preview of week {week_no(key)}</div>{state}{problems}{tools}{saved}</div>{data}"]
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
    js = f"<script src='../../assets/geonews.js?v={asset_version('geonews.js')}' defer></script>"
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
        body = (masthead(cfg, "", "") + "<div class='gn-main'><p class='intro'>Every week, the geotechnical news from around "
                "the world, chosen by the ISSMGE Magazine Presidential Committee (MPC). The first issue is coming soon.</p></div>")
    site_builder.write(OUT / "index.html", shell(cfg, f"{opts['name']} · ISSMGE", body, "",
                                                 "Geotechnical news from around the world, every week, for ISSMGE members"))
    arc = (masthead(cfg, "", f"<span class='no'>All issues</span><span>{count} published</span>")
           + f"<div class='gn-main'>{archive_html(published, cfg, '')}</div>")
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
                    + ": swap stories, edit texts, key numbers and places.", 14, n.INK)
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
    stories, papers = all_items(digests)
    sites = []
    for path in issue_files():
        try:
            issue = load_issue(path, stories, papers)
        except ValueError:
            continue
        sites += [it.get("site") for it in issue["highlights"] + issue["around"] if it.get("adverts") == "auto"]
    check_ads(sites, today)
    rec = load_sent()
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
