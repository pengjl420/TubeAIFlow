from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol

from app.schemas.subtitle_alignment import (
    AlignedCue,
    AsrWord,
    Language,
    SegmentAlignment,
    TimedUnit,
)


_SOURCE_TOKEN = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*|\d+(?:[,.]\d+)*|[\u3400-\u9fff]")
_ZH_ASR_TOKEN = re.compile(
    r"[零〇一二两三四五六七八九十百千万亿点]+|[A-Za-z]+(?:['’][A-Za-z]+)*|"
    r"\d+(?:[,.]\d+)*|[\u3400-\u9fff]"
)
_STRONG_END = "。！？.!?"
_MEDIUM_END = "；;：:"
_WEAK_END = "，,、"
_EN_ORPHANS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "of", "on",
    "or", "the", "to", "with",
}
_ZH_ORPHANS = set("的了和与及或在把被从向于而但因为所以")


class AsrBackend(Protocol):
    name: str

    def transcribe(self, audio_path: Path, language: Language, *, vad_filter: bool = False) -> list[AsrWord]: ...


@dataclass(frozen=True)
class SourceUnit:
    text: str
    normalized: str
    display_start: int
    display_end: int


@dataclass(frozen=True)
class AnchorUnit:
    normalized: str
    start_ms: int
    end_ms: int
    confidence: float


def infer_language(text: str, configured: str | None = None) -> Language:
    value = str(configured or "").lower()
    if value.startswith("zh") or value in {"chinese", "mandarin"}:
        return "zh"
    if value.startswith("en") or value == "english":
        return "en"
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    return "zh" if cjk >= latin else "en"


def source_units(display_text: str, language: Language) -> list[SourceUnit]:
    result: list[SourceUnit] = []
    pattern = _ZH_ASR_TOKEN if language == "zh" else _SOURCE_TOKEN
    for match in pattern.finditer(display_text):
        token = match.group(0)
        if language == "zh" and re.fullmatch(r"\d+(?:[,.]\d+)*", token):
            parts = [(token, match.start(), match.end(), token.replace(",", "").replace(".", "点"))]
        elif language == "zh" and re.fullmatch(r"[零〇一二两三四五六七八九十百千万亿]+", token):
            parts = [(token, match.start(), match.end(), _chinese_number_to_digits(token))]
        else:
            parts = [(token, match.start(), match.end(), _normalize_token(token))]
        for text, start, end, normalized in parts:
            if normalized:
                result.append(SourceUnit(text, normalized, start, end))
    return result


def expand_asr_words(words: list[AsrWord], language: Language) -> list[AnchorUnit]:
    anchors: list[AnchorUnit] = []
    for word in words:
        pattern = _ZH_ASR_TOKEN if language == "zh" else _SOURCE_TOKEN
        tokens = [match.group(0) for match in pattern.finditer(word.text)]
        if language == "zh":
            expanded: list[str] = []
            for token in tokens:
                if re.fullmatch(r"[零〇一二两三四五六七八九十百千万亿点]+", token):
                    expanded.append(_chinese_number_to_digits(token))
                elif re.fullmatch(r"\d+(?:[,.]\d+)*", token):
                    expanded.append(token.replace(",", "").replace(".", "点"))
                elif re.fullmatch(r"[\u3400-\u9fff]+", token):
                    expanded.extend(token)
                else:
                    expanded.append(token)
            tokens = expanded
        tokens = [value for token in tokens if (value := _normalize_token(token))]
        if not tokens:
            continue
        span = max(1, word.end_ms - word.start_ms)
        for index, token in enumerate(tokens):
            start = word.start_ms + round(span * index / len(tokens))
            end = word.start_ms + round(span * (index + 1) / len(tokens))
            anchors.append(AnchorUnit(token, start, max(start + 1, end), word.confidence))
    return anchors


