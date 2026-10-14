<p align="center">
  <img src="frontend/public/brand/tubeaifolw-logo.png" alt="TubeAiFolw Logo" width="128" />
</p>

<h1 align="center">TubeAiFolw</h1>

<p align="center">
  面向 YouTube、Faceless 与长视频创作者的本地优先 AI 生产工作流
</p>

<p align="center"><strong>简体中文</strong> · <a href="README_EN.md">English</a></p>

> [!IMPORTANT]
> TubeAiFolw 正处于积极开发阶段。目前以 Vue 3 Web UI + FastAPI 本地引擎运行，尚未接入 Tauri/Electron 桌面壳，也尚未发布正式安装包。

---

## 项目简介

TubeAiFolw 不是“又一个 AI 视频生成器”，而是一套面向专业创作者的 **Local-first AI Long-form Video Production Workflow**。

它把脚本、分段 TTS、字幕对齐、语义分镜、本地素材匹配、本地 AI 插图、质量检查和剪辑工程导出组织成可恢复、可人工干预、可批量执行的生产流程，目标是稳定完成 20–60 分钟长视频，而不是只展示几十秒的 Demo。

核心原则：

- **本地优先**：重计算、项目数据、素材和日志尽量保留在本机。
- **BYOK**：第三方服务使用用户自己的 API Key。
- **Provider 可替换**：模型和供应商通过统一接口接入。
- **Scene-first**：以 Scene 作为文本、音频、字幕、画面和质量状态的核心单位。
- **可恢复**：耗时任务支持持久化、暂停、恢复、取消、重试和断点续跑。
- **人类可干预**：支持 Scene 编辑、锁定、素材替换和局部重新生成。
- **工程交付优先**：主交付物是可继续编辑的真实 `.prproj` 以及 WAV、SRT 和素材，而不是不可修改的最终 MP4。

## 当前能力

```text
创建项目
  ↓
导入 / 清洗 / 分段 TXT 或 Markdown 脚本
  ↓
本地分段 TTS 与最终 WAV 合并
  ↓
字幕对齐与 SRT
  ↓
语义 Storyboard / Visual Scene
  ↓
本地素材匹配或本地 AI 图片生成
  ↓
Scene Preview 与交付质量检查
  ↓
通过 Adobe Premiere Pro 转换并导出真实 PRPROJ
```

主要实现：

- 项目 CRUD、自定义输出目录、原子写入、产物清单和 SQLite Schema Migration。
- 持久化任务队列，以及 CPU、GPU、API、FFmpeg、Network 资源并发限制。
- TXT / Markdown 脚本清洗、普通分段与 AI 语义分段。
- IndexTTS、MOSS-TTS、CosyVoice 和 Qwen3-TTS 本地语音生成。
- Voice Profile、参考音频、单段重生成、失败重试、暂停与恢复。
- Faster-Whisper 本地字幕对齐；模型不可用时退回比例计时并标记人工复核。
- Local Qwen 与 DeepSeek BYOK 的结构化 Storyboard。
- Scene 编辑、历史版本恢复以及文本、音频、画面锁定。
- 本地图片/视频扫描、SHA-256 去重、候选排序和手动素材选择。
- 本地 SDXL，以及 BGE-M3、Qwen、FLUX/ComfyUI、Qwen3-VL 高级视觉流程。
- `anime_full_coverage` 动漫全片覆盖策略和 Scene 内多镜头分配。
- Scene Preview、技术质量检查和工程交付质量报告。
- FCPXML、Premiere XML 和真实 PRPROJ 工程导出。
- 最多 100 个 TXT / Markdown 脚本的批量项目导入与执行。
- 独立语音生成、本地视频拼接和数字人兼容工具。
- Windows DPAPI Secret Store、敏感字段过滤、诊断日志和自动清理。

## 尚未实现或尚未完成验收

- Tauri / Electron 桌面壳、Windows Installer、自动更新和代码签名。
- Account、Login、License、设备激活、支付与版本服务。
- 每项目独立的 `project.db`；当前权威数据库仍是全局 SQLite。
- Cloud TTS、Cloud Image、AI Video 和 Stock Provider。
- 完整关键帧提取、镜头切分、AI Caption 与统一 Embedding 素材搜索。
- Channel Profile、Style Bible、Workflow Preset 和完整成本统计。
- 真实本地模型 + GPU + Premiere Pro + 目标剪映版本的 20–60 分钟全链路 Golden Test。
- macOS、移动端、云端项目同步和多人协作。

