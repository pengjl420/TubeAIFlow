# Video Synthesis Agents

## 1. 文档目标

本文档用于定义视频制作工具中“自动生成动态画面并合成最终视频”的完整技术方案。

核心目标是：

> 以“本地素材库 + Pexels + Pixabay + FFmpeg 合成”为主链路，根据逐字稿、配音和字幕时间轴自动生成分镜、检索画面、选择素材、编排镜头并输出视频。

该方案不依赖剪映草稿格式，不把剪映作为核心生产引擎。剪映可作为后续人工精修或可选导出目标，但系统在没有剪映的情况下，也必须能够独立完成完整 MP4 视频输出。

适用内容包括：

- 人物纪录片
- 商业人物故事
- 中国企业史
- 历史故事
- 社会与经济事件解说
- 25 分钟左右的 YouTube 长视频
- 中英文字幕双轨输出
- 批量化、低人工干预的视频生产

---

## 2. 核心原则

### 2.1 系统必须独立完成视频输出

系统的核心输出不是剪映草稿，而是：

- 完整配音
- 精确字幕时间轴
- 分镜时间轴
- 画面素材
- 合成后的预览视频
- 最终可发布 MP4

剪映只能作为可选后处理工具。

### 2.2 配音分段不等于视觉分镜

逐字稿可能已经按口播拆成短句，但不能每条字幕对应一个画面。

例如四条字幕：

```text
Jack Ma was born in Hangzhou in 1964.
At the time, China was still largely closed to the outside world.
Foreign visitors were rare.
For Ma, meeting them became a way to understand another world.
```

视觉上可以合并为两个镜头：

```text
镜头 1：1960—1970 年代杭州城市、街道或旧照片
镜头 2：年轻人与外国游客交流、练习英语
```

系统必须先将字幕合并为“视觉语义段”，再检索画面。

### 2.3 真实素材优先，AI 画面仅做补充

画面优先级：

1. 本地已审核素材
2. 本地已下载的 Pexels、Pixabay 素材
3. Pexels 在线搜索
4. Pixabay 在线搜索
5. 相关静态图片动态化
6. 主题化本地兜底素材
7. 纯风景空镜
8. 可选 AI 图片或 AI 视频

AI 视频不作为基础生产方式，以避免成本过高、人物不一致、事实错误和整体 AI 感过强。

### 2.4 “接口有结果”不等于“素材合格”

Pexels 或 Pixabay 返回结果，只说明关键词命中了候选素材，不代表画面一定适合。

系统必须区分：

```text
NO_RESULT       没有返回候选
LOW_RELEVANCE   有候选，但相关度不足
QUALIFIED       候选通过语义和质量检查
```

只有 `QUALIFIED` 素材可以直接使用。

### 2.5 向量检索负责“相关”，规则负责“正确”

- 向量匹配：判断画面是否大致符合语义
- 实体和标签：判断人物、公司、地点、年代是否正确
- 技术规则：判断分辨率、比例、时长、清晰度是否可用
- 去重规则：避免同一镜头或相似镜头频繁出现

---

## 3. 总体流程

```text
逐字稿
  ↓
口播分段
  ↓
逐段配音
  ↓
完整音频合成
  ↓
真实音频时长
  ↓
中文字幕时间轴
  ↓
英文字幕时间轴
  ↓
字幕合并为视觉语义段
  ↓
AI 分镜分析
  ↓
生成视觉查询、实体、场景类型和兜底类型
  ↓
搜索本地向量素材库
  ↓
未命中时搜索 Pexels / Pixabay
  ↓
候选缩略图向量重排
  ↓
下载合格视频
  ↓
视频切镜、抽帧、向量化、入库
  ↓
镜头时长编排
  ↓
素材裁剪、缩放、运镜、转场
  ↓
FFmpeg 合成画面、配音、字幕、音乐和音效
  ↓
自动质量检查
  ↓
预览视频
  ↓
人工故事板复核
  ↓
最终导出 MP4
```

---

## 4. Agent 划分