def align_segment(
    *,
    segment_id: str,
    display_text: str,
    language: Language,
    duration_ms: int,
    audio_path: Path | None,
    backend: AsrBackend | None,
    min_duration_ms: int = 1000,
    max_duration_ms: int = 5600,
    max_display_units: int = 22,
) -> SegmentAlignment:
    if not display_text.strip():
        raise ValueError(f"Segment {segment_id} 原稿不能为空")
    if duration_ms <= 0:
        raise ValueError(f"Segment {segment_id} 音频时长无效")
    source = source_units(display_text, language)
    if not source:
        raise ValueError(f"Segment {segment_id} 原稿没有可对齐文字")

    error = None
    backend_name = "heuristic"
    words: list[AsrWord] = []
    if backend is not None and audio_path is not None:
        backend_name = backend.name
        try:
            words = backend.transcribe(audio_path, language, vad_filter=False)
            first = _build_mapping(source, expand_asr_words(words, language), duration_ms)
            if first[1] < 0.78:
                retry_words = backend.transcribe(audio_path, language, vad_filter=True)
                retry = _build_mapping(source, expand_asr_words(retry_words, language), duration_ms)
                if retry[1] > first[1]:
                    words = retry_words
        except Exception as exc:  # one bad segment must not discard completed work
            error = str(exc)
            words = []

    anchors = expand_asr_words(words, language)
    if anchors:
        units, similarity, coverage = _build_mapping(source, anchors, duration_ms)
    else:
        units = _heuristic_mapping(source, duration_ms)
        similarity = 0.0
        coverage = 0.0

    confidence = round(0.55 * similarity + 0.45 * coverage, 4)
    cues = optimize_cues(
        display_text,
        units,
        language,
        duration_ms,
        min_duration_ms=min_duration_ms,
        max_duration_ms=max_duration_ms,
        max_display_units=max_display_units,
    )
    status = "passed" if confidence >= 0.78 else "needs_review"
    return SegmentAlignment(
        segment_id=segment_id,
        language=language,
        duration_ms=duration_ms,
        backend=backend_name if anchors else "heuristic",
        status=status,
        confidence=confidence,
        text_similarity=round(similarity, 4),
        anchor_coverage=round(coverage, 4),
        units=units,
        cues=cues,
        error=error,
    )


def _build_mapping(
    source: list[SourceUnit], anchors: list[AnchorUnit], duration_ms: int
) -> tuple[list[TimedUnit], float, float]:
    pairs = _sequence_align([item.normalized for item in source], [item.normalized for item in anchors])
    anchor_by_source = {left: right for left, right in pairs if left is not None and right is not None}
    direct = len(anchor_by_source)
    exact = sum(
        1 for left, right in anchor_by_source.items()
        if _equivalent(source[left].normalized, anchors[right].normalized)
    )
    similarity = exact / max(len(source), len(anchors), 1)
    coverage = direct / len(source)

    starts: list[int | None] = [None] * len(source)
    ends: list[int | None] = [None] * len(source)
    confidences = [0.0] * len(source)
    for source_index, anchor_index in anchor_by_source.items():
        anchor = anchors[anchor_index]
        starts[source_index] = min(duration_ms - 1, max(0, anchor.start_ms))
        ends[source_index] = min(duration_ms, max((starts[source_index] or 0) + 1, anchor.end_ms))
        confidences[source_index] = anchor.confidence
    _interpolate_times(starts, ends, duration_ms)

    result = []
    previous_end = 0
    for index, item in enumerate(source):
        start = max(previous_end, int(starts[index] or 0))
        end = max(start + 1, int(ends[index] or start + 1))
        end = min(duration_ms, end)
        if start >= duration_ms:
            start, end = max(0, duration_ms - 1), duration_ms
        direct_anchor = index in anchor_by_source
        result.append(
            TimedUnit(
                text=item.text,
                display_start=item.display_start,
                display_end=item.display_end,
                start_ms=start,
                end_ms=end,
                confidence=confidences[index] if direct_anchor else 0.45,
                source="asr_anchor" if direct_anchor else "interpolated",
            )
        )
        previous_end = end
    return result, similarity, coverage


