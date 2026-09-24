"""Verse reference handling for the Scripture desktop app.

A faithful port of the Omarchy Scripture widget's `Scripture.js` (.pragma
library): the curated no-repeat deck, range/focal parsing, passage splitting,
and the rich-text composer. Pure Python, no Qt dependency, so it is unit- and
smoke-testable on any platform. When these two diverge, the Omarchy plugin is
the upstream source of truth — keep this file in sync with it.
"""

import math
import random
import re

# Hard cap mirrors the plugin: a single short passage is a few KB, so this
# bounds a misbehaving endpoint without ever trimming a real response.
MAX_RESPONSE_BYTES = 262144
MAX_REFERENCE_BYTES = 120

# Well-known, always-valid references drawn across the whole Bible. Random
# picks are drawn from this deck so a request can never throw a nonexistent
# chapter:verse.
SCRIPTURE = [
    "Genesis 1:1", "Genesis 1:27", "Genesis 2:18", "Genesis 12:2", "Genesis 28:15",
    "Exodus 14:14", "Exodus 15:2", "Exodus 20:12", "Exodus 33:14",
    "Leviticus 19:18", "Leviticus 26:12",
    "Numbers 6:24", "Numbers 23:19",
    "Deuteronomy 6:5", "Deuteronomy 31:6", "Deuteronomy 33:27",
    "Joshua 1:9", "Joshua 24:15",
    "Judges 6:24",
    "Ruth 1:16",
    "1 Samuel 16:7", "1 Samuel 12:24",
    "2 Samuel 22:31",
    "1 Kings 8:61",
    "2 Kings 19:19",
    "1 Chronicles 16:11",
    "2 Chronicles 7:14",
    "Ezra 7:10",
    "Nehemiah 8:10",
    "Job 1:21", "Job 19:25", "Job 42:2",
    "Psalm 1:1", "Psalm 16:11", "Psalm 19:1", "Psalm 23:1", "Psalm 23:4",
    "Psalm 27:1", "Psalm 30:5", "Psalm 32:8", "Psalm 34:8", "Psalm 37:4",
    "Psalm 37:5", "Psalm 46:1", "Psalm 46:10", "Psalm 55:22", "Psalm 62:8",
    "Psalm 91:1", "Psalm 103:12", "Psalm 118:24", "Psalm 119:105", "Psalm 127:1",
    "Psalm 133:1", "Psalm 139:14", "Psalm 145:18", "Psalm 150:6",
    "Proverbs 3:5", "Proverbs 3:6", "Proverbs 16:3", "Proverbs 17:17",
    "Proverbs 18:10", "Proverbs 27:17",
    "Ecclesiastes 3:1", "Ecclesiastes 12:13",
    "Song of Solomon 4:7",
    "Isaiah 40:8", "Isaiah 40:31", "Isaiah 41:10", "Isaiah 41:13", "Isaiah 43:2",
    "Isaiah 53:5", "Isaiah 55:8", "Isaiah 58:11",
    "Jeremiah 29:11", "Jeremiah 33:3", "Lamentations 3:22", "Ezekiel 34:15",
    "Daniel 2:20", "Hosea 6:6", "Joel 2:13", "Amos 5:24", "Jonah 2:2",
    "Micah 6:8", "Nahum 1:7", "Habakkuk 3:19", "Zephaniah 3:17", "Haggai 2:4",
    "Zechariah 4:6", "Malachi 3:10",
    "Matthew 5:14", "Matthew 6:33", "Matthew 6:34", "Matthew 7:7", "Matthew 11:28",
    "Matthew 28:20",
    "Mark 9:23", "Mark 11:24",
    "Luke 1:37", "Luke 6:38", "Luke 10:27", "Luke 12:32", "Luke 15:10",
    "John 1:29", "John 3:16", "John 6:35", "John 8:32", "John 10:10", "John 10:27",
    "John 11:25", "John 13:34", "John 14:6", "John 14:27", "John 15:5", "John 16:33",
    "Acts 1:8", "Acts 4:12", "Acts 16:31",
    "Romans 3:23", "Romans 5:8", "Romans 8:28", "Romans 8:38", "Romans 10:9",
    "Romans 12:2", "Romans 12:12", "Romans 15:13",
    "1 Corinthians 10:13", "1 Corinthians 13:4", "1 Corinthians 15:58",
    "1 Corinthians 16:14",
    "2 Corinthians 5:17", "2 Corinthians 5:18", "2 Corinthians 12:9",
    "Galatians 5:22", "Galatians 6:9",
    "Ephesians 2:8", "Ephesians 2:10", "Ephesians 3:20", "Ephesians 4:32",
    "Ephesians 6:10",
    "Philippians 4:4", "Philippians 4:6", "Philippians 4:8", "Philippians 4:13",
    "Philippians 4:19",
    "Colossians 3:2", "Colossians 3:23",
    "1 Thessalonians 5:16", "1 Thessalonians 5:18",
    "2 Thessalonians 3:3",
    "1 Timothy 2:5", "1 Timothy 4:12", "1 Timothy 6:12",
    "2 Timothy 1:7", "2 Timothy 2:15", "2 Timothy 3:16", "2 Timothy 4:7",
    "Titus 2:11", "Philemon 1:6",
    "Hebrews 10:35", "Hebrews 11:1", "Hebrews 11:6", "Hebrews 12:1", "Hebrews 12:2",
    "Hebrews 13:5", "Hebrews 13:8",
    "James 1:5", "James 1:17", "James 2:17", "James 4:8", "James 4:10", "James 5:16",
    "1 Peter 2:9", "1 Peter 5:7",
    "2 Peter 1:4", "2 Peter 3:9",
    "1 John 1:9", "1 John 4:7", "1 John 4:19", "1 John 5:14",
    "2 John 1:6",
    "3 John 1:2",
    "Jude 1:21",
    "Revelation 3:20", "Revelation 21:4", "Revelation 22:20",
]

