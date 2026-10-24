#!/usr/bin/env python3
"""
Test candidate feed addresses from GitHub's network (run by the "Check feeds"
workflow). Input: JSON {"Source name": ["https://...", ...], ...}, from the
FEEDS environment variable or a file given as the first argument.
For every address it prints OK with the number of entries and the newest one,
or FAIL with the reason. Crossref API addresses (api.crossref.org) are tested
as JSON, with the scanner's Crossref User-Agent, and report the number of
works, the journal they belong to and the newest one (so a journal's ISSN can
be checked); the input may also be {"research": true} to test every journal in
config.yaml's research: list.
"""
import json
import os
import sys

import requests
import yaml

import scanner


def check(url, cfg):
    if "api.crossref.org" in url:
        r = requests.get(url, headers=scanner.crossref_headers(cfg), timeout=30)
        r.raise_for_status()
        items = r.json().get("message", {}).get("items", [])
        newest = items[0] if items else {}
        title = (newest.get("title") or [""])[0][:90]
        journal = (newest.get("container-title") or [""])[0][:60]
        created = (newest.get("created") or {}).get("date-time", "")[:10]
        return f"{len(items)} works; journal: {journal or '?'}; newest {created or 'no date'}: {title}"
    entries = scanner.read_feed(url)
    newest = max(entries, key=lambda e: scanner.entry_time(e) or scanner.dt.datetime.min.replace(tzinfo=scanner.dt.timezone.utc))
    when = scanner.entry_time(newest)
    date = f"{when:%Y-%m-%d}" if when else "no date"
    return f"{len(entries)} entries; newest {date}: {scanner.clean(newest.get('title'))[:90]}"


def main():
    raw = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else os.environ.get("FEEDS", "{}")
    candidates = json.loads(raw)
    cfg = yaml.safe_load(scanner.CONFIG.read_text(encoding="utf-8"))
    if candidates.pop("research", False):  # every configured journal, over the last 30 days
        since = scanner.dt.date.today() - scanner.dt.timedelta(days=30)
        for j in scanner.research_cfg(cfg).get("journals") or []:
            candidates.setdefault(j["name"], []).append(scanner.crossref_url(j["issn"], since, cfg))
    for name, urls in candidates.items():
        for url in ([urls] if isinstance(urls, str) else urls):
            try:
                print(f"OK    | {name} | {url} | {check(url, cfg)}")
            except Exception as ex:  # report every failure, keep going
                print(f"FAIL  | {name} | {url} | {type(ex).__name__}: {str(ex)[:160]}")


if __name__ == "__main__":
    main()
