#!/usr/bin/env python3
"""
World map page (docs/map.html): stories plotted by the country they are about
(the "country" Claude reads in each story during triage, not the Google News
edition), with the ISSMGE regions and the member-society countries that have no
stories in the period, so regional gaps are visible. Also locates archived
stories that have no country yet.

    python geomap.py      locate archived stories that have no country now (Claude)

The geometry is assets/world.json (Natural Earth, made by tools/make_world.py),
the page's script assets/map.js; the settings and the ISSMGE member lists are
under map: in config.yaml.
"""
import datetime as dt
import json
import os
import sys

import yaml

import site_builder

esc = site_builder.esc
WORLD_FILE = site_builder.ASSETS / "world.json"
REGIONS = ["Africa", "Asia", "Australasia", "Europe", "North America", "South America"]
DEFAULTS = {"model": "", "effort": "low", "locate_per_run": 300, "embed_limit": 1500}
BATCH = 60  # stories per request when locating archived stories
# places Natural Earth draws as part of another country: their stories are mapped there
ALIASES = {"GF": "FR", "GP": "FR", "MQ": "FR", "RE": "FR", "YT": "FR", "SJ": "NO", "BV": "NO", "BQ": "NL",
           "GI": "GB", "UM": "US", "CX": "AU", "CC": "AU", "TK": "NZ"}
EXTRA_NAMES = {"GF": "French Guiana", "GP": "Guadeloupe", "MQ": "Martinique", "RE": "Réunion", "YT": "Mayotte",
               "SJ": "Svalbard and Jan Mayen", "BV": "Bouvet Island", "BQ": "Caribbean Netherlands",
               "GI": "Gibraltar", "UM": "US Minor Outlying Islands", "CX": "Christmas Island",
               "CC": "Cocos (Keeling) Islands", "TK": "Tokelau"}
CREDIT = ("Made with Natural Earth. Boundaries are drawn for orientation only and imply no position on disputed "
          "territories.")
TOP_LIST = 12  # countries in the panel's ranking


# ------------------------------------------------------------------ countries and regions
_world = None


def world():
    """assets/world.json (names, continent groups, label points and outlines), read once."""
    global _world
    if _world is None:
        try:
            _world = json.loads(WORLD_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError) as ex:
            print(f"World map geometry {WORLD_FILE.name} could not be read ({ex}); country names fall back to codes.")
            _world = {"countries": {}}
    return _world


def code_of(value):
    """A country code as written in config.yaml or a story. YAML reads an unquoted NO
    (Norway) as false, so false is NO."""
    return "NO" if value is False else str(value or "").strip().upper()


def canonical(code):
    """The code the map knows the country by (overseas departments go with their country), or ""."""
    code = code_of(code)
    code = ALIASES.get(code, code)
    return code if code in world()["countries"] else ""


def country_name(code):
    """English name of a country code ("" for "")."""
    code = code_of(code)
    if not code:
        return ""
    known = world()["countries"].get(code)
    return (known["n"] if known else EXTRA_NAMES.get(code)) or site_builder.COUNTRIES.get(code, code)


_warned = set()  # settings already reported as unreadable


def settings(cfg):
    """The map: section of config.yaml, with defaults; a number that cannot be read is reported
    and its default used, so a typo there never stops the site from being built."""
    m = cfg.get("map")
    m = m if isinstance(m, dict) else {}
    out = dict(DEFAULTS)
    for key, default in DEFAULTS.items():
        if key not in m or m[key] in (None, ""):
            continue
        if isinstance(default, int):
            try:
                out[key] = max(0, int(m[key]))
            except (TypeError, ValueError):
                if key not in _warned:  # once per run, not once per call
                    _warned.add(key)
                    print(f"config.yaml map: {key} should be a whole number; {default} is used.")
        else:
            out[key] = str(m[key]).strip()
    out["model"] = out["model"] or str((cfg.get("claude") or {}).get("model") or "claude-haiku-5-5")
    for key in ("regions", "continents", "regions_of"):
        out[key] = m.get(key) if isinstance(m.get(key), dict) else {}
    return out


