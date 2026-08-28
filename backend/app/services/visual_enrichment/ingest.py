from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.services.visual_enrichment.models import CanonicalSegment, TranscriptSpan


TIMESTAMP_RE = re.compile(
    r"^(?P<sh>\d{1,2}):(?P<sm>\d{2}):(?P<ss>\d{2})[,.](?P<sms>\d{3})\s*-->\s*"
    r"(?P<eh>\d{1,2}):(?P<em>\d{2}):(?P<es>\d{2})[,.](?P<ems>\d{3})$"
)
MARKUP_RE = re.compile(r"<[^>]+>|\{\\[^}]+\}")
SPACE_PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)


@dataclass(frozen=True)
class ParsedCue:
    index: int
    start_ms: int
    end_ms: int
    text: str


def timestamp_to_ms(hours: str, minutes: str, seconds: str, millis: str) -> int:
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def parse_srt(content: str) -> list[ParsedCue]:
    normalized = content.replace("\ufeff", "").replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized.strip())
    cues: list[ParsedCue] = []
    previous_end = 0
    for block_number, block in enumerate(blocks, start=1):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            raise ValueError(f"Invalid SRT block {block_number}: missing timestamp or text")
        if "-->" in lines[0]:
            cue_index, timestamp_line, text_lines = block_number, lines[0], lines[1:]
        else:
            try:
                cue_index = int(lines[0])
            except ValueError as exc:
                raise ValueError(f"Invalid SRT cue index in block {block_number}") from exc
            timestamp_line, text_lines = lines[1], lines[2:]
        match = TIMESTAMP_RE.fullmatch(timestamp_line)
        if not match or not text_lines:
            raise ValueError(f"Invalid SRT block {block_number}")
        values = match.groupdict()
        start_ms = timestamp_to_ms(values["sh"], values["sm"], values["ss"], values["sms"])
        end_ms = timestamp_to_ms(values["eh"], values["em"], values["es"], values["ems"])
        if end_ms <= start_ms:
            raise ValueError(f"SRT cue {cue_index} has non-positive duration")
        if cues and start_ms < previous_end:
            raise ValueError(f"SRT cue {cue_index} overlaps or is out of order")
        text = MARKUP_RE.sub("", "\n".join(text_lines)).strip()
        if not text:
            raise ValueError(f"SRT cue {cue_index} has empty text")
        cues.append(ParsedCue(cue_index, start_ms, end_ms, text))
        previous_end = end_ms
    if not cues:
        raise ValueError("SRT contains no cues")
    return cues


def normalize_transcript(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    return SPACE_PUNCT_RE.sub("", value)


def _normalized_with_positions(text: str) -> tuple[str, list[int]]:
    normalized_chars: list[str] = []
    positions: list[int] = []
    for index, original_char in enumerate(text):
        for char in unicodedata.normalize("NFKC", original_char).casefold():
            if SPACE_PUNCT_RE.fullmatch(char):
                continue
            normalized_chars.append(char)
            positions.append(index)
    return "".join(normalized_chars), positions


class TranscriptAligner:
    """Alignment abstraction with a deterministic stdlib implementation."""

    def align(self, transcript: str, cues: list[ParsedCue]) -> list[CanonicalSegment]:
        normalized_transcript, positions = _normalized_with_positions(transcript)
        if not normalized_transcript:
            raise ValueError("Transcript is empty after normalization")
        cursor = 0
        output: list[CanonicalSegment] = []
        for sequence, cue in enumerate(cues, start=1):
            normalized_cue = normalize_transcript(cue.text)
            if not normalized_cue:
                raise ValueError(f"SRT cue {cue.index} is empty after normalization")
            found = normalized_transcript.find(normalized_cue, cursor)
            if found < 0:
                found = self._fuzzy_start(normalized_transcript, normalized_cue, cursor)
            end = min(len(normalized_transcript), found + len(normalized_cue))
            start_char = positions[min(found, len(positions) - 1)]
            end_char = positions[min(max(end - 1, found), len(positions) - 1)] + 1
            output.append(
                CanonicalSegment(
                    segment_id=f"sub_{sequence:06d}",
                    start_ms=cue.start_ms,
                    end_ms=cue.end_ms,
                    subtitle_text=cue.text,
                    normalized_text=normalized_cue,
                    transcript_span=TranscriptSpan(char_start=start_char, char_end=end_char),
                )
            )
            cursor = max(cursor, end)
        return output

    @staticmethod
    def _fuzzy_start(transcript: str, cue: str, cursor: int) -> int:
        search_end = min(len(transcript), cursor + max(len(cue) * 4, 200))
        window = transcript[cursor:search_end]
        match = SequenceMatcher(None, window, cue, autojunk=False).find_longest_match()
        if match.size < max(1, len(cue) // 3):
            raise ValueError("Transcript and SRT could not be aligned")
        return cursor + max(0, match.a - match.b)


def build_canonical_timeline(transcript: str, srt_content: str) -> list[CanonicalSegment]:
    return TranscriptAligner().align(transcript, parse_srt(srt_content))
