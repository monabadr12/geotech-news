#!/usr/bin/env python3
"""
ISSMGE Magazine — Geotechnical News Scanner
Reads trade-site feeds and Google News searches, scores stories for
geotechnical relevance, (optionally) asks Claude to triage them, saves the
digest to data/digests/ (the permanent archive) and rebuilds the website in
docs/ (GitHub Pages). E-mail (alerts and the weekly summary) is sent by notify.py.
"""
import calendar
import collections
import datetime as dt
import difflib
import functools
import hashlib
import html
import json
import math
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote, quote_plus, urlencode, urljoin

import feedparser
import requests
import yaml

import site_builder

ROOT = Path(__file__).resolve().parent
CONFIG = Path(os.environ.get("SCANNER_CONFIG", ROOT / "config.yaml"))
SEEN_FILE = ROOT / "data" / "seen.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GeotechNewsScanner/1.0)"}
USES = site_builder.USES


# ------------------------------------------------------------------ fetching
MAX_FEED_BYTES = 15 * 1024 * 1024


def fetch(url):
    with requests.get(url, headers=HEADERS, timeout=25, stream=True) as r:
        r.raise_for_status()
        body = b""
        for chunk in r.iter_content(65536):
            body += chunk
            if len(body) > MAX_FEED_BYTES:
                raise ValueError("response larger than 15 MB")
        return body


FEED_TAG = re.compile(r"<link[^>]+type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>", re.I)
HREF = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)


def read_feed(url):
    """Return feed entries; if url is a web page, auto-discover its feed."""
    content = fetch(url)
    parsed = feedparser.parse(content)
    if parsed.entries:
        return parsed.entries
    page = content.decode("utf-8", "ignore")
    for tag in FEED_TAG.findall(page):
        m = HREF.search(tag)
        if not m:
            continue
        found = feedparser.parse(fetch(urljoin(url, html.unescape(m.group(1)))))
        if found.entries:
            return found.entries
    raise ValueError("no RSS/Atom feed found at this address")


def google_news_url(query, lang, country):
    """A language with its own region code, such as es-419 (the Spanish of the
    Latin American editions), is used as it is; others get the country's."""
    q = quote_plus(f"{query} when:3d")
    hl = lang if "-" in lang else f"{lang}-{country}"
    return f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={country}&ceid={country}:{lang}"


def google_sources(g):
    """Build one feed per (query, edition). Non-English queries carry a bonus so
    they survive the English keyword filter and are judged by Claude instead.
    A query may also carry a boost, like a website: the site searches that
    stand in for sites which block feed readers keep their specialist bonus."""
    out = []
    dl, dc = g.get("language", "en"), g.get("country", "GB")
    editions = g.get("editions") or [{"language": dl, "country": dc}]
    for q in g.get("core_queries", []):
        for ed in editions:
            lang, country = ed.get("language", dl), ed.get("country", dc)
            out.append({"name": f"Google News {country}", "google": True, "bonus": 0,
                        "region": country, "url": google_news_url(q, lang, country)})
    for item in g.get("extra_queries", []):
        if isinstance(item, str):
            item = {"q": item}
        lang, country = item.get("language", dl), item.get("country", dc)
        out.append({"name": f"Google News {country}", "google": True,
                    "bonus": int(item.get("bonus", 0)), "boost": int(item.get("boost", 0)),
                    "region": country, "url": google_news_url(item["q"], lang, country)})
    return out


# ------------------------------------------------------------------ helpers
# control characters other than tab and line breaks (they break the Excel export)
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = CONTROL.sub(" ", html.unescape(text))
    return re.sub(r"\s+", " ", text).strip()


# Persian is written with its own yeh and kaf, but many sites (and Egyptian
# Arabic, which ends words with a dotless yeh) use the Arabic letters, so all
# are read as one. The zero-width non-joiner inside Persian words (زمین‌لغزش)
# counts as a space; Russian ё is read as е, as most Russian text writes it.
LETTER_FOLD = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "\u200c": " ", "ё": "е"})


def fold(text):
    """Lower-case text for matching. NFKC turns full-width letters into plain
    ones. Turkish capitals lower-case oddly (İ becomes i plus a combining dot,
    I becomes i where the word has ı), so the dot is dropped and ı is read as i;
    text and terms are folded alike."""
    low = unicodedata.normalize("NFKC", text or "").lower().replace("\u0307", "").replace("ı", "i")
    return low.translate(LETTER_FOLD)


def entry_time(e):
    for key in ("published_parsed", "updated_parsed"):
        t = e.get(key)
        if t:
            return dt.datetime.fromtimestamp(calendar.timegm(t), dt.timezone.utc)
    return None


# scripts matched inside words: Thai, Japanese kana and Chinese characters,
# written without spaces between words, and Korean Hangul, whose particles
# attach to the noun before them (산사태로, "by a landslide")
NOSPACE = ("\u0e00-\u0e7f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
           "\u1100-\u11ff\u3130-\u318f\uac00-\ud7af")
NOSPACE_CHAR = re.compile(f"[{NOSPACE}]")
# a word goes on while a letter, digit or combining mark (Arabic vowel sign,
# Devanagari vowel sign) of any script follows
MARKS = (r"\u0300-\u036f\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed"
         r"\u0900-\u0903\u093a-\u094f\u0951-\u0957\u0962\u0963")
WORD_END = rf"(?![^\W_]|[{MARKS}])"
# a word may not start inside a Latin (accented ones too), Greek or Cyrillic
# word: сель (debris flow) is not found in Брюссель
WORD_START = r"(?<![a-z0-9\u00c0-\u024f\u1e00-\u1eff\u0370-\u03ff\u0400-\u052f])"
# "*" in a term stands for the rest of the word: оползн* finds оползень's
# other forms оползня, оползни, оползневой
WILDCARD = rf"(?:[^\W_]|[{MARKS}])*"
# Korean writes spaces between words, so a Korean term must start a word:
# 제방 (embankment) is not found in 규제방안 (regulatory measures)
HANGUL = "\u1100-\u11ff\u3130-\u318f\uac00-\ud7af"
HANGUL_CHAR = re.compile(f"[{HANGUL}]")
HANGUL_START = f"(?<![{HANGUL}])"


@functools.lru_cache(maxsize=None)
def term_regex(term):
    """Chinese and Japanese terms match anywhere, since those languages put no
    spaces between words. Korean terms must start a word but may go on, since
    Korean attaches particles to the end of a word (산사태로, "by a landslide");
    a leading "*" lets them start inside a word too: '*댐' finds 소양강댐 (Soyang
    River Dam). Other terms must end where a word ends, with an optional plural
    s/es, so نفق (tunnel) does not match inside نفقات (expenses); a "*" lets the
    word go on, for languages that change a word's ending (Russian, Polish):
    'подпорн* стен*' is any form of подпорная стена (retaining wall). The start
    is checked against Latin, Greek and Cyrillic letters only, so Arabic
    prefixes such as ال (the) still match."""
    t = fold(str(term))
    body = WILDCARD.join(re.escape(part) for part in t.split("*"))
    if NOSPACE_CHAR.search(t):
        return re.compile((HANGUL_START if HANGUL_CHAR.match(t) else "") + body)
    return re.compile(WORD_START + body + ("" if t.endswith("*") else r"(?:s|es)?") + WORD_END)


def compile_keywords(cfg):
    """English concept -> [(pattern, weight)]. Terms in other languages are
    filed under the English concept they translate."""
    compiled = {}
    for term, weight in cfg["keywords"].items():
        compiled.setdefault(term, []).append((term_regex(term), weight))
    for concept, spec in (cfg.get("multilingual_keywords") or {}).items():
        for term in spec.get("terms", []):
            compiled.setdefault(concept, []).append((term_regex(str(term)), spec.get("weight", 1)))
    return compiled


