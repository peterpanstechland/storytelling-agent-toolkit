"""Word-timed lyric queries and karaoke subtitle events.

Adapted from mexicat/pdoom-video `app/src/engine/lyrics.ts` and `smart` / `plain`
in `app/src/engine/type.ts`. MIT License. Copyright (c) 2026 Giacomo Magnanini.
https://github.com/mexicat/pdoom-video

The upstream song, audio, scenes and lyric files are not included. Callers supply
their own timed lines.
"""
import re


class LyricError(ValueError):
    pass


def smart(text):
    """Curly quotes and an ellipsis, matching the upstream type helper."""
    text = text.replace("...", "…")
    text = re.sub(
        r"(^|[\s([{—–-])'(?=(?:cause|cos|til|em|round|n|tis|twas|\d0s)\b)",
        r"\1’",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"(^|[\s([{—–-])'", r"\1‘", text)
    text = text.replace("'", "’")
    text = re.sub(r'(^|[\s([{—–-])"', r"\1“", text)
    text = text.replace('"', "”")
    return text


def plain(text):
    return text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"').replace("…", "...")


def _fold(text):
    return text.lower().replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')


def _norm(text):
    return re.sub(r"[^a-z0-9()]", "", text.lower())


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LyricError(f"{label} must be a number")
    if value < 0:
        raise LyricError(f"{label} must be >= 0")
    return float(value)


class Word:
    def __init__(self, raw, line, index):
        if not isinstance(raw, dict) or not isinstance(raw.get("w"), str) or not raw["w"]:
            raise LyricError("each word needs a non-empty w")
        self.w = smart(raw["w"])
        self.start = _number(raw.get("start"), "word.start")
        self.end = _number(raw.get("end"), "word.end")
        if self.end <= self.start:
            raise LyricError(f"word {raw['w']!r} must end after it starts")
        syllables = raw.get("syl")
        self.syl = None
        if syllables is not None:
            if not isinstance(syllables, list) or not syllables:
                raise LyricError("syl must be a non-empty list of [start, end] pairs")
            self.syl = []
            for pair in syllables:
                if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                    raise LyricError("each syllable is [start, end]")
                a, b = _number(pair[0], "syl.start"), _number(pair[1], "syl.end")
                if b <= a:
                    raise LyricError("each syllable must end after it starts")
                self.syl.append((a, b))
        self.line = line
        self.index = index
        self.gi = 0


class Line:
    def __init__(self, raw, index):
        if not isinstance(raw, dict):
            raise LyricError("each line must be an object")
        words = raw.get("words")
        if not isinstance(words, list) or not words:
            raise LyricError("each line needs words")
        self.i = index
        self.words = [Word(word, index, i) for i, word in enumerate(words)]
        text = raw.get("text")
        if text is None:
            text = " ".join(word.w for word in self.words)
        if not isinstance(text, str) or not text.strip():
            raise LyricError("line text must be a non-empty string")
        self.text = smart(text)
        self.start = _number(raw["start"], "line.start") if "start" in raw else self.words[0].start
        self.end = _number(raw["end"], "line.end") if "end" in raw else self.words[-1].end
        if self.end <= self.start:
            raise LyricError("line must end after it starts")


class Lyrics:
    def __init__(self, payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("lines"), list) or not payload["lines"]:
            raise LyricError("lyrics need a non-empty lines array")
        self.title = payload.get("title") or ""
        self.lines = [Line(line, i) for i, line in enumerate(payload["lines"])]
        self.words = [word for line in self.lines for word in line.words]
        for index, word in enumerate(self.words):
            word.gi = index

    def line_at(self, t):
        return next((line for line in self.lines if line.start <= t < line.end), None)

    def last_line(self, t):
        best = None
        for line in self.lines:
            if line.start <= t:
                best = line
        return best

    def next_line(self, t):
        return next((line for line in self.lines if line.start > t), None)

    def lines_in(self, t0, t1):
        return [line for line in self.lines if line.end > t0 and line.start < t1]

    def find(self, text):
        query = _fold(text)
        return [line for line in self.lines if query in _fold(line.text)]

    def get(self, text, nth=0):
        found = self.find(text)
        if nth >= len(found):
            raise LyricError(f"lyric not found: {text}")
        return found[nth]

    def word_at(self, t):
        return next((word for word in self.words if word.start <= t < word.end), None)

    def last_word(self, t):
        best = None
        for word in self.words:
            if word.start <= t:
                best = word
        return best

    def find_words(self, text):
        query = _norm(text)
        return [word for word in self.words if _norm(plain(word.w)) == query]

    @staticmethod
    def word_progress(word, t):
        if word is None or t <= word.start:
            return 0.0
        if t >= word.end:
            return 1.0
        if word.syl and len(word.syl) > 1:
            count = len(word.syl)
            for index, (start, end) in enumerate(word.syl):
                if t < start:
                    return index / count
                if t < end:
                    return (index + (t - start) / max(1e-3, end - start)) / count
            return 1.0
        return (t - word.start) / max(1e-3, word.end - word.start)

    @staticmethod
    def line_char_progress(line, t):
        if line is None:
            return 0.0
        chars = 0.0
        for word in line.words:
            progress = Lyrics.word_progress(word, t)
            chars += progress * len(word.w)
            if progress < 1:
                break
            chars += 1  # the space the upstream counter inserts between words
        return min(chars, float(len(line.text)))


def karaoke_syllables(line):
    """Centisecond karaoke chunks from each word's own start and end."""
    chunks = []
    for word in line.words:
        centiseconds = max(1, int(round((word.end - word.start) * 100)))
        chunks.append((centiseconds, word.w))
    return chunks


def ass_escape(text):
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}").replace("\n", "\\N")


def ass_time(seconds):
    centiseconds = max(0, int(round(seconds * 100)))
    hours, centiseconds = divmod(centiseconds, 360000)
    minutes, centiseconds = divmod(centiseconds, 6000)
    whole, centiseconds = divmod(centiseconds, 100)
    return f"{hours}:{minutes:02}:{whole:02}.{centiseconds:02}"


def to_ass(lyrics, width=1920, height=1080, font="Noto Sans CJK SC"):
    """ASS dialogue with \\k wipes. Sung fill is primary; the rest is secondary."""
    header = "\n".join([
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(width)}",
        f"PlayResY: {int(height)}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Karaoke,{font},{max(28, int(height * 0.046))},"
        "&H00FFFFFF,&H00808080,&H00202020,&H64000000,0,0,0,0,100,100,0,0,1,3,0,2,80,80,72,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ])
    events = []
    for line in lyrics.lines:
        pieces = [f"{{\\k{cs}}}{ass_escape(text)}" for cs, text in karaoke_syllables(line)]
        body = " ".join(pieces)
        events.append(
            f"Dialogue: 0,{ass_time(line.start)},{ass_time(line.end)},Karaoke,,0,0,0,,{body}"
        )
    return header + "\n" + "\n".join(events) + "\n"


def frame_cue(lyrics, t):
    line = lyrics.line_at(t)
    word = lyrics.word_at(t)
    return {
        "time": t,
        "line": None if line is None else line.i,
        "text": "" if line is None else line.text,
        "char_progress": Lyrics.line_char_progress(line, t),
        "word": None if word is None else word.w,
        "word_index": None if word is None else word.gi,
        "word_progress": Lyrics.word_progress(word, t),
    }
