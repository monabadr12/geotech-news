#!/usr/bin/env python3
"""
Alerts and the weekly summary: an e-mail when a 5/5 story appears and a Monday
summary for the editorial team, and the weekly summary pages (docs/weekly/).

    python notify.py --auto      after each daily scan: one e-mail for the new 5/5 stories, and on
                                 Mondays (Cairo time) the summary of the week before
    python notify.py --weekly    send last week's summary now (any day; --week 2026-W43 for another)
    python notify.py --test      send a short test e-mail, to check the e-mail settings
    (--today 2026-10-26 runs the --auto rules as on that day, for testing)

E-mail goes out by the first channel that is set up:
  1. a mail server: the GitHub secret SMTP_HOST, with SMTP_PORT (587, or 465 for SSL), SMTP_USER,
     SMTP_PASSWORD and MAIL_TO (addresses separated by commas);
  2. the Google connector of the AI assistant (assistant/bridge.gs, whose web address is
     config.yaml assistant: endpoint): it sends from the editor's Google account when the GitHub
     secret NOTIFY_TOKEN matches the script's NOTIFY_TOKEN property (recipients: its MAIL_TO
     property, or the account's own address);
  3. neither: the log shows what would have been sent and how to set e-mail up. --auto still ends
     without an error (it never fails a scan); --weekly and --test end with exit code 1, so their run
     on GitHub (and the website's Send summary now) does not report an e-mail that was not sent.

data/notify.json records what was sent, so nothing goes out twice:
    {"alerted": {story id (or "digest:<date>" for the daily digest): date sent},
     "weekly":  {week key, e.g. "2026-W43": time sent}}
Only an e-mail that was really sent is recorded; alert entries are kept for 60 days.
"""
import argparse
import datetime as dt
import json
import os
import re
import smtplib
import ssl
import sys
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
import yaml

import site_builder

ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("SCANNER_CONFIG", ROOT / "config.yaml"))
NOTIFY_FILE = ROOT / "data" / "notify.json"
esc = site_builder.esc
MONTHS = site_builder.MONTHS
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEK_KEY = re.compile(r"^(\d{4})-W(\d{2})$")
KEEP_DAYS = 60      # alert records older than this are forgotten
SENDER = "Geotechnical News Desk"
DEFAULTS = {"story_alerts": True, "weekly_summary": True, "min_relevance": 5, "weekday": "Monday",
            "catch_up_days": 1, "max_stories": 8, "events_days": 60, "daily_digest": False}
try:
    CAIRO = ZoneInfo("Africa/Cairo")
except ZoneInfoNotFoundError:  # no time-zone database on this machine: Egypt's winter time
    CAIRO = dt.timezone(dt.timedelta(hours=2))


class NotifyError(Exception):
    """An e-mail could not be sent; the message says why, for the log."""


# ------------------------------------------------------------------ settings and dates
_warned = set()


def warn_once(text):
    if text not in _warned:
        _warned.add(text)
        print(text)


def settings(cfg):
    """The alerts: section of config.yaml, with defaults. A value that cannot be read is
    reported (once) and its default used, so a typo there never stops a scan or a build."""
    a = cfg.get("alerts")
    a = a if isinstance(a, dict) else {}
    out = {}
    for name, default in DEFAULTS.items():
        value = a.get(name)
        if value is None:
            out[name] = default
        elif isinstance(default, bool):
            if isinstance(value, bool):
                out[name] = value
            else:
                warn_once(f"config.yaml, alerts: {name}: {value!r} is not true or false; using {str(default).lower()}.")
                out[name] = default
        elif name == "weekday":
            text = str(value).strip().lower()
            day = next((d for d in WEEKDAYS if text and d.lower().startswith(text[:3]) and len(text) >= 3), None)
            if not day:
                warn_once(f"config.yaml, alerts: weekday: {value!r} is not a day of the week; using {default}.")
            out[name] = day or default
        else:
            try:
                if isinstance(value, bool):
                    raise ValueError
                out[name] = int(value)
            except (TypeError, ValueError):
                warn_once(f"config.yaml, alerts: {name}: {value!r} is not a whole number; using {default}.")
                out[name] = default
    out["min_relevance"] = min(5, max(1, out["min_relevance"]))
    out["catch_up_days"] = min(6, max(0, out["catch_up_days"]))
    out["max_stories"] = max(1, out["max_stories"])
    out["events_days"] = max(1, out["events_days"])
    return out