def keyword_score(text, cfg, compiled):
    low = fold(text)
    score, hits = 0, []
    for concept, patterns in compiled.items():
        weights = [w for rx, w in patterns if rx.search(low)]
        if weights:
            score += max(weights)
            hits.append(concept)
    for bad in cfg.get("exclude", []):
        if term_regex(str(bad)).search(low):  # whole words: "election" spares "selection"
            score -= 5
    return score, hits


@functools.lru_cache(maxsize=None)
def theme_regex(word):
    """Words of 6+ letters are stems (sustainab -> sustainable); shorter ones
    must match whole, with an optional plural (dam, dams, but not damage)."""
    w = re.escape(fold(word))
    return re.compile(r"(?<![a-z])" + w + ("" if len(word) >= 6 else r"(?:s|es)?(?![a-z])"))


def guess_theme(text, themes, hits=()):
    """Theme with the most matching words, counting the English concepts found
    by the keyword lists (so non-English stories are themed too). A tie goes
    to the theme matched through those concepts, so a landslip in high winds
    is a hazard story; a remaining tie goes to the theme listed first."""
    concepts = fold(" | ".join(hits))
    low = fold(text) + " | " + concepts
    best, best_key = "General", (0, 0)
    for theme, words in themes.items():
        found = [w for w in words if theme_regex(w).search(low)]
        key = (len(found), sum(1 for w in found if theme_regex(w).search(concepts)))
        if key > best_key:
            best, best_key = theme, key
    return best


# ------------------------------------------------------------------ same event, several outlets
# Function words of the covered languages (words of one or two letters are
# dropped anyway). Chinese, Japanese and Korean are compared by pairs of characters.
STOPWORDS = """
the and for with from into after over under about amid near than that this these those will would could should
have has had was were are been being not but its their they them his her our out off new says said say why how
what when where who which while more most also just against between through during before upon via per
les des une est dans pour par sur avec sans aux sous entre vers chez leur leurs ses son sont qui que quoi dont
mais plus moins tout tous toute toutes cette ces été être avoir fait après avant selon depuis pendant contre comme
ont elle elles ils nous vous très encore aussi
los las del una uno unos unas por para con sin sobre tras desde hasta hacia ante bajo según quien cual como más
muy sus esta este estos estas ese esa eso fue son han hay tiene tienen ser está están durante pero también otro
otra otros otras sido
das dos umas uns pela pelo pelas pelos com sem após até mais muito seu sua seus suas isso essa esse são foi tem
têm estão nas nos num numa
della delle dello degli dei alla alle allo agli dal dalla dalle dagli nel nella nelle negli sul sulla sulle sugli
tra fra che chi più meno sono gli dopo prima anche questo questa suo loro
der die den dem ein eine einen einem einer eines und oder mit von vom zum zur bei nach vor für auf aus über
unter gegen ohne nicht sich ist sind wird werden wurde wurden hat haben noch nur bis seit sein ihre ihr
bir ile için gibi daha çok olan olarak sonra önce kadar değil veya ama hem her
dan yang untuk dengan dari pada dalam akan oleh juga tidak ini itu atau karena setelah sebelum bagi para telah
sudah masih bisa dapat ada saat
में से की का के को ने पर और है हैं था थी थे लिए बाद साथ एक यह वह गया गई गए किया कर तक भी नहीं हुआ हुई हुए रहा रही रहे
في من على إلى الى عن مع بعد قبل حتى هذا هذه ذلك التي الذي الذين وفي ومن أن إن كان كانت بين خلال عند تم
что это как для при после около более также его она они был была были будет может где когда который которая
которые против между через чтобы тоже уже еще всех все под над без или так
się jest nie dla przez oraz który która które jak już tak ale czy jego ich pod nad bez przy został została
zostały będzie może gdzie kiedy także tylko więcej ponad wśród
của và các những cho với được trong tại khi này một người đã đang sẽ không có là từ theo về sau trên vào
برای این است شده بود خود های
""".split()
STOPWORDS = frozenset(fold(w) for w in STOPWORDS)  # folded like the headlines (في, على)
# Words of every Korean disaster story (occurred, residents, evacuation, damage,
# heavy rain...) and counters (50명, 3대). Korean has no capitals that tell
# places apart, so two headlines must share another word to be one event:
# '강원 정선 산사태 발생…주민 대피' and '경북 봉화 산사태 발생…주민 대피' are two.
# A word that starts with one of these (주민들, 발생해) counts as that word.
KOREAN_NEWS_WORDS = frozenset("""
발생 주민 시민 이재민 대피 피해 사고 현장 정부 당국 경찰 소방 원인 조사 점검 우려 위험 비상 긴급 통제 복구 지원
대책 추가 확인 사망 실종 부상 숨져 숨진 구조 수색 매몰 발견 출동 인근 일대 곳곳 지역 마을 도심 전국 오늘 어제 새벽
오전 오후 밤사이 이틀째 사흘째 잇따라 속보 단독 종합 영상 포토 폭우 호우 집중호우 장마 태풍 강풍 폭설 기상청 특보
경보 주의보 관계자 작업자 근로자 운전자 차량 건물 주택 아파트 공사 공사장 대형 가구 세대 명 곳 건 채 대 개
""".split())
KOREAN_PARTICLE = re.compile("(?:으로|에서|에게|로|에|서|의|은|는|을|를|과|와)$")
KOREAN_STEMS = sorted((w for w in KOREAN_NEWS_WORDS if len(w) > 1), key=len, reverse=True)
SCRIPT_RUNS = re.compile(f"[{NOSPACE}]+|[^{NOSPACE}]+")
SENTENCE_BREAK = re.compile(r"[.!?¡¿|•]")
NAME_TOKEN = re.compile(r"[^\W\d_][\w'’-]*")
SAME_EVENT_OVERLAP = 0.4  # share of the shorter headline's significant words


def title_norm(title):
    """Letters, combining marks and digits of every script, lower-cased;
    everything else becomes a single space."""
    kept = "".join(c if unicodedata.category(c)[0] in "LMN" else " " for c in fold(title))
    return " ".join(kept.split())


def title_words(norm, topic=frozenset()):
    """The significant words of a normalised headline: no short words, numbers
    or stopwords; the first six letters stand for the word (deslizamiento and
    deslizamientos, destruyó and destruidas); Arabic ال (the) is dropped.
    Chinese, Japanese and Korean give pairs of characters (common Korean news
    words stay whole). Words of the keyword lists
    (topic) are left out: every landslide story says landslide, while place
    names and details tell one event from another."""
    out = set()
    for word in norm.split():
        for run in SCRIPT_RUNS.findall(word):
            if HANGUL_CHAR.match(run) and len(run) >= 3:
                run = KOREAN_PARTICLE.sub("", run)  # 산사태로 -> 산사태
            stem = HANGUL_CHAR.match(run) and next((w for w in KOREAN_STEMS if run.startswith(w)), None)
            if stem or run in KOREAN_NEWS_WORDS:
                out.add(stem or run)
            elif NOSPACE_CHAR.match(run):
                out.update({run[i:i + 2] for i in range(len(run) - 1)} or {run})
            elif len(run) >= 3 and not run.isdigit() and run not in STOPWORDS:
                if len(run) >= 5 and run.startswith("ال"):
                    run = run[2:]
                out.add(run[:6])
    return out - topic


def topic_words(cfg):
    terms = [str(t) for t in (cfg.get("keywords") or {})]
    for spec in (cfg.get("multilingual_keywords") or {}).values():
        terms += [str(t) for t in spec.get("terms", [])]
    # Korean compounds listed for matching (포항지진, 하천제방) would otherwise make
    # their place or river part (포항, 하천) a topic word and hide it from comparison
    base = [t for t in terms if not (HANGUL_CHAR.match(t) and any(o != t and t.endswith(o) for o in terms))]
    return frozenset(w for t in base for w in title_words(title_norm(t)))