def region_info(cfg):
    """The six ISSMGE regions in their fixed order: member-society countries, number of
    societies, transnational societies and whether the list still needs checking."""
    regions = settings(cfg)["regions"]
    out = []
    for name in REGIONS:
        r = regions.get(name) if isinstance(regions.get(name), dict) else {}
        raw, trans = r.get("members"), r.get("transnational")
        if isinstance(raw, str):  # codes written without brackets ("AU, NZ")
            raw = raw.replace(",", " ").split()
        if isinstance(trans, str):
            trans = [trans]
        members = []
        for c in raw if isinstance(raw, list) else []:
            c = code_of(c)
            if c and c not in members:
                members.append(c)
        try:
            societies = int(r.get("societies") or 0)
        except (TypeError, ValueError):
            societies = 0
        out.append({"name": name, "members": members, "societies": societies or len(members),
                    "transnational": [str(t) for t in trans] if isinstance(trans, list) else [],
                    "to_check": bool(r.get("to_check"))})
    return out


def member_countries(cfg):
    """{region: [member-society country codes]}, the regions in their fixed order."""
    return {r["name"]: r["members"] for r in region_info(cfg)}


_tables = {}


def region_table(cfg):
    """{country code: ISSMGE region} for every country the map knows, worked out once per settings."""
    s = settings(cfg)
    key = json.dumps([s["regions"], s["continents"], s["regions_of"]], sort_keys=True, default=str)
    if key not in _tables:
        table = {}
        for code, c in world()["countries"].items():
            region = s["continents"].get(c.get("g", ""), "")
            table[code] = region if region in REGIONS else ""
        for code, region in s["regions_of"].items():
            if str(region) in REGIONS:
                table[code_of(code)] = str(region)
        for region, codes in member_countries(cfg).items():
            for code in codes:
                table[code] = region
        _tables[key] = table
    return _tables[key]


def issmge_region(code, cfg):
    """The ISSMGE region of a country: its member society's region, else the region of its
    continent (config.yaml map: continents and regions_of); "" for "" or an unknown code."""
    code = code_of(code)
    table = region_table(cfg)
    return table.get(code) or table.get(ALIASES.get(code, ""), "")


def coverage(stories, cfg):
    """Per ISSMGE region (fixed order): stories located there, stories per country, member-society
    countries and how many of them have stories, and the members with none (the gaps)."""
    members = member_countries(cfg)
    rows = {r: {"region": r, "stories": 0, "countries": {}, "members": len(members[r]), "members_covered": 0,
                "gaps": []} for r in REGIONS}
    for s in stories:
        code = canonical(s.get("country"))
        row = rows.get(issmge_region(code, cfg)) if code else None
        if row:
            row["stories"] += 1
            row["countries"][code] = row["countries"].get(code, 0) + 1
    for r, row in rows.items():
        row["members_covered"] = sum(1 for m in members[r] if m in row["countries"])
        row["gaps"] = sorted((m for m in members[r] if m not in row["countries"]), key=country_name)
    return [rows[r] for r in REGIONS]


# ------------------------------------------------------------------ locating archived stories (Claude)
def locate_schema():
    item = {"type": "object",
            "properties": {"id": {"type": "integer"}, "country": {"type": "string"}, "place": {"type": "string"}},
            "required": ["id", "country", "place"], "additionalProperties": False}
    return {"type": "object", "properties": {"stories": {"type": "array", "items": item}},
            "required": ["stories"], "additionalProperties": False}


def unlocated(limit):
    """Archived stories with no "country" key, newest digest first: [(path, digest, story)]."""
    out, digests = [], []
    for path in sorted(site_builder.DIGESTS.glob("*.json"), reverse=True):
        if len(out) >= limit:
            break
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for s in d.get("stories") or []:
            if isinstance(s, dict) and "country" not in s and len(out) < limit:
                out.append((path, d, s))
    return out