TubeAiFolw **不计划**成为通用 NLE，不提供可拖拽多轨 Timeline、关键帧编辑或 Premiere / DaVinci / CapCut 替代能力。

## 架构

```text
┌─────────────────────────────────────┐
│ Vue 3 + TypeScript + Vite Web UI    │
└──────────────────┬──────────────────┘
                   │ localhost HTTP
┌──────────────────▼──────────────────┐
│ FastAPI + Python Local Engine       │
│ Workflow / Task Queue / Providers   │
└──────────┬──────────────┬───────────┘
           │              │
     SQLite + Files   FFmpeg + Local AI
                          │
                    Optional BYOK APIs
```

当前仍为开发期 Web 壳。前端不直接执行 AI 或拼接 FFmpeg 命令，工作流和重计算由本地引擎负责。

## 系统要求

基础环境：

- Windows 10 / Windows 11 64-bit（当前优先且主要验证的平台）
- Python 3.12（首次创建后端虚拟环境时需要）
- Node.js 20 LTS 或更新版本，以及 npm
- 足够的本地磁盘空间用于模型、音频、图片和项目素材

可选生产组件：

- FFmpeg / ffprobe；可在系统设置中自动下载并校验 Windows 构建。
- NVIDIA CUDA GPU；仅在运行本地大模型、图像模型或部分 TTS 时需要。
- Adobe Premiere Pro；仅生成真实 `.prproj` 时需要。TubeAiFolw 不会把 XML 改名伪装为 PRPROJ。
- 对应的本地 TTS、LLM、Embedding、Image 或 Vision 模型。

## Windows 快速启动

在仓库根目录双击 `Start_TubeAIFlow.bat`。首次启动会创建 `backend/.venv`、安装依赖、启动本地服务并打开浏览器。后续启动通过依赖指纹跳过未变化的安装步骤。

```powershell
# 启动
.\Start_TubeAIFlow.bat

# 重启 / 停止
.\Start_TubeAIFlow.bat --restart
.\Start_TubeAIFlow.bat --stop

# 只读环境检查 / 修复依赖
.\Start_TubeAIFlow.bat --check
.\Start_TubeAIFlow.bat --repair
```

也可以双击 `Restart_TubeAIFlow.bat`。兼容入口的共享逻辑位于 `scripts/Launch_TubeAiFolw.ps1`。

本地地址：

- 前端：<http://127.0.0.1:5173>
- 后端健康检查：<http://127.0.0.1:18080/api/health>
- FastAPI 文档：<http://127.0.0.1:18080/docs>

如果默认后端端口被占用，启动器会选择可用端口并配置前端。

创建桌面快捷方式：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts/Create_DesktopShortcut.ps1
```

移动仓库后请重新运行此命令。

## 手动开发启动

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m app.run
```

依赖文件：

- `requirements-core.txt`：本地引擎和云 Provider 的基础依赖。
- `requirements-tts-asr.txt`：TTS / ASR 集成。
- `requirements-local-ai-cu128.txt`：本地 CUDA AI 依赖。
- `requirements.txt`：完整 Windows 本地 AI 环境。
- `requirements-dev.txt`：测试和静态检查工具。

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

## 本地模型与高级视觉流程

模型按职责存放，模型文件不会提交到 Git：

```text
models/
  llm/qwen3-8b-q4_k_m/
  embedding/bge-m3-onnx/
  image_generation/flux2-klein-4b-fp8/
  vision/qwen3-vl-4b-instruct-bf16/
```

下载固定版本并安装本地服务：

```powershell
backend\.venv\Scripts\python.exe scripts\download_visual_models.py
backend\.venv\Scripts\python.exe scripts\install_llama_cpp.py
backend\.venv\Scripts\python.exe scripts\install_comfyui.py
```

按需启动语义或图像服务：

```powershell
backend\.venv\Scripts\python.exe scripts\start_visual_model_service.py semantic
backend\.venv\Scripts\python.exe scripts\start_visual_model_service.py image
```

