#!/usr/bin/env python3
"""
Builds assets/world.json, the geometry of the world map page (docs/map.html),
from Natural Earth's admin-0 countries (public domain, naturalearthdata.com):

    python tools/make_world.py ne_50m_admin_0_countries.geojson [ne_110m_admin_0_countries.geojson]

Download the files from
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/
Run it again only to change the geometry (a new Natural Earth release, more or
less detail); the asset is committed and the website build only reads it.

What it writes, for every country and territory in the 50m file (Antarctica left out):
  * "n": the English name; "g": its continent group (Natural Earth's continent, or
    its subregion in North America: Northern America, Central America, Caribbean),
    which config.yaml's map: continents rule turns into an ISSMGE region;
  * "c": the label point (Natural Earth's LABEL_X / LABEL_Y), where a story bubble goes;
  * "d": the outline as an SVG path, in the Equal Earth projection (equal-area, so no
    region looks bigger than it is), simplified and rounded to whole units of the
    viewBox. Places too small to draw at this scale (Singapore, Malta, Bahrain...)
    keep only their label point.
Countries are keyed by ISO 3166-1 alpha-2 (ISO_A2_EH). Natural Earth's -99 entries
are merged with the country they belong to geographically (N. Cyprus with Cyprus,
Somaliland with Somalia); Kosovo is XK; the Siachen Glacier is drawn as land with no
country. With the 110m file as well, the script reports which countries only the
50m file has (they are the ones that need the label points).
"""
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "world.json"

SCALE = 1000        # viewBox units per radian of the projection (the world is about 5,400 units wide)
TOLERANCE = 0.9     # simplification: points closer than this to the simplified line are dropped
MIN_AREA = 6        # islands smaller than this (square units) are dropped, unless they are all a country has
MERGE = {"N. Cyprus": "CY", "Somaliland": "SO"}  # Natural Earth's -99 entries, by NAME
NAMES = {  # shorter or more usual English names than Natural Earth's NAME_EN
    "US": "United States", "CN": "China", "CZ": "Czechia", "TR": "Türkiye", "CI": "Côte d'Ivoire",
    "CV": "Cabo Verde", "TL": "Timor-Leste", "MO": "Macao", "SZ": "Eswatini", "BS": "Bahamas", "GM": "Gambia",
    "CG": "Republic of the Congo", "CD": "Democratic Republic of the Congo", "VA": "Vatican City",
    "FM": "Micronesia", "AX": "Åland Islands", "FO": "Faroe Islands", "RS": "Serbia", "TZ": "Tanzania",
    "GS": "South Georgia and the South Sandwich Islands", "HK": "Hong Kong", "AU": "Australia",
}
# zoom presets (lon west, lon east, lat south, lat north), one per ISSMGE region
VIEWS = {
    "Africa": (-20, 55, -36, 38), "Asia": (26, 148, -11, 56), "Australasia": (110, 180, -48, -5),
    "Europe": (-25, 45, 34, 71), "North America": (-168, -50, 13, 72), "South America": (-118, -32, -56, 32),
}

A1, A2, A3, A4 = 1.340264, -0.081106, 0.000893, 0.003796
M = math.sqrt(3) / 2


def project(lon, lat):
    """Equal Earth (Šavrič, Patterson and Jenny, 2018), as SVG units (y down)."""
    lam, phi = math.radians(lon), math.radians(max(-90.0, min(90.0, lat)))
    t = math.asin(M * math.sin(phi))
    t2 = t * t
    t6 = t2 * t2 * t2
    x = lam * math.cos(t) / (M * (A1 + 3 * A2 * t2 + t6 * (7 * A3 + 9 * A4 * t2)))
    y = t * (A1 + A2 * t2 + t6 * (A3 + A4 * t2))
    return x * SCALE, -y * SCALE


