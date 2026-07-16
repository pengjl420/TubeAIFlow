# AGENTS.md

本文件用于约束本项目中的 AI 编码助手、开发者与自动化代理的行为。项目目标是构建一个本地 Web App，根据原始逐字稿与 TTS 参考音频，自动完成配音、字幕、视觉分镜、素材检索与最终视频合成。

当前规划采用“模块化单体 + 显式工作流编排”。配音字幕是稳定基础能力，视频合成是在其时间轴之上扩展的项目级能力。系统不依赖剪映，必须能够独立输出完整 MP4；剪映仅可作为后续可选导出或人工精修目标。

---

## 1. 项目定位

本项目是一个本地运行的视频生产辅助工具，面向人物纪录片、商业人物故事、中国企业史、历史故事以及社会经济事件解说等中长视频内容。

系统核心路线为：

```text
本地素材库
+ Pexels / Pixabay
+ 多模态检索与结构化元数据
+ 主题化兜底素材
+ FFmpeg 合成
```

核心输入与输出如下：

输入：

- 原始逐字稿文本
- TTS 参考音频
- 基础生成配置，例如项目名称、音色配置、字幕样式、输出目录
- 本地素材库与可选在线素材源
- 视频尺寸、画面节奏、素材偏好、渲染与质量检查配置

输出：

- 分段配音音频
- 完整配音文件，优先输出 WAV，可选输出 MP3
- 中文字幕 ASS 文件
- 英文字幕 ASS 文件
- 时间轴 JSON
- 分段信息 JSON
- 项目 Manifest 文件
- 视觉语义段与结构化分镜 JSON
- 素材候选、最终素材选择和来源清单
- 场景级中间视频
- 故事板预览与质量检查报告
- 合成后的预览视频与最终 MP4

核心流程：

```text
逐字稿
→ 文本清洗
→ 自动切段
→ 默认使用 Qwen3-TTS 批量生成分段音频
→ 音频后处理
→ 拼接完整配音
→ 读取每段音频时长
→ 生成时间轴
→ 生成中文字幕 ASS
→ 翻译英文字幕
→ 生成英文 ASS
→ 将字幕合并为视觉语义段
→ 生成结构化分镜与视觉查询
→ 检索本地素材库
→ 未命中时搜索 Pexels / Pixabay
→ 候选排序、规则过滤与兜底
→ 镜头时间轴编排
→ FFmpeg 场景级渲染
→ 拼接画面、配音、字幕、音乐与音效
→ 自动质量检查
→ 故事板人工复核
→ 导出最终 MP4 与项目素材包
```

核心原则：

- 配音 Segment、字幕 Cue、视觉 Scene 和素材 Shot 是不同层级的数据，不能混为同一种对象。
- 配音分段不等于视觉分镜；多个连续字幕可以合并为一个视觉语义段。
- 真实素材优先，AI 图片或 AI 视频只作为后续可选补充。
- 接口返回候选不代表素材合格，只有通过语义、事实、技术质量和去重检查的素材才能直接使用。
- 向量检索负责“相关”，实体、年代、地点、质量和重复规则负责“正确”。
- 本地素材优先，在线搜索和模型调用必须受缓存、配额和并发限制。

---

## 2. 技术选型

### 2.1 后端

后端语言固定使用 Python，原因是需要和 TTS、音频处理、字幕生成、AI 翻译、多模态检索与视频处理等能力进行深度集成。

推荐技术栈：

- Python 3.10+
- FastAPI
- Uvicorn
- SQLite
- SQLModel 或 SQLAlchemy
- Pydantic
- FFmpeg
- ffprobe
- Qwen3-TTS（默认）
- 可选 Chatterbox、CosyVoice
- httpx
- python-dotenv
- PySceneDetect
- FAISS
- SigLIP 2 或 Qwen3-VL Embedding

后端主要职责：

- 管理本地项目
- 管理参考音频与音色档案
- 清洗和切分逐字稿
- 调用 Qwen3-TTS、Chatterbox 或 CosyVoice 生成音频
- 调用 FFmpeg 处理音频
- 生成时间轴
- 生成 ASS 字幕
- 调用翻译 API 生成英文字幕
- 生成视觉语义段和结构化分镜
- 管理全局本地素材库
- 调用 Pexels、Pixabay 等素材提供方
- 对素材执行切镜、抽帧、向量化、检索、排序与去重
- 编排镜头时间轴并逐场景渲染
- 合成配音、字幕、背景音乐和音效
- 执行自动质量检查并输出报告
- 管理输出文件
- 提供本地 HTTP API 给前端调用

### 2.2 前端

前端使用本地 Web App 形式。

推荐技术栈：

- Vue 3
- TypeScript
- Vite
- Pinia
- Vue Router
- Naive UI 或 Element Plus
- Axios

前端主要职责：

- 创建项目
- 粘贴或上传逐字稿
- 上传参考音频
- 选择字幕样式
- 查看文本切段结果
- 查看 TTS 生成进度
- 查看生成日志
- 预览音频与字幕
- 编辑单条字幕文本
- 查看和调整视觉分镜
- 查看素材候选、评分、来源和授权信息
- 重搜、替换或确认低置信度素材
- 查看场景渲染与最终合成进度
- 查看自动质量检查结果
- 预览故事板、场景视频和最终视频
- 下载或打开输出文件

### 2.3 本地运行方式

项目默认以本地服务方式运行：

```text
前端：http://127.0.0.1:5173
后端：http://127.0.0.1:18080
```

后端 API 默认只监听本机地址，不默认暴露到公网。

---

## 3. 后端架构原则

后端采用清晰但不过度封装的结构。代码应优先保持简单、直接、可读、易调试。

### 3.1 基本原则

- 不要为了“架构感”而创建过多抽象层。
- 不要过度拆分方法。
- 不要把一段简单逻辑拆成大量只有一两行的小函数。
- 不要引入复杂的依赖注入框架。
- 不要设计复杂的插件系统。
- 不要引入微服务、消息队列、分布式任务或复杂权限系统。
- 后端优先使用同步、清晰、可追踪的代码；耗时任务可使用简单后台任务或本地任务状态表。
- 每个模块只处理自己职责范围内的事情。
- 涉及文件路径、音频生成、字幕生成、素材处理和视频渲染的逻辑必须可追踪、可重跑、可恢复。
- 参考方案中的 Agent 是职责边界，不代表必须创建多个大模型 Agent、进程或服务。
- 不要机械地为每个 Agent 创建一个类或文件。应将职责归并为稳定业务模块。
- 工作流编排与领域实现必须分离；批处理和单项目操作应调用同一套工作流入口。

### 3.2 推荐后端目录结构