默认 RTX 5060 Ti 配置只允许一个大型 GPU 工作负载。语义分析、图像生成和 Qwen3-VL QC 应串行运行。配置位于 `config/production_5060ti.yaml`。

无需加载模型的确定性检查：

```powershell
python run.py `
  --project tests/fixtures/demo `
  --config config/production_5060ti.yaml `
  --dry-run
```

使用 `--stage ingest|semantic|plan|generate|qc|timeline|render` 单独执行阶段，使用 `--resume` 复用 SHA-256 验证的产物，或使用 `--force` 重建。

## 项目数据与输出

每个项目可以选择独立输出目录：

```text
project-name/
  project.json
  input/
  audio/
  subtitles/
  scenes/
  assets/
  cache/
  renders/
  logs/
  reports/
  exports/
```

默认开发工作区位于 `backend/workspace`，其中可能包含 SQLite 数据库、日志、模型管理记录和兼容工具产物。工作区、模型、媒体和 Secret 不应提交到 Git。

## 测试与交付核验

```powershell
cd backend
python -m pip install -r requirements-dev.txt
pytest -q
ruff check app tests

cd ..\frontend
npm test
npm run build
```

真实长视频项目完成后：

```powershell
backend\.venv\Scripts\python.exe scripts\verify_long_form_delivery.py `
  --qa-report "<项目工作目录>\reports\qa.json" `
  --export-report "<项目工作目录>\reports\prproj_export_report.json"
