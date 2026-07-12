<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import { API_BASE_URL } from '../api/client'
import { mergeProjectAudio } from '../api/exports'
import { composeProjectVideo } from '../api/videos'
import {
  createSegments,
  getProject,
  getProjectOutputs,
  saveOutputSettings,
  saveScript,
  type ProjectOutputs,
} from '../api/projects'
import { listSegments, updateSegment } from '../api/segments'
import { getTtsStatus, regenerateSegmentTts, startTts, type TtsStatus } from '../api/tts'
import AudioPlayer from '../components/AudioPlayer.vue'
import type { Project } from '../types/project'
import type { Segment } from '../types/segment'

const route = useRoute()
const projectId = String(route.params.id)
const project = ref<Project | null>(null)
const outputs = ref<ProjectOutputs | null>(null)
const segments = ref<Segment[]>([])
const editedText = reactive<Record<string, string>>({})
const busySegments = reactive<Record<string, boolean>>({})
const scriptText = ref('')
const outputFilename = ref('')
const loading = ref(false)
const ttsRunning = ref(false)
const mergingAudio = ref(false)
const composingVideo = ref(false)
const oneClickGenerating = ref(false)
const savingFilename = ref(false)
const readingScriptFile = ref(false)
const scriptDragActive = ref(false)
const error = ref('')
const message = ref('')
let pollTimer: number | undefined

const ttsStatus = ref<TtsStatus>({ total: 0, completed: 0, failed: 0, pending: 0 })

const projectConfig = computed(() => {
  if (!project.value?.config_json) return {}
  try {
    const data = JSON.parse(project.value.config_json)
    return data && typeof data === 'object' ? data : {}
  } catch {
    return {}
  }
})

const referenceAudioName = computed(() => {
  const filename = projectConfig.value.reference_audio_filename
  return typeof filename === 'string' ? filename : ''
})

const referenceAudioUrl = computed(() => {
  if (!project.value?.reference_audio_path) return ''
  return `${API_BASE_URL}/projects/${projectId}/reference-audio?v=${encodeURIComponent(project.value.updated_at)}`
})

const hasOutputFilename = computed(() => {
  const filename = projectConfig.value.output_filename
  return typeof filename === 'string' && filename.trim().length > 0
})

const ttsPercent = computed(() => {
  const total = ttsStatus.value.total || 0
  return total ? Math.round(((ttsStatus.value.completed || 0) / total) * 100) : 0
})

const currentSegmentText = computed(() => {
  const currentId = ttsStatus.value.progress?.current_segment_id
  if (!currentId) return ''
  const segment = segments.value.find((item) => item.segment_id === currentId)
  return segment ? `#${segment.segment_id} ${segment.text_zh}` : `#${currentId}`
})

function fallbackFinalAudioPath() {
  const dir = outputs.value?.output_dir || project.value?.output_dir || ''
  if (!dir || !outputFilename.value.trim()) return ''
  return `${dir.replace(/[\\/]$/, '')}\\${outputFilename.value.trim()}.wav`
}

const finalAudioPath = computed(() => {
  if (!hasOutputFilename.value) return ''
  return outputs.value?.final_audio_path || fallbackFinalAudioPath()
})

const mediaVideoDir = computed(() => {
  const value = projectConfig.value.media_video_dir
  return typeof value === 'string' ? value : ''
})

const finalVideoPath = computed(() => {
  if (!hasOutputFilename.value) return ''
  const dir = outputs.value?.output_dir || project.value?.output_dir || ''
  if (!dir || !outputFilename.value.trim()) return outputs.value?.final_video_path || ''
  return outputs.value?.final_video_path || `${dir.replace(/[\\/]$/, '')}\\${outputFilename.value.trim()}.mp4`
})