def title_names(title, topic):
    """Significant words written with a capital inside a sentence, plus a
    one-word "Place:" dateline at the start: usually the places and people a
    story is about. Empty when capitals tell nothing: scripts without
    capitals, Title Case headlines and German nouns."""
    title = unicodedata.normalize("NFKC", title or "")
    names, total, capitals = set(), 0, 0
    for sentence in SENTENCE_BREAK.split(title):
        for k, word in enumerate(NAME_TOKEN.findall(sentence)):
            sig = title_words(title_norm(word), topic)
            if sig:
                total += 1
                if k and word[:1].isupper():
                    names |= sig
                    capitals += 1
    head, colon, _ = title.partition(":")
    if colon and len(head.split()) == 1 and head.strip()[:1].isupper():
        names |= title_words(title_norm(head), topic)
    return set() if total > 1 and capitals > total / 2 else names


def same_event(a, b):
    """a and b are (normalised title, significant words, names) of two headlines."""
    if a[2] and b[2] and (a[2] - b[2]) and (b[2] - a[2]):
        return False  # each names a place or person the other does not
    if a[1] and b[1] and not (a[1] & b[1]) - KOREAN_NEWS_WORDS and a[0] != b[0]:
        return False  # no significant word in common (common Korean news words do not count)
    shared = len(a[1] & b[1])
    if (shared >= (2 if a[2] and b[2] else 3)
            and shared >= SAME_EVENT_OVERLAP * min(len(a[1]), len(b[1]))):
        return True
    sm = difflib.SequenceMatcher(None, a[0], b[0])
    return sm.real_quick_ratio() > 0.8 and sm.quick_ratio() > 0.8 and sm.ratio() > 0.8


def headline_marks(title, topic):
    """What same_event() compares: (normalised title, significant words, names)."""
    norm = title_norm(title)
    return norm, title_words(norm, topic), title_names(title, topic)


def story_marks(it, topic):
    """What same_story() compares: the headline marks of a story's English
    wording (title_en, or the title of a story written in English), all its
    significant words (keyword words too), its numbers and the significant
    words of the place Claude read."""
    text = it.get("title_en") or it["title"]
    marks = headline_marks(text, topic)
    return (marks, title_words(marks[0]), set(re.findall(r"\d+", marks[0])),
            title_words(title_norm(it.get("place") or ""), topic))


def initials(norm):
    """The initials of each run of three or four words of a normalised
    headline, as an abbreviation of them would read (tunnel boring machine:
    tbm)."""
    words = norm.split()
    return {"".join(w[0] for w in words[i:i + n]) for n in (3, 4) for i in range(len(words) - n + 1)}


def same_story(a, b):
    """a and b are story_marks() of two stories, at least one of them
    translated by Claude. Short translated headlines look alike, so this is
    stricter than same_event(). Two stories that each have a number, or a
    word in Claude's place, that the other lacks are two (330 billion dong is
    not 200 billion). Wordings that differ by a word or two each, a keyword
    word among them, are two, whether or not they name a place: "Ca Mau:
    experts propose solutions for coastal erosion" is not "... for riverbank
    erosion" (but "TBM" may stand for "tunnel boring machine"). Otherwise
    the words they share must include a name or a word of the place, and
    another word: "Exploring Phong Nha-Ke Bang's famous sinkholes" is not
    "120 m deep sinkhole discovered in Phong Nha-Ke Bang". Wordings with no
    name in common may differ by one word each: "Anti-landslide embankment
    threatens residential area" is "Landslide-prevention embankment...".
    Wordings that are the same word for word are one story, unless Claude
    read two places."""
    (ha, wa, na, pa), (hb, wb, nb, pb) = a, b
    if ha[0] == hb[0] and (not pa or not pb or not (pa - pb and pb - pa)
                           or pa & pb & (ha[2] | hb[2])):  # the places share a name the headline gives
        return True
    if (na - nb and nb - na) or (pa - pb and pb - pa) or not same_event(ha, hb):
        return False
    short = (wa - wb) & initials(hb[0]) or (wb - wa) & initials(ha[0])  # TBM, tunnel boring machine
    swapped = wa ^ wb != ha[1] ^ hb[1] and not short  # a keyword word in one wording only
    if swapped and wa - wb and wb - wa and len(wa - wb) <= 2 and len(wb - wa) <= 2:
        return False
    shared = ha[1] & hb[1]
    named = ha[2] | hb[2] | pa | pb
    if shared & named:
        return bool(shared - named)
    return len(wa - wb) <= 1 and len(wb - wa) <= 1 and not swapped


