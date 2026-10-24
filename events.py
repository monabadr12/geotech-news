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
esc = site_builder.esc

KINDS = ["ISSMGE conference", "ISSMGE-supported", "Other conference", "Course / webinar"]
ISSMGE_KINDS = KINDS[:2]
KIND_CLASS = {"ISSMGE conference": "k-conf", "ISSMGE-supported": "k-supp", "Other conference": "k-other",
              "Course / webinar": "k-course"}
EFFORTS = ("low", "medium", "high", "xhigh", "max")
RESEARCH_TOKENS = 64000  # thinking, searches and the notes; streamed, so a long turn cannot time out
EXTRACT_TOKENS = 32000

DEFAULTS = {"model": "claude-opus-5-5", "effort": "medium", "extract_effort": "low", "refresh_days": 7,
            "months_ahead": 24, "deadline_days": 90, "keep_days": 7, "max_searches": 10, "max_fetches": 15,
            "max_continuations": 4}
DEFAULT_CALENDARS = [
    {"name": "ISSMGE events", "url": "https://www.issmge.org/events"},
    {"name": "ISSMGE news (calls for abstracts)", "url": "https://www.issmge.org/news"},
    {"name": "ITA-AITES future events", "url": "https://about.ita-aites.org/future-events"},
    {"name": "ASCE Geo-Institute conferences and events",
     "url": "https://www.asce.org/communities/institutes-and-technical-groups/geo-institute/conferences-and-events"},
    {"name": "GeoEngineer.org events", "url": "https://www.geoengineer.org/events"},
]
DEFAULT_BLOCKED = ["waset.org", "conferenceindex.org", "conferenceseries.com", "omicsonline.org"]
# WASET-style mass series: "ICGEGT 2027: 21. International Conference on ..." and the like
PREDATORY_NAME = re.compile(r"^\s*[A-Z]{3,}\s*\d{4}\s*:|\b\d{1,2}\.\s*International Conference on\b"
                            r"|World Academy of Science", re.I)
HOSTNAME = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,}$")
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
    """A refresh could not be completed; the message says why, for the log and the page."""


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
        try:
            if isinstance(value, bool):
                raise ValueError
            out[name] = default if value is None else max(0, int(value))
        except (TypeError, ValueError):
            print(f"config.yaml, events: {name}: {value!r} is not a whole number; using {default}.")
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
    if not m:
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
    """The last refresh: {"updated": iso or "", "events": [...], "notes": [...]}; empty when missing or unreadable."""
    try:
        data = json.loads(FOUND_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"updated": "", "events": [], "notes": []}
    data = data if isinstance(data, dict) else {}
    events = []
    for raw in data.get("events") or []:
        if isinstance(raw, dict):
            try:
                events.append(clean_event(raw, "scan")[0])
            except Problem:
                continue
    updated = str(data.get("updated") or "")
    try:
        dt.datetime.fromisoformat(updated)
    except ValueError:
        updated = ""
    return {"updated": updated, "events": events, "notes": [text(n, 400) for n in data.get("notes") or [] if n]}


STOP = {"the", "of", "on", "and", "for", "in", "a", "an", "to", "at", "with", "international", "conference",
        "symposium", "congress", "workshop", "annual", "meeting", "edition", "part", "issmge"}


def words(name):
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    plain = re.sub(r"\b(?:19|20)\d\d\b|\b\d+(?:st|nd|rd|th)\b", " ", plain)
    return {w for w in re.findall(r"[a-z0-9]+", plain) if w not in STOP and not w.isdigit()}


def norm_url(url):
    p = urlparse(url)
    return host(url) + p.path.rstrip("/").lower()