```

自动核验不能替代人工在 Premiere Pro 和目标剪映专业版中打开工程，检查音频、字幕、素材链接和重链接行为。

## 安全与隐私

- 项目内容和重计算默认保留在本机。
- Windows Secret 使用 DPAPI 保护，SQLite 仅保存 Credential ID。
- API Key 保存后不会返回给前端。
- 任务快照过滤 API Key、Token、Secret 和 Password。
- BYOK Provider 接收的数据受相应供应商条款约束。
- 不要提交 `.env`、数据库、工作区、模型权重、日志或生成媒体。

## 贡献

欢迎 Issue、文档改进、Bug 修复和经过测试的 Pull Request。提交前请：

1. 保持产品名称为 **TubeAiFolw**。
2. 避免把业务逻辑、AI 推理或 FFmpeg 命令写入 UI 组件。
3. 新 Provider 通过 Registry / Adapter 接口实现。
4. 为行为变更添加或更新测试。
5. 运行后端测试、Ruff、前端测试和构建。
6. 不提交模型、密钥、用户素材和运行时产物。

架构与维护约束请参阅 `AGENTS.md`，补充文档位于 `docs/`。

## 界面导航说明

启动后，左侧导航分为生产工作区、独立工具和系统配置：

| 页面 | 用途 | 适合场景 |
|---|---|---|
| 项目 | 创建、查看和继续长视频项目 | 单个 20–60 分钟视频的完整生产 |
| 批量生产 | 一次导入多个 TXT / Markdown 脚本 | 多频道、工作室或系列内容批量处理 |
| 配音生成 | 不创建视频项目，直接生成分段旁白 | 只需要完整 WAV 和分段 WAV |
| 本地素材拼接 | 按顺序合并本地视频素材 | 快速合并已有片段 |
| 数字人合成 | 使用人物模板和完整旁白生成视频 | 兼容工具，非 V1 核心工作流 |
| 音色中心 | 创建、试听、复制、修改和删除 Voice Profile | 管理不同频道或角色音色 |
| 系统设置 | 配置存储、模型、Provider、字幕、图片和 FFmpeg | 首次使用及环境维护 |

系统设置包含以下分类：

- **基础与存储**：工作目录、本地服务、自动清理等。
- **AI 服务**：Local Qwen、DeepSeek BYOK 和模型管理。
- **配音引擎**：TTS Provider、模型路径与运行环境。
- **字幕对齐**：Faster-Whisper 路径和字幕质量参数。
- **图片生成**：本地 SDXL 等图片模型配置。
- **渲染与编码**：FFmpeg、ffprobe、Premiere Pro 和硬件编码器。
- **转场策略**：工程编排使用的基础转场设置。
- **系统诊断**：CPU、内存、磁盘、GPU、CUDA、FFmpeg 与编码器状态。

## 第一次使用前的建议配置

建议按以下顺序完成初始化：

1. 打开 **系统设置 → 基础与存储**，确认工作目录有足够空间。
2. 打开 **系统设置 → 系统诊断**，检查 Python、GPU、CUDA 和磁盘状态。
3. 打开 **系统设置 → 渲染与编码**，检测或自动安装 FFmpeg / ffprobe。
4. 在 **音色中心** 创建至少一个 Voice Profile，并试听参考音频。
5. 在 **系统设置 → 配音引擎** 中确认所选 TTS Provider 可用。
6. 如需 AI 语义分段或分镜，在 **AI 服务** 中配置 Local Qwen 或 DeepSeek。
7. 如需本地图片生成，在 **图片生成** 中配置 SDXL 或准备高级视觉管线。
8. 如需真实 PRPROJ，配置 Adobe Premiere Pro 路径并完成状态检测。

建议先用几百字脚本完成一次小项目，再运行 20–60 分钟正式项目。这样可以提前发现模型路径、音色参考文本、显存或 Premiere 自动转换问题。

## 完整项目操作指南

### 1. 准备脚本

项目工作流只接收 TXT 或 Markdown 完整逐字稿。建议：

- 使用实际需要朗读的正文，不要混入制作备注和不可朗读的 Markdown 元数据。
- 人名、数字、缩写和外语词按 TTS 能正确朗读的形式书写。
- 使用“按换行分段”时，一行代表一个期望的 TTS 段落；空行会被忽略。
- 使用“AI 语义分段”时，系统仍会校验文本完整性，避免 LLM 改写或遗漏原稿。
- 超长段落会自动拆分，当前单个 TTS 段落上限为 180 字符。

### 2. 创建项目

在 **项目 → 新建项目** 中填写：

- 项目名称：建议在频道内保持唯一，便于搜索和归档。
- 输出目录：脚本、音频、字幕、Scene、素材和报告都会写入该位置。
- 默认音色：从音色中心已保存的 Voice Profile 中选择。

项目创建后仍可以在工作流开始前修改基础设置。旁白生成完成后，影响既有旁白的配置会被锁定，但后续视频配置仍可调整。

### 3. 配置生产模式

项目设置中的视频生产模式：

| 模式 | 行为 | 需要本地素材目录 |
|---|---|---:|
| 仅配音与字幕 | 生成 WAV 和 SRT，不进入视觉生产 | 否 |
| AI 分镜图片 | 为 Scene 生成本地 AI 图片 | 否 |
| AI 图片 + 本地横屏素材 | 混合使用生成图片和本地素材 | 是 |
| 仅本地横屏素材 | 扫描并匹配用户提供的图片/视频 | 是 |

分镜方式：

- **AI 语义分镜**：根据字幕语义和节奏重新规划 Visual Scene。
- **沿用 TTS 分段**：直接以旁白段落作为 Scene 边界，结果更确定。

高级视觉模式：

- `basic`：仅使用基础本地 SDXL 管线。
- `auto`：尝试 BGE-M3、Local Qwen、FLUX/ComfyUI 和 Qwen3-VL；可选组件不可用时记录报告并回退。
- `advanced`：要求高级视觉组件成功，失败时让持久化任务明确失败。
- `anime_full_coverage`：按 8–15 秒语义主场景覆盖整片，并为长 Scene 派生稳定 Visual Beat 和连续多镜头。

界面会根据视频生产模式只显示兼容的画面策略。

### 4. 导入并保存脚本

进入项目工作区的 **脚本** 阶段，粘贴完整逐字稿并保存。页面会显示字符数和预计旁白时长。

脚本保存前离开页面会丢失未保存修改。开始生成后不要直接编辑项目目录中的中间文件，应优先通过界面修改并让工作流正确失效下游产物。

### 5. 运行旁白工作流

点击 **运行工作流** 后，引擎依次完成脚本规范化、分段、逐段 TTS、音频探测、合并 WAV、字幕对齐与 SRT 生成。

长任务可以：

- 查看当前阶段、进度、排队位置和错误信息。
- 暂停或恢复支持该操作的持久化 Job。
- 取消当前项目任务。
- 对失败段重试，或只重新生成某一个 TTS Segment。
- 重启应用后恢复中断任务。

最终字幕文本始终来自原始逐字稿；ASR 只用于定位时间，不会用识别文本替换原稿。

### 6. 检查分镜

Storyboard 创建后，可逐个 Scene 检查：

- 原文、起止时间和视觉摘要。
- Visual Type、推荐来源、搜索词、人物、地点和情绪。
- Fact Risk、Image Prompt 和 Negative Prompt。
- Scene 历史版本与修改记录。

锁定字段的作用：

- `locked_text`：后续操作不能自动覆盖文本。
- `locked_audio`：保护已确认的旁白结果。
- `locked_visual`：保护人工选择或确认的画面。

修改 Scene 后，只会失效相关的局部下游产物，不需要无条件重做整片。

### 7. 选择或生成画面

本地素材模式会扫描项目配置的目录，读取分辨率、时长和编码信息，并使用 SHA-256 去重。候选结果综合文件名、描述、标签、画面规格和重复使用情况排序。

每个 Scene 可以：

- 手动选择本地图片或视频候选。
- 生成多张图片候选并选择其一。
- 重新生成当前 Scene 的图片。
- 设置 Scene 内连续多个 Shot、Trim、Playback Speed 和显示时长。
- 生成 Scene Preview 进行快速检查。

`MediaKeyframe` 数据表已经存在，但完整视频镜头切分、关键帧提取和 AI Caption 尚未完成。因此，当前本地视频匹配质量仍较依赖文件名、描述和标签。

### 8. 导出剪辑工程

主工作流在素材准备完成后进入 **工程导出**。系统先生成中间交换格式，再调用 Adobe Premiere Pro 转换成真实 `.prproj`。

交付内容通常包括：

- `.prproj`：包含旁白、字幕和素材链接的真实 Premiere 工程。
- `final.wav`：完整旁白。
- `final.srt`：最终字幕。
- 生成或引用的视觉素材。
- 导出报告和质量检查报告。

工程使用绝对路径链接素材。移动项目目录、删除素材或更改盘符后，Premiere 或剪映专业版可能要求重新链接。

### 9. 完成交付检查

交付 QC 会检查：

- PRPROJ、WAV、SRT 是否存在且非空。
- PRPROJ 转换记录和文件 SHA-256 证据链。
- SRT 与保存的字幕时间线是否一致。
- Scene 时间轴是否存在空洞、重叠或无效时长。
- Scene 是否被素材覆盖，关联素材是否仍然存在。
- 报告生成后文件或项目编排是否发生变化。

自动 QC 通过不代表目标剪辑软件一定兼容。最终仍需人工在 Premiere Pro 和目标剪映版本中打开工程，并在界面记录人工验收结果。

## Voice Profile 与独立配音生成

音色中心支持 WAV、MP3、FLAC、M4A 等常见参考音频。参考文本应尽可能准确对应音频实际内容：

- **Qwen3-TTS**：提供准确参考文本时克隆效果通常更好；缺失时使用仅 Speaker Embedding 模式。
- **CosyVoice**：Zero-shot 克隆需要准确的参考音频逐字稿。
- **IndexTTS / MOSS-TTS**：使用各自隔离的本地环境，路径在系统设置中配置。

独立 **配音生成** 页面适合不需要创建视频项目的任务：

1. 选择 Voice Profile。
2. 输入输出 WAV 文件名。
3. 每行粘贴一个期望的 TTS 段落。
4. 提交任务并等待逐段生成与合并。
5. 下载完整 WAV 或任意分段 WAV。

每个任务拥有 32 位十六进制 UUID。可在生成历史复制 ID，或使用以下格式搜索日志：

```text
[task_id=<任务 ID>]
```

默认产物结构：

```text
backend/workspace/voice_generations/{task_id}/
  输出文件.wav
  segments/
    输出文件_0001.wav
    输出文件_0002.wav
  segments.json
  logs/