```text
backend/
  app/
    main.py
    config.py
    database.py

    api/
      projects.py
      voices.py
      segments.py
      tts.py
      subtitles.py
      storyboard.py
      assets.py
      renders.py
      quality.py
      tasks.py
      batches.py
      settings.py
      exports.py

    models/
      project.py
      narration.py
      storyboard.py
      media.py
      task.py
      batch.py
      settings.py

    schemas/
      common.py
      project.py
      narration.py
      storyboard.py
      media.py
      render.py
      task.py

    services/
      projects/
        project_service.py
        manifest_service.py
      narration/
        text_cleaner.py
        segmenter.py
        tts_service.py
        audio_service.py
        timeline_service.py
        subtitle_service.py
        translation_service.py
      storyboard/
        scene_grouper.py
        storyboard_service.py
        query_builder.py
      media_library/
        ingestion_service.py
        retrieval_service.py
        ranking_service.py
        fallback_service.py
        usage_service.py
      rendering/
        timeline_composer.py
        scene_renderer.py
        final_renderer.py
        rough_cut_service.py
      quality/
        qa_service.py
      batches/
        batch_service.py
        batch_worker.py

    workflows/
      narration_generation.py
      video_synthesis.py

    integrations/
      tts/
        qwen_tts.py
        chatterbox.py
        cosyvoice.py
      llm/
        deepseek.py
      media_providers/
        pexels.py
        pixabay.py
      vision/
        embedding.py
        vector_index.py

    infrastructure/
      ffmpeg.py
      process_runner.py
      project_layout.py
      asset_layout.py

    shared/
      errors.py
      responses.py
      time.py

  workspace/
    app.db
    assets/
    indexes/
    projects/
    voices/
    templates/

  .env
  requirements.txt
```

说明：

- `api/` 只负责 HTTP 入参、出参、简单校验和调用 workflow 或 service。
- `models/` 放 SQLModel 数据库模型；少量关联紧密的小表可以放在同一文件中，避免一表一文件造成过度拆分。
- `schemas/` 放 API、配置和跨模块数据契约使用的 Pydantic 模型。
- `services/` 按业务域放核心业务逻辑，不再把所有 service 平铺在同一层。
- `workflows/` 只负责编排稳定步骤、保存检查点和恢复任务，不包含素材评分、FFmpeg 参数等领域细节。
- `integrations/` 隔离 TTS、LLM、Pexels、Pixabay、Embedding 等外部能力。
- `infrastructure/` 放 FFmpeg 进程执行、路径布局和底层存储等技术能力，不能反向依赖业务 service。
- `shared/` 只放真正跨领域且无业务含义的错误、响应和时间工具。
- `workspace/` 存放数据库、素材库、向量索引、项目文件、参考音频、模板和生成结果。
- 目录结构是职责规划，不要求提前创建没有实现内容的空文件。

### 3.3 业务模块与依赖边界

后端采用模块化单体，稳定业务域如下：

```text
projects
narration
storyboard
media_library
rendering
quality
batches
workflows
```

依赖方向必须保持：

```text
API / Batch Worker
→ Workflows
→ Domain Services
→ Integrations / Infrastructure
```

要求：

- API 层不能直接调用 FFmpeg、第三方素材 API、Embedding 模型或拼装复杂生产流程。
- Batch Worker 与手工触发接口必须调用相同的 workflow，不能复制一套生成逻辑。
- Workflow 可以调用多个领域 service；领域 service 不能反向依赖 workflow。
- 一个领域不得直接修改另一个领域的内部表或文件，应通过对方公开 service 或稳定数据契约交互。
- `integrations/` 和 `infrastructure/` 不得依赖项目业务 service。
- 不引入 Repository 层、抽象工厂或复杂依赖注入框架；SQLModel Session 可以由 service 直接使用。
- 当前简单随机视频粗剪保留为 `rough_cut_service.py`，不得继续扩展成智能分镜主流程。

### 3.4 核心数据概念

以下概念必须明确区分：

- `VoiceSegment`：适合 TTS 的口播生成单元，保存真实音频时长。
- `SubtitleCue`：实际显示的一条字幕，可以由 VoiceSegment 再拆分，但必须保持时间连续。
- `VisualScene`：一个视觉语义段，可以关联多个 SubtitleCue。
- `MediaFile`：素材库中的原始视频或图片文件。
- `MediaShot`：从 MediaFile 中切出的、可独立检索和使用的镜头。
- `SceneCandidate`：某个 VisualScene 检索到的候选素材及其评分与冲突信息。
- `SceneAssignment`：VisualScene 最终使用的 MediaShot，以及裁剪、速度、运镜和转场参数。
- `TaskRun`：某次配音或视频生成工作流的状态、阶段、进度和恢复检查点。

不得为了“统一时间轴”而把这些对象合并成一个巨型 Segment 模型。

---

## 4. 前端架构原则

前端以简单可用为第一目标，不追求复杂状态管理。

### 4.1 基本原则

- 页面结构清晰，避免过度组件化。
- 一个页面内部逻辑不复杂时，不要强行拆成多个小组件。
- 组件命名要直观，不要使用过度抽象的名称。
- API 请求统一放在 `api/` 目录。
- 页面级状态优先放在页面内部；跨页面共享状态再放入 Pinia。
- 表单校验以实用为主，不要写复杂规则系统。
- 日志和任务状态要直观展示，方便排查失败原因。

### 4.2 推荐前端目录结构

```text
frontend/
  src/
    main.ts
    App.vue
    router.ts

    api/
      projects.ts
      voices.ts
      narration.ts
      storyboard.ts
      assets.ts
      renders.ts
      quality.ts
      tasks.ts
      batches.ts
      settings.ts
      exports.ts

    pages/
      projects/
        ProjectList.vue
        ProjectCreate.vue
        ProjectShell.vue
        ProjectScript.vue
        ProjectNarration.vue
        ProjectSubtitles.vue
        ProjectStoryboard.vue
        ProjectMedia.vue
        ProjectRender.vue
        ProjectReports.vue
      batches/
        BatchList.vue
        BatchCreate.vue
        BatchDetail.vue
      settings/
        SystemSettings.vue

    components/
      common/
        AudioPlayer.vue
        TaskLogPanel.vue
        FileUploader.vue
      narration/
        SubtitleTable.vue
      storyboard/
        SceneCard.vue
        CandidateList.vue
      rendering/
        RenderProgress.vue
        QualityReport.vue

    stores/
      projectStore.ts

    types/
      project.ts
      narration.ts
      storyboard.ts
      media.ts
      render.ts
      task.ts
```

补充要求：

- `ProjectDetail.vue` 应逐步收敛为只负责布局和导航的 `ProjectShell.vue`。
- 项目脚本、配音字幕、故事板、素材审核、渲染和报告使用子路由页面。
- 页面拆分依据是业务步骤，不要把每个按钮、表单项或小块展示都拆成组件。
- 前端不得直接解析数据库字段 `config_json`；后端 API 应返回类型化后的 `config` 对象。
- 全局状态只保存跨页面需要的项目摘要和任务状态，场景候选、表单编辑等状态优先留在对应页面。

---

## 5. 核心功能模块

### 5.1 项目管理模块

职责：

- 创建项目
- 保存原始逐字稿
- 保存参考音频路径
- 保存生成配置
- 保存项目状态
- 管理输出目录
- 查询项目列表与详情

项目状态只保留粗粒度生命周期，建议：

```text
created
narration_in_progress
narration_ready
video_in_progress
review_required
completed
failed
```

`segmenting`、`tts`、`translation`、`storyboard`、`asset_search`、`rendering` 和 `quality_check` 等详细阶段统一保存在 TaskRun，不继续扩展 Project.status 为巨型状态机。迁移期间可以兼容现有旧状态值。

### 5.2 参考音频与音色档案模块

职责：

- 上传参考音频
- 保存参考音频
- 校验音频文件是否存在
- 使用 FFmpeg 转换为统一格式
- 记录音色名称与配置

参考音频建议统一转为：

```text
WAV
单声道或双声道统一
采样率 44100 Hz 或 48000 Hz
```

### 5.3 文本清洗模块

职责：

- 清理多余空行
- 清理 Markdown 符号
- 清理不可朗读字符
- 统一标点
- 处理数字、日期、英文缩写等 TTS 读法问题

