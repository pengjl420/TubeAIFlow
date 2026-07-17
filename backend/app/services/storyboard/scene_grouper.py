import json

from pydantic import ValidationError

from app.integrations.llm.deepseek import DeepSeekClient
from app.schemas.storyboard import SceneGroupingResult


GROUPING_PROMPT_VERSION = "visual-scene-grouping-v1"
MAX_CUES_PER_REQUEST = 80
MAX_CHARACTERS_PER_REQUEST = 12_000


def group_cues(cues: list[dict], client: DeepSeekClient) -> tuple[list[list[dict]], list[str]]:
    groups: list[list[dict]] = []
    warnings: list[str] = []
    for chunk in _chunk_cues(cues):
        try:
            suggested_ids = _request_groups(chunk, client)
            groups.extend(_materialize_groups(chunk, suggested_ids))
        except (RuntimeError, ValueError, ValidationError) as exc:
            warnings.append(f"语义分组已回退到时长规则：{exc}")
            groups.extend(_deterministic_groups(chunk))
    return groups, warnings


def _request_groups(cues: list[dict], client: DeepSeekClient) -> list[list[str]]:
    system_prompt = """
You are a documentary visual scene editor. Group consecutive subtitle cues into visual semantic scenes.
Return JSON only. The JSON format must be:
{"groups":[{"subtitle_ids":["id1","id2"]}]}
Rules:
- Every supplied subtitle id must appear exactly once and in the original order.
- A group must contain only consecutive subtitle ids.
- Change scene on subject, person, location, time period, event, or narration phase changes.
- Opening scenes should usually be 3-5 seconds; normal scenes 5-10 seconds.
- Do not translate, rewrite, or omit narration.
""".strip()
    payload = [
        {
            "id": cue["id"],
            "start_ms": cue["start_ms"],
            "end_ms": cue["end_ms"],
            "text": cue["text"],
        }
        for cue in cues
    ]
    result = SceneGroupingResult.model_validate(
        client.chat_json(system_prompt, json.dumps({"subtitle_cues": payload}, ensure_ascii=False))
    )
    return [group.subtitle_ids for group in result.groups]


def _materialize_groups(cues: list[dict], suggested_ids: list[list[str]]) -> list[list[dict]]:
    expected_ids = [cue["id"] for cue in cues]
    flattened_ids = [cue_id for group in suggested_ids for cue_id in group]
    if flattened_ids != expected_ids:
        raise ValueError("DeepSeek 返回的字幕分组不是连续且完整的覆盖")
    by_id = {cue["id"]: cue for cue in cues}
    return [[by_id[cue_id] for cue_id in group] for group in suggested_ids]


def _deterministic_groups(cues: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    current: list[dict] = []
    for cue in cues:
        current.append(cue)
        start_ms = current[0]["start_ms"]
        duration_ms = cue["end_ms"] - start_ms
        target_ms = 5_000 if start_ms < 30_000 else 8_000
        if duration_ms >= target_ms or duration_ms >= 12_000:
            groups.append(current)
            current = []
    if current:
        if groups and current[-1]["end_ms"] - current[0]["start_ms"] < 2_000:
            groups[-1].extend(current)
        else:
            groups.append(current)
    return groups


def _chunk_cues(cues: list[dict]) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    characters = 0
    for cue in cues:
        text_length = len(cue["text"])
        if current and (
            len(current) >= MAX_CUES_PER_REQUEST
            or characters + text_length > MAX_CHARACTERS_PER_REQUEST
        ):
            chunks.append(current)
            current = []
            characters = 0
        current.append(cue)
        characters += text_length
    if current:
        chunks.append(current)
    return chunks