_REFERENCE = re.compile(
    r"^(?:[1-3]\s+)?[A-Za-z]+(?:\s+[A-Za-z]+)*\s+(\d{1,3}):(\d{1,3})(?:-(\d{1,3}))?$"
)
_RANGE = re.compile(r"^(.*?)\s+(\d+):(\d+)$")
_FOCAL = re.compile(r"^.*?\s+\d+:(\d+)$")
_VERSE_MARKER = re.compile(r"\[(\d+)\]([\s\S]*?)(?=\[\d+\]|$)", re.DOTALL)


def normalize_reference(value: str) -> str:
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 for char in value):
        return ""
    text = re.sub(r"[ \t]+", " ", value).strip()
    if not text:
        return ""
    try:
        if len(text.encode("utf-8")) > MAX_REFERENCE_BYTES:
            return ""
    except UnicodeError:
        return ""
    match = _REFERENCE.fullmatch(text)
    if not match:
        return ""
    chapter = int(match.group(1))
    verse = int(match.group(2))
    end_verse = verse if match.group(3) is None else int(match.group(3))
    if chapter < 1 or verse < 1 or end_verse < verse:
        return ""
    return text


def is_valid_reference(value: str) -> bool:
    return bool(normalize_reference(value))


class Deck:
    """No-repeat rotation through the curated deck.

    A verse is not repeated until every reference has been drawn. The deck is
    reshuffled when exhausted, and a draw that follows a reshuffle can never
    equal the immediately previous reference.
    """

    def __init__(self, references=None):
        source = list(references if references is not None else SCRIPTURE)
        self._pool = [normalize_reference(item) for item in source]
        self._pool = [item for item in self._pool if item]
        if not self._pool:
            self._pool = list(SCRIPTURE)
        self._deck: list[str] = []
        self._pos = 0

    def _shuffle(self) -> None:
        pool = self._pool[:]
        random.shuffle(pool)
        self._deck = pool
        self._pos = 0

    def draw(self, avoid: str = "") -> str:
        if self._pos >= len(self._deck):
            self._shuffle()
        reference = self._deck[self._pos]
        self._pos += 1
        if reference == avoid and len(self._deck) > 1:
            reference = self._deck[self._pos % len(self._deck)]
            self._pos += 1
        return reference


