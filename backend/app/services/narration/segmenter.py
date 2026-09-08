import json

from pydantic import BaseModel, Field, ValidationError

from app.providers.llm import JSONLLMProvider, build_storyboard_llm, invoke_json


AI_SEGMENTATION_PROMPT_VERSION = "narration-segmentation-v1"


class _AISegment(BaseModel):
    text: str = Field(min_length=1)
    visual_description: str = ""


class _AISegmentationResult(BaseModel):
    segments: list[_AISegment] = Field(min_length=1)


def split_script(text: str) -> list[dict]:
    """Split on non-empty lines. This remains the default, local-only mode."""
    segments = [line.strip() for line in text.splitlines() if line.strip()]

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

    segment_texts = [item.text.strip() for item in parsed.segments]
    if _without_whitespace("".join(segment_texts)) != _without_whitespace(source):
        raise ValueError("AI 自动切段修改、遗漏或重排了逐字稿内容")
    return _serialize_segments(
        segment_texts,
        [item.visual_description.strip() for item in parsed.segments],
    )


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