系统可以采用多个逻辑 Agent，也可以由一个后端服务按模块实现。Agent 是职责边界，不要求必须调用多个大模型。

### 4.1 ScriptNormalizationAgent

职责：

- 清理逐字稿中的无用符号
- 保留自然口播标点
- 校验空行、异常字符和重复文本
- 保持原始段落 ID

输入：

```json
{
  "script": "原始逐字稿"
}
```

输出：

```json
{
  "normalized_script": "清理后的逐字稿",
  "paragraphs": []
}
```

### 4.2 VoiceSegmentAgent

职责：

- 将长文拆成适合 TTS 的短句
- 保留语义完整性
- 避免过度切分
- 为每句生成稳定 ID

建议：

- 英文单句通常控制在 8—22 个单词
- 中文单句通常控制在 10—35 个汉字
- 不因逗号机械拆分
- 同一逻辑单位尽量保持完整

### 4.3 AudioSynthesisAgent

职责：

- 调用本地 TTS
- 按段生成音频
- 记录失败状态
- 支持单段重试
- 保存每段真实时长

输出：

```json
{
  "segment_id": "seg_0001",
  "audio_path": "audio/seg_0001.wav",
  "duration_ms": 5280,
  "status": "success"
}
```

### 4.4 AudioAssemblyAgent

职责：

- 统一采样率、声道和响度
- 去除头尾异常静音
- 加入段间停顿
- 拼接完整音频
- 输出每段在完整音频中的绝对时间

建议音频规范：

```text
采样率：48 kHz
声道：单声道或双声道统一
响度：约 -16 LUFS（YouTube 口播可调整）
峰值：不高于 -1 dBTP
```

### 4.5 SubtitleTimelineAgent

职责：

- 根据真实语音时长生成字幕时间轴
- 生成中文字幕
- 翻译英文字幕
- 保持中英文时间轴一致
- 输出 SRT、ASS 和内部 JSON

### 4.6 VisualSceneGroupingAgent

职责：

- 将连续字幕合并成视觉语义段
- 决定镜头切换点
- 避免每句字幕切一次画面

建议时长：

| 类型 | 建议镜头长度 |
|---|---:|
| 开头强钩子 | 3—5 秒 |
| 普通叙事镜头 | 5—10 秒 |
| 历史照片 | 6—12 秒 |
| 地图、时间线 | 6—12 秒 |
| 重大事件 | 8—15 秒 |
| 情绪过渡 | 4—8 秒 |

合并原则：

- 同一人物、地点、事件连续出现时可以合并
- 发生时间跳跃时切镜
- 叙事从事实转为分析时切镜
- 主体变化时切镜
- 开头 30 秒适当加快节奏

### 4.7 StoryboardAgent

职责：

根据视觉语义段生成结构化分镜数据。

输出示例：

```json
{
  "scene_id": "scene_0012",
  "start_ms": 68500,
  "end_ms": 78100,
  "duration_ms": 9600,
  "subtitle_ids": ["sub_0018", "sub_0019"],
  "narration": "In 1995, Jack Ma traveled to the United States.",
  "visual_summary": "A Chinese traveler arriving in the United States during the mid-1990s",
  "visual_type": "historical_reconstruction",
  "entities": ["Jack Ma", "United States"],
  "locations": ["United States"],
  "time_period": "1995",
  "scene_category": "travel",
  "mood": "curious",
  "shot_preference": "wide_or_medium",
  "primary_query": "1990s international airport traveler arriving in America",
  "alternative_queries": [
    "international travel airport 1990s",
    "Chinese traveler arriving at US airport",
    "1995 American airport archival style"
  ],
  "fallback_category": "travel",
  "fallback_mood": "neutral",
  "must_include": ["airport", "traveler"],
  "avoid": ["modern smartphone", "European landmark"],
  "confidence": 0.83
}
```

### 4.8 QueryExpansionAgent

职责：

- 将旁白转换为可视化查询
- 生成精确、语义和通用三层搜索词
- 优先生成英文查询
- 删除不可视化的抽象语言