def clean_esv_text(raw: str, reference: str) -> str:
    """Collapse an api.esv.org passage string into one display paragraph.

    Drops the leading reference line (when present), any residual verse
    markers, and the trailing copyright suffix.
    """
    text = re.sub(r"[ \t]+", " ", (raw or "").replace("\r\n", "\n")).strip()

    if reference:
        line = text.split("\n")[0].strip()
        if line.lower() == str(reference).strip().lower():
            text = text[len(line):].lstrip("\n ")

    text = re.sub(r"\s*\(ESV\)\s*$", "", text)
    text = re.sub(r"^\s*\[\d+\]\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def clean_web_text(payload: dict) -> str:
    """Collapse a bible-api.com payload (random or list shape) into text."""
    random_verse = payload.get("random_verse") or {}
    if random_verse.get("text"):
        return re.sub(r"\s{2,}", " ", str(random_verse["text"])).strip()

    verses = payload.get("verses") or []
    if not verses:
        return str(payload.get("text") or "").strip()

    parts = [str(v.get("text") or "").strip() for v in verses if v.get("text")]
    return re.sub(r"\s{2,}", " ", " ".join(parts)).strip()


def reference_text(payload: dict) -> str:
    """Best-effort anchor reference for a bible-api.com response."""
    random_verse = payload.get("random_verse") or {}
    if random_verse.get("book") and random_verse.get("chapter") and random_verse.get("verse"):
        return normalize_reference(
            "{0} {1}:{2}".format(
                random_verse["book"], random_verse["chapter"], random_verse["verse"]
            )
        )
    return normalize_reference(payload.get("reference") or "")


def translation_text(payload: dict) -> str:
    """bible-api.com translation name, or a bare id."""
    translation = payload.get("translation") or {}
    if translation.get("name"):
        return str(translation["name"]).strip()
    return str(payload.get("translation_name") or "")


def range_query(reference: str, margin: int = 2) -> str:
    """A curated anchor ('John 3:16') becomes a short context window.

    Returns 'John 3:14-18' so a tiny verse is never shown without context.
    """
    normalized = normalize_reference(reference)
    if not normalized:
        return ""
    match = _RANGE.fullmatch(normalized)
    if not match:
        return normalized
    book = match.group(1)
    chapter = int(match.group(2))
    verse = int(match.group(3))
    try:
        margin = max(0, min(20, int(margin)))
    except (TypeError, ValueError):
        margin = 2
    start = max(1, verse - margin)
    end = verse + margin
    if start == end:
        return book + " " + str(chapter) + ":" + str(verse)
    return book + " " + str(chapter) + ":" + str(start) + "-" + str(end)


def focal_verse(reference: str) -> int:
    """Which verse number inside a fetched range is the curated anchor? 0 = not derivable."""
    normalized = normalize_reference(reference)
    match = _FOCAL.fullmatch(normalized) if normalized else None
    return int(match.group(1)) if match and "-" not in normalized else 0


def parse_numbered_passage(text: str, focal: int) -> tuple:
    """Split an ESV passage into (before, focal, after) around the anchor verse.

    Verse markers ('[n]') carry the numbering into the display. When the focal
    verse is absent the whole passage becomes focal with no context.
    """
    normalized = re.sub(r"[ \t]+", " ", (text or "").replace("\r\n", "\n")).strip()
    tokens = [
        {"n": int(m.group(1)), "t": m.group(2)}
        for m in _VERSE_MARKER.finditer(normalized)
    ]

    if not tokens:
        clean = re.sub(r"\n{2,}", "\n", normalized).strip()
        return "", clean, ""

    before: list[str] = []
    focal_text = ""
    after: list[str] = []
    found = False
    for token in tokens:
        verse_text = re.sub(r"\s+", " ", token["t"]).strip()
        if not verse_text:
            continue
        if token["n"] == focal and not found:
            focal_text = "[{0}] {1}".format(token["n"], verse_text)
            found = True
        elif not found:
            before.append("[{0}] {1}".format(token["n"], verse_text))
        else:
            after.append("[{0}] {1}".format(token["n"], verse_text))

    if not focal_text:
        whole = [
            "[{0}] {1}".format(t["n"], re.sub(r"\s+", " ", t["t"]).strip())
            for t in tokens
            if re.sub(r"\s+", " ", t["t"]).strip()
        ]
        return "", " ".join(whole), ""

    return " ".join(before), focal_text, " ".join(after)


def parse_web_passage(payload: dict, focal: int) -> tuple:
    """Split a bible-api.com range response around the anchor the same way."""
    before: list[str] = []
    focal_text = ""
    after: list[str] = []
    found = False
    for verses in payload.get("verses") or []:
        number = int(verses.get("verse") or verses.get("number") or 0)
        text = str(verses.get("text") or "").rstrip()
        text = re.sub(r"\s+", " ", text).strip()
        if not text and not number:
            continue

        if number == focal and not found:
            focal_text = "[{0}] {1}".format(number, text)
            found = True
        elif not found:
            before.append("[{0}] {1}".format(number, text))
        else:
            after.append("[{0}] {1}".format(number, text))

    if not focal_text:
        whole = [str(v.get("text") or "").strip() for v in payload.get("verses") or []]
        whole = [w for w in whole if w]
        return "", " ".join(whole), ""

    return " ".join(before), focal_text, " ".join(after)


def _escape(content: str) -> str:
    return (
        str(content)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def compose_rich_text(before: str, focal: str, after: str, max_chars: int = -1) -> str:
    """One rich-text string: leading/trailing context dimmed, the anchor bright.

    All spans inherit the Text element's size, keeping lines even. `max_chars`
    optionally truncates reveal progress across before -> focal -> after.
    """
    b = str(before if before is not None else "")
    f = str(focal if focal is not None else "")
    a = str(after if after is not None else "")

    if max_chars is not None and max_chars >= 0:
        bl, fl = len(b), len(f)
        if max_chars <= bl:
            b, f, a = b[:max_chars], "", ""
        elif max_chars <= bl + fl:
            f = f[: max_chars - bl]
            a = ""
        else:
            a = a[: max_chars - bl - fl]

    def span(color: str, content: str) -> str:
        return "" if content == "" else '<span style="color:{0};">{1}</span>'.format(color, _escape(content))

    return (
        span("rgba(255,255,255,0.55)", b)
        + span("#ffffff", f)
        + span("rgba(255,255,255,0.55)", a)
    )


def browser_url(reference: str, translation_id: str) -> str:
    """The public reading page for a reference in a given translation."""
    import urllib.parse

    normalized = normalize_reference(reference)
    if not normalized:
        return ""
    slug = urllib.parse.quote(normalized, safe="-_.!~*'()")
    translation = str(translation_id or "web").strip().lower()
    if translation == "esv":
        return "https://www.esv.org/" + slug + "/"
    version = "KJV" if translation == "kjv" else "WEB"
    return "https://www.biblegateway.com/passage/?search=" + slug + "&version=" + version


def encode_reference(reference: str) -> str:
    normalized = normalize_reference(reference)
    return quote(normalized) if normalized else ""


def quote(value: str) -> str:
    """Percent-encode like JavaScript's encodeURIComponent for URL segments."""
    import urllib.parse

    return urllib.parse.quote(str(value or ""), safe="-_.!~*'()")
