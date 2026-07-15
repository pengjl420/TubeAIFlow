def split_script(text: str) -> list[dict]:
    segments = [line.strip() for line in text.splitlines() if line.strip()]

    return [
        {
            "segment_id": f"{index:04d}",
            "index": index,
            "text_zh": segment,
            "status": "pending",
        }
        for index, segment in enumerate(segments, start=1)
    ]
