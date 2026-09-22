# AGENTS.md — TubeAiFolw

> 本文件位于项目仓库根目录，用于指导 Codex、ChatGPT、Claude Code、Cursor Agent、GitHub Copilot Agent 及其他自动化编码代理理解、开发、重构和维护本项目。
>
> **项目名称必须使用：`TubeAiFolw`**
>
> 本项目的核心定位不是“又一个 AI 视频生成器”，而是：
>
> **面向 YouTube / Faceless / 长视频创作者的 Local-first AI Production Workflow（本地优先 AI 长视频生产工作流）**
>
> 产品目标是将脚本、TTS、字幕、语义分镜、素材规划、AI 插图、质量检测和剪辑工程导出组织成稳定、可恢复、可人工干预、可批量生产的桌面工作流。
>
> 当前优先平台：**Windows 10 / Windows 11**
>
> 产品形态：**Desktop + License + Local AI Engine + BYOK（Bring Your Own Key）**
>
> 主要原则：
>
> 1. 重计算尽量发生在用户本地。
> 2. 云端只负责账号、License、版本、支付状态、轻量配置等。
> 3. 用户可使用自己的本地 GPU。
> 4. 用户可配置自己的第三方 API Key。
> 5. 模型与供应商必须可替换。
> 6. 核心护城河不是模型，而是 Workflow、Visual Matching、Quality Control 和可靠的剪辑工程交付。
> 7. 优先服务已经在生产内容的专业创作者，而不是完全小白。
> 8. 产品设计必须支持长视频，不能仅围绕 Shorts 或 30 秒 Demo。
> 9. 默认追求“稳定完成 20~60 分钟视频”而不是“展示炫酷 AI 效果”。
> 10. 产品必须从第一天开始考虑长期商业化、版本升级、License、数据迁移和可维护性。

---

# 0. 当前实现状态快照（2026-09-20）

> 本节记录已经通过代码与测试核验的实现现状，供后续 Coding Agent 优先读取。
>
> **开始任务时不要为了了解全局功能而重新扫描整个仓库。** 先以本节为基线，只针对当前任务涉及的模块读取实现和测试。若代码与本节不一致，以代码为准，并在完成修改时同步更新本节。

## 0.1 当前形态与验证基线

当前产品是：

```text
Vue 3 + TypeScript Web UI
        ↓ localhost HTTP
FastAPI + Python Local Engine
        ↓
SQLite + Project Directory + FFmpeg + Local AI
```

当前仍是开发期 Web 壳，通过 BAT / PowerShell 启动并打开浏览器；尚未接入 Tauri 或 Electron Desktop Shell。

2026-09-16 验证基线：

- Backend：`327 passed`
- Frontend：`3` 个测试文件、`7 passed`
- Frontend：`npm run build` 成功
- 已有 20 / 30 / 60 分钟规模的分段、Scene 边界和帧数精度测试
- 已有 `scripts/verify_long_form_delivery.py` 对真实项目产物、交付 QC 和 Premiere 转换记录做可重复的自动核验；尚无真实本地模型 + GPU + Premiere Pro + 目标剪映版本完成 20~60 分钟项目的全链路 Golden Test

真实项目完成后，可运行：

```powershell
backend\.venv\Scripts\python.exe scripts\verify_long_form_delivery.py --qa-report "<项目工作目录>\reports\qa.json" --export-report "<项目工作目录>\reports\prproj_export_report.json"
```

默认检查 20~30 分钟旁白、QC 通过、PRPROJ / WAV / SRT 非空、文件在 QC 后是否变化和 Premiere 转换记录。脚本不连接项目数据库；Scene 或素材分配变化应在 Project Workspace 重新检查。仍须在 Premiere Pro 和目标剪映版本中实际打开工程，检查音频、字幕、素材链接与重链接；验收脚本不能自动证明兼容性。

## 0.2 已实现的核心生产流程

当前主应用已经具备以下项目级链路：

```text
项目创建
↓
脚本导入 / 清洗 / 分段
↓
本地 TTS 分段生成与合并
↓
字幕对齐与 SRT
↓
语义 Storyboard / Visual Scene
↓
本地素材匹配或本地 AI 图片生成
↓
高级本地视觉增强（BGE-M3 / Qwen / FLUX / Qwen3-VL）
↓
本地素材匹配或本地 AI 图片生成
↓
Scene Preview 与基础质量检查
↓
带旁白、字幕和素材链接的 Premiere PRPROJ 工程导出
```

### Project 与工程文件

已实现：

- Project CRUD、状态管理、用户自定义输出目录
- 脚本保存、参考音频上传、项目设置和视频工作流设置
- 每项目独立目录，包含 `input`、`audio`、`subtitles`、`scenes`、`assets`、`cache`、`renders`、`logs`、`reports`、`exports` 等目录
- 原子写入、项目产物清单和不含 Secret 的 `project.json`
- 项目删除时移动到 Windows 回收站
- 全局 SQLite Schema Migration、迁移前备份、失败恢复
- Schema v23 为生成图片与 SceneAssignment 增加稳定 `visual_beat_id`，旧项目可原地迁移

注意：当前权威数据库仍是全局 SQLite；AGENTS.md 规划的每项目 `project.db` 尚未实现。

### Workflow 与 Task Queue

已实现：

- `WorkflowRegistry`、`WorkflowGraph`、注册式 `WorkflowStep`
- Step 的依赖、输入产物、输出产物、Resource Class 和 Cache 声明
- 持久化 `TaskRun`
- CPU / GPU / API / FFMPEG / NETWORK Resource Class 与并发限制
- Queue Sequence、Task Lease、Heartbeat，避免 Worker 重复领取
- Pause、Resume、Cancel、Retry、Checkpoint、配置快照
- 应用启动后恢复中断任务
- Scene 级 Storyboard、图片生成和 Preview Job
- 项目级素材扫描、Scene Preview、Visual Enrichment 和 PRPROJ Project Export Job
- 稳定的部分 Error Code 与统一 API 错误响应

### Script Engine

已实现：

- TXT / Markdown 脚本输入
- 文本清洗、换行分段、AI 语义分段
- 超长 TTS 段落自动拆分，当前单段上限为 180 字符
- AI 分段后校验文本完整性，防止 LLM 改写或遗漏原稿
- 分段级 Visual Hint
- 长脚本的有界上下文处理

部分实现：Entity / Event / Location / Citation 等结果尚未形成独立、统一的 Script Semantic 持久模型。

明确范围：Script Engine 只围绕 TXT / Markdown 完整逐字稿工作；不规划 Word、PDF、Podcast、已有音频统一导入器，也不规划章节编辑和章节审核界面。

### TTS 与 Voice Profile

已实现的本地 TTS：

- IndexTTS
- MOSS-TTS
- CosyVoice
- Qwen3-TTS

已实现能力：

- Voice Profile 创建、修改、复制、删除
- Reference Audio、Reference Text、语言和 Provider 配置
- Segment 级生成、状态、日志和音频文件
- 单段重新生成、失败段重试、暂停、恢复和重启恢复
- 音频时长探测、Segment 合并、最终 WAV
- GPU 任务保护、进程取消、部分异常音频自动重试
- 独立 Voice Generation 兼容工具页面

未实现：ElevenLabs、OpenAI、Azure、Google 等 Cloud TTS Provider。

### Subtitle / Alignment

已实现：

- TTS Segment 与 Subtitle Cue 解耦
- Faster-Whisper 本地时间对齐
- 无本地模型时使用比例计时并标记人工复核
- 最终字幕文本只取原始逐字稿，ASR 仅用于时间定位
- 字幕字符上限、最短/最长持续时间、CPS 配置
- Alignment JSON、SRT 生成与读取
- 字幕重叠、溢出、时长、字符数和 CPS 质量检查

### Storyboard 与 Scene

已实现：

- 从 Subtitle Cue 或 TTS Segment 创建 Visual Scene
- AI 语义分镜和沿用 TTS Segment 两种模式
- Local / Cloud / Hybrid LLM 路由
- Local Qwen llama.cpp Provider 与 DeepSeek BYOK Provider
- 结构化 Storyboard：Visual Type、推荐来源、视觉摘要、查询词、Entity、Location、Mood、Fact Risk、Image Prompt、Negative Prompt
- Scene 手工编辑、保存、单 Scene 重新生成
- `locked_text`、`locked_audio`、`locked_visual`
- Scene Version、Revision History 和历史版本恢复
- Scene 修改后局部产物失效，避免整片全部重做

### Local Asset 与 Visual Matching

已实现基础版本：

- 扫描项目配置的本地图片和视频目录
- FFprobe 读取时长、分辨率、编码等信息
- SHA-256 去重
- MediaFile、MediaShot、SceneCandidate、SceneAssignment 数据模型
- 使用文件名、描述、标签和 Scene Query 进行候选匹配
- 技术质量评分、重复使用惩罚、候选排序
- 手动选择本地素材
- AI 图片与本地横屏素材混合分配
- Scene 内多 Shot、Trim、Playback Speed 和显示时长

高级视觉管线已经接入正式项目 Workflow：

