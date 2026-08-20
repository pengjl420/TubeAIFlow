from pathlib import Path

from app.schemas.subtitle_alignment import AsrWord, Language


class FasterWhisperAligner:
    """Lazy, local-only faster-whisper adapter.

    Model loading is delayed until the first segment so normal application startup
    does not require the optional ASR dependency or consume GPU memory.
    """

    name = "faster-whisper"

    def __init__(
        self,
        model_path: Path,
        *,
        device: str = "cuda",
        compute_type: str = "float16",
        beam_size: int = 5,
    ) -> None:
        path = model_path.expanduser().resolve()
        if not path.is_dir():
            raise ValueError(f"Whisper 本地模型目录不存在：{path}")
        self.model_path = path
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self._model = None

    def transcribe(self, audio_path: Path, language: Language, *, vad_filter: bool = False) -> list[AsrWord]:
        if not audio_path.is_file():
            raise ValueError(f"字幕对齐音频不存在：{audio_path}")
        model = self._get_model()
        segments, _ = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=self.beam_size,
            temperature=0,
            word_timestamps=True,
            vad_filter=vad_filter,
            condition_on_previous_text=False,
        )
        words: list[AsrWord] = []
        for segment in segments:
            for word in segment.words or []:
                start_ms = max(0, round(float(word.start) * 1000))
                end_ms = max(start_ms + 1, round(float(word.end) * 1000))
                probability = float(getattr(word, "probability", 1.0) or 0.0)
                words.append(
                    AsrWord(
                        text=str(word.word),
                        start_ms=start_ms,
                        end_ms=end_ms,
                        confidence=max(0.0, min(1.0, probability)),
                    )
                )
        return words

    def _get_model(self):
        if self._model is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "未安装 faster-whisper，无法启用精准字幕对齐；请在后端环境安装可选依赖"
                ) from exc
            self._model = WhisperModel(
                str(self.model_path),
                device=self.device,
                compute_type=self.compute_type,
                local_files_only=True,
            )
        return self._model

