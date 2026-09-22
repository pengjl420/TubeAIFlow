"""Verify the artifacts from an opt-in real long-form production run.

This checks delivered files and reports. Opening the project in Premiere Pro
and the target Jianying version remains a manual acceptance step.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path


def verify(qa_path: Path, export_path: Path, minimum: float, maximum: float) -> list[str]:
    failures: list[str] = []
    try:
        qa = json.loads(qa_path.read_text(encoding="utf-8"))
        exported = json.loads(export_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"无法读取验收报告：{exc}"]
    if not isinstance(qa, dict) or not isinstance(exported, dict):
        return ["验收报告必须是 JSON 对象"]
    summary = qa.get("summary")
    if not isinstance(summary, dict):
        return ["QC 报告缺少 summary"]

    duration = summary.get("audio_duration_seconds")
    if not isinstance(duration, (int, float)) or not minimum * 60 <= duration <= maximum * 60:
        failures.append(f"旁白时长不在 {minimum:g}～{maximum:g} 分钟范围内：{duration}")
    if not qa.get("passed"):
        failures.append("交付质量检查未通过")
    if qa.get("schema_version") != 1:
        failures.append(f"不支持的 QC 报告版本：{qa.get('schema_version')}")
    if not qa.get("delivery_verified") or not qa.get("premiere_conversion_verified"):
        failures.append("Premiere 转换证据未通过自动验证")
    if qa.get("verification_status") not in {
        "manual_acceptance_required", "manually_accepted"
    }:
        failures.append("QC 报告缺少有效的交付验证状态")
    if summary.get("scene_count", 0) < 1:
        failures.append("验收报告没有 Scene")
    if (
        exported.get("schema_version") != 1
        or
        exported.get("format") != "prproj"
        or not exported.get("premiere_executable")
        or not exported.get("export_id")
        or not exported.get("created_at")
        or not isinstance(exported.get("premiere_result"), dict)
        or exported["premiere_result"].get("success") is not True
    ):
        failures.append("缺少 Premiere Pro 转换记录")

    for label, value in (
        ("PRPROJ", exported.get("path")),
        ("WAV", summary.get("audio_path")),
        ("SRT", summary.get("srt_path")),
    ):
        if not isinstance(value, str) or not Path(value).is_file() or Path(value).stat().st_size == 0:
            failures.append(f"{label} 文件不存在或为空：{value}")
    if exported.get("path") != summary.get("prproj_path"):
        failures.append("导出报告与 QC 报告指向不同的 PRPROJ")
    signatures = qa.get("file_signatures")
    if not isinstance(signatures, dict):
        failures.append("QC 报告缺少文件状态记录，需重新运行质量检查")
    else:
        for path, signature in signatures.items():
            file_path = Path(path)
            try:
                stat = file_path.stat() if file_path.is_file() else None
            except OSError:
                stat = None
            if stat and isinstance(signature, dict) and signature.get("sha256"):
                digest = hashlib.sha256()
                try:
                    with file_path.open("rb") as file:
                        for chunk in iter(lambda: file.read(1024 * 1024), b""):
                            digest.update(chunk)
                    current = {
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                        "sha256": digest.hexdigest(),
                    }
                except OSError:
                    current = None
            else:
                current = [stat.st_size, stat.st_mtime_ns] if stat else None
            if current != signature:
                failures.append(f"文件在 QC 后发生变化：{path}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="核验真实长视频项目的交付产物")
    parser.add_argument("--qa-report", required=True, type=Path)
    parser.add_argument("--export-report", required=True, type=Path)
    parser.add_argument("--min-minutes", type=float, default=20)
    parser.add_argument("--max-minutes", type=float, default=30)
    args = parser.parse_args()
    if args.min_minutes <= 0 or args.max_minutes < args.min_minutes:
        parser.error("分钟范围无效")
    failures = verify(args.qa_report, args.export_report, args.min_minutes, args.max_minutes)
    if failures:
        for item in failures:
            print(f"失败：{item}", file=sys.stderr)
        return 1
    print("自动交付核验通过；仍需在 Premiere Pro 与目标剪映版本中实际打开并检查工程。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