def drop_same_events(items, cfg, copies=None):
    """Keep one headline per event. Items must come best first. Headlines that
    match, directly or through a chain of re-wordings, form one group, and only
    the group's best headline is kept. Stories that Claude translated are also
    compared in English (same_story), so that the copies of one story in
    several languages count once (Vietnam.vn publishes each story in
    Vietnamese, English, Chinese and more, and Google News lists every copy).
    Reports from two websites must then also be from one country; copies on
    one website need not, since Claude may take an Indonesian copy of a
    Vietnamese story for Indonesian news. A dict given as copies receives, for
    each kept story's id, the other stories of its group, best first."""
    topic = topic_words(cfg)
    marks = [headline_marks(it["title"], topic) for it in items]
    translated = [bool(it.get("title_en")) for it in items]
    english = [story_marks(it, topic) for it in items] if any(translated) else []

    def same(i, j):
        if same_event(marks[i], marks[j]):
            return True
        if not (translated[i] or translated[j]):
            return False  # the titles were compared above
        ci, cj = items[i].get("country"), items[j].get("country")
        if ci and cj and ci != cj and source_key(items[i].get("source")) != source_key(items[j].get("source")):
            return False
        return same_story(english[i], english[j])

    parent = list(range(len(items)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i):
            if root(i) != root(j) and same(i, j):
                parent[max(root(i), root(j))] = min(root(i), root(j))
    kept, groups = [], {}
    for i, it in enumerate(items):
        if root(i) not in groups:  # the first item of each group is its best
            groups[root(i)] = it
            kept.append(it)
        elif copies is not None:
            copies.setdefault(groups[root(i)]["id"], []).append(it)
    return kept


# ------------------------------------------------------------------ theme balance
def theme_share(cfg):
    try:
        share = float(cfg.get("max_share_per_theme", 0.3))
    except (TypeError, ValueError):
        share = 0.3
    return min(max(share, 0.0), 1.0)


def fill_leftovers(cfg):
    return bool(cfg.get("fill_leftover_places", False))


source_cap = site_builder.source_cap  # max_per_source, read as the Method page reads it


def source_key(name):
    """A story's website as the cap counts it: case, spacing, a leading www.
    and trailing punctuation do not matter (Vietnam.vn, www.vietnam.vn and
    "VIETNAM.VN." are one website)."""
    key = re.sub(r"^www\.", "", " ".join(str(name or "").casefold().split()))
    while key and (key[-1].isspace() or unicodedata.category(key[-1])[0] == "P"):
        key = key[:-1]
    return key


def theme_turns(items, limit, share, rank, fill=True):
    """Up to `limit` items spread across the magazine themes. Themes take
    turns, the theme with the best story first, each giving its best remaining
    story, until it runs out or reaches its cap of ceil(limit * share). With
    fill, places still free when every theme is capped or empty go to the best
    remaining stories, whatever their theme; without it the cap is strict."""
    order = sorted(items, key=lambda i: -rank(i))
    if fill and len(order) <= limit:
        return order
    queues = {}
    for it in order:  # themes in the order of their best story
        queues.setdefault(it["theme"], []).append(it)
    picked = []
    for turn in range(max(1, math.ceil(limit * share))):
        for queue in queues.values():
            if turn < len(queue) and len(picked) < limit:
                picked.append(queue[turn])
    if fill and len(picked) < limit:
        chosen = {id(i) for i in picked}
        picked += [i for i in order if id(i) not in chosen][: limit - len(picked)]
    return sorted(picked, key=lambda i: -rank(i))


def balanced(items, limit, share, rank, fill=True, per_source=0, copies=None):
    """theme_turns(), with no website (source_key) keeping more than
    per_source stories (0 = no limit). A website's weakest stories beyond its
    best per_source are taken out and the places filled again, each theme
    giving its next story, until no website has too many. A story taken out
    gives way to another website's report of the same event when
    drop_same_events() merged one into it (copies), so that the event is not
    lost with it. Such a report can push a story out of its theme, leaving a
    website below its limit or with a weaker story: a story taken out then
    comes back, once, unless a report of its event is already picked."""
    pool, tried, spare = list(items), {id(i) for i in items}, {}
    stands_for, taken, back = {}, [], set()  # stands_for: a report put in -> the first story of its event (ids)

    def event(it):
        return stands_for.get(id(it), id(it))

    while True:
        picked = theme_turns(pool, limit, share, rank, fill)
        sites, weakest = collections.Counter(), {}
        out = []
        for it in picked:  # best first: a website keeps its best stories
            site = source_key(it.get("source"))
            sites[site] += 1
            if per_source and site and sites[site] > per_source:
                out.append(it)
            else:
                weakest[site] = rank(it)
        if not out:
            shown = {event(i) for i in picked}
            # a report put in that its theme had no place for: the event's next report from a website with room
            chosen, moved = {id(i) for i in picked}, False
            for r in [i for i in pool if id(i) in stands_for and id(i) not in chosen and event(i) not in shown]:
                others = [c for c in spare.pop(id(r), []) if id(c) not in tried
                          and sites[source_key(c.get("source"))] < per_source]
                if others:
                    pool = [i for i in pool if i is not r] + [others[0]]
                    tried.add(id(others[0]))
                    spare[id(others[0])] = others[1:]
                    stands_for[id(others[0])] = event(r)
                    moved = True
            if moved:
                continue
            # a story taken out whose website now has room, or keeps a weaker story
            due = [i for i in taken if id(i) not in back and event(i) not in shown
                   and (sites[source_key(i.get("source"))] < per_source
                        or rank(i) > weakest[source_key(i.get("source"))])]
            if not due:
                return picked
            it = max(due, key=rank)
            back.add(id(it))
            pool = [i for i in pool if event(i) != event(it)] + [it]  # its event's unpicked report makes way
            continue
        taken += out
        gone = {id(i) for i in out}
        pool = [i for i in pool if id(i) not in gone]
        for it in out:  # the other websites' reports of its event, best first, while their website has room
            others = spare.pop(id(it), None)
            if others is None:
                others = (copies or {}).get(it.get("id"), [])
            others = [c for c in others if id(c) not in tried and sites[source_key(c.get("source"))] < per_source]
            if others:
                pool.append(others[0])
                tried.add(id(others[0]))
                spare[id(others[0])] = others[1:]
                stands_for[id(others[0])] = event(it)


# ------------------------------------------------------------------ Claude triage
def triage_schema(themes):
    story = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "relevance": {"type": "integer"},
            "theme": {"type": "string", "enum": themes},
            "use": {"type": "string", "enum": USES},
            "angle": {"type": "string"},
            "title_en": {"type": "string"},
            "country": {"type": "string"},
            "place": {"type": "string"},
            "primary_source": {"type": "string"},
        },
        "required": ["id", "relevance", "theme", "use", "angle", "title_en", "country", "place", "primary_source"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"stories": {"type": "array", "items": story}},
            "required": ["stories"], "additionalProperties": False}


KEY_TOKEN = re.compile(r"sk-ant-[A-Za-z0-9_-]+")
QUOTES = "\"'`“”‘’"
KEY_NAME = re.compile(r"^(?:export\s+)?ANTHROPIC_API_KEY\s*[=:]\s*", re.I)


def clean_api_key(raw):
    """The key inside the secret as pasted: without spaces or line breaks
    around it, surrounding quotes, a leading ANTHROPIC_API_KEY= or other text
    next to it (the first sk-ant-... token wins)."""
    key = KEY_NAME.sub("", (raw or "").strip().strip(QUOTES).strip())
    key = key.strip().strip(QUOTES).strip()
    found = KEY_TOKEN.search(key)
    return found.group(0) if found else key


def describe_key(raw, key):
    """What the secret looks like, without revealing it."""
    raw = raw or ""
    found = []
    if raw != raw.strip():
        found.append("spaces or line breaks around it")
    if re.search(r"\s", raw.strip()):
        found.append("spaces or line breaks inside it")
    if any(q in raw for q in QUOTES):
        found.append("quote marks")
    if "ANTHROPIC_API_KEY" in raw.upper():
        found.append('the name "ANTHROPIC_API_KEY=" in front of the key')
    bare = KEY_NAME.sub("", raw.strip().strip(QUOTES).strip()).strip().strip(QUOTES).strip()
    if key and bare != key:
        found.append("other text next to the key")
    text = f"The secret is {len(raw)} characters long"
    text += (f" and contained {', '.join(found)}, removed before use. " if found else ". ")
    n = len(key)
    if not key:
        return text + "Nothing is left once spaces and quotes are removed: paste the key itself as the secret's value."
    if key.startswith("sk-ant-admin"):
        kind = ("It is an Admin key (it starts with sk-ant-admin), which manages an organisation but cannot "
                "call Claude: create an ordinary API key in the Claude Console under API keys.")
    elif key.startswith("sk-ant-oat"):
        kind = ("It is a Claude subscription (OAuth) token (it starts with sk-ant-oat), not an API key, and the "
                "API does not accept it here: create an API key in the Claude Console under API keys.")
    elif key.startswith("sk-ant-api"):
        kind = f"The key starts with sk-ant-api, as an API key should, and is {n} characters long"
        if n < 100:
            kind += ", which looks cut short (complete keys are about 108): paste the whole key again."
        else:
            kind += (". If it was copied whole, it has probably been deleted or disabled in the Claude"
                     " Console, or its organisation has no API access: create a new key and paste it again.")
    elif key.startswith("sk-ant-"):
        kind = (f"The key is {n} characters long and starts with sk-ant- but not sk-ant-api, so it is not an "
                "API key: create one in the Claude Console under API keys.")
    else:
        kind = (f"The value used is {n} characters long and does not start with sk-ant-, so it is not an "
                "Anthropic API key: check that the secret's value is the key itself.")
    return text + kind


def api_message(ex):
    """The API's own explanation of an error, with anything key-like masked."""
    body = getattr(ex, "body", None)
    err = body.get("error") if isinstance(body, dict) else None
    msg = (err.get("message") if isinstance(err, dict) else None) or getattr(ex, "message", "") or str(ex)
    return KEY_TOKEN.sub("sk-ant-…", str(msg))[:160]


COUNTRY_CODE = re.compile(r"^[A-Z]{2}$")
COUNTRY_ALIASES = {"UK": "GB", "EL": "GR"}  # common non-ISO codes
NOT_COUNTRIES = {"XX", "ZZ", "EU", "EZ", "UN"}  # unknown, and groupings that are not one country (counted as global)


def country_code(text):
    """An ISO 3166-1 alpha-2 code from Claude's answer, or "" (global or unknown)."""
    code = str(text or "").strip().upper()
    code = COUNTRY_ALIASES.get(code, code)
    return code if COUNTRY_CODE.match(code) and code not in NOT_COUNTRIES else ""


