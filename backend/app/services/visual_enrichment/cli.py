from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.services.visual_enrichment.pipeline import STAGE_ORDER, VisualEnrichmentPipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="TubeAiFolw semantic visual enrichment pipeline")
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--stage", choices=(*STAGE_ORDER, "dry-run"))
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.force and args.resume:
        raise SystemExit("--force and --resume cannot be used together")
    pipeline = VisualEnrichmentPipeline(
        args.project,
        args.config,
        resume=args.resume,
        force=args.force,
        dry_run=args.dry_run,
    )
    outputs = pipeline.run(args.stage)
    print(json.dumps({"success": True, "data": outputs}, ensure_ascii=False, indent=2))
    return 0