def cairo_today(now=None):
    """Today's date in Cairo (the scan's clock: 05:00 Cairo time)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.astimezone(CAIRO).date()


def week_key(date):
    """ISO week of a date (or an ISO date text), e.g. "2026-W43"."""
    if isinstance(date, str):
        date = dt.date.fromisoformat(date[:10])
    year, week, _ = date.isocalendar()
    return f"{year}-W{week:02d}"


def week_range(key):
    """Monday and Sunday of an ISO week key."""
    m = WEEK_KEY.match(key or "")
    if not m:
        raise ValueError(f"not a week key: {key!r} (give it as year-Wnn, e.g. 2026-W43)")
    monday = dt.date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
    return monday, monday + dt.timedelta(days=6)


def last_week(today):
    """The last full week (Monday to Sunday) before the week of today."""
    return week_key(today - dt.timedelta(days=today.weekday() + 1))


def send_day(key, opts):
    """The day the summary of a week goes out: the first configured weekday after the week."""
    return week_range(key)[1] + dt.timedelta(days=1 + WEEKDAYS.index(opts["weekday"]))


def short_date(d):
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def span_text(monday, sunday):
    """19–25 Oct 2026; 28 Sep – 4 Oct 2026; 29 Dec 2025 – 4 Jan 2026."""
    if monday.year != sunday.year:
        return f"{short_date(monday)} – {short_date(sunday)}"
    if monday.month != sunday.month:
        return f"{monday.day} {MONTHS[monday.month - 1]} – {short_date(sunday)}"
    return f"{monday.day}–{short_date(sunday)}"


def week_label(key):
    m = WEEK_KEY.match(key)
    return f"Week {int(m.group(2))}, {m.group(1)}"


def when_sent(iso):
    """'Monday 26 Oct 2026 at 05:12 (Cairo time)' from the recorded UTC time."""
    try:
        t = dt.datetime.fromisoformat(str(iso))
    except ValueError:
        return ""
    t = (t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)).astimezone(CAIRO)
    return f"{t:%A} {short_date(t.date())} at {t:%H:%M} (Cairo time)"


# ------------------------------------------------------------------ the record of e-mails sent
def load_record():
    """data/notify.json; a file that cannot be read counts as empty (with a message)."""
    try:
        j = json.loads(NOTIFY_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        j = {}
    except (OSError, ValueError) as ex:
        print(f"data/notify.json could not be read ({type(ex).__name__}); treating it as empty.")
        j = {}
    j = j if isinstance(j, dict) else {}
    return {k: {str(i): str(v) for i, v in (j.get(k) or {}).items()} if isinstance(j.get(k), dict) else {}
            for k in ("alerted", "weekly")}


def save_record(rec, today):
    cutoff = (today - dt.timedelta(days=KEEP_DAYS)).isoformat()
    rec["alerted"] = {k: v for k, v in rec["alerted"].items() if v[:10] >= cutoff}
    NOTIFY_FILE.parent.mkdir(parents=True, exist_ok=True)
    NOTIFY_FILE.write_text(json.dumps({k: dict(sorted(rec[k].items())) for k in ("alerted", "weekly")},
                                      ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ delivery
def env(name):
    return os.environ.get(name, "").strip()


def mask(text):
    """Any secret that might appear in an error message, replaced by ***."""
    text = str(text)
    for name in ("SMTP_PASSWORD", "NOTIFY_TOKEN"):
        value = os.environ.get(name, "")
        if len(value) >= 4:
            text = text.replace(value, "***")
    return text


def channel(cfg):
    """How e-mail goes out: "smtp", "connector" or "" (not set up)."""
    if env("SMTP_HOST"):
        return "smtp"
    if site_builder.assistant_endpoint(cfg) and env("NOTIFY_TOKEN"):
        return "connector"
    return ""


def channel_name(kind):
    return {"smtp": f"the mail server ({env('SMTP_HOST')})", "connector": "the Google connector (Apps Script)"}.get(kind, "")


def plural(n, one, many=None):
    return site_builder.count(n, one, many)


def send_smtp(subject, html_, text):
    host, user, pwd = env("SMTP_HOST"), env("SMTP_USER"), os.environ.get("SMTP_PASSWORD", "")
    to = [a.strip() for a in env("MAIL_TO").replace(";", ",").split(",") if a.strip()]
    if not to and "@" in user:
        to = [user]  # no MAIL_TO: to the mail account itself
    if not to:
        raise NotifyError("SMTP_HOST is set but there is no recipient: add the GitHub secret MAIL_TO "
                          "(addresses separated by commas).")
    try:
        port = int(env("SMTP_PORT") or 587)
    except ValueError:
        raise NotifyError(f"SMTP_PORT is {env('SMTP_PORT')!r}, not a port number (usually 587).") from None
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user if "@" in user else to[0], ", ".join(to)
    msg["Date"], msg["Message-ID"] = formatdate(localtime=False), make_msgid(domain="geotech-news")
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html_, "html", "utf-8"))
    context = ssl.create_default_context()  # verify the mail server's certificate
    try:
        if port == 465:  # SSL from the start
            server = smtplib.SMTP_SSL(host, port, timeout=60, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=60)
        with server as s:
            if port != 465:
                s.starttls(context=context)
            if user:
                s.login(user, pwd)
            refused = s.sendmail(msg["From"], to, msg.as_string())
    except smtplib.SMTPAuthenticationError:
        raise NotifyError(f"The mail server {host} did not accept SMTP_USER and SMTP_PASSWORD. For Gmail, "
                          "SMTP_PASSWORD must be an app password (Google account → Security → App passwords).") from None
    except smtplib.SMTPNotSupportedError:
        raise NotifyError(f"The mail server {host}:{port} does not offer an encrypted connection (STARTTLS): "
                          "use port 587, or 465 for SSL.") from None
    except smtplib.SMTPRecipientsRefused:
        raise NotifyError(f"The mail server {host} refused every address in MAIL_TO.") from None
    except ssl.SSLError as ex:
        raise NotifyError(f"The secure connection to {host}:{port} failed ({mask(ex)}).") from None
    except (smtplib.SMTPException, OSError) as ex:
        raise NotifyError(f"The mail server {host}:{port} could not be used: {type(ex).__name__}: {mask(ex)}") from None
    sent = len(to) - len(refused or {})
    return f"sent by the mail server ({host}) to {plural(sent, 'recipient')}" + (
        f"; {plural(len(refused), 'address', 'addresses')} refused" if refused else "")


def send_connector(subject, html_, text, cfg):
    url = site_builder.assistant_endpoint(cfg)
    payload = {"action": "notify", "token": env("NOTIFY_TOKEN"), "subject": subject, "html": html_, "text": text}
    try:
        # as plain text, as the website does: Apps Script answers with a redirect to the reply,
        # which requests follows with a GET (the token is not sent again)
        r = requests.post(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), timeout=90,
                          headers={"Content-Type": "text/plain;charset=utf-8"})
    except requests.RequestException as ex:
        raise NotifyError(f"The Google connector could not be reached ({type(ex).__name__}). "
                          "Check config.yaml assistant: endpoint.") from None
    try:
        j = r.json()
    except ValueError:
        j = None
    if r.status_code != 200 or not isinstance(j, dict):
        page = "a web page" if "html" in r.headers.get("Content-Type", "") else "an unexpected reply"
        raise NotifyError(f"The Google connector answered HTTP {r.status_code} with {page} instead of its JSON reply. "
                          "Check that config.yaml assistant: endpoint is the web app's /exec address and that the "
                          "deployment has Execute as: Me and Who has access: Anyone.")
    if j.get("ok"):
        n = j.get("sent_to")
        return "sent by the Google connector" + (f" to {plural(n, 'recipient')}" if isinstance(n, int) else "")
    err = str(j.get("error") or "no reason given")
    if err in ("passcode", "Empty question."):  # an older bridge.gs, which only answers questions
        raise NotifyError("The Google connector does not send e-mail yet: paste the new assistant/bridge.gs into its "
                          "Apps Script project, run testEmail once, and deploy a new version "
                          "(Deploy → Manage deployments → Edit → Version: New version).")
    raise NotifyError(f"The Google connector did not send the e-mail: {mask(err)[:300]}")


def setup_help(cfg):
    """How to set e-mail up, for the log, naming what is missing."""
    lines = ["To send e-mail, set up one of these (see the header of notify.py):"]
    if site_builder.assistant_endpoint(cfg):
        lines.append("  - The Google connector (the AI assistant's, already deployed): in its Apps Script project paste the "
                     "new assistant/bridge.gs, add the Script property NOTIFY_TOKEN (a long random text) and, if you like, "
                     "MAIL_TO (addresses separated by commas; empty sends to your own address), run testEmail once and "
                     "deploy a new version. Then add the same text as the GitHub secret NOTIFY_TOKEN "
                     "(Settings → Secrets and variables → Actions). The secret NOTIFY_TOKEN is missing now.")
    else:
        lines.append("  - The Google connector: deploy assistant/bridge.gs (README, \"AI assistant\"), put its address in "
                     "config.yaml under assistant: endpoint, and give the script and GitHub the same NOTIFY_TOKEN.")
    lines.append("  - A mail server: the GitHub secrets SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD and MAIL_TO.")
    return "\n".join(lines)


def deliver(subject, html_, cfg):
    """Send by the first channel that is set up. (True, status) once sent; (False, status) when
    e-mail is not set up (the log then shows the e-mail); NotifyError when sending failed."""
    subject = " ".join(str(subject).split())[:200]
    text = html_to_text(html_)
    kind = channel(cfg)
    if kind == "smtp":
        return True, send_smtp(subject, html_, text)
    if kind == "connector":
        return True, send_connector(subject, html_, text, cfg)
    print("E-mail is not set up, so nothing was sent. This e-mail would have gone out:")
    print(f"  Subject: {subject}")
    body = text if len(text) <= 6000 else text[:6000].rstrip() + "\n[… shortened for the log]"
    print("  " + body.replace("\n", "\n  "))
    print(setup_help(cfg))
    annotate("warning", "E-mail is not set up, so nothing was sent; the log shows what would have gone out and how to set it up.")
    return False, "not sent: e-mail is not set up"


def send(subject, html, cfg):
    """Send an e-mail by the first channel that is set up (mail server, then the Google
    connector); the status text for the log. Raises NotifyError when sending failed."""
    return deliver(subject, html, cfg)[1]


def annotate(level, text):
    """Show a message on the GitHub run's page as well as in its log (warning or error)."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::{level} title=E-mail::" + mask(text).replace("%", "%25").replace("\n", "%0A"))