- `auto`：运行 BGE-M3、Local Qwen、FLUX / ComfyUI 和 Qwen3-VL；可选组件未就绪时记录报告并回退到 SDXL
- `advanced`：高级视觉管线失败时让持久化 Job 明确失败
- `basic`：只使用基础 SDXL 管线
- 高级 Visual Plan 会回写正式 VisualScene Storyboard；Qwen3-VL 通过的 FLUX 图片会注册为 GeneratedImageVariant、MediaFile 和 MediaShot
- 新增独立 `anime_full_coverage` 画面生成策略：逐字稿按 8~15 秒语义主场景全片覆盖，跳过重点视觉模式的候选阈值、10 秒抑制和每分钟数量上限；统一注入原创二维动漫 Style Prompt，并为后续 3~6 秒取景/运动变化保留 Motion Prompt。高级管线不可用时，未锁定 Scene 仍使用相同动漫风格回退到本地 SDXL。
- 视觉生成策略已经统一到可注册的 Strategy Registry；后端提供策略能力元数据，前端按视频模式动态显示兼容策略。动漫策略保留正式 VisualScene 作为父级，对超长 Scene 按字幕边界派生稳定 Visual Beat，并生成 Scene 内连续多镜头 Assignment。
- 动漫 Style Prompt 在生成时动态组合，不永久覆盖基础 Storyboard；视觉策略切换会失效未锁定 Scene 的旧图片变体，高级管线固定复用每 Scene 的 `variant_index=0` 槽位，避免历史图片误复用和唯一索引冲突。

部分实现：`MediaKeyframe` 表已存在，但本地视频的关键帧提取、镜头切分和 AI Caption 尚未完成；本地素材候选匹配仍需继续统一到 BGE-M3 Embedding。

### Image Generation

已实现：

- Provider Registry 中的本地 SDXL Image Provider
- Prompt、Negative Prompt、Seed、Width、Height、Steps、Guidance Scale
- 每 Scene 多候选图片
- GeneratedImageVariant、输入签名、模型信息、耗时和错误记录
- Scene 级重生成、未变化输入复用
- CUDA OOM 后降低分辨率重试
- 生成图片注册为 MediaFile / MediaShot 并进入 SceneAssignment

已实现补充：FLUX / ComfyUI 已通过高级视觉桥接进入正式项目 Workflow，并由 Qwen3-VL 做生成结果筛选。

明确范围：图片生成只支持本地 Provider。OpenAI Image、Gemini Image 等 Cloud Image Provider、Upscale Provider 和图片费用统计不属于产品计划。Reference Image、ControlNet、LoRA 仍是可选的本地后续能力。

### 剪辑工程编排与 PRPROJ 导出

产品不提供 Timeline 内容编辑，不建设 NLE、可拖拽多轨编辑器、关键帧编辑、Timeline Undo / Redo、BGM / Overlay / Text Track 编辑器。

内部允许保留只读的 SceneAssignment、时间范围、素材顺序、Trim、Playback Speed 等编排数据，因为生成 PRPROJ 必须把旁白、字幕和素材放到确定位置；这些内部数据不是用户可编辑的 Timeline 产品功能。

主工作流在素材完成后直接进入 `project_export`，通过 Premiere Pro 将中间交换格式转换为真实 `.prproj`。禁止把 XML 改后缀伪装成 PRPROJ。工程使用绝对路径链接素材，移动项目后可能需要在剪辑软件中重新链接。

目标交付软件是支持 PR 工程导入的剪映专业版；不同剪映版本兼容能力可能不同，必须同时保留 WAV、SRT 和素材作为回退交付物。

### FFmpeg / Preview / Render

已实现：

- FFmpeg 和 ffprobe 集中封装，UI 不直接拼接命令
- Windows FFmpeg 自动下载、SHA-256 校验和本地安装
- NVENC / QSV / AMF 探测，并实际验证编码器能否打开设备
- 硬件编码失败后回退到 libx264
- Scene Preview 与内部媒体验证
- 历史底层 Scene Render、Visual Track、Rough Cut 和 Final Render 服务代码暂作兼容实现；对应 Timeline 编辑器、项目级 Render API 和 Job 已移除
- 主项目不再以最终 MP4 为默认交付物
- Render Signature Cache 和未变化产物复用
- 原子输出与渲染后时长验证

### Quality Control

现有能力：

- Qwen3-VL 对高级管线生成图片的语义与瑕疵筛选
- 工程交付型 QA Job / API：检查 PRPROJ、WAV、SRT 文件及 SRT 与字幕时间线一致性、Scene 时间轴与素材覆盖、关联素材文件存在性和绝对路径重链接风险
- 主工作流在 PRPROJ 导出后进入独立 `delivery_quality_check` Step；Project Workspace 显示错误、提醒、文件路径和处理建议，支持定位 Scene、显示 SRT 全局条目序号与时间、手动复检
- 交付 QC 只读检查已保存的镜头范围，不重排或写回 SceneAssignment；读取报告时检查交付文件、素材和项目编排是否变化，过期报告不再显示为通过
- PRPROJ 转换报告记录导出 ID、Premiere 执行结果及 PRPROJ / 源 XML SHA-256；交付 QC 会核对证据链，且 QC 执行异常不会抹去已经成功生成的 PRPROJ
- QC 报告使用版本化强类型契约，区分自动技术验证与人工验收；通过 API 可记录 Premiere / 目标剪辑软件的人工打开验收，文件或项目编排变化后会自动失效
- 旧渲染链路中的视频和 Scene Render 技术检查服务仍作为兼容代码保留，不再是主交付 QC 的必需项
- 素材来源元数据完整性
- 重复素材
- 字幕重叠、持续时间、字符数和 CPS
- 旧渲染链路中的视频分辨率、Codec、Sample Aspect Ratio、黑帧和冻结帧检查代码
- 音频响度、削波和过长静音
- 原子写入质量报告

部分实现或待迁移：

- 当前 QC 仅检查文件与数据库编排的一致性，尚未通过重新打开 PRPROJ 验证 Premiere / 剪映实际轨道和链接状态
- QC 问题面板可定位 Scene，并显示字幕在 SRT 中的条目序号与时间；尚无 Cue 级编辑界面
- 尚无 Overall Score、Visual Diversity、Scene Matching 等统一维度分数
- 尚无 Visual 与 Text 的语义相关度检查
- 尚无连续同类画面、同人物、同构图、AI 视觉比例等高级内容检查
- 尚无正式的长视频实机 Golden Test 结果；自动核验脚本不能替代 Premiere / 目标剪映的人工导入验收

### Batch 与兼容工具

已实现：

- 一次导入最多 100 个 TXT / Markdown 脚本创建批次
- Batch Start、Pause、Continue、失败项目 Retry
- 单个项目失败后继续执行
- 批次和项目级进度、状态及耗时
- 独立本地视频拼接工具
- 独立数字人合成工具及其任务恢复
- FCPXML、Premiere XML 和 PRPROJ 导出

数字人不属于 V1 优先功能；除非有明确用户需求，后续 Agent 不应继续扩大数字人范围。

### Settings / Security / Infrastructure

已实现：

- 基础与存储、AI 服务、TTS、字幕、图片、渲染、转场、诊断设置页
- 工作目录、模型路径、FFmpeg 路径和 Provider 配置
- CPU、RAM、GPU、VRAM、CUDA、FFmpeg 和硬件编码器检测
- LLM Model Manager 的下载、暂停、继续、校验和状态恢复
- Windows DPAPI Secret Store；SQLite 只保存 Credential ID
- 启动时迁移历史明文 Secret
- Task 配置快照自动排除 API Key、Token、Secret 和 Password
- 自动清理完成任务产物的调度器
- 原子文件、日志、诊断报告和数据库迁移备份

部分实现：Model Manager 当前主要管理 LLM，不是统一的 TTS / STT / Image / Vision Model Manager。

## 0.3 明确尚未实现的产品模块

以下内容不要误判为已有功能：

- Tauri / Electron Desktop Shell
- 正式 Windows EXE Installer、Auto Updater 和 Code Signing 流程
- Account、Login、License、Device Activation、Signed License、Offline Lease、Grace Period
- License Server、Version API、Payment Webhook
- Stable / Beta / Dev Release Channel
- Desktop / Engine / Model 独立更新和兼容矩阵
- 每项目独立 `project.db`
- Channel Profile / Style Bible / Workflow Preset
- Project Cost、LLM Token、TTS 字符和 AI Video 费用统计
- Cloud TTS Provider
- AI Video Provider 及异步轮询
- Pexels / Pixabay / Storyblocks / Envato 等 Stock Provider
- 主应用内完整的关键帧提取、镜头切分、AI Caption 和 Embedding 素材搜索
- Visual Diversity 滚动窗口和 Channel Visual Ratio 规划
- Chart、Map、Timeline、Quote Card、Text Card、Diagram 的正式生成与渲染器
- Render Preset、Thumbnail Profile 和 Thumbnail Workflow
- Project Backup / Restore 用户流程
- Plugin System / Plugin Market
- Telemetry 和 Crash Report 上传体系
- YouTube SEO、Upload、Social Scheduling
- macOS、Mobile、Cloud Project Sync、多人协作

