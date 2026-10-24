#!/usr/bin/env python3
"""
ISSMGE Magazine — Geotechnical News Scanner
Reads trade-site feeds and Google News searches, scores stories for
geotechnical relevance, (optionally) asks Claude to triage them, saves the
digest to data/digests/ (the permanent archive) and rebuilds the website in
docs/ (GitHub Pages). Optionally e-mails the digest.
"""
import calendar
import datetime as dt
import difflib
import functools
import hashlib
import html
import json
import math
import os
import re
import smtplib
import ssl
import sys
import time
import unicodedata
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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


def drop_same_events(items, cfg):
    """Keep one headline per event. Items must come best first. Headlines that
    match, directly or through a chain of re-wordings, form one group, and only
    the group's best headline is kept."""
    topic = topic_words(cfg)
    marks = []
    for it in items:
        norm = title_norm(it["title"])
        marks.append((norm, title_words(norm, topic), title_names(it["title"], topic)))
    parent = list(range(len(items)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i):
            if root(i) != root(j) and same_event(marks[i], marks[j]):
                parent[max(root(i), root(j))] = min(root(i), root(j))
    kept, groups = [], set()
    for i, it in enumerate(items):
        if root(i) not in groups:  # the first item of each group is its best
            groups.add(root(i))
            kept.append(it)
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


def balanced(items, limit, share, rank, fill=True):
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
        },
        "required": ["id", "relevance", "theme", "use", "angle", "title_en"],
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
- "angle": one sentence (max 30 words) stating the geotechnical question a magazine piece could explore, in your own words
- "title_en": if the headline is not in English, your English translation of it (max 20 words); otherwise ""

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
                    title_en=d["title_en"][:200])
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
    return f"{p['title']} {p.get('abstract', '')}"


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
- "angle": one sentence (max 30 words), in your own words, on why the paper matters to practitioners

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


# ------------------------------------------------------------------ e-mail
def send_email(subject, body_html):
    host, to = os.environ.get("SMTP_HOST", "").strip(), os.environ.get("MAIL_TO", "").strip()
    if not host or not to:
        return "E-mail not configured (optional)."
    user, pwd = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
    port = int(os.environ.get("SMTP_PORT", "587") or 587)
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, user or to, to
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    with smtplib.SMTP(host, port, timeout=60) as s:
        s.starttls(context=ssl.create_default_context())  # verify the mail server's certificate
        if user:
            s.login(user, pwd)
        s.sendmail(msg["From"], [a.strip() for a in to.split(",")], msg.as_string())
    return f"E-mail sent to {to}."


# ------------------------------------------------------------------ archive
def rescore_unrated(stories, cfg):
    """Score keyword-ranked stories again with the current lists. Earlier versions
    added a language bonus to the score, which would let old stories crowd out
    new ones when a day's digests are merged."""
    compiled = compile_keywords(cfg)
    for s in stories:
        if not s.get("relevance"):
            s["score"], hits = keyword_score(f"{s['title']} {s.get('summary', '')}", cfg, compiled)
            s["rank"] = s["score"]
            s["keywords"] = hits[:6]


def merge_papers(ours, theirs, cfg):
    """Union of two lists of papers (ours win), balanced again to max_papers."""
    known = {p["id"] for p in ours}
    return select_papers(list(ours) + [p for p in theirs or [] if p["id"] not in known], cfg)


def save_digest(now, stories, failures, notes, ai_used, new_count, cfg, papers=None):
    """Write today's digest to data/digests/YYYY-MM-DD.json. A second run on the
    same day merges its stories with the morning's file: the union is cleared
    of repeated events and balanced across the themes again, up to max_items,
    so a re-run also mends a lopsided earlier digest. Research papers are
    merged the same way."""
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
        digest["stories"] = balanced(drop_same_events(union, cfg), cfg.get("max_items", 40),
                                     theme_share(cfg), lambda s: s["rank"], fill=fill_leftovers(cfg))
        digest["new_items"] += old.get("new_items", 0)
        digest["ai_used"] = ai_used or old.get("ai_used", False)
        if papers is not None or old.get("papers"):
            digest["papers"] = merge_papers(papers or [], old.get("papers"), cfg)
    digest["stories"].sort(key=lambda s: -s["rank"])
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
    unique = drop_same_events(items, cfg)

    # The language bonus only lifts foreign headlines, whose words the keyword
    # lists may miss, over min_keyword_score so that Claude can read them. It
    # plays no part in ranking: score is the keyword score alone.
    minscore = cfg.get("min_keyword_score", 3)
    share = theme_share(cfg)
    pool = [i for i in unique if i["score"] + i["bonus"] >= minscore]
    candidates = balanced(pool, cfg["claude"].get("max_candidates", 80), share, lambda i: i["score"])
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
    selected = balanced(kept, cfg.get("max_items", 40), share, lambda i: i["rank"], fill=fill_leftovers(cfg))

    # new research papers for the Academia-to-Industry pages (remembered by DOI)
    papers = research_papers(cfg, now, seen, compiled, failures, notes)

    # prune memory older than 45 days
    limit = (now - dt.timedelta(days=45)).date().isoformat()
    seen = {k: v for k, v in seen.items() if v >= limit}
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen, indent=0))

    stories = [{
        "id": i["id"], "title": i["title"], "title_en": i["title_en"], "link": i["link"],
        "source": i["source"], "region": i["region"], "summary": i["summary"][:400],
        "published": i["time"].isoformat(timespec="minutes") if i["time"] else "",
        "theme": i["theme"], "relevance": i["relevance"], "use": i["use"], "angle": i["angle"],
        "keywords": i["hits"][:6], "score": i["score"], "rank": i["rank"],
    } for i in selected]
    digest = save_digest(now, stories, failures, notes, ai_used, new_count, cfg, papers)
    site_builder.build(cfg)

    try:
        mail_note = None
        if selected:
            mail_note = send_email(
                f"Geotechnical News Digest — {now:%d %b %Y} ({len(digest['stories'])} stories)",
                site_builder.render_email(digest, cfg))
    except Exception as ex:
        mail_note = f"E-mail failed: {ex}"
    print(f"{new_count} new items, {len(selected)} selected, {len(failures)} failed sources. {mail_note or ''}")
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
            text = f"{s['title']} {s.get('summary', '')}"
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
            path.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"{path.name}: {changed} stories re-classified")
    site_builder.build(cfg)


def rebalance(names):
    """Clear repeated events from the named digests and balance them across the
    themes again (used when two runs saved the same day)."""
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    minscore = cfg.get("min_keyword_score", 3)
    for name in names:
        path = site_builder.DIGESTS / Path(name).name
        digest = json.loads(path.read_text(encoding="utf-8"))
        rescore_unrated(digest["stories"], cfg)
        stories = sorted((s for s in digest["stories"] if s.get("relevance") or s["score"] >= minscore),
                         key=lambda s: -s["rank"])
        digest["stories"] = balanced(drop_same_events(stories, cfg), cfg.get("max_items", 40), theme_share(cfg),
                                     lambda s: s["rank"], fill=fill_leftovers(cfg))
        if digest.get("papers"):
            digest["papers"] = select_papers(digest["papers"], cfg)
        path.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{path.name}: {len(digest['stories'])} stories after re-balancing")


if __name__ == "__main__":
    if "--rebalance" in sys.argv:
        sys.exit(rebalance(sys.argv[sys.argv.index("--rebalance") + 1:]))
    sys.exit(reclassify() if "--reclassify" in sys.argv else main())