代码要求：

- 文本清洗规则应简单明确。
- 不要把规则系统设计得过度复杂。
- 可以使用少量正则表达式，但不要写难以维护的巨型正则。
- 需要保留清洗前文本与清洗后文本，方便排查问题。

### 5.4 自动切段模块

职责：

- 根据标点和长度将逐字稿切成适合 TTS 的小段
- 生成稳定的 `segment_id`
- 控制每段文字长度
- 支持长句拆分与短句合并

推荐规则：

```text
每段 30 到 60 个中文字
优先按句号、问号、感叹号切分
其次按逗号、分号切分
避免过短片段
避免超长片段
```

每个 segment 至少包含：

```json
{
  "segment_id": "0001",
  "index": 1,
  "text_zh": "这里是分段后的中文文本。",
  "status": "pending"
}
```

### 5.5 TTS 集成模块

职责：

- 调用 Qwen3-TTS（默认）、Chatterbox 或 CosyVoice 生成每段音频
- 支持按 segment 单独生成
- 支持失败重试
- 支持跳过已生成音频
- 保存每段生成日志
- 记录失败原因

代码要求：

- 业务入口集中放在 `services/narration/tts_service.py`，引擎适配放在 `integrations/tts/`。
- 不要把具体 TTS 引擎调用散落到 API、workflow、字幕或渲染模块中。
- 第一版可以使用 subprocess 调用 CLI。
- 各 TTS 引擎使用独立 Python 环境时，也应保持统一且清晰的业务调用入口。
- 每段音频独立生成，避免整篇长稿失败后全部重跑。

配音字幕基础输出结构如下，完整项目目录以第 8 节为准：

```text
workspace/projects/{project_id}/audio/segments/
  0001.wav
  0002.wav
  0003.wav
```

### 5.6 音频处理模块

职责：

- 读取每段音频时长
- 去除异常静音
- 统一音量
- 统一采样率
- 插入段间停顿
- 拼接完整配音文件
- 导出 WAV 与 MP3

推荐工具：

- FFmpeg
- ffprobe

代码要求：

- FFmpeg 命令执行集中在 `infrastructure/ffmpeg.py`，音频业务参数由 `services/narration/audio_service.py` 组织。
- 命令执行失败时要记录 stderr。
- 不要吞掉错误。
- 不要在代码中硬编码绝对路径。

### 5.7 时间轴生成模块

职责：

- 根据每段音频真实时长生成时间轴
- 累加 start_time 与 end_time
- 考虑段间停顿
- 保存 `timeline.json`

时间轴数据示例：

```json
{
  "segments": [
    {
      "segment_id": "0001",
      "start": 0.0,
      "end": 8.42,
      "duration": 8.42,
      "text_zh": "这里是第一段字幕。"
    }
  ]
}
```

注意：

- 不要根据文字长度估算最终字幕时间。
- 字幕时间必须基于真实音频时长。

### 5.8 中文字幕 ASS 生成模块

职责：

- 根据时间轴生成 `zh.ass`
- 支持基础 ASS 样式配置
- 支持自动换行
- 支持字体、字号、描边、阴影、位置等配置

代码要求：

- ASS 生成逻辑放在 `services/narration/subtitle_service.py`。
- 不要依赖复杂字幕库，第一版可以直接生成文本文件。
- 时间格式转换函数要清晰可读。
- 字幕文本需要转义 ASS 特殊字符。

### 5.9 英文翻译模块

职责：

- 将中文 segment 翻译为英文
- 保持 segment_id 不变
- 不合并字幕
- 不拆分字幕
- 保存翻译结果

推荐支持：

- DeepSeek API
- Gemini API
- OpenAI API
- DeepL API

代码要求：

- 翻译业务逻辑集中放在 `services/narration/translation_service.py`，外部客户端放在 `integrations/llm/`。
- API Key 从 `.env` 读取。
- 不要将 API Key 写死在代码中。
- 翻译结果必须保存到 `translation.json`。
- 翻译失败时应支持重试。

翻译结果示例：

```json
[
  {
    "segment_id": "0001",
    "text_zh": "这里是中文。",
    "text_en": "This is the English translation."
  }
]
```

### 5.10 英文 ASS 生成模块

职责：

- 根据同一份时间轴生成 `en.ass`
- 使用英文字幕样式
- 控制英文换行长度
- 避免字幕过长遮挡画面

英文字幕不应改变时间轴。中文与英文字幕必须使用同一组 segment 时间。

### 5.11 导出模块

职责：

- 整理输出目录
- 生成完整项目素材包
- 生成 `manifest.json`
- 提供下载或打开本地目录能力

推荐输出结构：

```text
workspace/projects/{project_id}/
  input/
    script_raw.txt
    script_clean.txt
    reference.wav

  segments/
    segments.json

  audio/
    segments/
      0001.wav
      0002.wav
    full_voice.wav
    full_voice.mp3

  subtitles/
    zh.ass
    en.ass

  timeline/
    timeline.json

  translation/
    translation.json

  logs/
    tts.log
    error.log

  storyboard/
    scenes.json
    candidates.json

  media/
    selections.json

  renders/
    scenes/
    preview.mp4
    final.mp4

  reports/
    qa.json
    asset_sources.csv
    render_report.json

  manifest.json
```

### 5.12 视觉语义段模块

职责：

- 将连续 SubtitleCue 合并为 VisualScene。
- 根据人物、地点、事件、时间和叙事阶段决定镜头切换点。
- 避免每条字幕机械对应一个画面。
- 保持 VisualScene 的首尾时间与字幕时间轴严格对齐。

建议时长：

| 类型 | 建议镜头长度 |
|---|---:|
| 开头强钩子 | 3—5 秒 |
| 普通叙事镜头 | 5—10 秒 |
| 历史照片 | 6—12 秒 |
| 地图、时间线 | 6—12 秒 |
| 重大事件 | 8—15 秒 |
| 情绪过渡 | 4—8 秒 |

合并与切换原则：

- 同一人物、地点或事件连续出现时可以合并。
- 发生时间跳跃、主体变化或地点变化时切换。
- 叙事从事实转为分析时切换。
- 开头 30 秒可以适当加快节奏。
- 不允许 VisualScene 覆盖不到完整音频，场景时间轴不能出现空洞。

### 5.13 分镜与视觉查询模块

职责：

- 根据 VisualScene 生成结构化 Storyboard 数据。
- 将不可直接可视化的旁白转换为具体英文视觉查询。
- 生成精确、语义和通用三个层级的查询。
- 提取实体、地点、年代、场景类型、情绪、镜头偏好、必须包含和应避免内容。
- 输出兜底类别和置信度，供素材检索与人工审核使用。

分镜至少包含：

```json
{
  "scene_id": "scene_0012",
  "start_ms": 68500,
  "end_ms": 78100,
  "subtitle_ids": ["sub_0018", "sub_0019"],
  "narration": "In 1995, the traveler arrived in the United States.",
  "visual_summary": "A traveler arriving at an American airport in the mid-1990s",
  "visual_type": "historical_reconstruction",
  "entities": ["traveler", "United States"],
  "locations": ["United States"],
  "time_period": "1995",
  "scene_category": "travel",
  "mood": "curious",
  "shot_preference": "wide_or_medium",
  "primary_query": "1990s international airport traveler arriving in America",
  "alternative_queries": ["international travel airport 1990s"],
  "fallback_category": "travel",
  "fallback_mood": "neutral",
  "must_include": ["airport", "traveler"],
  "avoid": ["modern smartphone", "European landmark"],
  "confidence": 0.83
}
```