例如：

```text
旁白：
His success created pressures he could no longer control.
```

转换为：

```json
{
  "primary_query": "business executive alone in a dark office at night",
  "secondary_queries": [
    "empty corporate boardroom",
    "financial pressure office",
    "serious businessman looking out office window"
  ],
  "fallback_category": "crisis"
}
```

### 4.9 LocalAssetRetrievalAgent

职责：

- 将分镜查询转换为多模态向量
- 检索本地素材向量库
- 进行元数据硬过滤
- 返回 Top K 候选

### 4.10 RemoteAssetSearchAgent

职责：

- 本地没有合格结果时调用 Pexels 和 Pixabay
- 搜索候选视频
- 获取缩略图和预览图
- 先对缩略图向量排序
- 只下载最终候选
- 保存来源、作者、平台 ID 和授权信息

### 4.11 AssetIngestionAgent

职责：

下载新素材后执行：

- 文件哈希去重
- 技术信息读取
- 镜头切分
- 关键帧抽取
- 画面向量生成
- 结构化描述生成
- 写入数据库和 FAISS

### 4.12 AssetRankingAgent

职责：

- 多路召回结果合并
- 计算最终评分
- 应用冲突惩罚和重复惩罚
- 输出最终素材或触发兜底

### 4.13 FallbackAssetAgent

职责：

- 当本地和外部素材都不合格时选择兜底素材
- 优先选择主题化兜底，而不是随机风景
- 控制同类兜底镜头重复

### 4.14 TimelineCompositionAgent

职责：

- 将素材放入精确时间轴
- 决定素材裁剪区间
- 处理素材不足时长
- 配置图片运镜、视频速度和转场

### 4.15 FFmpegRenderAgent

职责：

- 生成中间视频片段
- 拼接主画面
- 合成音频
- 烧录或外挂字幕
- 添加背景音乐、音效、转场
- 输出预览和最终视频

### 4.16 QualityAssuranceAgent

职责：

自动检查：

- 视频时长与配音时长
- 黑屏
- 静帧过长
- 音频峰值
- 字幕越界
- 字幕时间冲突
- 素材重复
- 分辨率
- 帧率
- 编码完整性
- 文件是否可播放

---

## 5. 本地素材库设计

### 5.1 素材来源

本地素材库主要由以下内容构成：

1. Pexels 已下载视频
2. Pixabay 已下载视频
3. 人工整理的主题化兜底视频
4. 可选自有拍摄素材
5. 可选历史档案和公开授权素材

第一阶段只需要对 Pexels 和 Pixabay 下载的视频进行完整向量化。

兜底素材可以先使用人工分类，不强制向量化。

### 5.2 目录结构

```text
assets/
├── downloaded/
│   ├── pexels/
│   └── pixabay/
├── fallback/
│   ├── business/
│   ├── technology/
│   ├── finance/
│   ├── history/
│   ├── crisis/
│   ├── travel/
│   ├── city/
│   ├── transition/
│   └── landscape/
├── thumbnails/
├── keyframes/
├── proxy/
└── metadata/
```

### 5.3 主题化兜底分类

#### 商业

- 办公楼
- 会议室
- 商务区
- 员工办公
- 文件和电脑
- 夜间办公室

#### 科技

- 服务器
- 芯片
- 电路板
- 手机生产
- 网络机房
- 工程师背影

#### 金融

- 股票图表
- 金融中心
- 交易屏幕
- 合同文件
- 银行建筑

#### 历史

- 旧报纸
- 胶片纹理
- 老式电视
- 火车
- 旧街道
- 档案文件

#### 危机与转折

- 空会议室
- 雨夜玻璃
- 昏暗走廊
- 关闭的办公室
- 一个人的背影

#### 纯风景

仅用于：

- 章节过渡
- 时间流逝
- 人生感悟
- 结尾总结
- 情绪舒缓

纯风景不能作为所有搜索失败场景的统一默认画面。

---

## 6. 素材向量化方案

### 6.1 推荐方案

正式版推荐：

