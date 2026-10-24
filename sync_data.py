#!/usr/bin/env python3
"""
Save step of the scan workflow.

Carries this run's new data (the day's digest and any archived digest it updated,
the seen-stories memory, the events calendar, the record of e-mails sent and any
issue brief, unless the branch already holds a newer brief for that window) onto
the newest version of the branch, then rebuilds the website from it. Generated
files in docs/ are never merged line by line, they are rebuilt, so a scan cannot
clash with a site update or another run that finished in the meantime (or with
a re-run that started from an older commit).

    python sync_data.py <branch>
"""
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIGESTS = ROOT / "data" / "digests"
BRIEFS = ROOT / "data" / "briefs"
SEEN_FILE = ROOT / "data" / "seen.json"
EVENTS_FILE = ROOT / "data" / "events.json"   # events found by events.py: {"updated": iso, "events": [...]}
NOTIFY_FILE = ROOT / "data" / "notify.json"   # e-mails sent by notify.py: {"alerted": {id: date}, "weekly": {week: iso}}


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout


def changed(folder):
    """JSON files under data/<folder> this run created or changed (staged or not)."""
    out = git("status", "--porcelain", "--untracked-files=all", "--", f"data/{folder}")
    return sorted({Path(line[3:].strip()).name for line in out.splitlines() if line[3:].strip().endswith(".json")})


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def committed(name):
    """The digest as it was in the commit this run started from (None if new)."""
    try:
        return json.loads(git("show", f"HEAD:data/digests/{name}"))
    except subprocess.CalledProcessError:
        return None


def generated(text):
    """When a brief (its JSON text) was written, or None when that cannot be read."""
    try:
        when = dt.datetime.fromisoformat(str(json.loads(text).get("generated", "")))
    except (ValueError, TypeError, AttributeError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def changed_file(path):
    """This run's version of a data file it created or changed, else None."""
    out = git("status", "--porcelain", "--untracked-files=all", "--", str(path.relative_to(ROOT)))
    return load(path) if out.strip() and path.exists() else None


def merge_events(theirs, ours):
    """The calendar refreshed last wins (two refreshes at once are rare)."""
    if not theirs:
        return ours
    return ours if str(ours.get("updated", "")) >= str(theirs.get("updated", "")) else theirs


def merge_notify(theirs, ours):
    """Every e-mail either run sent stays recorded, so none is sent twice."""
    merged = dict(theirs or {})
    for key in ("alerted", "weekly"):
        both = dict((theirs or {}).get(key) or {})
        for k, v in (ours.get(key) or {}).items():
            if str(v) > str(both.get(k, "")):
                both[k] = v
        merged[key] = both
    return merged


def merge_digest(theirs, ours):
    """Union of the day's stories (this run's version of a story wins); the
    caller re-balances it."""
    if not theirs:
        return ours
    known = {s["id"] for s in ours["stories"]}
    merged = dict(ours)
    merged["stories"] = sorted(ours["stories"] + [s for s in theirs["stories"] if s["id"] not in known],
                               key=lambda s: -s.get("rank", 0))
    if ours.get("papers") or theirs.get("papers"):
        known = {p["id"] for p in ours.get("papers", [])}
        merged["papers"] = ours.get("papers", []) + [p for p in theirs.get("papers", []) if p["id"] not in known]
    merged["new_items"] = max(ours.get("new_items", 0), theirs.get("new_items", 0))
    merged["ai_used"] = ours.get("ai_used") or theirs.get("ai_used", False)
    return merged


def main():
    branch = sys.argv[1] if len(sys.argv) > 1 else "main"
    our_seen = load(SEEN_FILE) or {}
    ours = {name: load(DIGESTS / name) for name in changed("digests")}
    base = {name: committed(name) for name in ours}
    briefs = {name: (BRIEFS / name).read_text(encoding="utf-8") for name in changed("briefs") if (BRIEFS / name).exists()}
    extras = {path: (merge, changed_file(path)) for path, merge in ((EVENTS_FILE, merge_events), (NOTIFY_FILE, merge_notify))}

    git("fetch", "--quiet", "origin", branch)
    git("reset", "--quiet", "--hard", f"origin/{branch}")

    if our_seen:
        seen = load(SEEN_FILE) or {}
        for key, day in our_seen.items():
            if day > seen.get(key, ""):
                seen[key] = day
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SEEN_FILE.write_text(json.dumps(seen, indent=0))
    for path, (merge, mine) in extras.items():
        if mine is not None:
            path.write_text(json.dumps(merge(load(path), mine), ensure_ascii=False, indent=1), encoding="utf-8")
    rebalance = []
    for name, digest in ours.items():
        if digest is None:
            continue
        path = DIGESTS / name
        path.parent.mkdir(parents=True, exist_ok=True)
        theirs = load(path)
        if theirs is None or theirs == base[name]:
            merged = digest  # nobody else changed it: this run's digest already includes the earlier one
        else:
            merged = merge_digest(theirs, digest)  # another run saved the same day meanwhile
            rebalance.append(name)
        path.write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")
    saved = 0
    for name, text in briefs.items():  # issue briefs: this run's version, unless the branch has a newer one
        path = BRIEFS / name
        theirs = generated(path.read_text(encoding="utf-8")) if path.exists() else None
        mine = generated(text)
        if theirs and (mine is None or theirs > mine):  # e.g. a brief saved by another run meanwhile
            print(f"Issue brief {name} not saved: the branch already has a newer one "
                  f"(written {theirs.astimezone(dt.timezone.utc):%Y-%m-%d %H:%M} UTC).")
            continue
        BRIEFS.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        saved += 1
    if rebalance:
        subprocess.run([sys.executable, str(ROOT / "scanner.py"), "--rebalance", *rebalance], cwd=ROOT, check=True)

    # rebuild with the newest code, in a fresh process (this one has the old modules loaded)
    subprocess.run([sys.executable, str(ROOT / "site_builder.py")], cwd=ROOT, check=True)
    print(f"Synced {len(ours)} digest(s) and {saved} brief(s) onto origin/{branch} and rebuilt the website.")


if __name__ == "__main__":
    main()
