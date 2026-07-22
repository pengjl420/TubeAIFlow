<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { mergeProjectAudio } from '../../api/exports'
import { getProject, getProjectOutputs, type ProjectOutputs } from '../../api/projects'
import {
  composeProjectVideo,
  getIntelligentRenderStatus,
  getVideoStatus,
  type IntelligentRenderStatus,
  type VideoProgress,
} from '../../api/renders'
import { getVideoWorkflowStatus, startVideoWorkflow, type ProjectTaskStatus } from '../../api/tasks'
import { usePageFeedback } from '../../services/feedback'
import type { Project } from '../../types/project'

const route = useRoute()
const projectId = String(route.params.id)
const project = ref<Project | null>(null)
const outputs = ref<ProjectOutputs | null>(null)
const task = ref<ProjectTaskStatus | null>(null)
const status = ref<IntelligentRenderStatus | null>(null)
const videoProgress = ref<VideoProgress | null>(null)
const loading = ref(false)
const starting = ref(false)
const error = ref('')
const message = ref('')
usePageFeedback(error, message, { errorTitle: '渲染流程未继续', messageTitle: '渲染状态' })
let timer: number | undefined

const stageLabels: Record<string, string> = {
  storyboard: '生成视觉分镜',
  image_generation: '本地生成分镜图片',
  scene_render: '渲染场景视频',
  visual_track: '拼接纯视频轨道',
  final_render: '合成最终视频',
  quality_check: '完成生成（旧任务）',
  quality_review: '完成生成（旧任务）',
  fcpxml_export: '生成 FCPXML 工程',
  prproj_export: '生成 PRPROJ 工程',
  editable_export: '生成双格式可编辑工程',
  completed: '流程已完成',
}

const videoMode = computed(() => project.value?.config?.video_mode || 'none')
const usesLandscapeVideo = computed(() => videoMode.value === 'landscape')
const usesAiVideo = computed(() => videoMode.value === 'ai_generated_images')
const active = computed(() => usesLandscapeVideo.value
  ? videoProgress.value?.status === 'running'
  : task.value?.status === 'queued' || task.value?.status === 'running')

const actionLabel = computed(() => {
  if (starting.value) return usesLandscapeVideo.value && !outputs.value?.final_audio_exists ? '正在合并配音…' : usesLandscapeVideo.value ? '正在生成风景视频…' : '正在启动…'
  if (usesLandscapeVideo.value) return videoProgress.value?.status === 'completed' ? '重新生成风景视频' : '生成风景视频'
  if (usesAiVideo.value) return task.value?.status === 'completed' ? '重新运行视频流程' : '启动 / 继续自动流程'
  return '当前项目仅生成配音'
})

const pipelineStages = computed(() => {
  if (usesLandscapeVideo.value) {
    const progress = videoProgress.value
    const completed = progress?.status === 'completed' || status.value?.final_video_exists === true
    return [
      { label: '扫描风景素材', caption: progress?.stage === 'scanning' ? '正在扫描素材目录' : '使用项目配置的素材目录', done: Boolean(progress && progress.stage !== 'scanning') || completed },
      { label: '选择并处理素材', caption: progress?.status === 'running' ? `${progress.percent || 0}%` : completed ? '素材处理完成' : '尚未开始', done: completed },
      { label: '最终合成', caption: completed ? 'MP4 已生成' : progress?.status === 'failed' ? '生成失败' : '尚未生成', done: completed },
    ]
  }
  const value = status.value
  return [
    { label: '分镜生成', caption: value?.scene_count ? `${value.scene_count} 个场景` : '尚未生成', done: Boolean(value?.scene_count) },
    { label: '生成图片分配', caption: value?.scene_count ? `${value.assignment_count}/${value.scene_count} 已分配` : '等待分镜', done: Boolean(value?.scene_count && value.assignment_count === value.scene_count) },
    { label: '场景渲染', caption: value?.scene_count ? `${value.rendered_scene_count}/${value.scene_count} 已完成` : '等待图片生成', done: Boolean(value?.scene_count && value.rendered_scene_count === value.scene_count) },
    { label: '纯视频轨道', caption: value?.visual_track_exists ? '无音轨 MP4 已生成' : '等待场景渲染', done: Boolean(value?.visual_track_exists) },
    { label: '最终合成', caption: value?.final_video_exists ? 'MP4 已生成' : '尚未生成', done: Boolean(value?.final_video_exists) },
  ]
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [loadedProject, loadedOutputs, loadedTask, loadedStatus, loadedVideoProgress] = await Promise.all([
      getProject(projectId),
      getProjectOutputs(projectId),
      getVideoWorkflowStatus(projectId),
      getIntelligentRenderStatus(projectId),
      getVideoStatus(projectId),
    ])
    project.value = loadedProject
    outputs.value = loadedOutputs
    task.value = loadedTask
    status.value = loadedStatus
    videoProgress.value = loadedVideoProgress
    if (active.value) startPolling()
    else stopPolling()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '智能视频流程加载失败'
  } finally {
    loading.value = false
  }
}