## 0.4 当前最重要的技术债务

1. 高级视觉能力已经通过桥接服务进入主 Workflow，但仍需把 CLI 的 Artifact/Generation History 完全统一到主应用数据库，消除剩余双存储。
2. 全局 SQLite 仍是权威数据库，项目工程尚未拥有版本化 `project.db`。
3. Project、Scene 和 Asset 的部分核心字段仍保存在 `config_json`、`storyboard_json`、`metadata_json` 中。
4. Frontend 自动化测试只有 5 项，Project Workspace、Batch、Settings、Scene 和工程导出缺少 UI / E2E 测试。
5. 现有长视频测试和交付核验脚本不能代表真实 20~60 分钟本地模型生产及目标剪辑软件导入验收。
6. Error Code 已有基础，但部分服务仍直接返回异常文本，尚未完成全覆盖。
7. 高级视觉模型的下载、启动和串行 GPU 调度主要依赖脚本，尚未形成统一 Model Manager 和 UI。

## 0.5 后续 Agent 的读取与更新规则

后续 Agent 应遵守：

1. 需求分析时先阅读本节，不要为了重复制作功能清单而执行全仓库扫描。
2. 只读取当前任务直接相关的 API、Service、Model、Workflow 和 Test 文件。
3. “已实现”表示存在主应用代码和测试，不表示所有真实本地模型都已在目标硬件完成验收。
4. 独立 CLI 中存在、但没有接入 FastAPI 项目 Workflow 的能力，只能标记为“部分实现”。
5. 新增或完成一个产品模块时，必须同步修改本节对应状态。
6. 删除、替换或降级既有能力时，也必须同步修改本节，不能让本节继续宣称已经实现。

## 0.6 已确认的产品范围决策（2026-09-13）

以下决策优先于后文仍可能存在的历史性建议：

1. Script Engine 只接收 TXT / Markdown 完整逐字稿；不开发 Word、PDF、Podcast、已有音频统一导入器，也不开发章节编辑或章节审核界面。
2. 保留 BGE-M3、Local Qwen、FLUX / ComfyUI、Qwen3-VL 高级视觉管线，并持续把它统一进项目 Workflow、Provider、Artifact 和 Job 体系。
3. Image Generation 只做本地 Provider；不开发 OpenAI Image、Gemini Image 等 Cloud Image Provider，不开发 Upscale Provider，不统计图片生成费用。
4. TubeAiFolw 不提供 Timeline 内容编辑。SceneAssignment 等时间信息只能作为自动编排和工程导出的内部数据。
5. 主交付物是带旁白、字幕和素材链接的真实 `.prproj` 工程，供支持 PR 工程导入的剪映专业版继续深度剪辑；同时保留 WAV、SRT 和素材回退文件。
6. 真实 PRPROJ 必须由 Adobe Premiere Pro 转换生成；禁止把 XML 或 JSON 简单改名为 `.prproj`。

---

# 1. 项目愿景

TubeAiFolw 的目标是成为一个：

**Creator Production OS / AI Long-form Video Production Engine**

用户最终可以从以下任意输入开始：

- 完整逐字稿
- Markdown
- TXT
- 视频脚本
- 分章节脚本
- 已有项目模板

经过自动化生产流程，得到：

- 完整 TTS 音频
- 精确字幕
- Scene / Shot 分镜
- 视觉素材清单
- AI 插图
- AI 视频片段
- 本地素材匹配结果
- 图表 / 地图 / 时间线 / 文字卡
- 带素材链接的真实 `.prproj` 剪辑工程
- WAV、SRT、素材清单和可重链接的项目中间文件
- 质量检查报告
- 可继续编辑和重新生成的工程文件

最终用户不应该被迫在多个独立工具之间手工复制：

```text
ChatGPT
↓
ElevenLabs
↓
Whisper
↓
Midjourney
↓
Runway
↓
Premiere
↓
FFmpeg
```

TubeAiFolw 负责将这些能力统一成一个完整生产工作流。

---

# 2. 非目标

当前阶段不要把项目做成以下产品：

- 不做通用视频剪辑器
- 不做 Premiere / DaVinci / CapCut 替代品
- 不做通用 TTS 平台
- 不做通用 AI 图片平台
- 不做通用 AI 视频平台
- 不做“输入一句话自动生成 100 条垃圾视频”的工具
- 不做纯云端 SaaS 渲染平台
- 不承担用户大规模 GPU 推理成本
- 不追求支持所有操作系统
- 不优先支持移动端
- 不把“支持最多模型”作为第一竞争力
- 不允许项目演变成大量无法维护的 Provider 特殊逻辑
- 不允许业务逻辑大量耦合 UI
- 不允许 FFmpeg 命令散落在各个页面组件
- 不允许 Python AI 逻辑直接侵入 Desktop UI 层
- 不允许数据库 Schema 无迁移机制地随意修改

---

# 3. 目标用户

优先服务以下用户：

## 3.1 核心用户

- YouTube 长视频创作者
- Faceless YouTube 创作者
- Documentary / Essay 类创作者
- 历史频道
- 财经频道
- 心理频道
- 教育频道
- 科普频道
- Storytelling 频道
- 商业人物频道
- 纪录片型频道
- Podcast 视频化用户
- 多频道运营者
- 小型 MCN
- 视频代运营团队
- AI 视频工作室

## 3.2 不优先用户

- 仅偶尔生成短视频的普通用户
- 纯娱乐型 AI 绘图用户
- 只需要简单字幕导出的用户
- 完全没有内容生产经验、需要大量人工客服的小白
- 只希望“一键上传到 YouTube 并自动赚钱”的用户

---

# 4. 核心商业定位

TubeAiFolw 的付费价值应围绕：

- 节省长视频生产时间
- 降低重复劳动
- 提高画面与内容匹配度
- 降低视频重复和模板化风险
- 提高批量生产稳定性
- 支持本地模型
- 支持 BYOK
- 降低云端使用成本
- 降低创作者多工具切换成本
- 支持失败恢复
- 支持 Scene 级重新生成
- 支持频道风格复用
- 支持质量检查

不要以以下卖点作为核心：

- “我们也支持 TTS”
- “我们也能调用 GPT”
- “我们也能生成图片”
- “我们也能 FFmpeg 合并”
- “支持 30 个模型”
- “一天生成 1000 个视频”

---

# 5. 产品原则

所有新功能实现前必须判断是否符合以下原则。

## 5.1 Local-first

优先本地处理：

- TTS
- STT
- 字幕对齐
- FFmpeg
- 本地图片模型
- 本地 OCR（非核心）
- 本地视频处理
- 本地缓存
- 本地项目文件
- 本地素材库
- 本地日志
- 本地 SQLite

除非功能必须依赖云端，否则不要把用户内容上传到 TubeAiFolw 自有服务器。

## 5.2 BYOK

第三方 API 默认由用户自行配置：

- OpenAI
- Anthropic
- Gemini
- ElevenLabs
- Runway
- Kling
- Seedance
- 其他图片 / 视频 / TTS Provider

TubeAiFolw 只负责编排。

## 5.3 Provider 可替换

所有外部模型和平台必须通过统一 Adapter / Provider Interface 接入。

禁止在业务层出现：

```ts
if (provider === "elevenlabs") {
   ...
}
```

应改为：

```ts
const provider = providerRegistry.get(providerId)
await provider.generate(...)
```

## 5.4 Scene-first

TubeAiFolw 最重要的数据单位不是文件，而是：

**Scene**

一个 Scene 应至少能够承载：

- 文本
- 开始时间
- 结束时间
- 音频
- 字幕
- 画面类型
- 画面 Prompt
- 素材引用
- AI 图片
- AI 视频
- Motion
- Transition
- Duration
- Voice
- 状态
- 生成日志
- 失败原因
- 质量评分

## 5.5 可恢复

任何耗时任务必须：

- 支持状态持久化
- 支持失败重试
- 支持断点续跑
- 支持单个 Scene 重跑
- 支持跳过完成步骤
- 支持取消
- 支持暂停
- 支持重启应用后恢复状态

## 5.6 人类可干预

最终产品不是黑盒“一键生成”。

必须允许用户：

- 编辑 Scene
- 调整分镜
- 修改 Prompt
- 替换图片
- 替换素材
- 重新生成 TTS
- 重新生成单个 Scene
- 修改 Voice
- 调整镜头时长
- 修改 Transition
- 禁用某类画面
- 手动锁定结果
- 标记“不允许自动覆盖”

---

# 6. 总体架构

推荐架构：

```text
┌─────────────────────────────┐
│        TubeAiFolw Desktop   │
│        React + Tauri        │
│     或 React + Electron     │
└──────────────┬──────────────┘
               │ IPC / localhost
               ▼
┌─────────────────────────────┐
│       TubeAiFolw Engine     │
│           Python            │
│                             │
│ Workflow / AI / FFmpeg      │
└──────────────┬──────────────┘
               │
      ┌────────┼─────────┐
      ▼        ▼         ▼
   Local AI  FFmpeg   External API
               │
               ▼
         Project Output
```