```

## 批量生产

批量生产适合结构和默认配置相近的多个项目：

1. 一次选择最多 100 个 TXT / Markdown 文件。
2. 设置输出根目录、默认音色和生产配置。
3. 创建批次并开始执行。
4. 随时查看批次与单项目进度。
5. 暂停批次不会删除已经完成的项目产物。
6. 单个项目失败不会阻止后续项目继续运行，可单独重试失败项目。

正式批量生产前，建议先用同一音色和配置完成一个代表性项目，以确认 TTS、显存和磁盘空间满足要求。

## 仓库目录说明

```text
TubeAiFolw/
  backend/                 FastAPI 本地引擎、服务、数据库与测试
    app/api/               HTTP API
    app/providers/         Provider Registry 与类型
    app/services/          项目、TTS、视觉、质量和渲染服务
    app/workflows/         工作流定义与步骤
    tests/                 后端自动化测试
    workspace/             默认运行时工作区，不提交 Git
  frontend/                Vue 3 + TypeScript 用户界面
    src/api/               前端 API Client
    src/components/        可复用组件
    src/pages/             项目、批量、工具和设置页面
  config/                  高级视觉与硬件配置
  docs/                    架构和维护文档
  models/                  本地模型目录，不提交 Git
  schemas/                 数据交换 Schema
  scripts/                 启动、安装、下载和交付核验脚本
  tests/fixtures/          管线测试夹具
  workflows/               ComfyUI 等外部工作流定义
  run.py                   独立高级视觉管线入口
