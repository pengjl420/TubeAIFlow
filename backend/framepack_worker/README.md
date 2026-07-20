# TubeAIFlow FramePack Worker

This worker is intentionally isolated from the main backend environment. It uses
Hugging Face Diffusers' `HunyuanVideoFramepackPipeline`, loads the model once,
and processes jobs serially on `127.0.0.1`.

## Environment

```powershell
cd D:\TubeAIFlow\backend\framepack_worker
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu126
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Then set **FramePack Python** in TubeAIFlow System Settings to:

```text
D:\TubeAIFlow\backend\framepack_worker\.venv\Scripts\python.exe
```

Model downloading is disabled by default because the required caches exceed
30 GB. Either prepare the Hugging Face cache manually or explicitly enable
**Allow model download** in System Settings before starting the worker.

The F1 transformer uses `vanilla` sampling. If the transformer is changed to
`lllyasviel/FramePackI2V_HY`, change the sampling type to
`inverted_anti_drifting` as well.

Worker output is restricted to the configured TubeAIFlow workspace. Logs are
written to `workspace/logs/framepack_worker.log`.