云端：

```text
┌─────────────────────────────┐
│      TubeAiFolw Cloud       │
│                             │
│ Account                     │
│ License                     │
│ Device                      │
│ Version                     │
│ Payment Webhook             │
│ Download Metadata           │
└─────────────────────────────┘
```

云端绝对不要承担：

- 大规模视频存储
- 大规模视频渲染
- 用户视频备份
- AI GPU 推理
- 项目实时同步

除非未来商业模式发生明确变化。

---

# 7. 推荐技术栈

## 7.1 Desktop

优先：

```text
React
TypeScript
Tauri
```

如果现有开发效率明显更高，也允许：

```text
React
TypeScript
Electron
```

原则：

- 不为了技术洁癖重写
- 一人团队优先开发效率
- Desktop UI 不承担 AI 逻辑
- Desktop UI 不直接运行复杂 FFmpeg 命令

## 7.2 Engine

```text
Python 3.11+
FastAPI / IPC Server
Pydantic
SQLAlchemy 可选
FFmpeg
PyTorch
```

Engine 可作为：

- Localhost Service
- Child Process
- IPC Process

优先选择便于调试和解耦的方案。

## 7.3 本地数据库

```text
SQLite
```

用途：

- 项目元数据
- Scene
- Job
- Asset
- Provider 配置引用
- Project Setting
- 任务状态
- 生成历史
- 质量检查结果

## 7.4 云端

可选：

```text
Cloudflare Workers
+
D1
```

或：

```text
Node.js / TypeScript
+
PostgreSQL
```

原则：

- 简单
- 低成本
- 无 GPU
- 无复杂微服务

## 7.5 下载与 CDN

推荐：

```text
Cloudflare R2
+
Cloudflare CDN
```

可替代：

- AWS S3
- Backblaze B2
- GitHub Releases（开发期）
- 国内 OSS（如后续需要）

---

# 8. 推荐仓库结构

建议 Monorepo：

```text
TubeAiFolw/
│
├─ AGENTS.md
├─ README.md
├─ LICENSE
├─ package.json
├─ pnpm-workspace.yaml
├─ .github/
│  └─ workflows/
│
├─ apps/
│  ├─ desktop/
│  │  ├─ src/
│  │  ├─ src-tauri/
│  │  └─ tests/
│  │
│  └─ website/
│
├─ engine/
│  ├─ tubeaifolw/
│  │  ├─ api/
│  │  ├─ core/
│  │  ├─ workflow/
│  │  ├─ providers/
│  │  ├─ media/
│  │  ├─ subtitle/
│  │  ├─ tts/
│  │  ├─ stt/
│  │  ├─ storyboard/
│  │  ├─ visual/
│  │  ├─ render/
│  │  ├─ quality/
│  │  ├─ storage/
│  │  └─ utils/
│  ├─ tests/
│  └─ pyproject.toml
│
├─ packages/
│  ├─ shared-types/
│  ├─ ui/
│  ├─ sdk/
│  └─ license-client/
│
├─ cloud/
│  ├─ license-api/
│  └─ version-api/
│
├─ installer/
│
├─ scripts/
│
├─ docs/
│  ├─ architecture/
│  ├─ providers/
│  ├─ database/
│  └─ release/
│
└─ migrations/
```

---

# 9. 项目工程文件

每一个视频项目必须拥有独立目录。

推荐：

```text
project-name/
│
├─ project.json
├─ project.db
│
├─ input/
│  ├─ script.md
│  └─ source/
│
├─ audio/
│  ├─ segments/
│  └─ final.wav
│
├─ subtitle/
│  ├─ final.srt
│  └─ alignment.json
│
├─ scenes/
│  ├─ scene_0001/
│  ├─ scene_0002/
│  └─ ...
│
├─ assets/
│  ├─ local/
│  ├─ stock/
│  ├─ generated/
│  └─ imported/
│
├─ cache/
│
├─ renders/
│  ├─ preview/
│  └─ final/
│
├─ logs/
│
└─ exports/
```

用户可自定义项目根目录。

不要强制所有视频数据保存在：

```text
C:\Users\xxx\AppData
```

AppData 仅保存：

- 应用配置
- License
- 登录信息
- 全局数据库
- 日志
- UI 配置

---

# 10. 核心数据模型

## 10.1 Project

字段建议：

```ts
interface Project {
  id: string
  name: string
  createdAt: string
  updatedAt: string
  status: ProjectStatus
  rootPath: string

  sourceLanguage: string
  targetLanguage?: string

  scriptPath?: string
  audioPath?: string
  subtitlePath?: string

  channelProfileId?: string
  workflowPresetId?: string

  fps: number
  width: number
  height: number
  aspectRatio: string

  durationMs?: number

  locked: boolean
}
```

## 10.2 Scene

Scene 是核心对象。

```ts
interface Scene {
  id: string
  projectId: string
  index: number

  title?: string

  text: string
  normalizedText?: string

  startMs?: number
  endMs?: number
  durationMs?: number

  audioAssetId?: string
  subtitleSegmentIds: string[]

  visualType?: VisualType
  visualIntent?: string
  visualPrompt?: string
  negativePrompt?: string

  assetIds: string[]

  motion?: MotionConfig
  transitionIn?: TransitionConfig
  transitionOut?: TransitionConfig

  providerId?: string
  modelId?: string

  state: SceneState

  lockedText: boolean
  lockedAudio: boolean
  lockedVisual: boolean

  qualityScore?: number

  createdAt: string
  updatedAt: string
}
```

## 10.3 Asset

```ts
interface Asset {
  id: string
  projectId: string

  type:
    | "audio"
    | "image"
    | "video"
    | "subtitle"
    | "document"
    | "chart"
    | "map"
    | "screenshot"

  source:
    | "local"
    | "generated"
    | "stock"
    | "api"
    | "imported"

  path: string

  hash?: string

  durationMs?: number
  width?: number
  height?: number

  providerId?: string
  prompt?: string

  metadata?: Record<string, unknown>
}
```

## 10.4 Job

```ts
interface Job {
  id: string
  projectId: string
  sceneId?: string

  type: JobType

  state:
    | "queued"
    | "running"
    | "paused"
    | "success"
    | "failed"
    | "cancelled"

  progress: number

  retryCount: number
  maxRetries: number

  errorCode?: string
  errorMessage?: string

  createdAt: string
  startedAt?: string
  finishedAt?: string
}
```

---

# 11. 工作流引擎

TubeAiFolw 必须拥有独立 Workflow Engine。

不要把工作流写死在 UI 点击事件中。

推荐：

```text
Workflow
│
├─ Step
├─ Dependency
├─ Condition
├─ Retry
├─ Cache
├─ Artifact
└─ State
```

示例：

```text
Import Script
↓
Normalize Script
↓
Semantic Chunk
↓
Generate TTS
↓
Merge Audio
↓
Align Subtitle
↓
Scene Planning
↓
Visual Planning
↓
Generate / Match Assets
↓
Project Assembly
↓
Quality Check
↓
PRPROJ Export
```

每一步必须：

- 可单独运行
- 可重新运行
- 有输入
- 有输出
- 有状态
- 有日志
- 有错误信息
- 可缓存
- 可判断是否跳过

建议抽象：

```python
class WorkflowStep:
    id: str

    async def can_run(self, context): ...
    async def run(self, context): ...
    async def validate(self, result): ...
    async def rollback(self, context): ...
```

---

# 12. Script Engine

Script Engine 负责：

- 导入
- 清洗
- 规范化
- 分段
- 章节识别
- 语义分析
- 实体识别
- 时间节点识别
- 人物识别
- 地点识别
- 数据识别
- 引用识别
- 重要性评分
- 视觉机会识别

输出不是简单的文本数组。

应输出结构化语义信息，例如：

```json
{
  "text": "In 2008 Lehman Brothers collapsed...",
  "entities": [
    {
      "type": "organization",
      "value": "Lehman Brothers"
    }
  ],
  "event": {
    "type": "historical_event",
    "year": 2008
  },
  "visualOpportunities": [
    "archive",
    "building",
    "newspaper",
    "timeline"
  ]
}
```

---

# 13. TTS Engine

TTS 必须通过 Provider 抽象。

统一接口示例：

```python
class TTSProvider:
    async def list_voices(self): ...
    async def synthesize(self, request): ...
    async def estimate_cost(self, request): ...
    async def health_check(self): ...
```

支持两类：

## 13.1 Local TTS

可接入：

- IndexTTS
- CosyVoice
- MOSS TTS
- 其他本地模型

## 13.2 Cloud TTS

可接入：

- ElevenLabs
- OpenAI
- Azure TTS
- Google TTS
- 其他

TTS 功能必须支持：

- 长文本智能切段
- 语义断句
- 最短文本限制
- 最大文本限制
- Voice Profile
- Speed
- Pitch（如果 Provider 支持）
- Emotion（如果支持）
- Seed（如果支持）
- Retry
- Segment Cache
- 单段重生成
- 音量标准化
- Silence Trim
- 合并
- Segment 时间映射