```text
Qwen3-VL-Embedding-2B
+ 结构化画面描述
+ FAISS
+ SQLite
```

性能优先版本可采用：

```text
SigLIP 2 Base 快速预筛
+ Qwen3-VL-Embedding-2B 正式建库
```

MVP 可先采用：

```text
SigLIP 2 Base
+ FAISS IndexFlatIP
+ SQLite
```

### 6.2 为什么不能整条视频只生成一个向量

一个 30 秒素材可能同时包含城市、办公室、仓库和道路。

整条视频只生成一个向量会把多个场景混合，导致检索不精确。

正确流程：

```text
视频
→ 镜头切分
→ 每个镜头抽取关键帧
→ 每个镜头独立生成向量
```

### 6.3 镜头切分

推荐使用 PySceneDetect。

规则：

- 小于 1.5 秒的镜头与相邻镜头合并
- 大于 15 秒的镜头根据画面变化或固定间隔继续切分
- Pexels、Pixabay 中短于 12 秒且无明显切镜的视频，可整条作为一个镜头

### 6.4 关键帧抽取

建议：

| 镜头时长 | 抽帧数量 |
|---:|---:|
| 1.5—4 秒 | 3 帧 |
| 4—8 秒 | 4 帧 |
| 8—15 秒 | 6 帧 |
| 15 秒以上 | 8 帧 |

抽取位置可按百分比：

```text
10%、25%、45%、65%、85%
```

应排除：

- 黑屏
- 转场帧
- 运动模糊
- 过曝
- 欠曝
- 大量重复帧

### 6.5 向量生成

推荐输入固定任务指令：

```text
Represent this video shot for retrieval by its visible subjects,
actions, environment, location type, mood, time of day,
camera composition, and suitable documentary use cases.
Ignore audio and avoid inferring identities that are not visually confirmed.
```

建议参数：

```text
模型：Qwen3-VL-Embedding-2B
帧数：4—6
向量维度：768
存储格式：Float16
索引：FAISS IndexFlatIP
```

### 6.6 结构化描述

可使用 Qwen3-VL-2B-Instruct 离线生成：

```json
{
  "caption": "A modern Asian office with employees working at computers at night.",
  "scene": "office",
  "subjects": ["office workers", "computers"],
  "actions": ["working", "typing"],
  "location_type": "corporate office",
  "time_of_day": "night",
  "mood": ["serious", "busy"],
  "shot_type": "wide shot",
  "camera_motion": "slow pan",
  "people_count": 5,
  "visible_text": [],
  "logos": [],
  "documentary_topics": ["business", "technology"],
  "negative_topics": ["medical", "education"]
}
```

向量负责语义召回，结构化描述负责过滤和解释。

### 6.7 低成本处理策略

下载新素材后：

1. 先生成向量，素材立即可搜索
2. 系统空闲时再生成详细结构化描述
3. 只对最终下载的视频做正式向量化
4. Pexels、Pixabay 候选缩略图先用轻量模型预筛

---

## 7. 数据存储设计

