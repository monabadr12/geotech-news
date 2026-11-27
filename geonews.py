#!/usr/bin/env python3
"""
Geo-News Weekly: the weekly news page for ISSMGE members (docs/geonews/), its archive of past
issues, and the LinkedIn post that goes with each issue.

How an issue is made
  1. After the Monday scan, a draft of the week before (Monday to Sunday) is written to
     data/geonews/<YYYY-Www>.yaml: the week's best stories (highlights), stories from the other
     regions (around the world), a case history, new research papers, and the events coming up (added by themselves).
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

News of the week only: a week's stories are those the scan saved Monday to Sunday (the news of the weekend before is saved
on Monday or Tuesday, so it belongs to this issue). A draft takes no story published more than a few days before the
issue week (SCAN_LAG_DAYS; the scan sometimes finds older items) and nothing from encyclopedias and similar reference
sites (REFERENCE_SITES); the preview lists them apart, under "Older or reference items (not used as news)".
Links: the scan keeps many links as Google News redirects (news.google.com/rss/articles/...). The publisher's own
address is found with googlenewsdecoder for the stories of an issue (when the draft is written and when the pages are
built) and for the other stories shown on a draft's preview (when the pages are built), each link once
(data/geonews/gnews_links.json, {google link: publisher link}), gently (a pause between calls, at most GNEWS_MAX links
and GNEWS_SECONDS seconds each time the program runs). A link that cannot be decoded keeps going through Google News
(the preview says so); it is tried again on another day, on GNEWS_TRIES days at most (data/geonews/gnews_failed.json).
Case history: one well-known case per issue, after "Around the world", from the checked list in
data/geonews/case_histories.yaml (choose_case: an anniversary in the issue week or the week after it, else the next
case not used before, regions in turn; never a case used before). The draft holds its id and a text written from the
list (case_text), which the editor may change or swap for another case.
Pictures: no photos. Each story shows where it happened: a satellite view of the site (Sentinel-2 cloudless 2020
by EOX, CC BY-NC-SA 4.0, credited in the footer; data/geonews/img/LICENSE.txt) when the place is known exactly,
otherwise a small map of the country (Natural Earth).
The satellite views are made when the pages are built: the map tiles around the place are downloaded once, put
together and cut to one picture per story (data/geonews/img/<week>/), which is published with the pages; a story whose
picture cannot be downloaded shows its country map. Readers' browsers ask no other server for anything.
Claude adds to each story of the draft the key number of its headline, where it happened (latitude and
longitude) and the language and web site of the outlet; the editor can change all of them.
Adverts: each week the home page of every outlet in the issues is read once (the result is kept for 30 days
in data/geonews/ads.json) and the advertising systems on it are counted; an outlet with many is marked
"This site may show many adverts". The editor can set adverts: yes or no for any story.
Fonts, icons and flags are kept with the site, so a page asks no other server for them (no Google Fonts, no
flagcdn.com): the fonts of issmge.org (Newsreader for headings, Libre Franklin for text) in assets/fonts/, Lucide
line icons in assets/icons/ (put into the page as SVG) and the flag-icons flags in assets/flags/, each with its
licence. The e-mails use no web fonts and no icons (Gmail and Outlook show neither).

data/geonews/sent.json records the e-mails sent: {"draft": {week: time}, "approved": {week: time}}.
"""
import argparse
import datetime as dt
import json
import math
import re
import shutil
import sys
import time
from pathlib import Path

import yaml

import site_builder

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "geonews"
SENT_FILE = DATA / "sent.json"
OUT = site_builder.DOCS / "geonews"
ADS_FILE = DATA / "ads.json"
EDITS = DATA / "edits"   # saves from the story editor on the preview page: <week>--<time>.json, the newest wins
CASES_FILE = DATA / "case_histories.yaml"   # the case histories of the Case history section (a checked list)
GNEWS_FILE = DATA / "gnews_links.json"      # Google News links turned into the publisher's own: {google link: publisher link}
GNEWS_FAILED = DATA / "gnews_failed.json"   # Google News links that could not be decoded: {google link: [days, last day]}
IMG = DATA / "img"                          # the satellite pictures of the stories: img/<week>/<story>-<place>.jpg
GNEWS_PAUSE = 1      # seconds to wait after each link decoded through Google News
GNEWS_MAX = 80       # at most this many links decoded each time the program runs; the rest the next times
GNEWS_SECONDS = 120  # and for at most this many seconds (each link takes about 3 seconds)
GNEWS_TRIES = 3      # a link that could not be decoded on this many different days is not tried again
SAT_TILES = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{z}/{y}/{x}.jpg"
SAT_PX = 640         # a satellite picture: 640 x 640 pixels, the place in the middle, one map pixel per screen pixel
SCAN_LAG_DAYS = 3    # the scan saves a story up to this many days after it was published: older items are not news
# encyclopedias and similar reference sites: their entries turn up in news searches, but they are background, not news
REFERENCE_SITES = ("britannica.com", "wikipedia.org", "wikiwand.com", "wikimedia.org", "encyclopedia.com",
                   "newworldencyclopedia.org", "worldhistory.org", "scholarpedia.org", "encyclopedia.pub", "treccani.it",
                   "larousse.fr", "universalis.fr", "kotobank.jp", "baike.baidu.com", "baike.com", "namu.wiki", "snl.no")
REFERENCE_NAMES = re.compile(r"britannica|wikipedia|wikiwand|enc[iy]clop|treccani|larousse|kotobank|baike|namu ?wiki|"
                             r"scholarpedia|world history", re.I)   # the same, by the outlet's name
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
            "linkedin_page": "", "editor": "",
            "initiative": "A new weekly service for ISSMGE members.",
            "subscribe_form": "", "unsubscribe_form": "", "suggest_form": "", "public_url": ""}
INTRO = ("Dear members, every week our profession is at work around the world, in foundations and tunnels, slopes and dams, "
         "coastlines and cities. Here is a selection of that work, gathered from news sources in many languages and brought "
         "to you by the ISSMGE Magazine Presidential Committee.")
ICONS = site_builder.ASSETS / "icons"   # Lucide line icons (npm lucide-static 1.82.0, ISC licence in assets/icons/LICENSE)
FLAGS = site_builder.ASSETS / "flags"   # flags, 4 x 3 (npm flag-icons 7.6.0, MIT licence in assets/flags/LICENSE)
# the fonts named in the e-mails and the pictures (map, LinkedIn card): e-mail programs load no web fonts, so each
# name is followed by one every computer has
SERIF = "Newsreader,Georgia,serif"
SANS = '"Libre Franklin",Arial,sans-serif'


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
    """The flag emoji of a country, for the LinkedIn post only (plain text); the pages use flag_img."""
    code = str(code or "").upper()
    return "".join(chr(0x1F1E6 + ord(c) - 65) for c in code) if re.match(r"^[A-Z]{2}$", code) else "🌍"


_ICONS = {}


def icon(name):
    """A Lucide line icon (assets/icons/<name>.svg) put into the page as SVG: the height of the text, in ISSMGE red
    (the colour of .icon in geonews.css), hidden from screen readers (the words beside it say what it means)."""
    if name not in _ICONS:
        try:
            svg = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
        except OSError:
            svg = ""
        inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S)
        _ICONS[name] = ("<svg class='icon' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
                        "stroke-linecap='round' stroke-linejoin='round' aria-hidden='true' focusable='false'>"
                        + " ".join(inner.group(1).split()).replace('"', "'") + "</svg>") if inner else ""
    return _ICONS[name]


def story_date(s):
    """The day the story was published, as the scan stored it ('12 Nov 2026'; "" when unknown)."""
    return site_builder.nice_date(notify().story_day(s))


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


# ------------------------------------------------------------------ links: the publisher's own address
_LINKS = None     # data/geonews/gnews_links.json, once read
_FAILED = None    # data/geonews/gnews_failed.json, once read
_TRIED = set()    # Google News links tried in this run (not tried again in it)
_DECODED = 0      # links decoded through Google News in this run
_SPENT = 0.0      # seconds spent decoding links in this run
_GOOGLE = None    # whether Google News can be reached (and the decoder is installed), checked once in a run


def google_link(url):
    return "news.google.com/" in str(url or "")