不得强制采用“一行字幕一段 TTS”。

TTS 切段是为了语音自然度，不是为了字幕长度。

---

# 14. Subtitle / Alignment Engine

字幕必须与 TTS 解耦。

即：

```text
TTS Segment
≠
Subtitle Segment
```

支持：

- Whisper
- Faster-Whisper
- WhisperX
- Forced Alignment
- 原始文稿辅助 Alignment
- Segment 内二次对齐
- SRT
- VTT
- JSON Timeline

目标：

即使一个 TTS Segment 长达：

- 10 秒
- 30 秒
- 60 秒
- 120 秒

系统仍应能够在 Segment 内生成自然的逐行字幕。

字幕规则应可配置：

- 每行最大字符数
- 每条最大时长
- 每条最小时长
- 标点优先断句
- 语义优先断句
- 单词不切断
- 中英文差异规则
- CPS 字符速度
- 最大行数

---

# 15. Storyboard Engine

Storyboard Engine 是核心能力之一。

输入：

- Script Semantic Result
- Audio Timing
- Subtitle Timing
- Channel Profile
- Visual Strategy

输出：

- Scene
- Shot
- Scene Type
- Visual Intent
- Visual Prompt
- Recommended Source
- Duration
- Transition

不要简单地：

```text
每 5 秒生成一张图
```

应该根据语义节奏决定。

可能画面类型：

```text
REAL_FOOTAGE
STOCK_VIDEO
AI_IMAGE
AI_VIDEO
ARCHIVE
PORTRAIT
DOCUMENT
SCREENSHOT
CHART
MAP
TIMELINE
QUOTE_CARD
TEXT_CARD
DIAGRAM
INFOGRAPHIC
B_ROLL
```

---

# 16. Visual Matching Engine

这是 TubeAiFolw 未来最重要的护城河之一。

输入：

- Scene 语义
- Entity
- Event
- Location
- Person
- Time
- Abstract Concept

输出：

- 视觉策略
- 素材类型
- Prompt
- 搜索关键词
- 优先级

例如：

```text
文本：
“In 2008 Lehman Brothers collapsed.”

分类：
Historical Event

推荐：
1. Archive Footage
2. Lehman Building
3. 2008 Wall Street
4. Newspaper Headline
5. Financial Crisis Timeline

不推荐：
Generic City Skyline
Random Business Office
```

Visual Matching Engine 不应完全依赖一个 LLM Prompt。

应逐渐形成：

- Rule
- Ontology
- Prompt
- Feedback
- Template
- History

混合系统。

---

# 17. Visual Diversity Engine

需要避免长视频中连续出现大量：

- 同类静态图
- 同一个人物
- 同一种构图
- 同一种动画
- 同一种素材
- 同一画面类型

建议维护滚动窗口。

例如：

```text
最近 10 个 Scene
AI_IMAGE = 8

则下一 Scene 优先：
STOCK_VIDEO
CHART
MAP
ARCHIVE
TEXT_CARD
```

可配置 Channel Visual Ratio：

```json
{
  "stockVideo": 0.35,
  "aiImage": 0.25,
  "aiVideo": 0.10,
  "chart": 0.08,
  "map": 0.05,
  "archive": 0.10,
  "textCard": 0.07
}
```

此比例不是硬限制，而是规划参考。

---

# 18. 图片生成

Image Provider 必须统一。

```python
class ImageProvider:
    async def generate(self, request): ...
```

只支持本地 Provider：

- FLUX
- SDXL
- ComfyUI Workflow

支持：

- Prompt
- Negative Prompt
- Seed
- Style
- Aspect Ratio
- Resolution
- Batch Count
- Reference Image
- ControlNet（可选）
- LoRA（可选）

生成图片必须记录：

- Prompt
- Model
- Seed
- Provider
- 生成时间
- 费用
- 文件 Hash

---

# 19. AI 视频生成

Video Provider 通过 Adapter 接入。

可能支持：

- Seedance
- Kling
- Runway
- Veo
- 其他

不要把具体服务写进核心 Workflow。

统一接口：

```python
class VideoGenerationProvider:
    async def generate(self, request): ...
    async def get_status(self, task_id): ...
    async def cancel(self, task_id): ...
    async def estimate_cost(self, request): ...
```

需要兼容：

- 同步 API
- 异步任务 API
- Polling
- Webhook（本地软件不强依赖）
- Task ID
- Retry

---

# 20. Stock / Local Asset Engine

支持本地素材库。

功能：

- 导入目录
- 扫描
- 建索引
- 视频时长读取
- 分辨率读取
- Hash
- 去重
- 标签
- AI Caption
- Embedding
- 语义搜索
- 关键词搜索
- 使用历史
- 重复率控制

未来可扩展：

- Pexels
- Pixabay
- Storyblocks
- Envato
- 用户私有 NAS

不要在没有明确授权和合法来源的情况下自动抓取版权不明的视频。

---

# 21. 关键帧提取

关键帧提取用于：

- 视频理解
- 素材索引
- 相似度分析
- 重复检测
- Visual Matching
- Preview

支持策略：

- 固定时间间隔
- Scene Change Detection
- SSIM
- Histogram
- CLIP Similarity
- I-frame
- 自适应关键帧

不要对所有视频每秒提取大量帧。

应根据任务进行分级。

---

# 22. Project Assembly / PRPROJ Export Engine

TubeAiFolw 不提供 Timeline 内容编辑器，也不建设多轨 NLE、关键帧编辑、拖拽剪辑或 Undo / Redo。

系统只维护生成真实剪辑工程所需的只读编排数据：

- Scene 与旁白、字幕的时间范围
- SceneAssignment 与素材文件引用
- Shot 顺序、源素材入点和出点
- 素材路径、Hash、分辨率、时长和离线状态
- 工程 FPS、画幅、分辨率和声道配置

默认交付流程：

```text
Scene / Asset Assignment
↓
FCPXML Interchange
↓
Adobe Premiere Pro Automation
↓
Real PRPROJ
```

`.prproj` 必须是 Adobe Premiere Pro 可打开的真实工程文件，不能通过修改 XML / JSON 扩展名伪造。目标剪映专业版不支持 PR 工程导入时，用户仍可使用 WAV、SRT 和素材目录手工重建。

---

# 23. Motion Metadata

Motion 只作为 Scene 的自动建议或导出元数据保留，不提供 TubeAiFolw 内的动画、关键帧或效果编辑界面。最终动画由用户在目标剪辑软件中完成。

---

# 24. Transition Metadata

Transition 只作为工程导出时的默认建议保留，不提供 TubeAiFolw 内的转场编辑器。默认使用 Cut；其他转场由用户在目标剪辑软件中完成。

---

# 25. FFmpeg Media Engine

所有 FFmpeg 调用必须集中在 Render Engine。

禁止 UI 页面直接拼接 FFmpeg 命令。

FFmpeg Media Engine 负责：

- Probe
- Decode
- Transcode
- Scale
- Crop
- Pad
- Audio Merge
- 格式兼容性转码
- 素材代理和技术预览
- 导出前媒体校验

主项目 Workflow 不以 FFmpeg Final Render 或最终 MP4 为交付目标。

必须支持硬件编码检测：

- NVENC
- QSV
- AMF

默认根据硬件能力选择。

必须保留软件编码 fallback。

---

# 26. Scene Preview

只保留用于检查单个 Scene 素材的轻量 Preview。项目级 30 / 60 秒时间轴预览、Final Render 和对应 Job / API 不属于产品范围。

---

# 27. Quality Control Engine

TubeAiFolw 必须逐渐建立自动质量检查。

检查项：

## 27.1 视频

- 黑帧
- 冻结帧
- 画面分辨率异常
- 长时间无变化
- 重复素材
- 高相似度素材
- 连续静态图过多
- 连续同类 Visual Type
- 画面比例错误
- Letterbox 异常

## 27.2 音频

- 音量过低
- 音量过高
- Clip
- 静音过长
- TTS 异常
- 音频缺失
- Segment 拼接爆音

## 27.3 字幕

- 字幕超屏
- 字幕持续时间过短
- 字幕持续时间过长
- CPS 过快
- 时间轴重叠
- 字幕断裂
- 文本缺失

## 27.4 内容

- Visual 与 Text 低相关
- 相同画面多次重复
- 同一生成图重复
- 连续镜头变化过慢
- AI 视觉比例过高
- Archive 素材不足
- 图表机会未使用

最终可生成：

```text
Overall Score: 86

Visual Diversity: 82
Audio Quality: 93
Subtitle Quality: 91
Scene Matching: 84
Repetition Risk: Low
```

评分只能作为辅助，不应声明是 YouTube 官方审核结果。

---

# 28. Channel Profile / Style Bible

必须允许为不同频道保存 Profile。

例如：

```json
{
  "name": "Tomorrow Atlas",
  "language": "en-US",
  "voiceProfile": "narrator_01",
  "visualStyle": "cinematic_scifi",
  "subtitleStyle": "minimal_white",
  "shotDuration": {
    "min": 5,
    "max": 12
  },
  "visualRatio": {
    "stockVideo": 0.20,
    "aiImage": 0.30,
    "aiVideo": 0.25,
    "chart": 0.10,
    "map": 0.10,
    "textCard": 0.05
  }
}
```