def locate_missing(cfg, notes):
    """Give archived stories without a "country" key their country and place (Claude), newest
    first, at most map: locate_per_run per run, and save their digests. A story Claude answers
    for keeps its answer (a "" country means global), so it is never asked again. Returns how
    many were located; without a key it does nothing. The scan calls it before it saves the
    day's digest, so an unexpected error here becomes a note, never a failed scan."""
    import scanner  # (it imports this module's callers, so not at the top)

    try:
        return _locate(cfg, notes, scanner)
    except Exception as ex:
        note = (f"Locating archived stories for the world map stopped ({type(ex).__name__}: "
                f"{scanner.api_message(ex)[:100]}); they are tried again after the next scan.")
        notes.append(note)
        print(note)
        return 0


def _locate(cfg, notes, scanner):
    opts = settings(cfg)
    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    key = scanner.clean_api_key(raw)
    if not key or not opts["locate_per_run"]:
        return 0
    todo = unlocated(opts["locate_per_run"])
    if not todo:
        return 0
    import anthropic  # only needed when a key is configured

    client = anthropic.Anthropic(api_key=key, max_retries=3)
    schema = locate_schema()
    located, changed, failed = 0, {}, None
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        listing = "\n".join(
            f'{i}. [{s.get("source", "")}] {s.get("title_en") or s.get("title", "")}'
            + (f' (original: {s.get("title", "")})' if s.get("title_en") else "")
            + f' :: {str(s.get("summary") or s.get("angle") or "")[:300]}'
            for i, (_, _, s) in enumerate(batch))
        prompt = f"""You are the news-desk assistant of the ISSMGE magazine (International Society for Soil Mechanics and Geotechnical Engineering). For each news story below, say where it happened, for the magazine's world map.

For each story return an object with:
- "id": the number
- "country": the ISO 3166-1 alpha-2 code (e.g. "CO", "GB", "HK") of the country where the event, project or site is, which may differ from the outlet's country; "" if the story is not about one country (a global market report, a general research result, several countries)
- "place": the town, city, region or site named in the story, in English (max 6 words, e.g. "Moniquirá, Boyacá" or "HS2 Chiltern Tunnel"); "" if none is named

Stories:
{listing}"""
        try:
            response = client.messages.create(
                model=opts["model"], max_tokens=16000,
                output_config={"effort": opts["effort"], "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": prompt}])
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as ex:
            why = ("was rejected" if isinstance(ex, anthropic.AuthenticationError)
                   else f"was refused access to {opts['model']}")
            failed = (f"Archived stories were not located on the world map: the ANTHROPIC_API_KEY secret {why} "
                      f"({scanner.api_message(ex)}). " + scanner.describe_key(raw, key))
            break
        except anthropic.APIError as ex:
            failed = f"Locating archived stories for the world map failed for a batch ({scanner.api_message(ex)[:100]})."
            continue
        if response.stop_reason != "end_turn":
            failed = f"Locating archived stories for the world map stopped early for a batch ({response.stop_reason})."
            continue
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            answers = json.loads(text)["stories"]
            if not isinstance(answers, list):
                raise TypeError("no list of stories")
        except (ValueError, KeyError, TypeError) as ex:
            failed = f"Claude's locations for the world map could not be read for a batch ({str(ex)[:80]})."
            continue
        for a in answers:
            try:
                idx = int(a["id"])
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= idx < len(batch) and "country" not in batch[idx][2]:
                path, digest, story = batch[idx]
                story["country"] = scanner.country_code(a.get("country"))
                story["place"] = str(a.get("place") or "")[:80]
                changed[path] = digest
                located += 1
    for path, digest in changed.items():  # same formatting as scanner.save_digest
        path.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
    if failed:
        notes.append(failed)
    print(f"World map: {located} archived {'story' if located == 1 else 'stories'} located"
          + (f"; {failed}" if failed else "."))
    return located


# ------------------------------------------------------------------ the page
def theme_index(order):
    idx = {t: i for i, t in enumerate(order)}
    return lambda t: idx.get(t, idx.get("General", len(order) - 1))


