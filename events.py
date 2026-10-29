#!/usr/bin/env python3
"""
Events calendar: ISSMGE conferences, other events and call-for-papers deadlines,
from data/events.yaml (kept by the editors) and data/events.json (found by the
weekly refresh), listed on docs/events.html, with an iCalendar feed that editors
can subscribe to (docs/events.ics, one .ics file per event in docs/calendar/) and
a machine-readable list (docs/exports/events.json, read by the AI assistant).

    python events.py             the calendar as it stands, and any problems in data/events.yaml
    python events.py --auto      in the daily scan: refresh when the calendar is refresh_days old
    python events.py --refresh   refresh now (the Events page's "Refresh calendar" button)

A refresh asks Claude to read the organisers' calendars (config.yaml, events:
calendars) with Anthropic's web search and web fetch tools. They run on
Anthropic's servers, because issmge.org and most organiser sites cannot be read
from GitHub's runners. A second request, without tools, turns Claude's research
notes into calendar entries, which are checked here before they are kept: a
working https link from a page Claude actually read, real dates in the next
months_ahead months, no predatory conference series. A refresh that fails keeps
the calendar as it was.
"""
import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import quote, urlparse

import yaml

import scanner
import site_builder

ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("SCANNER_CONFIG", ROOT / "config.yaml"))
CURATED_FILE = ROOT / "data" / "events.yaml"   # kept by the editors
FOUND_FILE = ROOT / "data" / "events.json"     # written by the refresh: {"updated": iso, "events": [...], "notes": [...]}
#                                                and, after a refresh that failed, "attempted", "failed" and "retry"
esc = site_builder.esc