function segmentAudioUrl(segment: Segment) {
  if (!segment.audio_path) return ''
  const version = encodeURIComponent(segment.updated_at || segment.audio_path)
  return `${API_BASE_URL}/projects/${projectId}/segments/${segment.segment_id}/audio?v=${version}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    project.value = await getProject(projectId)
    fillOutputFilename()
    await refreshSegments()
    await Promise.all([refreshTtsStatus(), refreshOutputs()])
  } catch (err) {
    error.value = err instanceof Error ? err.message : '项目加载失败'
  } finally {
    loading.value = false
  }
}

function fillOutputFilename() {
  const filename = projectConfig.value.output_filename
  outputFilename.value = typeof filename === 'string' ? filename : ''
}

function getFilenameStem(filename: string) {
  return filename.replace(/\.[^/.]+$/, '').trim()
}

async function readTextFile(file: File) {
  const buffer = await file.arrayBuffer()
  const encodings = ['utf-8', 'gb18030', 'gbk', 'big5']

  for (const encoding of encodings) {
    try {
      const text = new TextDecoder(encoding, { fatal: true }).decode(buffer)
      if (text.trim().length > 0 || file.size === 0) return text
    } catch {
      // Try the next common text encoding.
    }
  }

  return new TextDecoder().decode(buffer)
}

async function applyScriptFile(file: File) {
  readingScriptFile.value = true
  error.value = ''
  message.value = ''
  try {
    scriptText.value = await readTextFile(file)
    const filenameStem = getFilenameStem(file.name)
    if (filenameStem) {
      outputFilename.value = filenameStem
      await ensureFilenameSaved()
    }
    message.value = filenameStem ? `已读取 ${file.name}，当前生成文件名已保存` : `已读取 ${file.name}`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '文件读取失败，请确认拖入的是文本内容'
  } finally {
    readingScriptFile.value = false
    scriptDragActive.value = false
  }
}

async function handleScriptDrop(event: DragEvent) {
  scriptDragActive.value = false
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  await applyScriptFile(file)
}

async function refreshSegments() {
  segments.value = await listSegments(projectId)
  for (const segment of segments.value) {
    editedText[segment.segment_id] = segment.text_zh
  }
}

async function refreshTtsStatus() {
  ttsStatus.value = await getTtsStatus(projectId)
  applyLiveSegmentStatus()
  ttsRunning.value = ttsStatus.value.progress?.status === 'running'
}

function applyLiveSegmentStatus() {
  const liveSegments = ttsStatus.value.segments || []
  if (!liveSegments.length) return
  const liveById = new Map(liveSegments.map((item) => [item.segment_id, item]))
  segments.value = segments.value.map((segment) => {
    const live = liveById.get(segment.segment_id)
    if (!live) return segment
    return {
      ...segment,
      status: live.status || segment.status,
      audio_path: live.audio_path || segment.audio_path,
      duration: live.duration ?? segment.duration,
      error_message: live.error_message ?? segment.error_message,
      updated_at: live.updated_at || segment.updated_at,
    }
  })
}

async function refreshOutputs() {
  outputs.value = await getProjectOutputs(projectId)
}

async function refreshAfterChange() {
  project.value = await getProject(projectId)
  fillOutputFilename()
  await refreshSegments()
  await Promise.all([refreshTtsStatus(), refreshOutputs()])
}

function startPolling() {
  stopPolling()
  pollTimer = window.setInterval(async () => {
    try {
      await refreshTtsStatus()
      if (!ttsRunning.value) {
        stopPolling()
        await refreshAfterChange()
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : '刷新进度失败'
    }
  }, 1500)
}

function stopPolling() {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

async function ensureFilenameSaved() {
  if (!project.value) throw new Error('项目未加载')
  project.value = await saveOutputSettings(
    projectId,
    outputs.value?.output_dir || project.value.output_dir || '',
    outputFilename.value.trim(),
  )
  fillOutputFilename()
  await refreshOutputs()
}

async function saveCurrentFilename() {
  savingFilename.value = true
  error.value = ''
  message.value = ''
  const wasBlank = !outputFilename.value.trim()
  try {
    await ensureFilenameSaved()
    message.value = wasBlank ? '已使用当前时间戳作为文件名' : '当前生成文件名已保存'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '文件名保存失败'
  } finally {
    savingFilename.value = false
  }
}

async function submitScript() {
  if (!scriptText.value.trim()) {
    error.value = '请先粘贴逐字稿'
    return
  }
  error.value = ''
  message.value = ''
  try {
    await ensureFilenameSaved()
    project.value = await saveScript(projectId, scriptText.value)
    await refreshOutputs()
    message.value = '脚本已保存'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '逐字稿保存失败'
  }
}

async function splitSegments() {
  error.value = ''
  message.value = ''
  try {
    await ensureFilenameSaved()
    await createSegments(projectId)
    await refreshAfterChange()
    message.value = '切段已生成'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '切段失败'
  }
}

async function runTts() {
  error.value = ''
  message.value = ''
  if (!project.value?.reference_audio_path) {
    error.value = '请先配置项目参考音频后再开始 TTS'
    return
  }
  ttsRunning.value = true
  startPolling()
  try {
    await ensureFilenameSaved()
    await startTts(projectId)
    await refreshAfterChange()
    message.value = '分段音频已生成，可以合并完整音频'
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'TTS 启动失败'
    await refreshAfterChange()
  } finally {
    ttsRunning.value = false
    stopPolling()
  }
}

async function mergeAudio() {
  error.value = ''
  message.value = ''
  mergingAudio.value = true
  try {
    await ensureFilenameSaved()
    const result = await mergeProjectAudio(projectId)
    await refreshAfterChange()
    message.value = `完整音频已生成：${result.path}`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '完整音频合并失败'
  } finally {
    mergingAudio.value = false
  }
}

async function composeVideo() {
  error.value = ''
  message.value = ''
  if (!mediaVideoDir.value) {
    error.value = '请先在项目配置中选择素材视频目录'
    return
  }
  composingVideo.value = true
  try {
    await ensureFilenameSaved()
    const result = await composeProjectVideo(projectId)
    await refreshAfterChange()
    message.value = `无声视频已生成：${result.path}`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '无声视频生成失败'
  } finally {
    composingVideo.value = false
  }
}

async function oneClickGenerate() {
  if (!scriptText.value.trim()) {
    error.value = '请先粘贴或拖入逐字稿'
    return
  }
  if (!project.value?.reference_audio_path) {
    error.value = '请先配置项目参考音频后再一键生成'
    return
  }

  error.value = ''
  message.value = '正在保存脚本...'
  oneClickGenerating.value = true
  ttsRunning.value = true
  mergingAudio.value = false
  startPolling()

  try {
    await ensureFilenameSaved()
    project.value = await saveScript(projectId, scriptText.value)
    message.value = '正在生成切段...'
    await createSegments(projectId)
    await refreshAfterChange()

    message.value = '正在生成分段音频...'
    await startTts(projectId)
    await refreshAfterChange()

    if (ttsStatus.value.failed > 0) {
      throw new Error(`TTS 有 ${ttsStatus.value.failed} 段生成失败，请处理失败段后再合并完整音频`)
    }

    message.value = '正在合并完整音频...'
    mergingAudio.value = true
    const result = await mergeProjectAudio(projectId)
    await refreshAfterChange()
    message.value = `一键生成完成：${result.path}`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '一键生成失败'
    await refreshAfterChange()
  } finally {
    oneClickGenerating.value = false
    ttsRunning.value = false
    mergingAudio.value = false
    stopPolling()
  }
}

async function saveSegmentText(segment: Segment) {
  busySegments[segment.segment_id] = true
  error.value = ''
  message.value = ''
  try {
    await updateSegment(projectId, segment.segment_id, { text_zh: editedText[segment.segment_id] || '' })
    await refreshSegments()
    message.value = `#${segment.segment_id} 文本已保存`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '切段文本保存失败'
  } finally {
    busySegments[segment.segment_id] = false
  }
}