### 7.1 media_files 表

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
    created_at DATETIME,
    downloaded_at DATETIME
);
```

### 7.2 shots 表

```sql
CREATE TABLE shots (
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
    last_used_at DATETIME,
    FOREIGN KEY(media_id) REFERENCES media_files(id)
);
```

### 7.3 keyframes 表

```sql
CREATE TABLE keyframes (
    id INTEGER PRIMARY KEY,
    shot_id INTEGER NOT NULL,
    timestamp_ms INTEGER NOT NULL,
    image_path TEXT NOT NULL,
    vector_id INTEGER,
    sharpness_score REAL,
    brightness_score REAL,
    FOREIGN KEY(shot_id) REFERENCES shots(id)
);
```

### 7.4 asset_usage 表

```sql
CREATE TABLE asset_usage (
    id INTEGER PRIMARY KEY,
    project_id TEXT NOT NULL,
    scene_id TEXT NOT NULL,
    shot_id INTEGER NOT NULL,
    used_start_ms INTEGER,
    used_end_ms INTEGER,
    created_at DATETIME
);
```

### 7.5 search_cache 表

```sql
CREATE TABLE search_cache (
    id INTEGER PRIMARY KEY,
    platform TEXT NOT NULL,
    normalized_query TEXT NOT NULL,
    response_json TEXT NOT NULL,
    expires_at DATETIME,
    created_at DATETIME
);
```

---

## 8. 本地向量检索流程

### 8.1 查询预处理

分镜描述不能直接使用完整旁白。

例如：

```text
By 2014, Alibaba had become one of the most powerful symbols of China's growing digital economy.
```

转换成：

```text
Chinese e-commerce employees working in a modern technology office,
online shopping warehouse, Hangzhou technology district
```

### 8.2 三路召回

#### 路线一：视觉向量召回

将视觉查询编码为向量，从 FAISS 取 Top 50。

#### 路线二：描述文本召回

对 `caption` 使用：

- SQLite FTS5
- BM25
- 或文本向量

#### 路线三：元数据过滤

例如：

```json
{
  "orientation": "landscape",
  "min_width": 1920,
  "scene": "office",
  "time_of_day": "night",
  "people_count_max": 1
}
```

### 8.3 综合评分

```text
最终分数 =
视觉向量相似度 × 55%
+ 描述文本相似度 × 20%
+ 标签匹配 × 15%
+ 技术质量 × 10%
- 重复使用惩罚
- 事实冲突惩罚
- 年代冲突惩罚
- 地点冲突惩罚
```

### 8.4 重复控制

规则建议：

- 同一视频内，同一 shot 禁止重复
- 同一原始视频连续使用禁止
- 60 秒内禁止出现视觉高度相似镜头
- 最近 5 条视频频繁使用的素材扣分
- pHash 高度相似素材只保留一个

---

## 9. Pexels 与 Pixabay 搜索流程

### 9.1 搜索顺序

```text
本地向量库
→ Pexels
→ Pixabay
→ 静态图片动态化
→ 主题化兜底素材
→ 纯风景空镜
```

### 9.2 查询分层

每个分镜生成三层查询：

#### 精确查询

```text
Huawei telecommunications equipment factory
```

#### 语义查询

```text
Chinese telecommunications engineers working
```

#### 通用视觉查询

```text
modern network equipment factory
telecom server room
engineers installing communications hardware
```

每个分镜最多搜索 2—3 轮，避免接口调用失控。

### 9.3 不要直接下载全部候选

推荐流程：

```text
搜索返回 20—40 个候选
→ 获取缩略图或预览图
→ 对缩略图向量化
→ 选 Top 3—5
→ 只下载最终候选视频
→ 对完整视频切镜和向量化
```

### 9.4 查询缓存

必须实现：

- 查询词标准化
- 搜索结果缓存
- 同义查询合并
- 下载文件哈希去重
- 同一平台资产 ID 去重

标准化示例：

```text
Chinese modern office workers
chinese office workers modern
modern Chinese corporate office
```

可以归并到同一个语义查询缓存键。

### 9.5 合格判断

候选素材必须检查：

- 语义相关度
- 横屏比例
- 分辨率
- 视频时长
- 水印和内嵌文字
- 错误人物或品牌
- 年代冲突
- 地区冲突
- 本期是否已使用
- 最近视频是否高频使用

输出：

```json
{
  "status": "qualified",
  "semantic_score": 0.81,
  "quality_score": 0.92,
  "conflict_score": 0.03,
  "source": "pexels"
}
```

或：

```json
{
  "status": "fallback_required",
  "reason": "No candidate passed semantic threshold",
  "fallback_category": "finance"
}
```

---

## 10. 兜底策略

### 10.1 兜底优先级

```text
相关静态图片动态化
→ 主题化视频兜底
→ 地点类中性素材
→ 情绪类中性素材
→ 纯风景
```

### 10.2 兜底选择字段

StoryboardAgent 输出：

```json
{
  "fallback_category": "technology",
  "fallback_mood": "serious",
  "fallback_motion": "slow",
  "avoid_recently_used": true
}
```

### 10.3 纯风景使用限制

纯风景只应出现在：

- 章节切换
- 时间流逝
- 结尾总结
- 人生感悟
- 情绪缓冲

不应在具体商业事件、人物经历或公司冲突中随机插入。

---

## 11. 分镜时间轴编排

### 11.1 素材时长大于分镜时长

处理方式：

- 从视觉质量最高区间裁剪
- 优先保留动作完整区间
- 避免从镜头切换点附近开始

### 11.2 素材时长小于分镜时长

优先级：

1. 降低到最低允许速度，例如 0.85 倍
2. 补充同主题第二镜头
3. 使用最后一帧轻微推拉
4. 插入相关静态图
5. 不建议明显循环视频

### 11.3 静态图片动态化

可以使用：

- 缓慢放大
- 缓慢缩小
- 左右平移
- 轻微景深
- 2.5D 视差
- 轻微胶片颗粒

建议缩放范围：

```text
100% → 106% 或 108%
```

不宜过快，以免出现廉价模板感。

### 11.4 转场

普通纪录片建议：

- 硬切为主
- 叠化为辅
- 章节过渡使用黑场、淡入淡出或地图动画
- 避免大量花哨转场

建议转场时长：

```text
0.2—0.5 秒
```

---

## 12. FFmpeg 合成架构

### 12.1 标准输出参数

```text
分辨率：1920×1080
帧率：30 fps
编码：H.264
像素格式：yuv420p
音频：AAC 48 kHz
容器：MP4
```

### 12.2 每个镜头先标准化

每个素材先转为统一规格：

- 1920×1080
- 30 fps
- H.264
- 固定像素格式
- 删除原素材音轨
- 精确裁剪到目标时长

### 12.3 横屏视频处理

优先使用：

```text
scale + crop
```

避免拉伸变形。

### 12.4 竖屏视频处理

默认不使用。

必须使用时：

- 主画面居中
- 背景使用同画面模糊放大
- 或使用画中画模板

### 12.5 图片处理

使用 `zoompan` 或预先生成动态视频片段。

### 12.6 中间片段策略

推荐为每个视觉场景生成独立中间片段：

```text
renders/scenes/scene_0001.mp4
renders/scenes/scene_0002.mp4
```

所有片段规格统一后，再通过 concat 拼接。

优点：

- 单场景失败可重试
- 替换素材无需重渲染整条视频
- 易于生成故事板预览
- 支持并行渲染

### 12.7 字幕方式

两种模式：

#### 模式 A：外挂字幕

输出：

- video.mp4
- zh.srt
- en.srt

优点：可切换语言。

#### 模式 B：烧录字幕

使用 ASS 统一样式。

建议支持：

- 中文字幕
- 英文字幕
- 中英双语字幕
- 字体、字号、边距、描边、阴影

### 12.8 音频轨道

建议结构：

```text
A1：完整配音
A2：背景音乐
A3：音效
```

背景音乐自动压低：

- 配音存在时降低
- 章节过渡可略微提高
- 结尾可渐强

---

## 13. 项目文件结构

```text
project/
├── project.json
├── script/
│   ├── original.txt
│   ├── normalized.txt
│   └── segments.json
├── audio/
│   ├── segments/
│   ├── narration.wav
│   └── bgm.wav
├── subtitles/
│   ├── zh.srt
│   ├── en.srt
│   ├── zh.ass
│   └── en.ass
├── storyboard/
│   ├── scenes.json
│   ├── candidates.json
│   └── storyboard.html
├── media/
│   ├── selected/
│   ├── downloaded/
│   └── images/
├── renders/
│   ├── scenes/
│   ├── preview.mp4
│   └── final.mp4
├── logs/
└── reports/
    ├── qa.json
    ├── asset_sources.csv
    └── render_report.json