PRIMARY_SOURCE_WORDS = 12
# words a shortened answer must not end on ("… the regional geological survey and")
DANGLING = {"and", "or", "of", "the", "a", "an", "with", "for", "to", "its", "their", "in", "at", "on", "by",
            "from", "&"}


def primary_source(text):
    """Claude's "who to check the facts with" on one line, at most PRIMARY_SOURCE_WORDS words and 120
    characters ("" when unclear, or when Claude answered "none", "unknown" or the like). A longer answer is
    shortened at a word, without a dangling "and", "of" or the like, and ends in "…"."""
    words = " ".join(str(text or "").split()).strip(" .;:-–—").split(" ")
    out = " ".join(words[:PRIMARY_SOURCE_WORDS])
    if out.casefold() in ("", "none", "n/a", "na", "unknown", "unclear", "not clear", "-"):
        return ""
    cut = len(words) > PRIMARY_SOURCE_WORDS
    if len(out) > 120:
        out, cut = out[:119].rsplit(" ", 1)[0], True
    if not cut:
        return out
    kept = out.split(" ")
    while len(kept) > 1 and kept[-1].rstrip(",;:").casefold() in DANGLING:
        kept.pop()
    return " ".join(kept).rstrip(" ,;:-–—") + "…"


def claude_triage(items, cfg, notes):
    """Ask Claude to rate the candidates. True if at least one batch was rated."""
    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    key = clean_api_key(raw)
    if not key:
        print("AI triage off: the scan received no ANTHROPIC_API_KEY (the secret is missing or empty).")
        return False
    if not items:
        return False
    if key != raw:
        print("ANTHROPIC_API_KEY: " + describe_key(raw, key).split(". ")[0] + ".")
    import anthropic  # only needed when a key is configured

    client = anthropic.Anthropic(api_key=key, max_retries=3)
    ccfg = cfg["claude"]
    themes = list(cfg["themes"].keys()) + ["General"]
    schema = triage_schema(themes)
    rated = 0
    for start in range(0, len(items), 40):
        batch = items[start:start + 40]
        listing = "\n".join(
            f'{start + i}. [{it["source"]}] {it["title"]} :: {it["summary"][:350]}'
            for i, it in enumerate(batch))
        prompt = f"""You are the news-desk assistant of the ISSMGE magazine (International Society for Soil Mechanics and Geotechnical Engineering). Readers are practising geotechnical engineers and academics worldwide. The editor wants stories with real geotechnical substance, not general construction or politics.

For each story below return an object with:
- "id": the number
- "relevance": 1-5 (5 = rich geotechnical lesson or major ground-related event; 3 = clear ground engineering element worth a brief; 1 = not geotechnical)
- "theme": the one magazine theme it fits best
- "use": the best editorial use
- "angle": one sentence (max 30 words) stating the geotechnical question a magazine piece could explore, entirely in your own words: never copy or closely paraphrase the headline or the summary
- "title_en": if the headline is not in English, your English translation of it (max 20 words); otherwise ""
- "country": the ISO 3166-1 alpha-2 code (e.g. "CO", "GB", "HK") of the country where the event, project or site is, which may differ from the outlet's country; "" if the story is not about one country (a global market report, a general research result, several countries)
- "place": the town, city, region or site named in the story, in English (max 6 words, e.g. "Moniquirá, Boyacá" or "HS2 Chiltern Tunnel"); "" if none is named
- "primary_source": who the editor should check the facts with before publishing, in at most 12 words: the authority, the project owner or client, the company, or the body behind the official report (e.g. "HS2 Ltd", "the state disaster management authority", "the city's water utility", "the national geological survey's landslide report"); "" when unclear. The news outlet that ran the story is not a primary source

The magazine treats every story as a lead: its writers check the facts with the primary source and write their own pieces. The headlines and summaries below are the outlets' text, for you to judge the stories by; they are not to be reused.

Stories:
{listing}"""
        try:
            response = client.messages.create(
                model=ccfg["model"],
                max_tokens=16000,
                output_config={"effort": ccfg.get("effort", "low"),
                               "format": {"type": "json_schema", "schema": schema}},
                messages=[{"role": "user", "content": prompt}])
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as ex:
            why = ("was rejected" if isinstance(ex, anthropic.AuthenticationError)
                   else f"was refused access to {ccfg['model']}")
            note = (f"AI triage skipped: the ANTHROPIC_API_KEY secret {why} ({api_message(ex)}). "
                    + describe_key(raw, key)
                    + " Change the key in Settings → Secrets and variables → Actions.")
            notes.append(note)
            print(note)
            return False
        except anthropic.APIError as ex:  # fall back to keywords for this batch
            note = f"AI triage failed for one batch ({api_message(ex)[:100]}); keyword ranking used."
            if note not in notes:
                notes.append(note)
                print(note)
            continue
        if response.stop_reason != "end_turn":
            notes.append(f"AI triage stopped early for one batch ({response.stop_reason}); keyword ranking used.")
            continue
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            results = json.loads(text)["stories"]
        except (ValueError, KeyError) as ex:
            notes.append(f"AI triage returned unreadable output for one batch ({str(ex)[:80]}).")
            continue
        for d in results:
            idx = int(d["id"])
            if 0 <= idx < len(items):
                items[idx].update(
                    relevance=max(1, min(5, int(d["relevance"]))),
                    theme=d["theme"] if d["theme"] in themes else items[idx]["theme"],
                    use=d["use"] if d["use"] in USES else "",
                    angle=d["angle"][:300],
                    title_en=d["title_en"][:200],
                    country=country_code(d["country"]),
                    place=d["place"][:80],
                    primary_source=primary_source(d.get("primary_source")))
        rated += 1
    if items and not rated:
        note = "AI triage failed for every batch, so all stories were ranked by keywords only."
        notes.append(note)
        print(note)
    return rated > 0


# ------------------------------------------------------------------ research papers
# New papers from the journals in config.yaml (research: journals), read from
# Crossref's free API. They are scored and themed like the news, rated by
# Claude for their use in practice, and kept in the digest as "papers".
CROSSREF = "https://api.crossref.org/journals/{issn}/works?"
CROSSREF_FIELDS = "DOI,title,author,container-title,created,published,published-online,abstract,type"
CROSSREF_ROWS = 50
# notices, corrections and replies that Crossref files as journal articles.
# Discussions are titled 'Discussion of “…”' (ASCE), 'Discussion: …' (ICE) or
# 'Discussion on “…”' (Elsevier); a paper may begin "Discussion on the …".
NOT_RESEARCH = re.compile(
    r"^(?:(?:erratum|corrigendum|correction|retraction|retracted|expression of concern|editorial|editor['’]?s note|"
    r"publisher['’]?s note|in memoriam|obituary|book review|reviewers|acknowledg|issue information|front matter|"
    r"back matter|cover image|table of contents|call for papers|announcement|discussion of|discussion by|"
    r"closure to|reply to|response to|comment on|author(?:['’]?s|s['’])? (?:reply|response|closure))\b"
    r"|(?:discussion|closure|reply|response)(?: on)?\s*[:“\"‘'«])", re.I)
JATS_HEADING = re.compile(r"<jats:title[^>]*>.*?</jats:title>", re.I | re.S)
# markup inside words and formulas (CO<sub>2</sub>, <scp>CPT</scp>‐based,
# MathML), dropped without a space so the word stays whole
INLINE_TAG = re.compile(r"</?(?:jats:)?(?:sub|sup|i|b|em|strong|u|sc|scp|italic|bold|underline|monospace|"
                        r"span|inline-formula)\b[^>]*>|</?mml:[^>]*>", re.I)


def research_cfg(cfg):
    return cfg.get("research") or {}