def load_links():
    global _LINKS
    if _LINKS is None:
        try:
            d = json.loads(GNEWS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        _LINKS = {k: v for k, v in d.items() if str(v).startswith("http")} if isinstance(d, dict) else {}
    return _LINKS


def load_failed():
    """{google link: [days it could not be decoded, the last of them]} (data/geonews/gnews_failed.json), once read."""
    global _FAILED
    if _FAILED is None:
        try:
            d = json.loads(GNEWS_FAILED.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        _FAILED = {k: [int(v[0]), str(v[1])] for k, v in d.items()
                   if isinstance(v, list) and len(v) == 2 and str(v[0]).isdigit()} if isinstance(d, dict) else {}
    return _FAILED


def story_link(s):
    """The link of a story: the publisher's own address when its Google News link has been decoded, else as the scan
    stored it."""
    url = str(s.get("link") or "")
    return load_links().get(url, url) if google_link(url) else url


def google_reachable():
    """False when Google News cannot be reached at all (no internet, or a network that blocks it): no link is tried."""
    import requests
    try:
        return requests.get("https://news.google.com/", timeout=15).status_code < 400
    except Exception:
        return False


def decode_links(urls):
    """Find the publisher's own address of Google News links with googlenewsdecoder, each link once (kept in
    data/geonews/gnews_links.json), in the order given, with a pause after each, and at most GNEWS_MAX links and
    GNEWS_SECONDS seconds each time the program runs. A link that cannot be decoded keeps its Google News address (noted
    in the log); it is tried again on another day, at most on GNEWS_TRIES days (data/geonews/gnews_failed.json). Never
    fails. The number of links decoded."""
    global _DECODED, _SPENT, _GOOGLE
    links, failed = load_links(), load_failed()
    today = dt.date.today().isoformat()

    def worth_trying(u):   # not failed today, nor on GNEWS_TRIES days already
        days, last = failed.get(u) or [0, ""]
        return days < GNEWS_TRIES and last != today
    todo = [u for u in dict.fromkeys(str(u or "") for u in urls)
            if google_link(u) and u not in links and u not in _TRIED and worth_trying(u)]
    todo = todo[:max(0, GNEWS_MAX - _DECODED)]
    if not todo or _GOOGLE is False or _SPENT >= GNEWS_SECONDS:
        return 0
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        print("Geo-News: googlenewsdecoder is not installed; story links stay as Google News links")
        _GOOGLE = False
        return 0
    if _GOOGLE is None:
        _GOOGLE = google_reachable()
        if not _GOOGLE:
            print("Geo-News: Google News cannot be reached; the story links stay as Google News links for now")
            return 0
    start = time.monotonic()
    done, misses, missed = 0, 0, []
    for url in todo:
        if _SPENT + time.monotonic() - start >= GNEWS_SECONDS:
            print(f"Geo-News: {GNEWS_SECONDS} seconds spent on links; the others are tried in the next run")
            break
        _DECODED += 1
        _TRIED.add(url)
        try:
            r = gnewsdecoder(url, interval=GNEWS_PAUSE)
        except Exception as ex:  # the decoder itself failed: the link stays
            r = {"message": f"{type(ex).__name__}: {ex}"}
        new = str(r.get("decoded_url") or "") if isinstance(r, dict) and (r.get("success") or r.get("status")) else ""
        if new.startswith("http") and not google_link(new):
            links[url] = new
            done, misses = done + 1, 0
            continue
        missed.append(url)
        misses += 1
        why = str(r.get("message", "") if isinstance(r, dict) else r)[:100]
        print(f"Geo-News: link not decoded, it stays a Google News link ({why}): {url[:90]}")
        if misses >= 10:  # ten in a row: Google is refusing for now, which is not the links' fault
            print("Geo-News: Google News refused ten links in a row; the others are tried in the next run")
            _GOOGLE = False
            del missed[-misses:]
            break
    _SPENT += time.monotonic() - start
    if done or missed:
        DATA.mkdir(parents=True, exist_ok=True)
    if done:
        GNEWS_FILE.write_text(json.dumps(links, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        print(f"Geo-News: {done} Google News link(s) turned into the publisher's own")
    if missed:
        for url in missed:
            failed[url] = [(failed.get(url) or [0, ""])[0] + 1, today]
        GNEWS_FAILED.write_text(json.dumps(failed, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    return done


def reference_item(s):
    """True for an entry of an encyclopedia or a similar reference site (by its link or its outlet's name):
    background, not news."""
    host = domain_of(story_link(s))
    return (any(host == d or host.endswith("." + d) for d in REFERENCE_SITES)
            or bool(REFERENCE_NAMES.search(str(s.get("source") or ""))))


def not_news(s, key):
    """Why an item of the week is not used as news ("" when it is news): an encyclopedia entry, or published more than
    SCAN_LAG_DAYS days before Monday of the issue week, or after its Sunday. (A week's items are those the scan saved
    Monday to Sunday; the news of the weekend before is saved on Monday or Tuesday and belongs to this issue.)"""
    if reference_item(s):
        return f"Reference site ({s.get('source') or domain_of(story_link(s)) or 'encyclopedia'}), not news"
    monday, sunday = notify().week_range(key)
    try:
        day = dt.date.fromisoformat(notify().story_day(s)[:10])
    except ValueError:  # no date: the day it was saved, in the week
        return ""
    if day < monday - dt.timedelta(days=SCAN_LAG_DAYS):
        return f"Published {site_builder.nice_date(day.isoformat())}, before the issue week"
    if day > sunday:
        return f"Published {site_builder.nice_date(day.isoformat())}, after the issue week"
    return ""


REPEAT_WEEKS = 6   # a draft leaves out the stories of the issues published in this many weeks before it


def published_before(key, stories, papers, weeks=REPEAT_WEEKS):
    """[{"week", "id", "line", "title"}] of the stories in the issues approved in the weeks before key."""
    n = notify()
    out = []
    for path in issue_files():
        if not (path.stem < key) or path.stem < (n.week_range(key)[0] - dt.timedelta(weeks=weeks)).strftime("%G-W%V"):
            continue
        try:
            issue = load_issue(path, stories, papers)
        except ValueError:
            continue
        if issue["status"] != "approved":
            continue
        for it in issue["highlights"] + issue["around"]:
            out.append({"week": path.stem, "id": it["s"]["id"], "line": n.line_key(it["s"]),
                        "title": it["title"] or title_of(it["s"])})
    return out


def check_repeats(stories, past, cfg, limit=60):
    """{story id: {"kind": "repeat" | "update", "week", "note"}} for the stories that tell news already
    published (repeat: leave out) or a new development of it (update: keep, marked as an update). The same
    story or developing story (storyline) counts by itself; Claude judges the rest and whether a story of
    the same developing story brings real news (the best `limit` stories are judged). Without Claude, the same
    developing story counts as a repeat."""
    import os
    n = notify()
    by_id = {p["id"]: p for p in past}
    by_line = {}
    for p in past:
        by_line.setdefault(p["line"], p)
    out = {}
    for s in stories:
        if s["id"] in by_id:
            out[s["id"]] = {"kind": "repeat", "week": by_id[s["id"]]["week"], "note": ""}
        elif n.line_key(s) in by_line:
            out[s["id"]] = {"kind": "repeat", "week": by_line[n.line_key(s)]["week"], "note": ""}
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    rest = [s for s in n.by_rank(stories) if s["id"] not in by_id and (s.get("relevance") or 0) >= 3][:limit]
    if not key or not past or not rest:
        return out
    try:
        import anthropic
        weeks = sorted({p["week"] for p in past})
        published = "\n".join(f'{weeks.index(p["week"])}.{i}. {p["title"]}' for i, p in enumerate(past))
        listing = "\n".join(f'{i}. {title_of(s)} ({n.country_name(s.get("country")) or "global"}; {s.get("source", "")})'
                            for i, s in enumerate(rest))
        schema = {"type": "object", "properties": {"stories": {"type": "array", "items": {
            "type": "object", "properties": {
                "id": {"type": "integer"}, "kind": {"type": "string", "enum": ["new", "update", "repeat"]},
                "published": {"type": "string"}, "note": {"type": "string"}},
            "required": ["id", "kind", "published", "note"], "additionalProperties": False}}},
            "required": ["stories"], "additionalProperties": False}
        prompt = f"""A weekly geotechnical newsletter must not repeat news it has already published, except as a clearly marked update.

Already published (number before the dot = week {", ".join(f"{i} = {w}" for i, w in enumerate(weeks))}):
{published}

For each candidate story below return:
- "kind": "repeat" when it reports the same event or news as a published story, even from another website, in other words or with small extra details (the same tunnel breakthrough, the same contract award, the same study); "update" when it is about the same event or project as a published story but reports a real new development (new decisions, numbers, damage, findings, a new stage of the works); "new" otherwise. Another project of the same kind is "new".
- "published": for repeat or update, the number of the published story it follows (e.g. "1.4"); "" for new.
- "note": for update, at most 10 words on what is new; "" otherwise.

Candidates:
{listing}"""
        client = anthropic.Anthropic(api_key=key, max_retries=3)
        ccfg = cfg.get("claude") or {}
        r = client.messages.create(model=ccfg.get("model", "claude-haiku-5-5"), max_tokens=8000,
                                   output_config={"effort": ccfg.get("effort", "low"),
                                                  "format": {"type": "json_schema", "schema": schema}},
                                   messages=[{"role": "user", "content": prompt}])
        text = next((b.text for b in r.content if b.type == "text"), "")
        for d in json.loads(text)["stories"]:
            i = int(d["id"])
            if not 0 <= i < len(rest):
                continue
            s = rest[i]
            try:
                follows = past[int(str(d["published"]).split(".", 1)[1])]
            except (IndexError, ValueError):
                follows = by_line.get(n.line_key(s))
            kind = d["kind"]
            if kind == "new" and n.line_key(s) in by_line:
                kind = "update"   # the same developing story, judged a new event of it
            if kind == "new" or not follows:
                continue
            out[s["id"]] = {"kind": kind, "week": follows["week"], "note": " ".join(str(d["note"]).split())[:90]}
    except Exception as ex:  # without Claude, the same developing story stays a repeat
        print(f"Geo-News: Claude could not check for repeats ({type(ex).__name__}: {str(ex)[:120]})")
    return out


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
        f'| place: {s.get("place")} | link: {story_link(s) if not google_link(story_link(s)) else "(via Google News)"}'
        for i, s in enumerate(items))
    schema = {"type": "object", "properties": {"stories": {"type": "array", "items": {
        "type": "object", "properties": {
            "id": {"type": "integer"}, "number": {"type": "string"}, "number_label": {"type": "string"},
            "language": {"type": "string"}, "lat": {"type": "number"}, "lon": {"type": "number"},
            "satellite": {"type": "boolean"}, "site": {"type": "string"}},
        "required": ["id", "number", "number_label", "language", "lat", "lon", "satellite", "site"],
        "additionalProperties": False}}}, "required": ["stories"], "additionalProperties": False}
    prompt = f"""For each news story below, return:
- "number": the most striking figure stated in the headline itself (e.g. "96%", "4.5 km", "US$16.5 bn", "3"), copied from the headline and written in English with digits and SI units (e.g. "500 metri" becomes "500 m", "2割程度" becomes "about 20%"); "" when the headline states no figure or the figure is part of a name (a programme, a law, a street). Never compute, estimate or take a figure from elsewhere.
- "number_label": at most 8 words saying what the figure counts (e.g. "of strongly shaken sites liquefied again"); "" when number is "".
- "language": the language the outlet publishes this story in, as an English name (e.g. "English", "Japanese", "Spanish"), judged from the original headline.
- "lat", "lon": the latitude and longitude of the place the story is about, as exactly as the headline and place allow (the site, else the town, else the region, else the country's centre).
- "satellite": true only when the story is about one specific site on land whose position you know to within about 1 km (a dam, a landslide, a building, a tunnel portal or station site, a small town), so that a satellite view about 10 km across shows something meaningful; false for crossings under seas, straits, bays or rivers, for routes and lines tens of kilometres long, for regions, countries and general stories, and whenever lat/lon are only approximate.
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


# ------------------------------------------------------------------ case histories
_CASES = None
_CASES_SKIPPED = []   # entries of the case list left out (no id or name, or an id used twice), for the preview
CASE_TEXTS = ("name", "country", "region", "date", "anniversary", "outcome", "lives_lost", "what_happened", "lesson",
              "framing_note", "theme", "overview", "overview_title")   # the fields of a case, each read as plain text
CASE_DAYS = 14        # a case whose anniversary falls in the issue week or the week after it goes first
CASE_KEEP_DAYS = 42   # otherwise a case whose anniversary comes within this many days after that is kept for it
DIED = re.compile(r"\b(died|dead|deaths?|killed|lives|victims?|missing|never found)\b", re.I)
ADVICE = re.compile(r"\b(avoid|do not|don't|mention|acknowledge|the item|consider|make clear|lead with|start with|"
                    r"frame it|name the|say clearly|use a sourced)\b", re.I)   # the framing notes' advice to the writer
LESSON = "Lesson for practice:"


def load_cases():
    """The case list (data/geonews/case_histories.yaml) as {id: case}, in its order, every field as plain text; {} when
    it is missing. The list is edited by hand, so a mistake in it never stops the pages: an entry without an id or a
    name (or with an id used before) is left out and named in _CASES_SKIPPED, which the draft's preview shows."""
    global _CASES
    if _CASES is None:
        try:
            raw = yaml.safe_load(CASES_FILE.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as ex:
            print(f"Geo-News: the case list cannot be read ({type(ex).__name__}); no case history")
            raw = {}
        if not isinstance(raw, dict):
            print("Geo-News: the case list does not start with the line cases: ; no case history")
            raw = {}
        entries = raw.get("cases") if isinstance(raw.get("cases"), list) else []
        _CASES = {}
        _CASES_SKIPPED.clear()
        for i, c in enumerate(entries, 1):
            c = c if isinstance(c, dict) else {}
            cid = " ".join(str(c.get("id") or "").split())
            why = ("no id" if not cid else "no name" if not str(c.get("name") or "").strip()
                   else f"the id {cid} is used twice" if cid in _CASES else "")
            if why:
                _CASES_SKIPPED.append(f"entry {i}" + (f" ({cid})" if cid and "twice" not in why else "") + f": {why}")
                continue
            case = dict(c, id=cid, **{k: " ".join(str(c.get(k) or "").split()) for k in CASE_TEXTS})
            case["sources"] = [{"title": " ".join(str(s.get("title") or "").split()), "url": str(s.get("url") or "").strip()}
                               for s in (c.get("sources") if isinstance(c.get("sources"), list) else []) if isinstance(s, dict)]
            _CASES[cid] = case
        if _CASES_SKIPPED:
            print(f"Geo-News: left out of the case list: {'; '.join(_CASES_SKIPPED)}")
    return _CASES


def case_when(c):
    """The date of a case, short, for its heading: '9 Oct 1963', 'Construction 1975 to 1991', '1993–1998'."""
    d = " ".join(str(c.get("date") or "").split())
    short = re.split(r" \(|;|\. ", d, maxsplit=1)[0].strip().rstrip(".")
    if len(short) > 32:
        years = re.findall(r"\b(?:1[89]|20)\d\ds?\b", re.split(r"\. ", d, maxsplit=1)[0])
        short = f"{years[0]}–{years[-1]}" if len(years) > 1 and years[0] != years[-1] else (years[0] if years else short)
    return short[:1].upper() + short[1:]


def anniversary_day(c, monday, days):
    """The day of the case's anniversary (day and month, DD-MM) within the days from monday on; None when not."""
    m = re.match(r"^(\d{2})-(\d{2})$", str(c.get("anniversary") or ""))
    if not m:
        return None
    for i in range(days):
        d = monday + dt.timedelta(days=i)
        if (d.day, d.month) == (int(m.group(1)), int(m.group(2))):
            return d
    return None


def cases_used(key):
    """{case id: week} of the case histories of the issues before key (drafts too, with the story editor's saves)."""
    out = {}
    for path in sorted(issue_files()):
        if path.stem >= key:
            continue
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        edit, _ = latest_edit(path.stem)
        if edit and isinstance(raw, dict):
            raw = apply_edit(raw, edit)
        ch = raw.get("case_history") if isinstance(raw, dict) else None
        if isinstance(ch, dict) and ch.get("case"):
            out[str(ch["case"]).strip()] = path.stem
    return out


def choose_case(key, used=None, cases=None):
    """The case history for the draft of a week: a case whose anniversary falls in the issue week or the week after it
    (the nearest first); otherwise the next case of the list, from the region used least so far (after the region of
    the last case used), keeping a case whose anniversary is coming soon for its week. Never a case used before
    (used: {id: week}). None when every case has been used."""
    cases = load_cases() if cases is None else cases
    used = cases_used(key) if used is None else used
    free = [c for cid, c in cases.items() if cid not in used]
    if not free:
        return None
    monday = notify().week_range(key)[0]
    dated = [(anniversary_day(c, monday, CASE_DAYS), i, c) for i, c in enumerate(free)]
    dated = [x for x in dated if x[0]]
    if dated:
        return min(dated, key=lambda x: (x[0], x[1]))[2]
    later = monday + dt.timedelta(days=CASE_DAYS)
    soon = [c for c in free if not anniversary_day(c, later, CASE_KEEP_DAYS)] or free
    regions = list(dict.fromkeys(str(c.get("region") or "") for c in cases.values()))
    count = {r: 0 for r in regions}
    for cid in used:
        if cid in cases:
            count[str(cases[cid].get("region") or "")] += 1
    last = cases.get(max(used, key=lambda cid: used[cid])) if used else None
    start = regions.index(str(last.get("region") or "")) + 1 if last and str(last.get("region") or "") in regions else 0
    order = regions[start:] + regions[:start]
    region = min((r for r in order if any(str(c.get("region") or "") == r for c in soon)),
                 key=lambda r: (count[r], order.index(r)))
    return next(c for c in soon if str(c.get("region") or "") == region)


def suggest_cases(key, current, n=3):
    """n other cases the editor might use instead, chosen by the same rules as the draft's."""
    used = dict(cases_used(key))
    if current:
        used[current] = key
    out = []
    for _ in range(n):
        c = choose_case(key, used)
        if not c:
            break
        out.append(c)
        used[str(c["id"])] = key
    return out


def people_died(c):
    """True when the case cost lives (its lives_lost starts with a number above 0)."""
    t = str(c.get("lives_lost") or "").strip().lower()
    m = re.search(r"\d[\d,]*", t)
    return not t.startswith(("none", "no ")) and bool(m) and m.start() < 25 and int(m.group().replace(",", "")) > 0


def victims_text(c):
    """The opening of a case where people died, from its framing note: the sentence the note suggests (in quotes) and
    its other facts, without its advice to the writer ("Start with the victims", "Avoid ..."); "" when none."""
    note = " ".join(str(c.get("framing_note") or "").split())
    m = re.search(r"""(?:^|:\s*)(["'])(.+?[.!?…])\1(?=\s|$)""", note)
    if m and re.search(r"(?:^|[.!?]\s)If [^.!?]*$", note[:m.start()]) and not people_died(c):
        return ""  # a sentence for an item that speaks of something this text leaves out
    out, rest = ([m.group(2)], note[m.end():]) if m else ([], note)
    for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", rest.strip()):
        s = s.strip()
        a = re.match(r"(?:Acknowledge (?:briefly )?that|Make clear that|Note that) (.+?)(?:,? before turning to .*)?\.$", s)
        b = re.match(r"(.+?),? so (?:do not|don't|avoid) .*$", s)
        if a and (s.startswith("Note") or DIED.search(a.group(1))):  # "Acknowledge that context ..." is advice
            s = a.group(1)[:1].upper() + a.group(1)[1:] + "."
        elif b and not ADVICE.search(b.group(1)):
            s = b.group(1) + "."
        elif ADVICE.search(s) or s.startswith("If ") or len(s.split()) < 5:
            continue
        out.append(s)
    text = " ".join(re.sub(r"\s*(?:\.\.\.|…)$", ".", s) for s in out)
    return text if text and (people_died(c) or DIED.search(text)) else ""


def case_text(c):
    """The text of a case history, written from the case list: where people died the victims first (from the framing
    note), then what happened, then "Lesson for practice: ..."; about 120 to 150 words."""
    first = victims_text(c)
    lesson = " ".join(str(c.get("lesson") or "").split())
    if len((first + " " + str(c.get("what_happened")) + " " + lesson).split()) > 155 and "; " in lesson:
        lesson = lesson.split("; ")[0] + "."   # a long case: the lesson's first part only
    parts = [first, " ".join(str(c.get("what_happened") or "").split()).rstrip(".") + ".", f"{LESSON} {lesson}"]
    text = " ".join(p for p in parts if p.strip(" ."))
    return re.sub(r"\b(k?m)([23])\b", lambda m: m.group(1) + ("²" if m.group(2) == "2" else "³"), text)   # m3, km2


_NAMES = {}


def case_flags(c, root=""):
    """The flags of a case's country or countries ("United Kingdom and France"); the globe icon when none is known."""
    if not _NAMES:   # the English name of every country with a flag
        for f in FLAGS.glob("*.svg"):
            name = notify().country_name(f.stem.upper())
            if name and name.upper() != f.stem.upper():
                _NAMES[name.lower()] = f.stem.upper()
        _NAMES.update({v.lower(): k for k, v in site_builder.COUNTRIES.items()})
    names = _NAMES
    out = []
    for part in re.split(r"\s+and\s+|,|\(", str(c.get("country") or "")):
        code = names.get(part.strip(" )").lower())
        if code and code not in out:
            out.append(code)
    return " ".join(flag_img(code, root) for code in out) or icon("earth")


def case_anniversary(issue):
    """'60th anniversary · 21 October' when the case's anniversary falls in the issue week or the week after it."""
    c = (issue.get("case") or {}).get("c") or {}
    day = anniversary_day(c, notify().week_range(issue["key"])[0], CASE_DAYS)
    years = re.search(r"\b(1[89]\d\d|20\d\d)\b", str(c.get("date") or ""))
    if not day or not years:
        return ""
    n = day.year - int(years.group(1))
    th = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{th} anniversary · {day.day} {day:%B}" if n > 0 else ""


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
              f"    site: {q(domain_of(story_link(s)) or info.get('site'))}   # the news site, for the advert check",
              "    adverts: auto   # auto (checked each week), yes or no",
              f"    update: {q(s.get('_update', ''))}   # the week of the earlier story this one updates (e.g. 2026-W44); \"\" for a new story"]
    return lines


def case_lines(c):
    """The case history of an issue file: the case's id and its text, which the editor may change."""
    if not c:
        return []
    return ["# CASE HISTORY: a well-known case from data/geonews/case_histories.yaml, kept apart from the news. To use",
            "# another case, write its id after case: (the preview page suggests three) and empty the text (\"\"): the",
            "# page then writes the text from the list. Change the text as you wish; delete these lines for no case history.",
            "case_history:",
            f"  case: {c['id']}   # {note(c.get('name'))} ({note(c.get('country'))}, {note(case_when(c))})",
            f"  text: {q(case_text(c))}",
            ""]


def draft_text(key, highlights, around, research, cfg, info=None, case=None):
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
             "#  - Case history: see the note above case_history: below.",
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
    lines += [""] + case_lines(case) + ["research:"]
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
    # news of the week only: older items and encyclopedia entries are left out (the preview lists them apart)
    aside = {s["id"]: not_news(s, key) for s in stories}
    for s in stories:
        if aside[s["id"]] and (s.get("relevance") or 0) >= 3:
            print(f"Geo-News: {s['id']} not used as news: {aside[s['id']]}")
    stories = [s for s in stories if not aside[s["id"]]]
    every, every_p = all_items(digests)
    past = published_before(key, every, every_p)
    seen = check_repeats(stories, past, cfg)
    for sid, r in seen.items():
        print(f"Geo-News: {sid} " + ("left out, already published" if r["kind"] == "repeat" else "kept as an update of a story")
              + f" in {r['week']}" + (f" ({r['note']})" if r["note"] else ""))
    stories = [dict(s, _update=seen[s["id"]]["week"]) if seen.get(s["id"], {}).get("kind") == "update" else s
               for s in stories if seen.get(s["id"], {}).get("kind") != "repeat"]
    for _ in range(3):  # the chosen stories' own addresses; one that turns out to be an encyclopedia entry is replaced
        hl, ar, rs = select(stories, papers, settings(cfg))
        decode_links([s["link"] for s in hl + ar])
        ref = {s["id"] for s in hl + ar if reference_item(s)}
        if not ref:
            break
        print(f"Geo-News: {', '.join(sorted(ref))} not used as news: reference site")
        stories = [s for s in stories if s["id"] not in ref]
    hl, ar = [s for s in hl if not reference_item(s)], [s for s in ar if not reference_item(s)]
    # (the other stories of the week, shown on the preview, are decoded when the pages are built)
    info = enrich(hl + ar, cfg)
    case = choose_case(key)
    if case:
        print(f"Geo-News: case history of {key}: {case['id']} {case.get('name')}")
    DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(draft_text(key, hl, ar, rs, cfg, info, case), encoding="utf-8")
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
                             site=text(it.get("site")) or domain_of(story_link(found)),
                             adverts={True: "yes", False: "no"}.get(it.get("adverts"), text(it.get("adverts")).lower() or "auto"),
                             update=text(it.get("update")) if KEY.match(text(it.get("update"))) else "")
                if entry["satellite"] and (entry["lat"] is None or entry["lon"] is None):
                    entry["satellite"] = False
            out.append(entry)
        return out

    def case_history():
        ch = raw.get("case_history")
        if ch in (None, "", "none") or (isinstance(ch, dict) and not text(ch.get("case"))):
            return None
        if not isinstance(ch, dict):
            problems.append("case_history: not laid out as a case (case: and text:)")
            return None
        found = load_cases().get(text(ch.get("case")))
        if not found:
            problems.append(f"case_history: no case has the id {text(ch.get('case'))} (see data/geonews/case_histories.yaml)")
            return None
        return {"c": found, "text": text(ch.get("text")) or case_text(found)}

    status = text(raw.get("status")).lower() or "draft"
    if status not in ("draft", "approved"):
        problems.append(f"status is \"{status}\": write draft or approved")
    issue = {"key": key, "status": status, "intro": text(raw.get("intro")) or INTRO,
             "highlights": items("highlights", "story", stories), "around": items("around_the_world", "story", stories),
             "research": items("research", "paper", papers), "case": case_history(),
             "events": text(raw.get("events")).lower() != "none",
             "magazine_note": text(raw.get("magazine_note")), "magazine_link": site_builder.safe_url(text(raw.get("magazine_link")))
             if text(raw.get("magazine_link")) else "", "problems": problems, "edited": edited}
    if status == "draft":  # a story that is not news of this week (chosen by hand, or before the date check)
        part = ["Highlights"] * len(issue["highlights"]) + ["Around the world"] * len(issue["around"])
        for i, it in enumerate(issue["highlights"] + issue["around"], 1):   # numbered as on the page
            why = not_news(it["s"], key)
            if not why:
                continue
            it["aside"] = why[:1].lower() + why[1:] + (f" ({week_span(key)})" if why.endswith("issue week") else "")
            head = it["title"] or title_of(it["s"])
            head = head if len(head) <= 60 else head[:57].rsplit(" ", 1)[0] + "…"
            problems.append(f"{part[i - 1]}, story {i} ({head}, code {it['s']['id']}): {it['aside']}. Please replace it.")
        load_cases()
        if _CASES_SKIPPED:
            problems.append(f"Case list (data/geonews/case_histories.yaml): {'; '.join(_CASES_SKIPPED)}. These cases are "
                            "left out until the list is corrected.")
    return issue


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
                if "satellite" in e:
                    it["satellite"] = "yes" if e["satellite"] else "no"
                if "update" in e:
                    it["update"] = e["update"]
                out.append(it)
            raw[name] = out
    for k in ("status", "intro"):
        if edit.get(k):
            raw[k] = edit[k]
    if "case_history" in edit:  # saves made before the case history existed have none: the file's case stays
        ch = edit["case_history"]
        if isinstance(ch, dict) and ch.get("case"):
            raw["case_history"] = {"case": str(ch["case"]), "text": str(ch.get("text") or "")}
        else:
            raw.pop("case_history", None)
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

    every, every_p = all_items(digests)
    past = published_before(key, every, every_p)
    done = {p["id"]: p["week"] for p in past}
    for p in past:
        done.setdefault(p["line"], p["week"])

    def story(s):
        return {"t": title_of(s), "w": n.country_name(s.get("country")) or "Global", "f": flag_img(s.get("country"), "../"),
                "src": s.get("source", ""), "th": s.get("theme", ""), "r": s.get("relevance") or 0,
                "a": s.get("angle", ""), "l": story_link(s),
                "p": done.get(s["id"]) or done.get(n.line_key(s)) or "", "o": not_news(s, key)}

    def case(c):
        return {"n": c.get("name", ""), "w": c.get("country", ""), "y": case_when(c), "t": case_text(c)}
    current = issue.get("case")   # a published issue without a case history keeps none (no choice offered)
    cases = (([current["c"]] if current else []) + suggest_cases(key, current["c"]["id"] if current else None)
             if current or issue["status"] == "draft" else [])

    def entry(it):
        return {"story": it["s"]["id"], "title": it["title"], "text": it["text"], "number": it.get("number", ""),
                "number_label": it.get("number_label", ""), "satellite": bool(it.get("satellite")),
                "update": it.get("update", ""),
                "place": it.get("lat") is not None and it.get("lon") is not None}
    order = sorted(pool.values(), key=lambda s: (-(s.get("relevance") or 0), -(s.get("rank") or 0)))
    return {"week": key, "span": week_span(key), "repo": site_builder.repository(cfg), "status": issue["status"],
            "intro": issue["intro"], "highlights": [entry(it) for it in issue["highlights"]],
            "around_the_world": [entry(it) for it in issue["around"]],
            "research": [it["s"]["id"] for it in issue["research"]],
            "case_history": {"case": current["c"]["id"], "text": current["text"]} if current else None,
            "cases": {str(c["id"]): case(c) for c in cases},
            "stories": {s["id"]: story(s) for s in order}, "order": [s["id"] for s in order],
            "icons": {k: icon(k) for k in ("pencil", "save", "check", "x", "plus", "refresh-cw", "history")}}


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


_SAT_TRIED = set()   # satellite pictures that could not be downloaded in this run (tried again in the next run)
_SAT_MISSES = 0      # pictures that failed in a row: after three, none is tried in this run


def sat_name(it, z):
    """The file of a story's satellite picture: the story's code and a fingerprint of the place and zoom, so a story
    moved to another place (or from the cover to a card) gets a new picture."""
    import hashlib
    place = "%.4f,%.4f,%d" % (it["lat"], it["lon"], z)
    return f"{it['s']['id']}-{hashlib.sha1(place.encode()).hexdigest()[:8]}.jpg"


def get_tile(z, x, y):
    import requests
    r = requests.get(SAT_TILES.format(z=z, x=x, y=y), timeout=20, headers={"User-Agent": "GeoNewsWeekly/1.0 (ISSMGE MPC)"})
    r.raise_for_status()
    return r.content


def make_satellite(path, lat, lon, z, get=None):
    """Download the Sentinel-2 cloudless map tiles (EOX) around a place, put them together and cut out a picture of
    SAT_PX x SAT_PX pixels with the place in the middle, at the map's own scale (as the page showed the tiles before);
    saved as JPEG at path. True when saved; False, with nothing saved, when the place is off the map. A tile that cannot
    be downloaded raises."""
    from io import BytesIO
    from PIL import Image
    get = get or get_tile
    n = 2 ** z
    lr = math.radians(lat)
    px = (lon + 180) / 360 * n * 256
    py = (1 - math.log(math.tan(lr) + 1 / math.cos(lr)) / math.pi) / 2 * n * 256
    x0, y0 = int(round(px - SAT_PX / 2)), int(round(py - SAT_PX / 2))
    tx0, ty0, tx1, ty1 = x0 // 256, y0 // 256, (x0 + SAT_PX - 1) // 256, (y0 + SAT_PX - 1) // 256
    if ty0 < 0 or ty1 >= n:  # too near a pole
        return False
    sheet = Image.new("RGB", ((tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256))
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            if tx > tx0 or ty > ty0:
                time.sleep(0.1)  # gently
            tile = Image.open(BytesIO(get(z, tx % n, ty))).convert("RGB")
            sheet.paste(tile if tile.size == (256, 256) else tile.resize((256, 256)), ((tx - tx0) * 256, (ty - ty0) * 256))
    left, top = x0 - tx0 * 256, y0 - ty0 * 256
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    try:
        sheet.crop((left, top, left + SAT_PX, top + SAT_PX)).save(part, "JPEG", quality=82, optimize=True, progressive=True)
        part.replace(path)
    finally:
        if part.exists():  # a picture that could not be written leaves nothing behind
            part.unlink()
    return True


def pictures(issue, get=None):
    """The satellite picture of each highlight that has one (satellite: yes): it["picture"] = "<week>/<file>", kept in
    data/geonews/img/<week>/ and downloaded once (in GitHub Actions, when the pages are built). A story whose picture
    cannot be downloaded has none and shows its country map. Pictures of the week no story uses any more are removed."""
    global _SAT_MISSES
    folder = IMG / issue["key"]
    keep = set()
    for i, it in enumerate(issue["highlights"]):
        if not it.get("satellite") or it.get("lat") is None or it.get("lon") is None:
            continue
        z = 13 if i == 0 else 12   # the cover shows the site closer
        name = sat_name(it, z)
        path = folder / name
        if not path.exists() and name not in _SAT_TRIED and _SAT_MISSES < 3:
            try:
                ok = make_satellite(path, it["lat"], it["lon"], z, get)
            except Exception as ex:  # no network, a tile missing, a picture that cannot be read
                ok = False
                print(f"Geo-News: no satellite picture for {it['s']['id']} ({type(ex).__name__}: {str(ex)[:80]}); "
                      "its country map is shown")
            if ok:
                _SAT_MISSES = 0
                print(f"Geo-News: satellite picture of {it['s']['id']} saved as {path.relative_to(ROOT)}")
            else:
                _SAT_TRIED.add(name)
                _SAT_MISSES += 1
                if _SAT_MISSES == 3:
                    print("Geo-News: the satellite pictures cannot be downloaded now; the others are tried in the next run")
        if path.exists():
            it["picture"] = f"{issue['key']}/{name}"
            keep.add(name)
    for f in folder.glob("*.jpg") if folder.is_dir() else []:
        if f.name not in keep:
            f.unlink()
    if folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()


def copy_pictures(dest, weeks=None):
    """The satellite pictures next to the pages (geonews/img/<week>/), with their licence (img/LICENSE.txt); weeks: only
    those weeks (the public site)."""
    if dest.exists():
        shutil.rmtree(dest)
    for folder in sorted(IMG.iterdir()) if IMG.is_dir() else []:
        if folder.is_dir() and KEY.match(folder.name) and (weeks is None or folder.name in weeks) and any(folder.glob("*.jpg")):
            shutil.copytree(folder, dest / folder.name, ignore=shutil.ignore_patterns("*.part"))
    if dest.is_dir() and (IMG / "LICENSE.txt").exists():
        shutil.copy2(IMG / "LICENSE.txt", dest / "LICENSE.txt")


def satellite(it, root, lazy=True):
    """A satellite view of the place (Sentinel-2 cloudless 2020 by EOX, CC BY-NC-SA 4.0, credited in the page footer):
    the story's picture, kept with the site, with the place marked in the middle."""
    lazy = " loading='lazy'" if lazy else ""
    return (f"<div class='sat'><img class='satimg' src='{root}img/{esc(it['picture'])}' width='{SAT_PX}' height='{SAT_PX}' "
            f"alt=''{lazy}><span class='satpin'></span>"
            f"<span class='satlbl'>{icon('satellite')} Satellite view</span><span class='satcr'>Sentinel-2 cloudless 2020 · EOX</span></div>")


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
                       f"font-weight='bold' fill='#fff' font-family='{SANS}'>{i}</text>" if label else "")
                    + "</a>")
    vb = " ".join(map(str, MAP_VIEW))
    return (f"<svg class='{cls}' viewBox='{vb}' role='img' aria-label='World map of this week’s stories'>"
            f"<rect x='{MAP_VIEW[0]}' y='{MAP_VIEW[1]}' width='{MAP_VIEW[2]}' height='{MAP_VIEW[3]}' fill='#f6f1ea'/>"
            f"<g stroke='#fff' stroke-width='3'>{''.join(paths)}</g>{''.join(pins)}</svg>")


# ------------------------------------------------------------------ the page
def flag_img(code, root=""):
    """A small flag picture, kept with the site (assets/flags/): flag emoji do not show on Windows computers.
    root: the way from the page to geonews/ ("" or "../"); the globe icon when the country has no flag."""
    code = str(code or "").upper()
    code = {"UK": "GB", "EL": "GR"}.get(code, code)
    if not re.match(r"^[A-Z]{2}$", code) or code in ("XX", "ZZ") or not (FLAGS / f"{code.lower()}.svg").exists():
        return icon("earth")
    return f"<img class='flag' src='{root}../assets/flags/{code.lower()}.svg' width='20' height='15' alt=''>"


def where_text(s, root=""):
    n = notify()
    place = n.country_name(s.get("country"))
    return f"{flag_img(s.get('country'), root)} {esc(place)}" if place else f"{icon('earth')} Global"


def source_line(s):
    """The outlet (or journal) and the day it published the story: 'Tunnels & Tunnelling · 12 Nov 2026', on the pages
    and in the e-mails. The name keeps its own writing direction (dir=auto), so an Arabic name does not move the date."""
    name, day = s.get("source") or s.get("journal") or "", story_date(s)
    parts = [f"<span dir='auto'>{esc(name)}</span>" if name else "", f"<span class='dt'>{day}</span>" if day else ""]
    return " · ".join(x for x in parts if x)


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


def notes_html(it, ads, dark=False, preview=False, highlight=False):
    """The small notes under a story: its language when not English, and many adverts on its site; on the editor's
    preview also a link that still goes through Google News, a story that is not news of the week (a draft's) and
    (highlights) a satellite view not downloaded yet."""
    out = []
    lang = it.get("language", "English")
    if lang and lang.lower() != "english":
        out.append(f"<span class='nt'>{icon('globe')} In {esc(lang)} · use your browser's Translate</span>")
    elif not lang:
        out.append(f"<span class='nt'>{icon('globe')} Not in English · use your browser's Translate</span>")
    many = {"yes": True, "no": False}.get(it.get("adverts"), (ads.get(it.get("site")) or {}).get("many"))
    if many:
        out.append(f"<span class='nt ad'>{icon('megaphone')} This site may show many adverts</span>")
    if preview and google_link(story_link(it["s"])):
        out.append(f"<span class='nt pv'>{icon('link')} Editor: link still goes through Google News</span>")
    if preview and it.get("aside"):
        out.append(f"<span class='nt pv'>{icon('pencil')} Editor: {esc(it['aside'])}; please replace it</span>")
    if preview and highlight and it.get("satellite") and not it.get("picture"):
        out.append(f"<span class='nt pv'>{icon('satellite')} Editor: satellite picture not downloaded yet; the country map is shown</span>")
    return f"<div class='nts{' dk' if dark else ''}'>{''.join(out)}</div>" if out else ""


def update_html(it, root, dark=False):
    """The mark of a story that follows one published before: "Update · first reported in Week 44", linked to that issue."""
    w = it.get("update")
    if not w:
        return ""
    return (f"<div class='upd{' dk' if dark else ''}'>{icon('refresh-cw')} <b>Update</b> · first reported in "
            f"<a href='{root}{esc(w)}.html'>Week {week_no(w)}</a></div>")


def key_number(it, cls="kn"):
    if not it.get("number"):
        return ""
    return f"<div class='{cls}'><b>{esc(it['number'])}</b><span>{esc(it.get('number_label', ''))}</span></div>"


def masthead(cfg, root, chips):
    return (f"<header class='mh'><div class='mh-row'><div><div class='mh-k'>ISSMGE · <a href='{MPC_URL}'>Magazine Presidential Committee (MPC)</a></div>"
            f"<h1>{esc(settings(cfg)['name'])}</h1><div class='mh-t'>Ground engineering in a changing world</div>"
            + (f"<div class='mh-i'>{esc(settings(cfg)['initiative'])}</div>" if settings(cfg)["initiative"] else "")
            + "</div>"
            f"<img class='mh-logo' src='{root}../assets/issmge-logo.png' alt='ISSMGE'></div><div class='mh-rule'></div>"
            + (f"<div class='mh-meta'>{chips}</div>" if chips else "") + "</header>")


def tips():
    return (f"<aside class='before'><b>{icon('lightbulb')} Reading tips</b><ul>"
            f"<li>{icon('globe')} Story in another language? Use your browser's <b>Translate</b>.</li>"
            f"<li>{icon('newspaper')} Headlines open the original news site; sites with many adverts are marked.</li></ul></aside>")


def case_parts(text):
    """(the case, its lesson): a case history's text split at "Lesson for practice:"."""
    m = re.search(r"\s*Lesson for practice:\s*", text, re.I)
    return (text[:m.start()].strip(), text[m.end():].strip()) if m else (text.strip(), "")


def case_sources(c):
    """[(title, link)] to read more about a case: its overview page first, then its sources, each address once. The
    overview is named by the source with the same address, else by overview_title, else by its site."""
    out, seen = [], set()
    ov = str(c.get("overview") or "")
    if ov.startswith("http"):
        same = next((str(s.get("title") or "") for s in c.get("sources") or [] if isinstance(s, dict) and s.get("url") == ov), "")
        host = domain_of(ov)
        name = (f"Overview: {same.replace(': ', ' – ', 1)}" if same
                else f"Overview: {c['overview_title']}" if c.get("overview_title")
                else "Overview (Wikipedia)" if host.endswith("wikipedia.org") else f"Overview: {host or 'web page'}")
        out.append((name, ov))
        seen.add(ov)
    for s in c.get("sources") or []:
        url = str((s or {}).get("url") or "") if isinstance(s, dict) else ""
        if url.startswith("http") and url not in seen:
            out.append((str(s.get("title") or domain_of(url)), url))
            seen.add(url)
    return out


def case_html(issue, root, preview=False):
    """The case history: a well-known case, kept apart from the news, with its lesson and where to read more; on the
    preview, a note that its text is a draft to check."""
    ch = issue.get("case")
    if not ch:
        return ""
    c = ch["c"]
    color = theme_color(c.get("theme"))
    story, lesson = case_parts(ch["text"])
    ann = case_anniversary(issue)
    links = "".join(f"<li><a href='{esc(site_builder.safe_url(u))}'>{esc(t)}</a></li>" for t, u in case_sources(c))
    check = (f"<div class='cs-pv'>{icon('pencil')} <b>Editor:</b> this text is a draft written from the case list (case "
             f"<code>{esc(c['id'])}</code>; the list is to be confirmed by ISSMGE TC302). Please check it before publishing; "
             f"other cases are suggested at the end of this page.</div>" if preview else "")
    return (f"<h2>Case history</h2><article class='case' id='case' style='--c:{color}'>"
            f"<div class='cs-k'>{icon('history')} {'Success' if c.get('outcome') == 'success' else 'Failure'} · "
            f"{case_flags(c, root)} {esc(c.get('country', ''))} · {esc(case_when(c))}</div>"
            + (f"<div class='cs-ann'>{esc(ann)}</div>" if ann else "")
            + f"<h3>{esc(c.get('name', ''))}</h3>{check}<p>{esc(story)}</p>"
            + (f"<p class='cs-l'><b>{LESSON}</b> {esc(lesson)}</p>" if lesson else "")
            + (f"<div class='cs-src'><b>{icon('book-open')} Read more</b><ul>{links}</ul></div>" if links else "")
            + f"{tag(c)}</article>")


def issue_html(issue, cfg, root, number=None, preview=False):
    """The issue itself: masthead, map, highlights, around the world, case history, research, events, magazine box.
    preview: the editor's preview, with notes for the editor (Google News links, missing pictures, the case text)."""
    opts = settings(cfg)
    hl, ar = issue["highlights"], issue["around"]
    ads = load_ads()
    chips = (f"<span class='no'>Week {week_no(issue['key'])} · {issue['key'][:4]}</span><span>{esc(week_span(issue['key']))}</span>"
             + (f"<span>Issue {number}</span>" if number else ""))
    out = [masthead(cfg, root, chips), "<div class='gn-main'>", f"<p class='intro'>{esc(issue['intro'])}</p>"
           + (f"<p class='editor-line'>Edited by {esc(opts['editor'])}</p>" if opts["editor"] else ""), tips()]
    if hl or ar:
        out.append(f"<section class='mapcard'><h2>This week on the map</h2>{map_svg(issue)}"
                   "<div class='mapkey'><span><i class='k1'></i>Highlights</span><span><i class='k2'></i>Around the world</span>"
                   "<span>Tap a number to read the story</span></div></section>")
    if hl:
        out.append("<h2>Highlights</h2>")
        lead = hl[0]
        s = lead["s"]
        link = esc(story_link(s))
        c = theme_color(s.get("theme"))
        sat = lead.get("satellite") and lead.get("picture")   # no picture (not downloaded): the country map
        media = satellite(lead, root, lazy=False) if sat else locator(lead, c, "loc full")
        mini = (f"<div class='cv-loc'>{locator(lead, c)}<span>{esc(place_name(lead))}</span></div>" if sat
                else f"<span class='plc'>{icon('map-pin')} {esc(place_name(lead))}</span>")
        out.append(f"<article class='cover' id='s1' style='--c:{c}'><div class='cv-text'>"
                   f"<div class='cv-k'><b class='num w'>1</b> Story of the week</div>{update_html(lead, root, True)}{key_number(lead)}"
                   f"<h3><a href='{link}'>{headline_html(lead)}</a></h3>"
                   f"<div class='cv-meta'>{where_text(s, root)} · {source_line(s)}</div>"
                   + (f"<p>{esc(lead['text'])}</p>" if lead["text"] else "") + notes_html(lead, ads, True, preview, True)
                   + f"<span class='cv-tag'>{esc(s.get('theme') or '')}</span></div>"
                   f"<a class='cv-media' href='{link}'>{media}{mini}</a></article>")
        for i, it in enumerate(hl[1:], 2):
            s = it["s"]
            link = esc(story_link(s))
            c = theme_color(s.get("theme"))
            sat = it.get("satellite") and it.get("picture")
            media = satellite(it, root) if sat else locator(it, c)
            mini = f"<div class='mini'>{locator(it, c)}</div>" if sat else ""
            out.append(f"<article class='card2' id='s{i}' style='--c:{c}'><a class='m2' href='{link}'>{media}{mini}"
                       f"<span class='plc'>{icon('map-pin')} {esc(place_name(it))}</span></a><div class='b2'>"
                       f"<div class='meta'><b class='num'>{i}</b> {where_text(s, root)} · {source_line(s)}</div>"
                       f"{update_html(it, root)}{key_number(it, 'kn sm')}<h3><a href='{link}'>{headline_html(it)}</a></h3>"
                       + (f"<p>{esc(it['text'])}</p>" if it["text"] else "") + notes_html(it, ads, False, preview, True)
                       + f"{tag(s)}</div></article>")
    if ar:
        rows = []
        for i, it in enumerate(ar, len(hl) + 1):
            s = it["s"]
            link = esc(story_link(s))
            c = theme_color(s.get("theme"))
            kn = (f"<span class='kchip'><b>{esc(it['number'])}</b> {esc(it.get('number_label', ''))}</span>"
                  if it.get("number") else "")
            rows.append(f"<li id='s{i}' style='--c:{c}'><a class='wl' href='{link}'>{locator(it, c, 'loc', 900, 1)}</a>"
                        f"<div><div class='meta'><b class='num g'>{i}</b> {where_text(s, root)}"
                        + (f" · {esc(s.get('place'))}" if s.get("place") else "") + "</div>"
                        + update_html(it, root) + f"<a class='hl' href='{link}'>{headline_html(it)}</a>"
                        + (f"<div class='txt'>{esc(it['text'])}</div>" if it["text"] else "")
                        + f"{kn}<div class='src'>{source_line(s)}</div>{notes_html(it, ads, False, preview)}</div></li>")
        out.append(f"<h2>Around the world</h2><ul class='world2'>{''.join(rows)}</ul>")
    out.append(case_html(issue, root, preview))
    if issue["research"]:
        rows = "".join(f"<li><a href='{esc(p['s']['link'])}'>{esc(p['title'] or p['s'].get('title', ''))}</a>"
                       f"<div class='j'>{source_line(p['s'])}</div>"
                       + (f"<div>{esc(p['text'])}</div>" if p["text"] else "") + "</li>"
                       for p in issue["research"])
        out.append(f"<section class='papers'><h2>Research highlights</h2><ol>{rows}</ol></section>")
    out.append(events_html(issue, cfg, opts))
    out.append(stay_in_touch(opts))
    if issue["magazine_note"]:
        link = (f" <a href='{esc(issue['magazine_link'])}'>Read it</a>" if issue["magazine_link"] else "")
        out.append(f"<div class='mag'><div class='ic'></div><div><b>From the ISSMGE Magazine</b> — "
                   f"{esc(issue['magazine_note'])}{link}</div></div>")
    out.append("</div>")
    return "".join(out)


def stay_in_touch(opts):
    """The box at the end of an issue: subscribe, unsubscribe, suggestions (Google Forms in the editor's Drive);
    shown once at least one form's address is in config.yaml."""
    links = [(opts["subscribe_form"], "btn red", f"{icon('mail')} Subscribe to this newsletter"),
             (opts["suggest_form"], "btn", f"{icon('lightbulb')} Suggestions for improvement"),
             (opts["unsubscribe_form"], "btn alt", "Unsubscribe")]
    links = [(u, c, t) for u, c, t in links if str(u).startswith("https://")]
    if not links:
        return ""
    btns = "".join(f"<a class='{c}' href='{esc(u)}' target='_blank' rel='noopener'>{t}</a>" for u, c, t in links)
    return (f"<section class='touch'><h2>Stay in touch</h2><p>Receive Geo-News Weekly, tell us how to make it better, "
            f"or leave the list at any time.</p><div class='toolbar'>{btns}</div></section>")


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
<link rel="preload" href="{root}../assets/fonts/libre-franklin-latin-400-normal.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="{root}../assets/fonts/newsreader-latin-600-normal.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{root}../assets/geonews.css?v={asset_version('geonews.css')}">{extra_head}
</head><body><div class="gn-wrap">
{body}
<footer class="gn-foot">Stories come from public news sources in many languages; each headline links to the original publisher,
whose site may be in another language and may show adverts. Please check details with the original source.<br>
Maps: Natural Earth. Satellite views: <a href="https://s2maps.eu">Sentinel-2 cloudless – s2maps.eu</a> by EOX IT Services GmbH
(contains modified Copernicus Sentinel data 2020), <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/">CC BY-NC-SA 4.0</a>.<br>
Fonts: Newsreader and Libre Franklin (SIL Open Font License). Icons: Lucide. Flags: flag-icons.<br>
Prepared by the ISSMGE <a href="{MPC_URL}">Magazine Presidential Committee (MPC)</a></footer>
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
    """The address members use: the newsletter's own website when it has one (geonews: public_url), else the
    geonews/ folder of the News Desk."""
    public = str(settings(cfg)["public_url"] or "").strip()
    if public:
        return public.rstrip("/") + "/" + (key + ".html" if key else "")
    return f"{site_builder.site_url(cfg)}geonews/{key + '.html' if key else 'index.html'}"


PUBLIC_ASSETS = ("geonews.css", "issmge-logo.png", "favicon.svg")
PUBLIC_FOLDERS = ("fonts", "flags", "icons")   # kept with the site, each with its licence (icons: for the licence only)


def public_bundle(dest):
    """The newsletter's own website, from the built docs/geonews/: the published issues, the newest issue and the
    archive at the top level, with their style sheet and pictures, and nothing of the News Desk (no previews, no
    links back). The workflow copies it to the newsletter's own repository (README, "Geo-News Weekly")."""
    global OUT
    import tempfile
    dest = Path(dest)
    if dest.exists():
        shutil.rmtree(dest)
    (dest / "assets").mkdir(parents=True)
    cfg = yaml.safe_load(Path(site_builder.ROOT / "config.yaml").read_text(encoding="utf-8"))
    desk, OUT = OUT, Path(tempfile.mkdtemp())
    try:
        build({"cfg": cfg, "digests": site_builder.load_digests()}, public=True)
        pages = list(OUT.glob("*.html"))
    finally:
        built, OUT = OUT, desk
    for f in pages:
        text = f.read_text(encoding="utf-8").replace("../assets/", "assets/")
        (dest / f.name).write_text(text, encoding="utf-8")
    for name in PUBLIC_ASSETS:
        src = site_builder.ASSETS / name
        if src.exists():
            shutil.copy2(src, dest / "assets" / name)
    for name in PUBLIC_FOLDERS:
        src = site_builder.ASSETS / name
        if src.is_dir():
            shutil.copytree(src, dest / "assets" / name)
    # the satellite views of the published issues only
    copy_pictures(dest / "img", {p.stem for p in dest.glob("*.html") if KEY.match(p.stem)})
    (dest / ".nojekyll").write_text("", encoding="utf-8")
    (dest / "robots.txt").write_text("User-agent: *\nAllow: /\n", encoding="utf-8")
    shutil.rmtree(built, ignore_errors=True)
    # the list of issues on the site: it changes whenever an issue is published, so every publication is a new push,
    # which is what makes GitHub Pages rebuild the site
    issues = sorted(p.stem for p in dest.glob("*.html") if KEY.match(p.stem))
    (dest / "issues.txt").write_text("Geo-News Weekly – published issues\n" + "\n".join(issues) + "\n", encoding="utf-8")
    pages = sorted(p.name for p in dest.glob("*.html"))
    print(f"Geo-News: public site in {dest}: {', '.join(pages)}")
    return pages


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
    if issue.get("case"):
        c = issue["case"]["c"]
        year = re.search(r"\b(1[89]\d\d|20\d\d)\b", str(c.get("date") or ""))
        lines.append(f"Case history: {c.get('name')} ({c.get('country')}" + (f", {year.group(1)}" if year else "") + ").")
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
    """A 1200 × 627 picture for the LinkedIn post (SVG; the preview page saves it as PNG, with the fonts put into it).
    The fonts are named in style attributes, which the page's style sheet does not override."""
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
                     f"font-size='20' font-weight='bold' fill='#fff' style='font-family:{SANS}'>{i}</text>")
        for j, l in enumerate(ls):
            texts.append(f"<text x='92' y='{y + j * 30}' font-size='25' font-weight='600' fill='#2a2024' style='font-family:{SERIF}'>{esc(l)}</text>")
        y += 30 * len(ls) + 26
    inner = map_svg(issue, "", label=True).replace("<svg class=''", "<svg x='470' y='150' width='710' height='400'", 1)
    return (f"<svg xmlns='http://www.w3.org/2000/svg' class='li-card' viewBox='0 0 1200 627' width='1200' height='627'>"
            f"<rect width='1200' height='627' fill='#fffdf8'/>"
            f"<rect width='1200' height='120' fill='#a6242e'/><rect y='120' width='1200' height='8' fill='#b9962e'/>"
            f"<text x='40' y='52' font-size='20' letter-spacing='3' fill='#f3d98b' style='font-family:{SANS}' font-weight='bold'>"
            f"ISSMGE · MAGAZINE PRESIDENTIAL COMMITTEE (MPC)</text>"
            f"<text x='40' y='98' font-size='42' fill='#fff' style='font-family:{SERIF}' font-weight='bold'>{esc(opts['name'])}</text>"
            f"<text x='1010' y='98' text-anchor='end' font-size='26' fill='#fff' style='font-family:{SANS}'>{esc(week_span(issue['key']))}</text>"
            f"<rect x='1036' y='14' width='146' height='94' rx='10' fill='#fff'/>"
            f"<image x='1046' y='20' width='126' height='82' href='{logo_data()}'/>"
            f"<text x='40' y='200' font-size='22' letter-spacing='2' fill='#a6242e' style='font-family:{SANS}' font-weight='bold'>THIS WEEK'S HIGHLIGHTS</text>"
            f"<rect x='40' y='216' width='60' height='5' fill='#b9962e'/>"
            f"{''.join(texts)}{inner}"
            f"<text x='40' y='600' font-size='18' fill='#6b6066' style='font-family:{SANS}'>Full round-up: {esc(page_url(cfg, issue['key']))}</text>"
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
                    f"<td><a href='{esc(story_link(s))}'>{esc(title_of(s))}</a><div class='meta'>{where_text(s, '../')} · {source_line(s)} · "
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


def set_aside_html(key, issue, digests):
    """The week's items not used as news (published before the issue week, or encyclopedia entries), for the editor to
    see; one already in the issue is shaded."""
    stories, _ = week_items(digests, key)
    used = {it["s"]["id"] for it in issue["highlights"] + issue["around"]}
    rows = []
    for s in notify().by_rank(stories):
        why = not_news(s, key) if (s.get("relevance") or 0) >= 3 or s["id"] in used else ""
        if why:
            mark = " class='in'" if s["id"] in used else ""
            rows.append(f"<tr{mark}><td><code>{esc(s['id'])}</code> "
                        f"<button type='button' class='copy' data-copy='{esc(s['id'])}'>Copy</button></td>"
                        f"<td><a href='{esc(story_link(s))}'>{esc(title_of(s))}</a><div class='meta'>{where_text(s, '../')} · "
                        f"{source_line(s)}</div></td><td>{esc(why)}</td></tr>")
    if not rows:
        return ""
    one = len(rows) == 1
    return (f"<section class='tools'><h2>Older or reference items (not used as news)</h2><p>The scan also found "
            f"{len(rows)} {'item that was' if one else 'items that were'} published before the issue week or "
            f"{'comes' if one else 'come'} from an encyclopedia, so the draft does not use {'it' if one else 'them'} as "
            f"news. A shaded item is still in the issue: please replace it. If an item is about a case on the case list "
            f"(such as Vajont), choose that case under Case history.</p><div class='tw'><table class='alt'><tr><th>Code</th>"
            f"<th>Item</th><th>Why</th></tr>{''.join(rows)}</table></div></section>")


def case_tools_html(key, issue):
    """The case history of the issue and three other cases the editor might use instead, with their ids."""
    current = issue.get("case")
    if not current and issue["status"] != "draft":
        return ""
    monday = notify().week_range(key)[0]
    rows = []
    for c in suggest_cases(key, current["c"]["id"] if current else None):
        day = anniversary_day(c, monday, CASE_DAYS)
        rows.append(f"<tr><td><code>{esc(c['id'])}</code> <button type='button' class='copy' data-copy='{esc(c['id'])}'>Copy</button></td>"
                    f"<td><b>{esc(c.get('name', ''))}</b><div class='meta'>{case_flags(c, '../')} {esc(c.get('country', ''))} · "
                    f"{esc(c.get('region', ''))} · {esc(case_when(c))} · {'success' if c.get('outcome') == 'success' else 'failure'}"
                    + (f" · anniversary on {day.day} {day:%b}" if day else "") + "</div></td></tr>")
    now = (f"The case history of this issue is <b>{esc(current['c'].get('name', ''))}</b> (<code>{esc(current['c']['id'])}</code>). "
           if current else "This issue has no case history. ")
    return (f"<section class='tools'><h2>Case history: other suggestions</h2><p>{now}To use another case, press "
            f"<b>Change the stories</b> and choose it under Case history, or write its id after <code>case:</code> in the "
            f"issue file and empty the text. A case is used only once; the whole list is in "
            f"<code>data/geonews/case_histories.yaml</code>.</p>"
            + (f"<div class='tw'><table class='alt'><tr><th>Id</th><th>Case</th></tr>{''.join(rows)}</table></div>" if rows
               else "<p>Every case of the list has been used.</p>") + "</section>")


def review_url(cfg, key):
    return f"{site_builder.site_url(cfg)}geonews/preview/{key}-view.html"


def review_html(key, issue, cfg):
    """The view-only page to send colleagues: the issue as members will see it, with no editing buttons."""
    if issue["status"] == "approved":
        bar = (f"<div class='bar ok'><b>This issue is published.</b> "
               f"<a href='{esc(page_url(cfg, key))}'>Open the published page</a>.</div>")
    else:
        bar = ("<div class='bar draft'><b>Draft for review — not public yet.</b> This is how the issue will look to ISSMGE "
               "members. Headlines open the original news sites. Please send your comments to the editor.</div>")
    return (f"<div class='editor'><div class='ed-k'>ISSMGE · Magazine Presidential Committee (MPC) · draft of week "
            f"{week_no(key)}</div>{bar}</div>" + issue_html(issue, cfg, "../"))


def preview_html(key, issue, error, digests, cfg):
    repo = site_builder.repository(cfg)
    edit = f"https://github.com/{repo}/edit/main/data/geonews/{key}.yaml"
    if error:
        state = (f"<div class='bar err'><b>This issue cannot be shown:</b> {esc(error)}. Open the file, correct it and commit; "
                 f"the preview is rebuilt within a few minutes.</div>")
    elif issue["status"] == "approved":
        state = (f"<div class='bar ok big'><b>{icon('circle-check')} Published.</b> This issue is public. Members see it at "
                 f"<a href='{esc(page_url(cfg, key))}'>{esc(page_url(cfg, key))}</a>.<div class='toolbar'>"
                 f"<a class='btn green' href='{esc(page_url(cfg, key))}'>Open the published page</a></div>"
                 f"<small>To correct it, press {icon('pencil')} Change the stories below and save again; the published page updates too.</small></div>")
    else:
        state = ("<div class='bar draft'><b>Draft — not public yet.</b> Members cannot find this page. Change the stories "
                 "if you wish, then press <b>Approve and publish</b> in the story editor.</div>")
    probs = ("".join(f"<li>{esc(p)}</li>" for p in issue["problems"]) if issue else "")
    problems = f"<div class='bar err'><b>Please check:</b><ul>{probs}</ul></div>" if probs else ""
    tools = ("<div class='toolbar'>" + (f"<button type='button' class='btn' id='ed-open'>{icon('pencil')} Change the stories</button>" if issue else "")
             + (f"<button type='button' class='btn alt' data-copy='{esc(review_url(cfg, key))}'>{icon('link')} Copy the view-only link</button>"
                if issue else "")
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
        parts.append(issue_html(issue, cfg, "../", preview=True))
        parts.append(case_tools_html(key, issue))
        parts.append(set_aside_html(key, issue, digests))
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
def forward_page(url):
    """A page that sends the reader on to the newsletter's own website at once."""
    u = esc(url)
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='robots' content='noindex'>"
            f"<link rel='canonical' href='{u}'><meta http-equiv='refresh' content='0; url={u}'>"
            f"<title>Geo-News Weekly</title><script>location.replace({json.dumps(url)})</script></head>"
            f"<body><p>Geo-News Weekly has moved to <a href='{u}'>{u}</a>.</p></body></html>")


def links_wanted(loaded, digests, public=False):
    """The links of the stories in the issues, then (for the editor's preview of a draft) of the other stories of the
    draft's week, best first: the order in which their publisher's own address is looked for."""
    issues = [i for _, i, _ in loaded if i]
    out = [it["s"].get("link") for i in issues for it in i["highlights"] + i["around"]]
    if not public:
        for i in issues:
            if i["status"] != "draft":
                continue
            stories, _ = week_items(digests, i["key"])
            out += [s.get("link") for s in notify().by_rank(stories) if (s.get("relevance") or 0) >= 3]
    return out


def build(ctx, public=False):
    """docs/geonews/: index.html (newest published issue), <week>.html for each published issue, archive.html,
    and preview/<week>.html for every issue file, draft or published. When the newsletter has its own website
    (geonews: public_url), the pages members read are built only for that site (public=True, see public_bundle);
    the News Desk then keeps the previews and, at the old addresses, pages that forward to the new site."""
    cfg, digests = ctx["cfg"], ctx["digests"]
    forward = bool(str(settings(cfg)["public_url"] or "").strip()) and not public
    stories, papers = all_items(digests)
    for p in papers.values():
        p["_paper"] = True
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "preview").mkdir(exist_ok=True)

    def load_all():
        out = []
        for path in issue_files():
            try:
                issue, error = load_issue(path, stories, papers), ""
            except ValueError as ex:
                issue, error = None, str(ex)
            out.append((path.stem, issue, error))
        return out
    loaded = load_all()
    # the publisher's own address of the stories' links (read again once some are found: the news sites change)
    if decode_links(links_wanted(loaded, digests, public)):
        loaded = load_all()
    for _, issue, _ in loaded:   # the satellite views, kept with the site
        if issue:
            pictures(issue)
    copy_pictures(OUT / "img")
    published = [i for _, i, _ in loaded if i and i["status"] == "approved" and (i["highlights"] or i["around"])]
    keys = [i["key"] for i in published]
    count = len(keys)
    opts = settings(cfg)
    js = f"<script src='../../assets/geonews.js?v={asset_version('geonews.js')}' defer></script>"
    for key, issue, error in loaded:
        site_builder.write(OUT / "preview" / f"{key}.html",
                           shell(cfg, f"Preview · {opts['name']} · week {week_no(key)}", preview_html(key, issue, error, digests, cfg),
                                 "../", "Preview for the MPC editor", js, noindex=True))
        if issue:
            site_builder.write(OUT / "preview" / f"{key}-view.html",
                               shell(cfg, f"For review · {opts['name']} · week {week_no(key)}", review_html(key, issue, cfg),
                                     "../", "Draft for review", js, noindex=True))
    if forward:
        for issue in published:
            site_builder.write(OUT / f"{issue['key']}.html", forward_page(page_url(cfg, issue["key"])))
        site_builder.write(OUT / "index.html", forward_page(page_url(cfg)))
        site_builder.write(OUT / "archive.html", forward_page(page_url(cfg) + "archive.html"))
        return
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


def reviewers():
    """The colleagues who receive the Geo-News e-mails only (the secret GEONEWS_REVIEWERS, addresses separated by commas)."""
    import os
    raw = os.environ.get("GEONEWS_REVIEWERS", "")
    return [a.strip() for a in raw.replace(";", ",").replace("\n", ",").split(",") if "@" in a]


def gn_mail(title, sub, body, why):
    """A Geo-News e-mail in the magazine's colours, with no link to the News Desk. The fonts of the site are named
    first (SERIF, SANS); e-mail programs that do not have them use Georgia and Arial."""
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='color-scheme' content='light'></head><body style='margin:0;padding:0;background:#F2F0EC'>"
            "<div style='max-width:640px;margin:0 auto;background:#ffffff'>"
            "<div style='padding:22px 24px 14px;border-bottom:3px solid #B9962E'>"
            f"<div style='font:600 11px {SANS};letter-spacing:.14em;text-transform:uppercase;color:#A6242E'>"
            "ISSMGE · Magazine Presidential Committee (MPC)</div>"
            f"<div style='font:700 26px/1.2 {SERIF};color:#A6242E;margin:4px 0 2px'>{title}</div>"
            f"<div style='font:13px {SANS};color:#625C60'>{sub}</div></div>"
            f"<div style='padding:6px 24px 22px;font:15px/1.6 {SANS};color:#2A2024'>{body}</div>"
            f"<div style='padding:14px 24px;background:#2A2024;color:#cbbfc3;font:12px/1.6 {SANS}'>{why}</div>"
            "</div></body></html>")


def mail_button(url, label, color="#A6242E"):
    return (f"<p style='margin:18px 0'><a href='{esc(url)}' style='display:inline-block;background:{color};color:#ffffff;"
            f"font:bold 15px {SANS};text-decoration:none;padding:12px 22px;border-radius:24px'>{label}</a></p>")


def mail_heading(text, top=26):
    """A section heading of an e-mail (Highlights, Around the world, LinkedIn post)."""
    return (f"<h3 style='font:bold 12px {SANS};letter-spacing:.12em;text-transform:uppercase;color:#A6242E;"
            f"margin:{top}px 0 12px'>{text}</h3>")


def mail_stories(issue, full=True):
    """The issue in an e-mail: the highlights (headline, place, source and date, one line), if full around the world,
    then the case history. Headlines are underlined so readers see they are links; a thin line and space separate the
    stories."""
    n = notify()
    out = [mail_heading("Highlights")]
    last = len(issue["highlights"])
    for i, it in enumerate(issue["highlights"], 1):
        s = it["s"]
        place = n.country_name(s.get("country")) or "Global"
        meta = " · ".join(x for x in (esc(place), source_line(s)) if x)
        num = f" <b style='color:#A6242E'>{esc(it['number'])}</b> {esc(it.get('number_label', ''))} ·" if it.get("number") else ""
        lead = f" <span style='font:bold 11px {SANS};color:#B9962E'>STORY OF THE WEEK</span>" if i == 1 else ""
        sep = "" if i == last else "padding:0 0 20px;border-bottom:1px solid #E6E1DC;"
        out.append(f"<div style='margin:0 0 20px;{sep}'><div style='font:12px/1.5 {SANS};color:#625C60;margin:0 0 4px'>{i}. {meta}{lead}</div>"
                   f"<a href='{esc(story_link(s))}' style='font:bold 17px/1.35 {SERIF};color:#2A2024;text-decoration:underline'>"
                   f"{headline_html(it)}</a>"
                   + (f"<div style='font:14px/1.55 {SANS};color:#2A2024;margin-top:6px'>{num} {esc(it['text'])}</div>"
                      if it["text"] or num else "") + "</div>")
    if full and issue["around"]:
        out.append(mail_heading("Around the world", 30) + "<ul style='padding-left:18px;margin:0'>")
        for it in issue["around"]:
            s = it["s"]
            meta = " · ".join(x for x in (esc(n.country_name(s.get("country")) or "Global"), source_line(s)) if x)
            out.append(f"<li style='margin:0 0 14px'><a href='{esc(story_link(s))}' style='font:bold 15px/1.4 {SERIF};color:#2A2024;"
                       f"text-decoration:underline'>{headline_html(it)}</a><br>"
                       f"<span style='font:13px/1.5 {SANS};color:#625C60'>{meta}</span></li>")
        out.append("</ul>")
    return "".join(out) + mail_case(issue)


def mail_case(issue):
    """The case history in an e-mail: the case, its country and date, its text and lesson, and where to read more."""
    ch = issue.get("case")
    if not ch:
        return ""
    c = ch["c"]
    story, lesson = case_parts(ch["text"])
    meta = " · ".join(x for x in ("Success" if c.get("outcome") == "success" else "Failure", esc(c.get("country", "")),
                                  esc(case_when(c)), esc(case_anniversary(issue))) if x)
    links = "<br>".join(f"<a href='{esc(site_builder.safe_url(u))}' style='color:#A6242E'>{esc(t)}</a>" for t, u in case_sources(c))
    return (mail_heading("Case history", 30)
            + f"<div style='font:12px/1.5 {SANS};color:#625C60;margin:0 0 4px'>{meta}</div>"
            f"<div style='font:bold 17px/1.35 {SERIF};color:#2A2024'>{esc(c.get('name', ''))}</div>"
            f"<div style='font:14px/1.55 {SANS};color:#2A2024;margin-top:6px'>{esc(story)}</div>"
            + (f"<div style='font:14px/1.55 {SANS};color:#2A2024;margin-top:8px'><b>{LESSON}</b> {esc(lesson)}</div>" if lesson else "")
            + (f"<div style='font:12px/1.6 {SANS};color:#625C60;margin-top:10px'><b>Read more:</b><br>{links}</div>" if links else ""))


def email_draft(issue, cfg, reviewer=False):
    """(subject, html) of the Monday e-mail: to the editor with the editor's preview, to colleagues with the view-only page."""
    key = issue["key"]
    name, span = settings(cfg)["name"], week_span(key)
    if reviewer:
        body = (f"<p>Dear colleague, the draft of <b>{esc(name)}</b> for <b>{esc(span)}</b> is ready for your review. "
                + ("Here are its highlights and its case history; " if issue.get("case") else "Here are its highlights; ")
                + "the full draft shows them with the world map, the stories from around the world, "
                "the research highlights and the events.</p>"
                + mail_button(review_url(cfg, key), "Read the full draft")
                + mail_stories(issue, full=False)
                + "<p>Please send your comments to the editor by replying to this e-mail.</p>")
        return (f"{name} – draft for your review · {span}",
                gn_mail(esc(name), f"Draft for review · week {week_no(key)} · {esc(span)}", body,
                        "You receive this as a reviewer of Geo-News Weekly for the ISSMGE Magazine Presidential Committee (MPC). "
                        "The draft is not public yet."))
    prev = f"{site_builder.site_url(cfg)}geonews/preview/{key}.html"
    body = (f"<p>The draft of <b>{esc(name)}</b> for <b>{esc(span)}</b> is ready.</p>"
            + mail_button(prev, "Open the draft and the story editor")
            + "<p style='font-size:14px'>Change stories with the story editor if needed, then press <b>Approve and publish</b>. "
              f"Colleagues on the review list received the view-only link: <a href='{esc(review_url(cfg, key))}'>"
              f"{esc(review_url(cfg, key))}</a></p>"
            + mail_stories(issue, full=False))
    return (f"{name} draft ready for approval · {span}",
            gn_mail(esc(name), f"Draft ready · week {week_no(key)} · {esc(span)}", body,
                    "You receive this as the editor of Geo-News Weekly."))


def email_approved(issue, cfg, reviewer=False):
    """(subject, html) after publishing: the newsletter in short with a button to the full issue; for the editor also the
    LinkedIn post."""
    key = issue["key"]
    name, span = settings(cfg)["name"], week_span(key)
    intro = f"<p>{esc(issue['intro'])}</p>" + mail_button(page_url(cfg, key), "Read the full newsletter")
    body = intro + mail_stories(issue, full=True) + mail_button(page_url(cfg, key), "Read the full newsletter")
    if reviewer:
        return (f"{name} · {span}",
                gn_mail(esc(name), f"Week {week_no(key)} · {esc(span)}", body,
                        "Published by the ISSMGE Magazine Presidential Committee (MPC). You receive this as a reviewer of Geo-News Weekly."))
    prev = f"{site_builder.site_url(cfg)}geonews/preview/{key}.html"
    li = esc(linkedin_text(issue, cfg)).replace("\n", "<br>")
    body += (mail_heading("LinkedIn post", 30)
             + f"<p style='font-size:14px'>Copy the text below; download the picture from the "
             f"<a href='{esc(prev)}'>preview page</a> (Download the picture).</p>"
             f"<div style='border:1px solid #E6E1DC;border-radius:8px;padding:12px 14px;font:14px/1.5 {SANS};"
             f"background:#F7ECEE'>{li}</div>")
    return (f"{name} published · LinkedIn post ready · {span}",
            gn_mail(esc(name), f"Published · week {week_no(key)} · {esc(span)}", body,
                    "You receive this as the editor of Geo-News Weekly."))


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
            make, label = email_draft, "draft"
        elif issue["status"] == "approved" and k not in rec["approved"] and (issue["highlights"] or issue["around"]):
            make, label = email_approved, "approved"
        else:
            continue
        try:
            subject, html = make(issue, cfg)
            sent, status = n.deliver(subject, html, cfg)
        except n.NotifyError as ex:
            print(f"Geo-News: the {label} e-mail for {k} was not sent: {ex}")
            continue
        print(f"Geo-News: {label} e-mail for {k}: {status}")
        team = reviewers()
        if sent and team:
            try:
                subject, html = make(issue, cfg, reviewer=True)
                print(f"Geo-News: {label} e-mail for {k} to {len(team)} reviewer(s): {n.deliver(subject, html, cfg, to=team)[1]}")
            except n.NotifyError as ex:
                print(f"Geo-News: the {label} e-mail for {k} to the reviewers was not sent: {ex}")
        if sent:
            rec[label][k] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            changed = True
    if changed:
        save_sent(rec)


def sample(cfg, week=None):
    """Send the editor (MAIL_TO only) the two e-mails colleagues receive for an issue (the newest unless week is given),
    marked [Sample]. 0 when sent, 1 when not."""
    n = notify()
    stories, papers = all_items(site_builder.load_digests())
    files = [p for p in issue_files() if not week or p.stem == week]
    if not files:
        print(f"Geo-News: no issue {week or ''} to make a sample of.")
        return 1
    issue = load_issue(files[0], stories, papers)
    ok = True
    for make, what in ((email_draft, "draft for review"), (email_approved, "published newsletter")):
        subject, html = make(issue, cfg, reviewer=True)
        try:
            sent, status = n.deliver("[Sample] " + subject, html, cfg)
        except n.NotifyError as ex:
            sent, status = False, str(ex)
        print(f"Geo-News: sample of the colleagues' {what} e-mail ({issue['key']}): {status}")
        ok = ok and sent
    return 0 if ok else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description="Geo-News Weekly: drafts, pages and e-mails.")
    ap.add_argument("--auto", action="store_true", help="write last week's draft if missing; send e-mails not yet sent")
    ap.add_argument("--draft", action="store_true", help="write a draft now")
    ap.add_argument("--week", help="with --draft: the week, e.g. 2026-W44 (default: last week)")
    ap.add_argument("--force", action="store_true", help="with --draft: replace an existing file")
    ap.add_argument("--sample", action="store_true", help="send the editor (MAIL_TO) a sample of the colleagues' e-mails")
    ap.add_argument("--public-bundle", metavar="FOLDER", help="copy the newsletter's own website (published issues only) to FOLDER")
    args = ap.parse_args(argv)
    cfg = yaml.safe_load(Path(site_builder.ROOT / "config.yaml").read_text(encoding="utf-8"))
    if args.draft:
        key = args.week or notify().last_week(notify().cairo_today())
        if not KEY.match(key):
            ap.error("give the week as 2026-W44")
        ok = write_draft(site_builder.load_digests(), key, cfg, force=args.force)
        print(f"Draft of {key} " + ("written." if ok else "not written: it exists (use --force) or the week has no stories."))
        return 0
    if args.sample:
        return sample(cfg, args.week)
    if args.public_bundle:
        public_bundle(args.public_bundle)
        return 0
    if args.auto:
        auto(cfg)
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
