#!/usr/bin/env python3
"""
Builds assets/regions.json: the lines between the six ISSMGE regions on the Geo-News world map (shown when
config.yaml sets geonews: map_regions: outline), from the country outlines of assets/world.json and the regions
the site gives each country (geomap.region_table, from config.yaml map: regions, continents and regions_of).

    pip install shapely
    python tools/make_regions.py            write assets/regions.json
    python tools/make_regions.py --check    say whether assets/regions.json still matches config.yaml (exit 1 if not)

Run it again after moving a country to another region in config.yaml (or after a new assets/world.json). The website
build only reads the file, so it needs no shapely; while the file no longer matches config.yaml, the map draws no
region lines and the build says so (the region names and the shading still follow config.yaml).

What it writes:
  * "regions": the region of every country, as the lines were drawn for it (the build compares it with config.yaml);
  * "borders": the lines between regions on land, as one SVG path in the units of the world map (Equal Earth).
The outlines of assets/world.json are simplified country by country, so neighbours do not meet exactly: each
region is the union of its countries widened by GAP and narrowed again (which closes the slits between them), and a
line is the part of one region's edge that lies within NEAR of another region and along a land border: where a
country of one region comes within CONTACT of a country of another (so not where two coasts face each other across a
narrow gulf or strait, such as Egypt and Saudi Arabia across the Gulf of Aqaba). Pieces shorter than MIN_LINE are
dropped.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "assets" / "regions.json"

GAP = 2.0        # map units: slits narrower than twice this between the countries of one region are closed
NEAR = 3.0       # a region's edge within this distance of another region is a border between them
CONTACT = 1.5    # two countries whose outlines come this close share a land border (across water they are further)
MIN_LINE = 12    # pieces of border shorter than this (map units) are dropped
SIMPLIFY = 0.6   # the lines are simplified by this much, then rounded to whole units


def table(cfg):
    """{country code: ISSMGE region} for the countries the map draws (the ones with an outline)."""
    import geomap
    t = geomap.region_table(cfg)
    return {k: t.get(k, "") for k, v in sorted(geomap.world()["countries"].items()) if v.get("d")}


def rings(d):
    """The rings of an SVG path of assets/world.json (M x y l dx dy ... z), as lists of points."""
    out, x, y = [], 0.0, 0.0
    for cmd, args in re.findall(r"([MLlmz])([^MLlmz]*)", d):
        nums = [float(t) for t in re.findall(r"-?\d+(?:\.\d+)?", args)]
        if cmd in "Mm":
            x, y = (x + nums[0], y + nums[1]) if cmd == "m" else (nums[0], nums[1])
            out.append([(x, y)])
            nums = nums[2:]
        elif cmd == "z":
            continue
        for i in range(0, len(nums) - 1, 2):
            x, y = (x + nums[i], y + nums[i + 1]) if cmd in "lm" else (nums[i], nums[i + 1])
            out[-1].append((x, y))
    return [r for r in out if len(r) >= 3]


def number_list(values):
    """SVG numbers with the fewest separators: a minus sign separates on its own (as tools/make_world.py writes them)."""
    out = ""
    for v in values:
        out += (str(v) if v < 0 or not out else " " + str(v))
    return out


def line_path(lines):
    parts = []
    for pts in lines:
        pts = [(round(x), round(y)) for x, y in pts]
        pts = [p for i, p in enumerate(pts) if i == 0 or p != pts[i - 1]]
        if len(pts) < 2:
            continue
        deltas = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            deltas += [x1 - x0, y1 - y0]
        parts.append(f"M{number_list(list(pts[0]))}l{number_list(deltas)}")
    return "".join(parts)


def borders(regions):
    """The SVG path of the lines between the regions, from {country code: region}."""
    from shapely.geometry import LineString, MultiLineString, Polygon
    from shapely.ops import linemerge, unary_union
    from shapely.validation import make_valid
    import geomap
    shapes, countries = {}, {}
    for code, region in regions.items():
        if not region:
            continue
        # a country's parts overseas (geomap.OVERSEAS, e.g. French Guiana) count in the region they lie in
        for part, where in geomap.country_parts(code, geomap.world()["countries"][code]["d"], region):
            polys = [make_valid(Polygon(r)) for r in rings(part)]
            shapes.setdefault(where, []).extend(p.buffer(GAP) for p in polys)
            countries[(code, where)] = unary_union(polys)
    whole = {r: unary_union(p).buffer(-GAP) for r, p in shapes.items()}
    # the land borders between countries of different regions: each one's edge within CONTACT of the other
    codes = sorted(countries)
    contacts = []
    for i, a in enumerate(codes):
        for b in codes[i + 1:]:
            if a[1] != b[1] and countries[a].distance(countries[b]) <= CONTACT:
                contacts.append(countries[a].boundary.intersection(countries[b].buffer(CONTACT)))
    land = unary_union(contacts).buffer(NEAR)
    names = [r for r in geomap.REGIONS if r in whole]
    pieces = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            near = whole[a].boundary.intersection(whole[b].buffer(NEAR)).intersection(land)
            parts = getattr(near, "geoms", [near])
            pieces += [p for p in parts if isinstance(p, LineString) and p.length > 0]
    if not pieces:
        return ""
    merged = linemerge(MultiLineString(pieces))
    lines = [m for m in getattr(merged, "geoms", [merged]) if m.length >= MIN_LINE]
    lines.sort(key=lambda m: (round(m.coords[0][0]), round(m.coords[0][1])))
    return line_path([m.simplify(SIMPLIFY).coords for m in lines])


def main():
    import yaml
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    regions = table(cfg)
    if "--check" in sys.argv[1:]:
        try:
            stored = json.loads(OUT.read_text(encoding="utf-8")).get("regions")
        except (OSError, ValueError):
            stored = None
        if stored == regions:
            print(f"{OUT.relative_to(ROOT)} matches the regions of config.yaml.")
            return 0
        moved = sorted(k for k in set(regions) | set(stored or {}) if (stored or {}).get(k) != regions.get(k))
        print(f"{OUT.relative_to(ROOT)} no longer matches config.yaml ({', '.join(moved[:12]) or 'unreadable'}); "
              f"run python tools/make_regions.py")
        return 1
    asset = {"source": "Made by tools/make_regions.py from assets/world.json (Natural Earth) and the regions of config.yaml",
             "regions": regions, "borders": borders(regions)}
    OUT.write_text(json.dumps(asset, ensure_ascii=False, separators=(",", ":"), sort_keys=False), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: lines between {len(set(regions.values()) - {''})} regions, "
          f"{asset['borders'].count('M')} pieces, {OUT.stat().st_size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
