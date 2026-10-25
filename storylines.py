#!/usr/bin/env python3
"""
Developing stories: follow-up reports linked to the original event (a dam
failure, then the inquiry, then the repair), and the page docs/developing.html.

Every scan, link() compares the day's stories with the archive of the last
year. Claude (model) decides which new story follows up an earlier one about
the same real-world event, project or site, names the stage the story has
reached and says whether it is sure; the cases it is unsure of are read again,
each against its own closest earlier stories, by a more capable model
(check_model), whose decision stands. Without Claude a cautious headline match
links reports found within a month. A follow-up gets three keys in its digest:

    "storyline":        "sl-<id of the earliest story of the event>"
    "stage":            one of STAGES
    "storyline_title":  a short neutral name, e.g. "Moniquirá landslide, Colombia (Oct 2026)"

The earliest story is never rewritten in its old digest: a developing story is
every story whose "storyline" is sl-X plus the story whose id is X. No other
file keeps any state.
"""
import datetime as dt
import json
import math
import os
import re
import unicodedata

import scanner
import site_builder

esc = site_builder.esc
PREFIX = "sl-"
STAGES = ["Event", "Response & recovery", "Investigation & inquiry", "Repair & reconstruction",
          "Legal & policy", "Update"]
EFFORTS = ("low", "medium", "high", "xhigh", "max")
CONFIDENCE = ["sure", "unsure"]
DEFAULTS = {"enabled": True, "model": "claude-sonnet-5-5", "effort": "low", "check_model": "claude-opus-5-5",
            "check_effort": "low", "max_checks": 8, "lookback_days": 365, "max_candidates": 400,
            "heuristic_days": 30, "active_days": 90}
OFF = ("", "off", "no", "none", "false", "0")  # check_model: any of these (or left blank) turns the second check off
PER_STORY = 25     # closest earlier stories kept for each new story before the max_candidates cap
FOLD_AFTER = 6     # timelines longer than this show the first report and the latest four until opened
MAX_TOKENS = 16000


class LinkError(Exception):
    """Claude could not link the day's stories; the message says why, for the scan's notes."""


def settings(cfg):
    """The storylines: section of config.yaml, with defaults. A value that cannot be read is
    reported and its default used, so a typo there never stops a scan or the site build."""
    sec = cfg.get("storylines") if isinstance(cfg, dict) else None
    sec = sec if isinstance(sec, dict) else {}
    out = {}
    for name, default in DEFAULTS.items():
        value = sec.get(name)
        if name == "check_model" and name in sec and (value is None or value is False
                                                     or str(value).strip().lower() in OFF):
            out[name] = ""  # no second check: the first reading stands for every story
        elif value is None:
            out[name] = default
        elif isinstance(default, bool):
            out[name] = value if isinstance(value, bool) else str(value).strip().lower() not in ("false", "no", "off", "0")
        elif isinstance(default, str):
            out[name] = (str(value).strip().lower() if name.endswith("effort") else str(value).strip()) or default
        else:
            try:
                if isinstance(value, bool):
                    raise ValueError
                out[name] = max(0 if name == "max_checks" else 1, int(value))  # max_checks: 0 checks nothing
            except (TypeError, ValueError):
                print(f"config.yaml, storylines: {name}: {value!r} is not a whole number; using {default}.")
                out[name] = default
    for name in ("effort", "check_effort"):
        if out[name] not in EFFORTS:
            print(f"config.yaml, storylines: {name}: {out[name]!r} is not one of {', '.join(EFFORTS)}; "
                  f"using {DEFAULTS[name]}.")
            out[name] = DEFAULTS[name]
    return out


def model_name(model):
    """"Claude Opus 5.5" for claude-opus-5-5, for the pages; any other name as it is."""
    m = re.fullmatch(r"claude-([a-z]+)-(\d+)(?:-(\d))?", str(model or "").strip())
    return f"Claude {m.group(1).title()} {m.group(2)}{'.' + m.group(3) if m.group(3) else ''}" if m else str(model or "")


def clip(text, n):
    """One line of at most n characters."""
    text = " ".join(site_builder.CONTROL_CHARS.sub(" ", str(text or "")).split())
    return text if len(text) <= n else text[:n - 1].rstrip() + "…"


def headline(s):
    """The English headline: Claude's translation when the original is in another language."""
    return s.get("title_en") or s.get("title") or ""


def iso_date(text):
    try:
        return dt.date.fromisoformat(str(text or "")[:10])
    except ValueError:
        return None


def story_date(s, digest_date):
    """The day a report was published, or the day the scan found it when the feed's date is
    missing or implausible (more than a month before the digest, or after it)."""
    found = iso_date(digest_date)
    pub = iso_date(s.get("published"))
    if found and pub and found - dt.timedelta(days=30) <= pub <= found + dt.timedelta(days=1):
        return pub
    return found or pub or dt.date.min


def storyline_of(s):
    """The developing story an earlier story belongs to: its own, or the one it would start."""
    sl = s.get("storyline")
    return sl if isinstance(sl, str) and sl.startswith(PREFIX) else PREFIX + str(s.get("id", ""))


