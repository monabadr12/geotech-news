#!/usr/bin/env python3
"""
Save step of the scan workflow.

Carries this run's new data (the day's digest, the seen-stories memory and any
issue brief) onto the newest version of the branch, then rebuilds the website
from it. Generated files in docs/ are never merged line by line, they are
rebuilt, so a scan cannot clash with a site update or another run that finished
in the meantime (or with a re-run that started from an older commit).

    python sync_data.py <branch>
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIGESTS = ROOT / "data" / "digests"
BRIEFS = ROOT / "data" / "briefs"
SEEN_FILE = ROOT / "data" / "seen.json"


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
    briefs = {name: (BRIEFS / name).read_text(encoding="utf-8") for name in changed("briefs")}

    git("fetch", "--quiet", "origin", branch)
    git("reset", "--quiet", "--hard", f"origin/{branch}")

    if our_seen:
        seen = load(SEEN_FILE) or {}
        for key, day in our_seen.items():
            if day > seen.get(key, ""):
                seen[key] = day
        SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        SEEN_FILE.write_text(json.dumps(seen, indent=0))
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
    for name, text in briefs.items():  # issue briefs: this run's version wins
        BRIEFS.mkdir(parents=True, exist_ok=True)
        (BRIEFS / name).write_text(text, encoding="utf-8")
    if rebalance:
        subprocess.run([sys.executable, str(ROOT / "scanner.py"), "--rebalance", *rebalance], cwd=ROOT, check=True)

    # rebuild with the newest code, in a fresh process (this one has the old modules loaded)
    subprocess.run([sys.executable, str(ROOT / "site_builder.py")], cwd=ROOT, check=True)
    print(f"Synced {len(ours)} digest(s) and {len(briefs)} brief(s) onto origin/{branch} and rebuilt the website.")


if __name__ == "__main__":
    main()
