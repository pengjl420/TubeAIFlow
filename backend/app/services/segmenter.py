import re


def split_script(text: str, min_len: int = 60, max_len: int = 150) -> list[dict]:
    pieces = [item.strip() for item in re.split(r"(?<=[。！？!?])", text) if item.strip()]
    if not pieces:
        pieces = [text.strip()] if text.strip() else []

    segments: list[str] = []
    current = ""
    for piece in pieces:
        if not current:
            current = piece
            continue
        if len(current) < min_len or len(current) + len(piece) <= max_len:
            current += piece
        else:
            segments.extend(_split_long_text(current, max_len))
            current = piece
    if current:
        segments.extend(_split_long_text(current, max_len))

    return [
        {
            "segment_id": f"{index:04d}",
            "index": index,
            "text_zh": segment,
            "status": "pending",
        }
        for index, segment in enumerate(segments, start=1)
    ]


def _split_long_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    parts = [part.strip() for part in re.split(r"(?<=[，,；;])", text) if part.strip()]
    output: list[str] = []
    current = ""
    for part in parts:
        if not current or len(current) + len(part) <= max_len:
            current += part
        else:
            output.append(current)
            current = part
    if current:
        output.append(current)
    if len(output) == 1 and len(output[0]) > max_len:
        return [text[i : i + max_len] for i in range(0, len(text), max_len)]
    return output
