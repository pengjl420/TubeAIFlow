#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="D:/TubeAIFlow"
MODELS_ROOT="${PROJECT_ROOT}/models"

# Python环境和模型缓存严格分开
ENV_DIR="${MODELS_ROOT}/framepack_env"
CACHE_DIR="${MODELS_ROOT}/framepack_cache"

WORKER_REQUIREMENTS="${PROJECT_ROOT}/backend/framepack_worker/requirements.txt"

echo "========================================"
echo "FramePack 环境目录：${ENV_DIR}"
echo "FramePack 模型缓存：${CACHE_DIR}"
echo "========================================"

mkdir -p "${ENV_DIR}"
mkdir -p "${CACHE_DIR}"

# 检查磁盘空间；建议至少保留55GB
py -3.10 -c "
import shutil
total, used, free = shutil.disk_usage('D:/')
free_gb = free / 1024**3
print(f'D盘当前剩余空间：{free_gb:.1f} GB')
if free_gb < 55:
    raise SystemExit('错误：建议至少准备55GB可用空间，请先清理D盘。')
"

# 检查Python 3.10
if ! py -3.10 --version >/dev/null 2>&1; then
    echo "错误：没有检测到Python 3.10。"
    echo "请先安装Python 3.10，并确保Windows py启动器可用。"
    exit 1
fi

# 创建独立虚拟环境
if [ ! -f "${ENV_DIR}/Scripts/python.exe" ]; then
    echo "创建FramePack独立Python环境……"
    py -3.10 -m venv "${ENV_DIR}"
else
    echo "FramePack环境已经存在，继续使用。"
fi

PYTHON="${ENV_DIR}/Scripts/python.exe"

echo "升级pip基础工具……"
"${PYTHON}" -m pip install --upgrade pip setuptools wheel

echo "安装PyTorch 2.6 CUDA 12.6……"
"${PYTHON}" -m pip install \
    torch==2.6.0 \
    torchvision==0.21.0 \
    torchaudio==2.6.0 \
    --index-url https://download.pytorch.org/whl/cu126

echo "安装FramePack Worker依赖……"
"${PYTHON}" -m pip install -r "${WORKER_REQUIREMENTS}"

# 固定当前接入代码所使用的Diffusers版本
"${PYTHON}" -m pip install \
    "diffusers==0.39.0" \
    "huggingface_hub>=0.30" \
    "sentencepiece>=0.2" \
    "protobuf>=5"

# Hugging Face会在HF_HOME/hub下保存模型
export HF_HOME="${CACHE_DIR}"
export HF_HUB_DISABLE_SYMLINKS_WARNING=1

echo "开始下载FramePack模型，下载量超过30GB……"
echo "模型缓存位置：${HF_HOME}/hub"

"${PYTHON}" - <<'PY'
import os
from pathlib import Path
from huggingface_hub import snapshot_download

cache_root = Path(os.environ["HF_HOME"]) / "hub"
cache_root.mkdir(parents=True, exist_ok=True)

models = [
    # FramePack F1 Transformer
    "lllyasviel/FramePack_F1_I2V_HY_20250503",

    # HunyuanVideo基础模型
    "hunyuanvideo-community/HunyuanVideo",

    # SigLIP图像编码器
    "lllyasviel/flux_redux_bfl",
]

token = os.environ.get("HF_TOKEN") or None

for index, model_id in enumerate(models, start=1):
    print()
    print("=" * 72)
    print(f"[{index}/{len(models)}] 正在下载：{model_id}")
    print("=" * 72)

    path = snapshot_download(
        repo_id=model_id,
        cache_dir=str(cache_root),
        token=token,
        resume_download=True,
    )

    print(f"下载完成：{path}")

print()
print("所有FramePack模型下载完成。")
PY

echo
echo "验证CUDA和环境……"

"${PYTHON}" - <<'PY'
import torch
import diffusers
import transformers

print("PyTorch:", torch.__version__)
print("PyTorch CUDA:", torch.version.cuda)
print("CUDA可用:", torch.cuda.is_available())
print("Diffusers:", diffusers.__version__)
print("Transformers:", transformers.__version__)

if torch.cuda.is_available():
    print("显卡:", torch.cuda.get_device_name(0))
    memory = torch.cuda.get_device_properties(0).total_memory / 1024**3
    print(f"显存: {memory:.1f} GB")
else:
    raise SystemExit("错误：PyTorch无法识别CUDA显卡。")
PY

echo
echo "========================================"
echo "FramePack安装和模型下载完成"
echo
echo "系统设置中填写："
echo "FramePack Python："
echo "D:\\TubeAIFlow\\models\\framepack_env\\Scripts\\python.exe"
echo
echo "模型缓存目录："
echo "D:\\TubeAIFlow\\models\\framepack_cache"
echo
echo "建议设置："
echo "CPU Offload：开启"
echo "允许下载模型：关闭"
echo "自动启动Worker：开启"
echo "采样策略：F1 vanilla"
echo "========================================"