代码要求：

- Storyboard 输出必须通过 Pydantic Schema 校验，不能直接信任模型返回 JSON。
- 查询生成与素材搜索分离，Storyboard service 不直接调用 Pexels 或 Pixabay。
- 不根据画面猜测无法视觉确认的真实人物身份。
- Prompt、模型名称和关键参数需要保存到任务配置快照，确保结果可追踪。

### 5.14 全局本地素材库模块

素材来源优先级：

```text
本地已审核素材
→ 本地已下载的 Pexels / Pixabay 素材
→ Pexels 在线搜索
→ Pixabay 在线搜索
→ 相关静态图片动态化
→ 主题化本地兜底素材
→ 纯风景最终兜底
```

素材库职责：

- 管理视频、图片、缩略图、代理文件、关键帧和结构化元数据。
- 使用平台资产 ID 与文件哈希去重。
- 对视频执行切镜、关键帧抽取和技术信息读取。
- 为每个 MediaShot 独立生成向量，不允许整条多场景视频只使用一个向量。
- 保存素材来源、作者、原始页面、许可信息和下载时间。
- 统计素材使用次数、最近使用时间和项目内重复情况。

镜头切分建议：

- 使用 PySceneDetect 或明确的固定间隔策略。
- 小于 1.5 秒的镜头与相邻镜头合并。
- 大于 15 秒的镜头根据画面变化或固定间隔继续拆分。
- 短于 12 秒且没有明显切镜的视频可以整条作为一个 MediaShot。

关键帧抽取建议：

| 镜头时长 | 抽帧数量 |
|---:|---:|
| 1.5—4 秒 | 3 帧 |
| 4—8 秒 | 4 帧 |
| 8—15 秒 | 6 帧 |
| 15 秒以上 | 8 帧 |

应过滤黑屏、转场帧、运动模糊、过曝、欠曝和重复帧。

向量检索推荐：

```text
MVP：SigLIP 2 Base + FAISS IndexFlatIP + SQLite
正式版：Qwen3-VL-Embedding-2B + 结构化描述 + FAISS + SQLite
```

向量负责语义召回，结构化描述负责过滤、冲突判断和结果解释。向量文件存放在独立索引目录，SQLite 只保存 `vector_id` 和元数据，不把大向量直接塞入业务 JSON。

### 5.15 远程素材搜索模块

职责：

- 只有本地素材库没有合格结果时才调用 Pexels 和 Pixabay。
- 为每个场景按精确、语义和通用查询逐层搜索。
- 获取候选缩略图或预览图，先排序再下载完整视频。
- 每个场景限制搜索轮数、候选数和完整视频下载数。
- 缓存标准化查询结果，避免重复 API 调用。

推荐流程：

```text
搜索返回 20—40 个候选
→ 获取缩略图或预览图
→ 轻量模型预筛
→ 选出 Top 3—5
→ 只下载最终候选
→ 对完整视频切镜、抽帧、向量化并入库
```

要求：

- Pexels 与 Pixabay 的请求、响应解析、鉴权和限流分别放在 `integrations/media_providers/`。
- Provider 返回统一候选 Schema，业务层不得依赖平台专有响应结构。
- 查询缓存必须包含平台、标准化查询、过期时间和响应数据。
- 不得为了提高命中率无限扩大搜索轮数或下载全部候选。

### 5.16 素材排序、合格判断与去重模块

候选状态统一为：

```text
NO_RESULT
LOW_RELEVANCE
QUALIFIED
FALLBACK_REQUIRED
```

综合评分可以参考：

```text
视觉语义相似度 × 55%
+ 描述文本相似度 × 20%
+ 标签匹配 × 15%
+ 技术质量 × 10%
- 重复使用惩罚
- 人物或品牌冲突惩罚
- 年代冲突惩罚
- 地点冲突惩罚
```

要求：

- 相似度阈值不能在多个文件中写死，应通过测试集按模型和素材类型校准。
- 必须检查横屏比例、分辨率、时长、水印、内嵌文字、清晰度和编码完整性。
- 同一视频内禁止重复使用同一 MediaShot。
- 同一原始 MediaFile 不应连续使用。
- 60 秒内避免出现高度相似镜头。
- 对最近多个项目高频使用的素材进行扣分。
- pHash 高度相似或文件哈希相同的素材只保留一个。
- 只有 `QUALIFIED` 候选可以自动选用；低置信度候选必须进入人工审核或兜底。

### 5.17 兜底素材模块

兜底优先级：

```text
相关静态图片动态化
→ 主题化视频兜底
→ 地点类中性素材
→ 情绪类中性素材
→ 纯风景最终兜底
```

主题化兜底至少支持：

```text
business
technology
finance
history
crisis
travel
city
transition
landscape
```

要求：

- 不允许所有检索失败场景统一使用随机风景。
- 纯风景只适用于章节切换、时间流逝、人生感悟、情绪缓冲和结尾总结。
- 商业事件、人物经历和公司冲突等具体叙事不能随意插入风景空镜。
- 控制同类兜底素材在单条视频中的占比和连续重复。

### 5.18 镜头时间轴编排模块

职责：

- 将 SceneAssignment 放入精确时间轴。
- 决定素材裁剪区间、播放速度、图片运镜和转场。
- 保证画面轨道覆盖完整旁白时长。

素材长于场景时：

- 从视觉质量较高且动作完整的区间裁剪。
- 避免从源视频切镜点附近开始。

素材短于场景时，按以下顺序处理：

1. 降低到允许的最低速度，例如 0.85 倍。
2. 补充同主题第二镜头。
3. 使用最后一帧轻微推拉。
4. 插入相关静态图片。
5. 避免明显循环播放。

纪录片风格以硬切为主、叠化为辅；普通转场建议 0.2—0.5 秒。图片运镜应缓慢，缩放通常控制在 100% 到 106% 或 108%。

### 5.19 FFmpeg 视频渲染模块

标准输出参数：

```text
分辨率：1920×1080
帧率：30 fps
视频编码：H.264
像素格式：yuv420p
音频编码：AAC 48 kHz
容器：MP4
```

渲染要求：

- 每个 VisualScene 先独立渲染为统一规格的中间片段。
- 场景片段全部校验后再执行最终 concat 和音轨合成。
- 横屏视频使用 `scale + crop`，禁止拉伸变形。
- 竖屏素材默认不使用；必须使用时采用居中主画面和模糊背景或画中画布局。
- 原素材音轨默认删除，最终音轨由配音、背景音乐和音效统一混合。
- 支持外挂字幕和 ASS 烧录字幕两种模式。
- 配音存在时应自动压低背景音乐；音量和峰值规则通过配置管理。
- 单场景失败必须可重试，替换一个场景素材时不能强制重渲染整条视频。
- 最终拼接前使用 ffprobe 校验所有中间片段。

推荐中间结构：

```text
renders/scenes/scene_0001.mp4
renders/scenes/scene_0002.mp4
renders/preview.mp4
renders/final.mp4
```

### 5.20 自动质量检查模块

自动检查至少包括：

- 时间轴首尾连续、无负时长、无画面空洞。
- 视频总时长与配音时长误差小于 100 ms。
- 字幕不得越过音频结束时间。
- 黑屏比例、长静帧、重复画面、分辨率、纵横比和编码完整性。
- 音频峰值、LUFS、过长静音、爆音和声道异常。
- 字幕空文本、重叠、行长、中英文数量与时间轴一致性、特殊字符和安全区。
- 素材平台、素材 ID、作者、来源页面、下载时间和使用场景是否齐全。