# ------------------------------------------------------------------ comparing headlines
def plain(text):
    """Accents of Latin letters dropped (Bogotá = Bogota), so a translated headline still
    matches the original's place names."""
    out = []
    for c in unicodedata.normalize("NFD", text or ""):
        if unicodedata.category(c) == "Mn" and out and "a" <= out[-1].lower() <= "z":
            continue
        out.append(c)
    return unicodedata.normalize("NFC", "".join(out))


def marks(s, topic):
    """What tells one event from another, from the original headline, its English translation
    and the place Claude read: significant words, capitalised names and place words (keyword
    words such as landslide or tunnel are left out: every landslide story says landslide).
    "variants" are (headline, words, names) triples in the shape scanner.same_event() takes."""
    place = {plain(w) for w in scanner.title_words(scanner.title_norm(s.get("place") or ""), topic)}
    variants, words, names = [], set(), set()
    for head in {s.get("title") or "", s.get("title_en") or ""} - {""}:
        w = {plain(x) for x in scanner.title_words(scanner.title_norm(head), topic)} | place
        n = {plain(x) for x in scanner.title_names(head, topic)}
        variants.append((plain(scanner.title_norm(head)), w, n))
        words |= w
        names |= n
    return {"words": words - scanner.KOREAN_NEWS_WORDS, "names": names, "place": place,
            "country": scanner.country_code(s.get("country")), "variants": variants}


def conflict(a, b, places=True):
    """Both stories are located and their countries (or, with places, their named places) differ."""
    if a["country"] and b["country"] and a["country"] != b["country"]:
        return True
    return places and bool(a["place"] and b["place"] and not a["place"] & b["place"])


def closeness(a, b, idf):
    """How much two stories have in common, rare words counting most; 0 when they are in
    different countries or have nothing to go on: a single common word in common or, when
    their named places differ, no shared name or rare word. (Claude names a place at any
    scale, a town, a region or a site: Amersham and the Chiltern Tunnel can be one story.)"""
    shared = a["words"] & b["words"]
    if not shared or conflict(a, b, places=False):
        return 0
    rare = any(idf.get(w, 0) >= idf.get("", 0) for w in shared)
    named = shared & (a["names"] | b["names"] | a["place"] | b["place"])
    if not (named or rare) and (len(shared) < 2 or conflict(a, b)):
        return 0
    return sum(idf.get(w, 1) * (1.5 if w in a["place"] or w in b["place"] else 1) for w in shared)


def weights(items):
    """Inverse document frequency of each word over the stories compared; key "" holds the
    weight of a word found in 0.5% of them, above which a word counts as rare."""
    df = {}
    for m in items:
        for w in m["words"]:
            df[w] = df.get(w, 0) + 1
    n = max(len(items), 1)
    idf = {w: math.log(1 + n / c) for w, c in df.items()}
    idf[""] = math.log(1 + n / max(3, n * 0.005))
    return idf


# ------------------------------------------------------------------ linking the day's stories
def archive(today, opts, new_ids):
    """Earlier stories within lookback_days (today's earlier run included, the new stories
    themselves never), each once, with the date of its digest; and the name of every
    developing story in the archive, the latest one given."""
    earliest = today - dt.timedelta(days=opts["lookback_days"])
    earlier, seen, titles = [], set(), {}
    for d in sorted(site_builder.load_digests(), key=lambda d: d["date"]):
        day = iso_date(d.get("date"))
        for s in d["stories"]:
            if s.get("storyline") and s.get("storyline_title"):
                titles[s["storyline"]] = clip(s["storyline_title"], 90)
            if (day and earliest <= day <= today and s.get("id") and s["id"] not in new_ids
                    and s["id"] not in seen):
                seen.add(s["id"])
                earlier.append(dict(s, _digest=d["date"]))
    return earlier, titles


def candidates(new, earlier, nm, em, idf, opts):
    """For each new story the closest earlier stories (up to PER_STORY), and all of them
    together within max_candidates, taken in turns so every new story keeps its best ones.
    Returns the new stories that have any, the earlier stories chosen, oldest first, and
    {new story: its own earlier stories among those chosen, the closest first} (a second
    check shows each unsure story only its own)."""
    index = {}  # word -> earlier stories that have it, so only stories sharing a word are compared
    for j, m in enumerate(em):
        for w in m["words"]:
            index.setdefault(w, []).append(j)
    ranked = []
    for i in range(len(new)):
        near = {j for w in nm[i]["words"] for j in index.get(w, ())}
        scored = [(closeness(nm[i], em[j], idf), earlier[j]["_digest"], j) for j in near]
        ranked.append([j for score, _, j in sorted(scored, reverse=True) if score > 0][:PER_STORY])
    chosen, order = set(), []
    for turn in range(PER_STORY):
        for picks in ranked:
            if turn < len(picks) and picks[turn] not in chosen and len(chosen) < opts["max_candidates"]:
                chosen.add(picks[turn])
                order.append(picks[turn])
    own = {i: [j for j in ranked[i] if j in chosen] for i in range(len(new)) if ranked[i]}
    return list(own), sorted(order, key=lambda j: earlier[j]["_digest"]), own