Channel Profile 可包含：

- 频道名
- 目标语言
- 目标地区
- 旁白声音
- TTS Provider
- 字幕风格
- 字幕语言
- 视觉风格
- Prompt Prefix
- Prompt Negative
- 镜头节奏
- 图表样式
- 地图样式
- Motion
- Transition
- Logo
- Intro
- Outro
- 背景音乐
- 音量
- Thumbnail Profile
- Render Profile

---

# 29. Batch Production

Pro / Studio 需要支持批量。

例如：

```text
Project Queue
│
├─ Video A
├─ Video B
├─ Video C
└─ Video D
```

支持：

- 最大并行任务数
- GPU 队列
- API 并发
- Rate Limit
- 夜间渲染
- 自动重试
- Fail Fast
- Stop After Current
- Resume

Batch 不等于“一键生产垃圾内容”。

仍需质量控制。

---

# 30. Task Queue

Task Queue 是必需基础设施。

任务分类：

```text
CPU
GPU
NETWORK
FFMPEG
API
```

不同类型有独立并发限制。

示例：

```text
GPU Jobs: 1
FFmpeg Jobs: 2
API Jobs: 4
CPU Jobs: 4
```

任务必须持久化。

应用崩溃后：

```text
RUNNING
```

的任务重新标记为：

```text
INTERRUPTED
```

由用户决定：

- Resume
- Retry
- Cancel

---

# 31. Cache

所有昂贵操作尽量缓存。

缓存 Key 应基于：

```text
Input Hash
+
Provider
+
Model
+
Parameters
+
App Engine Version
```

例如：

```text
TTS Cache

hash(
text
+ voice
+ speed
+ provider
+ model
)
```

这样同样的输入不会重复花钱。

---

# 32. 成本统计

BYOK 也应帮助用户统计成本。

记录：

- LLM Token
- TTS 字符数
- 图片数量
- AI 视频秒数
- API 调用
- 估算 USD
- 项目成本

例如：

```text
Project Cost

LLM            $0.13
TTS            $1.25
Image          $0.80
AI Video       $4.50

Total          $6.68
```

Local Model：

```text
Cost: Local
```

不需要虚构 GPU 电费。

---

# 33. Provider Registry

所有 Provider 统一注册。

例如：

```python
provider_registry.register("tts.elevenlabs", provider)
provider_registry.register("tts.indextts", provider)

provider_registry.register("image.flux", provider)
provider_registry.register("image.openai", provider)

provider_registry.register("video.seedance", provider)
```

Provider Metadata：

```json
{
  "id": "tts.elevenlabs",
  "category": "tts",
  "displayName": "ElevenLabs",
  "capabilities": [
    "voice_list",
    "streaming",
    "emotion"
  ]
}
```

---

# 34. Provider Capability

不要假设所有 Provider 功能相同。

通过 Capability 判断。

例如：

```text
supportsSeed
supportsReferenceImage
supportsNegativePrompt
supportsVoiceClone
supportsStreaming
supportsAsyncTask
```

UI 根据 Capability 动态显示。

---

# 35. Model Manager

模型必须与 Desktop 安装包解耦。

功能：

- 查看已安装
- 查看版本
- 下载
- 暂停
- 恢复
- 校验
- 删除
- 移动模型目录
- 查看磁盘占用
- 检查依赖
- 检查 GPU
- 检查 VRAM

模型目录用户可指定：

```text
D:\TubeAiFolw\Models
```

不要固定在系统盘。

模型 Manifest：

```json
{
  "id": "whisper-large-v3",
  "version": "1.0",
  "size": 3100000000,
  "sha256": "...",
  "downloadUrl": "...",
  "requiredVram": 6000
}
```

---

# 36. Hardware Detection

首次启动运行 Hardware Check。

检测：

- OS
- CPU
- RAM
- GPU
- VRAM
- CUDA
- FFmpeg
- NVENC
- 可用磁盘
- Python Engine
- Model Directory

给出：

```text
Recommended
Compatible
Limited
Unsupported
```

不要仅仅因为没有 NVIDIA GPU 就禁止使用。

---

# 37. 设置

Settings 建议分：

## General

- Language
- Theme
- Project Directory
- Temp Directory
- Cache Directory

## Performance

- CPU Threads
- GPU Device
- FFmpeg Encoder
- Parallel Jobs
- VRAM Strategy

## Models

- Model Directory
- Installed Models

## Providers

- LLM
- TTS
- Image
- Video
- Stock

## Account

- Account
- License
- Device

## Update

- Stable
- Beta
- Dev

## Privacy

- Telemetry
- Crash Report

---

# 38. API Key 安全

禁止明文写入：

```text
config.json
settings.json
project.json
SQLite plaintext field
```

Windows 应优先：

- DPAPI
- Windows Credential Manager

只在配置层保存：

```text
credential_id
```

而不是：

```text
api_key
```

日志中必须过滤：

```text
sk-...
Bearer ...
Authorization
Cookie
```

---

# 39. License 架构

商业版本使用：

```text
Account
+
Device Activation
+
Signed License
+
Offline Lease
```

## 39.1 原则

- Private Key 只存在服务器
- Desktop 仅保存 Public Key
- License 使用 Ed25519 签名
- 客户端可离线验证
- 不要求每次启动联网
- 支持设备解绑
- 不追求无法破解
- 重点阻止普通复制滥用

## 39.2 License Payload

示例：

```json
{
  "licenseId": "lic_xxx",
  "userId": "usr_xxx",
  "plan": "pro",
  "licenseType": "perpetual",
  "maintenanceUntil": "2027-08-28",
  "leaseExpiresAt": "2026-09-28",
  "deviceId": "device_xxx",
  "features": [
    "batch",
    "advanced_storyboard",
    "quality_control"
  ]
}
```

## 39.3 Offline Lease

推荐：

```text
Lease = 30 days
```

客户端：

```text
每 7 天尝试刷新
```

如果网络不可用：

- 当前 Lease 未过期 -> 正常使用
- Lease 过期 -> 进入 Grace Period
- Grace Period 过期 -> 限制 Pro 功能

避免服务器短时不可用导致所有客户无法工作。

---

# 40. Device Fingerprint

不能过于严格。

可综合：

- MachineGuid
- 主板
- CPU
- 系统盘

然后 Hash。

云端只存 Hash。

用户应可以在账户页：

```text
Deactivate Device
```

建议：

```text
Creator: 1 device
Pro: 2 devices
Studio: 3~5 devices
```

---

# 41. 商业模式

优先推荐：

**Desktop Perpetual License + 1 Year Updates**

例如：

```text
Free
$0

Creator
$99

Pro
$199

Studio
$499
```

购买后：

- 当前大版本永久使用
- 12 个月免费更新
- 12 个月后旧版本继续使用
- 想继续获取新版本则购买维护期

不要默认：

```text
不续订就软件完全打不开
```

后续可以提供 Subscription，但不应成为唯一方式。

---

# 42. License Server

API：

```text
POST /auth/login
POST /auth/refresh

GET  /license
POST /license/activate
POST /license/refresh
POST /license/deactivate

GET  /devices
DELETE /devices/:id

GET /versions/latest
```

Payment：

```text
POST /payment/webhook
```

数据库：

```text
users
licenses
devices
subscriptions
payments
versions
```

---

# 43. 更新系统

更新拆为：

```text
Desktop
Engine
Models
```

不要把三者绑死。

## 43.1 Desktop Update

Version API：

```json
{
  "version": "1.4.2",
  "channel": "stable",
  "mandatory": false,
  "downloadUrl": "...",
  "sha256": "...",
  "releaseNotes": "..."
}
```

更新：

```text
Check
↓
Download
↓
SHA256
↓
Signature Verify
↓
Install
```

## 43.2 Engine Update

Engine 独立版本：

```text
Desktop: 1.4.2
Engine: 0.9.3
```

需要兼容矩阵。

## 43.3 Model Update

Model Manager 负责。

不要因为 Desktop 更新重新下载 10GB 模型。

---

# 44. Release Channel

必须支持：

```text
stable
beta
dev
```

默认用户：

```text
stable
```

Beta 用户主动选择。

Dev 不对普通客户展示。

---

# 45. 强制更新

仅以下情况：

- 严重安全问题
- License 协议不兼容
- 云端 API 完全不兼容
- 数据破坏 Bug

普通功能更新：

```text
mandatory = false
```

---

# 46. Windows 安装

V1 推荐：

```text
EXE Installer
+
Auto Updater
```

可使用：

- Inno Setup
- NSIS
- WiX

后期：

- MSIX
- Microsoft Store

不是第一优先级。

---

# 47. Code Signing

商业发行版本需要 Code Signing。

所有：

- EXE
- DLL
- Installer
- Updater

应签名。

CI/CD 中统一处理。

---

# 48. CI/CD

目标：

```text
git tag v1.3.0
```

自动：