def same_event(a, b):
    """Two entries for one event: the same name, acronym or link in the same year, or the
    same start day in the same city."""
    if first_day(a["start"]).year != first_day(b["start"]).year:
        return False
    wa, wb = words(a["name"]), words(b["name"])
    if wa and wa == wb:
        return True
    sa, sb = re.sub(r"[^a-z0-9]", "", a["short"].lower()), re.sub(r"[^a-z0-9]", "", b["short"].lower())
    if sa and sa == sb:
        return True
    overlap = len(wa & wb) / len(wa | wb) if wa and wb else 0
    if overlap >= 0.75:
        return True
    if norm_url(a["url"]) == norm_url(b["url"]) and (a["start"] == b["start"] or overlap >= 0.5):
        return True
    return bool(a["start"] == b["start"] and a["city"] and a["city"].lower() == b["city"].lower())


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
    (an editors' entry always wins; when it has no deadlines yet, the refresh's are shown)."""
    problems = [] if problems is None else problems
    curated = read_curated(problems)
    found = read_found()
    out = list(curated)
    for e in found["events"]:
        twin = next((c for c in curated if same_event(c, e)), None)
        if twin is not None:
            if not twin["deadlines"] and e["deadlines"]:
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
    """'Upcoming events & deadlines': the next calls for papers and events, for other pages.
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
                   for title, items in (("Calls for papers", deadline_items_), ("Coming up", event_items)) if items)
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
    return ["BEGIN:VEVENT", f"UID:{ics_uid(e['id'], 'deadline', d['label'])}", f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + dt.timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{ics_text('Deadline: ' + d['label'] + ' – ' + label_of(e))}",
            f"DESCRIPTION:{ics_text(desc)}", *([f"URL:{e['url']}"] if e["url"] != "#" else []),
            "CATEGORIES:Call for papers", "TRANSP:TRANSPARENT", "END:VEVENT"]


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
        return (f"<section class='ev-calls none' id='calls'><h2 class='section-h'>Open calls for papers</h2>"
                f"<p class='empty'>No call-for-papers deadlines in the next {days} days. Later deadlines are shown "
                "on each event below.</p></section>")
    rows = []
    for c in calls:
        e, n = c["event"], left_of(c["date"], today)
        state = "urgent" if n <= 14 else "soon" if n <= 30 else "open"
        sub = " · ".join(x for x in (e["name"] if e["short"] else "", place(e), date_range(e["start"], e["end"])) if x)
        rows.append(f"<li class='{state}'><a href='#ev-{esc(e['id'])}'><span class='ev-cd'>{date_tile(c['date'])}</span>"
                    f"<span class='ev-ct'><b>{esc(c['label'])}</b> · {esc(label_of(e))}<small dir='auto'>{esc(sub)}</small></span>"
                    f"{left_html(c['date'], today)}</a></li>")
    return (f"<section class='ev-calls' id='calls'><h2 class='section-h'>Open calls for papers "
            f"<span class='h1-sub'>deadlines in the next {days} days</span></h2>"
            "<p class='hint'>Abstract, paper and registration deadlines, soonest first. Check each date on the event's "
            f"website before announcing it.</p><ol class='ev-calls-list'>{''.join(rows)}</ol></section>")


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
    nxt = next((e for e in coming if first_day(e["start"]) > today), None)
    stats = (site_builder.stat(len(coming), f"events in the next {opts['months_ahead']} months")
             + site_builder.stat(sum(1 for e in coming if e["issmge"]), "ISSMGE events")
             + site_builder.stat(len(calls), f"open calls ({opts['deadline_days']} days)")
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
        head="<script src='assets/events.js' defer></script>"))

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
        with client.messages.stream(model=model, **request) as stream:
            return stream.get_final_message()
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
        raise ScanError(f"Claude returned an error or could not be reached during the {what} "
                        f"({scanner.api_message(ex)}). The next daily scan tries again.") from None


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
        for block in response.content:
            kind = getattr(block, "type", "")
            if kind == "text":
                notes.append(block.text)
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
    shown = [host(u) + urlparse(u).path for u in failed if u]
    if failed:
        tool_notes.append(f"Claude could not open {site_builder.count(len(failed), 'page')}"
                          + (f": {', '.join(shown[:5])}" + (" …" if len(shown) > 5 else "") if shown else "") + ".")
    if codes.get("max_uses_exceeded"):
        tool_notes.append("Claude reached the limit of searches or pages for one refresh (max_searches and max_fetches "
                          "in config.yaml, events:).")
    if codes.get("too_many_requests") or codes.get("unavailable"):
        tool_notes.append("The web tools were busy or unavailable for part of the refresh, so some calendars may "
                          "not have been read.")
    # cited passages come as separate text blocks within one sentence, so the blocks are joined as they are
    return "".join(notes).strip(), hosts, tool_notes


