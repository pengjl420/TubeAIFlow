from app.integrations.image_generation.sdxl_runner import (
    _is_cuda_oom,
    _reduced_dimensions,
)


def test_cuda_oom_is_classified_without_hiding_other_failures() -> None:
    assert _is_cuda_oom(RuntimeError("CUDA out of memory"))
    assert not _is_cuda_oom(RuntimeError("model file not found"))


def test_oom_retry_dimensions_are_smaller_and_model_compatible() -> None:
    width, height = _reduced_dimensions(1344, 768)

    assert (width, height) == (1008, 576)
    assert width % 8 == 0
    assert height % 8 == 0
