from app.schemas.storyboard import StoryboardContent
from app.services.storyboard.prompt_compiler import compile_image_prompt, derive_visual_brief


def normalize_storyboard(value: StoryboardContent) -> StoryboardContent:
    """Normalize model query fields without inventing new visual facts."""
    data = value.model_dump()
    alternatives = []
    seen = {value.primary_query.casefold()}
    for query in value.alternative_queries:
        key = query.casefold()
        if key not in seen:
            seen.add(key)
            alternatives.append(query)
    data["alternative_queries"] = alternatives[:5]
    data["entities"] = _deduplicate(value.entities)
    data["locations"] = _deduplicate(value.locations)
    data["must_include"] = _deduplicate(value.must_include)
    data["avoid"] = _deduplicate(value.avoid)
    if value.visual_brief is None:
        data["visual_brief"] = derive_visual_brief(value).model_dump()
    image_prompt, negative_prompt = compile_image_prompt(
        StoryboardContent.model_validate(data)
    )
    data["image_prompt"] = image_prompt
    data["negative_prompt"] = negative_prompt
    return StoryboardContent.model_validate(data)


def _deduplicate(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result
