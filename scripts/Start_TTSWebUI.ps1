param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("index_tts", "moss_tts", "cosyvoice", "qwen3_tts")]
    [string]$Engine
)

$ErrorActionPreference = "Stop"
switch ($Engine) {
    "index_tts" {
        $root = "D:\index-tts"; $python = Join-Path $root "python310\python.exe"; $url = "http://127.0.0.1:7861"
        $arguments = @("-s", (Join-Path $root "webui.py"), "--host", "127.0.0.1", "--port", "7861", "--model_dir", (Join-Path $root "checkpoints"))
    }
    "moss_tts" {
        $root = "D:\MOSS-TTS"; $python = Join-Path $root ".venv\Scripts\python.exe"; $url = "http://127.0.0.1:7860"
        $codec = Join-Path $root "models\cache\hub\models--OpenMOSS-Team--MOSS-Audio-Tokenizer-v2\snapshots\f6e20e543b33d2c252a7ef71bdf8aa71e5ff9169"
        $arguments = @((Join-Path $root "clis\moss_tts_local_v1.5_app.py"), "--model-dir", (Join-Path $root "models\MOSS-TTS-Local-Transformer-v1.5"), "--codec-dir", $codec, "--device", "cuda", "--tts-device", "cuda:0", "--codec-device", "cuda:0", "--dtype", "bfloat16", "--attn-implementation", "sdpa", "--codec-weight-dtype", "bf16", "--codec-compute-dtype", "bf16", "--host", "127.0.0.1", "--port", "7860")
        $env:HF_HOME = Join-Path $root "models\cache"; $env:HF_HUB_OFFLINE = "1"; $env:HF_HUB_DISABLE_XET = "1"
    }
    "cosyvoice" {
        $root = "D:\CosyVoice"; $python = Join-Path $root ".venv\Scripts\python.exe"; $url = "http://127.0.0.1:50000"
        $arguments = @((Join-Path $root "webui.py"), "--host", "127.0.0.1", "--port", "50000", "--model_dir", (Join-Path $root "pretrained_models\Cosyvoice2-Yue-ZoengJyutGaai"))
        $env:PYTHONPATH = "$root;$root\third_party\Matcha-TTS"; $env:MODELSCOPE_CACHE = Join-Path $root "model_cache\modelscope"; $env:HF_HOME = Join-Path $root "model_cache\huggingface"
    }
    "qwen3_tts" {
        $root = "D:\Qwen3-TTS"; $python = "D:\TubeAIFlow\backend\.venv\Scripts\python.exe"; $url = "http://127.0.0.1:7862"; $webui = Join-Path $root "webui.py"
        if (-not (Test-Path -LiteralPath $webui)) { throw "Qwen3-TTS checkout does not provide webui.py: $webui" }
        $arguments = @($webui, "--host", "127.0.0.1", "--port", "7862")
    }
}
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "TTS Python runtime was not found: $python" }
Write-Host "Starting $Engine WebUI at $url"
Start-Process $url
& $python @arguments
