# AGENTS.md

本文件用于约束本项目中的 AI 编码助手、开发者与自动化代理的行为。项目目标是构建一个本地 Web App，用于根据原始逐字稿与 index-tts 参考音频，自动生成完整配音文件、中文字幕 ASS 文件与英文字幕 ASS 文件。

本项目第一阶段只关注“配音与字幕自动化”，不包含剪映草稿生成、视频合成、分镜生成、图片生成、YouTube 上传、账号系统或云端 SaaS 化能力。

---

## 1. 项目定位

本项目是一个本地运行的视频生产辅助工具，核心输入与输出如下：

输入：

- 原始逐字稿文本
- index-tts 参考音频
- 基础生成配置，例如项目名称、音色配置、字幕样式、输出目录

输出：

- 分段配音音频
- 完整配音文件，优先输出 WAV，可选输出 MP3
- 中文字幕 ASS 文件
- 英文字幕 ASS 文件
- 时间轴 JSON
- 分段信息 JSON
- 项目 Manifest 文件

核心流程：

```text
逐字稿
→ 文本清洗
→ 自动切段
→ index-tts 批量生成分段音频
→ 音频后处理
→ 拼接完整配音
→ 读取每段音频时长
→ 生成时间轴
→ 生成中文字幕 ASS
→ 翻译英文字幕
→ 生成英文 ASS
→ 导出项目素材包
```

---

## 2. 技术选型

### 2.1 后端

后端语言固定使用 Python，原因是需要和 index-tts、音频处理、字幕生成、AI 翻译等能力进行深度集成。

推荐技术栈：

- Python 3.10+
- FastAPI
- Uvicorn
- SQLite
- SQLModel 或 SQLAlchemy
- Pydantic
- FFmpeg
- index-tts
- httpx
- python-dotenv

后端主要职责：

- 管理本地项目
- 管理参考音频与音色档案
- 清洗和切分逐字稿
- 调用 index-tts 生成音频
- 调用 FFmpeg 处理音频
- 生成时间轴
- 生成 ASS 字幕
- 调用翻译 API 生成英文字幕
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
- 不要在第一阶段引入微服务、消息队列、分布式任务或复杂权限系统。
- 后端优先使用同步、清晰、可追踪的代码；耗时任务可使用简单后台任务或本地任务状态表。
- 每个模块只处理自己职责范围内的事情。
- 涉及文件路径、音频生成、字幕生成的逻辑必须可追踪、可重跑、可恢复。

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
      exports.py

    models/
      project.py
      segment.py
      voice_profile.py
      subtitle_template.py

    services/
      text_cleaner.py
      segmenter.py
      tts_service.py
      audio_service.py
      timeline_service.py
      translate_service.py
      ass_service.py
      export_service.py

    utils/
      file_utils.py
      time_utils.py
      ffmpeg_utils.py

  workspace/
    projects/
    voices/
    templates/

  .env
  requirements.txt
```

说明：

- `api/` 只负责 HTTP 入参、出参和调用 service。
- `services/` 放核心业务逻辑。
- `models/` 放数据库模型。
- `utils/` 只放通用工具，不要把业务逻辑塞进去。
- `workspace/` 存放本地项目文件、参考音频、模板文件和生成结果。

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
      segments.ts
      tts.ts
      subtitles.ts
      exports.ts

    pages/
      ProjectList.vue
      ProjectCreate.vue
      ProjectDetail.vue
      SegmentEditor.vue
      GenerationStatus.vue
      ResultPreview.vue

    components/
      AudioPlayer.vue
      SubtitleTable.vue
      TaskLogPanel.vue
      FileUploader.vue

    stores/
      projectStore.ts

    types/
      project.ts
      segment.ts
      subtitle.ts
```

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

项目状态建议：

```text
created
script_imported
segmented
tts_running
tts_completed
audio_merged
zh_subtitle_created
translating
en_subtitle_created
exported
failed
```

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
每段 60 到 150 个中文字
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

### 5.5 index-tts 集成模块

职责：

- 调用 index-tts 生成每段音频
- 支持按 segment 单独生成
- 支持失败重试
- 支持跳过已生成音频
- 保存每段生成日志
- 记录失败原因

代码要求：

- index-tts 调用逻辑集中放在 `tts_service.py`。
- 不要把 index-tts 调用散落到 API 层或多个模块中。
- 第一版可以使用 subprocess 调用 CLI。
- 如果后续直接 import index-tts Python API，也应保持调用入口清晰。
- 每段音频独立生成，避免整篇长稿失败后全部重跑。

推荐输出结构：

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

- FFmpeg 命令要集中封装在 `ffmpeg_utils.py` 或 `audio_service.py`。
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

- ASS 生成逻辑放在 `ass_service.py`。
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

- Gemini API
- OpenAI API
- DeepL API

代码要求：

- 翻译调用集中放在 `translate_service.py`。
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

  manifest.json
```

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

第一阶段使用 SQLite。

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

### 7.3 voice_profiles

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

### 7.4 subtitle_templates

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

---

## 8. 文件与路径规范

- 所有项目文件必须存放在 `workspace/projects/{project_id}/` 下。
- 所有参考音频档案必须存放在 `workspace/voices/` 下。
- 不要在代码中硬编码 Windows 或 macOS 绝对路径。
- 路径处理统一使用 `pathlib.Path`。
- 文件名使用英文、数字、下划线和短横线。
- segment 文件名使用固定四位编号，例如 `0001.wav`。
- 删除文件前需要确认文件位于 workspace 目录内。

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

### 9.4 注释规范

- 注释解释“为什么这样做”，不要重复代码表面含义。
- 对 FFmpeg 命令、ASS 格式、index-tts 调用参数要写必要注释。
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
```

要求：

- API Key 不得写入代码。
- `.env` 不得提交到公开仓库。
- 默认配置应能在本地直接运行。
- 缺少外部翻译 API Key 时，中文配音和中文字幕功能仍应可用。

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

日志文件建议：

```text
workspace/projects/{project_id}/logs/app.log
workspace/projects/{project_id}/logs/tts.log
workspace/projects/{project_id}/logs/error.log
```

要求：

- 日志要能帮助定位是哪一个 segment 失败。
- 不要在日志中输出完整 API Key。
- 不要在日志中输出过长的原始全文，可截断显示。

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

第一阶段明确不做以下内容：

- 不做剪映草稿生成
- 不做剪映自动点击
- 不做完整视频合成
- 不做图片生成
- 不做分镜生成
- 不做 YouTube 自动上传
- 不做云端账号系统
- 不做多人协作
- 不做复杂权限系统
- 不做插件市场
- 不做复杂工作流编排

如需新增上述能力，应放在后续版本，不应污染第一阶段核心代码。

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
- 数据库第一阶段使用 SQLite。
- 音频处理优先使用 FFmpeg。
- 字幕生成优先直接生成 ASS 文本文件。
- index-tts 集成逻辑必须集中，不能散落在多个模块。
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
