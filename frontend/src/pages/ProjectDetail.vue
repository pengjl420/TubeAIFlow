<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import { API_BASE_URL } from '../api/client'
import { mergeProjectAudio } from '../api/exports'
import { createZhSrt } from '../api/subtitles'
import { composeProjectVideo, getVideoStatus, type VideoProgress } from '../api/videos'
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
import { cancelProjectTask } from '../api/tasks'
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
const ttsRequestActive = ref(false)
const mergingAudio = ref(false)
const generatingSubtitles = ref(false)
const composingVideo = ref(false)
const oneClickGenerating = ref(false)
const savingFilename = ref(false)
const stoppingGeneration = ref(false)
const readingScriptFile = ref(false)
const scriptDragActive = ref(false)
const error = ref('')
const message = ref('')
let pollTimer: number | undefined
let videoPollTimer: number | undefined
let oneClickTimer: number | undefined

const oneClickStage = ref('')
const oneClickStartedAt = ref(0)
const oneClickStageStartedAt = ref(0)
const oneClickFinishedAt = ref(0)
const timerNow = ref(Date.now())

const ttsStatus = ref<TtsStatus>({ total: 0, completed: 0, failed: 0, pending: 0 })
const videoProgress = ref<VideoProgress | null>(null)
const hasRunningGeneration = computed(() => (
  ttsRunning.value || mergingAudio.value || generatingSubtitles.value
  || composingVideo.value || oneClickGenerating.value
))

const oneClickStageElapsed = computed(() => {
  if (!oneClickStageStartedAt.value) return 0
  const end = oneClickFinishedAt.value || timerNow.value
  return Math.max(0, end - oneClickStageStartedAt.value)
})

const oneClickTotalElapsed = computed(() => {
  if (!oneClickStartedAt.value) return 0
  const end = oneClickFinishedAt.value || timerNow.value
  return Math.max(0, end - oneClickStartedAt.value)
})

function formatElapsed(milliseconds: number) {
  const totalSeconds = Math.floor(milliseconds / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function beginOneClickStage(stage: string) {
  oneClickStage.value = stage
  oneClickStageStartedAt.value = Date.now()
  timerNow.value = oneClickStageStartedAt.value
}

function startOneClickTimer() {
  stopOneClickTimer()
  const startedAt = Date.now()
  oneClickStartedAt.value = startedAt
  oneClickStageStartedAt.value = startedAt
  oneClickFinishedAt.value = 0
  timerNow.value = startedAt
  oneClickTimer = window.setInterval(() => {
    timerNow.value = Date.now()
  }, 1000)
}

function stopOneClickTimer() {
  if (oneClickTimer !== undefined) {
    window.clearInterval(oneClickTimer)
    oneClickTimer = undefined
  }
}

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

const finalEnglishSrtPath = computed(() => {
  if (!hasOutputFilename.value) return ''
  const dir = outputs.value?.output_dir || project.value?.output_dir || ''
  if (!dir || !outputFilename.value.trim()) return outputs.value?.final_en_srt_path || ''
  return outputs.value?.final_en_srt_path || `${dir.replace(/[\\/]$/, '')}\\${outputFilename.value.trim()}_en.srt`
})

const finalTranslatedSrtPath = computed(() => outputs.value?.final_translated_srt_path || finalEnglishSrtPath.value)

const mediaVideoDir = computed(() => {
  const value = projectConfig.value.media_video_dir
  return typeof value === 'string' ? value : ''
})

const includeTranslation = computed(() => projectConfig.value.include_translation === true)
const includeVideo = computed(() => projectConfig.value.include_video === true)

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
    if (ttsRunning.value) startPolling()
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
  if (!ttsRequestActive.value) {
    ttsRunning.value = ttsStatus.value.progress?.status === 'running'
  }
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
      if (!ttsRequestActive.value && !ttsRunning.value) {
        stopPolling()
        await Promise.all([refreshSegments(), refreshOutputs()])
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : '刷新进度失败'
    }
  }, 1500)
}

