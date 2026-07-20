<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { getProject } from '../../api/projects'
import { getIntelligentRenderStatus, type IntelligentRenderStatus } from '../../api/renders'
import { getVideoWorkflowStatus, startVideoWorkflow, type ProjectTaskStatus } from '../../api/tasks'
import type { Project } from '../../types/project'

const route = useRoute()
const projectId = String(route.params.id)
const project = ref<Project | null>(null)
const task = ref<ProjectTaskStatus | null>(null)
const status = ref<IntelligentRenderStatus | null>(null)
const loading = ref(false)
const starting = ref(false)
const error = ref('')
const message = ref('')
let timer: number | undefined

const stageLabels: Record<string, string> = {
  storyboard: '生成视觉分镜',
  asset_search: '检索本地素材库',
  asset_review: '等待素材审核',
  image_generation: '本地生成分镜图片',
  image_review: '等待图片审核',
  scene_render: '渲染场景视频',
  visual_track: '拼接纯视频轨道',
  final_render: '合成最终视频',
  quality_check: '执行质量检查',
  quality_review: '等待 QA 复核',
  completed: '流程已完成',
}

const active = computed(() => task.value?.status === 'queued' || task.value?.status === 'running')
const needsAssetReview = computed(() => task.value?.status === 'review_required' && ['asset_review', 'image_review'].includes(task.value.stage || ''))
const needsQualityReview = computed(() => task.value?.status === 'review_required' && task.value.stage === 'quality_review')
const missingAssignments = computed(() => Math.max(0, (status.value?.scene_count || 0) - (status.value?.assignment_count || 0)))
const assetReviewBlocked = computed(() => needsAssetReview.value && missingAssignments.value > 0)
const framepackSceneCount = computed(() => Object.values(status.value?.scene_render_results || {}).filter((item) => item.provider === 'framepack').length)
const framepackFallbackCount = computed(() => Object.values(status.value?.scene_render_results || {}).filter((item) => item.requested_provider === 'framepack' && item.provider === 'ffmpeg').length)

const pipelineStages = computed(() => {
  const value = status.value
  const qa = value?.qa_report
  return [
    { label: '分镜生成', caption: value?.scene_count ? `${value.scene_count} 个场景` : '尚未生成', done: Boolean(value?.scene_count) },
    { label: '素材审核', caption: value?.scene_count ? `${value.assignment_count}/${value.scene_count} 已确认` : '等待分镜', done: Boolean(value?.scene_count && value.assignment_count === value.scene_count) },
    { label: '场景渲染', caption: value?.scene_count ? `${value.rendered_scene_count}/${value.scene_count} 已完成 · FramePack ${framepackSceneCount.value} · 降级 ${framepackFallbackCount.value}` : '等待审核', done: Boolean(value?.scene_count && value.rendered_scene_count === value.scene_count) },
    { label: '纯视频轨道', caption: value?.visual_track_exists ? '无音轨 MP4 已生成' : '等待场景渲染', done: Boolean(value?.visual_track_exists) },
    { label: '最终合成', caption: value?.final_video_exists ? 'MP4 已生成' : '尚未生成', done: Boolean(value?.final_video_exists) },
    { label: '质量检查', caption: qa ? (qa.passed ? 'QA 通过' : `${qa.summary.error_count} 个错误`) : '尚未执行', done: Boolean(qa?.passed) },
  ]
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [loadedProject, loadedTask, loadedStatus] = await Promise.all([
      getProject(projectId),
      getVideoWorkflowStatus(projectId),
      getIntelligentRenderStatus(projectId),
    ])
    project.value = loadedProject
    task.value = loadedTask
    status.value = loadedStatus
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
    task.value = await startVideoWorkflow(projectId)
    message.value = '视频工作流已进入后台队列'
    startPolling()
    await refresh()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '视频工作流启动失败'
  } finally {
    starting.value = false
  }
}

