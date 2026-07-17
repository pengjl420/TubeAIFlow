<script setup lang="ts">
import { computed, ref } from 'vue'

import { generateStoryboardLab, parseStoryboardLabSrt } from '../../api/storyboard'
import type { LabSubtitleCue, VisualScene } from '../../types/storyboard'

const srtContent = ref('')
const selectedFilename = ref('')
const cues = ref<LabSubtitleCue[]>([])
const scenes = ref<VisualScene[]>([])
const warnings = ref<string[]>([])
const modelName = ref('')
const importing = ref(false)
const generating = ref(false)
const error = ref('')
const message = ref('')

const totalDuration = computed(() => {
  if (!cues.value.length) return 0
  return Math.max(0, cues.value[cues.value.length - 1].end_ms - cues.value[0].start_ms)
})

async function chooseSrtFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  error.value = ''
  try {
    srtContent.value = await file.text()
    selectedFilename.value = file.name
    cues.value = []
    scenes.value = []
    message.value = `已读取 ${file.name}，点击“解析字幕”检查内容`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '读取字幕文件失败'
  } finally {
    input.value = ''
  }
}

async function parseSrt() {
  if (!srtContent.value.trim()) {
    error.value = '请先选择 SRT 文件或粘贴字幕内容'
    return
  }
  importing.value = true
  error.value = ''
  message.value = ''
  warnings.value = []
  try {
    cues.value = await parseStoryboardLabSrt(srtContent.value)
    scenes.value = []
    message.value = `已解析 ${cues.value.length} 条字幕；本次测试不会写入任何项目`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '解析字幕失败'
  } finally {
    importing.value = false
  }
}

async function runStoryboard() {
  if (!srtContent.value.trim()) {
    error.value = '请先选择 SRT 文件或粘贴字幕内容'
    return
  }
  generating.value = true
  error.value = ''
  message.value = 'DeepSeek 正在分析视觉语义段并生成分镜…'
  warnings.value = []
  try {
    const result = await generateStoryboardLab(srtContent.value)
    cues.value = result.cues
    scenes.value = result.scenes
    warnings.value = result.warnings
    modelName.value = result.model
    message.value = `已生成 ${result.scenes.length} 个视觉场景；结果仅保留在当前页面`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '生成分镜失败'
    message.value = ''
  } finally {
    generating.value = false
  }
}

function formatTime(milliseconds: number) {
  const totalSeconds = Math.floor(milliseconds / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const ms = milliseconds % 1000
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(ms).padStart(3, '0')}`
}

</script>

<template>
  <section class="storyboard-page">
    <div class="project-hero storyboard-hero">
      <div>
        <span class="section-eyebrow">STORYBOARD LAB</span>
        <h1>分镜测试台</h1>
        <p>独立测试 SRT 解析、视觉语义分段与 DeepSeek Storyboard，不创建或修改项目。</p>
      </div>
      <div class="page-title-actions">
        <span v-if="modelName" class="status-pill is-neutral">{{ modelName }}</span>
        <button class="primary-button" :disabled="generating || !srtContent.trim()" @click="runStoryboard">
          {{ generating ? 'DeepSeek 生成中…' : '生成视觉分镜' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger"><strong>操作未完成</strong><span>{{ error }}</span></div>
    <div v-if="message" class="alert alert-success"><strong>当前状态</strong><span>{{ message }}</span></div>
    <div v-for="warning in warnings" :key="warning" class="alert storyboard-warning">
      <strong>生成提醒</strong><span>{{ warning }}</span>
    </div>

    <div class="storyboard-input-grid">
      <article class="panel">
        <div class="section-head">
          <div>
            <span class="section-eyebrow">TEST INPUT</span>
            <h2>输入 SRT 字幕</h2>
          </div>
          <span class="status-pill is-neutral">{{ cues.length }} 条</span>
        </div>
        <label class="srt-file-picker">
          <input type="file" accept=".srt,text/plain" @change="chooseSrtFile" />
          <span class="secondary-button">选择 SRT 文件</span>
          <small>{{ selectedFilename || '也可以直接粘贴下方内容' }}</small>
        </label>
        <label class="field">
          <span>SRT 内容</span>
          <textarea
            v-model="srtContent"
            class="srt-input"
            placeholder="1&#10;00:00:00,000 --> 00:00:04,500&#10;在这里粘贴字幕内容……"
          ></textarea>
        </label>
        <div class="actions">
          <button class="primary-button" :disabled="importing" @click="parseSrt">
            {{ importing ? '解析中…' : '解析字幕' }}
          </button>
          <span class="muted">测试数据仅在当前页面使用，不写入项目数据库。</span>
        </div>
      </article>

      <aside class="panel subtitle-preview-panel">
        <div class="section-head">
          <div>
            <span class="section-eyebrow">CUES</span>
            <h2>字幕解析预览</h2>
          </div>
          <span class="muted">{{ formatTime(totalDuration) }}</span>
        </div>
        <div v-if="!cues.length" class="empty-state compact-empty">
          <h2>尚未导入字幕</h2>
          <p>选择文件或粘贴 SRT 后即可在这里检查解析结果。</p>
        </div>
        <div v-else class="cue-list">
          <div v-for="cue in cues" :key="cue.id" class="cue-row">
            <span>{{ cue.cue_index }}</span>
            <div><small>{{ formatTime(cue.start_ms) }} → {{ formatTime(cue.end_ms) }}</small><p>{{ cue.text }}</p></div>
          </div>
        </div>
      </aside>
    </div>

    <div class="section-toolbar compact-title storyboard-section-title">
      <div>
        <span class="section-eyebrow">VISUAL SCENES</span>
        <h2>结构化视觉分镜</h2>
        <p>场景时间由字幕 Cue 推导，模型只决定语义分组和视觉检索字段。</p>
      </div>
      <span class="status-pill is-neutral">{{ scenes.length }} 个场景</span>
    </div>

    <div v-if="!scenes.length" class="empty-state panel">
      <h2>等待生成视觉分镜</h2>
      <p>输入字幕后点击“生成视觉分镜”，系统将调用已配置的 DeepSeek。</p>
    </div>
    <div class="scene-card-list">
      <article v-for="scene in scenes" :key="scene.id" class="panel scene-card">
        <div class="scene-card-head">
          <div><span class="scene-index">{{ String(scene.scene_index).padStart(2, '0') }}</span><strong>{{ scene.storyboard?.visual_summary || '待生成视觉摘要' }}</strong></div>
          <div><span class="status-pill is-neutral">{{ scene.storyboard?.visual_type || scene.status }}</span><span class="scene-time">{{ formatTime(scene.start_ms) }} – {{ formatTime(scene.end_ms) }}</span></div>
        </div>
        <p class="scene-narration">{{ scene.narration }}</p>
        <div v-if="scene.storyboard" class="storyboard-detail-grid">
          <div><span>主查询</span><strong>{{ scene.storyboard.primary_query }}</strong></div>
          <div><span>类别 / 情绪</span><strong>{{ scene.storyboard.scene_category }} · {{ scene.storyboard.mood }}</strong></div>
          <div><span>必须包含</span><strong>{{ scene.storyboard.must_include.join('、') || '无' }}</strong></div>
          <div><span>应避免</span><strong>{{ scene.storyboard.avoid.join('、') || '无' }}</strong></div>
        </div>
        <div v-if="scene.storyboard?.alternative_queries.length" class="query-tags">
          <span v-for="query in scene.storyboard.alternative_queries" :key="query">{{ query }}</span>
        </div>
      </article>
    </div>
  </section>
</template>
