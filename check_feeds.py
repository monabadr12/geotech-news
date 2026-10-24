#!/usr/bin/env python3
"""
Test candidate feed addresses from GitHub's network (run by the "Check feeds"
workflow). Input: JSON {"Source name": ["https://...", ...], ...}, from the
FEEDS environment variable or a file given as the first argument.
For every address it prints OK with the number of entries and the newest one,
or FAIL with the reason. Crossref API addresses (api.crossref.org) are tested
as JSON and report the number of works returned.
"""
import json
import os
import sys

import requests

import scanner


def check(url):
    if "api.crossref.org" in url:
        r = requests.get(url, headers=scanner.HEADERS, timeout=30)
        r.raise_for_status()
        items = r.json().get("message", {}).get("items", [])
        newest = items[0] if items else {}
        title = (newest.get("title") or [""])[0][:90]
        return f"{len(items)} works; newest: {title}"
    entries = scanner.read_feed(url)
    newest = max(entries, key=lambda e: scanner.entry_time(e) or scanner.dt.datetime.min.replace(tzinfo=scanner.dt.timezone.utc))
    when = scanner.entry_time(newest)
    date = f"{when:%Y-%m-%d}" if when else "no date"
    return f"{len(entries)} entries; newest {date}: {scanner.clean(newest.get('title'))[:90]}"


def main():
    raw = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else os.environ.get("FEEDS", "{}")
    candidates = json.loads(raw)
    for name, urls in candidates.items():
        for url in ([urls] if isinstance(urls, str) else urls):
            try:
                print(f"OK    | {name} | {url} | {check(url)}")
            except Exception as ex:  # report every failure, keep going
                print(f"FAIL  | {name} | {url} | {type(ex).__name__}: {str(ex)[:160]}")


if __name__ == "__main__":
    main()