def tally(stories, ti):
    """Per country {code: {theme index: n}}, global {theme: n} and not located {theme: n}."""
    c, g, u = {}, {}, {}
    for s in stories:
        t = str(ti(s.get("theme") or "General"))
        if "country" not in s:
            bucket = u
        else:
            code = canonical(s.get("country"))
            bucket = c.setdefault(code, {}) if code else g
        bucket[t] = bucket.get(t, 0) + 1
    return c, g, u


def periods(ctx):
    """The page's periods, the default (current issue window) first: last 30 days, the whole
    archive, then every other issue window, newest first."""
    windows, digests, today_key = ctx["windows"], ctx["digests"], ctx["today_key"]
    asof, first = digests[0]["date"][:10], digests[-1]["date"][:10]
    nice = site_builder.nice_date
    cur = next((w for w in windows if w["win"]["key"] == today_key), windows[0])

    def make(key, label, sub, ws, lo="", hi="9999"):
        stories = [s for w in ws for s in w["stories"] if lo <= s["_digest"][:10] <= hi]
        return {"key": key, "label": label, "sub": sub, "windows": [w["win"]["key"] for w in ws],
                "lo": lo, "hi": hi if hi != "9999" else "", "stories": stories}

    def win_label(w):
        return f"{w['win']['label']} issue window"

    a30 = (dt.date.fromisoformat(asof) - dt.timedelta(days=29)).isoformat()
    in30 = [w for w in windows if any(d["date"][:10] >= a30 for d in w["digests"])]
    current = cur["win"]["key"] == today_key
    out = [make(cur["win"]["key"], win_label(cur) + (" (current)" if current else " (latest)"),
                cur["win"]["span"] + (f", to {nice(asof)}" if current else ""), [cur]),
           make("30d", "Last 30 days", f"{nice(a30)} – {nice(asof)}", in30, a30),
           make("all", "Whole archive", f"{nice(first)} – {nice(asof)}", windows)]
    out += [make(w["win"]["key"], win_label(w), w["win"]["span"], [w]) for w in windows if w is not cur]
    return out


def story_row(s, ti):
    """A located story as the page keeps it: [code, theme, digest date, title, English title, link,
    source, place, relevance]."""
    return [canonical(s.get("country")), ti(s.get("theme") or "General"), s["_digest"][:10], s.get("title", ""),
            s.get("title_en", ""), site_builder.safe_url(s.get("link")), s.get("source", ""), s.get("place", ""),
            s.get("relevance") or 0]