质量检查输出 `reports/qa.json`，不得只返回布尔值。每个问题应包含类型、严重级别、关联场景或字幕、可读说明和可选修复建议。

### 5.21 故事板人工审核模块

审核页面应显示：

- 场景起止时间和对应字幕。
- 当前画面缩略图或预览。
- 素材来源、评分、状态和冲突原因。
- 替换、重搜、确认和选择兜底操作。

重点突出：

- 低于阈值或使用兜底的场景。
- 可能存在人物、品牌、地点或年代错误的场景。
- 同类素材重复过多的场景。
- 纯风景镜头和低置信度镜头。

人工确认结果必须持久化到 SceneAssignment，重新渲染时不得丢失人工选择。

### 5.22 工作流、任务与恢复模块

系统只维护两条主要工作流：

```text
narration_generation
video_synthesis
```

`narration_generation` 负责：

```text
文本清洗 → 口播切段 → TTS → 音频拼接 → 字幕时间轴 → 翻译与字幕导出
```

`video_synthesis` 负责：

```text
视觉语义段 → Storyboard → 素材检索与选择 → 时间轴编排
→ 场景渲染 → 最终合成 → QA → 人工复核 → 最终导出
```

要求：

- 每一步必须具有明确输入、输出、状态和错误信息。
- 已成功且输入未变化的步骤可以跳过。
- 支持从失败检查点继续，不要强制整条流程从头开始。
- 单项目手工操作和批处理调用同一套 workflow。
- 不实现可视化通用 DAG、插件式节点系统或复杂工作流 DSL。

---

## 6. API 设计规范

API 使用 REST 风格即可，不需要 GraphQL。

### 6.1 基础接口

```text
GET    /api/projects
POST   /api/projects
GET    /api/projects/{project_id}
DELETE /api/projects/{project_id}
```

```text
POST /api/projects/{project_id}/script
POST /api/projects/{project_id}/reference-audio
POST /api/projects/{project_id}/segments
GET  /api/projects/{project_id}/segments
```

```text
POST /api/projects/{project_id}/tts/start
POST /api/projects/{project_id}/tts/retry-failed
POST /api/projects/{project_id}/tts/regenerate/{segment_id}
GET  /api/projects/{project_id}/tts/status
```

```text
POST /api/projects/{project_id}/audio/merge
POST /api/projects/{project_id}/subtitles/zh
POST /api/projects/{project_id}/subtitles/en
POST /api/projects/{project_id}/export
```

```text
POST /api/projects/{project_id}/storyboard/generate
GET  /api/projects/{project_id}/storyboard
PUT  /api/projects/{project_id}/storyboard/scenes/{scene_id}
POST /api/projects/{project_id}/storyboard/scenes/{scene_id}/search
POST /api/projects/{project_id}/storyboard/scenes/{scene_id}/assign
```

```text
GET  /api/assets
POST /api/assets/import
GET  /api/assets/{media_id}
POST /api/assets/{media_id}/ingest
POST /api/assets/search
```

```text
POST /api/projects/{project_id}/render/scenes/{scene_id}
POST /api/projects/{project_id}/render/preview
POST /api/projects/{project_id}/render/final
GET  /api/projects/{project_id}/render/status
POST /api/projects/{project_id}/quality/check
GET  /api/projects/{project_id}/quality/report
```

```text
POST /api/projects/{project_id}/workflows/narration/start
POST /api/projects/{project_id}/workflows/video/start
POST /api/projects/{project_id}/tasks/cancel
GET  /api/projects/{project_id}/tasks/status
```

具体路径可以按现有兼容性小范围调整，但资源边界不得混淆。API 不应暴露 FAISS 索引路径、模型内部对象或第三方平台原始响应。

### 6.2 API 返回格式

成功返回：

```json
{
  "success": true,
  "data": {}
}
```

失败返回：

```json
{
  "success": false,
  "error": "错误说明"
}
```

要求：

- 错误信息要可读。
- 不要只返回 `failed`。
- 后端日志中要记录完整错误信息。
- 前端展示给用户的错误可以简化，但不能完全丢失原因。

---

## 7. 数据库规范

本地单机版本使用 SQLite。随着表结构增加，应使用轻量数据库迁移机制管理变更；不能依赖 `create_all()` 修改已有表。

数据库按两类数据划分：

- 全局可复用数据：素材文件、镜头、关键帧和搜索缓存。
- 项目级数据：口播段、字幕、视觉场景、候选、最终分配、使用记录和任务状态。

### 7.1 projects

