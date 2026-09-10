import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from typing import Iterable

from sqlmodel import Session

from app.config import get_settings
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_final_prproj_path,
    get_project_work_dir,
)
from app.models.project import Project
from app.services.projects import fcpxml_export_service, premiere_xml_export_service


PREMIERE_ENV = "TUBEAI_PREMIERE_PRO_PATH"
DEFAULT_TIMEOUT_SECONDS = 300


def find_premiere_executable() -> Path | None:
    settings_path = get_settings().premiere_pro_path
    if settings_path:
        path = Path(settings_path).expanduser().resolve()
        if path.is_file():
            return path
    configured = os.environ.get(PREMIERE_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        if path.is_file():
            return path
    for candidate in _registry_premiere_candidates():
        if candidate.is_file():
            return candidate.resolve()
    candidates: list[Path] = []
    for root_name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(root_name)
        if not root:
            continue
        adobe_root = Path(root) / "Adobe"
        if adobe_root.is_dir():
            candidates.extend(adobe_root.glob("Adobe Premiere Pro*/Adobe Premiere Pro.exe"))
    return sorted(candidates, reverse=True)[0].resolve() if candidates else None


def _registry_premiere_candidates() -> Iterable[Path]:
    if os.name != "nt":
        return []
    try:
        import winreg
    except ImportError:
        return []
    candidates: list[Path] = []
    subkey = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Adobe Premiere Pro.exe"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, subkey) as key:
                value, _ = winreg.QueryValueEx(key, None)
        except OSError:
            continue
        configured = str(value or "").strip().strip('"')
        if configured:
            candidates.append(Path(configured))
    return candidates


def get_premiere_status() -> dict:
    executable = find_premiere_executable()
    return {
        "installed": executable is not None,
        "path": str(executable) if executable else None,
        "configured_path": (
            str(get_settings().premiere_pro_path) if get_settings().premiere_pro_path else None
        ),
    }


def export_project_prproj(
    session: Session,
    project: Project,
    *,
    premiere_executable: Path | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Convert the project's FCPXML timeline into a real Premiere project.

    PRPROJ is an Adobe-owned project format. Premiere's documented openFCPXML
    API is used as the conversion boundary instead of writing a renamed or
    structurally incomplete XML file.
    """
    fcpxml_report = fcpxml_export_service.export_project_fcpxml(session, project)
    fcpxml_path = Path(fcpxml_report["path"]).resolve()
    premiere_xml_report = premiere_xml_export_service.convert_fcpxml_for_premiere(
        project, fcpxml_path
    )
    premiere_xml_path = Path(premiere_xml_report["path"]).resolve()
    output_path = get_final_prproj_path(project, get_settings().workspace_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.is_dir():
        try:
            output_path.rmdir()
        except OSError as exc:
            raise ValueError(
                f"PRPROJ output path is an existing non-empty directory: {output_path}"
            ) from exc
    executable = premiere_executable or find_premiere_executable()
    if not executable:
        raise ValueError(
            "未检测到 Adobe Premiere Pro，无法生成真实 PRPROJ。"
            f"请安装 Premiere Pro，或设置环境变量 {PREMIERE_ENV} 指向 Adobe Premiere Pro.exe。"
            "FCPXML 已正常生成，可继续单独使用。"
        )

    work_dir = get_project_work_dir(project, get_settings().workspace_dir)
    ensure_project_dirs(work_dir)
    marker_path = work_dir / "logs" / "prproj_export_result.json"
    script_path = work_dir / "logs" / "export_prproj.jsx"
    import_dir = work_dir / "logs" / f"premiere_import_{uuid.uuid4().hex[:8]}"
    marker_path.unlink(missing_ok=True)
    script_path.write_text(
        _conversion_script(premiere_xml_path, output_path, marker_path, import_dir),
        encoding="utf-8-sig",
    )
    _run_premiere_conversion(executable, script_path, marker_path, output_path, timeout_seconds)

    report = {
        **fcpxml_report,
        "path": str(output_path),
        "format": "prproj",
        "source_fcpxml_path": str(fcpxml_path),
        "source_premiere_xml_path": str(premiere_xml_path),
        "premiere_executable": str(executable),
        "compatibility_notes": [
            "PRPROJ was created by Adobe Premiere Pro from Final Cut Pro 7 XML.",
            "Media is linked by absolute path; relink after moving source files.",
            "FCPXML, Premiere XML, and SRT are retained as interchange fallbacks.",
        ],
    }
    report_path = work_dir / "reports" / "prproj_export_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _conversion_script(
    fcpxml_path: Path,
    output_path: Path,
    marker_path: Path,
    import_dir: Path,
) -> str:
    def js(value: Path | str) -> str:
        return json.dumps(str(value), ensure_ascii=False)

    import_path = f"{import_dir}{os.sep}"

    return f"""#target premierepro
(function () {{
    var marker = new File({js(marker_path)});
    var result = {{ success: false, error: "Premiere conversion did not complete" }};
    function jsonQuote(value) {{
        var text = String(value);
        text = text.split("\\\\").join("\\\\\\\\");
        text = text.split('"').join('\\\\"');
        text = text.split("\\r").join("\\\\r");
        text = text.split("\\n").join("\\\\n");
        return '"' + text + '"';
    }}
    try {{
        var importFolder = new Folder({js(import_dir)});
        if (!importFolder.exists && !importFolder.create()) {{
            throw new Error("Could not create Premiere import directory");
        }}
        var ok = app.openFCPXML({js(fcpxml_path)}, {js(import_path)});
        if (!ok) throw new Error("app.openFCPXML returned false");
        if (!app.project || !app.project.sequences || app.project.sequences.numSequences < 1) {{
            throw new Error("Premiere imported the project without a sequence");
        }}
        var sequence = app.project.sequences[0];
        if (!app.project.openSequence(sequence.sequenceID)) {{
            throw new Error("Premiere imported the sequence but could not open its timeline");
        }}
        var saveResult = app.project.saveAs({js(output_path)});
        if (saveResult !== 0 && saveResult !== true) {{
            throw new Error("app.project.saveAs failed: " + saveResult);
        }}
        app.project.save();
        result = {{
            success: true,
            path: {js(output_path)},
            sequence_name: sequence.name,
            sequence_count: app.project.sequences.numSequences,
            video_track_count: sequence.videoTracks.numTracks,
            audio_track_count: sequence.audioTracks.numTracks
        }};
    }} catch (error) {{
        result = {{ success: false, error: String(error) }};
    }}
    marker.encoding = "UTF-8";
    marker.open("w");
    var payload;
    if (result.success) {{
        payload = '{{"success":true'
            + ',"path":' + jsonQuote(result.path)
            + ',"sequence_name":' + jsonQuote(result.sequence_name)
            + ',"sequence_count":' + result.sequence_count
            + ',"video_track_count":' + result.video_track_count
            + ',"audio_track_count":' + result.audio_track_count
            + '}}';
    }} else {{
        payload = '{{"success":false,"error":' + jsonQuote(result.error) + '}}';
    }}
    marker.write(payload);
    marker.close();
}}());
"""


def _run_premiere_conversion(
    executable: Path,
    script_path: Path,
    marker_path: Path,
    output_path: Path,
    timeout_seconds: int,
) -> None:
    if not executable.is_file():
        raise ValueError(f"Premiere Pro executable does not exist: {executable}")
    if _premiere_is_running():
        raise RuntimeError(
            "Adobe Premiere Pro is already running. Close Premiere before exporting PRPROJ, "
            "then retry; command-line ExtendScript is only delivered reliably during launch."
        )
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    process = subprocess.Popen(
        [str(executable), "/C", "es.processFile", str(script_path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    deadline = time.monotonic() + max(1, timeout_seconds)
    while time.monotonic() < deadline:
        if marker_path.is_file():
            try:
                marker_text = marker_path.read_text(encoding="utf-8-sig")
                if not marker_text.strip():
                    time.sleep(0.25)
                    continue
                result = json.loads(marker_text)
            except (OSError, json.JSONDecodeError):
                time.sleep(0.25)
                continue
            if not result.get("success"):
                raise RuntimeError(
                    f"Premiere PRPROJ conversion failed: {result.get('error') or 'unknown error'}"
                )
            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise RuntimeError("Premiere reported success but the PRPROJ file was not created")
            return
        if process.poll() not in (None, 0):
            raise RuntimeError(
                f"Premiere exited before creating PRPROJ (exit code {process.returncode})"
            )
        time.sleep(0.25)
    raise RuntimeError(f"Premiere PRPROJ conversion timed out after {timeout_seconds} seconds")


def _premiere_is_running() -> bool:
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    invalid_handle = ctypes.c_void_p(-1).value
    if snapshot == invalid_handle:
        return False
    try:
        entry = ProcessEntry()
        entry.dwSize = ctypes.sizeof(entry)
        has_entry = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while has_entry:
            if entry.szExeFile.casefold() == "adobe premiere pro.exe":
                return True
            has_entry = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        return False
    finally:
        kernel32.CloseHandle(snapshot)