async function refresh() {
  const [loadedTask, loadedStatus] = await Promise.all([
    getVideoWorkflowStatus(projectId),
    getIntelligentRenderStatus(projectId),
  ])
  task.value = loadedTask
  status.value = loadedStatus
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
        <RouterLink class="breadcrumb-link" :to="`/projects/${projectId}`">← 返回项目</RouterLink>
        <span class="section-eyebrow">VIDEO SYNTHESIS</span>
        <h1>{{ project?.name || '智能视频流程' }}</h1>
        <p>分镜生成、素材审核、场景渲染、最终合成和 QA 使用同一条可恢复任务链。</p>
      </div>
      <div class="page-title-actions">
        <RouterLink class="secondary-button" :to="`/projects/${projectId}/storyboard`">分镜工作区</RouterLink>
        <RouterLink class="secondary-button" :to="`/projects/${projectId}/media`">素材审核</RouterLink>
        <button class="primary-button" :disabled="loading || starting || active || assetReviewBlocked" @click="start">
          {{ starting ? '正在启动…' : needsQualityReview ? '重新渲染并复查' : needsAssetReview ? '审核完成，继续渲染' : task?.status === 'completed' ? '重新运行流程' : '启动 / 继续流程' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger"><strong>流程未继续</strong><span>{{ error }}</span></div>
    <div v-if="message" class="alert alert-success"><strong>当前状态</strong><span>{{ message }}</span></div>
    <div v-if="assetReviewBlocked" class="alert storyboard-warning">
      <strong>等待素材审核</strong>
      <span>还有 {{ missingAssignments }} 个场景未确认。完成全部选择后，在素材审核页继续流程。</span>
    </div>
    <div v-if="needsQualityReview" class="alert alert-danger">
      <strong>QA 需要复核</strong>
      <span>{{ task?.error_message }}</span>
    </div>

    <div class="pipeline-stage-grid">
      <article v-for="(stage, index) in pipelineStages" :key="stage.label" class="panel pipeline-stage-card" :class="{ 'is-done': stage.done }">
        <span>{{ stage.done ? '✓' : index + 1 }}</span>
        <div><strong>{{ stage.label }}</strong><small>{{ stage.caption }}</small></div>
      </article>
    </div>

    <div class="grid pipeline-detail-grid">
      <article class="panel">
        <div class="section-head"><h2>后台任务</h2><span class="status-pill is-neutral">{{ task?.status || 'idle' }}</span></div>
        <dl class="output-path-list">
          <div><dt>当前阶段</dt><dd>{{ stageLabels[task?.stage || ''] || task?.stage || '尚未启动' }}</dd></div>
          <div><dt>任务编号</dt><dd>{{ task?.id || '—' }}</dd></div>
          <div><dt>最终视频</dt><dd>{{ status?.final_video_path || '生成后显示' }}</dd></div>
        </dl>
      </article>

      <article class="panel">
        <div class="section-head"><h2>QA 报告</h2><span class="status-pill" :class="status?.qa_report?.passed ? 'is-success' : 'is-neutral'">{{ status?.qa_report ? (status.qa_report.passed ? '通过' : '需复核') : '未生成' }}</span></div>
        <div v-if="status?.qa_report" class="qa-issue-list">
          <div v-for="issue in status.qa_report.issues" :key="`${issue.type}-${issue.scene_id}-${issue.subtitle_id}`" class="qa-issue-row">
            <span class="status-pill" :class="issue.severity === 'error' ? 'is-danger' : 'is-warning'">{{ issue.severity }}</span>
            <div><strong>{{ issue.message }}</strong><small>{{ issue.suggestion || issue.type }}</small></div>
          </div>
          <p v-if="!status.qa_report.issues.length" class="muted">所有自动检查均已通过。</p>
        </div>
        <div v-else class="empty-state compact-empty"><p>最终合成完成后自动执行质量检查。</p></div>
      </article>
    </div>
  </section>
</template>
