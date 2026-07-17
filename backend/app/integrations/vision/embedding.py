import hashlib
import math
import re


MODEL_NAME = "local-hash-v1"
VECTOR_DIMENSIONS = 256


def embed_text(value: str) -> list[float]:
    """Create a deterministic normalized vector without loading a model runtime.

    This is the lightweight local baseline. The stable integration boundary lets a
    SigLIP or Qwen3-VL encoder replace it without changing media-library services.
    """
    vector = [0.0] * VECTOR_DIMENSIONS
    for token in _tokens(value):
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % VECTOR_DIMENSIONS
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign
    magnitude = math.sqrt(sum(component * component for component in vector))
    if magnitude:
        return [component / magnitude for component in vector]
    return vector


def _tokens(value: str) -> list[str]:
    normalized = value.lower().strip()
    words = re.findall(r"[a-z0-9]+", normalized)
    chinese_runs = re.findall(r"[\u4e00-\u9fff]+", normalized)
    tokens = list(words)
    for word in words:
        if len(word) >= 4:
            tokens.extend(word[index : index + 3] for index in range(len(word) - 2))
    for run in chinese_runs:
        tokens.extend(run)
        tokens.extend(run[index : index + 2] for index in range(max(0, len(run) - 1)))
    return tokens
