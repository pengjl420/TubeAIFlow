<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import { API_BASE_URL } from '../../api/client'
import { mergeProjectAudio } from '../../api/exports'
import {
  createSrt,
  getTtsStatus,
  listSegments,
  regenerateSegmentTts,
  startTts,
  updateSegment,
  type TtsStatus,
} from '../../api/narration'
import { composeProjectVideo, getVideoStatus, type VideoProgress } from '../../api/renders'
import {
  createSegments,
  getProject,
  getProjectOutputs,
  saveOutputSettings,
  saveScript,
  type ProjectOutputs,
} from '../../api/projects'
import {
  cancelProjectTask,
  getProjectTaskStatus,
  startProjectWorkflow,
  type ProjectTaskStatus,
} from '../../api/tasks'
import AudioPlayer from '../../components/common/AudioPlayer.vue'
import type { Segment } from '../../types/narration'
import type { Project } from '../../types/project'
import { formatDateTime, formatDuration } from '../../utils/time'

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
let taskPollTimer: number | undefined

const oneClickStage = ref('')
const oneClickStartedAt = ref(0)
const oneClickStageStartedAt = ref(0)
const oneClickFinishedAt = ref(0)
const timerNow = ref(Date.now())

const ttsStatus = ref<TtsStatus>({ total: 0, completed: 0, failed: 0, pending: 0 })
const videoProgress = ref<VideoProgress | null>(null)
const projectTask = ref<ProjectTaskStatus | null>(null)
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

const audioDurationSeconds = computed(() => {
  const segmentTotal = segments.value.reduce((total, segment) => total + (segment.duration || 0), 0)
  return segmentTotal || project.value?.audio_duration_seconds || 0
})

const workflowStartedAt = computed(() => (
  projectTask.value?.started_at || project.value?.workflow_started_at || null
))