def crossref_headers(cfg):
    """Crossref asks API users to name their tool, with a link and (optionally)
    an e-mail address so that it can get in touch about heavy use."""
    repo = site_builder.repository(cfg) or "monabadr12/geotech-news"
    mailto = str(research_cfg(cfg).get("mailto") or "").strip()
    contact = f"https://github.com/{repo}" + (f"; mailto:{mailto}" if mailto else "")
    return {"User-Agent": f"GeotechNewsScanner/1.0 ({contact})"}


def crossref_url(issn, since, cfg):
    params = {"filter": f"from-created-date:{since:%Y-%m-%d},type:journal-article", "sort": "created",
              "order": "desc", "rows": CROSSREF_ROWS, "select": CROSSREF_FIELDS}
    mailto = str(research_cfg(cfg).get("mailto") or "").strip()
    if mailto:
        params["mailto"] = mailto
    return CROSSREF.format(issn=issn) + urlencode(params, safe=":,")


def shorten(text, limit):
    """text cut at a word break so that, with the ellipsis, it has at most limit characters."""
    if len(text) <= limit:
        return text
    return text[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def plain_abstract(raw):
    """Crossref abstracts are JATS XML: drop the headings (Abstract, Purpose…)
    and the tags, keep the text."""
    text = clean(INLINE_TAG.sub("", JATS_HEADING.sub(" ", raw or "")))
    return shorten(re.sub(r"^(?:abstract|summary)\b[\s:.]*", "", text, flags=re.I), 800)


def short_authors(authors):
    """'Smith J, Lee K' for one to three authors, 'Smith J, Lee K et al.' for more."""
    names = []
    for a in authors or []:
        family = clean(a.get("family") or a.get("name") or "")
        if family:
            given = clean(a.get("given") or "")
            initials = "".join(p[0].upper() for p in re.split(r"[\s.\-]+", given) if p)
            names.append(f"{family} {initials}".strip())
    return ", ".join(names[:2]) + " et al." if len(names) > 3 else ", ".join(names)


def crossref_date(item, today):
    """The first complete date among online publication, publication and DOI
    registration that is not in the future."""
    for key in ("published-online", "published", "created"):
        parts = ((item.get(key) or {}).get("date-parts") or [[]])[0] or []
        try:
            day = dt.date(*(int(p) for p in parts)) if len(parts) == 3 else None
        except (TypeError, ValueError):
            day = None
        if day and day <= today:
            return day.isoformat()
    return today.isoformat()


def paper_text(p):
    """What a paper's keyword score reads: its title and, during the scan, its abstract. The archive keeps
    no abstracts (see clear_publisher_text), so for an archived paper the keyword concepts found in the abstract
    stand in for it, kept apart by " | " so that two of them never make up a longer term ("tunnel" and
    "collapse" are not "tunnel collapse")."""
    if p.get("abstract"):
        return f"{p['title']} {p['abstract']}"
    return " | ".join([p["title"], *(p.get("keywords") or [])])


def paper_rank(p, cfg, compiled):
    """Claude's rating first, then the keyword score of title and abstract."""
    return (p.get("relevance") or 0) * 100 + keyword_score(paper_text(p), cfg, compiled)[0]


def select_papers(papers, cfg, compiled=None):
    """Up to research: max_papers papers, best first, spread across the themes
    like the stories."""
    compiled = compiled or compile_keywords(cfg)
    ranks = {p["id"]: paper_rank(p, cfg, compiled) for p in papers}
    limit = int(research_cfg(cfg).get("max_papers", 20))
    return balanced(papers, limit, theme_share(cfg), lambda p: ranks[p["id"]], fill=fill_leftovers(cfg))


def fetch_papers(cfg, now, seen, compiled, failures):
    """New papers of every journal since research: lookback_days, not seen before."""
    rcfg = research_cfg(cfg)
    since = now.date() - dt.timedelta(days=int(rcfg.get("lookback_days", 4)))
    headers = crossref_headers(cfg)
    papers = []
    for journal in rcfg.get("journals") or []:
        name, issn = journal["name"], str(journal["issn"]).strip()
        try:
            r = requests.get(crossref_url(issn, since, cfg), headers=headers, timeout=30)
            r.raise_for_status()
            items = r.json()["message"]["items"]
        except Exception as ex:
            failures.append((f"{name} (Crossref)", str(ex)[:140]))
            continue
        for it in items:
            doi = str(it.get("DOI") or "").strip()
            title = clean(INLINE_TAG.sub("", " ".join(it.get("title") or [])))
            if not doi or not title or NOT_RESEARCH.match(title):
                continue
            pid = hashlib.sha1(f"doi:{doi.lower()}".encode()).hexdigest()[:16]
            if pid in seen:
                continue
            seen[pid] = now.date().isoformat()
            abstract = plain_abstract(it.get("abstract"))
            score, hits = keyword_score(f"{title} {abstract}", cfg, compiled)
            papers.append({
                "id": pid, "title": title, "link": "https://doi.org/" + quote(doi, safe="/:;()._-"),
                "journal": clean(" ".join(it.get("container-title") or [])) or name,
                "authors": short_authors(it.get("author")), "published": crossref_date(it, now.date()),
                "abstract": abstract, "theme": guess_theme(title, cfg["themes"], hits), "relevance": 0,
                "angle": "", "keywords": hits[:6], "score": score})
        time.sleep(0.2)
    return papers


def paper_schema(themes):
    paper = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "relevance": {"type": "integer"},
            "theme": {"type": "string", "enum": themes},
            "angle": {"type": "string"},
        },
        "required": ["id", "relevance", "theme", "angle"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"papers": {"type": "array", "items": paper}},
            "required": ["papers"], "additionalProperties": False}


def claude_papers(papers, cfg, notes):
    """Ask Claude, in one small batch, how useful each paper is in practice and
    why. True if the batch was rated."""
    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    key = clean_api_key(raw)
    if not key or not papers:
        return False
    import anthropic  # only needed when a key is configured

    client = anthropic.Anthropic(api_key=key, max_retries=3)
    ccfg = cfg["claude"]
    themes = list(cfg["themes"].keys()) + ["General"]
    listing = "\n".join(f'{i}. [{p["journal"]}] {p["title"]} :: {p["abstract"][:600]}' for i, p in enumerate(papers))
    prompt = f"""You are the news-desk assistant of the ISSMGE magazine (International Society for Soil Mechanics and Geotechnical Engineering). Its Academia-to-Industry pages tell practising geotechnical engineers about new research they can use.

For each paper below return an object with:
- "id": the number
- "relevance": 1-5 for practice (5 = findings a practising engineer could apply now or should know about: design methods, case histories, field performance, monitoring, new testing or construction techniques; 3 = sound research with a clear route to practice; 1 = theoretical with no near-term use, or not geotechnical)
- "theme": the one magazine theme it fits best
- "angle": one sentence (max 30 words), entirely in your own words, on why the paper matters to practitioners: never copy or closely paraphrase the title or the abstract

Papers:
{listing}"""
    try:
        response = client.messages.create(
            model=ccfg["model"],
            max_tokens=16000,
            output_config={"effort": ccfg.get("effort", "low"),
                           "format": {"type": "json_schema", "schema": paper_schema(themes)}},
            messages=[{"role": "user", "content": prompt}])
        if response.stop_reason != "end_turn":
            raise ValueError(f"stopped early: {response.stop_reason}")
        results = json.loads(next((b.text for b in response.content if b.type == "text"), ""))["papers"]
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as ex:
        if not any(n.startswith("AI triage skipped") for n in notes):  # the stories' note already explains it
            notes.append(f"AI review of research papers skipped: the ANTHROPIC_API_KEY secret was refused "
                         f"({api_message(ex)}). " + describe_key(raw, key))
        return False
    except (anthropic.APIError, ValueError, KeyError, TypeError) as ex:
        msg = api_message(ex) if isinstance(ex, anthropic.APIError) else str(ex)
        notes.append(f"AI review of research papers failed ({msg[:100]}); keyword ranking used.")
        return False
    for d in results:
        idx = int(d["id"])
        if 0 <= idx < len(papers):
            papers[idx].update(relevance=max(1, min(5, int(d["relevance"]))),
                               theme=d["theme"] if d["theme"] in themes else papers[idx]["theme"],
                               angle=d["angle"][:300])
    return True


