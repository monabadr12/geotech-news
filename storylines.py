#!/usr/bin/env python3
"""
Developing stories: follow-up reports linked to the original event (a dam
failure, then the inquiry, then the repair), and the page docs/developing.html.

Placeholder: replaced by the full implementation.
"""
import site_builder


def link(stories, now, cfg, notes):
    """Mark today's stories that follow up an earlier one. Placeholder."""
    return 0


def build(ctx):
    cfg = ctx["cfg"]
    site_builder.write(site_builder.DOCS / "developing.html",
                       site_builder.page(cfg, "Developing stories", site_builder.hero("Developing stories", "Coming soon"),
                                         "", "developing"))