```

---

## 14. 故事板审核页面

自动生成 `storyboard.html`，显示：

| 时间 | 字幕 | 当前画面 | 来源 | 分数 | 状态 | 操作 |
|---|---|---|---|---:|---|---|
| 00:00—00:06 | Jack Ma seemed untouchable | 马云演讲候选 | 本地库 | 0.91 | 合格 | 替换 |
| 00:06—00:12 | Ant Group prepared for IPO | 金融中心 | Pexels | 0.76 | 待确认 | 替换 |
| 00:12—00:18 | The IPO was suspended | 股票下跌 | Pixabay | 0.68 | 低置信度 | 重搜 |

建议突出：

- 低于阈值的镜头
- 使用兜底素材的镜头
- 人物或年代可能错误的镜头
- 同类素材重复过多的镜头
- 纯风景镜头

人工只需重点复核低置信度场景。

---

## 15. 自动质量检查

### 15.1 时间轴检查

- 所有分镜首尾连续
- 不允许负时长
- 不允许画面轨道空洞
- 视频总时长与配音误差小于 100 ms
- 字幕不得越过音频结束时间

### 15.2 画面检查

- 黑屏帧比例
- 长时间静帧
- 重复画面
- 分辨率不足
- 纵横比错误
- 转场异常
- 画面编码损坏

### 15.3 音频检查

- 音频峰值
- LUFS
- 静音过长
- 爆音
- 左右声道异常
- 配音与背景音乐比例

### 15.4 字幕检查

- 空字幕
- 字幕重叠
- 每行过长
- 中英文数量不一致
- 时间轴不一致
- 特殊符号
- 超出安全区域

### 15.5 素材来源检查

最终生成：

```text
素材平台
素材 ID
作者
原始页面
下载时间
使用场景
```

---

## 16. 性能与成本控制

### 16.1 本地优先

每个分镜先检索本地向量库。

本地有合格素材时，不调用 Pexels 或 Pixabay。

### 16.2 缓存优先

必须缓存：

- 查询结果
- 缩略图
- 已下载视频
- 视频哈希
- 关键帧
- 向量
- 结构化描述

### 16.3 模型串行加载

针对 RTX 4060 Ti 8GB：

```text
阶段一：加载 Embedding 模型，批量向量化
阶段二：卸载 Embedding，加载描述模型
阶段三：描述完成后卸载
```

避免多个 VLM 同时常驻显存。

### 16.4 批量策略

- 同一章节查询合并
- 常见场景提前建立素材池
- 新下载素材一次处理，长期复用
- 对候选缩略图使用轻量模型
- 只对低置信度场景启用重排模型

### 16.5 API 调用控制

系统应配置：

```json
{
  "max_remote_search_rounds_per_scene": 3,
  "max_candidates_per_platform": 30,
  "max_full_video_downloads_per_scene": 3,
  "prefer_local_assets": true,
  "search_cache_ttl_hours": 24
}
```

---

## 17. 配置文件建议

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
  embedding_dimension: 768
  similarity_threshold: null
  use_dynamic_threshold: true

remote_search:
  providers:
    - pexels
    - pixabay
  max_rounds: 3
  preview_candidates: 30
  full_download_candidates: 3

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

`landscape_max_ratio` 用于限制纯风景镜头在整条视频中的占比。

---

## 18. 阈值校准

不要直接写死一个通用向量相似度阈值。

不同模型和素材类型的分数分布不同。

推荐建立测试集：

- 100 条分镜描述
- 每条人工标注 3—5 个合格素材
- 统计 Top 1、Top 3、Top 5 命中率
- 对人物、商业、科技、金融、历史、情绪分别统计

核心指标：

```text
Top 1 准确率
Top 3 召回率
Top 5 召回率
错误人物率
错误年代率
纯风景使用率
人工替换率
单条视频平均人工处理时间
```

---

## 19. MVP 实施范围

第一阶段建议只完成：

1. 视觉语义段合并
2. Storyboard JSON
3. 英文视觉查询生成
4. Pexels 和 Pixabay 搜索
5. 缩略图语义排序
6. 下载候选视频
7. 本地视频切镜
8. SigLIP 2 或 Qwen3-VL 向量化
9. FAISS 检索
10. 主题化兜底素材
11. FFmpeg 场景片段合成
12. 完整视频拼接
13. 中英文字幕合成
14. 故事板页面
15. 低置信度人工替换

第一阶段暂时不做：

- 剪映草稿
- 复杂 AI 视频生成
- 自动人物识别
- 复杂新闻档案搜索
- 多模型重排
- 高级地图和数据动画

---

## 20. 第二阶段优化

1. Qwen3-VL 结构化画面描述
2. 文本描述与视觉向量双路检索
3. 低置信度 Reranker
4. 图片动态化模板
5. 地图、时间线和数据动画模板
6. 人物、公司和地点实体库
7. 历史素材来源接入
8. 素材复用统计
9. 自动学习人工替换偏好
10. 可选剪映草稿导出器

---

## 21. 第三阶段优化

1. AI 图片生成补充
2. 章节开头 AI 视频镜头
3. 自动人物关系图
4. 自动新闻标题动画
5. 自动股票和时间线图表
6. 多语言视觉查询
7. 频道视觉风格模板
8. 多机并行渲染
9. 分布式素材库
10. Web 可视化时间轴编辑器

---

## 22. 风险与应对

### 22.1 Pexels、Pixabay 没有准确素材

应对：

- 多层查询扩展
- 使用语义替代画面
- 静态图片动态化
- 主题化兜底
- 纯风景仅最终兜底

### 22.2 返回结果泛化

应对：

- 缩略图向量重排
- 结构化标签过滤
- 实体冲突惩罚
- 低置信度人工复核

### 22.3 素材重复

应对：

- shot 使用记录
- pHash 去重
- 向量近似去重
- 最近视频复用惩罚

### 22.4 API 配额不足

应对：

- 本地库优先
- 搜索缓存
- 查询合并
- 下载复用
- 限制每场景搜索次数

### 22.5 8GB 显存不足

应对：

- 限制帧数
- 降低批次
- 使用量化模型
- 模型串行加载
- 使用 SigLIP 预筛

### 22.6 合成失败

应对：

- 每个场景独立渲染
- 单场景失败重试
- 统一中间编码规格
- 最终拼接前使用 ffprobe 校验

---

## 23. 最终推荐架构

```text
                           ┌─ 本地向量素材库
                           │
