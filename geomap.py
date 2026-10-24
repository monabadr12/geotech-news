#!/usr/bin/env python3
"""
World map page (docs/map.html): stories plotted by the country they are about,
with the ISSMGE regions and member-society countries that have no stories, so
regional gaps are visible. Also locates archived stories that have no country.

Placeholder: replaced by the full implementation.
"""
import site_builder


def locate_missing(cfg, notes):
    """Give archived stories without a "country" key one (Claude). Placeholder."""
    return 0


def build(ctx):
    cfg = ctx["cfg"]
    site_builder.write(site_builder.DOCS / "map.html",
                       site_builder.page(cfg, "World map", site_builder.hero("World map", "Coming soon"), "", "map"))