async function stopGeneration() {
  stoppingGeneration.value = true
  error.value = ''
  try {
    const result = await cancelProjectTask(projectId)
    message.value = result.cancelled ? '已发送终止指令，正在停止当前阶段…' : '当前没有可终止的生成任务'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '终止任务失败'
  } finally {
    stoppingGeneration.value = false
  }
}

function stopPolling() {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

function startVideoPolling() {
  stopVideoPolling()
  videoPollTimer = window.setInterval(async () => {
    try {
      videoProgress.value = await getVideoStatus(projectId)
    } catch (err) {
      error.value = err instanceof Error ? err.message : '刷新视频进度失败'
    }
  }, 1000)
}

function stopVideoPolling() {
  if (videoPollTimer !== undefined) {
    window.clearInterval(videoPollTimer)
    videoPollTimer = undefined
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
  try {
    await ensureFilenameSaved()
    ttsRequestActive.value = true
    startPolling()
    await startTts(projectId)
    await refreshAfterChange()
    message.value = '分段音频已生成，可以合并完整音频'
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'TTS 启动失败'
    await refreshAfterChange()
  } finally {
    ttsRequestActive.value = false
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
    message.value = includeTranslation.value ? '正在生成原文和翻译字幕...' : '正在生成原文字幕...'
    mergingAudio.value = false
    generatingSubtitles.value = true
    const subtitles = await createZhSrt(projectId, includeTranslation.value)
    await refreshAfterChange()
    message.value = subtitles.translated_path
      ? `完整音频已生成：${result.path}；翻译字幕已生成：${subtitles.translated_path}`
      : `完整音频和原文字幕已生成：${result.path}`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '完整音频合并失败'
  } finally {
    mergingAudio.value = false
    generatingSubtitles.value = false
  }
}

async function composeVideo() {
  error.value = ''
  message.value = ''
  if (!mediaVideoDir.value) {
    error.value = '请先在项目设置中选择素材视频目录'
    return
  }
  composingVideo.value = true
  videoProgress.value = {
    status: 'running', stage: 'preparing', percent: 0, total: 0, completed: 0, message: '正在准备视频生成',
  }
  try {
    await ensureFilenameSaved()
    startVideoPolling()
    const result = await composeProjectVideo(projectId)
    videoProgress.value = await getVideoStatus(projectId)
    await refreshAfterChange()
    message.value = `视频已生成：${result.path}`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '视频生成失败'
  } finally {
    composingVideo.value = false
    stopVideoPolling()
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
  if (includeVideo.value && !mediaVideoDir.value) {
    error.value = '请先在项目设置中选择素材视频目录后再一键生成'
    return
  }

  error.value = ''
  message.value = '正在保存脚本...'
  oneClickGenerating.value = true
  ttsRunning.value = true
  mergingAudio.value = false
  oneClickStage.value = '保存脚本'
  startOneClickTimer()

  try {
    await ensureFilenameSaved()
    project.value = await saveScript(projectId, scriptText.value)
    message.value = '正在生成切段...'
    beginOneClickStage('生成切段')
    await createSegments(projectId)
    await refreshAfterChange()

    message.value = '正在生成分段音频...'
    beginOneClickStage('生成分段音频')
    ttsRequestActive.value = true
    startPolling()
    await startTts(projectId)
    ttsRequestActive.value = false
    stopPolling()
    await refreshAfterChange()

    if (ttsStatus.value.failed > 0) {
      throw new Error(`TTS 有 ${ttsStatus.value.failed} 段生成失败，请处理失败段后再合并完整音频`)
    }

    message.value = '正在合并完整音频...'
    beginOneClickStage('合并完整音频')
    mergingAudio.value = true
    await mergeProjectAudio(projectId)
    await refreshAfterChange()

    message.value = includeTranslation.value ? '正在生成原文和翻译字幕...' : '正在生成原文字幕...'
    beginOneClickStage(includeTranslation.value ? '生成原文和翻译字幕' : '生成原文字幕')
    mergingAudio.value = false
    generatingSubtitles.value = true
    await createZhSrt(projectId, includeTranslation.value)
    generatingSubtitles.value = false
    await refreshAfterChange()

    if (includeVideo.value) {
      message.value = '正在生成视频...'
      beginOneClickStage('生成视频')
      mergingAudio.value = false
      composingVideo.value = true
      videoProgress.value = {
        status: 'running', stage: 'preparing', percent: 0, total: 0, completed: 0, message: '正在准备视频生成',
      }
      startVideoPolling()
      const result = await composeProjectVideo(projectId)
      videoProgress.value = await getVideoStatus(projectId)
      await refreshAfterChange()
      message.value = `一键生成完成：${result.path}`
    } else {
      message.value = '一键生成完成'
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '一键生成失败'
    await refreshAfterChange()
  } finally {
    oneClickFinishedAt.value = Date.now()
    timerNow.value = oneClickFinishedAt.value
    stopOneClickTimer()
    oneClickGenerating.value = false
    ttsRequestActive.value = false
    ttsRunning.value = false
    mergingAudio.value = false
    generatingSubtitles.value = false
    composingVideo.value = false
    stopPolling()
    stopVideoPolling()
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
onBeforeUnmount(() => {
  stopPolling()
  stopVideoPolling()
  stopOneClickTimer()
})
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
          <RouterLink class="secondary-button" :to="`/projects/${project.id}/config`">项目设置</RouterLink>
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
          <button class="secondary-button" :disabled="mergingAudio || generatingSubtitles || oneClickGenerating" @click="mergeAudio">
            {{ generatingSubtitles ? '字幕生成中' : mergingAudio ? '合并中' : '合并完整音频' }}
          </button>
          <button class="secondary-button" :disabled="composingVideo || oneClickGenerating" @click="composeVideo">
            {{ composingVideo ? '视频生成中' : '生成视频' }}
          </button>
          <button
            v-if="hasRunningGeneration"
            class="danger-button"
            :disabled="stoppingGeneration"
            @click="stopGeneration"
          >
            {{ stoppingGeneration ? '正在终止…' : '强制终止当前任务' }}
          </button>
        </div>

        <p v-if="error" class="error">{{ error }}</p>
        <p v-if="message" class="success">{{ message }}</p>
        <div v-if="oneClickStartedAt" class="generation-timing">
          <div>
            <span class="muted">当前阶段</span>
            <strong>{{ oneClickStage }}</strong>
          </div>
          <div>
            <span class="muted">当前执行时长</span>
            <strong>{{ formatElapsed(oneClickStageElapsed) }}</strong>
          </div>
          <div>
            <span class="muted">总用时</span>
            <strong>{{ formatElapsed(oneClickTotalElapsed) }}</strong>
          </div>
        </div>
        <div v-if="composingVideo || videoProgress" class="video-progress-panel">
          <div class="section-head">
            <strong>视频生成进度</strong>
            <span class="muted">{{ videoProgress?.percent || 0 }}%</span>
          </div>
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: `${videoProgress?.percent || 0}%` }"></div>
          </div>
          <p class="muted">
            {{ videoProgress?.message || '正在准备视频生成' }}
            <span v-if="videoProgress?.total">（{{ videoProgress.completed }}/{{ videoProgress.total }}）</span>
          </p>
          <p v-if="videoProgress?.current_file" class="muted path-line">当前素材：{{ videoProgress.current_file }}</p>
          <p v-if="videoProgress?.error" class="error">{{ videoProgress.error }}</p>
        </div>
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
          <p class="path-line"><strong>翻译字幕：</strong>{{ includeTranslation ? finalTranslatedSrtPath || '生成后自动创建' : '未启用' }}</p>
          <p class="path-line"><strong>素材视频目录：</strong>{{ mediaVideoDir || '未配置' }}</p>
          <p class="path-line"><strong>最终视频：</strong>{{ finalVideoPath || '生成后自动创建' }}</p>
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