逐字稿 → 配音 → 字幕时间轴 → AI 视觉分镜
                           │
                           ├─ Pexels
                           ├─ Pixabay
                           ├─ 相关静态图片
                           ├─ 主题化兜底素材
                           └─ 纯风景最终兜底
                                    ↓
                              候选向量重排
                                    ↓
                             规则过滤与去重
                                    ↓
                              统一时间轴 JSON
                                    ↓
                         FFmpeg 场景片段独立渲染
                                    ↓
                              完整视频拼接
                                    ↓
                         配音 + 字幕 + 音乐 + 音效
                                    ↓
                                自动 QA
                                    ↓
                              故事板人工复核
                                    ↓
                                最终 MP4
```

---

## 24. 最终实施结论

本项目的视频合成模块应遵循以下定位：

> 系统负责理解内容、生成视觉分镜、搜索和管理素材、建立向量库、匹配镜头、编排时间轴并通过 FFmpeg 输出完整视频。

核心技术路线：

```text
本地素材库
+ Pexels
+ Pixabay
+ 多模态向量检索
+ 结构化元数据
+ 主题化兜底素材
+ FFmpeg 合成
```

剪映不应成为核心依赖。

最优先建设的能力不是 AI 视频生成，而是：

1. 字幕到视觉分镜的转换
2. 本地素材向量库
3. Pexels、Pixabay 候选搜索和缓存
4. 候选缩略图重排
5. 主题化兜底体系
6. 精确时间轴编排
7. FFmpeg 稳定合成
8. 故事板和低置信度人工审核

随着视频持续生产，本地素材库会不断增长，远程搜索次数和人工替换成本会逐步下降，最终形成可复用、可扩展、低成本、低维护的视频自动化生产系统。