def _sequence_align(source: list[str], observed: list[str]) -> list[tuple[int | None, int | None]]:
    rows, columns = len(source), len(observed)
    scores = [[0.0] * (columns + 1) for _ in range(rows + 1)]
    moves = [[""] * (columns + 1) for _ in range(rows + 1)]
    for i in range(1, rows + 1):
        scores[i][0], moves[i][0] = scores[i - 1][0] - 2.5, "delete"
    for j in range(1, columns + 1):
        scores[0][j], moves[0][j] = scores[0][j - 1] - 2.0, "insert"
    for i in range(1, rows + 1):
        for j in range(1, columns + 1):
            ratio = SequenceMatcher(None, source[i - 1], observed[j - 1]).ratio()
            match_score = 5.0 if _equivalent(source[i - 1], observed[j - 1]) else -1.5 + 4 * ratio
            options = (
                (scores[i - 1][j - 1] + match_score, "match"),
                (scores[i - 1][j] - 2.5, "delete"),
                (scores[i][j - 1] - 2.0, "insert"),
            )
            scores[i][j], moves[i][j] = max(options, key=lambda item: item[0])
    result: list[tuple[int | None, int | None]] = []
    i, j = rows, columns
    while i or j:
        move = moves[i][j]
        if move == "match":
            result.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif move == "delete":
            result.append((i - 1, None))
            i -= 1
        else:
            result.append((None, j - 1))
            j -= 1
    result.reverse()
    return result


def _interpolate_times(starts: list[int | None], ends: list[int | None], duration_ms: int) -> None:
    index = 0
    while index < len(starts):
        if starts[index] is not None:
            index += 1
            continue
        gap_start = index
        while index < len(starts) and starts[index] is None:
            index += 1
        gap_end = index
        left = int(ends[gap_start - 1]) if gap_start else 0
        right = int(starts[gap_end]) if gap_end < len(starts) else duration_ms
        right = max(left + (gap_end - gap_start), right)
        span = right - left
        count = gap_end - gap_start
        for offset, target in enumerate(range(gap_start, gap_end)):
            starts[target] = left + round(span * offset / count)
            ends[target] = left + round(span * (offset + 1) / count)


def _heuristic_mapping(source: list[SourceUnit], duration_ms: int) -> list[TimedUnit]:
    weights = [max(1, len(item.normalized)) for item in source]
    total = sum(weights)
    elapsed = 0
    result: list[TimedUnit] = []
    for index, (item, weight) in enumerate(zip(source, weights, strict=True)):
        start = round(duration_ms * elapsed / total)
        elapsed += weight
        end = duration_ms if index == len(source) - 1 else round(duration_ms * elapsed / total)
        result.append(
            TimedUnit(
                text=item.text,
                display_start=item.display_start,
                display_end=item.display_end,
                start_ms=start,
                end_ms=max(start + 1, end),
                confidence=0,
                source="heuristic",
            )
        )
    return result


def optimize_cues(
    display_text: str,
    units: list[TimedUnit],
    language: Language,
    duration_ms: int,
    *,
    min_duration_ms: int,
    max_duration_ms: int,
    max_display_units: int,
) -> list[AlignedCue]:
    count = len(units)
    costs = [math.inf] * (count + 1)
    previous = [-1] * (count + 1)
    costs[0] = 0.0
    for end in range(1, count + 1):
        for start in range(end - 1, -1, -1):
            char_start = 0 if start == 0 else units[start].display_start
            char_end = len(display_text) if end == count else units[end].display_start
            text = display_text[char_start:char_end].strip()
            length = _cue_length(text, language)
            hard_limit = max_display_units if language == "zh" else max(52, max_display_units * 2)
            if length > hard_limit and start < end - 1:
                break
            cue_duration = units[end - 1].end_ms - units[start].start_ms
            penalty = _cue_cost(text, language, length, cue_duration, min_duration_ms, max_duration_ms)
            candidate = costs[start] + penalty
            if candidate < costs[end]:
                costs[end], previous[end] = candidate, start
    if previous[count] < 0:
        previous[count] = 0
    ranges: list[tuple[int, int]] = []
    end = count
    while end > 0:
        start = previous[end]
        if start < 0:
            start = end - 1
        ranges.append((start, end))
        end = start
    ranges.reverse()

    cues: list[AlignedCue] = []
    for index, (start, end) in enumerate(ranges):
        char_start = 0 if start == 0 else units[start].display_start
        char_end = len(display_text) if end == count else units[end].display_start
        raw_text = display_text[char_start:char_end]
        stripped = raw_text.strip()
        leading = len(raw_text) - len(raw_text.lstrip())
        trailing = len(raw_text) - len(raw_text.rstrip())
        source_start = char_start + leading
        source_end = max(source_start + 1, char_end - trailing)
        cue_start = max(0, units[start].start_ms - 40)
        cue_end = min(duration_ms, units[end - 1].end_ms + 80)
        if cues and cue_start < cues[-1].local_end_ms:
            boundary = (cue_start + cues[-1].local_end_ms) // 2
            cues[-1].local_end_ms = max(cues[-1].local_start_ms + 1, boundary)
            cue_start = max(cues[-1].local_end_ms, boundary)
        confidence = sum(unit.confidence for unit in units[start:end]) / (end - start)
        timing_sources = {unit.source for unit in units[start:end]}
        cues.append(
            AlignedCue(
                text=stripped,
                local_start_ms=cue_start,
                local_end_ms=max(cue_start + 1, cue_end),
                confidence=round(confidence, 4),
                source_char_start=source_start,
                source_char_end=source_end,
                timing_source="+".join(sorted(timing_sources)),
            )
        )
    return cues


