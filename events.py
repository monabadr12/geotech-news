#!/usr/bin/env python3
"""
Events calendar: ISSMGE conferences, other events and call-for-papers deadlines,
from data/events.yaml (kept by the editors) and data/events.json (found by the
weekly scan), listed on docs/events.html.

    python events.py --auto      in the daily scan: refresh when the calendar is a week old
    python events.py --refresh   refresh now

Placeholder: replaced by the full implementation.
"""
import sys

import site_builder


def build(ctx):
    cfg = ctx["cfg"]
    site_builder.write(site_builder.DOCS / "events.html",
                       site_builder.page(cfg, "Events", site_builder.hero("Events", "Coming soon"), "", "events"))


if __name__ == "__main__":
    sys.exit(0)
