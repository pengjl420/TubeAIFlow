import json
from pathlib import Path

from app.services.visual_enrichment.providers import ComfyUIImageProvider, ImageQCResult


def test_flux2_workflow_template_patches_typed_inputs() -> None:
    root = Path(__file__).resolve().parents[3]
    template = json.loads(
        (root / "workflows" / "flux2_klein_scene_api.json").read_text(encoding="utf-8")
    )
    patched = ComfyUIImageProvider._patch(
        template,
        {
            "visual_id": "visual_0001",
            "prompt": "editorial image",
            "seed": 42,
            "width": 512,
            "height": 288,
            "candidates": 3,
        },
    )

    assert patched["4"]["inputs"]["text"] == "editorial image"
    assert patched["7"]["inputs"]["noise_seed"] == 42
    assert patched["10"]["inputs"]["batch_size"] == 3
    assert "{{" not in json.dumps(patched)


def test_image_qc_schema_rejects_out_of_range_score() -> None:
    try:
        ImageQCResult.model_validate(
            {
                "semantic_match": 6,
                "random_text": False,
                "watermark": False,
                "unapproved_logo": False,
                "approved": True,
            }
        )
    except ValueError:
        return
    raise AssertionError("out-of-range semantic_match must fail validation")
