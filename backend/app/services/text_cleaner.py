import re


def clean_script(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        stripped = re.sub(r"^[#>*\-\s]+", "", stripped)
        stripped = re.sub(r"`+", "", stripped)
        if stripped:
            lines.append(stripped)
    cleaned = "\n".join(lines)
    cleaned = cleaned.replace("...", "。").replace("……", "。")
    cleaned = re.sub(r"[ \t]+", " ", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()
