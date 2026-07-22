import json
import os
import subprocess
import time
from pathlib import Path

from sqlmodel import Session

from app.config import get_settings
from app.infrastructure.project_layout import (
    ensure_project_dirs,
    get_final_prproj_path,
    get_project_work_dir,
)
from app.models.project import Project
from app.services.projects import fcpxml_export_service


PREMIERE_ENV = "TUBEAI_PREMIERE_PRO_PATH"
DEFAULT_TIMEOUT_SECONDS = 300


def find_premiere_executable() -> Path | None:
    settings_path = get_settings().premiere_pro_path
    if settings_path:
        path = Path(settings_path).expanduser().resolve()
        return path if path.is_file() else None
    configured = os.environ.get(PREMIERE_ENV, "").strip()
    if configured:
        path = Path(configured).expanduser().resolve()
        return path if path.is_file() else None
    candidates: list[Path] = []
    for root_name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(root_name)
        if not root:
            continue
        adobe_root = Path(root) / "Adobe"
        if adobe_root.is_dir():
            candidates.extend(adobe_root.glob("Adobe Premiere Pro*/Adobe Premiere Pro.exe"))
    return sorted(candidates, reverse=True)[0].resolve() if candidates else None


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
    output_path = get_final_prproj_path(project, get_settings().workspace_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    executable = (premiere_executable or find_premiere_executable())
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
    marker_path.unlink(missing_ok=True)
    script_path.write_text(
        _conversion_script(fcpxml_path, output_path, marker_path),
        encoding="utf-8-sig",
    )
    _run_premiere_conversion(executable, script_path, marker_path, output_path, timeout_seconds)

    report = {
        **fcpxml_report,
        "path": str(output_path),
        "format": "prproj",
        "source_fcpxml_path": str(fcpxml_path),
        "premiere_executable": str(executable),
        "compatibility_notes": [
            "PRPROJ was created by Adobe Premiere Pro from the generated FCPXML timeline.",
            "Media is linked by absolute path; relink after moving source files.",
            "The FCPXML and SRT files are retained as interchange fallbacks.",
        ],
    }
    report_path = work_dir / "reports" / "prproj_export_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _conversion_script(fcpxml_path: Path, output_path: Path, marker_path: Path) -> str:
    def js(value: Path) -> str:
        return json.dumps(str(value), ensure_ascii=False)

    return f'''#target premierepro
(function () {{
    var marker = new File({js(marker_path)});
    var result = {{ success: false, error: "Premiere conversion did not complete" }};
    try {{
        var ok = app.openFCPXML({js(fcpxml_path)}, {js(output_path)});
        if (!ok) throw new Error("app.openFCPXML returned false");
        if (app.project) app.project.save();
        result = {{ success: true, path: {js(output_path)} }};
    }} catch (error) {{
        result = {{ success: false, error: String(error) }};
    }}
    marker.encoding = "UTF-8";
    marker.open("w");
    marker.write(JSON.stringify(result));
    marker.close();
}}());
'''


def _run_premiere_conversion(
    executable: Path,
    script_path: Path,
    marker_path: Path,
    output_path: Path,
    timeout_seconds: int,
) -> None:
    if not executable.is_file():
        raise ValueError(f"Premiere Pro executable does not exist: {executable}")
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
            result = json.loads(marker_path.read_text(encoding="utf-8-sig"))
            if not result.get("success"):
                raise RuntimeError(f"Premiere PRPROJ conversion failed: {result.get('error') or 'unknown error'}")
            if not output_path.is_file() or output_path.stat().st_size == 0:
                raise RuntimeError("Premiere reported success but the PRPROJ file was not created")
            return
        if process.poll() is not None:
            raise RuntimeError(f"Premiere exited before creating PRPROJ (exit code {process.returncode})")
        time.sleep(0.25)
    raise RuntimeError(f"Premiere PRPROJ conversion timed out after {timeout_seconds} seconds")
