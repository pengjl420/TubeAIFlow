import re
import textwrap


Cue = tuple[float, float, str]


def split_timed_subtitle_cues(text: str, start: float, end: float, language: str = "zh") -> list[Cue]:
    clean_text = _normalize_text(text)
    if not clean_text:
        return []

    max_chars = 42 if language == "en" else 18
    pieces = split_subtitle_text(clean_text, max_chars=max_chars)
    if not pieces:
        return []

    duration = max(0.0, end - start)
    if duration <= 0:
        return [(start, end, pieces[0])]

    weights = [max(_count_timing_chars(piece), 1) for piece in pieces]
    total_weight = sum(weights)

    cues: list[Cue] = []
    current = start
    for index, piece in enumerate(pieces):
        if index == len(pieces) - 1:
            cue_end = end
        else:
            cue_duration = duration * weights[index] / total_weight
            cue_end = current + cue_duration
        cues.append((round(current, 3), round(cue_end, 3), piece))
        current = cue_end
    return cues


def split_subtitle_text(text: str, max_chars: int = 24) -> list[str]:
    parts = _split_by_punctuation(text, max_chars)
    output: list[str] = []
    current = ""

    for part in parts:
        if len(part) > max_chars:
            if current:
                output.append(current)
                current = ""
            output.extend(_split_long_part(part, max_chars))
            continue

        if not current:
            current = part
        elif len(current) + len(part) <= max_chars:
            current += part
        else:
            output.append(current)
            current = part

    if current:
        output.append(current)

    return [item for item in output if item.strip()]


def wrap_subtitle_text(text: str, language: str) -> str:
    if language == "en":
        return "\n".join(textwrap.wrap(text, width=42, break_long_words=False)[:2])
    if len(text) <= 14:
        return text
    return "\n".join(textwrap.wrap(text, width=14)[:2])


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def _split_by_punctuation(text: str, max_chars: int) -> list[str]:
    pieces = _split_keep_delimiter(text, r"[。！？!?]")
    output: list[str] = []
    for piece in pieces:
        if len(piece) <= max_chars:
            output.append(piece)
        else:
            output.extend(_split_keep_delimiter(piece, r"[，、；：,;:]"))
    return [item.strip() for item in output if item.strip()]


def _split_keep_delimiter(text: str, delimiter_pattern: str) -> list[str]:
    tokens = re.split(f"({delimiter_pattern})", text)
    pieces: list[str] = []
    current = ""
    for token in tokens:
        if not token:
            continue
        current += token
        if re.fullmatch(delimiter_pattern, token):
            pieces.append(current)
            current = ""
    if current:
        pieces.append(current)
    return pieces


def _split_long_part(text: str, max_chars: int) -> list[str]:
    pieces = _split_keep_delimiter(text, r"[，、；：,;:]")
    if len(pieces) == 1 and len(pieces[0]) > max_chars:
        return [text[index : index + max_chars] for index in range(0, len(text), max_chars)]

    output: list[str] = []
    current = ""
    for piece in pieces:
        if len(piece) > max_chars:
            if current:
                output.append(current)
                current = ""
            output.extend(piece[index : index + max_chars] for index in range(0, len(piece), max_chars))
        elif not current or len(current) + len(piece) <= max_chars:
            current += piece
        else:
            output.append(current)
            current = piece
    if current:
        output.append(current)
    return output


def _count_timing_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text))
