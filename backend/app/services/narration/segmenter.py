import json
import logging
import re

from pydantic import BaseModel, Field, ValidationError

from app.providers.llm import JSONLLMProvider, build_storyboard_llm, invoke_json
from app.integrations.llm.deepseek import ProviderOutputTruncatedError


AI_SEGMENTATION_PROMPT_VERSION = "narration-segmentation-v2"
MAX_TTS_SEGMENT_CHARACTERS = 180
MIN_PREFERRED_SPLIT_CHARACTERS = 45
MAX_AI_WINDOW_CHARACTERS = 4_000
_STRONG_BOUNDARIES = frozenset("。！？!?；;\n")
_SOFT_BOUNDARIES = frozenset("，,、：: ")
logger = logging.getLogger(__name__)


class _AISegment(BaseModel):
    text: str = Field(min_length=1)


class _AISegmentationResult(BaseModel):
    segments: list[_AISegment] = Field(min_length=1)


def split_script(text: str) -> list[dict]:
    """Split locally while enforcing a safe upper bound for long-form TTS."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    segments = [part for line in lines for part in _split_long_segment(line)]

    return _serialize_segments(segments)


def split_script_with_ai(
    text: str,
    client: JSONLLMProvider | None = None,
) -> list[dict]:
    """Use the configured local-first LLM to choose TTS boundaries without rewriting."""
    source = text.strip()
    if not source:
        return []
    llm_client = client or build_storyboard_llm()
    segment_texts: list[str] = []
    for window_index, window in enumerate(_split_ai_windows(source), start=1):
        try:
            payload = invoke_json(
                llm_client,
                _ai_segmentation_system_prompt(window),
                json.dumps({"script": window}, ensure_ascii=False),
                schema=_AISegmentationResult.model_json_schema(),
                task="transcript-segmentation",
            )
            try:
                parsed = _AISegmentationResult.model_validate(payload)
            except ValidationError as exc:
                raise ValueError(f"AI 自动切段结果格式无效：{exc}") from exc
            window_segments = [item.text.strip() for item in parsed.segments]
            if _without_whitespace("".join(window_segments)) != _without_whitespace(window):
                raise ValueError("AI 自动切段修改、遗漏或重排了逐字稿内容")
        except ProviderOutputTruncatedError:
            logger.warning(
                "AI segmentation window %s exceeded the provider output budget; "
                "using deterministic boundaries for this window",
                window_index,
            )
            window_segments = [item["text"] for item in split_script(window)]
        for segment in window_segments:
            segment_texts.extend(_split_long_segment(segment))
    if _without_whitespace("".join(segment_texts)) != _without_whitespace(source):
        raise ValueError("AI 自动切段修改、遗漏或重排了逐字稿内容")
    return _serialize_segments(segment_texts)


def _split_ai_windows(
    text: str,
    max_characters: int = MAX_AI_WINDOW_CHARACTERS,
) -> list[str]:
    """Bound LLM output size while keeping paragraph and sentence boundaries stable."""
    paragraphs = [item.strip() for item in text.splitlines() if item.strip()]
    units = [
        part
        for paragraph in paragraphs
        for part in _split_long_segment(paragraph, max_characters=max_characters)
    ]
    windows: list[str] = []
    current: list[str] = []
    current_length = 0
    for unit in units:
        added_length = len(unit) + (1 if current else 0)
        if current and current_length + added_length > max_characters:
            windows.append("\n".join(current))
            current = []
            current_length = 0
        current.append(unit)
        current_length += len(unit) + (1 if len(current) > 1 else 0)
    if current:
        windows.append("\n".join(current))
    return windows


def _split_long_segment(
    text: str,
    max_characters: int = MAX_TTS_SEGMENT_CHARACTERS,
) -> list[str]:
    """Choose deterministic punctuation-aware boundaries without rewriting text."""
    remaining = text.strip()
    if not remaining:
        return []
    if max_characters < 2:
        raise ValueError("TTS segment character limit must be at least 2")
    parts: list[str] = []
    while len(remaining) > max_characters:
        window = remaining[:max_characters]
        minimum = min(MIN_PREFERRED_SPLIT_CHARACTERS, max_characters // 2)
        split_at = _last_boundary(window, _STRONG_BOUNDARIES, minimum)
        if split_at is None:
            split_at = _last_boundary(window, _SOFT_BOUNDARIES, minimum)
        if split_at is None:
            split_at = max_characters
        part = remaining[:split_at].strip()
        if not part:
            split_at = max_characters
            part = remaining[:split_at]
        parts.append(part)
        remaining = remaining[split_at:].strip()
    if remaining:
        parts.append(remaining)
    return parts


def _last_boundary(window: str, boundaries: frozenset[str], minimum: int) -> int | None:
    for index in range(len(window) - 1, minimum - 1, -1):
        if window[index] in boundaries:
            return index + 1
    return None


def _serialize_segments(segments: list[str]) -> list[dict]:
    return [
        {
            "segment_id": f"{index:04d}",
            "index": index,
            "text": segment,
            "status": "pending",
        }
        for index, segment in enumerate(segments, start=1)
    ]


def _without_whitespace(value: str) -> str:
    return "".join(value.split())


def _ai_segmentation_system_prompt(text: str) -> str:
    language_guidance = (
        "The transcript is primarily Chinese. Prefer complete thoughts of roughly 30-60 Chinese characters."
        if _is_primarily_cjk(text)
        else "The transcript is not primarily Chinese. Prefer complete thoughts of roughly 15-35 words."
    )
    return f"""
You are a documentary narration editor. Segment the supplied transcript window into natural
TTS narration units. Return JSON only in this exact root shape:
{{"segments":[{{"text":"..."}}]}}
Rules:
- Preserve every original non-whitespace character exactly and in the original order.
- Only choose boundaries; never translate, rewrite, summarize, add, or omit transcript text.
- {language_guidance}
- Avoid fragments that are too short and split unusually long sentences at natural punctuation.
""".strip()


def _is_primarily_cjk(text: str) -> bool:
    visible = re.sub(r"\s+", "", text)
    if not visible:
        return False
    cjk = sum("\u3400" <= character <= "\u9fff" for character in visible)
    return cjk / len(visible) >= 0.25