def _cue_cost(text: str, language: Language, length: int, duration: int, minimum: int, maximum: int) -> float:
    target_length = 14 if language == "zh" else 8
    target_duration = 2800 if language == "zh" else 3000
    cost = ((length - target_length) / max(1, target_length)) ** 2
    cost += 0.5 * ((duration - target_duration) / target_duration) ** 2
    if duration < minimum:
        cost += 8 * (minimum - duration) / minimum
    if duration > maximum:
        cost += 8 * (duration - maximum) / maximum
    ending = text[-1:] if text else ""
    if ending in _STRONG_END:
        cost -= 1.5
    elif ending in _MEDIUM_END:
        cost -= 0.8
    elif ending in _WEAK_END:
        cost -= 0.3
    if _is_orphan(text, language):
        cost += 10
    return cost


def _is_orphan(text: str, language: Language) -> bool:
    tokens = [item.normalized for item in source_units(text, language)]
    if not tokens:
        return True
    if language == "zh":
        return len(tokens) <= 2 and all(token in _ZH_ORPHANS for token in tokens)
    return len(tokens) <= 2 and tokens[-1] in _EN_ORPHANS


def _cue_length(text: str, language: Language) -> int:
    return len(source_units(text, language)) if language == "en" else sum(
        1 for char in text if not char.isspace() and char not in _STRONG_END + _MEDIUM_END + _WEAK_END
    )


def _normalize_token(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).lower().replace("’", "'")
    return re.sub(r"[^\w\u3400-\u9fff']", "", value, flags=re.UNICODE)


def _chinese_number_to_digits(value: str) -> str:
    if "点" in value:
        integer, decimal = value.split("点", 1)
        decimal_digits = "".join(str(_zh_digit(character)) for character in decimal)
        return f"{_parse_zh_integer(integer)}点{decimal_digits}"
    return str(_parse_zh_integer(value))


def _parse_zh_integer(value: str) -> int:
    if not any(character in "十百千万亿" for character in value):
        digits = "".join(str(_zh_digit(character)) for character in value)
        return int(digits or "0")
    total = section = number = 0
    small_units = {"十": 10, "百": 100, "千": 1000}
    for character in value:
        if character in small_units:
            section += (number or 1) * small_units[character]
            number = 0
        elif character == "万":
            total += (section + number) * 10_000
            section = number = 0
        elif character == "亿":
            total = (total + section + number) * 100_000_000
            section = number = 0
        else:
            number = _zh_digit(character)
    return total + section + number


def _zh_digit(character: str) -> int:
    return "零一二三四五六七八九".index(character.translate(str.maketrans("〇两", "零二")))


def _equivalent(left: str, right: str) -> bool:
    return left == right or left.replace("'", "") == right.replace("'", "")


def cache_key(audio_path: Path | None, display_text: str, language: Language, config: dict) -> str:
    digest = hashlib.sha256()
    if audio_path and audio_path.is_file():
        with audio_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    digest.update(display_text.encode("utf-8"))
    digest.update(language.encode("ascii"))
    digest.update(json.dumps(config, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return digest.hexdigest()