def script_json(data):
    """JSON safe inside <script>: no "<" survives, so feed text cannot close the element."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def pct(n, total):
    return f"{n / total * 100:.0f}%" if total else "–"


def top_themes(counts, order, n=2):
    best = sorted(((v, int(k)) for k, v in counts.items()), key=lambda x: (-x[0], x[1]))[:n]
    return ", ".join(f"{order[i]} ({v})" for v, i in best)


def kpis_html(n, located, codes, cov, g, u, members):
    total = sum(r["members"] for r in cov)
    covered = sum(r["members_covered"] for r in cov)
    with_member = sum(1 for c in codes if c in members)
    return (site_builder.kpi(f"{n:,}", "Stories in the period", f"{located:,} located in a country")
            + site_builder.kpi(f"{len(codes):,}", "Countries with stories",
                               f"{with_member} with an ISSMGE member society")
            + site_builder.kpi(f"{covered} of {total}" if located else "–", "Member-society countries covered",
                               f"{total - covered} with no stories (the gaps)" if located else "Shown once stories are located")
            + site_builder.kpi(f"{g + u:,}", "Global or not located",
                               f"{g:,} global or several countries · {u:,} not located yet"))


def regions_html(cov, info, located):
    cards = []
    for r, meta in zip(cov, info):
        share = pct(r["stories"], located)
        m, k = r["members"], r["members_covered"]
        gaps = ", ".join(esc(country_name(c)) for c in r["gaps"])
        if not m:
            gap_line = "<p class='mr-gaps'>No member society is listed for this region in config.yaml.</p>"
        elif not located:
            names = ", ".join(esc(n) for n in sorted(country_name(c) for c in meta["members"]))
            gap_line = f"<p class='mr-gaps'><span class='members'>Member-society countries:</span> {names}</p>"
        elif gaps:
            gap_line = f"<p class='mr-gaps'><span>No stories from:</span> {gaps}</p>"
        else:
            gap_line = "<p class='mr-gaps ok'>Every member-society country has stories in this period.</p>"
        extra = []
        if meta["transnational"]:
            extra.append("Also " + ", ".join(esc(t) for t in meta["transnational"]) + " (transnational, not mapped).")
        if meta["to_check"]:
            extra.append(f"ISSMGE lists {meta['societies']} societies here; the list used for the map is still being "
                         "checked against issmge.org.")
        cards.append(
            f"<article class='map-region'><div class='mr-head'><h3>{esc(r['region'])}</h3>"
            f"<button type='button' class='linkbtn mr-zoom' data-zoom='{esc(r['region'])}'>Show on map</button></div>"
            f"<p class='mr-fig'><b>{r['stories']:,}</b><span>{'story' if r['stories'] == 1 else 'stories'}"
            f"{' · ' + share + ' of located' if located else ''}</span></p>"
            f"<p class='mr-cov'><b>{k if located else '–'} of {m}</b> member-society "
            f"{'country' if m == 1 else 'countries'} with stories</p>"
            f"<div class='mr-meter' aria-hidden='true'><i style='width:{(k / m * 100 if m and located else 0):.1f}%'></i></div>"
            f"{gap_line}" + (f"<p class='mr-note'>{' '.join(extra)}</p>" if extra else "") + "</article>")
    return "".join(cards)


def table_rows(c, located, cfg, order, members):
    """Countries with stories and member-society countries without (the gaps), most stories first."""
    codes = set(c) | (set(members) if located else set())
    rows = []
    for code in codes:
        counts = c.get(code, {})
        n = sum(counts.values())
        rows.append((n, country_name(code), code, issmge_region(code, cfg), code in members, top_themes(counts, order)))
    rows.sort(key=lambda r: (-r[0], r[1]))
    return rows


def table_html(rows, located):
    body = []
    for n, name, code, region, member, themes in rows:
        body.append(f"<tr{' class=gap' if member and not n else ''}><th scope='row'><button type='button' class='map-cc' "
                    f"data-cc='{esc(code)}'>{esc(name)}</button></th><td>{esc(region or '–')}</td>"
                    f"<td>{'Yes' if member else 'No'}</td><td class='num'>{n:,}</td><td class='num'>{pct(n, located)}</td>"
                    f"<td>{esc(themes) if n else '<span class=gap-tag>No stories</span>'}</td></tr>")
    if not body:
        body.append("<tr><td colspan='6' class='viz-empty'>No located stories in this period.</td></tr>")
    return ("<div class='table-wrap'><table class='overview viz-tbl map-tbl'><thead><tr><th scope='col'>Country</th>"
            "<th scope='col'>ISSMGE region</th><th scope='col'>Member society</th><th scope='col' class='num'>Stories</th>"
            "<th scope='col' class='num'>Share</th><th scope='col'>Top themes</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table></div>")


def panel_html(rows, label):
    ranked = [r for r in rows if r[0]][:TOP_LIST]
    if not ranked:
        return ("<div class='mp-head'><h3>Countries</h3><p>No located stories in this period yet. Select any country "
                "on the map to see whether it has a member society.</p></div>")
    top = ranked[0][0]
    items = "".join(f"<li><button type='button' class='map-cc' data-cc='{esc(code)}'><span class='mp-n'>{esc(name)}</span>"
                    f"<span class='mp-bar'><i style='width:{n / top * 100:.1f}%'></i></span><b>{n:,}</b></button></li>"
                    for n, name, code, *_ in ranked)
    more = sum(1 for r in rows if r[0]) - len(ranked)
    return (f"<div class='mp-head'><h3>Countries with the most stories</h3><p>{esc(label)}. Select a country on the map "
            "or below to list its stories.</p></div>"
            f"<ol class='mp-top'>{items}</ol>"
            + (f"<p class='mp-foot'>{more} more {'country' if more == 1 else 'countries'} in the table view.</p>" if more > 0 else ""))


def map_body(ctx):
    cfg, digests, order = ctx["cfg"], ctx["digests"], list(ctx["order"])
    lede = ("Where the archive's stories happen: the country Claude reads in each story (the site, project or event, "
            "not the outlet), with the ISSMGE regions and the member-society countries that have no stories in the "
            "period, so regional gaps stand out.")
    if not digests:
        return (site_builder.hero("World map", "World map", lede)
                + "<p class='empty'>The archive is empty. The map fills in after the first scan.</p>")
    ti = theme_index(order)
    info = region_info(cfg)
    members = {c for r in info for c in r["members"]}
    opts = settings(cfg)
    ps = periods(ctx)
    data_periods = []
    for p in ps:
        c, g, u = tally(p["stories"], ti)
        data_periods.append({"k": p["key"], "l": p["label"], "sub": p["sub"], "w": p["windows"], "a": p["lo"],
                             "b": p["hi"], "n": len(p["stories"]), "c": c, "g": g, "u": u})
    d0, p0 = data_periods[0], ps[0]
    located_rows = [s for s in p0["stories"] if canonical(s.get("country"))]
    embed = located_rows if len(located_rows) <= opts["embed_limit"] else None
    table = region_table(cfg)
    data = {
        "themes": order, "tc": [site_builder.theme_color(t) for t in order],
        "regions": [{"n": r["name"], "m": r["members"], "s": r["societies"], "t": r["transnational"], "x": r["to_check"]}
                    for r in info],
        "rc": {code: REGIONS.index(region) for code, region in table.items() if region},
        "names": {code: country_name(code) for code in sorted(set(world()["countries"]) | members)},
        "alias": ALIASES, "periods": data_periods, "asof": digests[0]["date"][:10],
        "stories": [story_row(s, ti) for s in embed] if embed is not None else None,
    }

    # the default period (all themes) is rendered here too, so the page reads well before and without the script
    c, g, u = d0["c"], sum(d0["g"].values()), sum(d0["u"].values())
    located = sum(sum(v.values()) for v in c.values())
    cov = coverage(located_rows, cfg)
    rows = table_rows(c, located, cfg, order, members)
    options = [f"<option value='{esc(p['k'])}'>{esc(p['l'])}</option>" for p in data_periods[:3]]
    if len(data_periods) > 3:
        options.append("<optgroup label='Issue windows'>" + "".join(
            f"<option value='{esc(p['k'])}'>{esc(p['l'])} ({esc(p['sub'])})</option>" for p in data_periods[3:]) + "</optgroup>")
    themes = "".join(f"<option value='{i}'>{esc(t)}</option>" for i, t in enumerate(order))
    zoom = "".join(f"<button type='button' aria-pressed='{'true' if not r else 'false'}' data-zoom='{esc(r)}'>{esc(r or 'World')}</button>"
                   for r in [""] + REGIONS)
    zoom_opts = "".join(f"<option value='{esc(r)}'>{esc(r or 'World')}</option>" for r in [""] + REGIONS)
    note = ""
    if d0["n"] and not located:
        note = (f"None of this period's {d0['n']:,} stories has a location yet. Claude reads each story's country "
                "during the scan; stories archived earlier are located in batches after the next scan.")
    elif not d0["n"]:
        note = "No stories in this period."
    elif u:  # the same words as map.js
        note = (f"{u:,} {'story' if u == 1 else 'stories'} in this period {'has' if u == 1 else 'have'} no location "
                f"yet; {'it is' if u == 1 else 'they are'} located after the next scan. Member-society countries are "
                "marked as gaps only from the stories already located.")
    count = f"{d0['n']:,} {'story' if d0['n'] == 1 else 'stories'} · {len(c)} {'country' if len(c) == 1 else 'countries'}"
    out = [
        site_builder.hero(f"World map · as of {esc(site_builder.nice_date(data['asof']))}", "World map", lede),
        "<div class='toolbar map-tools' role='group' aria-label='What the map shows'>"
        f"<label class='field'><span>Period</span><select id='map-period'>{''.join(options)}</select></label>"
        f"<label class='field'><span>Theme</span><select id='map-theme'><option value='-1'>All themes</option>{themes}</select></label>"
        f"<span class='f-count' id='map-count' aria-live='polite'>{esc(count)}</span></div>",
        f"<div class='stats map-kpis' id='map-kpis'>{kpis_html(d0['n'], located, list(c), cov, g, u, members)}</div>",
        "<figure class='viz map-fig' id='map-fig'><div class='viz-head'><div><h3>Stories by country</h3>"
        f"<p id='map-sub'>{esc(d0['l'])} · {esc(d0['sub'])}. Circle area shows the number of stories.</p></div>"
        "<div class='viz-toggle' role='group' aria-label='View'><button type='button' aria-pressed='true' data-view='chart'>Map</button>"
        "<button type='button' aria-pressed='false' data-view='table'>Table</button></div></div>"
        "<div class='viz-chart'>"
        f"<div class='map-zoom' role='group' aria-label='Zoom to a region'>{zoom}</div>"
        f"<label class='field map-zoom-sel'><span>Zoom to</span><select id='map-zoom-sel'>{zoom_opts}</select></label>"
        "<div class='map-grid'><div class='map-main'>"
        "<div class='map-canvas' id='map-canvas' tabindex='0' role='application' aria-roledescription='map' "
        "aria-label='World map of stories by country. Arrow keys move between countries, Enter lists the stories of the "
        "country shown, Escape closes. The Table button shows every number.'>"
        "<p class='map-loading'>Loading the map…</p></div>"
        f"<p class='map-note' id='map-note'{'' if note else ' hidden'}>{esc(note)}</p>"
        "<div class='map-legend' id='map-legend'></div><p class='map-sr' id='map-live' aria-live='polite'></p></div>"
        f"<aside class='map-panel' id='map-panel' aria-label='Stories by country'>{panel_html(rows, d0['l'])}</aside></div></div>"
        f"<div class='viz-table' id='map-table' hidden>{table_html(rows, located)}</div>"
        f"<figcaption class='map-credit'>{esc(CREDIT)} A story's country is where its event, project or site is, as "
        "Claude read it; the Google News edition that found a story is not used here.</figcaption></figure>",
        "<h2 class='section-h'>ISSMGE regions</h2><p class='hint'>Stories located in each of ISSMGE's six regions in the "
        "period, and how many of the region's member-society countries have at least one. Countries without a member "
        "society count towards the region of their continent; ISSMGE's South America region also covers Central America "
        "and the Caribbean.</p>",
        f"<div class='map-regions' id='map-regions'>{regions_html(cov, info, located)}</div>",
        f"<script type='application/json' id='map-data'>{script_json(data)}</script>",
        "<noscript><p class='empty'>The map needs JavaScript; the figures above and the regions below are for the "
        "current issue window.</p></noscript>",
    ]
    return "".join(out)


def build(ctx):
    cfg = ctx["cfg"]
    site_builder.write(site_builder.DOCS / "map.html", site_builder.page(
        cfg, "World map", map_body(ctx), "", "map",
        "Where the geotechnical stories happen, by country, and the ISSMGE member societies with no stories in the period",
        head="<script src='assets/map.js' defer></script>"))


if __name__ == "__main__":
    path = os.environ.get("SCANNER_CONFIG") or str(site_builder.ROOT / "config.yaml")
    config = yaml.safe_load(open(path, encoding="utf-8").read())
    run_notes = []
    n = locate_missing(config, run_notes)
    for line in run_notes:
        print(line)
    sys.exit(0 if not run_notes or n else 1)