def where(s):
    place = clip(s.get("place"), 60)
    country = scanner.country_code(s.get("country"))
    return ", ".join(x for x in (place, country) if x) or ("global" if "country" in s else "not located")


def new_line(n, s, today):
    parts = [f"N{n}", today.isoformat(), s.get("theme", ""), clip(headline(s), 200)
             + (f" (original: {clip(s['title'], 160)})" if s.get("title_en") else ""),
             clip(s.get("source"), 60), where(s)]
    about = s.get("angle") or s.get("summary")
    if about:
        parts.append(clip(about, 220))
    return " | ".join(parts)


def earlier_line(n, s, titles):
    parts = [f"E{n}", str(s["_digest"]), s.get("theme", ""), clip(headline(s), 200)
             + (f" (original: {clip(s['title'], 160)})" if s.get("title_en") else ""),
             clip(s.get("source"), 60), where(s)]
    title = titles.get(storyline_of(s))
    if title:
        parts.append(f'developing story: "{title}"')
    return " | ".join(parts)


INTRO = ("You are the news-desk assistant of the ISSMGE magazine (International Society for Soil Mechanics and "
         "Geotechnical Engineering). The editors follow developing stories: a geotechnical event, project or site "
         "that is reported again later. A dam fails, then an inquiry reports, then the repair begins; a landslide is "
         "followed by the clean-up, a lawsuit and new slope works; a tunnel project goes from contract award to "
         "breakthrough.")
LINES = ("number | date | theme | headline | source | place and ISO country code | for new stories, the magazine "
         "angle or summary; for earlier stories, the name of the developing story they already belong to, if any")


def fields(among):
    """What Claude gives for every new story; among: which earlier stories "follows" may name."""
    stages = "; ".join(f'"{s}"' for s in STAGES)
    return f"""- "follows": the earlier story it follows up{among}, only when both are clearly about the same real-world event, project or site: the same landslide, dam, tunnel, building, mine, slope or works, in the same place. A similar hazard in the same country or region is not enough, nor are two separate storms, floods or earthquakes, two projects of the same company or two stories about the same kind of problem. If several earlier stories match, give the most recent one. Otherwise "".
- "stage": what the new story reports, one of {stages}. "Event" is the event itself (or more reports of it in the first days); "Response & recovery" is rescue, evacuation, emergency works, clean-up or aid; "Investigation & inquiry" is the cause, an investigation, an inquiry or an expert report; "Repair & reconstruction" is repair, rebuilding, permanent works or reopening; "Legal & policy" is a court case, charges, compensation or new rules and standards; "Update" is anything else, such as progress on a project.
- "storyline_title": a short neutral name for the event, project or site in English, at most 8 words, saying what and where, with the month and year it began for an event, e.g. "Moniquirá landslide, Colombia (Oct 2026)" or "HS2 Chiltern Tunnel, UK". If the earlier story already belongs to a developing story, repeat that name exactly. "" when "follows" is ""."""


def build_prompt(new_lines, earlier_lines, today):
    """The first reading: every new story that has close earlier stories, against all of them."""
    return f"""{INTRO}

Below are today's new stories (N1, N2, ...) and earlier stories from the archive (E1, E2, ...), one per line: {LINES}.

For every new story return an object with:
- "story": its number, e.g. "N3"
{fields(', e.g. "E12"')}
- "confidence": "sure" when the answer is clear either way, as it is for most stories; "unsure" when the new story might be about the same event, project or site as an earlier story but the evidence is not clear either way: the same region but different place names, only general hazard words in common, a translated headline that may or may not name the same site, a possible follow-up whose project name differs. Give "unsure" whether or not you linked the story: those stories are read again more closely.

Today is {today.isoformat()}.

New stories:
{chr(10).join(new_lines)}

Earlier stories:
{chr(10).join(earlier_lines)}"""


def build_check_prompt(blocks, today):
    """The second reading: only the unsure stories, each followed by its own earlier stories."""
    return f"""{INTRO}

A first reading could not tell whether the new stories below (N1, N2, ...) follow up an earlier story from the archive. Under each new story are the earlier stories closest to it (E1, E2, ...), one per line: {LINES}. Read each new story closely against its own earlier stories and decide. Weigh the details: places at every scale (a town, its district and its region can be one place; two towns in the same region are not), the kind of event, the names of projects, owners and contractors, the dates, and headlines translated from another language, which may spell a place or a project differently.

For every new story return an object with:
- "story": its number, e.g. "N2"
{fields(', one of those listed under it, e.g. "E4"')}

Today is {today.isoformat()}.

{(chr(10) + chr(10)).join(blocks)}"""


def link_schema(check=False):
    """The answer: one object per new story; the first reading also says whether it is sure."""
    props = {"story": {"type": "string"}, "follows": {"type": "string"},
             "stage": {"type": "string", "enum": STAGES}, "storyline_title": {"type": "string"}}
    if not check:
        props["confidence"] = {"type": "string", "enum": CONFIDENCE}
    item = {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}
    return {"type": "object", "properties": {"links": {"type": "array", "items": item}},
            "required": ["links"], "additionalProperties": False}


