import json

from pydantic import BaseModel, Field, ValidationError

from app.providers.llm import JSONLLMProvider, build_storyboard_llm, invoke_json


AI_SEGMENTATION_PROMPT_VERSION = "narration-segmentation-v1"
MAX_TTS_SEGMENT_CHARACTERS = 180
MIN_PREFERRED_SPLIT_CHARACTERS = 45
_STRONG_BOUNDARIES = frozenset("。！？!?；;\n")
_SOFT_BOUNDARIES = frozenset("，,、：: ")


class _AISegment(BaseModel):
    text: str = Field(min_length=1)
    visual_description: str = ""


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
    payload = invoke_json(
        llm_client,
        _ai_segmentation_system_prompt(),
        json.dumps({"script": source}, ensure_ascii=False),
        schema=_AISegmentationResult.model_json_schema(),
        task="transcript-segmentation",
    )
    try:
        parsed = _AISegmentationResult.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"AI 自动切段结果格式无效：{exc}") from exc

    segment_texts: list[str] = []
    visual_descriptions: list[str] = []
    for item in parsed.segments:
        parts = _split_long_segment(item.text.strip())
        segment_texts.extend(parts)
        visual_descriptions.extend([item.visual_description.strip()] * len(parts))
    if _without_whitespace("".join(segment_texts)) != _without_whitespace(source):
        raise ValueError("AI 自动切段修改、遗漏或重排了逐字稿内容")
    return _serialize_segments(segment_texts, visual_descriptions)


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


def _serialize_segments(
    segments: list[str],
    visual_descriptions: list[str] | None = None,
) -> list[dict]:
    descriptions = visual_descriptions or [""] * len(segments)

    return [
        {
            "segment_id": f"{index:04d}",
            "index": index,
            "text": segment,
            "status": "pending",
            **({"visual_description": descriptions[index - 1]} if descriptions[index - 1] else {}),
        }
        for index, segment in enumerate(segments, start=1)
    ]


def _without_whitespace(value: str) -> str:
    return "".join(value.split())


def _ai_segmentation_system_prompt() -> str:
    return """
You are a Chinese documentary narration editor. Read the COMPLETE supplied transcript before
segmenting it into natural TTS narration units. Return JSON only in this exact root shape:
{"segments":[{"text":"...","visual_description":"..."}]}
Rules:
- Preserve every original non-whitespace character exactly and in the original order.
- Only choose boundaries; never translate, rewrite, summarize, add, or omit transcript text.
- Prefer complete semantic thoughts and natural speaking rhythm, normally 30-60 Chinese characters.
- Avoid fragments that are too short and split unusually long sentences at natural punctuation.
- visual_description is only a rough English visual hint informed by the complete transcript.
  It must not determine TTS boundaries and will not be treated as a final visual scene plan.
""".strip()