def research(client, opts, prompt, raw, key):
    """Claude reads the calendars with web search and web fetch; (notes, web hosts seen, tool notes)."""
    tool_opts = {"blocked_domains": opts["blocked_domains"]} if opts["blocked_domains"] else {}
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": opts["max_searches"], **tool_opts},
             {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": opts["max_fetches"], **tool_opts}]
    messages = [{"role": "user", "content": prompt}]
    turns, extra = [], []
    for _ in range(opts["max_continuations"] + 1):
        response = api_call(client, raw, key, opts["model"], "calendar research", max_tokens=RESEARCH_TOKENS,
                            system=SYSTEM_RESEARCH, tools=tools, output_config={"effort": opts["effort"]},
                            messages=messages)
        turns.append(response)
        if response.stop_reason != "pause_turn":
            break
        # the server paused a long run of searches: send the paused turn back and it carries on
        messages.append({"role": "assistant", "content": response.content})
    else:
        extra.append(f"Claude was still reading after {opts['max_continuations']} continuations; the notes it had "
                     "made by then were used.")
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
    calendars = {norm_url(c["url"]) for c in opts["calendars"]}
    for raw in entries:
        if blocked(raw, opts):
            why["a predatory conference series"] += 1
            continue
        # the link must come from a page Claude read (a search result, a fetched page or a citation),
        # so an address it made up never reaches the calendar
        links = [u for u in (text(raw.get("url"), 500), text(raw.get("source_url"), 500))
                 if u.lower().startswith("https://") and host(u)]
        good = [u for u in links if on_domain(host(u), hosts) or norm_url(u) in calendars]
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
        before = next((o for o in old if same_event(o, e)), None)
        if before is not None:
            e["id"], e["found"] = before["id"], before["found"] or day
            e["deadlines"] = merge_deadlines(e["deadlines"], before["deadlines"])
        else:
            e["found"] = day
            fresh += not any(same_event(c, e) for c in curated)
        kept.append(e)
    distinct = len(kept)
    for o in old:
        if last_day(o["end"]) >= oldest and not any(same_event(k, o) for k in kept):
            kept.append(o)
    kept.sort(key=lambda e: (first_day(e["start"]), e["name"].lower()))
    assign_ids(kept)
    return kept, fresh, distinct


def due(now, opts):
    """(True, why) when the calendar should be refreshed today, else (False, why)."""
    updated = read_found()["updated"]
    if not updated:
        return True, "the calendar has not been refreshed yet"
    last = dt.datetime.fromisoformat(updated)
    last = (last if last.tzinfo else last.replace(tzinfo=dt.timezone.utc)).astimezone(dt.timezone.utc).date()
    age = (now.astimezone(dt.timezone.utc).date() - last).days
    if age >= opts["refresh_days"]:
        return True, f"the calendar was last refreshed {site_builder.count(age, 'day')} ago"
    return False, (f"refreshed on {nice(last.isoformat())}; the next refresh is due on "
                   f"{nice((last + dt.timedelta(days=opts['refresh_days'])).isoformat())}")


def scan(cfg, now, notes, force=False):
    """Refresh data/events.json with the events Claude finds on the organisers' calendars.
    Returns the number of events this refresh found (0 when it was not due, had no key or failed:
    notes says why). The calendar is only saved after a refresh that found events."""
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
        note = f"Events calendar not refreshed: {ex} The calendar keeps the events it had."
        print(note)
        notes.append(note)
        return 0
    found, why = check_found(entries, today, opts, hosts)
    if why:
        run_notes.append(f"Left out {site_builder.count(sum(why.values()), 'event')} that Claude reported: "
                         + "; ".join(f"{reason} ({n})" for reason, n in why.most_common()) + ".")
    if not found:
        note = ("Events calendar not refreshed: no event Claude reported passed the checks"
                + (f" ({len(entries)} reported)" if entries else "") + ". The calendar keeps the events it had.")
        for n in run_notes:
            print("  " + n)
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
    print(f"Open calls for papers (next {opts['deadline_days']} days):" + ("" if calls else " none"))
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
        return 0
    found = scan(cfg, now, notes, force=True)
    if not found:
        annotate("warning" if args.auto else "error", notes[-1] if notes else "The calendar was not refreshed.")
        return 0 if args.auto else 1  # after a scan a failed refresh is a note, not an error
    site_builder.build(cfg)  # the save step rebuilds the site again from the newest branch
    return 0


if __name__ == "__main__":
    sys.exit(main())