class _Text(HTMLParser):
    """Plain-text version of an e-mail, for mail programs that do not show HTML: one line per block,
    a blank line around headings, paragraphs and the items marked class='m-gap'."""
    PARA = {"p", "h1", "h2", "h3", "table"}
    LINE = {"div", "li", "tr", "ul", "ol"}
    SKIP = {"style", "script", "head", "title"}
    VOID = {"br", "meta", "img", "hr", "link"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.links, self.stack = [], 0, [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in self.VOID:
            if tag == "br":
                self.out.append("\n")
            return
        mark = "\x00" if tag in self.PARA or "m-gap" in (a.get("class") or "") else "\n" if tag in self.LINE else ""
        self.stack.append((tag, mark))
        if tag in self.SKIP:
            self.skip += 1
        self.out.append(mark)
        if tag == "li":
            self.out.append("- ")
        elif tag in ("td", "th"):
            self.out.append("\x01")  # a cell: " | " between cells
        elif tag == "a":
            self.links.append((a.get("href") or "", len(self.out)))

    def handle_endtag(self, tag):
        if not any(name == tag for name, _ in self.stack):
            return  # <br/>, <img/> or a stray end tag: nothing to close
        while self.stack:
            name, mark = self.stack.pop()
            if name in self.SKIP:
                self.skip = max(0, self.skip - 1)
            if name == "a" and self.links:
                href, start = self.links.pop()
                label = "".join(self.out[start:]).strip()
                if href.startswith("http") and href != label:
                    self.out.append(f" <{href}>")
            self.out.append(mark)
            if name == tag:
                break

    def handle_data(self, data):
        if not self.skip:
            self.out.append(re.sub(r"\s+", " ", data))


def html_to_text(html_):
    p = _Text()
    p.feed(html_)
    p.close()
    text = re.sub(r"[ \t]*([\n\x00])[ \t]*", r"\1", "".join(p.out))
    text = re.sub(r"[\n\x00]+", lambda m: "\n\n" if "\x00" in m.group() else "\n", text)
    lines = (re.sub(r"\s*\x01\s*", " | ", " ".join(line.split())).strip(" |") for line in text.splitlines())
    return "\n".join(lines).strip()


# ------------------------------------------------------------------ other modules (optional)
def optional(module, name, *args, **kw):
    """module.name(*args) from another feature module, or None when it is missing or fails:
    its section is then left out, and the e-mail or page is still made."""
    try:
        mod = __import__(module)
        fn = getattr(mod, name, None)
        return fn(*args, **kw) if callable(fn) else None
    except Exception as ex:  # another module's fault must not stop an e-mail
        warn_once(f"Weekly summary: {module}.{name} failed ({type(ex).__name__}: {ex}); that section is left out.")
        return None


def country_name(code):
    """English name of an ISO country code (the world map's list when it has one); "" for none or a code
    that is not one (as scanner.country_code: "UK" is GB, "XX" and "ZZ" mean unknown)."""
    code = str(code or "").strip().upper()
    code = {"UK": "GB", "EL": "GR"}.get(code, code)
    if not re.match(r"^[A-Z]{2}$", code) or code in ("XX", "ZZ"):
        return ""
    name = optional("geomap", "country_name", code)
    return name or site_builder.COUNTRIES.get(code, code)


def mapped(code):
    """The world map's code for a story's country; "" when the map knows no such country (a global
    story, or an answer such as "EU"), which the map counts as global."""
    found = optional("geomap", "canonical", code)
    return str(code or "") if found is None else found


def where(s):
    """'Moniquirá, Boyacá, Colombia' from the place and country Claude read in the story."""
    place, country = str(s.get("place") or "").strip(), country_name(s.get("country"))
    if country and country.lower() in place.lower():
        country = ""
    return ", ".join(x for x in (place, country) if x)


def headline(s):
    return s.get("title_en") or s.get("title") or ""


def primary(s):
    """Whom to check the story's facts with, as Claude named it ("" when it named none)."""
    return " ".join(str(s.get("primary_source") or "").split())


def story_day(s):
    return (s.get("published") or s.get("_digest") or "")[:10]


def line_key(s):
    """The developing story a story belongs to (its own id when it is a first report)."""
    sl = s.get("storyline")
    return sl if isinstance(sl, str) and sl.startswith("sl-") else "sl-" + str(s.get("id", ""))


def by_rank(items):
    return sorted(items, key=lambda s: (-(s.get("relevance") or 0), -(s.get("rank") or 0)))


# ------------------------------------------------------------------ the weekly summary
def pick_top(stories, limit):
    """The week's best stories spread across the themes: the best story of each theme in turn (the
    theme with the strongest story first), one story per developing story."""
    ranked = by_rank(stories)
    queues, order = {}, []
    for s in ranked:
        t = s.get("theme") or "General"
        if t not in queues:
            queues[t] = []
            order.append(t)
        queues[t].append(s)
    out, lines = [], set()
    while len(out) < limit and any(queues.values()):
        for t in order:
            while queues[t]:
                s = queues[t].pop(0)
                if line_key(s) in lines:
                    continue
                lines.add(line_key(s))
                out.append(s)
                break
            if len(out) >= limit:
                break
    return out


def week_summary(digests, key, cfg, today=None):
    """Everything the weekly e-mail and page show for an ISO week (key "2026-W43"), from the
    digests (newest first, as site_builder loads them) saved Monday to Sunday of that week."""
    opts = settings(cfg)
    today = today or cairo_today()
    monday, sunday = week_range(key)
    lo, hi = monday.isoformat(), sunday.isoformat()
    sm = site_builder.start_month(cfg)
    known = [d for d in digests if d["date"][:10] <= hi]  # what was known when the week ended
    days = sorted((d for d in known if d["date"][:10] >= lo), key=lambda d: d["date"])
    stories, papers, seen = [], [], set()
    for d in days:
        for s in d.get("stories") or []:
            sid = str(s.get("id") or id(s))
            if sid not in seen:
                seen.add(sid)
                stories.append(dict(s, _digest=d["date"][:10]))
        papers += [dict(p, _digest=d["date"][:10]) for p in d.get("papers") or []]
    limit = opts["max_stories"]
    top = pick_top(stories, limit)
    shown = {id(s) for s in top}
    fives = by_rank([s for s in stories if s.get("relevance") == 5])
    more5 = [s for s in fives if id(s) not in shown]

    order = list(site_builder.theme_order(cfg))
    themes = {}
    for s in stories:
        themes[s.get("theme") or "General"] = themes.get(s.get("theme") or "General", 0) + 1
    order += sorted(t for t in themes if t not in order)

    developing = None
    groups = optional("storylines", "groups", known) if days else []
    if groups is not None:
        developing = []
        for g in groups:
            new = [s for s in g.get("stories") or [] if lo <= str(s.get("_digest", ""))[:10] <= hi]
            if not new:
                continue
            latest = new[-1]
            developing.append({"id": g.get("id", ""), "title": g.get("title") or headline(latest),
                               "country": g.get("country", ""), "place": g.get("place", ""),
                               "theme": g.get("theme") or latest.get("theme") or "General",
                               "first": g.get("first", ""), "last": g.get("last", ""),
                               "reports": len(g.get("stories") or []), "new": len(new),
                               "stage": latest.get("stage") or ("Event" if len(new) == len(g.get("stories") or []) else "Update"),
                               "latest": latest})
        developing.sort(key=lambda g: (g["new"], g["last"]), reverse=True)  # most reports this week first

    regions = optional("geomap", "coverage", stories, cfg) if stories else None
    located = sum(1 for s in stories if "country" in s)
    global_ = sum(1 for s in stories if "country" in s and not mapped(s.get("country")))

    send_on = send_day(key, opts)
    ref = min(send_on, today) if sunday < today else today  # events as they stood when the summary went out
    events = optional("events", "upcoming", cfg, ref, days=opts["events_days"])
    deadlines = optional("events", "deadlines", cfg, ref, days=opts["events_days"])

    windows = []  # the issue windows of the week's digests (a window without digests has no issue page)
    for d in sorted({d["date"][:10] for d in days}):
        win = site_builder.issue_window(d, sm)
        if win["key"] not in [w["key"] for w in windows]:
            windows.append(win)
    ranked_papers = sorted(papers, key=lambda p: -site_builder.paper_rank(p))
    return {
        "key": key, "label": week_label(key), "week": int(key[-2:]), "year": int(key[:4]),
        "span": span_text(monday, sunday), "monday": lo, "sunday": hi,
        "in_progress": sunday >= today, "send_on": send_on.isoformat(), "events_from": ref.isoformat(),
        "digests": [{"date": d["date"][:10], "stories": len(d.get("stories") or [])} for d in days],
        "figures": {"stories": len(stories), "rated": sum(1 for s in stories if s.get("relevance")),
                    "top": len(fives), "papers": len(papers), "digests": len(days), "themes": len(themes)},
        "themes": [(t, themes[t]) for t in order if t in themes],
        "top": top, "more5": more5[:limit], "more5_hidden": max(0, len(more5) - limit),
        "developing": None if developing is None else developing[:limit],
        "developing_hidden": 0 if developing is None else max(0, len(developing) - limit),
        "regions": regions, "located": located, "global": global_,
        "events": None if events is None else list(events)[:limit],
        "deadlines": None if deadlines is None else list(deadlines)[:limit],
        "papers": ranked_papers[:3], "papers_total": len(papers),
        "windows": windows, "events_days": opts["events_days"],
    }


def coverage_note(W):
    """What follows "Stories this week by ISSMGE region …", and whether member-society countries can be
    marked as gaps: only from stories located in a country, as on the world map."""
    waiting, in_country = W["figures"]["stories"] - W["located"], W["located"] - W["global"]
    note = ((f" {plural(W['global'], 'story is', 'stories are')} global or about several countries." if W["global"] else "")
            + (f" {plural(waiting, 'story has', 'stories have')} no location yet." if waiting else ""))
    if not in_country:
        note += " No story is located in a country yet, so no member-society country is marked as a gap."
    elif waiting:
        note += " Member-society countries are marked as gaps only from the stories already located."
    return note, in_country > 0


# ------------------------------------------------------------------ e-mail (inline styles, as render_email)
FONT, SERIF = "Arial,Helvetica,sans-serif", "Georgia,serif"  # no quotes: they sit in style='...'
INK, MUTED, BRAND, GOLD, LINE, SOFT, LINK = "#1b2430", "#5b6573", "#16324f", "#9a7b1c", "#e2e7ee", "#f6f8fb", "#1f5fa8"


def m_h2(text, color=BRAND):
    return (f"<h2 style='font:600 16px {FONT};color:{color};border-bottom:2px solid #e0b13a;padding-bottom:5px;"
            f"margin:28px 0 10px'>{text}</h2>")


def m_p(text, size=13, color=MUTED, margin="0 0 10px"):
    return f"<p style='font:{size}px/1.5 {FONT};color:{color};margin:{margin}'>{text}</p>"


def m_link(url, text, color=LINK, weight=400):
    return f"<a href='{esc(url)}' style='color:{color};font-weight:{weight}'>{text}</a>"


def event_dates(e):
    """'12–15 Nov 2026', 'Nov 2026' (month only) or '30 Nov 2026'."""
    def one(text):
        text = str(text or "")
        if re.match(r"^\d{4}-\d{2}$", text):
            return f"{MONTHS[int(text[5:7]) - 1]} {text[:4]}"
        try:
            return short_date(dt.date.fromisoformat(text[:10]))
        except ValueError:
            return text
    start, end = str(e.get("start") or ""), str(e.get("end") or "")
    if not end or end == start:
        return one(start)
    if len(start) == len(end) == 10 and start[:7] == end[:7]:
        return f"{int(start[8:10])}–{one(end)}"
    return f"{one(start)} – {one(end)}"


def event_place(e):
    if e.get("online") and not e.get("city"):
        return "Online"
    bits = [str(e.get("city") or ""), country_name(e.get("country"))]
    return ", ".join(b for b in bits if b) + (" and online" if e.get("online") else "")


def m_story(s, url, note=""):
    """One story in an e-mail: theme, headline, original headline, where and when, angle."""
    color = site_builder.theme_color(s.get("theme") or "General")
    rel = s.get("relevance") or 0
    meta = [f"<b style='color:{INK}'>{rel}/5</b>" if rel else "Keyword-ranked", esc(s.get("use") or ""),
            esc(s.get("source") or ""), esc(site_builder.nice_date(story_day(s)))]
    place = where(s)
    if place:
        meta.append(esc(place))
    parts = [f"<div class='m-gap' style='margin:0 0 16px;padding:0 0 0 12px;border-left:3px solid {color}'>",
             f"<div style='font:700 11px {FONT};letter-spacing:.06em;text-transform:uppercase;color:{color}'>"
             f"{esc(s.get('theme') or 'General')}</div>",
             f"<a href='{esc(site_builder.safe_url(s.get('link')))}' dir='auto' style='font:600 15px/1.4 {FONT};color:{INK}'>"
             f"{esc(headline(s))}</a>"]
    if s.get("title_en"):
        parts.append(f"<div style='font:13px {FONT};color:{MUTED};margin-top:2px'>{site_builder.TRANSLATED} · Original: "
                     f"<span dir='auto'>{esc(s.get('title') or '')}</span></div>")
    parts.append(f"<div style='font:12px {FONT};color:{MUTED};margin-top:3px'>{' · '.join(m for m in meta if m)}</div>")
    if s.get("angle"):  # Claude's own words; the publisher's text is never sent
        parts.append(f"<div style='font:italic 14px/1.5 {SERIF};color:#333;margin-top:5px'>{esc(s['angle'])}</div>")
    if primary(s):
        parts.append(f"<div style='font:12.5px/1.5 {FONT};color:{INK};margin-top:4px'><b>Check with:</b> {esc(primary(s))}</div>")
    if note:
        parts.append(f"<div style='font:12.5px/1.5 {FONT};color:{INK};background:{SOFT};border:1px solid {LINE};"
                     f"border-radius:6px;padding:6px 9px;margin-top:7px'>{note}</div>")
    if url and s.get("_digest"):
        parts.append(f"<div style='font:12px {FONT};margin-top:5px'>"
                     + m_link(f"{url}digests/{s['_digest']}.html", f"Open the {esc(site_builder.nice_date(s['_digest']))} digest")
                     + "</div>")
    parts.append("</div>")
    return "".join(parts)


def m_shell(eyebrow, title, sub, body, cfg, why):
    url = site_builder.site_url(cfg)
    home = (f" · {m_link(url + 'index.html', 'Website', MUTED)}" if url else "")
    return ("<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta name='color-scheme' content='light'><meta name='supported-color-schemes' content='light'></head>"
            "<body style='margin:0;padding:0;background:#f4f5f3'>"
            "<div style='max-width:680px;margin:0 auto;background:#ffffff;padding:24px 26px 20px'>"
            f"<div style='font:600 12px {FONT};letter-spacing:.08em;text-transform:uppercase;color:{GOLD}'>{eyebrow}</div>"
            f"<h1 style='font:600 24px/1.25 {SERIF};color:{BRAND};margin:4px 0 6px'>{title}</h1>"
            f"<div style='font:13px/1.5 {FONT};color:{MUTED}'>{sub}</div>"
            f"{body}"
            f"<div style='border-top:1px solid {LINE};margin-top:28px;padding-top:12px;font:11.5px/1.5 {FONT};color:{MUTED}'>"
            f"{why} Ratings, themes and angles are machine-assisted suggestions: check every story at its source before "
            f"publishing.{home}</div></div></body></html>")


def follow_up_note(s, url, groups_by_id):
    """'Follows up an earlier report' for a story Claude linked to a developing story."""
    sl, title = s.get("storyline"), s.get("storyline_title")
    if not (isinstance(sl, str) and sl.startswith("sl-")):
        return ""
    g = groups_by_id.get(sl) or {}
    bits = ["<b>Developing story</b>: follows up an earlier report"
            + (f" on <i>{esc(title)}</i>" if title else "")]
    if s.get("stage"):
        bits.append(f"stage: {esc(s['stage'])}")
    if g.get("first"):
        bits.append(f"first reported {esc(site_builder.nice_date(g['first']))}")
    if g.get("stories"):
        bits.append(plural(len(g["stories"]), "report") + " so far")
    text = " · ".join(bits)
    if url:
        text += " · " + m_link(f"{url}developing.html#{sl}", "Follow it on the website")
    return text


def alert_subject(stories, opts):
    level = "5/5" if opts["min_relevance"] >= 5 else f"{opts['min_relevance']}/5+"
    if len(stories) == 1:
        return f"New {level} story: {headline(stories[0])}"[:180]
    return f"{len(stories)} new {level} stories"


def render_alert(stories, cfg, digests=(), opts=None):
    """(subject, html) of the alert for new top-rated stories (one e-mail per scan)."""
    opts = opts or settings(cfg)
    url = site_builder.site_url(cfg)
    groups = optional("storylines", "groups", list(digests)) if any(s.get("storyline") for s in stories) else None
    by_id = {g.get("id"): g for g in groups or []}
    level = "5 / 5" if opts["min_relevance"] >= 5 else f"{opts['min_relevance']} / 5 or higher"
    days = sorted({s["_digest"] for s in stories if s.get("_digest")})
    body = [m_p(f"Claude rated {'this story' if len(stories) == 1 else 'these stories'} {level} for geotechnical "
                f"relevance in the {' and '.join(esc(site_builder.nice_date(d)) for d in days)} "
                f"digest{'s' if len(days) > 1 else ''}.", 14, INK, "18px 0 18px")]
    body += [m_story(s, url, follow_up_note(s, url, by_id)) for s in stories]
    if url:
        links = ([m_link(f"{url}digests/{days[-1]}.html", "Open the latest digest", LINK, 600)] if days else []) + [
            m_link(url + "developing.html", "Developing stories"), m_link(url + "map.html", "World map"),
            m_link(url + "weekly/index.html", "Weekly summaries")]
        body.append(m_p(" · ".join(links), 13, MUTED, "18px 0 0"))
    body.append(site_builder.use_steps_email(FONT, MUTED, INK, LINE))
    title = "New story rated " + level if len(stories) == 1 else f"{len(stories)} new stories rated {level}"
    html_ = m_shell(f"Geotechnical News Desk · new {level} {'story' if len(stories) == 1 else 'stories'}", title,
                    esc(site_builder.nice_date(days[-1], weekday=True)) if days else "", "".join(body), cfg,
                    "You receive this alert because your address is in the news desk's e-mail settings; the "
                    f"{opts['weekday']} summary lists the whole week.")
    return alert_subject(stories, opts), html_


def figures_cells(F):
    cells = [(F["stories"], "stories"), (F["rated"], "AI-rated"), (F["top"], "rated 5 / 5"),
             (F["papers"], "papers"), (F["digests"], "digests")]  # one-line labels keep the tiles even on phones
    return "".join(f"<div style='display:inline-block;vertical-align:top;width:92px;margin:0 6px 6px 0;padding:8px 9px;"
                   f"background:{SOFT};border:1px solid {LINE};border-radius:8px'>"
                   f"<span style='display:block;font:700 21px {SERIF};color:{BRAND}'>{v:,}</span> "
                   f"<span style='display:block;font:600 10px/1.3 {FONT};letter-spacing:.04em;text-transform:uppercase;color:{MUTED}'>"
                   f"{esc(label)}</span></div>" for v, label in cells)


def week_subject(W):
    F = W["figures"]
    if not F["digests"]:
        return f"Weekly summary · week {W['week']} ({W['span']}): no digests"
    return (f"Weekly summary · week {W['week']} ({W['span']}): {plural(F['stories'], 'story', 'stories')}, "
            f"{F['top']} rated 5/5")


def render_week_email(W, cfg):
    """(subject, html) of the weekly summary e-mail."""
    url = site_builder.site_url(cfg)
    F = W["figures"]
    body = [f"<div style='margin:16px 0 0'>{figures_cells(F)}</div>"] if F["digests"] else []
    if W["themes"]:
        body.append(m_p("By theme: " + " · ".join(
            f"<span style='color:{site_builder.theme_color(t)};font-weight:600'>{esc(t)}</span> {n}" for t, n in W["themes"]),
            12.5, MUTED, "6px 0 0"))
    if url:  # the website has a page for every week with digests
        body.append(m_p(m_link(f"{url}weekly/{W['key']}.html", "Open this summary on the website", LINK, 600) if F["digests"]
                        else m_link(f"{url}weekly/index.html", "All weekly summaries on the website", LINK, 600), 13, MUTED, "12px 0 0"))
    if not F["digests"]:
        repo = site_builder.repository(cfg)
        body.append(m_p("No daily digests were saved this week, so the scans may not have run. "
                        + (m_link(f"https://github.com/{repo}/actions/workflows/scan.yml", "Check the scan's runs on GitHub")
                           if "/" in repo else "Check the scan's runs on GitHub (Actions)") + ".", 14, INK, "18px 0 0"))
    if W["top"]:
        body.append(m_h2("Top stories of the week"))
        body.append(m_p("The best-rated story of each theme in turn, with the magazine angle Claude suggests."))
        body += [m_story(s, url) for s in W["top"]]
    if W["more5"]:
        body.append(m_h2("Also rated 5 / 5"))
        body += [f"<div class='m-gap' style='font:13.5px/1.45 {FONT};margin:0 0 8px'>"
                 f"<a href='{esc(site_builder.safe_url(s.get('link')))}' dir='auto' style='color:{INK};font-weight:600'>{esc(headline(s))}</a>"
                 f"<div style='font:12px {FONT};color:{MUTED}'>{esc(s.get('source') or '')} · "
                 f"{esc(site_builder.nice_date(story_day(s)))} · "
                 f"<span style='color:{site_builder.theme_color(s.get('theme') or 'General')}'>{esc(s.get('theme') or 'General')}</span>"
                 + (f" · {esc(where(s))}" if where(s) else "") + (f" · Check with: {esc(primary(s))}" if primary(s) else "")
                 + "</div></div>" for s in W["more5"]]
        if W["more5_hidden"]:
            body.append(m_p(f"…and {plural(W['more5_hidden'], 'more story', 'more stories')} rated 5 / 5 in the week's digests."))
    if W["developing"]:
        body.append(m_h2("Developing stories updated this week"))
        for g in W["developing"]:
            place = ", ".join(x for x in (g["place"], country_name(g["country"])) if x)
            head = (m_link(f"{url}developing.html#{g['id']}", esc(g["title"]), INK, 600) if url
                    else f"<b style='color:{INK}'>{esc(g['title'])}</b>")
            body.append(f"<div class='m-gap' style='font:13.5px/1.45 {FONT};margin:0 0 9px'>{head}<div style='font:12px {FONT};color:{MUTED}'>"
                        + " · ".join(x for x in (esc(place), f"{plural(g['reports'], 'report')}, {g['new']} this week",
                                                 f"latest: {esc(g['stage'])}") if x)
                        + "</div></div>")
        if W["developing_hidden"]:
            body.append(m_p(f"…and {W['developing_hidden']} more on the Developing stories page."))
    if W["regions"]:
        body.append(m_h2("Regional coverage"))
        note, known = coverage_note(W)
        body.append(m_p("Stories this week by ISSMGE region, and the member societies whose countries had none." + note))
        rows = []
        for r in W["regions"]:
            gaps = [country_name(c) for c in r.get("gaps") or []]
            gap_text = (", ".join(gaps[:6]) + (f" and {len(gaps) - 6} more" if len(gaps) > 6 else "")) or "—"
            rows.append(f"<tr><td style='padding:6px 8px;border-bottom:1px solid {LINE};font-weight:600;color:{INK}'>{esc(r['region'])}</td>"
                        f"<td style='padding:6px 8px;border-bottom:1px solid {LINE};text-align:right'>{r['stories']}</td>"
                        f"<td style='padding:6px 8px;border-bottom:1px solid {LINE};text-align:right'>"
                        f"{r['members_covered'] if known else '–'} of {r['members']}</td>"
                        f"<td style='padding:6px 8px;border-bottom:1px solid {LINE};color:{MUTED}'>"
                        f"{esc(gap_text) if known else 'Shown once stories are located'}</td></tr>")
        body.append(f"<table role='presentation' cellspacing='0' cellpadding='0' style='width:100%;border-collapse:collapse;"
                    f"font:12.5px/1.4 {FONT};color:{INK}'><tr style='background:{SOFT};color:{MUTED};font-size:11px;text-transform:uppercase'>"
                    "<th style='padding:6px 8px;text-align:left'>Region</th><th style='padding:6px 8px;text-align:right'>Stories</th>"
                    "<th style='padding:6px 8px;text-align:right'>Member societies covered</th>"
                    "<th style='padding:6px 8px;text-align:left'>No stories from</th></tr>" + "".join(rows) + "</table>")
        if url:
            body.append(m_p(m_link(url + "map.html", "See every story on the world map"), 12.5, MUTED, "8px 0 0"))
    if W["events"] or W["deadlines"]:
        body.append(m_h2(f"Coming up in the next {W['events_days']} days"))
        for e in W["events"] or []:
            name = esc(e.get("name") or e.get("short") or "")
            link = site_builder.safe_url(e.get("url"))
            body.append(f"<div class='m-gap' style='font:13.5px/1.45 {FONT};margin:0 0 8px'><b style='color:{BRAND}'>{esc(event_dates(e))}</b> · "
                        + (m_link(link, name, INK, 600) if link != "#" else f"<b>{name}</b>")
                        + f"<div style='font:12px {FONT};color:{MUTED}'>"
                        + " · ".join(x for x in (esc(event_place(e)), esc(e.get("kind") or "")) if x) + "</div></div>")
        if W["deadlines"]:
            body.append(m_p("<b style='color:#8a5a00'>Deadlines</b>", 13, INK, "12px 0 6px"))
            for x in W["deadlines"]:
                ev = x.get("event") or {}
                body.append(f"<div style='font:13px/1.45 {FONT};margin:0 0 6px'><b style='color:#8a5a00'>"
                            f"{esc(event_dates({'start': x.get('date')}))}</b> · {esc(x.get('label') or 'Deadline')} — "
                            f"{esc(ev.get('short') or ev.get('name') or '')}</div>")
        if url:
            body.append(m_p(m_link(url + "events.html", "The whole events calendar"), 12.5, MUTED, "8px 0 0"))
    if W["papers"]:
        body.append(m_h2("New research"))
        body.append(m_p(f"The best-rated of the week's {plural(W['papers_total'], 'paper')} for use in practice "
                        "(Academia-to-Industry)."))
        for p in W["papers"]:
            rel = f"{p['relevance']}/5 for practice · " if p.get("relevance") else ""
            body.append(f"<div class='m-gap' style='margin:0 0 13px'>"
                        f"<a href='{esc(site_builder.safe_url(p.get('link')))}' style='font:600 14.5px/1.4 {FONT};color:{INK}'>{esc(p.get('title') or '')}</a>"
                        f"<div style='font:12px {FONT};color:{MUTED};margin-top:2px'>{rel}{esc(p.get('journal') or '')}"
                        f"{' · ' + esc(p['authors']) if p.get('authors') else ''}</div>"
                        + (f"<div style='font:italic 14px/1.5 {SERIF};color:#333;margin-top:4px'>{esc(p['angle'])}</div>" if p.get("angle") else "")
                        + "</div>")
    if url and F["digests"]:
        days = " · ".join(m_link(f"{url}digests/{d['date']}.html", f"{dt.date.fromisoformat(d['date']):%a} "
                                 f"{int(d['date'][8:10])}") for d in W["digests"])
        wins = " · ".join(m_link(f"{url}issues/{w['key']}.html", f"{esc(w['label'])} issue window") for w in W["windows"])
        body.append(m_h2("On the website"))
        body.append(m_p(f"Daily digests: {days}", 13, INK, "0 0 6px"))
        body.append(m_p(f"{wins} · {m_link(url + 'developing.html', 'Developing stories')} · "
                        f"{m_link(url + 'map.html', 'World map')} · {m_link(url + 'events.html', 'Events')} · "
                        f"{m_link(url + 'weekly/index.html', 'All weekly summaries')}", 13, INK))
    if F["digests"]:
        body.append(site_builder.use_steps_email(FONT, MUTED, INK, LINE))
    sub = "The week's geotechnical news for the editorial team" + (" (so far: the week is not over)" if W["in_progress"] else "")
    html_ = m_shell("Geotechnical News Desk · weekly summary", f"Week {W['week']}: {esc(W['span'])}", esc(sub),
                    "".join(body), cfg, "You receive this summary every week because your address is in the news desk's "
                    "e-mail settings.")
    return week_subject(W), html_


# ------------------------------------------------------------------ what --auto sends
def new_alerts(digests, rec, today, opts):
    """Top-rated stories of the digests from today and yesterday (Cairo; a scan just after midnight
    files under the UTC date) that have not been alerted yet, best first."""
    lo = (today - dt.timedelta(days=1)).isoformat()
    out, seen = [], set(rec["alerted"])
    for d in digests:
        if not lo <= d["date"][:10] <= today.isoformat():
            continue
        for s in d.get("stories") or []:
            sid = str(s.get("id") or "")
            if sid and sid not in seen and (s.get("relevance") or 0) >= opts["min_relevance"]:
                seen.add(sid)
                out.append(dict(s, _digest=d["date"][:10]))
    return by_rank(out)


def weekly_due(today, opts, rec, digests=None):
    """(week key, "") when the weekly summary is due today, else (None, why not). digests: the archive, so
    a missed week without digests is not offered to --weekly."""
    key = last_week(today)
    nxt = send_day(week_key(today), opts)
    if key in rec["weekly"]:
        return None, (f"the summary of {week_label(key).lower()} was sent on {when_sent(rec['weekly'][key]) or rec['weekly'][key]}; "
                      f"the next one goes out on {nxt:%A} {short_date(nxt)}")
    day = send_day(key, opts)
    if today < day:
        return None, f"it goes out on {day:%A} {short_date(day)}"
    if (today - day).days > opts["catch_up_days"]:
        monday, sunday = week_range(key)
        if digests is not None and not any(monday.isoformat() <= d["date"][:10] <= sunday.isoformat() for d in digests):
            return None, f"the next summary, of {week_label(week_key(today)).lower()}, goes out on {nxt:%A} {short_date(nxt)}"
        return None, (f"the summary of {week_label(key).lower()} was due on {day:%A} {short_date(day)}, more than "
                      f"{plural(opts['catch_up_days'], 'day')} ago (--weekly sends it now); the next one goes out on "
                      f"{nxt:%A} {short_date(nxt)}")
    return key, ""


def try_send(label, subject, html_, cfg, level):
    """Send one e-mail; True once sent. A failure is printed (and shown on the run's page)."""
    try:
        sent, status = deliver(subject, html_, cfg)
    except NotifyError as ex:
        print(f"{label}: not sent: {mask(ex)}")
        annotate(level, f"{label} not sent: {ex}")
        return None
    print(f"{label}: {status}.")
    return sent


def week_arg(text):
    key = text.strip().upper()
    try:
        week_range(key)
    except ValueError as ex:
        raise argparse.ArgumentTypeError(str(ex)) from None
    return key


def main(argv=None, now=None):
    ap = argparse.ArgumentParser(description="E-mail alerts for new 5/5 stories and the weekly summary.")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--auto", action="store_true", help="after a scan: alerts, and the weekly summary when it is due")
    mode.add_argument("--weekly", action="store_true", help="send last week's summary now")
    mode.add_argument("--test", action="store_true", help="send a short test e-mail")
    ap.add_argument("--week", type=week_arg, help="with --weekly: the week to send, e.g. 2026-W43 (default: last week)")
    ap.add_argument("--today", type=dt.date.fromisoformat, help="act as on this day (YYYY-MM-DD, Cairo), for testing")
    args = ap.parse_args(argv)
    if args.week and not args.weekly:
        ap.error("--week goes with --weekly")
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    opts = settings(cfg)
    today = args.today or cairo_today(now)
    rec = load_record()
    kind = channel(cfg)
    print(f"E-mail channel: {channel_name(kind) or 'none set up'}; today in Cairo: {today:%A} {today.isoformat()}.")

    if args.test:
        sent_at = dt.datetime.now(dt.timezone.utc).astimezone(CAIRO)
        url = site_builder.site_url(cfg)
        body = (m_p(f"This is a test e-mail from the Geotechnical News Desk, sent by <b>{esc(channel_name(kind) or 'no channel')}"
                    f"</b> on {sent_at:%A} {short_date(sent_at.date())} at {sent_at:%H:%M} (Cairo time).", 14, INK, "18px 0 10px")
                + m_p("E-mail works: alerts for new 5/5 stories (after the daily scan) and the weekly summary "
                      f"(on {opts['weekday']}s) will arrive the same way. No reply is needed.", 14, INK)
                + (m_p(m_link(url + "weekly/index.html", "Weekly summaries on the website")) if url else ""))
        sent = try_send("Test e-mail", "Geotechnical News Desk: test e-mail",
                        m_shell("Geotechnical News Desk · test", "E-mail is working", "", body, cfg,
                                "You receive this because someone ran the test from the news desk's workflow."), cfg, "error")
        return 0 if sent else 1  # nothing sent (failed, or e-mail not set up): the run fails

    digests = site_builder.load_digests()
    failed, changed = False, False
    if args.weekly:
        key = args.week or last_week(today)
        W = week_summary(digests, key, cfg, today=today)
        subject, html_ = render_week_email(W, cfg)
        sent = try_send(f"Weekly summary of {week_label(key).lower()}", subject, html_, cfg, "error")
        if sent:
            rec["weekly"][key] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
            save_record(rec, today)
        return 0 if sent else 1  # as --test: the website's Send summary now must not report an e-mail that did not go

    # --auto: (1) one alert for the new top-rated stories
    if not opts["story_alerts"]:
        print("Alerts: switched off in config.yaml (alerts: story_alerts: false).")
    elif not digests:
        print("Alerts: the archive is empty.")
    else:
        stories = new_alerts(digests, rec, today, opts)
        if not stories:
            print(f"Alerts: no new stories rated {opts['min_relevance']}/5 or higher in the digests of "
                  f"{short_date(today - dt.timedelta(days=1))} and {short_date(today)}.")
        else:
            subject, html_ = render_alert(stories, cfg, digests, opts)
            sent = try_send(f"Alert for {plural(len(stories), 'story', 'stories')}", subject, html_, cfg, "warning")
            failed |= sent is None
            if sent:
                for s in stories:
                    rec["alerted"][str(s["id"])] = today.isoformat()
                changed = True
    # (2) the whole daily digest, when the editors asked for it
    lo = (today - dt.timedelta(days=1)).isoformat()
    d = next((d for d in digests if lo <= d["date"][:10] <= today.isoformat()), None)  # newest of today and yesterday
    if opts["daily_digest"] and d:
        mark = f"digest:{d['date'][:10]}"
        if d.get("stories") and mark not in rec["alerted"]:
            day = dt.date.fromisoformat(d["date"][:10])
            sent = try_send("Daily digest", f"Geotechnical News Digest — {day:%d %b %Y} ({len(d['stories'])} stories)",
                            site_builder.render_email(d, cfg), cfg, "warning")
            failed |= sent is None
            if sent:
                rec["alerted"][mark] = today.isoformat()
                changed = True
    # (3) the weekly summary, on its day
    if not opts["weekly_summary"]:
        print("Weekly summary: switched off in config.yaml (alerts: weekly_summary: false).")
    else:
        key, why = weekly_due(today, opts, rec, digests)
        if not key:
            print(f"Weekly summary: not due today: {why}.")
        else:
            W = week_summary(digests, key, cfg, today=today)
            subject, html_ = render_week_email(W, cfg)
            sent = try_send(f"Weekly summary of {week_label(key).lower()}", subject, html_, cfg, "warning")
            failed |= sent is None
            if sent:
                rec["weekly"][key] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
                changed = True
    if changed:
        save_record(rec, today)
    return 1 if failed else 0


# ------------------------------------------------------------------ web pages (docs/weekly/)
def status_text(W, rec, opts):
    """(chip class, chip text, sentence) on the e-mail of a week; ("", "", "") when there is nothing to say
    (an older week that was not e-mailed, perhaps from before e-mail was set up). The pages are rebuilt
    after the morning scan, so on the day the summary is due it has normally gone out already."""
    sent = rec["weekly"].get(W["key"])
    if sent:
        return "ok", "E-mailed", f"E-mailed to the editorial team on {when_sent(sent)}."
    on, today = opts["weekly_summary"], cairo_today()
    day = dt.date.fromisoformat(W["send_on"])
    last = day + dt.timedelta(days=opts["catch_up_days"])  # the last day the scan tries to send it
    if W["in_progress"]:
        return "", "In progress", (f"The week is not over yet: its summary goes out on {day:%A} {short_date(day)}."
                                   if on else "The week is not over yet.")
    if on and day > today:
        return "", "Due", f"The summary goes out on {day:%A} {short_date(day)}, after the morning scan."
    if on and today <= last:
        return "", "Not sent yet", (f"Due on {day:%A} {short_date(day)} after the morning scan, and not sent yet. If the "
                                    "scan has run, its log on GitHub says why (e-mail may not be set up). "
                                    + (f"The daily scan tries again until {last:%A} {short_date(last)}; " if today < last else "")
                                    + "Send summary now sends it at any time.")
    return "", "", ""


def mail_card(W, rec, opts, last_key):
    """The e-mail status of the week, the Send summary now button and how e-mail is set up."""
    last = f"week {int(last_key[-2:])}, {span_text(*week_range(last_key))}"
    if W and W["key"] == last_key:
        which = f"e-mails this summary ({esc(last)}){' again' if last_key in rec['weekly'] else ''}"
    elif W:
        which = f"e-mails the summary of the last full week ({esc(last)}), not this one"
    else:
        which = f"e-mails the summary of the last full week ({esc(last)})"
    chip, label, sentence = status_text(W, rec, opts) if W else ("", "", "")
    status = (f"<p class='wk-status'><span class='wk-chip {chip}'>{esc(label)}</span>{esc(sentence)}</p>" if label else "")
    level = "5 / 5" if opts["min_relevance"] >= 5 else f"{opts['min_relevance']} / 5 or higher"
    plan = (f"The summary goes out every {opts['weekday']} after the morning scan" if opts["weekly_summary"]
            else "The weekly summary is switched off in config.yaml (alerts: weekly_summary)")
    plan += (f", and an alert follows any scan that finds a new story rated {level}." if opts["story_alerts"]
             else "; alerts for new top-rated stories are switched off (alerts: story_alerts).")
    return (f"<section class='wk-mail' aria-label='E-mail'><div class='wk-mail-head'><span class='brief-mark'>{site_builder.icon('send')}</span>"
            f"<div><p class='eyebrow'>E-mail to the editorial team</p>{status}"
            f"<p class='brief-meta'>{plan} <b>Send summary now</b> {which}, through its workflow on GitHub.</p></div></div>"
            f"<div class='actions'><button type='button' class='btn primary weekly-btn' id='weekly-btn' data-week='{esc(last_key)}'>{site_builder.icon('send')}<span>Send summary now</span></button></div>"
            "<details class='help wk-help'><summary>How e-mail is set up</summary><ol>"
            "<li><b>With the AI assistant's Google connector</b> (no mail server needed): paste the current "
            "<code>assistant/bridge.gs</code> into its Apps Script project, add the Script property <code>NOTIFY_TOKEN</code> "
            "(a long random text) and, if you like, <code>MAIL_TO</code> (addresses separated by commas; empty sends to your own "
            "address). Run <code>testEmail</code> once to allow e-mail, deploy a new version, and add the same text as the "
            "GitHub secret <code>NOTIFY_TOKEN</code>.</li>"
            "<li><b>Or with a mail server:</b> the GitHub secrets <code>SMTP_HOST</code>, <code>SMTP_PORT</code> (587), "
            "<code>SMTP_USER</code>, <code>SMTP_PASSWORD</code> and <code>MAIL_TO</code>.</li>"
            "<li>Check it with the <b>Events calendar and weekly summary</b> workflow on GitHub: choose <b>send a test e-mail</b>. "
            "Settings (which e-mails, the day) are under <code>alerts:</code> in <code>config.yaml</code>.</li></ol></details></section>")


def strip(themes):
    """The theme strip (as site_builder.theme_strip) from (theme, count) pairs."""
    segs = "".join(f"<i style='--tc:{site_builder.theme_color(t)};flex:{n}' title='{esc(t)}: {n}'></i>" for t, n in themes)
    return f"<div class='strip' aria-hidden='true'>{segs}</div>" if themes else ""


def week_list(items):
    return "<ul class='wk-list'>" + "".join(items) + "</ul>"


def week_body(W, cfg, rec, opts, older, newer, last_key):
    root = "../"
    F = W["figures"]
    eyebrow = ("<a href='index.html'>Weekly summaries</a> · "
               + " · ".join(f"<a href='{root}issues/{w['key']}.html'>{esc(w['label'])} issue window</a>" for w in W["windows"])
               + (" · <span class='badge'>In progress</span>" if W["in_progress"] else ""))
    stats = (site_builder.stat(f"{F['stories']:,}", "stories") + site_builder.stat(f"{F['rated']:,}", "AI-rated")
             + site_builder.stat(F["top"], "rated 5 / 5") + site_builder.stat(F["papers"], "research papers")
             + site_builder.stat(F["digests"], "daily digests"))
    lede = ("The week's geotechnical news for the editorial team: top stories, developing stories, regional coverage, "
            "what is coming up and new research. " + esc(status_text(W, rec, opts)[2]))
    out = [site_builder.hero(eyebrow, f"Week {W['week']} <span class='h1-sub'>{esc(W['span'])}</span>", lede, stats, strip(W["themes"]))]
    if not F["digests"]:
        out.append("<p class='empty'>No daily digests were saved in this week.</p>")
    if W["themes"]:
        out.append("<div class='wk-themes'>" + "".join(
            f"<span style='--tc:{site_builder.theme_color(t)}'>{site_builder.theme_icon(t)}{esc(t)} <b>{n}</b></span>"
            for t, n in W["themes"]) + "</div>")
    if W["top"]:
        out.append("<h2 class='section-h'>Top stories of the week</h2><p class='hint'>The best-rated story of each theme in "
                   "turn, with the magazine angle Claude suggests.</p>")
        out += [site_builder.story_card(s, show_theme=True, root=root) for s in W["top"]]
    if W["more5"]:
        out.append("<h2 class='section-h'>Also rated 5 / 5</h2>")
        out.append(week_list(
            f"<li style='--tc:{site_builder.theme_color(s.get('theme') or 'General')}'>"
            f"<a href='{esc(site_builder.safe_url(s.get('link')))}' target='_blank' rel='noopener' dir='auto'>{esc(headline(s))}</a>"
            f"<span class='wk-meta'>{esc(s.get('source') or '')} · {esc(site_builder.nice_date(story_day(s)))} · "
            f"<span class='wk-theme'>{esc(s.get('theme') or 'General')}</span>"
            + (f" · {esc(where(s))}" if where(s) else "") + (f" · Check with: {esc(primary(s))}" if primary(s) else "")
            + "</span></li>" for s in W["more5"]))
        if W["more5_hidden"]:
            out.append(f"<p class='hint wk-more'>…and {plural(W['more5_hidden'], 'more story', 'more stories')} rated 5 / 5 "
                       "in the week's digests below.</p>")
    if W["developing"]:
        out.append("<h2 class='section-h'>Developing stories updated this week</h2>")
        out.append(week_list(
            f"<li style='--tc:{site_builder.theme_color(g['theme'])}'><a href='{root}developing.html#{esc(g['id'])}' dir='auto'>"
            f"{esc(g['title'])}</a><span class='wk-meta'>"
            + " · ".join(x for x in (esc(", ".join(y for y in (g["place"], country_name(g["country"])) if y)),
                                     f"{plural(g['reports'], 'report')}, <b>{g['new']} this week</b>",
                                     f"latest: {esc(g['stage'])}") if x)
            + "</span></li>" for g in W["developing"]))
        if W["developing_hidden"]:
            out.append(f"<p class='hint wk-more'>…and {W['developing_hidden']} more on the "
                       f"<a href='{root}developing.html'>Developing stories</a> page.</p>")
    if W["regions"]:
        notes, known = coverage_note(W)
        rows = []
        for r in W["regions"]:
            gaps = [country_name(c) for c in r.get("gaps") or []]
            gap_text = (", ".join(gaps[:8]) + (f" and {len(gaps) - 8} more" if len(gaps) > 8 else "")) or "—"
            share = r["members_covered"] / r["members"] * 100 if r["members"] and known else 0
            rows.append(f"<tr><th scope='row'>{esc(r['region'])}</th><td>{r['stories']:,}</td>"
                        f"<td><span class='cellbar wk-bar'><i style='width:{share:.0f}%'></i></span>"
                        f"{r['members_covered'] if known else '–'} of {r['members']}</td>"
                        f"<td class='wk-gaps'>{esc(gap_text) if known else 'Shown once stories are located'}</td></tr>")
        out.append("<h2 class='section-h'>Regional coverage</h2><p class='hint'>Stories this week by ISSMGE region, and the "
                   f"member societies whose countries had none.{notes} <a href='{root}map.html'>World map</a></p>"
                   "<div class='table-wrap'><table class='overview wk-regions'><thead><tr><th scope='col'>Region</th>"
                   "<th scope='col'>Stories</th><th scope='col'>Member societies covered</th><th scope='col'>No stories from</th>"
                   f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>")
    if W["events"] or W["deadlines"]:
        since = dt.date.fromisoformat(W["events_from"])
        out.append(f"<h2 class='section-h'>Coming up in the next {W['events_days']} days</h2><p class='hint'>Conferences, "
                   f"courses and deadlines (calls for papers, registration) from {esc(short_date(since))}. "
                   f"<a href='{root}events.html'>The whole events calendar</a></p>")
        items = []
        for e in W["events"] or []:
            link = site_builder.safe_url(e.get("url"))
            name = esc(e.get("name") or e.get("short") or "")
            items.append(f"<li class='wk-ev{' issmge' if e.get('issmge') else ''}'><span class='wk-date'>{esc(event_dates(e))}</span>"
                         + (f"<a href='{esc(link)}' target='_blank' rel='noopener'>{name}</a>" if link != "#" else f"<b>{name}</b>")
                         + "<span class='wk-meta'>" + " · ".join(x for x in (esc(event_place(e)), esc(e.get("kind") or "")) if x)
                         + "</span></li>")
        dls = []
        for x in W["deadlines"] or []:
            ev = x.get("event") or {}
            dls.append(f"<li class='wk-ev wk-dl'><span class='wk-date'>{esc(event_dates({'start': x.get('date')}))}</span>"
                       f"<b>{esc(x.get('label') or 'Deadline')}</b><span class='wk-meta'>{esc(ev.get('name') or ev.get('short') or '')}</span></li>")
        # two lists, each in date order, as in the e-mail
        out += [f"<h3 class='wk-sub'>{title}</h3>" + week_list(group) for title, group in (("Events", items), ("Deadlines", dls))
                if group]
    if W["papers"]:
        out.append(f"<h2 class='section-h'>New research</h2><p class='hint'>The best-rated of the week's "
                   f"{plural(W['papers_total'], 'paper')} for use in practice (Academia-to-Industry).</p>")
        out += [site_builder.paper_card(p) for p in W["papers"]]
    if W["digests"]:
        out.append("<h2 class='section-h'>Daily digests this week</h2><ul class='digest-list'>" + "".join(
            f"<li><a href='{root}digests/{d['date']}.html'>{dt.date.fromisoformat(d['date']):%a} {esc(site_builder.nice_date(d['date']))}</a>"
            f"<span>{d['stories']} stories</span></li>" for d in W["digests"]) + "</ul>")
    if F["digests"]:  # as at the foot of the e-mail
        out.append(site_builder.use_box(root))
    out.append(mail_card(W, rec, opts, last_key))
    pager = ["<nav class='pager'>"]
    pager.append(f"<a href='{older}.html'>← Week {int(older[-2:])}</a>" if older else "<span></span>")
    pager.append("<a href='index.html'>All weekly summaries</a>")
    pager.append(f"<a href='{newer}.html'>Week {int(newer[-2:])} →</a>" if newer else "<span></span>")
    pager.append("</nav>")
    return "".join(out + pager)


def index_body(summaries, cfg, rec, opts, last_key):
    root = "../"
    if not summaries:
        return (site_builder.hero(f"<a href='{root}archive.html'>Archive</a> · Weekly summaries", "Weekly summaries",
                                  f"Every {opts['weekday']} the news desk e-mails the editorial team a summary of the week before.")
                + mail_card(None, rec, opts, last_key)
                + "<p class='empty'>No weekly summaries yet. They appear here after the first scan.</p>")
    stats = (site_builder.stat(len(summaries), "weeks") + site_builder.stat(f"{sum(W['figures']['stories'] for W in summaries):,}", "stories")
             + site_builder.stat(sum(W["figures"]["top"] for W in summaries), "rated 5 / 5")
             + site_builder.stat(sum(W["figures"]["digests"] for W in summaries), "daily digests"))
    out = [site_builder.hero(f"<a href='{root}archive.html'>Archive</a> · Weekly summaries", "Weekly summaries",
                             f"Every {opts['weekday']} the news desk e-mails the editorial team a summary of the week before: "
                             "the top stories of each theme, new 5 / 5 stories, developing stories, regional coverage, "
                             "events and deadlines coming up, and new research. Each week's page shows the same summary.",
                             stats, f"<div class='actions'><a class='btn primary' href='{summaries[0]['key']}.html'>"
                             f"{site_builder.icon('book')}Latest week</a></div>"),
           mail_card(None, rec, opts, last_key)]
    by_key = {W["key"]: W for W in summaries}
    weeks, monday = [], week_range(summaries[0]["key"])[0]
    oldest = week_range(summaries[-1]["key"])[0]
    while monday >= oldest:  # every week from the newest to the oldest, so weeks without scans show
        weeks.append(by_key.get(week_key(monday)) or week_key(monday))
        monday -= dt.timedelta(days=7)
    current = None
    for W in weeks:
        key = W if isinstance(W, str) else W["key"]
        win = site_builder.issue_window(week_range(key)[1].isoformat(), site_builder.start_month(cfg))
        if win["key"] != current:
            if current:
                out.append("</div>")
            current = win["key"]
            out.append(f"<h2 class='section-h'>{esc(win['label'])} <span class='h1-sub'>{esc(win['span'])}</span></h2><div class='wk-index'>")
        if isinstance(W, str):
            out.append(f"<div class='wk-card wk-gap'><span class='wk-card-head'><span><b>Week {int(key[-2:])}</b>"
                       f"<span class='wk-span'>{esc(span_text(*week_range(key)))}</span></span></span>"
                       "<span class='wk-figs'>No daily digests were saved this week: the scans did not run.</span></div>")
            continue
        F = W["figures"]
        lead = W["top"][0] if W["top"] else None
        sent = rec["weekly"].get(W["key"])
        chip = ("<span class='wk-chip ok'>E-mailed</span>" if sent else "<span class='wk-chip'>In progress</span>"
                if W["in_progress"] else "")
        out.append(f"<a class='wk-card' href='{W['key']}.html'><span class='wk-card-head'><span><b>Week {W['week']}</b>"
                   f"<span class='wk-span'>{esc(W['span'])}</span></span>{chip}</span>"
                   f"<span class='wk-figs'>{plural(F['stories'], 'story', 'stories')} · {F['top']} rated 5 / 5 · "
                   f"{plural(F['digests'], 'digest')}{' · ' + plural(F['papers'], 'paper') if F['papers'] else ''}</span>"
                   + (f"<span class='wk-lead' dir='auto'>{esc(headline(lead))}</span>" if lead else "")
                   + f"{strip(W['themes'])}</a>")
    out.append("</div>")
    return "".join(out)


def build(ctx):
    """docs/weekly/<YYYY-Www>.html for every week that has digests (newest first) and docs/weekly/index.html."""
    cfg, digests = ctx["cfg"], ctx["digests"]
    opts, rec, today = settings(cfg), load_record(), cairo_today()
    keys = sorted({week_key(d["date"]) for d in digests}, reverse=True)
    summaries = [week_summary(digests, k, cfg, today=today) for k in keys]
    last_key = last_week(today)
    folder = site_builder.DOCS / "weekly"
    for i, W in enumerate(summaries):
        older = keys[i + 1] if i + 1 < len(keys) else None
        newer = keys[i - 1] if i > 0 else None
        site_builder.write(folder / f"{W['key']}.html",
                           site_builder.page(cfg, f"Week {W['week']} · {W['span']}", week_body(W, cfg, rec, opts, older, newer, last_key),
                                             "../", "archive", f"Weekly summary of the geotechnical news, {W['span']}"))
    site_builder.write(folder / "index.html",
                       site_builder.page(cfg, "Weekly summaries", index_body(summaries, cfg, rec, opts, last_key), "../",
                                         "archive", "The weekly summaries the news desk e-mails to the editorial team"))


if __name__ == "__main__":
    sys.exit(main())
