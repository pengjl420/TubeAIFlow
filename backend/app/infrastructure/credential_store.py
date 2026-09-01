import ctypes
import os
from ctypes import wintypes
from pathlib import Path


_CREDENTIAL_DIR = Path(__file__).resolve().parents[2] / "workspace" / "credentials"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    return (
        _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))),
        buffer,
    )


def store_secret(credential_id: str, value: str) -> str:
    if os.name != "nt":
        raise RuntimeError("Secure credential storage currently requires Windows DPAPI")
    normalized_id = _normalize_id(credential_id)
    encrypted = _protect(value.encode("utf-8"))
    _CREDENTIAL_DIR.mkdir(parents=True, exist_ok=True)
    target = _CREDENTIAL_DIR / f"{normalized_id}.dpapi"
    temporary = target.with_suffix(".tmp")
    with temporary.open("wb") as file:
        file.write(encrypted)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, target)
    return normalized_id


def load_secret(credential_id: str) -> str:
    path = _CREDENTIAL_DIR / f"{_normalize_id(credential_id)}.dpapi"
    if not path.is_file():
        return ""
    if os.name != "nt":
        return ""
    try:
        return _unprotect(path.read_bytes()).decode("utf-8")
    except (OSError, UnicodeDecodeError, RuntimeError):
        return ""


def delete_secret(credential_id: str) -> None:
    path = _CREDENTIAL_DIR / f"{_normalize_id(credential_id)}.dpapi"
    path.unlink(missing_ok=True)


def _normalize_id(value: str) -> str:
    normalized = "".join(character for character in value if character.isalnum() or character in "-_")
    if not normalized or len(normalized) > 100:
        raise ValueError("Invalid credential id")
    return normalized


def _protect(value: bytes) -> bytes:
    source, source_buffer = _blob(value)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptProtectData(
        ctypes.byref(source),
        "TubeAiFolw credential",
        None,
        None,
        None,
        0,
        ctypes.byref(output),
    ):
        raise RuntimeError("Windows DPAPI encryption failed")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer


def _unprotect(value: bytes) -> bytes:
    source, source_buffer = _blob(value)
    output = _DataBlob()
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source), None, None, None, None, 0, ctypes.byref(output)
    ):
        raise RuntimeError("Windows DPAPI decryption failed")
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        kernel32.LocalFree(output.pbData)
        del source_buffer