```text
Lint
↓
Test
↓
Build Desktop
↓
Build Engine
↓
Build Installer
↓
Code Sign
↓
Generate SHA256
↓
Upload CDN
↓
Update Version API
```

不要手动修改生产版本文件。

---

# 49. 数据库迁移

SQLite 必须有 Migration。

禁止：

```text
修改表结构
然后假设用户数据库自动适配
```

每个 Schema 修改：

```text
migration_001
migration_002
migration_003
```

升级前：

- 自动备份
- 执行 Migration
- 验证
- 失败则恢复

---

# 50. 日志

日志级别：

```text
DEBUG
INFO
WARNING
ERROR
CRITICAL
```

记录：

- Job ID
- Project ID
- Scene ID
- Provider
- Model
- Duration
- Error Code

不要记录：

- API Key
- Access Token
- Password
- 完整 License Token

---

# 51. Error Code

所有 Engine 错误应有稳定 Error Code。

例如：

```text
TTS_PROVIDER_UNAVAILABLE
TTS_RATE_LIMIT
MODEL_NOT_INSTALLED
GPU_OUT_OF_MEMORY
FFMPEG_RENDER_FAILED
ASSET_NOT_FOUND
LICENSE_EXPIRED
LICENSE_DEVICE_LIMIT
```

UI 根据 Error Code 展示友好信息。

不要让用户只看到：

```text
Python traceback
```

但 Debug 页面可展示详细 Trace。

---

# 52. Crash Recovery

应用启动时检查：

- 未完成 Job
- 写入中的文件
- 不完整 Render
- 数据库事务
- 临时文件

用户看到：

```text
Previous session did not close normally.

3 interrupted tasks found.

[Resume]
[Review]
[Discard]
```

---

# 53. 临时文件管理

所有临时数据集中：

```text
Temp Directory
```

支持：

- 自动清理
- 手动清理
- 清理超过 N 天缓存
- 保留正在使用文件

不要在各个模块生成随机临时目录无法追踪。

---

# 54. 磁盘空间

执行任务前预估空间。

例如：

```text
Estimated required: 18 GB
Available: 7 GB
```

禁止直接开始渲染然后写满系统盘。

---

# 55. GPU OOM

GPU 任务必须捕获 OOM。

自动策略：

1. 清理缓存
2. 降低 Batch
3. 降低分辨率
4. CPU Offload
5. Retry
6. 提示用户

不得无限重试。

---

# 56. UI 主要页面

V1 建议：

```text
Home
Projects
Project Workspace
Jobs
Models
Providers
Settings
Account
```

Project Workspace：

```text
Script
Audio
Subtitle
Storyboard
Quality
Project Export
```

---

# 57. Project Workspace

推荐布局：

```text
左：
Scene List

中：
Scene / Visual Workspace

右：
Scene Inspector

底：
Jobs / Artifacts
```

Scene Inspector：

- Text
- Timing
- Voice
- Visual Type
- Prompt
- Asset
- Regenerate
- Lock

---

# 58. 生成按钮

不要只有：

```text
Generate Video
```

应该有：

```text
Generate Audio
Generate Subtitle
Generate Storyboard
Generate Visuals
Quality Check
Export PRPROJ
```

同时可以提供：

```text
Run Workflow
```

自动执行完整流程。

---

# 59. Undo / History

至少支持 Scene 编辑 History。

长期建议：

- Undo
- Redo
- Operation Log

AI 重新生成前应保留上一版本。

例如：

```text
scene_001
├─ visual_v1
├─ visual_v2
└─ visual_v3
```

用户可回退。

---

# 60. Lock

锁定机制非常重要。

用户手动确认一个 Scene 后：

```text
lockedVisual = true
```

再次：

```text
Run Workflow
```

不能覆盖。

同理：

- Text Lock
- Audio Lock
- Visual Lock
- Timing Lock

---

# 61. 素材重复检测

素材 Hash：

- 文件 Hash
- Perceptual Hash
- Frame Embedding

用于判断：

- 完全重复
- 高度相似
- 同一个视频不同裁剪

长视频中可设置：

```text
Avoid reuse within 10 minutes
```

---

# 62. YouTube 低质风险辅助

TubeAiFolw 可以提供：

```text
Repetition Risk
Template Risk
Visual Diversity
```

但产品文案必须说明：

- 不是 YouTube 官方检测
- 不保证获利
- 不保证审核通过
- 只作为内容质量辅助

不要宣称：

```text
100% pass monetization
```

---

# 63. Privacy

默认：

```text
Local Processing
```

如果用户调用第三方 Provider：

UI 应明确：

```text
This step will send data to Provider X.
```

可配置：

```text
Never Send Full Script
```

只发送当前 Scene。

---

# 64. Telemetry

默认只收集必要匿名数据。

建议可选：

- App Version
- OS
- Crash
- Feature Usage
- Job Success / Failure

禁止上传：

- Script
- Voice
- Images
- Video
- API Key

用户可关闭。

---

# 65. 插件系统

V1 不一定暴露插件市场。

但内部架构需插件化。

未来可允许：

```text
Provider Plugin
Workflow Plugin
Exporter Plugin
Asset Source Plugin
```

插件必须有明确 API Version。

---

# 66. Export

支持：

- PRPROJ
- SRT
- WAV Audio
- Scene JSON
- 素材清单与重链接信息

内部转换与兼容回退可保留：

- Premiere XML
- Final Cut XML

---

# 67. Render Preset

默认：

```text
YouTube 1080p
1920x1080
30fps
H.264
AAC
```

可选：

- 1080p 60fps
- 1440p
- 4K

不要默认 4K。

---

# 68. Thumbnail

Thumbnail 可作为独立模块。

但不是核心 V1。

未来：

- Thumbnail Prompt
- Thumbnail Image
- Thumbnail Text
- A/B Variants

不要让 Thumbnail 功能拖慢核心视频 Workflow。

---

# 69. SEO / Upload

未来可以支持：

- Title
- Description
- Chapters
- Keywords
- Tags
- Pinned Comment

自动上传 YouTube 不作为 V1 核心。

如果未来支持，必须使用官方 OAuth API。

---

# 70. V1 范围

V1 必须克制。

目标：

**Script → Editable Long-form Video Project**

V1 核心：

- 项目创建
- Script 导入
- TTS
- Audio Merge
- Subtitle Alignment
- Semantic Scene
- Storyboard
- AI Image
- 本地素材
- 高级视觉语义、Caption、Embedding 与 QC
- 素材工程编排
- 真实 PRPROJ 导出
- Scene Regenerate
- Basic Quality Check
- License
- Auto Update

V1 不需要：

- 完整 NLE
- 多人协作
- 云项目同步
- Plugin Market
- 移动端
- macOS
- AI Avatar
- 直播
- Social Scheduling

---

# 71. V2

重点：

- Scene Editor
- Advanced Visual Matching 持续优化
- Stock Integration
- AI Video
- Chart
- Map
- Screenshot
- Batch Projects
- Channel Profile

---

# 72. V3

重点：

- Studio
- 多项目 Queue
- Advanced QC
- Template
- Automation
- Export Integrations
- Plugin SDK
- macOS

---

# 73. Free 工具

官网可逐渐提供免费工具用于 SEO 获客：

- SRT 修复
- SRT 时间偏移
- TXT → SRT
- SRT → TXT
- 音频合并
- 视频合并
- 视频信息读取
- 关键帧提取
- 音频时长分析
- FFmpeg GUI

这些不应破坏 Desktop 主产品定位。

---

# 74. 编码规范 — TypeScript

必须：

- TypeScript Strict
- 避免 any
- 所有跨进程对象有类型
- API Response 有 Schema
- 使用 Zod / Valibot 可选
- UI Component 不承担业务逻辑

推荐：

```text
Component
↓
Hook
↓
Service
↓
IPC Client
```

---

# 75. 编码规范 — Python

必须：

- Type Hint
- Pydantic
- 明确 Exception
- 不使用裸 except
- 不使用大量全局变量
- Provider 无状态或明确状态管理
- Job 可重试
- IO 与业务逻辑分离

推荐：

```python
async def generate(...) -> Result:
```

---

# 76. 函数设计

避免：

```text
process_everything()
```

拆分：

```text
normalize_script
segment_tts
generate_audio
align_subtitle
plan_scene
generate_visual
render_scene
```

每个函数尽量：

- 单职责
- 可测试
- 可重用
- 可缓存

---

# 77. 配置

配置分层：

```text
App Default
↓
User Settings
↓
Channel Profile
↓
Project Settings
↓
Scene Override
```

Scene Override 优先级最高。

---

# 78. 兼容性

所有 Provider 数据必须保存：

```text
provider_id
model_id
model_version
```

不能只保存：

```text
model = "pro"
```

因为 Provider 会变。

---

# 79. Provider 失效

如果第三方 Provider：

- 改 API
- 下线模型
- 限流
- 涨价

不应该导致项目无法打开。

项目应显示：

```text
Provider unavailable.
Select replacement.
```

---

# 80. 测试

至少：

## Unit

- Script
- Segment
- Subtitle
- Project Assembly
- License Verify
- Provider Adapter

## Integration