const workflowDurationSeconds = computed(() => {
  const task = projectTask.value
  if (task?.started_at && task.status === 'running' && !task.finished_at) {
    const started = Date.parse(task.started_at)
    if (Number.isFinite(started)) return Math.max(0, (timerNow.value - started) / 1000)
  }
  return task?.workflow_duration_seconds ?? project.value?.workflow_duration_seconds ?? null
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

function startOneClickTimer(startedAt = Date.now()) {
  stopOneClickTimer()
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
  if (project.value?.config) return project.value.config
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
  return segment ? `#${segment.segment_id} ${segment.text}` : `#${currentId}`
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

const finalSrtPath = computed(() => {
  if (!hasOutputFilename.value) return ''
  const dir = outputs.value?.output_dir || project.value?.output_dir || ''
  if (!dir || !outputFilename.value.trim()) return outputs.value?.final_srt_path || ''
  return outputs.value?.final_srt_path || `${dir.replace(/[\\/]$/, '')}\\${outputFilename.value.trim()}.srt`
})

const mediaVideoDir = computed(() => {
  const value = projectConfig.value.media_video_dir
  return typeof value === 'string' ? value : ''
})

const videoMode = computed(() => {
  const mode = projectConfig.value.video_mode
  if (mode === 'ai_semantic' || mode === 'landscape' || mode === 'none') return mode
  return projectConfig.value.include_video === true ? 'landscape' : 'none'
})
const includeVideo = computed(() => videoMode.value !== 'none')
const usesAiSemanticVideo = computed(() => videoMode.value === 'ai_semantic')
const usesLandscapeVideo = computed(() => videoMode.value === 'landscape')

const finalVideoPath = computed(() => {
  if (!hasOutputFilename.value) return ''
  const dir = outputs.value?.output_dir || project.value?.output_dir || ''
  if (!dir || !outputFilename.value.trim()) return outputs.value?.final_video_path || ''
  return outputs.value?.final_video_path || `${dir.replace(/[\\/]$/, '')}\\${outputFilename.value.trim()}.mp4`
})

const projectStatusLabel = computed(() => {
  const labels: Record<string, string> = {
    created: '待开始',
    narration_in_progress: '配音生成中',
    narration_ready: '配音已就绪',
    video_in_progress: '视频合成中',
    review_required: '等待复核',
    completed: '已完成',
    failed: '执行失败',
  }
  return labels[project.value?.status || ''] || (project.value?.status || '未知状态').split('_').join(' ')
})

const scriptCharacterCount = computed(() => scriptText.value.trim().length)
const projectStatusTone = computed(() => {
  if (project.value?.status === 'failed') return 'is-danger'
  if (project.value?.status === 'completed') return 'is-success'
  if (project.value?.status === 'review_required') return 'is-warning'
  if (project.value?.status?.includes('progress')) return 'is-running'
  return 'is-neutral'
})
const workflowSteps = computed(() => {
  const segmentReady = segments.value.length > 0
  const scriptReady = scriptCharacterCount.value > 0 || segmentReady
  const voiceReady = ttsStatus.value.total > 0 && ttsStatus.value.completed >= ttsStatus.value.total
  const audioReady = Boolean(finalAudioPath.value && outputs.value?.final_audio_path)
  const videoReady = Boolean(finalVideoPath.value && outputs.value?.final_video_path)
  const videoActive = composingVideo.value || Boolean(
    projectTask.value?.status === 'running'
    && ['storyboard', 'asset_search', 'asset_review', 'scene_render', 'final_render', 'quality_check', 'quality_review'].includes(projectTask.value.stage || ''),
  )
  return [
    { label: '脚本', caption: scriptCharacterCount.value ? `${scriptCharacterCount.value} 字` : scriptReady ? '已保存' : '等待输入', state: scriptReady ? 'done' : 'current' },
    { label: '切段', caption: segmentReady ? `${segments.value.length} 段` : '尚未生成', state: segmentReady ? 'done' : scriptCharacterCount.value ? 'current' : 'pending' },
    { label: '配音', caption: voiceReady ? '音频已就绪' : ttsRunning.value ? '正在生成' : '等待生成', state: voiceReady ? 'done' : ttsRunning.value ? 'current' : 'pending' },
    { label: '字幕', caption: audioReady ? '已生成' : '等待合并', state: audioReady ? 'done' : mergingAudio.value || generatingSubtitles.value ? 'current' : 'pending' },
    { label: '成片', caption: includeVideo.value ? (videoReady ? '已输出' : '等待合成') : '未启用', state: videoReady ? 'done' : videoActive ? 'current' : 'pending' },
  ]
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
    await refreshProjectTaskStatus()
    if (projectTask.value && ['queued', 'running'].includes(projectTask.value.status)) {
      startTaskPolling()
    }
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
    editedText[segment.segment_id] = segment.text
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

function taskStageLabel(task: ProjectTaskStatus) {
  if (task.status === 'queued') {
    return task.queue_position ? `排队中（第 ${task.queue_position} 位）` : '排队中'
  }
  const labels: Record<string, string> = {
    segmenting: '生成切段',
    tts: '生成分段音频',
    audio_merge: '合并完整音频',
    subtitles: '生成字幕',
    video: '生成视频',
    storyboard: '生成视觉分镜',
    asset_search: '检索语义素材',
    asset_review: '等待素材审核',
    scene_render: '渲染场景视频',
    final_render: '合成最终视频',
    quality_check: '执行质量检查',
    quality_review: '等待质量复核',
    completed: '生成完成',
  }
  return labels[task.stage || ''] || task.stage || '准备执行'
}

function applyProjectTaskStatus(task: ProjectTaskStatus) {
  projectTask.value = task
  const active = task.status === 'queued' || task.status === 'running'
  oneClickGenerating.value = active
  ttsRunning.value = task.status === 'running' && task.stage === 'tts'
  mergingAudio.value = task.status === 'running' && task.stage === 'audio_merge'
  generatingSubtitles.value = task.status === 'running' && task.stage === 'subtitles'
  composingVideo.value = task.status === 'running' && task.stage === 'video'

  if (active) {
    const label = taskStageLabel(task)
    const recoveryNotice = task.compensation_count
      ? `（已自动恢复 ${task.compensation_count} 次）`
      : ''
    if (!oneClickStartedAt.value && task.started_at) {
      const started = Date.parse(task.started_at)
      if (Number.isFinite(started)) {
        startOneClickTimer(started)
      }
      oneClickStageStartedAt.value = Date.now()
      oneClickFinishedAt.value = 0
    }
    if (oneClickStage.value !== label) beginOneClickStage(label)
    message.value = task.status === 'queued'
      ? `任务已创建，${label}${recoveryNotice}。你可以继续创建其他项目或批次。`
      : `后台任务正在${label}${recoveryNotice}`
    return
  }

  if (oneClickGenerating.value || oneClickStartedAt.value) {
    const finished = Date.parse(task.finished_at || '')
    oneClickFinishedAt.value = Number.isFinite(finished) ? finished : Date.now()
    timerNow.value = oneClickFinishedAt.value
  }
  stopOneClickTimer()
  if (task.status === 'completed') message.value = '一键生成完成'
  if (task.status === 'failed') error.value = task.error_message || '一键生成失败'
  if (task.status === 'cancelled') message.value = '任务已取消'
  if (task.status === 'paused') message.value = '任务已暂停；如果它属于批次，请从批次详情页恢复执行。'
  if (task.status === 'review_required') message.value = task.error_message || 'AI 语义视频正在等待人工复核。'
}

async function refreshProjectTaskStatus() {
  const task = await getProjectTaskStatus(projectId)
  applyProjectTaskStatus(task)
  return task
}

function startTaskPolling() {
  stopTaskPolling()
  taskPollTimer = window.setInterval(async () => {
    try {
      const task = await refreshProjectTaskStatus()
      if (task.status === 'running' && task.stage === 'tts') await refreshTtsStatus()
      if (task.status === 'running' && task.stage === 'video') videoProgress.value = await getVideoStatus(projectId)
      if (!['queued', 'running'].includes(task.status)) {
        stopTaskPolling()
        await refreshAfterChange()
      }
    } catch (err) {
      error.value = err instanceof Error ? err.message : '刷新任务状态失败'
    }
  }, 1500)
}

function stopTaskPolling() {
  if (taskPollTimer !== undefined) {
    window.clearInterval(taskPollTimer)
    taskPollTimer = undefined
  }
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
    await refreshProjectTaskStatus()
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
    message.value = '正在生成字幕...'
    mergingAudio.value = false
    generatingSubtitles.value = true
    await createSrt(projectId)
    await refreshAfterChange()
    message.value = `完整音频和字幕已生成：${result.path}`
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
  if (usesLandscapeVideo.value && !mediaVideoDir.value) {
    error.value = '请先在项目设置中选择素材视频目录后再一键生成'
    return
  }

  error.value = ''
  message.value = '正在保存脚本并创建后台任务...'
  oneClickGenerating.value = true
  beginOneClickStage('创建任务')
  startOneClickTimer()

  try {
    await ensureFilenameSaved()
    project.value = await saveScript(projectId, scriptText.value)
    const task = await startProjectWorkflow(projectId)
    applyProjectTaskStatus(task)
    startTaskPolling()
    await refreshAfterChange()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '任务创建失败'
    oneClickFinishedAt.value = Date.now()
    timerNow.value = oneClickFinishedAt.value
    oneClickGenerating.value = false
    stopOneClickTimer()
  }
}

async function saveSegmentText(segment: Segment) {
  busySegments[segment.segment_id] = true
  error.value = ''
  message.value = ''
  try {
    await updateSegment(projectId, segment.segment_id, { text: editedText[segment.segment_id] || '' })
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
    await updateSegment(projectId, segment.segment_id, { text: editedText[segment.segment_id] || '' })
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
  stopTaskPolling()
})
</script>

<template>
  <section v-if="project">
    <div class="project-hero">
      <div>
        <RouterLink class="breadcrumb-link" to="/">← 返回项目</RouterLink>
        <div class="project-title-row">
          <h1>{{ project.name }}</h1>
          <span class="status-pill" :class="projectStatusTone"><i></i>{{ projectStatusLabel }}</span>
        </div>
        <p>在同一条生产线上编辑脚本、生成配音字幕并输出成片。</p>
      </div>
      <div class="page-title-actions">
        <RouterLink v-if="usesAiSemanticVideo" class="secondary-button" :to="`/projects/${project.id}/storyboard`">分镜工作区</RouterLink>
        <RouterLink v-if="usesAiSemanticVideo" class="secondary-button" :to="`/projects/${project.id}/media`">素材审核</RouterLink>
        <RouterLink v-if="usesAiSemanticVideo" class="primary-button" :to="`/projects/${project.id}/render`">智能视频流程</RouterLink>
        <RouterLink class="secondary-button" :to="`/projects/${project.id}/config`">项目设置</RouterLink>
      </div>
    </div>

    <div class="project-metrics-strip" aria-label="项目时间与时长">
      <div><span>项目创建时间</span><strong>{{ formatDateTime(project.created_at) }}</strong></div>
      <div><span>实际开始时间</span><strong>{{ formatDateTime(workflowStartedAt, '尚未开始') }}</strong></div>
      <div><span>音频文件时长</span><strong>{{ formatDuration(audioDurationSeconds || null, '未生成') }}</strong></div>
      <div><span>完整流程用时</span><strong>{{ formatDuration(workflowDurationSeconds, workflowStartedAt ? '计算中' : '未开始') }}</strong></div>
    </div>

    <div class="workflow-rail" aria-label="项目生产阶段">
      <div v-for="(step, index) in workflowSteps" :key="step.label" class="workflow-step" :class="`is-${step.state}`">
        <span class="step-index">{{ step.state === 'done' ? '✓' : index + 1 }}</span>
        <span><strong>{{ step.label }}</strong><small>{{ step.caption }}</small></span>
      </div>
    </div>

    <div class="studio-grid">
      <div class="panel script-panel">
        <div class="section-head script-section-head">
          <div>
            <span class="section-eyebrow">01 · CONTENT</span>
            <h2>逐字稿编辑</h2>
          </div>
          <span class="muted">{{ scriptCharacterCount.toLocaleString() }} 字</span>
        </div>
        <div class="reference-box">
          <div>
            <strong>参考音频</strong>
            <p class="muted">
              {{ project.reference_audio_path ? referenceAudioName || '参考音频' : '未配置参考音频' }}
            </p>
          </div>
          <AudioPlayer v-if="referenceAudioUrl" :src="referenceAudioUrl" />
          <span class="status-pill" :class="project.reference_audio_path ? 'is-success' : 'is-warning'">
            {{ project.reference_audio_path ? '已配置' : '需配置' }}
          </span>
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
          <span class="field-hint">支持粘贴或拖入 TXT / Markdown 文件；文件名会自动作为当前输出名称。</span>
        </label>

        <div class="manual-actions">
          <span>手动控制</span>
          <button class="text-button" :disabled="oneClickGenerating" @click="submitScript">保存脚本</button>
          <button class="text-button" :disabled="oneClickGenerating" @click="splitSegments">生成切段</button>
          <button class="text-button" :disabled="ttsRunning || oneClickGenerating" @click="runTts">{{ ttsRunning ? 'TTS 生成中' : '开始 TTS' }}</button>
          <button class="text-button" :disabled="mergingAudio || generatingSubtitles || oneClickGenerating" @click="mergeAudio">{{ generatingSubtitles ? '字幕生成中' : mergingAudio ? '合并中' : '合并音频字幕' }}</button>
          <button v-if="usesLandscapeVideo" class="text-button" :disabled="composingVideo || oneClickGenerating" @click="composeVideo">{{ composingVideo ? '视频生成中' : '单独生成纯风景视频' }}</button>
          <button
            v-if="hasRunningGeneration"
            class="text-button danger-text"
            :disabled="stoppingGeneration"
            @click="stopGeneration"
          >
            {{ stoppingGeneration ? '正在终止…' : '强制终止当前任务' }}
          </button>
        </div>

        <div v-if="error" class="alert alert-danger"><strong>操作未完成</strong><span>{{ error }}</span></div>
        <div v-if="message" class="alert alert-success"><strong>操作成功</strong><span>{{ message }}</span></div>
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

      <aside class="panel execution-panel">
        <div class="execution-intro">
          <span class="section-eyebrow">PRODUCTION</span>
          <h2>{{ hasRunningGeneration ? '正在执行生产任务' : '准备开始生成' }}</h2>
          <p v-if="usesAiSemanticVideo">将依次完成切段、配音、字幕与 AI 语义视频流程，并在素材审核阶段等待确认。</p>
          <p v-else-if="usesLandscapeVideo">将依次完成切段、配音、字幕与纯风景素材拼接。</p>
          <p v-else>将依次完成切段、配音与字幕生成。</p>
          <button class="primary-button primary-action" :disabled="oneClickGenerating || readingScriptFile" @click="oneClickGenerate">
            <span>{{ oneClickGenerating ? '●' : '▶' }}</span>
            {{ oneClickGenerating ? '正在一键生成' : '开始一键生成' }}
          </button>
        </div>

        <div class="section-head">
          <h3>配音进度</h3>
          <strong>{{ ttsPercent }}%</strong>
        </div>
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: `${ttsPercent}%` }"></div>
        </div>
        <div class="stats-row">
          <span><strong>{{ ttsStatus.total }}</strong><small>总段数</small></span>
          <span><strong>{{ ttsStatus.completed }}</strong><small>已完成</small></span>
          <span><strong>{{ ttsStatus.failed }}</strong><small>失败</small></span>
          <span><strong>{{ ttsStatus.pending }}</strong><small>等待</small></span>
        </div>
        <p v-if="currentSegmentText" class="muted current-segment">当前生成：{{ currentSegmentText }}</p>

        <div class="outputs-panel embedded-outputs">
          <div class="section-head">
            <h3>输出位置</h3>
            <button class="mini-button" @click="refreshOutputs">刷新</button>
          </div>
          <div class="inline-form">
            <label class="field">
              <span>当前生成文件名</span>
              <input v-model="outputFilename" placeholder="留空则使用当前时间戳" />
            </label>
            <button class="secondary-button" :disabled="savingFilename" @click="saveCurrentFilename">
              {{ savingFilename ? '保存中' : '保存文件名' }}
            </button>
          </div>
          <dl class="output-path-list">
            <div><dt>根目录</dt><dd>{{ outputs?.output_dir || project.output_dir || '暂无输出目录' }}</dd></div>
            <div><dt>完整音频</dt><dd>{{ finalAudioPath || '生成后自动创建' }}</dd></div>
            <div><dt>字幕</dt><dd>{{ finalSrtPath || '生成后自动创建' }}</dd></div>
            <div v-if="includeVideo"><dt>最终视频</dt><dd>{{ finalVideoPath || '生成后自动创建' }}</dd></div>
          </dl>
        </div>
      </aside>
    </div>

    <div class="segments-section">
      <div class="section-toolbar compact-title">
        <div>
          <span class="section-eyebrow">02 · SEGMENTS</span>
          <h2>配音分段</h2>
          <p>逐段检查文案和音频；修改后可以只重新生成当前分段。</p>
        </div>
        <span class="status-pill is-neutral">{{ loading ? '加载中' : `${segments.length} 段` }}</span>
      </div>
      <div v-if="!loading && !segments.length" class="empty-state panel compact-empty">
        <h2>尚未生成分段</h2>
        <p>保存逐字稿后点击“生成切段”，或直接使用一键生成。</p>
      </div>
      <div class="segments">
        <article v-for="segment in segments" :key="segment.id" class="segment-item">
          <div class="segment-head">
            <span class="segment-number">{{ segment.segment_id }}</span>
            <span class="status-pill is-neutral">{{ segment.status }}</span>
            <span v-if="segment.duration" class="segment-duration">{{ segment.duration.toFixed(2) }} 秒</span>
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
          <p v-if="segment.audio_path" class="muted path-line segment-path">{{ segment.audio_path }}</p>
          <p v-if="segment.error_message" class="error">{{ segment.error_message }}</p>
        </article>
      </div>
    </div>
  </section>
</template>