def simplify(points, tol):
    """Douglas-Peucker on an open polyline (iterative)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            d = (abs(dy * (px - ax) - dx * (py - ay)) / norm) if norm else math.hypot(px - ax, py - ay)
            if d > best:
                best, idx = d, i
        if best > tol and idx > 0:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def area(ring):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))) / 2


def ring_points(coords):
    """A ring projected, simplified and rounded, without its closing point; None when it vanishes."""
    pts = [project(lon, lat) for lon, lat in coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if len(pts) < 3:
        return None
    far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
    half = simplify(pts[:far + 1], TOLERANCE)[:-1] + simplify(pts[far:] + pts[:1], TOLERANCE)[:-1]
    out = []
    for x, y in half:
        p = (round(x), round(y))
        if not out or p != out[-1]:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out if len(out) >= 3 else None


def number_list(values):
    """SVG numbers with the fewest separators: a minus sign separates on its own."""
    out = ""
    for v in values:
        out += (str(v) if v < 0 or not out else " " + str(v))
    return out


def path(rings):
    parts = []
    for ring in rings:
        (x0, y0), rest = ring[0], ring[1:]
        deltas = []
        px, py = x0, y0
        for x, y in rest:
            deltas += [x - px, y - py]
            px, py = x, y
        parts.append(f"M{number_list([x0, y0])}l{number_list(deltas)}z")
    return "".join(parts)


def polygons(geometry):
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"]]
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    return []


def group(p):
    """Continent group for the ISSMGE region rule (config.yaml map: continents)."""
    cont = p["CONTINENT"]
    if cont == "North America":
        return p["SUBREGION"]  # Northern America, Central America or Caribbean
    if cont.startswith("Seven seas"):  # open-ocean islands: their UN region
        return {"Americas": "South America", "Oceania": "Oceania"}.get(p["REGION_UN"], p["REGION_UN"])
    return cont


def own(p, code):
    """How much a feature is the country itself: its own code first, then not a dependency. That
    feature gives the name and the label point (Cyprus, not N. Cyprus; Australia, not its islands)."""
    return (p["ISO_A2_EH"] == code, p["TYPE"] != "Dependency")


def view_box(west, east, south, north):
    pts = []
    for i in range(41):
        lon = west + (east - west) * i / 40
        pts += [project(lon, south), project(lon, north)]
    for i in range(41):
        lat = south + (north - south) * i / 40
        pts += [project(west, lat), project(east, lat)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    pad = 0.03 * (max(xs) - min(xs))
    return [round(min(xs) - pad), round(min(ys) - pad), round(max(xs) - min(xs) + 2 * pad), round(max(ys) - min(ys) + 2 * pad)]


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    features = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["features"]
    countries, land, raw = {}, [], {}
    for f in features:
        p = f["properties"]
        code = p["ISO_A2_EH"]
        if code == "AQ":
            continue
        if code == "-99":
            code = MERGE.get(p["NAME"])
            if not code:  # e.g. the Siachen Glacier: land, but no country
                land += [r for poly in polygons(f["geometry"]) for r in poly[:1]]
                continue
        entry = raw.setdefault(code, {"rings": [], "main": None})
        entry["rings"] += [poly[0] for poly in polygons(f["geometry"])]  # outer rings (lakes are not drawn)
        if entry["main"] is None or own(p, code) > own(entry["main"], code):
            entry["main"] = p
    for code, entry in sorted(raw.items()):
        p = entry["main"]
        rings = [r for r in (ring_points(c) for c in entry["rings"]) if r]
        big = [r for r in rings if area(r) >= MIN_AREA]
        if not big and rings:
            big = [max(rings, key=area)] if area(max(rings, key=area)) >= 1 else []
        cx, cy = project(p["LABEL_X"], p["LABEL_Y"])
        countries[code] = {"n": NAMES.get(code) or p["NAME_EN"] or p["NAME"], "g": group(p),
                           "c": [round(cx), round(cy)], **({"d": path(big)} if big else {})}
    land_rings = [r for r in (ring_points(c) for c in land) if r]

    # the frame: the projected globe from the pole line to 60°S (Antarctica is left out)
    edge = [project(-180, lat) for lat in range(90, -61, -5)] + [project(180, lat) for lat in range(-60, 91, 5)]
    xs = [x for c in countries.values() for x in [c["c"][0]]] + [x for x, _ in edge]
    top, bottom = project(0, 90)[1] - 8, project(0, -57)[1]
    asset = {
        "source": "Made with Natural Earth (public domain), admin-0 countries 1:50m; Equal Earth projection",
        "view": [round(min(xs)) - 4, round(top), round(max(xs) - min(xs)) + 8, round(bottom - top)],
        "sphere": path([[(round(x), round(y)) for x, y in edge]]),
        "views": {k: view_box(*v) for k, v in VIEWS.items()},
        "land": path(land_rings) if land_rings else "",
        "countries": countries,
    }
    OUT.write_text(json.dumps(asset, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    shapes = sum(1 for c in countries.values() if "d" in c)
    print(f"{OUT.relative_to(ROOT)}: {len(countries)} countries and territories ({shapes} with outlines, "
          f"{len(countries) - shapes} label points only), {OUT.stat().st_size / 1024:.0f} KB")
    if len(sys.argv) > 2:  # which places have no outline at 1:110m
        small = {f["properties"]["ISO_A2_EH"] for f in json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))["features"]}
        print("Only in the 50m file:", ", ".join(sorted(set(countries) - small)))


if __name__ == "__main__":
    main()