- TTS → Audio
- Audio → Subtitle
- Scene → Asset
- Scene / Asset → PRPROJ Interchange

## E2E

最少一个：

```text
short_test_script
↓
full workflow
↓
test.mp4
```

---

# 81. Golden Test

维护固定测试项目：

```text
tests/golden/
```

包含：

- 中文
- 英文
- 长句
- 短句
- 数字
- 人名
- 日期

每次核心逻辑变化执行。

---

# 82. FFmpeg Test

必须验证：

- Windows 路径
- 中文路径
- 空格路径
- 特殊字符
- 长路径

禁止假设路径只包含英文。

---

# 83. 性能

长项目不得把所有：

- Frame
- Audio
- Image

加载进内存。

应流式处理。

---

# 84. 大文件

视频文件统一通过 Path 引用。

数据库不存 Blob。

不要 Base64 存视频。

---

# 85. 文件命名

内部文件建议：

```text
scene_0001
scene_0002
```

不要直接使用用户文本作为文件名。

避免：

- 中文非法字符
- Windows 保留字符
- 超长 Path

---

# 86. 原子写入

重要 JSON：

```text
project.json
```

写入使用：

```text
temp
↓
fsync
↓
rename
```

避免崩溃导致项目文件损坏。

---

# 87. Project Backup

自动备份：

```text
.backup/
```

条件：

- Migration
- 大范围 Workflow
- 删除 Scene
- 导入 Project

---

# 88. Version

采用 Semantic Versioning：

```text
MAJOR.MINOR.PATCH
```

例如：

```text
1.3.2
```

Engine 独立版本。

---

# 89. Git

提交消息建议：

```text
feat:
fix:
refactor:
perf:
docs:
test:
build:
chore:
```

禁止一次提交同时：

- 重构
- 功能
- 格式化整个项目

除非必要。

---

# 90. Agent 工作原则

任何编码 Agent 在修改项目前：

1. 先阅读 `AGENTS.md`
2. 阅读相关目录
3. 查找现有实现
4. 不重复造已有模块
5. 不随意替换技术栈
6. 不修改无关代码
7. 不做超范围重构
8. 优先小步提交
9. 保证旧项目兼容
10. 如果修改数据结构，必须考虑 Migration

---

# 91. Agent 新增 Provider 时

必须完成：

1. Provider Interface 实现
2. Metadata
3. Capability
4. Config Schema
5. Error Mapping
6. Cost Estimate
7. Health Check
8. Unit Test
9. Documentation

禁止只在某个页面硬编码 API。

---

# 92. Agent 新增 Workflow Step 时

必须定义：

- Step ID
- Inputs
- Outputs
- Cache Key
- Retry Strategy
- Failure State
- Resume Strategy
- Progress
- Log

---

# 93. Agent 修改 Scene 时

必须检查：

- Project Assembly / Export
- Cache
- Job
- Project Serialization
- Migration
- UI
- Export

Scene 是核心数据结构。

不可轻易修改。

---

# 94. Agent 修改 License 时

严格要求：

- Private Key 不进入客户端
- 不在日志显示 Token
- 不移除签名验证
- 不将 License 逻辑仅放 UI
- Pro Feature 后端 / Engine 也要验证
- Offline Lease 可继续工作

---

# 95. Agent 修改 Update 时

必须：

- SHA256
- 签名验证
- Version Check
- Rollback
- 不自动执行未验证二进制

---

# 96. 安全边界

TubeAiFolw 不应：

- 收集用户密码
- 上传用户脚本
- 上传用户视频
- 私自上传声音
- 存储第三方 API Key 云端
- 自动抓取受版权保护素材
- 绕过平台风控
- 绕过 YouTube 审核
- 伪造原创性

---

# 97. AI 内容透明度

项目应提供：

- AI 生成标记 Metadata
- Provider 记录
- Prompt History

方便用户管理内容来源。

---

# 98. 商业优先级

如果资源有限，优先级：

```text
稳定性
>
可恢复
>
画面匹配
>
工程交付可靠性
>
质量控制
>
批量
>
模型数量
>
炫酷 UI
```

---

# 99. 一人公司原则

因为 TubeAiFolw 预期长期由极小团队维护，所以所有功能要考虑：

- 客服成本
- 服务器成本
- Bug 成本
- 依赖成本
- Provider 变更成本
- Windows 兼容成本

避免：

- 微服务过多
- 数据库过多
- 运行时过多
- 独立后台服务过多
- 自建 GPU 集群
- 自建视频 CDN
- 自建云盘
- 复杂多人权限系统

---

# 100. 产品最终目标

TubeAiFolw 最终应该做到：

```text
Script
↓
Semantic Analysis
↓
Voice
↓
Subtitle
↓
Storyboard
↓
Visual Planning
↓
Asset Generation
↓
Quality Check
↓
Project Assembly
↓
PRPROJ Export
```

同时保留：

```text
Human Review
```

即：

**AI 执行生产流程，人负责判断和确认。**

---

# 101. 核心护城河

长期重点投入：

## 第一层

```text
Workflow Engine
```

## 第二层

```text
Project Assembly / Reliable PRPROJ Delivery
```

## 第三层

```text
Script → Visual Matching
```

## 第四层

```text
Visual Diversity
```

## 第五层

```text
Quality Control
```

模型本身不是核心护城河。

---

# 102. 项目质量标准

一个功能只有满足以下条件才能视为完成：

- UI 可操作
- Engine 可运行
- 状态可保存
- 异常有提示
- 任务可重试
- 日志可定位
- 有测试
- 不破坏旧项目
- 不泄漏 API Key
- 不阻塞主 UI
- 能取消耗时任务
- 支持 Windows 路径
- README / Docs 有必要说明

---

# 103. V1 成功标准

V1 不以功能数量判断。

成功标准：

用户能将：

```text
20~30 分钟逐字稿
```

稳定完成：

```text
TTS
字幕
Scene
插图
素材
工程编排
PRPROJ
```

且：

- 中途失败可以恢复
- 单 Scene 可以重做
- 不需要人工重新从头运行
- 项目重启后可以继续
- 真实 PRPROJ 可在兼容的目标剪辑软件中打开，旁白、字幕和素材能够定位或重链接

---

# 104. 后续可探索模块

在核心稳定后才考虑：

- 自动 Chart
- 自动 Map
- Browser Screenshot
- Web Research
- Archive Search
- AI Music
- Thumbnail
- SEO
- Upload
- Analytics
- Content Planner
- Team Collaboration
- Cloud Sync

---

# 105. 产品命名约束

项目正式名称：

```text
TubeAiFolw
```

代码中：

```text
tubeaifolw
```

包名可使用：

```text
com.tubeaifolw.desktop
```

不要擅自改成：

```text
TubeAIFlow
TubeAiFlow
TubeFlow
```

除非产品负责人明确决定改名。

---

# 106. 建议初始 Milestone

## Milestone 1 — Core Project

- Desktop
- Engine IPC
- SQLite
- Project
- Scene
- Job

## Milestone 2 — Audio

- TTS Provider
- Audio Segment
- Merge
- Voice Profile

## Milestone 3 — Subtitle

- Whisper
- Alignment
- SRT

## Milestone 4 — Storyboard

- Semantic
- Scene
- Visual Type

## Milestone 5 — Visual

- Local Asset
- AI Image
- Prompt

## Milestone 6 — Project Assembly

- Scene / Asset Placement
- Audio / Subtitle Linking
- Relink Metadata

## Milestone 7 — PRPROJ Export

- FCPXML / Premiere XML Interchange
- Premiere Automation
- Real PRPROJ Verification

## Milestone 8 — QC

- Visual
- Audio
- Subtitle

## Milestone 9 — Commercial

- Login
- License
- Device
- Update
- Installer

---

# 107. 第一版建议不做的功能

Agent 如果没有明确任务，不要主动增加：

- Docker
- Kubernetes
- Redis
- Kafka
- RabbitMQ
- Microservices
- GraphQL
- Elasticsearch
- WebRTC
- Electron + Tauri 双客户端
- 多数据库
- 多云部署
- 自建 OAuth Provider

这些对一人公司早期没有必要。

---

# 108. 实现哲学

当两种方案都能满足需求：

优先：

```text
简单
稳定
可测试
可恢复
少依赖
低维护
```

而不是：

```text
最新
复杂
最炫
最抽象
```

---

# 109. 最后的 Agent 指令

当你作为 Coding Agent 参与 TubeAiFolw：

请始终记住：

这不是一个 Demo。

这不是一个 Hackathon 项目。

这是一个准备长期维护、商业化并由极小团队运营的 Windows AI 视频生产软件。

任何代码都应该尽量：

- 可维护
- 可恢复
- 可替换
- 可测试
- 可升级
- 可商业化

如果某项修改能让 Demo 更漂亮，但增加未来维护成本，应优先拒绝。

如果某项修改能降低用户 30 分钟长视频生产过程中的失败率、重复劳动或等待时间，应优先考虑。

TubeAiFolw 的最终竞争力不是“它用了什么最新模型”，而是：

> **它能不能稳定地把一个复杂的长视频，从脚本真正生产成成品。**