async function start() {
  starting.value = true
  error.value = ''
  message.value = ''
  try {
    if (usesLandscapeVideo.value) {
      if (!outputs.value?.final_audio_exists) {
        message.value = '正在合并完整配音，完成后将继续生成视频'
        await mergeProjectAudio(projectId)
        outputs.value = await getProjectOutputs(projectId)
      }
      videoProgress.value = { status: 'running', stage: 'scanning', percent: 0, total: 0, completed: 0 }
      startPolling()
      await composeProjectVideo(projectId)
      message.value = '风景素材视频已生成'
    } else if (usesAiVideo.value) {
      task.value = await startVideoWorkflow(projectId)
      message.value = '视频工作流已进入后台队列'
      startPolling()
    } else {
      error.value = '当前项目的视频模式为“仅生成完整配音”，请先在项目配置中启用视频生成'
      return
    }
    await refresh()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '视频工作流启动失败'
  } finally {
    starting.value = false
  }
}

async function refresh() {
  const [loadedOutputs, loadedTask, loadedStatus, loadedVideoProgress] = await Promise.all([
    getProjectOutputs(projectId),
    getVideoWorkflowStatus(projectId),
    getIntelligentRenderStatus(projectId),
    getVideoStatus(projectId),
  ])
  outputs.value = loadedOutputs
  task.value = loadedTask
  status.value = loadedStatus
  videoProgress.value = loadedVideoProgress
  if (!active.value) stopPolling()
}

function startPolling() {
  if (timer !== undefined) return
  timer = window.setInterval(() => {
    refresh().catch((err) => {
      error.value = err instanceof Error ? err.message : '流程状态刷新失败'
      stopPolling()
    })
  }, 2000)
}

function stopPolling() {
  if (timer !== undefined) window.clearInterval(timer)
  timer = undefined
}

onMounted(load)
onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="pipeline-page">
    <div class="project-hero">
      <div>
        <span class="section-eyebrow">VIDEO RENDERING</span>
        <h1>视频渲染</h1>
        <p>{{ usesLandscapeVideo ? '查看风景素材处理和最终视频合成进度。' : '查看图片生成、场景渲染和最终视频合成进度。' }}</p>
      </div>
      <div class="page-title-actions">
        <button class="primary-button" :disabled="loading || starting || active || (!usesLandscapeVideo && !usesAiVideo)" @click="start">
          {{ actionLabel }}
        </button>
      </div>
    </div>

    <div v-if="task?.status === 'failed'" class="alert alert-danger"><strong>自动流程无法继续</strong><span>{{ task.error_message }}</span></div>
    <div v-if="usesLandscapeVideo && videoProgress?.status === 'failed'" class="alert alert-danger"><strong>风景视频生成失败</strong><span>{{ videoProgress.error || videoProgress.message }}</span></div>

    <div class="pipeline-stage-grid">
      <article v-for="(stage, index) in pipelineStages" :key="stage.label" class="panel pipeline-stage-card" :class="{ 'is-done': stage.done }">
        <span>{{ stage.done ? '✓' : index + 1 }}</span>
        <div><strong>{{ stage.label }}</strong><small>{{ stage.caption }}</small></div>
      </article>
    </div>

    <div class="grid pipeline-detail-grid">
      <article class="panel">
        <div class="section-head"><h2>后台任务</h2><span class="status-pill is-neutral">{{ usesLandscapeVideo ? (videoProgress?.status || 'idle') : (task?.status || 'idle') }}</span></div>
        <dl class="output-path-list">
          <div><dt>视频模式</dt><dd>{{ usesLandscapeVideo ? '风景素材拼接' : usesAiVideo ? '本地 AI 分镜图片视频' : '仅生成完整配音' }}</dd></div>
          <div><dt>当前阶段</dt><dd>{{ usesLandscapeVideo ? (videoProgress?.message || videoProgress?.stage || '尚未启动') : (stageLabels[task?.stage || ''] || task?.stage || '尚未启动') }}</dd></div>
          <div v-if="!usesLandscapeVideo"><dt>任务编号</dt><dd>{{ task?.id || '—' }}</dd></div>
          <div><dt>最终视频</dt><dd>{{ status?.final_video_path || '生成后显示' }}</dd></div>
        </dl>
      </article>
    </div>
  </section>
</template>