```

## 日志、恢复与问题定位

默认日志位于 `backend/workspace/logs`。启动器记录前后端进程 ID，并通过进程树和监听端口停止旧实例。遇到问题时建议按顺序检查：

1. 运行 `.\Start_TubeAIFlow.bat --check` 验证环境，不安装依赖也不启动服务。
2. 查看系统设置中的诊断结果和 Provider 状态。
3. 查看界面显示的任务 ID、错误码和错误信息。
4. 在 `backend/workspace/logs/engine.log` 中搜索任务 ID。
5. 依赖损坏时运行 `.\Start_TubeAIFlow.bat --repair`。
6. 服务状态异常时运行 `.\Start_TubeAIFlow.bat --restart`。

常见问题：

### 页面打不开

确认启动窗口没有报错，并访问健康检查地址。默认前端端口为 `5173`；后端默认端口为 `18080`，但被占用时可能自动变化。

### PowerShell 禁止脚本执行

仓库入口已经使用 `-ExecutionPolicy Bypass` 调用共享脚本。手动执行脚本时也可以为当前命令添加该参数，不建议永久降低系统执行策略。

### FFmpeg 不可用

打开 **系统设置 → 渲染与编码** 重新检测或自动安装。自动安装只把 `ffmpeg.exe` 和 `ffprobe.exe` 放入本地工作区，不会修改全局系统安装。

### CUDA OOM / 显存不足

停止其他 GPU 任务，避免同时运行语义、图片和 Vision 模型。图片生成在部分 OOM 场景会降低分辨率重试，但正式项目仍应预留显存。

### 字幕被标记为需要人工复核

通常表示 Faster-Whisper 模型不可用，系统使用了比例计时。配置本地对齐模型后重新运行字幕阶段，并检查字幕重叠、持续时间、字符数和 CPS。

### PRPROJ 导出失败

确认 Premiere Pro 路径正确、应用可以在当前 Windows 用户下启动、中间 XML 存在，并检查 `prproj_export_report.json`。成功转换必须有 Premiere 执行记录和文件哈希，不能手工修改扩展名代替转换。

### QC 报告先前通过、后来变为过期

生成报告后修改了 PRPROJ、WAV、SRT、素材或 Scene 编排时，原报告会自动失效。重新运行交付检查并再次完成人工打开验收。

## 使用边界与数据备份

- 当前没有正式的 Project Backup / Restore 用户流程。重要项目应由用户自行备份整个项目输出目录。
- 删除项目时会尝试移动到 Windows 回收站，但不应把回收站视为备份方案。
- 不要只备份 `.prproj`；还应保留 WAV、SRT、项目素材、报告和 `project.json`。
- 项目移动后可能需要在剪辑软件中重链接绝对路径素材。
- 运行清理任务前仔细阅读保留规则；部分超过保留期的已完成任务日志和音频可能被永久删除。
- 模型、字体、第三方素材和参考音频可能有独立许可证，商业发布前需要自行确认使用权。

## 许可证

本仓库当前尚未包含 `LICENSE` 文件。因此，在许可证正式加入前，源代码适用默认版权规则；仓库公开可见不等同于已经授予复制、修改或分发许可。

计划参与、分发或商业集成前，请等待项目明确发布许可证。建议的发行方向是 **AGPL-3.0-only + 独立商业许可证**，但只有在根目录正式加入相应法律文件后才生效。