# "abstract" is kept as a key for older readers but saved empty (clear_publisher_text)
PAPER_FIELDS = ("id", "title", "link", "journal", "authors", "published", "abstract", "theme", "relevance",
                "angle", "keywords")


def research_papers(cfg, now, seen, compiled, failures, notes):
    """The digest's papers (see PAPER_FIELDS), best first; None when no
    journals are configured."""
    rcfg = research_cfg(cfg)
    if not rcfg.get("journals") or rcfg.get("enabled") is False:
        return None
    found = fetch_papers(cfg, now, seen, compiled, failures)
    share = theme_share(cfg)
    candidates = balanced(found, int(rcfg.get("max_candidates", 40)), share, lambda p: p["score"])
    if claude_papers(candidates, cfg, notes):
        minrel = int(rcfg.get("min_relevance", 3))
        found = [p for p in candidates if p["relevance"] >= minrel]
    papers = select_papers(found, cfg, compiled)
    print(f"Research papers: {len(papers)} selected for the digest.")
    return [{k: p[k] for k in PAPER_FIELDS} for p in papers]


# ------------------------------------------------------------------ archive
# Publisher text stays out of the archive. Feed summaries and paper abstracts are read during the scan, for
# the keyword score and for Claude's prompts, but the digests (public, like the website built from them)
# keep only what identifies an article and what the news desk wrote itself: the headline, the source and
# the link, and Claude's angle, translation, place and primary source. The magazine treats each story as a
# lead and writes its own piece from the facts.
def clear_publisher_text(digest):
    """Empty every story's "summary" and every paper's "abstract" in a digest (in place). The keys stay,
    empty, so older readers still find them; nothing else changes. The number of texts emptied."""
    cleared = 0
    for items, key in ((digest.get("stories") or [], "summary"), (digest.get("papers") or [], "abstract")):
        for item in items:
            if isinstance(item, dict) and item.get(key):
                item[key] = ""
                cleared += 1
    return cleared


def clear_archive(folder=None):
    """One-time clean-up (safe to run again): clear_publisher_text() on every digest in the archive,
    written back in the archive's own format. Returns {file name: texts emptied} for the files changed."""
    changed = {}
    for path in sorted((folder or site_builder.DIGESTS).glob("*.json")):
        digest = json.loads(path.read_text(encoding="utf-8"))
        n = clear_publisher_text(digest)
        if n:
            path.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
            changed[path.name] = n
    return changed


def story_text(s):
    """What a story's keyword score reads: its headline and, during the scan, its feed summary. The archive
    keeps no summaries, so the keyword concepts found in the summary stand in for it when an archived story
    is scored again, kept apart by " | " as in paper_text."""
    if s.get("summary"):
        return f"{s['title']} {s['summary']}"
    return " | ".join([s["title"], *(s.get("keywords") or [])])


def rescore_unrated(stories, cfg):
    """Score keyword-ranked stories again with the current lists. Earlier versions
    added a language bonus to the score, which would let old stories crowd out
    new ones when a day's digests are merged."""
    compiled = compile_keywords(cfg)
    for s in stories:
        if not s.get("relevance"):
            s["score"], hits = keyword_score(story_text(s), cfg, compiled)
            s["rank"] = s["score"]
            s["keywords"] = hits[:6]


def merge_papers(ours, theirs, cfg):
    """Union of two lists of papers (ours win), balanced again to max_papers."""
    known = {p["id"] for p in ours}
    return select_papers(list(ours) + [p for p in theirs or [] if p["id"] not in known], cfg)


def save_digest(now, stories, failures, notes, ai_used, new_count, cfg, papers=None):
    """Write today's digest to data/digests/YYYY-MM-DD.json. A second run on the
    same day merges its stories with the morning's file: the union is cleared
    of repeated events (and of copies of one story in several languages) and
    balanced across the themes and websites again, up to max_items, so a
    re-run also mends a lopsided earlier digest. Research papers are merged
    the same way. Feed summaries and abstracts are not saved (clear_publisher_text)."""
    path = site_builder.DIGESTS / f"{now:%Y-%m-%d}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = {"date": f"{now:%Y-%m-%d}", "generated": now.isoformat(timespec="minutes"),
              "ai_used": ai_used, "new_items": new_count, "stories": stories,
              "failures": [list(f) for f in failures], "notes": notes}
    if papers is not None:
        digest["papers"] = papers
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        rescore_unrated(old.get("stories", []), cfg)
        minscore = cfg.get("min_keyword_score", 3)
        earlier = [s for s in old.get("stories", []) if s.get("relevance") or s["score"] >= minscore]
        known = {s["id"] for s in stories}
        union = stories + [s for s in earlier if s["id"] not in known]
        union.sort(key=lambda s: -s["rank"])
        copies = {}
        digest["stories"] = balanced(drop_same_events(union, cfg, copies), cfg.get("max_items", 40),
                                     theme_share(cfg), lambda s: s["rank"], fill=fill_leftovers(cfg),
                                     per_source=source_cap(cfg), copies=copies)
        digest["new_items"] += old.get("new_items", 0)
        digest["ai_used"] = ai_used or old.get("ai_used", False)
        if papers is not None or old.get("papers"):
            digest["papers"] = merge_papers(papers or [], old.get("papers"), cfg)
    digest["stories"].sort(key=lambda s: -s["rank"])
    clear_publisher_text(digest)
    path.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
    return digest