KINDS = ["ISSMGE conference", "ISSMGE-supported", "Other conference", "Course / webinar"]
ISSMGE_KINDS = KINDS[:2]
KIND_CLASS = {"ISSMGE conference": "k-conf", "ISSMGE-supported": "k-supp", "Other conference": "k-other",
              "Course / webinar": "k-course"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
RESEARCH_TOKENS = 64000  # thinking, searches and the notes; streamed, so a long turn cannot time out
EXTRACT_TOKENS = 32000
RETRY_DAYS = 2  # after a failed refresh the daily scan waits this long (only a day when Claude was busy)

DEFAULTS = {"model": "claude-opus-5-5", "effort": "medium", "extract_effort": "low", "refresh_days": 7,
            "months_ahead": 24, "deadline_days": 90, "keep_days": 7, "max_searches": 10, "max_fetches": 12,
            "max_page_tokens": 12000, "max_continuations": 3, "max_cost_usd": 3.0}
# list prices in US$ per million tokens (input, output, cache read, 5-minute cache write) and per web
# search, for the cost line in the log; a model not listed here gets token counts only
PRICES = {"claude-opus-5-5": (4.0, 20.0, 0.20, 5.0), "claude-sonnet-5-5": (2.0, 10.0, 0.10, 2.5),
          "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125), "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
          "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5)}
SEARCH_PRICE = 0.01
BUSY_ERRORS = {"overloaded_error", "api_error", "rate_limit_error"}  # Claude busy: worth trying again tomorrow
# sent when the research reaches its limit: Claude writes its event blocks after its last search, so
# rather than stop with no notes it is asked to write them now from what it has read
WRAP_UP = ("The time and budget for this research are used up. Make no more searches or fetches. Write the blocks "
           "now, in the format asked for, for every event you have found so far, and nothing else.")
spent = []  # (model, usage, stopped part-way) of every request this refresh made, for the cost line
DEFAULT_CALENDARS = [
    {"name": "ISSMGE events", "url": "https://www.issmge.org/events"},
    {"name": "ISSMGE news (calls for abstracts)", "url": "https://www.issmge.org/news"},
    {"name": "ITA-AITES future events", "url": "https://about.ita-aites.org/future-events"},
    {"name": "ASCE Geo-Institute conferences and events",
     "url": "https://www.asce.org/communities/institutes-and-technical-groups/geo-institute/conferences-and-events"},
    {"name": "GeoEngineer.org events", "url": "https://www.geoengineer.org/events"},
]
DEFAULT_BLOCKED = ["waset.org", "conferenceindex.org", "conferenceseries.com", "omicsonline.org"]
# WASET-style mass series: "ICGEGT 2027: 21. International Conference on ..." and the like. The
# "21." is the tell: real conferences also write "ICSGE 2027: International Conference on ...".
PREDATORY_NAME = re.compile(r"\b\d{1,2}\.\s*International Conference on\b|World Academy of Science", re.I)
HOSTNAME = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")
# a deadline for abstracts or papers (a call for papers); registration and the like are other deadlines
CALL_LABEL = re.compile(r"abstract|paper|submission|manuscript|contribution|proposal|poster", re.I)
URL_IN_TEXT = re.compile(r"https?://[^\s\"'<>\\)\]]+", re.I)
# the API's answer when the organisation that owns the key has web search (or fetch) turned off
WEB_OFF = re.compile(r"web[ _-]?(?:search|fetch)\b[^.]*\b(?:not enabled|disabled|not available|not allowed|turned off)"
                     r"|(?:enable|turn on)[^.]*\bweb[ _-]?(?:search|fetch)", re.I)

ICONS = {
    "calendar": "<rect x='3' y='4' width='18' height='18' rx='2'/><path d='M16 2v4M8 2v4M3 10h18'/>",
    "pin": "<path d='M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z'/><circle cx='12' cy='10' r='3'/>",
    "external": "<path d='M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6'/>",
    "plus": "<rect x='3' y='4' width='18' height='18' rx='2'/><path d='M3 10h18M12 13v6M9 16h6'/>",
    "edit": "<path d='M12 20h9'/><path d='M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z'/>",
    "rss": "<path d='M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16'/><circle cx='5' cy='19' r='1'/>",
    "copy": "<rect x='9' y='9' width='13' height='13' rx='2'/><path d='M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1'/>",
    "clock": "<circle cx='12' cy='12' r='9'/><path d='M12 7v5l3 2'/>",
}
# Country names when geomap.country_name() is not available (it covers every code).
COUNTRY_NAMES = {
    "AR": "Argentina", "AT": "Austria", "AU": "Australia", "BE": "Belgium", "BR": "Brazil", "CA": "Canada",
    "CH": "Switzerland", "CL": "Chile", "CN": "China", "CO": "Colombia", "CZ": "Czechia", "DE": "Germany",
    "DK": "Denmark", "EG": "Egypt", "ES": "Spain", "FI": "Finland", "FR": "France", "GB": "United Kingdom",
    "GR": "Greece", "HK": "Hong Kong", "HR": "Croatia", "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland",
    "IL": "Israel", "IN": "India", "IR": "Iran", "IS": "Iceland", "IT": "Italy", "JP": "Japan", "KE": "Kenya",
    "KR": "South Korea", "KZ": "Kazakhstan", "MA": "Morocco", "MX": "Mexico", "MY": "Malaysia", "NG": "Nigeria",
    "NL": "Netherlands", "NO": "Norway", "NZ": "New Zealand", "PE": "Peru", "PH": "Philippines", "PL": "Poland",
    "PT": "Portugal", "QA": "Qatar", "RO": "Romania", "RS": "Serbia", "RU": "Russia", "SA": "Saudi Arabia",
    "SE": "Sweden", "SG": "Singapore", "SI": "Slovenia", "TH": "Thailand", "TN": "Tunisia", "TR": "Türkiye",
    "TW": "Taiwan", "UA": "Ukraine", "AE": "United Arab Emirates", "US": "United States", "VN": "Vietnam",
    "ZA": "South Africa",
}
NAME_TO_CODE = {v.lower(): k for k, v in {**site_builder.COUNTRIES, **COUNTRY_NAMES}.items()}
NAME_TO_CODE.update({"usa": "US", "uk": "GB", "england": "GB", "scotland": "GB", "turkey": "TR", "korea": "KR",
                     "the netherlands": "NL", "uae": "AE", "czech republic": "CZ"})


class ScanError(Exception):
    """A refresh could not be completed; the message says why, for the log and the page.
    transient: Claude was busy or could not be reached, so the next daily scan may well succeed."""

    def __init__(self, message, transient=False):
        super().__init__(message)
        self.transient = transient


class Problem(Exception):
    """An event that cannot be kept; the message says why."""


# ------------------------------------------------------------------ settings
def settings(cfg):
    """The events: section of config.yaml, with defaults. A value that cannot be read
    is reported and its default used, so a typo there never stops the site from being built."""
    e = cfg.get("events")
    e = e if isinstance(e, dict) else {}
    out = {}
    for name, default in DEFAULTS.items():
        value = e.get(name)
        if isinstance(default, str):
            value = str(value or default).strip()
            if name.endswith("effort") and value not in EFFORTS:
                print(f"config.yaml, events: {name}: {value!r} is not one of {', '.join(EFFORTS)}; using {default}.")
                value = default
            out[name] = value
            continue
        kind = float if isinstance(default, float) else int
        try:
            if isinstance(value, bool):
                raise ValueError
            out[name] = default if value is None else max(kind(0), kind(value))
        except (TypeError, ValueError):
            print(f"config.yaml, events: {name}: {value!r} is not a {'number' if kind is float else 'whole number'}; "
                  f"using {default}.")
            out[name] = default
    cals = e.get("calendars") if isinstance(e.get("calendars"), list) else DEFAULT_CALENDARS
    out["calendars"] = [{"name": text(c.get("name"), 80) or c.get("url"), "url": c["url"]} for c in cals
                        if isinstance(c, dict) and str(c.get("url", "")).startswith("https://")]
    blocked = e.get("blocked_domains") if isinstance(e.get("blocked_domains"), list) else DEFAULT_BLOCKED
    out["blocked_domains"] = sorted({str(d).strip().lower().removeprefix("www.") for d in blocked
                                     if HOSTNAME.match(str(d).strip().lower())})
    orgs = e.get("blocked_organisers") if isinstance(e.get("blocked_organisers"), list) else []
    out["blocked_organisers"] = [str(o).strip().lower() for o in orgs if str(o).strip()]
    return out


# ------------------------------------------------------------------ small helpers
def text(value, n=200):
    """One clean line of at most n characters (feed and web text is untrusted)."""
    value = site_builder.CONTROL_CHARS.sub("", " ".join(str(value if value is not None else "").split()))
    return value if len(value) <= n else value[:n - 1].rstrip() + "…"


def icon(name, cls="ico"):
    path = ICONS.get(name)
    if path is None:
        return site_builder.icon(name, cls)
    return (f"<svg class='{cls}' viewBox='0 0 24 24' fill='none' stroke='currentColor' stroke-width='2' "
            f"stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>{path}</svg>")


DATE = re.compile(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?$")


def parse_date(value):
    """'YYYY-MM-DD', or 'YYYY-MM' when only the month is known; "" when value is not a date."""
    if isinstance(value, dt.datetime):
        value = value.date()
    if isinstance(value, dt.date):
        return value.isoformat()
    m = DATE.match(str(value if value is not None else "").strip())
    if not m or not 1900 <= int(m[1]) <= 2999:  # a mistyped year (9999) would overflow the date sums
        return ""
    try:
        day = dt.date(int(m[1]), int(m[2]), int(m[3] or 1))
    except ValueError:
        return ""
    return day.isoformat() if m[3] else day.isoformat()[:7]


def first_day(iso):
    return dt.date.fromisoformat(iso if len(iso) == 10 else iso + "-01")


def last_day(iso):
    if len(iso) == 10:
        return dt.date.fromisoformat(iso)
    y, m = int(iso[:4]), int(iso[5:7])
    return dt.date(y + m // 12, m % 12 + 1, 1) - dt.timedelta(days=1)


def add_months(day, n):
    y, m = divmod(day.month - 1 + n, 12)
    y += day.year
    m += 1
    for d in (day.day, 30, 29, 28):
        try:
            return dt.date(y, m, d)
        except ValueError:
            continue


def month_only(iso):
    return len(iso) == 7


def nice(iso):
    """'14 Apr 2027', or 'Apr 2027' for a month-only date."""
    if not iso:
        return ""
    if month_only(iso):
        return f"{site_builder.MONTHS[int(iso[5:7]) - 1]} {iso[:4]}"
    return site_builder.nice_date(iso)


def date_range(start, end):
    """'12–14 Apr 2027', '28 Jun – 1 Jul 2027', '30 Dec 2027 – 2 Jan 2028', 'Nov 2027'."""
    if not end or end == start:
        return nice(start)
    if month_only(start) or month_only(end):
        a, b = nice(start), nice(end)
        return a if a == b else (f"{a.split()[0]} – {b}" if a[-4:] == b[-4:] else f"{a} – {b}")
    s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if (s.year, s.month) == (e.year, e.month):
        return f"{s.day}–{e.day} {s:%b %Y}"
    if s.year == e.year:
        return f"{s.day} {s:%b} – {e.day} {e:%b %Y}"
    return f"{s.day} {s:%b %Y} – {e.day} {e:%b %Y}"


def days_left(n):
    return "today" if n == 0 else "tomorrow" if n == 1 else f"{n} days left" if n > 1 else "passed"


def left_text(iso, today):
    """'12 days left', 'passed', or 'exact date TBC' for a deadline known only by its month."""
    n = (last_day(iso) - today).days
    return "exact date TBC" if month_only(iso) and n >= 0 else days_left(n)


def left_html(iso, today):
    """The days-left label; for an exact date the page's script recounts it from the reader's today."""
    count_ = "" if month_only(iso) else f" data-left='{iso}'"
    return f"<em class='ev-left'{count_}>{esc(left_text(iso, today))}</em>"


def slug(value):
    value = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def host(url):
    try:
        h = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return h.removeprefix("www.")


def on_domain(h, domains):
    return any(h == d or h.endswith("." + d) for d in domains)


def country_name(code):
    """English name of a country code: geomap's when available, else the short list here."""
    if not code:
        return ""
    try:
        import geomap
        name = getattr(geomap, "country_name", None)
        found = name(code) if name else ""
    except (ImportError, KeyError, ValueError, TypeError):
        found = ""
    return found or COUNTRY_NAMES.get(code) or site_builder.COUNTRIES.get(code) or code


def region_of(event, cfg):
    """The ISSMGE region of the event's country (geomap), "Online", or ""."""
    if event["online"] and not event["country"]:
        return "Online"
    if not event["country"]:
        return ""
    try:
        import geomap
        region = getattr(geomap, "issmge_region", None)
        return (region(event["country"], cfg) or "") if region else ""
    except (ImportError, KeyError, ValueError, TypeError):
        return ""


def place(event):
    """'Lyon, France', 'Online' or ''."""
    where = ", ".join(x for x in (event["city"], country_name(event["country"])) if x)
    if event["online"]:
        return f"{where} and online" if where else "Online"
    return where


def label_of(event):
    return event["short"] or event["name"]


def full_name(event):
    """'2nd International Symposium on Ground Improvement (IS-GI 2027)'."""
    short = event["short"]
    return event["name"] + (f" ({short})" if short and short.lower() not in event["name"].lower() else "")


# ------------------------------------------------------------------ reading and checking events
def to_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "yes", "y", "1", "online")


def clean_event(raw, source, https_only=False):
    """A checked event dict (the calendar's shape) from one entry, or Problem with the reason."""
    name = text(raw.get("name"), 200)
    if not name:
        raise Problem("it has no name")
    start = parse_date(raw.get("start"))
    if not start:
        raise Problem(f"the start date {str(raw.get('start') or '')!r} is not a date (write it as YYYY-MM-DD)"
                      if raw.get("start") else "it has no start date")
    end = parse_date(raw.get("end")) if raw.get("end") else start
    if not end:
        raise Problem(f"the end date {str(raw.get('end'))!r} is not a date (write it as YYYY-MM-DD)")
    if last_day(end) < first_day(start):
        raise Problem(f"it ends ({end}) before it starts ({start})")
    url = text(raw.get("url"), 500)
    if not re.match(r"https://" if https_only else r"https?://", url, re.I) or not host(url):
        raise Problem("its web address is missing or does not start with https://" if url or https_only
                      else "it has no web address (url)")
    country, warn = "", []  # warn: what was dropped or changed, for the editors
    given = text(raw.get("country"), 60)
    if given:
        country = scanner.country_code(given) or NAME_TO_CODE.get(given.lower(), "")
        if not country:
            warn.append(f"country {given!r} is not a two-letter country code (FR, GB, US …), so it is not shown")
    kind = text(raw.get("kind"), 40)
    matched = next((k for k in KINDS if k.lower() == kind.lower()), "")
    if kind and not matched:
        warn.append(f"kind {kind!r} is not one of: {', '.join(KINDS)}; it is shown as Other conference")
    kind = matched or "Other conference"
    deadlines, given = [], raw.get("deadlines") or []
    if not isinstance(given, list):
        warn.append("the deadlines are not written as a list (\"- label: …\" and \"date: …\"), so they are left out")
        given = []
    for d in given:
        if not isinstance(d, dict):
            warn.append("a deadline is not written as label and date, so it is left out")
            continue
        when = parse_date(d.get("date"))
        if not when:
            warn.append(f"deadline {text(d.get('label'), 40) or '?'!r} has no readable date, so it is left out")
            continue
        deadlines.append({"label": text(d.get("label"), 60) or "Deadline", "date": when})
    deadlines.sort(key=lambda d: first_day(d["date"]))
    event = {
        "id": slug(raw.get("id") or "")[:60], "name": name, "short": text(raw.get("short"), 40),
        "start": start, "end": end, "city": text(raw.get("city"), 80), "country": country,
        "online": to_bool(raw.get("online")), "organiser": text(raw.get("organiser"), 160), "kind": kind,
        # ISSMGE's own and supported events always count as ISSMGE events; others when marked so
        "issmge": kind in ISSMGE_KINDS or raw.get("issmge") is True,
        "url": site_builder.safe_url(url), "deadlines": deadlines, "source": source,
        "found": parse_date(raw.get("found")) if source == "scan" else "", "notes": text(raw.get("notes"), 300),
    }
    return event, warn


class TextDates(yaml.SafeLoader):
    """YAML as safe_load reads it, except that dates stay text: a mistyped date (2027-02-30)
    is then one entry's problem instead of making the whole file unreadable."""


TextDates.yaml_implicit_resolvers = {
    first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()}


def read_curated(problems):
    """The editors' events (data/events.yaml), checked; what cannot be read is added to problems."""
    if not CURATED_FILE.exists():
        return []
    try:
        data = yaml.load(CURATED_FILE.read_text(encoding="utf-8"), Loader=TextDates)
    except (yaml.YAMLError, UnicodeDecodeError, ValueError) as ex:
        where = re.sub(r'\s*in "<unicode string>",?', "", str(ex))  # keeps "line 3, column 7"
        problems.append("data/events.yaml could not be read, so the editors' events are missing until it is fixed: "
                        + text(where, 240))
        return []
    if isinstance(data, dict):  # "events:" above the list is fine too
        data = data.get("events")
    if data is None:
        return []
    if not isinstance(data, list):
        problems.append("data/events.yaml should be a list of events, each starting with \"- name:\".")
        return []
    out = []
    for n, raw in enumerate(data, 1):
        if not isinstance(raw, dict):
            problems.append(f"data/events.yaml, entry {n}: not an event (each one starts with \"- name:\"); left out.")
            continue
        where = f"data/events.yaml, entry {n}" + (f" ({text(raw.get('name'), 60)})" if raw.get("name") else "")
        try:
            event, warn = clean_event(raw, "editors")
        except Problem as ex:
            problems.append(f"{where}: left out because {ex}.")
            continue
        if warn:
            problems.append(f"{where}: " + "; ".join(warn) + ".")
        out.append(event)
    return out


def read_found():
    """The last refresh: {"updated": iso or "", "events": [...], "notes": [...]}, and "attempted" (iso),
    "failed" (why) and "retry" (YYYY-MM-DD), all "" unless a later refresh failed; empty when missing or unreadable."""
    try:
        data = json.loads(FOUND_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"updated": "", "events": [], "notes": [], "attempted": "", "failed": "", "retry": ""}
    data = data if isinstance(data, dict) else {}
    found, notes = data.get("events"), data.get("notes")
    events = []
    for raw in found if isinstance(found, list) else []:
        if isinstance(raw, dict):
            try:
                events.append(clean_event(raw, "scan")[0])
            except Problem:
                continue
    stamps, when = {}, {}
    for k in ("updated", "attempted"):
        stamps[k] = str(data.get(k) or "")
        try:
            w = dt.datetime.fromisoformat(stamps[k])
            when[k] = w if w.tzinfo else w.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            stamps[k] = ""
    # a refresh that failed after the last one that worked (a later success clears it)
    failed = "attempted" in when and ("updated" not in when or when["attempted"] > when["updated"])
    retry = parse_date(data.get("retry")) if failed else ""
    return {"updated": stamps["updated"], "events": events,
            "notes": [text(n, 400) for n in (notes if isinstance(notes, list) else []) if n],
            "attempted": stamps["attempted"] if failed else "", "failed": text(data.get("failed"), 400) if failed else "",
            "retry": retry if len(retry) == 10 else ""}


STOP = {"the", "of", "on", "and", "for", "in", "a", "an", "to", "at", "with", "international", "conference",
        "symposium", "congress", "workshop", "annual", "meeting", "edition", "part", "issmge"}


def words(name):
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    plain = re.sub(r"\b(?:19|20)\d\d\b|\b\d+(?:st|nd|rd|th)\b", " ", plain)
    return {w for w in re.findall(r"[a-z0-9]+", plain) if w not in STOP and not w.isdigit()}


def norm_url(url):
    p = urlparse(url)
    return host(url) + p.path.rstrip("/").lower()


def acronym(e):
    return re.sub(r"[^a-z0-9]", "", e["short"].lower())


def overlap(a, b):
    """The share of the two names' words that they have in common (0 to 1)."""
    wa, wb = words(a["name"]), words(b["name"])
    return len(wa & wb) / len(wa | wb) if wa and wb else 0


def same_name(a, b):
    """The names say it is one event: the same words or acronym, or most of the words shared."""
    wa, wb = words(a["name"]), words(b["name"])
    sa, sb = acronym(a), acronym(b)
    return bool(wa and wa == wb or sa and sa == sb or overlap(a, b) >= 0.75)


def named_alike(a, b):
    """The names agree in part, or one names the other's acronym ("18ARC" for the 18th Asian
    Regional Conference)."""
    sa, sb = acronym(a), acronym(b)
    return overlap(a, b) >= 0.3 or bool(sa and sa in words(b["name"]) or sb and sb in words(a["name"]))


def same_event(a, b):
    """Two entries for one event: the same name or acronym in the same year, the same link with
    most of the name shared, or the same start day with names that agree in part and the same
    link or city. A TC workshop that starts on a conference's first day in the same city is an
    event of its own, and so are two webinars that both link to the organiser's events page."""
    if first_day(a["start"]).year != first_day(b["start"]).year:
        return False
    if same_name(a, b):
        return True
    same_link = norm_url(a["url"]) == norm_url(b["url"])
    if same_link and overlap(a, b) >= 0.5:
        return True
    same_city = bool(a["city"] and a["city"].lower() == b["city"].lower())
    return a["start"] == b["start"] and (same_link or same_city) and named_alike(a, b)


def assign_ids(events):
    """A stable, readable id for every event (anchors, file names, calendar UIDs). Ids already
    given (by the editors or an earlier refresh) are kept, so links and calendar entries stay put."""
    used = set()
    for e in events:
        if e["id"] in used:
            e["id"] = ""  # a second event with the same id gets a new one below
        elif e["id"]:
            used.add(e["id"])
    for e in events:
        if e["id"]:
            continue
        base = slug(e["short"] or e["name"])[:50].strip("-") or "event"
        if e["start"][:4] not in base:
            base = f"{base}-{e['start'][:4]}"
        new, n = base, 2
        while new in used:
            new, n = f"{base}-{n}", n + 1
        e["id"] = new
        used.add(new)


def merge_deadlines(keep, extra):
    """keep's deadlines plus those of extra with labels keep does not have."""
    have = {d["label"].lower() for d in keep}
    return sorted(keep + [d for d in extra if d["label"].lower() not in have], key=lambda d: first_day(d["date"]))


def load(cfg, problems=None):
    """Every event: the editors' list, then the events the refresh found that are not on it
    (an editors' entry always wins; when it has no deadlines yet, the refresh's are shown if the
    names agree). A found event whose site or organiser has since been blocked in config.yaml is left out."""
    problems = [] if problems is None else problems
    curated = read_curated(problems)
    found = read_found()
    opts = settings(cfg)
    out = list(curated)
    for e in found["events"]:
        if blocked(e, opts):
            continue
        twin = next((c for c in curated if same_event(c, e)), None)
        if twin is not None:
            if not twin["deadlines"] and e["deadlines"] and same_name(twin, e):
                twin["deadlines"] = list(e["deadlines"])
                twin["notes"] = " ".join(x for x in (twin["notes"].rstrip(".") + "." if twin["notes"] else "",
                                                     "Deadlines found by the weekly refresh"
                                                     + (f" on {nice(found['updated'][:10])}" if found["updated"] else "")
                                                     + "; check them on the event's website.") if x)
            continue
        twin = next((o for o in out if o["source"] == "scan" and same_event(o, e)), None)
        if twin is not None:
            twin["deadlines"] = merge_deadlines(twin["deadlines"], e["deadlines"])
            continue
        out.append(e)
    assign_ids(out)
    out.sort(key=lambda e: (first_day(e["start"]), e["name"].lower()))
    return out


def is_past(event, today):
    return last_day(event["end"]) < today


def upcoming(cfg, today, days=365):
    """Events starting within [today, today + days], and those under way today, by start date."""
    horizon = today + dt.timedelta(days=days)
    return [e for e in load(cfg) if first_day(e["start"]) <= horizon and not is_past(e, today)]


def open_deadlines(events, today, days):
    out = []
    for e in events:
        if is_past(e, today):
            continue
        for d in e["deadlines"]:
            if last_day(d["date"]) >= today and first_day(d["date"]) <= today + dt.timedelta(days=days):
                out.append({"date": d["date"], "label": d["label"], "event": e})
    out.sort(key=lambda x: (first_day(x["date"]), x["event"]["name"].lower()))
    return out


def deadlines(cfg, today, days=90):
    """Open deadlines within the next days, soonest first: [{"date", "label", "event"}]."""
    return open_deadlines(load(cfg), today, days)


def left_of(date_iso, today):
    """Days from today to a deadline (to the month's end for a month-only date)."""
    return (last_day(date_iso) - today).days


# ------------------------------------------------------------------ sidebar for the Latest and issue pages
def date_tile(iso):
    """Day number and month for the small date tiles ('15' 'Jan'), or the month alone."""
    if month_only(iso):
        return f"<b>{site_builder.MONTHS[int(iso[5:7]) - 1]}</b>{iso[:4]}"
    d = dt.date.fromisoformat(iso)
    return f"<b>{d.day}</b>{d:%b}"


def sidebar(cfg, root, today, limit=5):
    """'Upcoming events & deadlines': the next deadlines (calls for papers, registration) and events, for other pages.
    Empty when the calendar has nothing coming up."""
    opts = settings(cfg)
    events = load(cfg)
    horizon = add_months(today, opts["months_ahead"])
    coming = [e for e in events if not is_past(e, today) and first_day(e["start"]) <= horizon]
    calls = open_deadlines(events, today, opts["deadline_days"])
    if not coming and not calls:
        return ""
    n_calls = min(len(calls), max(limit // 2, limit - len(coming)))  # about half each when both are full
    deadline_items_, event_items = [], []
    for c in calls[:n_calls]:
        e, n = c["event"], left_of(c["date"], today)
        deadline_items_.append(
            f"<li class='ev-side-dl{' ev-urgent' if n <= 14 else ''}'><span class='ev-side-date'>{date_tile(c['date'])}</span>"
            f"<span class='ev-side-txt'><a href='{root}events.html#ev-{esc(e['id'])}'>{esc(c['label'])} · "
            f"{esc(label_of(e))}</a><small>{esc(left_text(c['date'], today))}</small></span></li>")
    for e in coming[:max(0, limit - n_calls)]:
        when = (f"under way until {nice(e['end'])}" if first_day(e["start"]) <= today
                else date_range(e["start"], e["end"]))
        sub = " · ".join(x for x in (place(e), when) if x)
        event_items.append(f"<li><span class='ev-side-date'>{date_tile(e['start'])}</span><span class='ev-side-txt'>"
                           f"<a href='{root}events.html#ev-{esc(e['id'])}' dir='auto'>{esc(e['name'])}</a>"
                           f"<small>{esc(sub)}</small></span></li>")
    cols = "".join(f"<div><h3>{title}</h3><ul class='ev-side-list'>{''.join(items)}</ul></div>"
                   for title, items in (("Deadlines", deadline_items_), ("Coming up", event_items)) if items)
    return (f"<aside class='ev-side' aria-label='Upcoming events and deadlines'><div class='ev-side-head'>"
            f"<h2>{icon('calendar')}Upcoming events &amp; deadlines</h2>"
            f"<a href='{root}events.html'>Full calendar →</a></div><div class='ev-side-cols'>{cols}</div></aside>")


# ------------------------------------------------------------------ iCalendar (RFC 5545)
def ics_text(value):
    """TEXT value: backslash, semicolon, comma and line breaks escaped."""
    value = site_builder.CONTROL_CHARS.sub("", str(value))
    return (value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def ics_fold(line):
    """Lines of at most 75 octets, continued on lines that start with a space, never
    splitting a UTF-8 character."""
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > 75:
            out.append(cur)
            cur, size = " ", 1
        cur += ch
        size += n
    out.append(cur)
    return "\r\n".join(out)


def ics_uid(*parts):
    return "-".join(slug(p) for p in parts if p) + "@geotech-news-desk"


def ics_event(e, stamp):
    """VEVENT lines for an event (all day, DTEND the day after the last day), or [] for month-only dates."""
    if month_only(e["start"]) or month_only(e["end"]):
        return []
    desc = [e["name"]]
    if e["organiser"]:
        desc.append(f"Organiser: {e['organiser']}")
    desc.append(f"Kind: {e['kind']}")
    for d in e["deadlines"]:
        desc.append(f"{d['label']}: {nice(d['date'])}")
    if e["notes"]:
        desc.append(e["notes"])
    desc.append(f"Event website: {e['url']}")
    desc.append("Listed by the ISSMGE Magazine editors" if e["source"] == "editors"
                else "Found by the weekly calendar refresh; check the dates on the event's website")
    lines = ["BEGIN:VEVENT", f"UID:{ics_uid(e['id'])}", f"DTSTAMP:{stamp}",
             f"DTSTART;VALUE=DATE:{first_day(e['start']):%Y%m%d}",
             f"DTEND;VALUE=DATE:{last_day(e['end']) + dt.timedelta(days=1):%Y%m%d}",
             f"SUMMARY:{ics_text(full_name(e))}", f"DESCRIPTION:{ics_text(chr(10).join(desc))}"]
    if place(e):
        lines.append(f"LOCATION:{ics_text(place(e))}")
    if e["url"] != "#":
        lines.append(f"URL:{e['url']}")
    lines += [f"CATEGORIES:{ics_text(e['kind'])}", "TRANSP:TRANSPARENT", "END:VEVENT"]
    return lines


def ics_deadline(e, d, stamp):
    if month_only(d["date"]):
        return []
    day = dt.date.fromisoformat(d["date"])
    where = ", ".join(x for x in (date_range(e["start"], e["end"]), place(e)) if x)
    desc = f"{d['label']} deadline for {full_name(e)} ({where}).\nEvent website: {e['url']}"
    # a second deadline with the same label (an extension) needs its own UID, or calendars merge the two
    n = [x["label"].lower() for x in e["deadlines"]][:e["deadlines"].index(d)].count(d["label"].lower())
    uid = ics_uid(e["id"], "deadline", d["label"], str(n + 1) if n else "")
    return ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + dt.timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{ics_text('Deadline: ' + d['label'] + ' – ' + label_of(e))}",
            f"DESCRIPTION:{ics_text(desc)}", *([f"URL:{e['url']}"] if e["url"] != "#" else []),
            f"CATEGORIES:{'Call for papers' if CALL_LABEL.search(d['label']) else 'Deadline'}", "TRANSP:TRANSPARENT",
            "END:VEVENT"]


def ics_calendar(blocks, name, cfg):
    mag = (cfg.get("magazine") or {}).get("name", "ISSMGE Magazine")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Geotechnical News Desk//Events calendar//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{ics_text(name)}", f"NAME:{ics_text(name)}",
             f"X-WR-CALDESC:{ics_text('Geotechnical conferences and call-for-papers deadlines, from the ' + mag + ' news desk')}",
             "REFRESH-INTERVAL;VALUE=DURATION:P1D", "X-PUBLISHED-TTL:P1D"]
    for b in blocks:
        lines += b
    lines.append("END:VCALENDAR")
    return "".join(ics_fold(line) + "\r\n" for line in lines)


def stamp_of(updated, today):
    """DTSTAMP: when the calendar data last changed (the refresh), else today, in UTC."""
    try:
        when = dt.datetime.fromisoformat(updated)
        when = when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        when = dt.datetime.combine(today, dt.time(), dt.timezone.utc)
    return when.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


# ------------------------------------------------------------------ the map of events (Events page)
# Where the events' cities are (latitude, longitude), for the map on the Events page: the cities of the calendar and
# others where geotechnical conferences are often held. Names are matched without accents or case ("Zürich" and
# "zurich" are the same); a few have their other usual names too. An event in a city not listed here is shown in the
# middle of its country, and the map says so; add the city here (country code, then "City": (latitude, longitude))
# to place it exactly. Two names at the same point are one place, shown by the name listed first ("Wien" is Vienna).
# Overseas territories have their own codes (RE Réunion, GP Guadeloupe ...), at the end: the map draws them with their
# country, and an event there in a city not listed is shown at the territory's first city.
CITY_POINTS = {
    "AE": {"Abu Dhabi": (24.45, 54.38), "Dubai": (25.20, 55.27), "Sharjah": (25.35, 55.42)},
    "AL": {"Tirana": (41.33, 19.82)},
    "AM": {"Yerevan": (40.18, 44.51)},
    "AR": {"Buenos Aires": (-34.60, -58.38), "Córdoba": (-31.42, -64.19), "Mendoza": (-32.89, -68.85),
           "Rosario": (-32.95, -60.65), "Bariloche": (-41.13, -71.31), "San Carlos de Bariloche": (-41.13, -71.31),
           "Salta": (-24.78, -65.42), "Neuquén": (-38.95, -68.06), "Mar del Plata": (-38.00, -57.55)},
    "AT": {"Vienna": (48.21, 16.37), "Wien": (48.21, 16.37), "Graz": (47.07, 15.44), "Innsbruck": (47.27, 11.40),
           "Salzburg": (47.81, 13.06), "Linz": (48.31, 14.29), "Leoben": (47.38, 15.09)},
    "AU": {"Sydney": (-33.87, 151.21), "Melbourne": (-37.81, 144.96), "Brisbane": (-27.47, 153.03),
           "Perth": (-31.95, 115.86), "Adelaide": (-34.93, 138.60), "Canberra": (-35.28, 149.13),
           "Hobart": (-42.88, 147.33), "Darwin": (-12.46, 130.84), "Gold Coast": (-28.02, 153.40),
           "Cairns": (-16.92, 145.77), "Townsville": (-19.26, 146.82), "Wollongong": (-34.42, 150.89)},
    "AZ": {"Baku": (40.41, 49.87)},
    "BA": {"Sarajevo": (43.86, 18.41)},
    "BD": {"Dhaka": (23.81, 90.41), "Chittagong": (22.36, 91.78)},
    "BE": {"Brussels": (50.85, 4.35), "Bruxelles": (50.85, 4.35), "Antwerp": (51.22, 4.40), "Antwerpen": (51.22, 4.40),
           "Ghent": (51.05, 3.72), "Gent": (51.05, 3.72), "Leuven": (50.88, 4.70), "Liège": (50.63, 5.57),
           "Bruges": (51.21, 3.22)},
    "BG": {"Sofia": (42.70, 23.32), "Varna": (43.21, 27.91), "Plovdiv": (42.14, 24.75)},
    "BO": {"La Paz": (-16.50, -68.15), "Santa Cruz de la Sierra": (-17.78, -63.18), "Santa Cruz": (-17.78, -63.18)},
    "BR": {"São Paulo": (-23.55, -46.63), "Rio de Janeiro": (-22.91, -43.17), "Brasília": (-15.79, -47.88),
           "Belo Horizonte": (-19.92, -43.94), "Porto Alegre": (-30.03, -51.22), "Salvador": (-12.97, -38.50),
           "Recife": (-8.05, -34.88), "Fortaleza": (-3.73, -38.53), "Curitiba": (-25.43, -49.27),
           "Florianópolis": (-27.60, -48.55), "Foz do Iguaçu": (-25.55, -54.59), "Manaus": (-3.12, -60.02),
           "Belém": (-1.46, -48.50), "Natal": (-5.79, -35.21), "Campinas": (-22.91, -47.06), "São Carlos": (-22.02, -47.89),
           "Vitória": (-20.32, -40.34), "Goiânia": (-16.69, -49.26)},
    "BW": {"Gaborone": (-24.65, 25.91)},
    "CA": {"Toronto": (43.65, -79.38), "Montreal": (45.50, -73.57), "Montréal": (45.50, -73.57), "Vancouver": (49.28, -123.12),
           "Ottawa": (45.42, -75.70), "Calgary": (51.05, -114.07), "Edmonton": (53.55, -113.49),
           "Quebec City": (46.81, -71.21), "Québec": (46.81, -71.21), "Halifax": (44.65, -63.58),
           "Winnipeg": (49.90, -97.14), "Niagara Falls": (43.09, -79.08), "Saskatoon": (52.13, -106.67),
           "St. John's": (47.56, -52.71), "Victoria": (48.43, -123.37)},
    "CH": {"Zurich": (47.38, 8.54), "Geneva": (46.20, 6.14), "Genève": (46.20, 6.14), "Lausanne": (46.52, 6.63),
           "Bern": (46.95, 7.45), "Basel": (47.56, 7.59), "Lugano": (46.00, 8.95), "Lucerne": (47.05, 8.31)},
    "CI": {"Abidjan": (5.36, -4.01)},
    "CL": {"Santiago": (-33.45, -70.67), "Valparaíso": (-33.05, -71.62), "Viña del Mar": (-33.02, -71.55),
           "Concepción": (-36.83, -73.05), "Antofagasta": (-23.65, -70.40), "La Serena": (-29.90, -71.25),
           "Puerto Varas": (-41.32, -72.99), "Puerto Montt": (-41.47, -72.94), "Punta Arenas": (-53.16, -70.92),
           "Temuco": (-38.74, -72.60), "Valdivia": (-39.82, -73.25)},
    "CM": {"Yaoundé": (3.85, 11.50), "Douala": (4.05, 9.77)},
    "CN": {"Beijing": (39.90, 116.41), "Shanghai": (31.23, 121.47), "Guangzhou": (23.13, 113.26),
           "Shenzhen": (22.54, 114.06), "Wuhan": (30.59, 114.31), "Chengdu": (30.57, 104.07), "Xi'an": (34.34, 108.94),
           "Nanjing": (32.06, 118.80), "Hangzhou": (30.27, 120.16), "Tianjin": (39.34, 117.36),
           "Chongqing": (29.56, 106.55), "Dalian": (38.91, 121.61), "Qingdao": (36.07, 120.38),
           "Harbin": (45.80, 126.53), "Kunming": (25.04, 102.71), "Changsha": (28.23, 112.94),
           "Lanzhou": (36.06, 103.83), "Zhengzhou": (34.75, 113.63), "Xiamen": (24.48, 118.09),
           "Suzhou": (31.30, 120.59), "Shenyang": (41.81, 123.43), "Hefei": (31.82, 117.23), "Jinan": (36.65, 117.12)},
    "CO": {"Bogotá": (4.71, -74.07), "Medellín": (6.24, -75.58), "Cartagena": (10.39, -75.48), "Cali": (3.45, -76.53),
           "Barranquilla": (10.96, -74.80)},
    "CR": {"San José": (9.93, -84.08)},
    "CU": {"Havana": (23.11, -82.37)},
    "CY": {"Nicosia": (35.17, 33.36), "Limassol": (34.71, 33.02)},
    "CZ": {"Prague": (50.08, 14.44), "Praha": (50.08, 14.44), "Brno": (49.20, 16.61), "Ostrava": (49.82, 18.26)},
    "DE": {"Berlin": (52.52, 13.40), "Munich": (48.14, 11.58), "München": (48.14, 11.58), "Hamburg": (53.55, 9.99),
           "Frankfurt": (50.11, 8.68), "Frankfurt am Main": (50.11, 8.68), "Cologne": (50.94, 6.96), "Köln": (50.94, 6.96),
           "Stuttgart": (48.78, 9.18), "Dresden": (51.05, 13.74), "Aachen": (50.78, 6.08), "Karlsruhe": (49.01, 8.40),
           "Hanover": (52.37, 9.73), "Hannover": (52.37, 9.73), "Leipzig": (51.34, 12.37), "Bochum": (51.48, 7.22),
           "Düsseldorf": (51.23, 6.77), "Darmstadt": (49.87, 8.65), "Nuremberg": (49.45, 11.08), "Nürnberg": (49.45, 11.08),
           "Freiberg": (50.91, 13.34), "Weimar": (50.98, 11.33), "Bremen": (53.08, 8.80), "Essen": (51.46, 7.01),
           "Kassel": (51.31, 9.48), "Braunschweig": (52.27, 10.53)},
    "DK": {"Copenhagen": (55.68, 12.57), "Aarhus": (56.16, 10.20), "Aalborg": (57.05, 9.92), "Odense": (55.40, 10.39)},
    "DO": {"Santo Domingo": (18.49, -69.93), "Punta Cana": (18.58, -68.40)},
    "DZ": {"Algiers": (36.75, 3.06), "Oran": (35.70, -0.63)},
    "EC": {"Quito": (-0.18, -78.47), "Guayaquil": (-2.17, -79.92)},
    "EE": {"Tallinn": (59.44, 24.75), "Tartu": (58.38, 26.72)},
    "EG": {"Cairo": (30.04, 31.24), "Alexandria": (31.20, 29.92), "Sharm El Sheikh": (27.92, 34.33),
           "Hurghada": (27.26, 33.81), "Luxor": (25.69, 32.64), "Giza": (30.01, 31.21)},
    "ES": {"Madrid": (40.42, -3.70), "Barcelona": (41.39, 2.17), "Valencia": (39.47, -0.38), "Seville": (37.39, -5.98),
           "Sevilla": (37.39, -5.98), "Bilbao": (43.26, -2.93), "Málaga": (36.72, -4.42), "Granada": (37.18, -3.60),
           "Zaragoza": (41.65, -0.89), "Santander": (43.46, -3.81), "Palma": (39.57, 2.65), "Palma de Mallorca": (39.57, 2.65),
           "Las Palmas": (28.12, -15.43), "A Coruña": (43.36, -8.41), "Santiago de Compostela": (42.88, -8.54),
           "San Sebastián": (43.32, -1.98), "Alicante": (38.35, -0.48)},
    "ET": {"Addis Ababa": (9.03, 38.74)},
    "FI": {"Helsinki": (60.17, 24.94), "Espoo": (60.21, 24.66), "Tampere": (61.50, 23.76), "Oulu": (65.01, 25.47),
           "Turku": (60.45, 22.27)},
    "FR": {"Paris": (48.86, 2.35), "Lyon": (45.76, 4.84), "Marseille": (43.30, 5.37), "Nice": (43.70, 7.27),
           "Toulouse": (43.60, 1.44), "Grenoble": (45.19, 5.72), "Nantes": (47.22, -1.55), "Bordeaux": (44.84, -0.58),
           "Lille": (50.63, 3.06), "Strasbourg": (48.57, 7.75), "Montpellier": (43.61, 3.88), "Rennes": (48.11, -1.68),
           "Champs-sur-Marne": (48.85, 2.60), "Marne-la-Vallée": (48.85, 2.60)},
    "GB": {"London": (51.51, -0.13), "Leeds": (53.80, -1.55), "Southampton": (50.91, -1.40), "Manchester": (53.48, -2.24),
           "Birmingham": (52.49, -1.89), "Edinburgh": (55.95, -3.19), "Glasgow": (55.86, -4.25), "Cambridge": (52.21, 0.12),
           "Oxford": (51.75, -1.26), "Bristol": (51.45, -2.59), "Newcastle": (54.98, -1.61),
           "Newcastle upon Tyne": (54.98, -1.61), "Liverpool": (53.41, -2.99), "Cardiff": (51.48, -3.18),
           "Belfast": (54.60, -5.93), "Nottingham": (52.95, -1.15), "Sheffield": (53.38, -1.47), "Dundee": (56.46, -2.97),
           "Aberdeen": (57.15, -2.09), "Bath": (51.38, -2.36), "Durham": (54.78, -1.57), "Guildford": (51.24, -0.57),
           "Coventry": (52.41, -1.51), "Brighton": (50.82, -0.14), "Exeter": (50.72, -3.53)},
    "GE": {"Tbilisi": (41.72, 44.79), "Batumi": (41.64, 41.63)},
    "GH": {"Accra": (5.60, -0.19), "Kumasi": (6.69, -1.62)},
    "GR": {"Athens": (37.98, 23.73), "Thessaloniki": (40.64, 22.94), "Patras": (38.25, 21.73), "Heraklion": (35.34, 25.13),
           "Chania": (35.51, 24.02), "Rhodes": (36.43, 28.22)},
    "GT": {"Guatemala City": (14.63, -90.51)},
    "HK": {"Hong Kong": (22.32, 114.17)},
    "HN": {"Tegucigalpa": (14.07, -87.19)},
    "HR": {"Zagreb": (45.81, 15.98), "Split": (43.51, 16.44), "Dubrovnik": (42.65, 18.09), "Rijeka": (45.33, 14.44),
           "Opatija": (45.34, 14.31), "Zadar": (44.12, 15.23)},
    "HU": {"Budapest": (47.50, 19.04), "Debrecen": (47.53, 21.63), "Szeged": (46.25, 20.15)},
    "ID": {"Jakarta": (-6.21, 106.85), "Bandung": (-6.92, 107.62), "Yogyakarta": (-7.80, 110.37), "Surabaya": (-7.25, 112.75),
           "Bali": (-8.65, 115.22), "Denpasar": (-8.65, 115.22), "Nusa Dua": (-8.80, 115.23), "Medan": (3.59, 98.67)},
    "IE": {"Dublin": (53.35, -6.26), "Cork": (51.90, -8.47), "Galway": (53.27, -9.05), "Limerick": (52.66, -8.63)},
    "IL": {"Tel Aviv": (32.09, 34.78), "Haifa": (32.79, 34.99)},
    "IN": {"New Delhi": (28.61, 77.21), "Delhi": (28.70, 77.10), "Mumbai": (19.08, 72.88), "Chennai": (13.08, 80.27),
           "Bengaluru": (12.97, 77.59), "Bangalore": (12.97, 77.59), "Kolkata": (22.57, 88.36), "Hyderabad": (17.39, 78.49),
           "Pune": (18.52, 73.86), "Ahmedabad": (23.02, 72.57), "Kochi": (9.93, 76.27), "Guwahati": (26.14, 91.74),
           "Roorkee": (29.85, 77.89), "Kanpur": (26.45, 80.33), "Surat": (21.17, 72.83), "Jaipur": (26.91, 75.79),
           "Varanasi": (25.32, 82.97), "Bhubaneswar": (20.30, 85.82), "Chandigarh": (30.73, 76.78),
           "Visakhapatnam": (17.69, 83.22), "Coimbatore": (11.02, 76.96), "Goa": (15.49, 73.83), "Panaji": (15.49, 73.83),
           "Tiruchirappalli": (10.79, 78.70), "Mangaluru": (12.91, 74.86), "Mangalore": (12.91, 74.86),
           "Warangal": (17.97, 79.59), "Dehradun": (30.32, 78.03), "Nagpur": (21.15, 79.09), "Lucknow": (26.85, 80.95)},
    "IQ": {"Baghdad": (33.32, 44.37), "Erbil": (36.19, 44.01), "Basra": (30.51, 47.81)},
    "IR": {"Tehran": (35.69, 51.39), "Isfahan": (32.65, 51.67), "Shiraz": (29.59, 52.58), "Tabriz": (38.08, 46.29),
           "Mashhad": (36.30, 59.61)},
    "IS": {"Reykjavik": (64.15, -21.94), "Reykjavík": (64.15, -21.94)},
    "IT": {"Rome": (41.90, 12.50), "Roma": (41.90, 12.50), "Milan": (45.46, 9.19), "Milano": (45.46, 9.19),
           "Naples": (40.85, 14.27), "Napoli": (40.85, 14.27), "Turin": (45.07, 7.69), "Torino": (45.07, 7.69),
           "Florence": (43.77, 11.26), "Firenze": (43.77, 11.26), "Bologna": (44.49, 11.34), "Venice": (45.44, 12.32),
           "Venezia": (45.44, 12.32), "Genoa": (44.41, 8.93), "Genova": (44.41, 8.93), "Palermo": (38.12, 13.36),
           "Catania": (37.50, 15.09), "Padua": (45.41, 11.88), "Padova": (45.41, 11.88), "Bari": (41.12, 16.87),
           "Trento": (46.07, 11.12), "Pisa": (43.72, 10.40), "Perugia": (43.11, 12.39), "Cagliari": (39.22, 9.12),
           "Verona": (45.44, 10.99), "Messina": (38.19, 15.55), "Salerno": (40.68, 14.77), "Taormina": (37.85, 15.29)},
    "JM": {"Kingston": (17.97, -76.79)},
    "JO": {"Amman": (31.95, 35.93), "Aqaba": (29.53, 35.01)},
    "JP": {"Tokyo": (35.68, 139.69), "Kyoto": (35.01, 135.77), "Osaka": (34.69, 135.50), "Fukuoka": (33.59, 130.40),
           "Sapporo": (43.06, 141.35), "Yokohama": (35.44, 139.64), "Kobe": (34.69, 135.20), "Nagoya": (35.18, 136.91),
           "Sendai": (38.27, 140.87), "Hiroshima": (34.39, 132.46), "Niigata": (37.92, 139.04), "Okinawa": (26.21, 127.68),
           "Naha": (26.21, 127.68), "Kumamoto": (32.80, 130.71), "Nagasaki": (32.75, 129.88), "Tsukuba": (36.08, 140.11)},
    "KE": {"Nairobi": (-1.29, 36.82), "Mombasa": (-4.04, 39.67)},
    "KH": {"Phnom Penh": (11.56, 104.93), "Siem Reap": (13.36, 103.86)},
    "KR": {"Seoul": (37.57, 126.98), "Busan": (35.18, 129.08), "Daejeon": (36.35, 127.38), "Incheon": (37.46, 126.71),
           "Jeju": (33.50, 126.53), "Daegu": (35.87, 128.60), "Gwangju": (35.16, 126.85), "Gyeongju": (35.86, 129.22),
           "Suwon": (37.26, 127.03)},
    "KW": {"Kuwait City": (29.38, 47.98)},
    "KZ": {"Almaty": (43.24, 76.89), "Astana": (51.17, 71.45)},
    "LA": {"Vientiane": (17.97, 102.63)},
    "LB": {"Beirut": (33.89, 35.50)},
    "LK": {"Colombo": (6.93, 79.86), "Kandy": (7.29, 80.64)},
    "LT": {"Vilnius": (54.69, 25.28), "Kaunas": (54.90, 23.90)},
    "LU": {"Luxembourg": (49.61, 6.13)},
    "LV": {"Riga": (56.95, 24.11)},
    "LY": {"Tripoli": (32.89, 13.19)},
    "MA": {"Marrakech": (31.63, -7.99), "Marrakesh": (31.63, -7.99), "Rabat": (34.02, -6.84), "Casablanca": (33.57, -7.59),
           "Fez": (34.03, -5.00), "Tangier": (35.76, -5.83), "Agadir": (30.43, -9.60)},
    "ME": {"Podgorica": (42.44, 19.26), "Budva": (42.29, 18.84)},
    "MG": {"Antananarivo": (-18.88, 47.51)},
    "MK": {"Skopje": (42.00, 21.43), "Ohrid": (41.12, 20.80)},
    "MM": {"Yangon": (16.84, 96.17)},
    "MN": {"Ulaanbaatar": (47.89, 106.91)},
    "MX": {"Mexico City": (19.43, -99.13), "Ciudad de México": (19.43, -99.13), "Guadalajara": (20.67, -103.35),
           "Monterrey": (25.69, -100.32), "Cancún": (21.16, -86.85), "Puebla": (19.04, -98.21), "Querétaro": (20.59, -100.39),
           "Mérida": (20.97, -89.62), "Oaxaca": (17.07, -96.73), "Acapulco": (16.85, -99.82), "Puerto Vallarta": (20.65, -105.23),
           "Tijuana": (32.51, -117.04), "León": (21.12, -101.68)},
    "MY": {"Kuala Lumpur": (3.14, 101.69), "Penang": (5.41, 100.33), "George Town": (5.41, 100.33),
           "Kota Kinabalu": (5.98, 116.07), "Kuching": (1.55, 110.36), "Johor Bahru": (1.49, 103.74), "Putrajaya": (2.93, 101.69)},
    "MZ": {"Maputo": (-25.97, 32.57)},
    "NA": {"Windhoek": (-22.56, 17.08)},
    "NG": {"Lagos": (6.52, 3.38), "Abuja": (9.08, 7.40)},
    "NI": {"Managua": (12.11, -86.24)},
    "NL": {"Amsterdam": (52.37, 4.90), "Rotterdam": (51.92, 4.48), "Delft": (52.01, 4.36), "The Hague": (52.07, 4.30),
           "Den Haag": (52.07, 4.30), "Utrecht": (52.09, 5.12), "Eindhoven": (51.44, 5.48), "Papendrecht": (51.83, 4.69),
           "Groningen": (53.22, 6.57), "Maastricht": (50.85, 5.69), "Enschede": (52.22, 6.89), "Gouda": (52.01, 4.71)},
    "NO": {"Oslo": (59.91, 10.75), "Trondheim": (63.43, 10.40), "Bergen": (60.39, 5.32), "Stavanger": (58.97, 5.73),
           "Tromsø": (69.65, 18.96)},
    "NP": {"Kathmandu": (27.72, 85.32), "Pokhara": (28.21, 83.99), "Lalitpur": (27.67, 85.32)},
    "NZ": {"Auckland": (-36.85, 174.76), "Wellington": (-41.29, 174.78), "Christchurch": (-43.53, 172.64),
           "Queenstown": (-45.03, 168.66), "Dunedin": (-45.88, 170.50), "Napier": (-39.49, 176.91), "Rotorua": (-38.14, 176.25),
           "Hamilton": (-37.79, 175.28)},
    "OM": {"Muscat": (23.59, 58.41)},
    "PA": {"Panama City": (8.98, -79.52)},
    "PE": {"Lima": (-12.05, -77.04), "Cusco": (-13.53, -71.97), "Arequipa": (-16.41, -71.54), "Trujillo": (-8.11, -79.03)},
    "PH": {"Manila": (14.60, 120.98), "Quezon City": (14.68, 121.04), "Makati": (14.55, 121.02), "Cebu": (10.32, 123.89),
           "Cebu City": (10.32, 123.89), "Davao": (7.19, 125.46)},
    "PK": {"Islamabad": (33.68, 73.05), "Lahore": (31.52, 74.36), "Karachi": (24.86, 67.01), "Peshawar": (34.01, 71.58)},
    "PL": {"Warsaw": (52.23, 21.01), "Warszawa": (52.23, 21.01), "Kraków": (50.06, 19.94), "Cracow": (50.06, 19.94),
           "Gdańsk": (54.35, 18.65), "Wrocław": (51.11, 17.03), "Poznań": (52.41, 16.93), "Łódź": (51.76, 19.46),
           "Gliwice": (50.29, 18.67), "Lublin": (51.25, 22.57)},
    "PR": {"San Juan": (18.47, -66.11)},
    "PT": {"Lisbon": (38.72, -9.14), "Lisboa": (38.72, -9.14), "Porto": (41.15, -8.61), "Coimbra": (40.21, -8.43),
           "Funchal": (32.65, -16.91), "Faro": (37.02, -7.93), "Braga": (41.55, -8.42)},
    "PY": {"Asunción": (-25.26, -57.58)},
    "QA": {"Doha": (25.29, 51.53)},
    "RO": {"Bucharest": (44.43, 26.10), "Cluj-Napoca": (46.77, 23.60), "Iași": (47.16, 27.59), "Timișoara": (45.75, 21.23),
           "Constanța": (44.18, 28.63)},
    "RS": {"Belgrade": (44.79, 20.45), "Novi Sad": (45.27, 19.83), "Niš": (43.32, 21.90)},
    "RU": {"Moscow": (55.76, 37.62), "Saint Petersburg": (59.94, 30.31), "St Petersburg": (59.94, 30.31),
           "Novosibirsk": (55.01, 82.93), "Kazan": (55.79, 49.12), "Yekaterinburg": (56.84, 60.61), "Perm": (58.01, 56.25),
           "Vladivostok": (43.12, 131.89), "Sochi": (43.60, 39.73), "Tomsk": (56.48, 84.95)},
    "RW": {"Kigali": (-1.95, 30.06)},
    "SA": {"Riyadh": (24.71, 46.68), "Jeddah": (21.49, 39.19), "Dammam": (26.39, 50.10), "Dhahran": (26.29, 50.11),
           "Mecca": (21.39, 39.86), "Medina": (24.47, 39.61)},
    "SE": {"Stockholm": (59.33, 18.07), "Gothenburg": (57.71, 11.97), "Göteborg": (57.71, 11.97), "Malmö": (55.60, 13.00),
           "Lund": (55.70, 13.19), "Uppsala": (59.86, 17.64), "Luleå": (65.58, 22.15), "Linköping": (58.41, 15.62)},
    "SG": {"Singapore": (1.29, 103.85)},
    "SI": {"Ljubljana": (46.06, 14.51), "Bled": (46.37, 14.11), "Maribor": (46.55, 15.65), "Portorož": (45.51, 13.59)},
    "SK": {"Bratislava": (48.15, 17.11), "Košice": (48.72, 21.26), "Žilina": (49.22, 18.74)},
    "SN": {"Dakar": (14.72, -17.47)},
    "SV": {"San Salvador": (13.69, -89.22)},
    "TH": {"Bangkok": (13.76, 100.50), "Chiang Mai": (18.79, 98.98), "Pattaya": (12.93, 100.88), "Phuket": (7.88, 98.39),
           "Khon Kaen": (16.43, 102.84), "Nakhon Ratchasima": (14.97, 102.10), "Hat Yai": (7.01, 100.47)},
    "TN": {"Tunis": (36.81, 10.18), "Hammamet": (36.40, 10.62), "Sousse": (35.83, 10.64), "Sfax": (34.74, 10.76)},
    "TR": {"Istanbul": (41.01, 28.98), "Ankara": (39.93, 32.86), "Izmir": (38.42, 27.14), "Antalya": (36.90, 30.70),
           "Bursa": (40.19, 29.06), "Trabzon": (41.00, 39.72), "Eskişehir": (39.78, 30.52), "Konya": (37.87, 32.48),
           "Adana": (37.00, 35.32), "Gaziantep": (37.07, 37.38), "Kayseri": (38.73, 35.48)},
    "TT": {"Port of Spain": (10.66, -61.51)},
    "TW": {"Taipei": (25.03, 121.57), "Tainan": (23.00, 120.23), "Kaohsiung": (22.63, 120.30), "Taichung": (24.15, 120.67),
           "Hsinchu": (24.81, 120.97)},
    "TZ": {"Dar es Salaam": (-6.79, 39.21), "Arusha": (-3.39, 36.68), "Dodoma": (-6.16, 35.75)},
    "UA": {"Kyiv": (50.45, 30.52), "Kiev": (50.45, 30.52), "Lviv": (49.84, 24.03), "Odesa": (46.48, 30.72), "Kharkiv": (49.99, 36.23)},
    "UG": {"Kampala": (0.35, 32.58)},
    "US": {"New York": (40.71, -74.01), "New York City": (40.71, -74.01), "Washington": (38.91, -77.04),
           "Washington DC": (38.91, -77.04), "Washington D.C.": (38.91, -77.04), "Philadelphia": (39.95, -75.17),
           "Orlando": (28.54, -81.38), "Chicago": (41.88, -87.63), "Boston": (42.36, -71.06), "San Francisco": (37.77, -122.42),
           "Los Angeles": (34.05, -118.24), "San Diego": (32.72, -117.16), "Seattle": (47.61, -122.33), "Denver": (39.74, -104.99),
           "Dallas": (32.78, -96.80), "Fort Worth": (32.76, -97.33), "Houston": (29.76, -95.37), "Austin": (30.27, -97.74),
           "Atlanta": (33.75, -84.39), "Miami": (25.76, -80.19), "Las Vegas": (36.17, -115.14), "Phoenix": (33.45, -112.07),
           "Nashville": (36.16, -86.78), "New Orleans": (29.95, -90.07), "Minneapolis": (44.98, -93.27),
           "Pittsburgh": (40.44, -80.00), "St. Louis": (38.63, -90.20), "Saint Louis": (38.63, -90.20),
           "Kansas City": (39.10, -94.58), "Charlotte": (35.23, -80.84), "Baltimore": (39.29, -76.61),
           "Salt Lake City": (40.76, -111.89), "Portland": (45.52, -122.68), "Sacramento": (38.58, -121.49),
           "Honolulu": (21.31, -157.86), "Anchorage": (61.22, -149.90), "Indianapolis": (39.77, -86.16),
           "Columbus": (39.96, -83.00), "Detroit": (42.33, -83.05), "Cincinnati": (39.10, -84.51), "Raleigh": (35.78, -78.64),
           "Tampa": (27.95, -82.46), "San Antonio": (29.42, -98.49), "Albuquerque": (35.08, -106.65), "Reno": (39.53, -119.81),
           "Oakland": (37.80, -122.27), "Berkeley": (37.87, -122.27), "Long Beach": (33.77, -118.19),
           "National Harbor": (38.78, -77.02), "Arlington": (38.88, -77.10), "Charleston": (32.78, -79.93),
           "Savannah": (32.08, -81.09), "Louisville": (38.25, -85.76), "Memphis": (35.15, -90.05), "Boise": (43.62, -116.20),
           "Spokane": (47.66, -117.43), "Madison": (43.07, -89.40), "Milwaukee": (43.04, -87.91), "Cleveland": (41.50, -81.69),
           "Buffalo": (42.89, -78.88), "Omaha": (41.26, -95.93), "Oklahoma City": (35.47, -97.52), "Tucson": (32.22, -110.97),
           "San Jose": (37.34, -121.89), "Hartford": (41.76, -72.69), "Providence": (41.82, -71.41), "Richmond": (37.54, -77.44),
           "Norfolk": (36.85, -76.29), "Jacksonville": (30.33, -81.66), "Fort Lauderdale": (26.12, -80.14)},
    "UY": {"Montevideo": (-34.90, -56.16), "Punta del Este": (-34.96, -54.95)},
    "UZ": {"Tashkent": (41.30, 69.24)},
    "VE": {"Caracas": (10.48, -66.90)},
    "VN": {"Hanoi": (21.03, 105.85), "Ha Noi": (21.03, 105.85), "Ho Chi Minh City": (10.82, 106.63),
           "Saigon": (10.82, 106.63), "Da Nang": (16.05, 108.20), "Hue": (16.46, 107.59), "Hai Phong": (20.84, 106.69)},
    "ZA": {"Johannesburg": (-26.20, 28.05), "Cape Town": (-33.92, 18.42), "Durban": (-29.86, 31.02), "Pretoria": (-25.75, 28.19),
           "Stellenbosch": (-33.93, 18.86), "Sun City": (-25.34, 27.09), "Gqeberha": (-33.96, 25.60),
           "Port Elizabeth": (-33.96, 25.60)},
    "ZM": {"Lusaka": (-15.39, 28.32)},
    "ZW": {"Harare": (-17.83, 31.05), "Victoria Falls": (-17.93, 25.84)},
    # overseas territories (geomap.ALIASES)
    "BQ": {"Kralendijk": (12.15, -68.27)},
    "CC": {"West Island": (-12.19, 96.83)},
    "CX": {"Flying Fish Cove": (-10.42, 105.68)},
    "GF": {"Cayenne": (4.93, -52.33), "Kourou": (5.16, -52.65)},
    "GI": {"Gibraltar": (36.14, -5.35)},
    "GP": {"Pointe-à-Pitre": (16.24, -61.53), "Basse-Terre": (15.99, -61.73)},
    "MQ": {"Fort-de-France": (14.60, -61.07)},
    "RE": {"Saint-Denis": (-20.88, 55.45), "Saint-Pierre": (-21.34, 55.48)},
    "SJ": {"Longyearbyen": (78.22, 15.65)},
    "TK": {"Fakaofo": (-9.38, -171.22)},
    "YT": {"Mamoudzou": (-12.78, 45.23)},
}


def place_key(text):
    """A place name for matching: no accents, case or punctuation ("Zürich" is "zurich", "St. Louis" "st louis")."""
    text = unicodedata.normalize("NFKD", str(text or "").translate(PLAIN_LETTERS))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


PLAIN_LETTERS = str.maketrans({"ł": "l", "Ł": "L", "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ß": "ss", "æ": "ae", "ı": "i"})
_city_keys = {}


def known_cities(code):
    """CITY_POINTS of a country code, for matching: {place_key(name): (the name listed first at that point, point)}."""
    if not _city_keys:
        for cc, cities in CITY_POINTS.items():
            first = {}
            for name, point in cities.items():
                first.setdefault(point, name)
            _city_keys[cc] = {place_key(name): (first[point], point) for name, point in cities.items()}
    return _city_keys.get(str(code or "").strip().upper(), {})


def city_point(city, code):
    """(name, (latitude, longitude)) of an event's city from CITY_POINTS, or None; the name is the one listed first
    at that point, so 'Wien' and 'Vienna' are both 'Vienna'. 'Lyon', 'lyon', 'Lyon, France' and 'Lyon (hybrid)' all
    find Lyon."""
    known = known_cities(code)
    text = str(city or "")
    for candidate in (text, text.split(",")[0], re.sub(r"\(.*?\)", " ", text), re.sub(r"\(.*?\)", " ", text).split(",")[0]):
        point = known.get(place_key(candidate))
        if point:
            return point
    return None


def map_data(events, cfg):
    """What the Events page's map shows, for events.js (the filters) and eventmap.js (the map): the places (a city
    from CITY_POINTS, or the middle of the country for a city not listed or not given) with their position on
    the world map, and per event its place, label, dates and whether it is an ISSMGE event. Events held only online,
    or whose place is not given yet, have no place (-1); they are counted beside the map. None when the world map's
    geometry cannot be read."""
    try:
        import geomap
        if not geomap.world().get("countries"):
            return None
    except Exception as ex:  # the map is left out, never the page
        print(f"Events map left out: the world map could not be loaded ({type(ex).__name__}: {ex}).")
        return None
    places, index, rows = [], {}, []
    for e in events:
        code = geomap.canonical(e["country"])  # the country the map draws it in (Réunion, RE, with France)
        own = geomap.code_of(e["country"])     # the event's own code, RE for Réunion
        pos, exact, city = None, False, ""
        if code:
            found = city_point(e["city"], own) if e["city"] else None
            if found:
                city, point = found
                pos, exact = geomap.project(point[1], point[0]), True
            elif own != code:  # an overseas territory: its first city stands for it; none listed, not on the map
                first = next(iter(known_cities(own).values()), None)
                pos = geomap.project(first[1][1], first[1][0]) if first else None
            else:
                pos = geomap.label_point(code)
        p = -1
        if pos:
            key = (own, city if exact else "")  # one place per city, whichever of its names the events use
            if key not in index:
                index[key] = len(places)
                name = country_name(own)
                places.append({"x": round(pos[0], 1), "y": round(pos[1], 1), "cc": code, "e": 1 if exact else 0,
                               "n": f"{city}, {name}" if exact else name})
            p = index[key]
        rows.append({"i": e["id"], "n": label_of(e), "t": full_name(e), "d": date_range(e["start"], e["end"]),
                     "c": e["city"], "cc": code or e["country"], "k": KIND_CLASS.get(e["kind"], "k-other"),
                     "s": 1 if e["issmge"] else 0, "o": 1 if e["online"] else 0, "p": p})
    codes = sorted({pl["cc"] for pl in places} | {r["cc"] for r in rows if r["cc"]})
    return {"places": places, "events": rows,
            "names": {c: country_name(c) for c in codes},
            "regions": {c: geomap.issmge_region(c, cfg) for c in codes}}


def map_rows(data, ids=None):
    """The table view: per country (most events first) its events, then the events not on the map. ids: the events
    shown (all when None)."""
    shown = [r for r in data["events"] if ids is None or r["i"] in ids]
    by_country = {}
    for r in shown:
        if r["p"] >= 0:
            by_country.setdefault(data["places"][r["p"]]["cc"], []).append(r)
    out = sorted(((data["names"].get(cc, cc), cc, rs) for cc, rs in by_country.items()), key=lambda x: (-len(x[2]), x[0]))
    online = [r for r in shown if r["p"] < 0 and r["o"]]
    unknown = [r for r in shown if r["p"] < 0 and not r["o"]]
    return out, online, unknown


def map_event_links(rs):
    return "".join(f"<li><a href='#ev-{esc(r['i'])}'>{esc(r['n'])}</a><span>{esc(' · '.join(x for x in (r['c'], r['d']) if x))}"
                   f"{' · ISSMGE' if r['s'] else ''}</span></li>" for r in rs)


def map_table(data):
    countries, online, unknown = map_rows(data)
    body = []
    for name, cc, rs in countries:
        body.append(f"<tr><th scope='row'>{esc(name)}</th><td>{esc(data['regions'].get(cc) or '–')}</td>"
                    f"<td class='num'>{len(rs)}</td><td class='num'>{sum(r['s'] for r in rs)}</td>"
                    f"<td><ul class='evm-tl'>{map_event_links(rs)}</ul></td></tr>")
    if not body:
        body.append("<tr><td colspan='5' class='viz-empty'>No upcoming event has a place yet.</td></tr>")
    off = [(label, rs) for label, rs in (("Online only", online), ("Place not given yet", unknown)) if rs]
    foot = "".join(f"<tr class='evm-off-row'><th scope='row'>{label}</th><td>Not on the map</td><td class='num'>{len(rs)}</td>"
                   f"<td class='num'>{sum(r['s'] for r in rs)}</td><td><ul class='evm-tl'>{map_event_links(rs)}</ul></td></tr>"
                   for label, rs in off)
    return ("<div class='table-wrap'><table class='overview viz-tbl map-tbl evm-tbl'><thead><tr><th scope='col'>Country</th>"
            "<th scope='col'>ISSMGE region</th><th scope='col' class='num'>Events</th><th scope='col' class='num'>ISSMGE "
            "events</th><th scope='col'>The events (select one to go to it in the list)</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody>" + (f"<tbody class='evm-off-body'>{foot}</tbody>" if foot else "")
            + "</table></div>")


def map_summary(data):
    """'39 events in 31 places in 22 countries. Not on the map: 1 online only, 5 with no place given yet.'"""
    countries, online, unknown = map_rows(data)
    on_map = sum(len(rs) for _, _, rs in countries)
    places = len({r["p"] for _, _, rs in countries for r in rs})
    text = (f"{site_builder.count(on_map, 'event')} in {site_builder.count(places, 'place')} in "
            f"{site_builder.count(len(countries), 'country', 'countries')}.")
    off = [x for x in (f"{len(online)} online only" if online else "",
                       f"{len(unknown)} with no place given yet" if unknown else "") if x]
    return text + (f" Not on the map: {', '.join(off)}." if off else "")


def map_section(events, cfg):
    """The map above the list of upcoming events: where they take place (a circle per city, gold where an ISSMGE
    event is), what is there on a tap, and a table of the countries with their events. eventmap.js draws it; the
    filters above it (events.js) apply to the map as to the list. "" when the map cannot be made."""
    data = map_data(events, cfg)
    if not data or not events:
        return ""
    regions = ["", "Africa", "Asia", "Australasia", "Europe", "North America", "South America"]
    zoom = "".join(f"<button type='button' aria-pressed='{'true' if not r else 'false'}' data-zoom='{esc(r)}'>{esc(r or 'World')}</button>"
                   for r in regions)
    zoom_opts = "".join(f"<option value='{esc(r)}'>{esc(r or 'World')}</option>" for r in regions)
    legend = ("<ul class='viz-legend evm-key'><li><i class='ek-issmge'></i>With an ISSMGE event</li>"
              "<li><i class='ek-other'></i>Other events only</li><li><i class='ek-host'></i>Country with events</li>"
              "<li class='ek-note'>The number is how many events; nearby places share a circle until you zoom in.</li></ul>")
    return (
        "<figure class='viz map-fig evm-fig' id='evm-fig'><div class='viz-head'><div><h3>Where the events take place</h3>"
        f"<p id='evm-sub'>{esc(map_summary(data))}</p></div>"
        "<div class='viz-toggle' role='group' aria-label='View'><button type='button' aria-pressed='true' data-view='chart'>Map</button>"
        "<button type='button' aria-pressed='false' data-view='table'>Table</button></div></div>"
        "<div class='viz-chart evm-chart'>"
        f"<div class='map-zoom evm-zoom' role='group' aria-label='Zoom to a region'>{zoom}</div>"
        f"<label class='field map-zoom-sel'><span>Zoom to</span><select id='evm-zoom-sel'>{zoom_opts}</select></label>"
        "<div class='map-grid'><div class='map-main'>"
        "<div class='map-canvas evm-canvas' id='evm-canvas' tabindex='0' role='application' aria-roledescription='map' "
        "aria-label='Map of the upcoming events. Arrow keys move between the places, Enter lists the events there, "
        "Escape closes. The Table button lists every country and event.'><p class='map-loading'>Loading the map…</p></div>"
        f"<div class='map-legend'>{legend}</div><p class='map-sr' id='evm-live' aria-live='polite'></p></div>"
        "<aside class='map-panel evm-panel' id='evm-panel' aria-label='Events by place'></aside></div></div>"
        f"<div class='viz-table' id='evm-table' hidden>{map_table(data)}</div>"
        f"<figcaption class='map-credit'>{esc(geomap_credit())} Each circle is the event's city; an event whose city is "
        "not on the map's list of cities, or not given, is shown in the middle of its country. Events held only online "
        "and those whose place is not given yet are counted above the map, not drawn on it.</figcaption></figure>"
        f"<script type='application/json' id='evm-data'>{script_json(data)}</script>")


def script_json(data):
    """JSON safe inside <script>: no "<" survives, so an event's name cannot close the element."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def geomap_credit():
    try:
        import geomap
        return geomap.CREDIT
    except Exception:
        return ""


# ------------------------------------------------------------------ the page
def kind_badge(kind):
    return f"<span class='ev-kind {KIND_CLASS.get(kind, 'k-other')}'>{esc(kind)}</span>"


def deadline_items(e, today):
    out = []
    for d in e["deadlines"]:
        n = left_of(d["date"], today)
        state = "passed" if n < 0 else "urgent" if n <= 14 else "soon" if n <= 30 else "open"
        when = f"by end of {nice(d['date'])}" if month_only(d["date"]) else nice(d["date"])
        out.append(f"<li class='ev-dl {state}'><span class='ev-dl-l'>{esc(d['label'])}</span>"
                   f"<time datetime='{d['date']}'>{esc(when)}</time>{left_html(d['date'], today)}</li>")
    return f"<ul class='ev-dls'>{''.join(out)}</ul>" if out else ""


def tile(e):
    """The card's date tile: day range over month and year."""
    s, en = e["start"], e["end"]
    if month_only(s) or month_only(en):
        return (f"<div class='ev-date tbc'><b>{site_builder.MONTHS[int(s[5:7]) - 1]}</b>"
                f"<span>{s[:4]}</span><small>dates TBC</small></div>")
    a, b = dt.date.fromisoformat(s), dt.date.fromisoformat(en)
    if (a.year, a.month) == (b.year, b.month):
        return f"<div class='ev-date'><b>{a.day if a == b else f'{a.day}–{b.day}'}</b><span>{a:%b %Y}</span></div>"
    return f"<div class='ev-date'><b>{a.day} {a:%b}</b><span>– {b.day} {b:%b %Y}</span></div>"  # across a month end


def event_card(e, cfg, today, found_on="", past=False):
    region = region_of(e, cfg)
    where = place(e)
    search = " ".join([e["name"], e["short"], e["city"], country_name(e["country"]), e["organiser"], e["kind"],
                       e["notes"], region]).lower()
    started = first_day(e["start"]) <= today and not past
    top = [kind_badge(e["kind"])]
    if e["online"]:
        top.append("<span class='ev-flag'>Online</span>")
    if started:
        top.append("<span class='ev-flag live'>Under way</span>")
    if e["short"] and e["short"] not in e["name"]:
        top.append(f"<span class='ev-short'>{esc(e['short'])}</span>")
    meta = [f"<span>{icon('calendar')}{esc(date_range(e['start'], e['end']))}</span>"]
    if where:
        meta.append(f"<span>{icon('pin')}{esc(where)}</span>")
    if e["organiser"]:
        meta.append(f"<span class='ev-org'>{esc(e['organiser'])}</span>")
    if e["source"] == "editors":
        src = "Listed by the editors"
    else:
        src = ("Found by the weekly refresh" + (f" on {esc(nice(e['found']))}" if e["found"] else "")
               + " · check the dates on the event's website")
    actions = []
    if e["url"] != "#":
        actions.append(f"<a class='btn' href='{esc(e['url'])}' target='_blank' rel='noopener'>{icon('external')}Event website</a>")
    if not past and not month_only(e["start"]) and not month_only(e["end"]):
        actions.append(f"<a class='btn ghost' href='calendar/{esc(e['id'])}.ics' download='{esc(e['id'])}.ics' "
                       f"title='Download this event{' and its deadlines' if e['deadlines'] else ''} for Outlook, "
                       f"Google or Apple Calendar'>{icon('plus')}Add to calendar</a>")
    title = (f"<a href='{esc(e['url'])}' target='_blank' rel='noopener' dir='auto'>{esc(e['name'])}</a>"
             if e["url"] != "#" else f"<span dir='auto'>{esc(e['name'])}</span>")
    return (f"<article class='ev-card {KIND_CLASS.get(e['kind'], 'k-other')}{' past' if past else ''}' id='ev-{esc(e['id'])}' "
            f"data-kind='{esc(e['kind'])}' data-issmge='{'1' if e['issmge'] else ''}' data-region='{esc(region)}' "
            f"data-text='{esc(search)}'>{tile(e)}<div class='ev-main'>"
            f"<div class='ev-top'>{''.join(top)}</div><h3 class='ev-title'>{title}</h3>"
            f"<p class='ev-meta'>{''.join(meta)}</p>{deadline_items(e, today)}"
            + (f"<p class='ev-notes'>{esc(e['notes'])}</p>" if e["notes"] else "")
            + f"<div class='ev-foot'>{''.join(actions)}<span class='ev-src'>{src}</span></div></div></article>")


def calls_panel(calls, today, days):
    if not calls:
        return (f"<section class='ev-calls none' id='calls'><h2 class='section-h'>Open deadlines</h2>"
                f"<p class='empty'>No deadlines in the next {days} days. Later deadlines are shown "
                "on each event below.</p></section>")
    rows = []
    for c in calls:
        e, n = c["event"], left_of(c["date"], today)
        state = "urgent" if n <= 14 else "soon" if n <= 30 else "open"
        sub = " · ".join(x for x in (e["name"] if e["short"] else "", place(e), date_range(e["start"], e["end"])) if x)
        rows.append(f"<li class='{state}'><a href='#ev-{esc(e['id'])}'><span class='ev-cd'>{date_tile(c['date'])}</span>"
                    f"<span class='ev-ct'><b>{esc(c['label'])}</b> · {esc(label_of(e))}<small dir='auto'>{esc(sub)}</small></span>"
                    f"{left_html(c['date'], today)}</a></li>")
    return (f"<section class='ev-calls' id='calls'><h2 class='section-h'>Open deadlines "
            f"<span class='h1-sub'>in the next {days} days</span></h2>"
            "<p class='hint'>Calls for abstracts and papers, registration and other deadlines, soonest first. Check "
            f"each date on the event's website before announcing it.</p><ol class='ev-calls-list'>{''.join(rows)}</ol></section>")


def filters(events, cfg):
    kinds = [k for k in KINDS if any(e["kind"] == k for e in events)]
    regions = sorted({region_of(e, cfg) for e in events} - {""}, key=lambda r: (r == "Online", r))
    kopts = "".join(f"<option>{esc(k)}</option>" for k in kinds)
    region = ("<label class='field'><span>Region</span><select class='ev-f-region'><option value=''>All regions</option>"
              + "".join(f"<option>{esc(r)}</option>" for r in regions) + "</select></label>") if len(regions) > 1 else ""
    return (f"<div class='toolbar ev-tools' id='ev-filters' role='search' hidden>"
            "<label class='field grow'><span>Filter</span><input type='search' class='ev-f-text' "
            "placeholder='Name, city, organiser…'></label>"
            f"<label class='field'><span>Kind</span><select class='ev-f-kind'><option value=''>All kinds</option>{kopts}</select></label>"
            f"{region}<label class='ev-check'><input type='checkbox' class='ev-f-issmge'> ISSMGE only</label>"
            "<span class='f-count ev-count' aria-live='polite'></span></div>")


def month_groups(events, cfg, today):
    sm = site_builder.start_month(cfg)
    groups = {}
    for e in events:
        groups.setdefault(e["start"][:7], []).append(e)
    out = []
    for key, items in groups.items():
        y, m = int(key[:4]), int(key[5:7])
        quarter = site_builder.issue_window(f"{key}-01", sm)["label"]
        out.append(f"<section class='ev-month' id='m-{key}'><h3 class='ev-month-h'>{dt.date(y, m, 1):%B %Y}"
                   f"<span class='count'>{len(items)}</span><span class='ev-q' title='The magazine issue window this month "
                   f"falls in'>{esc(quarter)} issue</span></h3>"
                   + "".join(event_card(e, cfg, today) for e in items) + "</section>")
    return "".join(out)


def page_body(cfg, events, found, today, problems, opts):
    root = ""
    horizon = add_months(today, opts["months_ahead"])
    coming = [e for e in events if not is_past(e, today) and first_day(e["start"]) <= horizon]
    later = [e for e in events if not is_past(e, today) and first_day(e["start"]) > horizon]
    past = sorted((e for e in events if is_past(e, today)), key=lambda e: first_day(e["start"]), reverse=True)
    calls = open_deadlines(events, today, opts["deadline_days"])
    repo = site_builder.repository(cfg)
    feed = (site_builder.site_url(cfg) or "") + "events.ics"
    if found["updated"]:
        refreshed = f"Refreshed {esc(nice(found['updated'][:10]))}"
        state = (f"Claude last read the organisers' calendars on {esc(nice(found['updated'][:10]))}; the daily scan "
                 f"refreshes them every {site_builder.count(opts['refresh_days'], 'day')}.")
    else:
        refreshed = "Editors' list"
        state = ("The weekly refresh has not run yet, so the calendar shows the editors' list. Press "
                 "<b>Refresh calendar</b> to have Claude read the organisers' calendars now.")
    if found["failed"]:
        state += (f" The refresh of {esc(nice(found['attempted'][:10]))} did not complete: {esc(found['failed'])} "
                  + (f"The daily scan tries again on {esc(nice(found['retry']))}." if found["retry"] else ""))
    nxt = next((e for e in coming if first_day(e["start"]) > today), None)
    stats = (site_builder.stat(len(coming), f"events in the next {opts['months_ahead']} months")
             + site_builder.stat(sum(1 for e in coming if e["issmge"]), "ISSMGE events")
             + site_builder.stat(len(calls), f"open deadlines ({opts['deadline_days']} days)")
             + site_builder.stat(site_builder.count((first_day(nxt["start"]) - today).days, "day") if nxt else "–",
                                 "to the next event"))
    actions = (f"<div class='actions'><a class='btn primary' href='#subscribe'>{icon('rss')}Subscribe to the calendar</a>"
               f"<button type='button' class='btn light events-btn' id='events-btn' title='"
               + esc("Have Claude read the organisers' calendars again (opens GitHub)")
               + f"'>{site_builder.icon('scan')}<span>Refresh calendar</span></button>"
               + (f"<a class='btn light' href='https://github.com/{esc(repo)}/edit/main/data/events.yaml' target='_blank' "
                  f"rel='noopener'>{icon('edit')}Edit the editors' list</a>" if repo else "") + "</div>")
    body = [site_builder.hero(f"Events calendar · {refreshed}", "Events &amp; calls for papers",
                              "Conferences, symposia and courses for geotechnical engineers, with their abstract and paper "
                              "deadlines. The editors keep a list; each week Claude reads the organisers' calendars and adds "
                              "what it finds. Check every date on the event's own website before publishing it.",
                              stats, actions)]
    if problems:
        body.append("<div class='ev-warn' role='note'>" + icon("alert")
                    + f"<div><b>Some of data/events.yaml could not be used.</b> Fix these lines"
                    + (f" in <a href='https://github.com/{esc(repo)}/edit/main/data/events.yaml' target='_blank' "
                       "rel='noopener'>the editors' list</a>" if repo else " in data/events.yaml")
                    + ":<ul>" + "".join(f"<li>{esc(p)}</li>" for p in problems) + "</ul></div></div>")
    body.append(calls_panel(calls, today, opts["deadline_days"]))
    body.append("<div id='ev-app'><h2 class='section-h'>Upcoming events "
                f"<span class='h1-sub'>{site_builder.count(len(coming), 'event')}</span></h2>"
                f"<p class='hint'>{state} Grouped by the month they start, with the magazine's issue window.</p>")
    if coming:
        body.append(filters(coming, cfg))
        body.append(map_section(coming, cfg))  # the map of the same events, above the list; the filters apply to both
        body.append(f"<div class='ev-list'>{month_groups(coming, cfg, today)}</div>"
                    "<p class='empty ev-none' hidden>No events match these filters.</p>")
    else:
        body.append("<p class='empty'>No upcoming events in the calendar yet. Add them to the editors' list or press "
                    "<b>Refresh calendar</b>.</p>")
    body.append("</div>")
    if later:
        body.append(f"<details class='ev-fold'><summary>Further ahead ({len(later)})</summary>"
                    f"<div class='ev-fold-body'>{''.join(event_card(e, cfg, today) for e in later)}</div></details>")
    if past:
        body.append(f"<details class='ev-fold'><summary>Past events ({len(past)})</summary>"
                    f"<div class='ev-fold-body'>{''.join(event_card(e, cfg, today, past=True) for e in past)}</div></details>")
    webcal = re.sub(r"^https?://", "webcal://", feed) if feed.startswith("http") else ""
    google = f"https://calendar.google.com/calendar/r?cid={quote(webcal, safe='')}" if webcal else ""
    body.append(
        "<section class='ev-use' id='subscribe'><h2 class='section-h'>Use the calendar</h2><div class='ev-use-grid'>"
        f"<div class='ev-use-card'><h3>{icon('rss')}Subscribe</h3><p>Add every event and deadline to Outlook, Google or "
        "Apple Calendar. A subscription updates itself as the calendar changes.</p>"
        f"<div class='ev-feed'><input type='text' readonly value='{esc(feed)}' id='ev-feed' aria-label='Calendar feed address'>"
        f"<button type='button' class='btn' id='ev-copy'>{icon('copy')}<span>Copy</span></button></div>"
        "<p class='ev-how'><b>Outlook:</b> Add calendar → Subscribe from web, paste the address. <b>Google Calendar:</b> "
        "Other calendars → + → From URL.</p><div class='actions'>"
        + (f"<a class='btn' href='{esc(webcal)}' id='ev-webcal'>{icon('calendar')}Open in calendar app</a>" if webcal else "")
        + (f"<a class='btn' href='{esc(google)}' id='ev-google' target='_blank' rel='noopener'>{icon('plus')}Google Calendar</a>"
           if google else "")
        + f"<a class='btn ghost' href='events.ics' download>{icon('download')}events.ics</a></div></div>"
        f"<div class='ev-use-card'><h3>{icon('plus')}One event</h3><p><b>Add to calendar</b> on an event downloads it with its "
        "open deadlines, as a file that Outlook, Google and Apple Calendar open. All days are whole days.</p>"
        f"<p><a href='{root}exports/events.json'>All events as data (JSON)</a> for spreadsheets and the AI assistant.</p></div>"
        f"<div class='ev-use-card'><h3>{icon('edit')}Add or correct an event</h3><p>The editors' list is "
        "<code>data/events.yaml</code>; its first lines explain the format. An event listed there always wins over the "
        "same event found by the refresh.</p>"
        + (f"<div class='actions'><a class='btn' href='https://github.com/{esc(repo)}/edit/main/data/events.yaml' "
           f"target='_blank' rel='noopener'>{icon('edit')}Edit on GitHub</a></div>" if repo else "")
        + "</div></div></section>")
    if found["notes"]:
        body.append("<details class='notes'><summary>Notes from the last calendar refresh</summary><ul>"
                    + "".join(f"<li>{esc(n)}</li>" for n in found["notes"]) + "</ul></details>")
    return "".join(body)


def export_entry(e, cfg, today):
    return {**{k: e[k] for k in ("id", "name", "short", "start", "end", "city", "country")},
            "country_name": country_name(e["country"]), "region": region_of(e, cfg),
            **{k: e[k] for k in ("online", "organiser", "kind", "issmge", "url")},
            "deadlines": [dict(d, passed=left_of(d["date"], today) < 0) for d in e["deadlines"]],
            "source": e["source"], "found": e["found"], "notes": e["notes"],
            "status": "past" if is_past(e, today) else "under way" if first_day(e["start"]) <= today else "upcoming"}


def build(ctx):
    """docs/events.html, docs/events.ics, docs/calendar/<id>.ics and docs/exports/events.json."""
    cfg = ctx["cfg"]
    today = ctx.get("today") or dt.date.today()
    opts = settings(cfg)
    problems = []
    events = load(cfg, problems)
    found = read_found()
    for p in problems:
        print("Events calendar: " + p)
    docs = site_builder.DOCS
    site_builder.write(docs / "events.html", site_builder.page(
        cfg, "Events calendar", page_body(cfg, events, found, today, problems, opts), "", "events",
        "Geotechnical conferences, ISSMGE events and call-for-papers deadlines",
        head="<script src='assets/events.js' defer></script><script src='assets/eventmap.js' defer></script>"
             # without JavaScript the map cannot be drawn: its table (the countries and their events) is shown instead
             "<noscript><style>.evm-chart, .evm-fig .viz-toggle { display: none !important; } "
             "#evm-table { display: block !important; }</style></noscript>"))

    stamp = stamp_of(found["updated"], today)
    feed = []
    shutil.rmtree(docs / "calendar", ignore_errors=True)
    (docs / "calendar").mkdir(parents=True)
    for e in events:
        block = ics_event(e, stamp)
        feed.append(block)
        feed += [ics_deadline(e, d, stamp) for d in e["deadlines"]]
        if block and not is_past(e, today):
            own = [block] + [ics_deadline(e, d, stamp) for d in e["deadlines"] if left_of(d["date"], today) >= 0]
            (docs / "calendar" / f"{e['id']}.ics").write_bytes(
                ics_calendar([b for b in own if b], label_of(e), cfg).encode("utf-8"))
    (docs / "events.ics").write_bytes(ics_calendar([b for b in feed if b], "Geotechnical events (ISSMGE Magazine)",
                                                   cfg).encode("utf-8"))
    site_builder.write(docs / "exports" / "events.json", json.dumps(
        {"updated": found["updated"], "built": today.isoformat(), "feed": (site_builder.site_url(cfg) or "") + "events.ics",
         "kinds": KINDS, "events": [export_entry(e, cfg, today) for e in events]}, ensure_ascii=False, indent=1))


# ------------------------------------------------------------------ the weekly refresh (Claude with web tools)
SYSTEM_RESEARCH = (
    "You keep the events calendar of the ISSMGE Magazine (International Society for Soil Mechanics and Geotechnical "
    "Engineering), read by practising geotechnical engineers and academics worldwide. You read event calendars and "
    "organisers' pages with web search and web fetch, and you report only what those pages say: never guess a date, "
    "a place or a web address.")
SYSTEM_EXTRACT = ("You turn research notes about geotechnical events into calendar entries. Take every fact from the "
                  "notes; leave a field empty when the notes do not give it.")


def research_prompt(opts, today, curated):
    horizon = add_months(today, opts["months_ahead"])
    cals = "\n".join(f"- {c['name']}: {c['url']}" for c in opts["calendars"])
    known = "\n".join(
        f"- {label_of(e)} · {date_range(e['start'], e['end'])} · {place(e) or 'place not listed'} · deadlines: "
        + (", ".join(f"{d['label']} {d['date']}" for d in e["deadlines"]) or "none listed")
        for e in curated if not is_past(e, today)) or "- (none yet)"
    blocked = ", ".join(opts["blocked_domains"]) or "none"
    return f"""Today is {today:%d %B %Y}. Find the geotechnical events that start between {today:%d %B %Y} and {horizon:%d %B %Y}, and every call for papers or abstracts that is still open.

Start with these calendars (open each with web fetch):
{cals}

Then search for others: ISSMGE technical committee (TC) symposia and workshops, the ISSMGE regional conferences and the International Conference (ICSMGE), conferences of ISSMGE member societies, and the main international conferences on tunnelling, rock mechanics (ISRM), geosynthetics (IGS), deep foundations (DFI), earthquake geotechnical engineering, offshore geotechnics, dams, engineering geology and site characterisation. Short courses and webinars count when a recognised society or university runs them.

The editors already list these events. Report one again only if its dates or place differ, or if it has deadlines that are not listed here:
{known}

Leave out:
- predatory or mass-produced conference series, such as WASET (World Academy of Science, Engineering and Technology) and generic "International Conference on ..." events sold in many cities; never use pages on these sites: {blocked};
- events that have ended, and events starting after {horizon:%d %B %Y};
- trade fairs without a technical programme, and events not about geotechnical, rock or tunnelling engineering, engineering geology or geosynthetics.

For each event write one block:
Name: full official name
Acronym: e.g. WTC 2027, or none
Dates: first and last day as YYYY-MM-DD (YYYY-MM if only the month is known)
Place: city and country, or "online"
Organiser: society or committee (e.g. ISSMGE TC211)
Kind: "ISSMGE conference" (organised by ISSMGE or under its auspices: the International Conference and the regional conferences), "ISSMGE-supported" (a technical committee symposium or other event ISSMGE supports), "Other conference", or "Course / webinar"
Event page: the event's own web address (https)
Read on: the address of the page where you read these details
Deadlines: each abstract, paper or registration deadline with its date (YYYY-MM-DD), or "none published"
Notes: anything an editor should check, such as dates still to be confirmed

Write the blocks one after another and nothing else."""


def extract_prompt(notes_text, today):
    return f"""Today is {today:%d %B %Y}. Turn every event in the research notes below into one entry:
- start and end: YYYY-MM-DD, or YYYY-MM when only the month is known; end equals start for a one-day event
- city: the city in English; country: its ISO 3166-1 alpha-2 code (BE, US, TH); both "" for an event held online only
- online: true only for an event held online only
- kind: one of {", ".join(KINDS)}
- issmge: true when ISSMGE or one of its technical committees organises or supports the event
- url: the event's own page; source_url: the page where the details were read (both https, copied exactly from the notes)
- deadlines: each with a short label (Abstracts, Full papers, Early registration …) and its date; [] when none are published
- notes: one short sentence for the editor, or ""
Leave out an event whose dates the notes do not give.

<notes>
{notes_text}
</notes>"""


def extract_schema():
    text_ = {"type": "string"}
    deadline = {"type": "object", "properties": {"label": text_, "date": text_},
                "required": ["label", "date"], "additionalProperties": False}
    event = {"type": "object", "properties": {
        "name": text_, "short": text_, "start": text_, "end": text_, "city": text_, "country": text_,
        "online": {"type": "boolean"}, "organiser": text_, "kind": {"type": "string", "enum": KINDS},
        "issmge": {"type": "boolean"}, "url": text_, "source_url": text_,
        "deadlines": {"type": "array", "items": deadline}, "notes": text_},
        "required": ["name", "short", "start", "end", "city", "country", "online", "organiser", "kind", "issmge",
                     "url", "source_url", "deadlines", "notes"], "additionalProperties": False}
    return {"type": "object", "properties": {"events": {"type": "array", "items": event}},
            "required": ["events"], "additionalProperties": False}


def api_call(client, raw, key, model, what, **request):
    """One streamed request; its final message, or ScanError with a clear reason."""
    import anthropic  # only needed when a key is configured
    try:
        import httpx2 as http  # the HTTP library of anthropic 2.x
    except ImportError:
        import httpx as http

    try:
        with client.messages.stream(model=model, **request) as stream:
            try:
                response = stream.get_final_message()
            except Exception:
                record_partial(stream, model)
                raise
        spent.append((model, response.usage, False))
        return response
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as ex:
        if WEB_OFF.search(scanner.api_message(ex)):
            raise ScanError(web_off_note(ex)) from None
        why = "was rejected" if isinstance(ex, anthropic.AuthenticationError) else f"was refused access to {model}"
        raise ScanError(f"the ANTHROPIC_API_KEY secret {why} ({scanner.api_message(ex)}). "
                        + scanner.describe_key(raw, key)
                        + " Change the key in Settings → Secrets and variables → Actions.") from None
    except anthropic.BadRequestError as ex:
        if WEB_OFF.search(scanner.api_message(ex)):
            raise ScanError(web_off_note(ex)) from None
        raise ScanError(f"Claude could not take the {what} request ({scanner.api_message(ex)}).") from None
    except anthropic.APIError as ex:
        body = getattr(ex, "body", None)
        error = body.get("error") if isinstance(body, dict) else None
        kind = error.get("type") if isinstance(error, dict) else None  # an error inside the stream comes with status 200
        busy = isinstance(ex, anthropic.APIConnectionError) or kind in BUSY_ERRORS or (
            isinstance(ex, anthropic.APIStatusError) and (ex.status_code == 429 or ex.status_code >= 500))
        raise ScanError(f"Claude returned an error or could not be reached during the {what} "
                        f"({scanner.api_message(ex)}).", transient=busy) from None
    except http.TransportError as ex:  # the connection dropped while Claude was answering
        raise ScanError(f"the connection to Claude dropped during the {what} ({type(ex).__name__}).",
                        transient=True) from None


def record_partial(stream, model):
    """A request that failed part-way (an error inside the stream) is billed for what it did: record that."""
    try:
        usage = stream.current_message_snapshot.usage
    except Exception:  # the stream broke before Claude started
        return
    spent.append((model, usage, True))


def web_off_note(ex):
    return ("web search is not enabled for the Anthropic organisation that owns the ANTHROPIC_API_KEY, so Claude "
            f"cannot read the organisers' calendars ({scanner.api_message(ex)}). An admin of that organisation can turn "
            "on web search and web fetch in the Claude Console (platform.claude.com), in the organisation's settings "
            "under its capabilities; then press Refresh calendar on the Events page.")


def as_dict(block):
    if hasattr(block, "model_dump"):
        return block.model_dump(mode="json")
    if isinstance(block, dict):
        return block
    return {k: getattr(block, k) for k in vars(block)} if hasattr(block, "__dict__") else {}


def read_turns(turns):
    """Claude's notes (its text), the web hosts its tools returned, and notes about tool errors."""
    notes, hosts, failed, codes = [], set(), [], Counter()
    asked = {}  # tool_use_id -> what was asked (the url fetched or the query searched)
    for response in turns:
        notes.append("")  # each request's notes start on a line of their own
        for block in response.content:
            kind = getattr(block, "type", "")
            if kind == "text":
                notes[-1] += block.text
                for c in getattr(block, "citations", None) or []:
                    if getattr(c, "url", ""):
                        hosts.add(host(c.url))
            elif kind == "server_tool_use":
                inp = getattr(block, "input", None) or {}
                asked[block.id] = str(inp.get("url") or inp.get("query") or "")
            elif kind.endswith("_tool_result"):
                content = getattr(block, "content", None)
                code = getattr(content, "error_code", None) if not isinstance(content, list) else None
                if code:  # a server-tool error arrives inside the result, not as an exception
                    codes[code] += 1
                    if kind == "web_fetch_tool_result":
                        failed.append(asked.get(getattr(block, "tool_use_id", ""), ""))
                    continue
                for url in URL_IN_TEXT.findall(json.dumps(as_dict(block), ensure_ascii=False)):
                    if host(url):
                        hosts.add(host(url))
    tool_notes = []
    shown = list(dict.fromkeys(host(u) + urlparse(u).path for u in failed if u))  # a page retried is named once
    if failed:
        tool_notes.append(f"Claude could not open {site_builder.count(len(shown) or len(failed), 'page')}"
                          + (f": {', '.join(shown[:5])}" + (" …" if len(shown) > 5 else "") if shown else "") + ".")
    if codes.get("max_uses_exceeded"):
        tool_notes.append("Claude reached the limit of searches or pages for one refresh (max_searches and max_fetches "
                          "in config.yaml, events:).")
    if codes.get("too_many_requests") or codes.get("unavailable"):
        tool_notes.append("The web tools were busy or unavailable for part of the refresh, so some calendars may "
                          "not have been read.")
    # cited passages come as separate text blocks within one sentence, so a request's blocks are joined as
    # they are; the notes of separate requests (a continuation, the write-up) are kept apart
    return "\n\n".join(n.strip() for n in notes if n.strip()), hosts, tool_notes


def research(client, opts, prompt, raw, key):
    """Claude reads the calendars with web search and web fetch; (notes, web hosts seen, tool notes)."""
    tool_opts = {"blocked_domains": opts["blocked_domains"]} if opts["blocked_domains"] else {}
    # max_content_tokens caps how much of each page enters the conversation, and caching lets every
    # later step of the research (and each continuation) re-read what came before at a small fraction of
    # the price (the API caches each tool result once the request carries a cache marker)
    fetch_cap = {"max_content_tokens": opts["max_page_tokens"]} if opts["max_page_tokens"] else {}
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": opts["max_searches"], **tool_opts},
             {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": opts["max_fetches"], **fetch_cap,
              **tool_opts}]
    system = [{"type": "text", "text": SYSTEM_RESEARCH, "cache_control": {"type": "ephemeral"}}]

    def ask(conversation):
        return api_call(client, raw, key, opts["model"], "calendar research", max_tokens=RESEARCH_TOKENS,
                        system=system, tools=tools, output_config={"effort": opts["effort"]},
                        cache_control={"type": "ephemeral"}, messages=conversation)

    if opts["model"] not in PRICES:
        print(f"Events calendar: no list price is known for {opts['model']}, so the spending limit assumes the "
              "dearest known prices.")
    messages = [{"role": "user", "content": prompt}]
    turns, extra, limit = [], [], ""
    for _ in range(opts["max_continuations"] + 1):
        try:
            response = ask(messages)
        except ScanError as ex:
            if not turns or ex.transient:
                raise  # nothing read yet, or Claude was busy: the next daily scan tries again
            # a continuation failed for good: the notes Claude made before it are used
            print(f"Events calendar: a continuation of the research failed: {ex}")
            extra.append("Claude's research stopped part-way; the notes it had made by then were used.")
            break
        turns.append(response)
        if response.stop_reason != "pause_turn":
            break
        # the server paused a long run of searches: send the paused turn back and it carries on
        messages.append({"role": "assistant", "content": response.content})
        cost = spent_cost(assume_dearest=True)
        if cost >= 0.8 * opts["max_cost_usd"]:  # every continuation may search and fetch again: cap the cost here
            limit = f"the spending limit (about US${cost:.2f} spent, max_cost_usd US${opts['max_cost_usd']:g})"
            break
    else:
        limit = f"{opts['max_continuations']} continuations (max_continuations)"
    if limit:
        print(f"Events calendar: the research reached {limit}; asking Claude to write up what it has found.")
        try:
            if turns[-1].content and getattr(turns[-1].content[-1], "type", "") == "server_tool_use":
                # the turn paused with a search or fetch still to run, and a system message may not follow
                # that: the pending step runs first (one more plain continuation)
                response = ask(messages)
                turns.append(response)
                if response.stop_reason == "pause_turn":
                    messages.append({"role": "assistant", "content": response.content})
            if turns[-1].stop_reason == "pause_turn":
                turns.append(ask(messages + [{"role": "system", "content": WRAP_UP}]))
        except ScanError as ex:
            if ex.transient:
                raise  # Claude was busy: the next daily scan tries again
            print(f"Events calendar: the write-up request failed: {ex}")
        extra.append("Claude's research reached its limit for one refresh, so Claude wrote up the events it had found "
                     "by then." if turns[-1].stop_reason == "end_turn" else
                     "Claude's research reached its limit for one refresh; the notes made by then were used.")
    stop = turns[-1].stop_reason
    if stop == "refusal":
        raise ScanError("Claude declined the calendar research.")
    if stop == "max_tokens":
        extra.append("Claude's research notes reached the length limit; the events noted up to then were used.")
    notes_text, hosts, tool_notes = read_turns(turns)
    return notes_text, hosts, tool_notes + extra


def extract(client, opts, notes_text, today, raw, key):
    """The research notes as calendar entries (a list of dicts in extract_schema's shape)."""
    response = api_call(client, raw, key, opts["model"], "calendar entries", max_tokens=EXTRACT_TOKENS,
                        system=SYSTEM_EXTRACT, messages=[{"role": "user", "content": extract_prompt(notes_text, today)}],
                        output_config={"effort": opts["extract_effort"],
                                       "format": {"type": "json_schema", "schema": extract_schema()}})
    if response.stop_reason == "refusal":
        raise ScanError("Claude declined to turn the research notes into calendar entries.")
    if response.stop_reason != "end_turn":
        raise ScanError(f"the calendar entries stopped early ({response.stop_reason}).")
    answer = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    try:
        entries = json.loads(answer)["events"]
    except (ValueError, KeyError, TypeError) as ex:
        raise ScanError(f"the calendar entries could not be read ({text(str(ex), 80)}).") from None
    return [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []


def blocked(entry, opts):
    hosts = [host(entry.get("url") or ""), host(entry.get("source_url") or "")]
    if any(h and on_domain(h, opts["blocked_domains"]) for h in hosts):
        return True
    who = f"{entry.get('name', '')} {entry.get('organiser', '')}".lower()
    return bool(PREDATORY_NAME.search(str(entry.get("name") or ""))
                or any(re.search(rf"(?<!\w){re.escape(o)}(?!\w)", who) for o in opts["blocked_organisers"] + ["waset"]))


def check_found(entries, today, opts, hosts):
    """The entries that pass the checks, and a Counter of why the others were left out."""
    keep, why = [], Counter()
    oldest, horizon = today - dt.timedelta(days=opts["keep_days"]), add_months(today, opts["months_ahead"])
    for raw in entries:
        if blocked(raw, opts):
            why["a predatory conference series"] += 1
            continue
        # the link must come from a page Claude read (a search result, a fetched page or a citation),
        # so an address it made up never reaches the calendar; a configured calendar that could not
        # be opened does not count
        links = [u for u in (text(raw.get("url"), 500), text(raw.get("source_url"), 500))
                 if u.lower().startswith("https://") and host(u)]
        good = [u for u in links if on_domain(host(u), hosts)]
        if not links:
            why["no https web address"] += 1
            continue
        if not good:
            why["a link that did not come from a page Claude read"] += 1
            continue
        try:
            event, _ = clean_event(dict(raw, url=good[0], id="", found=""), "scan", https_only=True)
        except Problem as ex:
            reason = str(ex)
            why["no name" if "no name" in reason else "an end date before the start date" if reason.startswith("it ends")
                else "no readable dates"] += 1
            continue
        if last_day(event["end"]) < oldest:
            why["already over"] += 1
            continue
        if first_day(event["start"]) > horizon:
            why[f"starting more than {opts['months_ahead']} months ahead"] += 1
            continue
        event["deadlines"] = [d for d in event["deadlines"] if first_day(d["date"]) <= last_day(event["end"])]
        keep.append(event)
    return keep, why


def merge_found(new, old, curated, today, opts, day):
    """This refresh's events merged with the earlier ones: an event found again keeps its id and the
    day it was first found; earlier events that were not found again stay while they are still on.
    Returns (events to keep, events new to the calendar, distinct events this refresh found)."""
    oldest = today - dt.timedelta(days=opts["keep_days"])
    kept, fresh = [], 0
    for e in new:
        twin = next((k for k in kept if same_event(k, e)), None)
        if twin is not None:  # reported twice in one refresh
            twin["deadlines"] = merge_deadlines(twin["deadlines"], e["deadlines"])
            continue
        before = next((o for o in old if same_event(o, e) and not blocked(o, opts)), None)
        if before is not None:
            e["id"], e["found"] = before["id"], before["found"] or day
            e["deadlines"] = merge_deadlines(e["deadlines"], before["deadlines"])
        else:
            e["found"] = day
            fresh += not any(same_event(c, e) for c in curated)
        kept.append(e)
    distinct = len(kept)
    for o in old:  # an earlier find whose site or organiser has been blocked since is dropped
        if last_day(o["end"]) >= oldest and not blocked(o, opts) and not any(same_event(k, o) for k in kept):
            kept.append(o)
    kept.sort(key=lambda e: (first_day(e["start"]), e["name"].lower()))
    assign_ids(kept)
    return kept, fresh, distinct


def due(now, opts):
    """(True, why) when the calendar should be refreshed today, else (False, why). After a refresh
    that failed, the next one waits until its retry day, so Claude's research is not repeated every day."""
    found = read_found()
    updated, today = found["updated"], now.astimezone(dt.timezone.utc).date()
    if found["retry"] and today < dt.date.fromisoformat(found["retry"]):
        return False, (f"the refresh of {nice(found['attempted'][:10])} did not complete; the daily scan tries "
                       f"again on {nice(found['retry'])} (Refresh calendar on the Events page tries now)")
    if not updated:
        return True, "the calendar has not been refreshed yet"
    last = dt.datetime.fromisoformat(updated)
    last = (last if last.tzinfo else last.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc).date()
    age = (today - last).days
    if age >= opts["refresh_days"]:
        return True, f"the calendar was last refreshed {site_builder.count(age, 'day')} ago"
    return False, (f"refreshed on {nice(last.isoformat())}; the next refresh is due on "
                   f"{nice((last + dt.timedelta(days=opts['refresh_days'])).isoformat())}")


def record_failure(now, note, transient):
    """Note in data/events.json that a refresh failed, keeping the events it holds: the daily scan
    tries again after RETRY_DAYS days, or the next day when Claude was busy or could not be reached."""
    try:
        data = json.loads(FOUND_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    retry = now.astimezone(dt.timezone.utc).date() + dt.timedelta(days=1 if transient else RETRY_DAYS)
    data = {"updated": data.get("updated") or "", "events": data.get("events") or [], "notes": data.get("notes") or [],
            "attempted": now.isoformat(timespec="seconds"), "failed": text(note, 400), "retry": retry.isoformat()}
    FOUND_FILE.parent.mkdir(parents=True, exist_ok=True)
    FOUND_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return retry


def spent_cost(assume_dearest=False):
    """What this refresh has cost so far at list prices (US$), or None for a model without a price
    (assume_dearest: cost such a model at the dearest known prices instead, for the spending limit)."""
    total = 0.0
    for model, u, _ in spent:
        price = PRICES.get(model) or (max(PRICES.values()) if assume_dearest else None)
        if not price:
            return None
        tools = u.server_tool_use
        total += ((u.input_tokens or 0) * price[0] + (u.output_tokens or 0) * price[1]
                  + (u.cache_read_input_tokens or 0) * price[2] + (u.cache_creation_input_tokens or 0) * price[3]) / 1e6
        total += ((getattr(tools, "web_search_requests", 0) or 0) if tools else 0) * SEARCH_PRICE
    return total


def spent_line():
    """Tokens, searches and pages this refresh used, with the cost at list prices when the model is known."""
    if not spent:
        return ""
    sums = Counter()
    for model, u, _ in spent:
        part = {"in": u.input_tokens or 0, "out": u.output_tokens or 0, "read": u.cache_read_input_tokens or 0,
                "write": u.cache_creation_input_tokens or 0,
                "searches": getattr(u.server_tool_use, "web_search_requests", 0) or 0 if u.server_tool_use else 0,
                "pages": getattr(u.server_tool_use, "web_fetch_requests", 0) or 0 if u.server_tool_use else 0}
        sums.update(part)
    cost = spent_cost()
    broken = sum(1 for *_, partial in spent if partial)
    line = (f"Events calendar: {len(spent)} request(s)"
            + (f" ({broken} stopped part-way)" if broken else "") + f" used {sums['in'] + sums['read'] + sums['write']:,} input tokens "
            f"({sums['read']:,} read from the cache), {sums['out']:,} output tokens, "
            f"{site_builder.count(sums['searches'], 'web search', 'web searches')} and "
            f"{site_builder.count(sums['pages'], 'page')} opened")
    return line + (f"; about US${cost:.2f} at list prices." if cost is not None else ".")


def scan(cfg, now, notes, force=False):
    """Refresh data/events.json with the events Claude finds on the organisers' calendars.
    Returns the number of events this refresh found (0 when it was not due, had no key or failed:
    notes says why). The calendar's events are only replaced after a refresh that found events;
    a refresh that failed is recorded, so the daily scan does not repeat it every day."""
    opts = settings(cfg)
    if not force:
        is_due, why = due(now, opts)
        if not is_due:
            print(f"Events calendar: {why}.")
            return 0
    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    key = scanner.clean_api_key(raw)
    if not key:
        note = ("Events calendar not refreshed: there is no ANTHROPIC_API_KEY (the secret is missing or empty), so "
                "Claude cannot read the organisers' calendars. Add the key in Settings → Secrets and variables → Actions.")
        print(note)
        notes.append(note)
        return 0
    if key != raw:
        print("ANTHROPIC_API_KEY: " + scanner.describe_key(raw, key).split(". ")[0] + ".")
    import anthropic  # only needed when a key is configured

    client = anthropic.Anthropic(api_key=key, max_retries=3)
    spent.clear()
    today = now.date()
    curated = read_curated([])
    old = read_found()
    try:
        print(f"Events calendar: Claude is reading {site_builder.count(len(opts['calendars']), 'calendar')} "
              f"and searching for more ({opts['model']}, effort {opts['effort']}) …")
        notes_text, hosts, run_notes = research(client, opts, research_prompt(opts, today, curated), raw, key)
        if not notes_text.strip():
            raise ScanError("Claude's research came back without any notes.")
        entries = extract(client, opts, notes_text, today, raw, key)
    except ScanError as ex:
        retry = record_failure(now, str(ex), ex.transient)
        note = (f"Events calendar not refreshed: {ex} The calendar keeps the events it had; the daily scan tries "
                f"again on {nice(retry.isoformat())}.")
        if spent_line():
            print(spent_line())
        print(note)
        notes.append(note)
        return 0
    found, why = check_found(entries, today, opts, hosts)
    if why:
        run_notes.append(f"Left out {site_builder.count(sum(why.values()), 'event')} that Claude reported: "
                         + "; ".join(f"{reason} ({n})" for reason, n in why.most_common()) + ".")
    if not found:
        why_not = "no event Claude reported passed the checks" + (f" ({len(entries)} reported)" if entries else "")
        retry = record_failure(now, why_not + ".", False)
        note = (f"Events calendar not refreshed: {why_not}. The calendar keeps the events it had; the daily scan "
                f"tries again on {nice(retry.isoformat())}.")
        for n in run_notes:
            print("  " + n)
        print(spent_line())
        print(note)
        notes.append(note)
        return 0
    kept, fresh, distinct = merge_found(found, old["events"], curated, today, opts, today.isoformat())
    run_notes.insert(0, f"Claude found {site_builder.count(distinct, 'event')} ({fresh} new to the calendar); "
                        f"the calendar now holds {site_builder.count(len(kept), 'event')} found by refreshes.")
    FOUND_FILE.parent.mkdir(parents=True, exist_ok=True)
    FOUND_FILE.write_text(json.dumps({"updated": now.isoformat(timespec="seconds"), "events": kept,
                                      "notes": run_notes}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Events calendar refreshed: {FOUND_FILE.relative_to(ROOT)}")
    for n in run_notes:
        print("  " + n)
    print(spent_line())
    notes.extend(run_notes)
    return distinct


# ------------------------------------------------------------------ command line
def annotate(level, message):
    """Show a message on the GitHub run's page as well as in its log."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level} title=Events calendar::" + message.replace("%", "%25").replace("\n", "%0A"))


def summary(cfg, today):
    """The calendar as it stands, for the terminal."""
    opts = settings(cfg)
    problems = []
    events = load(cfg, problems)
    found = read_found()
    n_ed = sum(1 for e in events if e["source"] == "editors")
    print(f"Events calendar: {site_builder.count(n_ed, 'event')} from data/events.yaml, {len(events) - n_ed} found by "
          "the weekly refresh" + (f" (refreshed {nice(found['updated'][:10])})." if found["updated"] else " (not refreshed yet)."))
    coming = [e for e in events if not is_past(e, today)]
    if coming:
        print("Upcoming:")
        for e in coming:
            print(f"  {date_range(e['start'], e['end']):<26} {label_of(e)} · {place(e) or '–'} · {e['kind']}")
    calls = open_deadlines(events, today, opts["deadline_days"])
    print(f"Open deadlines (next {opts['deadline_days']} days):" + ("" if calls else " none"))
    for c in calls:
        print(f"  {nice(c['date']):<12} {c['label']} · {label_of(c['event'])} ({left_text(c['date'], today)})")
    if problems:
        print("Problems in data/events.yaml:")
        for p in problems:
            print("  " + p)
    return 1 if problems else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="The events calendar: show it, or have Claude refresh it.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--auto", action="store_true", help="refresh when the calendar is refresh_days old (daily scan)")
    mode.add_argument("--refresh", action="store_true", help="refresh now")
    ap.add_argument("--today", type=dt.date.fromisoformat, help="pretend today is YYYY-MM-DD (for testing)")
    args = ap.parse_args(argv)
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    if args.today:
        now = dt.datetime.combine(args.today, now.timetz())
    if not (args.auto or args.refresh):
        return summary(cfg, now.date())
    notes = []
    if args.auto:
        is_due, why = due(now, settings(cfg))
        if not is_due:
            print(f"Events calendar: no refresh today: {why}.")
            return 0
        print(f"Events calendar: refreshing, as {why}.")
    if not scanner.clean_api_key(os.environ.get("ANTHROPIC_API_KEY", "")):
        scan(cfg, now, notes, force=True)  # says why in the log
        if args.auto:
            return 0  # in the daily scan, as its other steps: a note in the log
        annotate("error", notes[-1])  # Refresh calendar must not report a refresh that did not happen
        return 1
    found = scan(cfg, now, notes, force=True)
    if not found:
        annotate("warning" if args.auto else "error", notes[-1] if notes else "The calendar was not refreshed.")
        return 0 if args.auto else 1  # after a scan a failed refresh is a note, not an error
    site_builder.build(cfg)  # the save step rebuilds the site again from the newest branch
    return 0


if __name__ == "__main__":
    sys.exit(main())