async function regenerateSegment(segment: Segment) {
  busySegments[segment.segment_id] = true
  error.value = ''
  message.value = ''
  try {
    await updateSegment(projectId, segment.segment_id, { text_zh: editedText[segment.segment_id] || '' })
    await regenerateSegmentTts(projectId, segment.segment_id)
    await refreshAfterChange()
    message.value = `#${segment.segment_id} 音频已重新生成`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '单段音频重生成失败'
  } finally {
    busySegments[segment.segment_id] = false
  }
}

onMounted(load)
onBeforeUnmount(stopPolling)
</script>

<template>
  <section v-if="project">
    <div class="page-title">
      <h1>{{ project.name }}</h1>
      <span class="status-pill">{{ project.status }}</span>
    </div>

    <div class="grid two-column">
      <div class="panel">
        <div class="reference-box">
          <div>
            <strong>参考音频</strong>
            <p class="muted">
              {{ project.reference_audio_path ? referenceAudioName || '参考音频' : '未配置参考音频' }}
            </p>
          </div>
          <AudioPlayer v-if="referenceAudioUrl" :src="referenceAudioUrl" />
          <RouterLink class="secondary-button" :to="`/projects/${project.id}/config`">项目配置</RouterLink>
        </div>

        <label class="field">
          <span>原始逐字稿</span>
          <textarea
            v-model="scriptText"
            :class="{ 'drag-active': scriptDragActive }"
            :placeholder="readingScriptFile ? '正在读取文本文件...' : '粘贴原始逐字稿文本，或拖入文本文件'"
            @dragenter.prevent="scriptDragActive = true"
            @dragover.prevent="scriptDragActive = true"
            @dragleave.prevent="scriptDragActive = false"
            @drop.prevent="handleScriptDrop"
          ></textarea>
          <span class="muted">拖入文本文件后会自动读取内容，并用文件名保存当前生成文件名。</span>
        </label>

        <div class="actions">
          <button class="primary-button" :disabled="oneClickGenerating || readingScriptFile" @click="oneClickGenerate">
            {{ oneClickGenerating ? '一键生成中' : '一键生成' }}
          </button>
          <button class="primary-button" :disabled="oneClickGenerating" @click="submitScript">保存脚本</button>
          <button class="secondary-button" :disabled="oneClickGenerating" @click="splitSegments">生成切段</button>
          <button class="secondary-button" :disabled="ttsRunning || oneClickGenerating" @click="runTts">
            {{ ttsRunning ? 'TTS 生成中' : '开始 TTS' }}
          </button>
          <button class="secondary-button" :disabled="mergingAudio || oneClickGenerating" @click="mergeAudio">
            {{ mergingAudio ? '合并中' : '合并完整音频' }}
          </button>
          <button class="secondary-button" :disabled="composingVideo || oneClickGenerating" @click="composeVideo">
            {{ composingVideo ? '视频生成中' : '生成无声视频' }}
          </button>
        </div>

        <p v-if="error" class="error">{{ error }}</p>
        <p v-if="message" class="success">{{ message }}</p>
      </div>

      <div class="panel">
        <div class="section-head">
          <h2>TTS 进度</h2>
          <span class="muted">{{ ttsPercent }}%</span>
        </div>
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: `${ttsPercent}%` }"></div>
        </div>
        <div class="stats-row">
          <span>总数 {{ ttsStatus.total }}</span>
          <span>完成 {{ ttsStatus.completed }}</span>
          <span>失败 {{ ttsStatus.failed }}</span>
          <span>等待 {{ ttsStatus.pending }}</span>
        </div>
        <p v-if="currentSegmentText" class="muted current-segment">当前生成：{{ currentSegmentText }}</p>

        <div class="outputs-panel embedded-outputs">
          <div class="section-head">
            <h2>输出文件</h2>
            <button class="secondary-button" @click="refreshOutputs">刷新</button>
          </div>
          <div class="inline-form">
            <label class="field">
              <span>当前生成文件名</span>
              <input v-model="outputFilename" placeholder="留空则使用当前时间戳" />
            </label>
            <button class="primary-button" :disabled="savingFilename" @click="saveCurrentFilename">
              {{ savingFilename ? '保存中' : '保存文件名' }}
            </button>
          </div>
          <p class="path-line"><strong>输出根目录：</strong>{{ outputs?.output_dir || project.output_dir || '暂无输出目录' }}</p>
          <p class="path-line"><strong>本次生成目录：</strong>{{ hasOutputFilename ? outputs?.work_dir : '保存或生成后自动创建' }}</p>
          <p class="path-line"><strong>最终完整音频：</strong>{{ finalAudioPath || '保存或生成后自动创建' }}</p>
          <p class="path-line"><strong>素材视频目录：</strong>{{ mediaVideoDir || '未配置' }}</p>
          <p class="path-line"><strong>最终无声视频：</strong>{{ finalVideoPath || '生成后自动创建' }}</p>
        </div>
      </div>
    </div>

    <div>
      <div class="page-title compact-title">
        <h1>切段结果</h1>
        <span class="muted">{{ loading ? '加载中' : `${segments.length} 段` }}</span>
      </div>
      <div class="segments">
        <article v-for="segment in segments" :key="segment.id" class="segment-item">
          <div class="segment-head">
            #{{ segment.segment_id }} · {{ segment.status }}
            <span v-if="segment.duration"> · {{ segment.duration.toFixed(2) }}s</span>
          </div>
          <textarea
            v-model="editedText[segment.segment_id]"
            class="segment-editor"
            rows="3"
          ></textarea>
          <AudioPlayer v-if="segmentAudioUrl(segment)" :src="segmentAudioUrl(segment)" />
          <div class="actions segment-actions">
            <button class="secondary-button" :disabled="busySegments[segment.segment_id]" @click="saveSegmentText(segment)">
              保存文本
            </button>
            <button class="primary-button" :disabled="busySegments[segment.segment_id]" @click="regenerateSegment(segment)">
              {{ busySegments[segment.segment_id] ? '处理中' : '重新生成音频' }}
            </button>
          </div>
          <p v-if="segment.audio_path" class="muted path-line">{{ segment.audio_path }}</p>
          <p v-if="segment.error_message" class="error">{{ segment.error_message }}</p>
        </article>
      </div>
    </div>
  </section>
</template>