def ask_claude(prompt, model, effort, schema, key, raw, check=False):
    """Claude's answer as a dict, or LinkError with a clear reason (shorter for the second check,
    whose key has just worked for the first reading)."""
    import anthropic  # only needed when a key is configured

    client = anthropic.Anthropic(api_key=key, max_retries=3)
    try:
        response = client.messages.create(
            model=model, max_tokens=MAX_TOKENS,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": prompt}])
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as ex:
        why = ("was rejected" if isinstance(ex, anthropic.AuthenticationError)
               else f"was refused access to {model}")
        raise LinkError(f"the ANTHROPIC_API_KEY secret {why} ({scanner.api_message(ex)})."
                        + ("" if check else " " + scanner.describe_key(raw, key)
                           + " Change the key in Settings → Secrets and variables → Actions.")) from None
    except anthropic.APIError as ex:
        raise LinkError(f"Claude returned an error or could not be reached ({scanner.api_message(ex)[:100]}).") from None
    if response.stop_reason == "refusal":
        raise LinkError("Claude declined to compare the stories.")
    if response.stop_reason != "end_turn":
        raise LinkError(f"Claude's answer stopped early ({response.stop_reason}).")
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        answer = json.loads(text)
        if not isinstance(answer, dict) or not isinstance(answer.get("links"), list):
            raise ValueError("no list of links")
        return answer
    except ValueError as ex:
        raise LinkError(f"Claude's answer could not be read ({str(ex)[:80]}).") from None


REF = re.compile(r"\s*([NE])\s*(\d+)\s*", re.I)


def number(ref, letter, n):
    """The place (from 0) that "N3" or "E12" stands for in a list of n, or None."""
    m = REF.fullmatch(str(ref or ""))
    if not m or m.group(1).upper() != letter:
        return None
    k = int(m.group(2)) - 1
    return k if 0 <= k < n else None


def resolve(ref, table, letter):
    """The item that "N3" or "E12" stands for in table, or None."""
    k = number(ref, letter, len(table))
    return None if k is None else table[k]


def default_title(s):
    """A name for a developing story when none was given: the first report's headline and month."""
    day = iso_date(s.get("_digest")) or iso_date(s.get("published"))
    return clip(headline(s), 70) + (f" ({site_builder.MONTHS[day.month - 1]} {day.year})" if day else "")


def mark(s, earlier, stage, title, titles):
    """Join s to the developing story of the earlier story it follows."""
    sl = storyline_of(earlier)
    s["storyline"] = sl
    s["stage"] = stage if stage in STAGES else "Update"
    s["storyline_title"] = clip(title if isinstance(title, str) else "", 90) or titles.get(sl) or default_title(earlier)


def read_links(answer, table_n, table_e, allowed=None):
    """Claude's answer as {place of the new story in table_n: decision}, each decision {"follows": the
    earlier story or None, "stage", "title", "unsure", "valid"}. Unknown story numbers are ignored and
    the first answer for a story counts. An answer is not valid when "follows" names a number not in
    table_e (or, with allowed = {story: places in table_e}, not one of the story's own earlier stories)
    or the story itself: the story is then left unlinked, and counted unsure."""
    out = {}
    for item in answer.get("links") or []:
        if not isinstance(item, dict):
            continue
        k = number(item.get("story"), "N", len(table_n))
        if k is None or k in out:
            continue
        ref = str(item.get("follows") or "").strip()
        p = number(ref, "E", len(table_e)) if ref else None
        valid = not ref or (p is not None and table_e[p].get("id") != table_n[k].get("id")
                            and (allowed is None or p in allowed[k]))
        out[k] = {"follows": table_e[p] if valid and p is not None else None, "stage": item.get("stage"),
                  "title": item.get("storyline_title"), "valid": valid,
                  "unsure": item.get("confidence") == "unsure" or not valid}
    return out


def same_link(a, b):
    """Two decisions join the same developing story (or both join none)."""
    return (a is None) == (b is None) and (a is None or storyline_of(a) == storyline_of(b))


def rank_of(s):
    try:
        return float(s.get("rank") or 0)
    except (TypeError, ValueError):
        return 0.0


def recheck(decided, table_n, table_e, own, titles, today, opts, key, raw, notes):
    """Have check_model read again the new stories the first reading was unsure of (at most
    max_checks, the best-ranked first), each against its own earlier stories and the one first
    chosen for it. Its valid answers replace the first reading's in decided; when the check fails,
    the first reading stands and a note says why. Returns the log's account of it."""
    first, check = opts["model"], opts["check_model"]
    unsure = sorted((k for k, d in decided.items() if d["unsure"] and (own[k] or d["follows"] is not None)),
                    key=lambda k: (-rank_of(table_n[k]), k))
    if not unsure:
        return "; no unsure cases"
    cases = site_builder.count(len(unsure), "unsure case")
    if not check or not opts["max_checks"]:
        return f"; {cases} not re-checked ({'check_model is off' if not check else 'max_checks is 0'})"
    chosen, more = unsure[:opts["max_checks"]], len(unsure) - opts["max_checks"]
    checked = site_builder.count(len(chosen), "unsure case")
    tail = (f"; {site_builder.count(more, 'more unsure case')} kept as {first} decided "
            f"(max_checks: {opts['max_checks']})" if more > 0 else "")
    where = {id(e): p for p, e in enumerate(table_e)}
    try:
        blocks, check_n, check_e, allowed, renumber = [], [], [], {}, {}
        for n, k in enumerate(chosen):
            picked = decided[k]["follows"]
            mine = sorted(set(own[k]) | ({where[id(picked)]} if picked is not None else set()))
            for p in mine:
                if p not in renumber:
                    renumber[p] = len(check_e)
                    check_e.append(table_e[p])
            allowed[n] = {renumber[p] for p in mine}
            check_n.append(table_n[k])
            blocks.append(new_line(n + 1, table_n[k], today) + f"\nEarlier stories for N{n + 1}:\n"
                          + "\n".join(earlier_line(renumber[p] + 1, table_e[p], titles) for p in mine))
        answer = ask_claude(build_check_prompt(blocks, today), check, opts["check_effort"],
                            link_schema(check=True), key, raw, check=True)
        redo = read_links(answer, check_n, check_e, allowed)
    except Exception as ex:  # a failed check keeps the first reading: it must not cost the day's links
        why = str(ex) if isinstance(ex, LinkError) else f"{type(ex).__name__}: {str(ex)[:120]}"
        note = (f"Developing stories: {check} could not re-check {checked} ({why.rstrip('.')}); "
                f"{first}'s first reading was kept for them.")
        notes.append(note)
        print(note)
        return f"; {checked} kept as {first} decided (the check by {check} failed){tail}"
    confirmed = changed = 0
    for n, k in enumerate(chosen):
        d = redo.get(n)
        if not d or not d["valid"]:
            continue  # no usable answer for this story: the first reading stands
        if same_link(d["follows"], decided[k]["follows"]):
            confirmed += 1
            if not (isinstance(d["title"], str) and d["title"].strip()):
                d = dict(d, title=decided[k]["title"])  # confirmed without a name: the first reading's name
        else:
            changed += 1
        decided[k] = d
    unanswered = len(chosen) - confirmed - changed
    return (f"; {checked} re-checked by {check} ({confirmed} confirmed, {changed} changed"
            + (f", {unanswered} not answered and kept" if unanswered else "") + f"){tail}")


def claude_links(new, idx, earlier, picks, own, titles, today, opts, key, raw, notes):
    """Ask Claude which new stories follow up an earlier one, then check_model about the cases
    Claude was unsure of; the number linked and the log's account of the check."""
    table_n = [new[i] for i in idx]
    table_e = [earlier[j] for j in picks]
    prompt = build_prompt([new_line(k + 1, s, today) for k, s in enumerate(table_n)],
                          [earlier_line(k + 1, s, titles) for k, s in enumerate(table_e)], today)
    decided = read_links(ask_claude(prompt, opts["model"], opts["effort"], link_schema(), key, raw),
                         table_n, table_e)
    place = {j: p for p, j in enumerate(picks)}
    checked = recheck(decided, table_n, table_e, {k: [place[j] for j in own[i]] for k, i in enumerate(idx)},
                      titles, today, opts, key, raw, notes)
    linked = 0
    for k, d in sorted(decided.items()):
        if d["follows"] is not None:
            mark(table_n[k], d["follows"], d["stage"], d["title"], titles)
            linked += 1
    return linked, checked


def kinds_of(cfg):
    """A function giving the kinds of event a story's headlines name (the English keyword concepts:
    landslide, sinkhole, tunnel …, whatever the language), worked out once per story."""
    compiled, seen = scanner.compile_keywords(cfg), {}

    def kinds(s):
        if id(s) not in seen:
            found = set()
            for head in {s.get("title") or "", s.get("title_en") or ""} - {""}:
                found.update(scanner.keyword_score(head, cfg, compiled)[1])
            seen[id(s)] = found
        return seen[id(s)]
    return kinds


def heuristic_links(new, earlier, nm, em, idf, titles, today, opts, kinds=None):
    """Without Claude: a new story follows an earlier one from another day within heuristic_days
    when the headlines would count as one event for the scanner (scanner.same_event: the same
    names and most significant words), the countries and places Claude read, if any, agree, and
    they name the same kind of event (kinds): a sinkhole in a city is not a follow-up of a landslide
    there, though the two headlines share the city, the rain and the residents."""
    linked = 0
    since = today - dt.timedelta(days=opts["heuristic_days"])
    for i, s in enumerate(new):
        best = None
        for j, e in enumerate(earlier):
            day = iso_date(e["_digest"])
            if not day or not since <= day < today or conflict(nm[i], em[j]):
                continue
            if not any(scanner.same_event(a, b) for a in nm[i]["variants"] for b in em[j]["variants"]):
                continue
            if kinds and kinds(s) and kinds(e) and not kinds(s) & kinds(e):
                continue
            score = (closeness(nm[i], em[j], idf), e["_digest"])
            if best is None or score > best[0]:
                best = (score, e)
        if best:
            e = best[1]
            mark(s, e, "Update", titles.get(storyline_of(e), ""), titles)
            linked += 1
    return linked


def link(stories, now, cfg, notes):
    """Mark today's stories that follow up an earlier archived story about the same event,
    project or site. Returns the number linked; never stops the scan."""
    try:
        return _link(stories, now, cfg, notes)
    except Exception as ex:  # a fault here must not cost the day's digest
        note = f"Developing stories skipped for this run ({type(ex).__name__}: {str(ex)[:120]})."
        notes.append(note)
        print(note)
        return 0


def _link(stories, now, cfg, notes):
    opts = settings(cfg)
    new = [s for s in stories if s.get("id") and not s.get("storyline")]
    if not opts["enabled"] or not new:
        return 0
    today = now.date() if isinstance(now, dt.datetime) else now
    earlier, titles = archive(today, opts, {s["id"] for s in stories})
    if not earlier:
        return 0
    topic = scanner.topic_words(cfg)
    nm = [marks(s, topic) for s in new]
    em = [marks(s, topic) for s in earlier]
    idf = weights(nm + em)
    idx, picks, own = candidates(new, earlier, nm, em, idf, opts)
    if not idx:
        print("Developing stories: no earlier story in the archive is close to today's stories.")
        return 0

    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    key = scanner.clean_api_key(raw)
    linked, checked = None, ""
    if not key:
        print("Developing stories: no ANTHROPIC_API_KEY, so follow-ups were matched by headline only.")
    else:
        try:
            linked, checked = claude_links(new, idx, earlier, picks, own, titles, today, opts, key, raw, notes)
            how = f"{opts['model']} compared {len(idx)} of them with {len(picks)} of {len(earlier)} archived stories"
        except LinkError as ex:
            note = f"Developing stories: {ex} Follow-ups were matched by headline only."
            notes.append(note)
            print(note)
    if linked is None:
        linked = heuristic_links(new, earlier, nm, em, idf, titles, today, opts, kinds_of(cfg))
        how = f"headlines compared with the last {opts['heuristic_days']} days"
    # e.g. "6 of today's 40 stories follow up an earlier one (claude-sonnet-5-5 compared …); 3 unsure
    # cases re-checked by claude-opus-5-5 (2 confirmed, 1 changed)."
    print(f"Developing stories: {linked} of today's {len(new)} stories follow up an earlier one ({how}){checked}.")
    return linked


# ------------------------------------------------------------------ developing stories in the archive
def _collect(digests):
    """{storyline id: [(story, digest date), ...]} for every developing story with two or more
    different reports in the loaded digests: the stories that name it plus its first story."""
    by_id, members = {}, {}
    for d in digests:
        for s in d.get("stories") or []:
            sid = str(s.get("id") or "")
            by_id.setdefault(sid, []).append((s, d["date"]))
            sl = s.get("storyline")
            if isinstance(sl, str) and sl.startswith(PREFIX) and len(sl) > len(PREFIX) and sl != PREFIX + sid:
                members.setdefault(sl, []).append((s, d["date"]))
    out = {}
    for sl, items in members.items():
        items = items + by_id.get(sl[len(PREFIX):], [])
        if len({str(s.get("id") or "") for s, _ in items}) >= 2:
            out[sl] = sorted(items, key=lambda x: (story_date(x[0], x[1]), x[1]))
    return out


def _reports(items):
    """Each report once (its first digest), oldest first."""
    seen, out = set(), []
    for s, day in sorted(items, key=lambda x: x[1]):
        sid = str(s.get("id") or "")
        if sid not in seen:
            seen.add(sid)
            out.append((s, day))
    return sorted(out, key=lambda x: (story_date(x[0], x[1]), x[1]))


def _title(sl, reports):
    """The latest name Claude gave the developing story, else its first headline."""
    names = [s.get("storyline_title") for s, _ in reports if s.get("storyline") == sl and s.get("storyline_title")]
    return clip(names[-1], 90) if names else default_title(dict(reports[0][0], _digest=reports[0][1]))


def _stage(s, sl):
    if s.get("storyline") == sl:
        return s.get("stage") if s.get("stage") in STAGES else "Update"
    return s.get("stage") if s.get("stage") in STAGES else "Event"  # the first report


def annotate(digests):
    """Give every story of the loaded digests that belongs to a developing story with two or
    more reports s["_storyline"] = {"id", "title", "size", "stage"} (story cards show it)."""
    found = _collect(digests)
    for sl, items in found.items():
        reports = _reports(items)
        info = {"id": sl, "title": _title(sl, reports), "size": len(reports)}
        for s, _ in items:
            own = s.get("storyline")
            if isinstance(own, str) and own != sl and own in found:
                continue  # a story that names another developing story belongs to that one
            s["_storyline"] = dict(info, stage=_stage(s, sl))


def _most_common(values):
    """The most frequent non-empty value, the earliest of equals."""
    counts = {}
    for v in values:
        if v:
            counts[v] = counts.get(v, 0) + 1
    return max(counts, key=lambda v: (counts[v], -values.index(v))) if counts else ""


def groups(digests):
    """Developing stories with two or more reports, the most recently active first: each
    {"id", "title", "country", "place", "theme", "first", "last", "stories"}, with its reports
    oldest first as copies carrying "_digest" (and "_date", the day shown for the report)."""
    out = []
    for sl, items in _collect(digests).items():
        reports = _reports(items)
        stories = [dict(s, _digest=day, _date=story_date(s, day).isoformat()) for s, day in reports]
        countries = [scanner.country_code(s.get("country")) for s in stories]
        country = _most_common(countries)
        place = next((clip(s.get("place"), 80) for s, c in zip(stories, countries)
                      if s.get("place") and c == country), "")
        # the theme of the first report: the event's, where follow-ups (inquiries, court cases) often file elsewhere
        out.append({"id": sl, "title": _title(sl, reports), "country": country, "place": place,
                    "theme": stories[0].get("theme") or "General",
                    "first": stories[0]["_date"], "last": stories[-1]["_date"], "stories": stories})
    out.sort(key=lambda g: (g["last"], len(g["stories"]), g["id"]), reverse=True)
    return out


# ------------------------------------------------------------------ page
def country_name(code):
    """English name of a country code (the world map's list when it has one)."""
    if not code:
        return ""
    try:
        import geomap  # (it imports site_builder, which imports this module lazily)
        fn = getattr(geomap, "country_name", None)
        name = fn(code) if fn else ""
    except Exception:  # the map module is optional here
        name = ""
    return name or site_builder.COUNTRIES.get(code, code)


def span_text(first, last):
    """"over 5 months": how long a developing story has been followed."""
    days = (dt.date.fromisoformat(last) - dt.date.fromisoformat(first)).days
    if days < 1:
        return "within a day"
    if days < 14:
        return "over " + site_builder.count(days, "day")
    if days < 60:
        return "over " + site_builder.count(round(days / 7), "week")
    if days < 730:
        return "over " + site_builder.count(round(days / 30.44), "month")
    return "over " + site_builder.count(round(days / 365.25), "year")


def stage_class(stage):
    return "st-" + site_builder.slug(stage.split()[0]) if stage in STAGES else "st-update"


def report_item(s, sl, fold):
    """One report on a developing story's timeline."""
    stage = _stage(s, sl)
    shown = headline(s)
    meta = [f"<span class='src'>{esc(s.get('source', ''))}</span>", site_builder.rating(s)]
    meta.append(f"<a href='digests/{esc(s['_digest'])}.html'>Found in the {esc(site_builder.nice_date(s['_digest']))} digest</a>")
    if s.get("use") == "Feature lead":
        meta.insert(0, "<span class='use use-feature'>Feature lead</span>")
    # Claude's angle, never the publisher's text, and whom to check the facts with
    about = (f"<p class='sl-angle'>{esc(s['angle'])}</p>" if s.get("angle") else "") + site_builder.check_with(s)
    return (f"<li class='sl-item {stage_class(stage)}'{' data-fold' if fold else ''}>"
            f"<div class='sl-when'><time datetime='{esc(s['_date'])}'>{esc(site_builder.nice_date(s['_date']))}</time>"
            f"<span class='sl-stage'>{esc(stage)}</span></div><div class='sl-body'>"
            f"<a class='sl-link' href='{esc(site_builder.safe_url(s.get('link')))}' target='_blank' rel='noopener' dir='auto'>"
            f"{esc(shown)}</a>"
            + (site_builder.original_line(s) if s.get("title_en") else "")
            + about + f"<div class='sl-meta'>{''.join(meta)}</div></div></li>")


def storyline_card(g, period):
    sl, stories, theme = g["id"], g["stories"], g["theme"]
    n = len(stories)
    country = country_name(g["country"])
    where = g["place"]
    if country and country.lower() not in where.lower():  # "Moniquirá, Boyacá, Colombia", not "Lima, Peru, Peru"
        where = f"{where}, {country}" if where else country
    text = " ".join([g["title"], g["place"], country, theme] + [headline(s) + " " + s.get("title", "") + " "
                                                                + s.get("source", "") for s in stories]).lower()
    fold = set(range(1, n - 4)) if n > FOLD_AFTER else set()
    items = [report_item(s, sl, i in fold) for i, s in enumerate(stories)]
    if fold:
        items.insert(1, f"<li class='sl-fold-btn' hidden><button type='button' class='linkbtn'>"
                        f"Show {site_builder.count(len(fold), 'earlier report')}</button></li>")
    stages = []
    for s in stories:
        st = _stage(s, sl)
        if st not in stages:
            stages.append(st)
    facts = (f"<div><dt>First report</dt><dd>{esc(site_builder.nice_date(g['first']))}</dd></div>"
             f"<div><dt>Latest report</dt><dd>{esc(site_builder.nice_date(g['last']))}</dd></div>"
             f"<div><dt>Followed</dt><dd>{esc(span_text(g['first'], g['last']))}</dd></div>"
             f"<div><dt>Reports</dt><dd>{n}</dd></div>")
    return (f"<article class='sl-card' id='{esc(sl)}' style='--tc:{site_builder.theme_color(theme)}' "
            f"data-period='{period}' data-theme='{esc(theme)}' data-text='{esc(text)}'>"
            f"<header class='sl-head'><span class='ticon'>{site_builder.theme_icon(theme)}</span><div class='sl-titles'>"
            f"<h3 class='sl-title'><a href='#{esc(sl)}'>{esc(g['title'])}</a></h3>"
            f"<p class='sl-where'>" + (f"<span class='sl-place'>{esc(where)}</span>" if where else "")
            + f"<span class='theme-tag'>{site_builder.theme_icon(theme)}{esc(theme)}</span></p></div></header>"
            f"<dl class='sl-facts'>{facts}</dl>"
            f"<div class='sl-stages' role='group' aria-label='Stages reported'>"
            + "".join(f"<span class='sl-stage {stage_class(st)}'>{esc(st)}</span>" for st in stages) + "</div>"
            f"<ol class='sl-timeline'>{''.join(items)}</ol></article>")


def page_body(found, cfg, order, today, opts):
    active_since = (today - dt.timedelta(days=opts["active_days"])).isoformat()
    active = [g for g in found if g["last"] >= active_since]
    older = [g for g in found if g["last"] < active_since]
    reports = sum(len(g["stories"]) for g in found)
    longest = max(found, key=lambda g: (dt.date.fromisoformat(g["last"]) - dt.date.fromisoformat(g["first"])).days,
                  default=None)
    stats = (site_builder.stat(len(found), "developing stories")
             + site_builder.stat(len(active), f"active in the last {opts['active_days']} days")
             + site_builder.stat(reports, "reports linked")
             + (site_builder.stat(esc(span_text(longest["first"], longest["last"]).replace("over ", "")),
                                  "longest followed") if longest else ""))
    hero = site_builder.hero(
        "Developing stories", "Developing stories",
        "Follow-up reports linked to the event they continue: the failure, then the inquiry, then the repair. "
        "Long-running events are often the best feature leads, because by the time the cause is known and the "
        "repair designed, the lessons for practice can be told.", stats)
    check = (f" The cases it is unsure of, such as two place names in one region or a translated headline that may or "
             f"may not name the same site, are read again by {esc(model_name(opts['check_model']))}, each against its "
             "own closest earlier stories, and its decision stands." if opts["check_model"] and opts["max_checks"] else "")
    how = (f"<div class='sl-how'>{site_builder.icon('layers')}<p><b>How reports are linked.</b> Every scan, "
           f"{esc(model_name(opts['model']))} compares the day's new stories with the archive of the last "
           f"{opts['lookback_days']} days and links a report to an earlier one only when both are about the same event, "
           "project or site, not merely a similar hazard in the same country, and notes the stage the story has "
           f"reached.{check} Without Claude, a cautious headline match links "
           f"reports found within {opts['heuristic_days']} days. Story cards across the site carry a "
           "<span class='sl-chip sl-demo'>Developing story</span> chip that leads here. Check each report at its "
           "source: a link is a lead, not a confirmed connection.</p></div>")
    if not found:
        return (hero + how + "<p class='empty'>No developing stories yet. They appear here when a new report follows up "
                "an earlier story in the archive, for example an inquiry into a landslide reported last month.</p>")
    themes = [t for t in order if any(g["theme"] == t for g in found)]
    themes += sorted({g["theme"] for g in found} - set(themes))
    topts = "".join(f"<option>{esc(t)}</option>" for t in themes)
    tools = (f"<div class='toolbar sl-tools' id='sl-app' role='search'>"
             "<label class='field grow'><span>Filter</span><input type='search' class='f-text' "
             "placeholder='Event, place, source…'></label>"
             "<label class='field'><span>Show</span><select class='f-period'><option value=''>All developing stories</option>"
             f"<option value='active'>Active ({len(active)})</option><option value='earlier'>Earlier ({len(older)})</option>"
             f"</select></label><label class='field'><span>Theme</span><select class='f-theme'><option value=''>All themes</option>"
             f"{topts}</select></label><span class='f-count' aria-live='polite'>{site_builder.count(len(found), 'developing story', 'developing stories')}</span></div>")
    sections = []
    for key, label, group, none in (
            ("active", f"Active in the last {opts['active_days']} days", active,
             f"No developing story has had a new report in the last {opts['active_days']} days."),
            ("earlier", "Earlier", older, "None yet: every developing story is still active.")):
        cards = "".join(storyline_card(g, key) for g in group) or f"<p class='empty sl-empty'>{none}</p>"
        sections.append(f"<section class='sl-group' data-period='{key}'><h2 class='section-h'>{esc(label)} "
                        f"<span class='h1-sub'>{len(group)}</span></h2>{cards}"
                        "<p class='empty sl-none' hidden>No developing story here matches the filters.</p></section>")
    return hero + how + tools + "".join(sections)


def build(ctx):
    """docs/developing.html: every developing story with two or more reports."""
    cfg = ctx["cfg"]
    order = ctx.get("order") or site_builder.theme_order(cfg)
    body = page_body(groups(ctx.get("digests") or []), cfg, order, dt.date.today(), settings(cfg))
    site_builder.write(site_builder.DOCS / "developing.html",
                       site_builder.page(cfg, "Developing stories", body, "", "developing",
                                         "Follow-up reports linked to the event they continue: inquiries, repairs and court cases",
                                         head="<script src='assets/storylines.js' defer></script>"))