# ------------------------------------------------------------------ main
def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=cfg.get("lookback_hours", 60))
    seen = json.loads(SEEN_FILE.read_text()) if SEEN_FILE.exists() else {}
    compiled = compile_keywords(cfg)

    sources = [dict(s) for s in cfg.get("feeds", [])]
    sources += google_sources(cfg.get("google_news") or {})

    items, failures, notes, new_count = [], [], [], 0
    for src in sources:
        try:
            entries = read_feed(src["url"])
        except Exception as ex:
            if not src.get("google"):
                failures.append((src["name"], str(ex)[:140]))
            continue
        for e in entries:
            link, title = str(e.get("link") or "").strip(), clean(e.get("title"))
            if not re.match(r"https?://", link, re.I):
                link = ""  # only web links are kept
            if not link or not title:
                continue
            uid = hashlib.sha1(link.encode()).hexdigest()[:16]
            if uid in seen:
                continue
            when = entry_time(e)
            if when and when < cutoff:
                continue
            seen[uid] = now.date().isoformat()
            new_count += 1
            source = src["name"]
            if src.get("google"):
                outlet = clean((e.get("source") or {}).get("title"))
                if outlet:
                    source = outlet
                    title = re.sub(r"\s+-\s+" + re.escape(outlet) + r"$", "", title)
            summary = clean(e.get("summary"))
            if src.get("google"):
                summary = ""  # Google's summary just repeats the headline
            text = f"{title} {summary}"
            score, hits = keyword_score(text, cfg, compiled)
            score += src.get("boost", 0) if hits else 0
            items.append(dict(id=uid, title=title, link=link, source=source, summary=summary,
                              time=when, region=src.get("region", ""), score=score, hits=hits,
                              bonus=src.get("bonus", 0),
                              theme=guess_theme(text, cfg["themes"], hits),
                              relevance=0, use="", angle="", title_en=""))
        time.sleep(0.3)

    # the same event from several outlets: keep its best-scoring headline
    items.sort(key=lambda i: (-i["score"], -i["bonus"]))
    first_copies = {}  # other outlets' reports of an event, merged before Claude reads the headlines
    unique = drop_same_events(items, cfg, first_copies)

    # The language bonus only lifts foreign headlines, whose words the keyword
    # lists may miss, over min_keyword_score so that Claude can read them. It
    # plays no part in ranking: score is the keyword score alone.
    minscore = cfg.get("min_keyword_score", 3)
    share = theme_share(cfg)
    pool = [i for i in unique if i["score"] + i["bonus"] >= minscore]
    # no website fills Claude's list either; each may send three times
    # max_per_source, since its copies of one story in other languages are only
    # found (and counted once) in Claude's translations
    candidates = balanced(pool, cfg["claude"].get("max_candidates", 80), share, lambda i: i["score"],
                          per_source=3 * source_cap(cfg))
    ai_used = claude_triage(candidates, cfg, notes)
    if ai_used:
        minrel = cfg["claude"].get("min_relevance", 3)
        # stories of a batch Claude could not rate fall back to their keywords
        kept = [i for i in candidates
                if i["relevance"] >= minrel or (i["relevance"] == 0 and i["score"] >= minscore)]
    else:
        # without Claude the candidate cap does not apply: every story whose
        # keywords pass on their own competes for the digest
        kept = [i for i in pool if i["score"] >= minscore]
    for i in kept:
        i["rank"] = i["relevance"] * 100 + i["score"]
    copies = {}
    if ai_used:
        # Claude's English titles show the copies of one story in other languages
        # (and reports of one event in two languages): the best one is kept
        kept.sort(key=lambda i: -i["rank"])
        kept = drop_same_events(kept, cfg, copies)
    # the reports merged before Claude stand in too, with the reading of the story they were merged into
    final = {i["id"]: i["id"] for i in kept}
    final.update({c["id"]: k for k, cs in copies.items() for c in cs})
    rated = {i["id"]: i for i in kept} | {c["id"]: c for cs in copies.values() for c in cs}
    for head, reports in first_copies.items():
        if head not in final:
            continue
        h = rated[head]
        for c in reports:
            c.update(relevance=h["relevance"], theme=h["theme"], use=h["use"], angle=h["angle"],
                     title_en=c["title_en"] or h["title_en"], rank=h["relevance"] * 100 + c["score"],
                     **({"country": h.get("country", ""), "place": h.get("place", ""),
                         "primary_source": h.get("primary_source", "")} if h["relevance"] else {}))
            copies.setdefault(final[head], []).append(c)
    for cs in copies.values():
        cs.sort(key=lambda c: -c["rank"])
    selected = balanced(kept, cfg.get("max_items", 40), share, lambda i: i["rank"], fill=fill_leftovers(cfg),
                        per_source=source_cap(cfg), copies=copies)

    # new research papers for the Academia-to-Industry pages (remembered by DOI)
    papers = research_papers(cfg, now, seen, compiled, failures, notes)

    # prune memory older than 45 days
    limit = (now - dt.timedelta(days=45)).date().isoformat()
    seen = {k: v for k, v in seen.items() if v >= limit}
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen, indent=0))

    stories = [{
        "id": i["id"], "title": i["title"], "title_en": i["title_en"], "link": i["link"],
        # the feed summary is only for Claude's reading below: save_digest() saves it empty
        "source": i["source"], "region": i["region"], "summary": i["summary"][:400],
        "published": i["time"].isoformat(timespec="minutes") if i["time"] else "",
        "theme": i["theme"], "relevance": i["relevance"], "use": i["use"], "angle": i["angle"],
        "keywords": i["hits"][:6], "score": i["score"], "rank": i["rank"],
        # where the story happened, as Claude read it ("" = global), and whom to check the facts
        # with; stories Claude did not rate have no "country" yet, so geomap.locate_missing()
        # locates them below, while their feed summaries are still here to read
        **({"country": i.get("country", ""), "place": i.get("place", ""),
            "primary_source": i.get("primary_source", "")} if i["relevance"] else {}),
    } for i in selected]

    import geomap, storylines  # (they import this module, so not at the top)
    storylines.link(stories, now, cfg, notes)  # follow-up reports joined to the earlier event
    geomap.locate_missing(cfg, notes, today=stories)  # today's and archived stories with no country yet
    save_digest(now, stories, failures, notes, ai_used, new_count, cfg, papers)
    site_builder.build(cfg)
    # e-mail (alerts for 5/5 stories, the Monday summary) is sent by notify.py, a later workflow step
    print(f"{new_count} new items, {len(selected)} selected, {len(failures)} failed sources.")
    for n, e in failures:
        print(f"  failed: {n}: {e}")


def reclassify():
    """Re-tag and re-theme archived stories that Claude did not triage, using
    the current keyword and theme lists, then rebuild the site."""
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    compiled = compile_keywords(cfg)
    for path in sorted(site_builder.DIGESTS.glob("*.json")):
        digest = json.loads(path.read_text(encoding="utf-8"))
        changed = 0
        for s in digest["stories"]:
            if s.get("relevance"):
                continue  # Claude's theme stands
            text = story_text(s)
            _, hits = keyword_score(text, cfg, compiled)
            theme = guess_theme(text, cfg["themes"], hits)
            if theme != s["theme"] or hits[:6] != s.get("keywords"):
                s["theme"], s["keywords"] = theme, hits[:6]
                changed += 1
        for p in digest.get("papers", []):
            if p.get("relevance"):
                continue
            _, hits = keyword_score(paper_text(p), cfg, compiled)
            theme = guess_theme(p["title"], cfg["themes"], hits)
            if theme != p["theme"] or hits[:6] != p.get("keywords"):
                p["theme"], p["keywords"] = theme, hits[:6]
                changed += 1
        if changed:
            clear_publisher_text(digest)
            path.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{path.name}: {changed} stories re-classified")
    site_builder.build(cfg)


def rebalance(names):
    """Clear repeated events (and copies of one story in several languages) from
    the named digests and balance them across the themes and websites again
    (used when two runs saved the same day)."""
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    minscore = cfg.get("min_keyword_score", 3)
    for name in names:
        path = site_builder.DIGESTS / Path(name).name
        digest = json.loads(path.read_text(encoding="utf-8"))
        rescore_unrated(digest["stories"], cfg)
        stories = sorted((s for s in digest["stories"] if s.get("relevance") or s["score"] >= minscore),
                         key=lambda s: -s["rank"])
        copies = {}
        digest["stories"] = balanced(drop_same_events(stories, cfg, copies), cfg.get("max_items", 40),
                                     theme_share(cfg), lambda s: s["rank"], fill=fill_leftovers(cfg),
                                     per_source=source_cap(cfg), copies=copies)
        if digest.get("papers"):
            digest["papers"] = select_papers(digest["papers"], cfg)
        clear_publisher_text(digest)
        path.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{path.name}: {len(digest['stories'])} stories after re-balancing")


def clear_archive_main():
    """python scanner.py --clear-publisher-text: empty the feed summaries and abstracts that digests saved
    before they stopped being kept (the archive is public); nothing else in the digests changes."""
    changed = clear_archive()
    for name, n in changed.items():
        print(f"{name}: {n} feed {'summary or abstract' if n == 1 else 'summaries and abstracts'} emptied")
    print(f"{len(changed)} digest(s) changed." if changed else "No digest holds a feed summary or abstract.")
    return 0


if __name__ == "__main__":
    if "--rebalance" in sys.argv:
        sys.exit(rebalance(sys.argv[sys.argv.index("--rebalance") + 1:]))
    if "--clear-publisher-text" in sys.argv:
        sys.exit(clear_archive_main())
    sys.exit(reclassify() if "--reclassify" in sys.argv else main())