```sql
CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  script_raw_path TEXT,
  script_clean_path TEXT,
  reference_audio_path TEXT,
  output_dir TEXT,
  status TEXT NOT NULL,
  config_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 7.2 segments

```sql
CREATE TABLE segments (
  id TEXT PRIMARY KEY,
  segment_id TEXT NOT NULL,
  project_id TEXT NOT NULL,
  segment_index INTEGER NOT NULL,
  text_zh TEXT NOT NULL,
  text_en TEXT,
  audio_path TEXT,
  duration REAL,
  start_time REAL,
  end_time REAL,
  status TEXT NOT NULL,
  error_message TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

`segment_id` 在同一项目内必须唯一，并在重新运行不改变输入时保持稳定。

### 7.3 subtitle_cues

```sql
CREATE TABLE subtitle_cues (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  source_segment_id TEXT NOT NULL,
  cue_index INTEGER NOT NULL,
  language TEXT NOT NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

中文与英文 SubtitleCue 必须可以通过稳定 ID 或 `source_segment_id + cue_index` 对齐，不能通过数组当前位置临时关联。

### 7.4 voice_profiles

```sql
CREATE TABLE voice_profiles (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  reference_audio_path TEXT NOT NULL,
  config_json TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 7.5 subtitle_templates

```sql
CREATE TABLE subtitle_templates (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  language TEXT NOT NULL,
  config_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 7.6 visual_scenes

```sql
CREATE TABLE visual_scenes (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  scene_index INTEGER NOT NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  narration TEXT NOT NULL,
  subtitle_ids_json TEXT NOT NULL,
  storyboard_json TEXT,
  confidence REAL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

### 7.7 scene_candidates

```sql
CREATE TABLE scene_candidates (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  scene_id TEXT NOT NULL,
  shot_id INTEGER,
  provider TEXT NOT NULL,
  provider_asset_id TEXT,
  preview_url TEXT,
  semantic_score REAL,
  quality_score REAL,
  conflict_score REAL,
  status TEXT NOT NULL,
  reason TEXT,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);
```

### 7.8 scene_assignments

```sql
CREATE TABLE scene_assignments (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  scene_id TEXT NOT NULL,
  shot_id INTEGER NOT NULL,
  source_start_ms INTEGER,
  source_end_ms INTEGER,
  speed REAL,
  motion_json TEXT,
  transition_json TEXT,
  selected_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

`selected_by` 至少区分 `automatic` 与 `manual`。人工确认的分配不能被后续自动检索静默覆盖。

### 7.9 media_files

```sql
CREATE TABLE media_files (
  id INTEGER PRIMARY KEY,
  platform TEXT,
  platform_asset_id TEXT,
  file_path TEXT NOT NULL,
  file_hash TEXT NOT NULL,
  source_page TEXT,
  author TEXT,
  license_info TEXT,
  duration_ms INTEGER NOT NULL,
  width INTEGER,
  height INTEGER,
  fps REAL,
  orientation TEXT,
  created_at TEXT NOT NULL,
  downloaded_at TEXT
);
```

平台资产 ID 和文件哈希必须建立合适的唯一约束或去重检查。

### 7.10 media_shots

```sql
CREATE TABLE media_shots (
  id INTEGER PRIMARY KEY,
  media_id INTEGER NOT NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  caption TEXT,
  scene_type TEXT,
  subjects_json TEXT,
  actions_json TEXT,
  locations_json TEXT,
  mood_json TEXT,
  time_of_day TEXT,
  shot_type TEXT,
  camera_motion TEXT,
  people_count INTEGER,
  visible_text_json TEXT,
  logos_json TEXT,
  quality_score REAL,
  used_count INTEGER DEFAULT 0,
  last_used_at TEXT,
  FOREIGN KEY(media_id) REFERENCES media_files(id)
);
```

### 7.11 keyframes

```sql
CREATE TABLE keyframes (
  id INTEGER PRIMARY KEY,
  shot_id INTEGER NOT NULL,
  timestamp_ms INTEGER NOT NULL,
  image_path TEXT NOT NULL,
  vector_id INTEGER,
  sharpness_score REAL,
  brightness_score REAL,
  FOREIGN KEY(shot_id) REFERENCES media_shots(id)
);
```

### 7.12 asset_usages

```sql
CREATE TABLE asset_usages (
  id INTEGER PRIMARY KEY,
  project_id TEXT NOT NULL,
  scene_id TEXT NOT NULL,
  shot_id INTEGER NOT NULL,
  used_start_ms INTEGER,
  used_end_ms INTEGER,
  created_at TEXT NOT NULL
);
```

### 7.13 search_cache

```sql
CREATE TABLE search_cache (
  id INTEGER PRIMARY KEY,
  platform TEXT NOT NULL,
  normalized_query TEXT NOT NULL,
  response_json TEXT NOT NULL,
  expires_at TEXT,
  created_at TEXT NOT NULL
);
```

### 7.14 task_runs

```sql
CREATE TABLE task_runs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL,
  workflow TEXT NOT NULL,
  status TEXT NOT NULL,
  current_stage TEXT NOT NULL,
  progress REAL NOT NULL,
  checkpoint_json TEXT,
  error_message TEXT,
  started_at TEXT,
  updated_at TEXT NOT NULL,
  finished_at TEXT
);
```

`projects.status` 只表示项目粗粒度状态；详细阶段、进度和恢复点统一由 `task_runs` 管理。不得同时在内存状态、批次字段、项目字段和多个 progress 文件中维护互相冲突的任务真相。

---

## 8. 文件与路径规范

- `backend/workspace/` 是默认运行时目录；可以通过 `WORKSPACE_DIR` 覆盖，但同一次运行只能有一个规范化后的 workspace 根目录。
- 仓库根目录与 `backend/` 下不得同时维护两套活跃 workspace。
- 所有项目工作文件必须存放在 `workspace/projects/{project_id}/` 下。
- 用户选择的外部输出目录只用于最终导出，不应成为任务缓存、数据库或中间文件目录。
- 所有参考音频档案必须存放在 `workspace/voices/` 下。
- 所有全局素材与派生文件必须存放在 `workspace/assets/` 下。
- FAISS 等向量索引必须存放在 `workspace/indexes/` 下。
- 不要在代码中硬编码 Windows 或 macOS 绝对路径。
- 路径处理统一使用 `pathlib.Path`。
- 文件名使用英文、数字、下划线和短横线。
- segment 文件名使用固定四位编号，例如 `0001.wav`。
- scene 文件名使用固定四位编号，例如 `scene_0001.mp4`。
- 删除文件前需要确认文件位于 workspace 目录内。
- 素材原文件全局只保存一份，项目目录保存素材引用、裁剪参数和来源清单。
- 只有导出自包含素材包时，才将全局原素材复制到项目导出目录。

推荐运行时目录：

```text
workspace/
├── app.db
├── assets/
│   ├── originals/
│   │   ├── pexels/
│   │   ├── pixabay/
│   │   └── manual/
│   ├── fallback/
│   │   ├── business/
│   │   ├── technology/
│   │   ├── finance/
│   │   ├── history/
│   │   ├── crisis/
│   │   ├── travel/
│   │   ├── city/
│   │   ├── transition/
│   │   └── landscape/
│   ├── thumbnails/
│   ├── keyframes/
│   ├── proxies/
│   └── metadata/
├── indexes/
│   └── media.faiss
├── projects/
│   └── {project_id}/
│       ├── manifest.json
│       ├── input/
│       │   ├── script_raw.txt
│       │   ├── script_clean.txt
│       │   └── reference.wav
│       ├── segments/
│       │   └── segments.json
│       ├── audio/
│       │   ├── segments/
│       │   ├── narration.wav
│       │   └── bgm.wav
│       ├── timeline/
│       │   └── timeline.json
│       ├── translation/
│       │   └── translation.json
│       ├── subtitles/
│       │   ├── zh.srt
│       │   ├── en.srt
│       │   ├── zh.ass
│       │   └── en.ass
│       ├── storyboard/
│       │   ├── scenes.json
│       │   ├── candidates.json
│       │   └── storyboard.html
│       ├── media/
│       │   ├── selections.json
│       │   └── images/
│       ├── renders/
│       │   ├── scenes/
│       │   ├── preview.mp4
│       │   └── final.mp4
│       ├── reports/
│       │   ├── qa.json
│       │   ├── asset_sources.csv
│       │   └── render_report.json
│       ├── logs/
│       └── temp/
├── voices/
└── templates/
```

---

## 9. 代码规范

### 9.1 总体要求

- 代码优先简洁、直接、可读。
- 不要过度封装。
- 不要为了复用而提前抽象。
- 不要设计复杂继承结构。
- 不要使用过深的类层级。
- 一个函数只要逻辑清晰，可以适当长一些，不需要强行拆分。
- 重复出现三次以上、且确实稳定的逻辑，再考虑提取函数。
- 业务逻辑优先写成简单函数，只有在确实需要保存状态时再使用类。
- 不要把参考文档中的每个 Agent 实现为抽象类、基类或独立服务。
- 同一业务域内的简单逻辑可以直接调用；跨业务域调用应通过公开 service 函数或 Pydantic Schema。
- 不得把所有流程状态、素材元数据和渲染参数继续堆入 `Project.config_json`。
- 不得创建包罗所有职责的 `video_service.py`；素材检索、镜头编排、渲染和 QA 必须分属不同模块。

### 9.2 Python 代码规范

- 使用类型标注。
- 使用 `pathlib.Path` 处理路径。
- 使用 `logging` 记录日志。
- 使用 Pydantic 定义 API 请求与响应模型。
- 捕获异常时必须记录原始错误。
- 不要使用裸 `except`。
- 不要静默忽略异常。
- 不要把大段业务逻辑写在 FastAPI 路由函数中。
- 路由函数只做参数接收、简单校验和调用 service。
- 外部 Provider 响应必须先转换为内部 Schema，再进入排序或持久化逻辑。
- LLM 和多模态模型的 JSON 输出必须使用 Pydantic 校验，并记录无法解析的原始错误摘要。
- FFmpeg 与 ffprobe 执行集中在 `infrastructure/ffmpeg.py`，业务模块只传递明确参数，不自行拼接 shell 字符串。
- 底层 `infrastructure/` 和 `shared/` 代码不得导入业务 service。
- 长任务要定期检查取消状态，并以原子方式保存任务进度或检查点。

示例风格：

```python
from pathlib import Path


def get_segment_audio_path(project_dir: Path, segment_id: str) -> Path:
    return project_dir / "audio" / "segments" / f"{segment_id}.wav"
```

避免：

```python
class AbstractSegmentAudioPathFactoryBase:
    ...
```

### 9.3 前端代码规范

- 页面代码优先直观。
- 不要过度封装 hooks。
- 简单请求可以直接在页面中调用 API 方法。
- 公共 API 请求封装在 `api/` 目录。
- 类型定义放在 `types/` 目录。
- 组件 props 不要设计得过度复杂。
- 不要写过度通用的表格组件、表单组件或弹窗系统。
- 项目详情页按脚本、配音字幕、故事板、素材、渲染和报告拆分子路由。
- 页面不得直接解析 `config_json`、第三方 Provider 响应或数据库内部字段。
- 故事板编辑状态应以 scene 为最小保存单元，替换单场景素材时不要刷新或重建整条故事板。

### 9.4 注释规范

- 注释解释“为什么这样做”，不要重复代码表面含义。
- 对 FFmpeg 命令、ASS 格式、TTS 调用参数、向量模型输入和素材评分规则要写必要注释。
- 对临时方案要标注清楚，例如 `TODO` 或 `NOTE`。
- 不要写无意义注释。

---

## 10. 配置规范

项目配置使用 `.env` 与简单配置文件。

`.env` 示例：

```env
APP_HOST=127.0.0.1
APP_PORT=18080
WORKSPACE_DIR=./workspace
FFMPEG_PATH=ffmpeg
FFPROBE_PATH=ffprobe
GEMINI_API_KEY=
OPENAI_API_KEY=
DEEPL_API_KEY=
PEXELS_API_KEY=
PIXABAY_API_KEY=
EMBEDDING_MODEL_PATH=
VECTOR_INDEX_PATH=./workspace/indexes/media.faiss
```

要求：

- API Key 不得写入代码。
- `.env` 不得提交到公开仓库。
- 默认配置应能在本地直接运行。
- 缺少外部翻译 API Key 时，中文配音和中文字幕功能仍应可用。
- 缺少远程素材 API Key 时，本地素材库、手工素材选择和粗剪功能仍应可用。
- 系统配置、项目配置与单次任务快照必须分开。
- 前端 API 返回配置对象时必须隐藏完整密钥，只返回是否已配置或掩码值。

配置分层：

1. `SystemSettings`：FFmpeg、模型路径、API Key、GPU 设备和本机 workspace。
2. `ProjectConfig`：音色、字幕样式、视频尺寸、素材偏好、兜底策略和渲染参数。
3. `TaskRun.checkpoint_json`：单次任务使用的配置快照、阶段输出和恢复点。

短期可以继续将 ProjectConfig 存在 `projects.config_json` 中，但必须通过 Pydantic 模型统一读写。API 返回解析后的 `config` 对象，前端不得自行解析 JSON 字符串。

视频相关项目配置建议：

```yaml
video:
  width: 1920
  height: 1080
  fps: 30
  codec: libx264
  pixel_format: yuv420p

scene:
  min_duration_ms: 3000
  preferred_duration_ms: 8000
  max_duration_ms: 15000

retrieval:
  local_top_k: 50
  final_candidates: 3
  similarity_threshold: null
  use_dynamic_threshold: true

remote_search:
  providers: [pexels, pixabay]
  max_rounds: 3
  preview_candidates: 30
  full_download_candidates: 3
  cache_ttl_hours: 24

fallback:
  enable_images: true
  enable_topic_assets: true
  enable_landscape: true
  landscape_max_ratio: 0.08

render:
  scene_parallelism: 2
  preview_crf: 26
  final_crf: 18
  audio_lufs: -16
```

不同模型的相似度分布不同，`similarity_threshold` 默认不写死。阈值应通过人工标注测试集校准，并保存模型版本和校准结果。

---

## 11. 日志规范

需要记录以下日志：

- 项目创建
- 文本清洗
- 切段结果
- 每个 segment 的 TTS 生成状态
- FFmpeg 命令执行失败原因
- 翻译 API 调用失败原因
- 字幕导出结果
- 完整音频导出结果
- 视觉语义段与 Storyboard 生成结果摘要
- 本地素材召回数量和候选状态
- 远程素材查询、缓存命中、配额和下载结果
- 素材入库、切镜、抽帧、向量化与去重结果
- 每个 scene 的素材选择、人工替换和渲染状态
- 最终视频拼接与音轨合成结果
- 自动质量检查问题摘要

日志文件建议：

```text
workspace/projects/{project_id}/logs/app.log
workspace/projects/{project_id}/logs/tts.log
workspace/projects/{project_id}/logs/storyboard.log
workspace/projects/{project_id}/logs/assets.log
workspace/projects/{project_id}/logs/render.log
workspace/projects/{project_id}/logs/qa.log
workspace/projects/{project_id}/logs/error.log
```

要求：

- 日志要能帮助定位是哪一个 segment 失败。
- 视频相关日志要能帮助定位是哪一个 scene、candidate、media file 或 shot 失败。
- 不要在日志中输出完整 API Key。
- 不要在日志中输出过长的原始全文，可截断显示。
- 不要记录第三方接口完整鉴权 URL。
- FFmpeg、Provider 和模型调用失败时必须保留可诊断的 stderr、HTTP 状态或解析错误摘要。

---

## 12. 安全与本地权限规范

本项目默认在本地运行，不默认提供公网访问。

要求：

- 后端默认监听 `127.0.0.1`。
- 不要默认开启跨域公网访问。
- 文件读写必须限制在 workspace 目录内。
- 不要允许前端传入任意系统路径后直接删除或覆盖文件。
- 所有外部命令调用必须使用参数数组，不要拼接 shell 字符串。
- 对上传文件类型进行基础校验。
- 对音频文件大小进行限制。
- 对视频和图片文件类型、文件大小、分辨率和可解码性进行基础校验。
- 远程下载必须限制超时、最大文件大小、重试次数和允许的协议。
- 不允许前端提供任意下载 URL 后由后端无条件访问；远程素材应来自配置过的 Provider 或经过明确校验的来源。
- 从素材元数据中读取到的文件名、作者名和标题不得直接用作系统路径。
- 素材删除前需要确认没有项目 SceneAssignment 正在引用；默认优先软删除元数据或移入受控回收目录。
- 第三方素材来源、作者和许可信息必须随最终导出清单保留。

---

## 13. ASS 字幕规范

ASS 字幕生成应支持基础样式配置。

默认分辨率：

```text
PlayResX: 1920
PlayResY: 1080
```

中文字幕建议：

```text
字体较大
底部居中
白字
黑色描边
最多两行
```

英文字幕建议：

```text
字号小于中文
底部居中
自动换行
最多两行
```

字幕文本要求：

- 需要转义 ASS 特殊字符。
- 不要让单条字幕过长。
- 英文字幕可以按字符数自动插入换行。
- 中文和英文字幕使用同一份时间轴。

---

## 14. 不做的事情

当前视频合成 MVP 明确不做以下内容：

- 不做剪映草稿生成
- 不做剪映自动点击
- 不把剪映作为核心渲染引擎
- 不把复杂 AI 视频生成作为基础生产方式
- 不默认使用 AI 图片生成；只保留后续可选补充能力
- 不做自动人物身份识别
- 不做复杂新闻档案搜索
- 不做多模型复杂重排
- 不做高级地图、时间线和数据动画
- 不做 YouTube 自动上传
- 不做云端账号系统
- 不做多人协作
- 不做复杂权限系统
- 不做插件市场
- 不做通用工作流编排平台、可视化 DAG 或工作流 DSL
- 不做多机并行或分布式素材库

当前 MVP 应优先完成：

1. 视觉语义段合并。
2. Storyboard JSON 与英文视觉查询。
3. Pexels、Pixabay 搜索和查询缓存。
4. 缩略图预筛、候选下载与本地素材入库。
5. 素材切镜、关键帧、向量化和 FAISS 检索。
6. 主题化兜底素材。
7. 场景独立渲染与完整视频拼接。
8. 中英文字幕、配音和基础背景音乐合成。
9. 自动 QA、故事板审核和低置信度人工替换。

后续能力必须通过现有业务边界扩展，不得污染配音字幕基础模块或把可选能力硬编码进核心工作流。

---

## 15. AI 编码助手行为规范

当 AI 编码助手参与本项目开发时，必须遵守以下规则：

- 优先保持代码简单。
- 不要主动引入复杂架构。
- 不要把简单需求写成企业级框架。
- 不要创建无必要的抽象基类、工厂、接口层、插件层。
- 不要在没有要求的情况下重构大量无关代码。
- 修改代码时应尽量小范围变更。
- 新增功能时应优先复用现有简单结构。
- 不要擅自改变技术栈。
- 后端必须使用 Python。
- 前端必须使用 Vue 3 + TypeScript。
- 本地版本数据库使用 SQLite。
- 音频处理优先使用 FFmpeg。
- 视频处理与最终合成优先使用 FFmpeg。
- 字幕生成优先直接生成 ASS 文本文件。
- TTS 集成逻辑必须集中在 `integrations/tts/` 与 `services/narration/tts_service.py`，不能散落在 API、workflow 或渲染模块。
- Pexels、Pixabay 集成逻辑必须集中在 `integrations/media_providers/`。
- Embedding 和向量索引逻辑必须集中在 `integrations/vision/`。
- 新增视频功能必须遵循 VoiceSegment、SubtitleCue、VisualScene、MediaShot 和 SceneAssignment 的边界。
- 新增完整流程步骤时优先扩展 `workflows/`，不要在 API 或 Batch Worker 中复制流程。
- 修改现有平铺 service 时，优先进行行为不变的小步迁移，再增加新功能。
- 不要在同一变更中同时大规模移动文件、修改 API 和重写业务逻辑。
- 涉及外部 API Key 的代码必须从环境变量读取。
- 涉及文件操作时必须考虑本地路径安全。

本项目的代码风格目标是：

```text
能跑通
易理解
易调试
少抽象
少魔法
少依赖
方便后续继续扩展
```

---

## 16. 渐进实施与迁移顺序

项目结构优化和视频功能必须渐进实施，不进行一次性大重构。

### 16.1 阶段一：稳定现有能力边界

- 将现有配音、字幕、项目、批处理和粗剪 service 移入对应业务子目录。
- 保持现有 API 路径、返回格式和用户行为不变。
- 为旧导入路径保留短期兼容入口，测试迁移完成后再清理。
- 将当前 `video_service.py` 拆为粗剪选择、FFmpeg 标准化、进度和最终拼接等明确职责。

### 16.2 阶段二：建立公共运行基础

- 建立 `workflows/narration_generation.py`，让单项目和批处理复用同一流程。
- 增加 TaskRun、类型化 ProjectConfig 和数据库迁移。
- 统一 workspace、项目路径和全局素材路径。
- 将 FFmpeg 进程执行和取消控制下沉到 infrastructure，消除底层工具对业务 service 的反向依赖。

### 16.3 阶段三：分镜 MVP

- 建立 SubtitleCue、VisualScene、Storyboard Schema 和数据库模型。
- 实现视觉语义段合并、结构化分镜和查询生成。
- 提供场景级查看、编辑和重新生成接口。

### 16.4 阶段四：素材库与检索 MVP

- 实现 Pexels、Pixabay Provider 和查询缓存。
- 实现全局素材入库、切镜、关键帧、文件哈希和元数据。
- 接入 SigLIP 2 或 Qwen3-VL Embedding 与 FAISS。
- 实现候选排序、冲突检查、去重和主题化兜底。

### 16.5 阶段五：视频渲染与 QA

- 实现场景时间轴、场景独立渲染和最终拼接。
- 合成配音、字幕、背景音乐和音效。
- 实现自动 QA 报告和场景级重试。
- 生成来源清单、渲染报告和最终 Manifest。

### 16.6 阶段六：前端工作台

- 将 ProjectDetail 收敛为 ProjectShell 和子路由。
- 增加故事板、候选审核、低置信度替换、渲染和报告页面。
- 保持页面级状态简单，不为时间轴编辑提前引入复杂前端状态框架。

每个阶段完成后都必须保证已有配音字幕流程仍可独立运行。

---

## 17. 性能、缓存与成本控制

- 每个场景必须先检索本地素材库，本地有 `QUALIFIED` 结果时不调用远程 Provider。
- 必须缓存查询结果、缩略图、已下载素材、文件哈希、关键帧、向量和结构化描述。
- 同一章节中语义接近的查询可以合并，但不能因为缓存合并而忽略必须包含或应避免的实体约束。
- 只对最终候选下载完整视频，避免下载全部搜索结果。
- 新下载素材只正式入库一次，后续项目复用。
- 对缩略图使用轻量模型预筛，只对低置信度候选使用更重的模型。
- 针对 8GB 显存，Embedding、描述模型和其他 VLM 串行加载，不允许多个模型长期同时驻留显存。
- 限制每个场景的远程搜索轮数、候选数、完整视频下载数和重试次数。
- 场景渲染并发必须可配置；默认从 1—2 个并发开始，不根据 CPU 核数盲目放大。
- 模型和 Provider 失败时允许降级到本地素材与人工选择，不得阻塞配音字幕输出。

---

## 18. 测试与验收规范

测试目录按业务域组织：

```text
backend/tests/
  narration/
  storyboard/
  media_library/
  rendering/
  workflows/
  integration/
```

要求：

- 文本清洗、切段、字幕时间、ASS 转义和路径安全使用确定性单元测试。
- Storyboard 和 Provider 使用固定 JSON Fixture 测试解析、校验和异常响应。
- 素材排序测试必须覆盖相关、低相关、人物冲突、年代冲突和重复素材。
- FFmpeg 测试优先验证参数数组和短素材集成结果，不依赖长视频样本。
- 工作流测试覆盖阶段跳过、失败检查点、取消、单场景重试和恢复。
- 至少保留一套数秒钟的端到端固定样本，验证配音时间轴、场景覆盖、字幕和最终 MP4 可播放。
- 数据库迁移必须同时测试新建数据库和已有数据库升级。

检索阈值应使用人工标注测试集校准，至少跟踪：

```text
Top 1 准确率
Top 3 / Top 5 召回率
错误人物率
错误年代率
纯风景使用率
人工替换率
单条视频平均人工处理时间
```

视频输出验收至少包括：

- 视频可播放且编码完整。
- 画面轨道无空洞。
- 视频与配音总时长误差小于 100 ms。
- 中英文字幕时间轴一致。
- 所有自动选择素材均为 `QUALIFIED`，或明确标记为人工确认/兜底。
- 最终导出包含素材来源与 QA 报告。
