<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { AlertCircle, CheckCircle2, Clock3, ListFilter, PauseCircle, RefreshCw, X } from 'lucide-vue-next'

import { listProjects } from '../api/projects'
import { cancelProjectTask, getProjectTaskStatus, type ProjectTaskStatus } from '../api/tasks'
import type { Project } from '../types/project'
import { formatDateTime, formatDuration } from '../utils/time'

interface TaskItem { project: Project; task: ProjectTaskStatus }

const route = useRoute()
const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const query = ref('')
const status = ref(typeof route.query.status === 'string' ? route.query.status : 'all')
const type = ref('all')
const selected = ref<TaskItem | null>(null)
const error = ref('')
let refreshTimer: number | undefined

const filtered = computed(() => tasks.value.filter((item) => {
  const keyword = query.value.trim().toLocaleLowerCase()
  const matchesQuery = !keyword || item.project.name.toLocaleLowerCase().includes(keyword) || (item.task.stage || '').includes(keyword)
  const matchesType = type.value === 'all' || item.task.workflow === type.value
  const matchesStatus = status.value === 'all'
    || (status.value === 'review' && item.task.status === 'review_required')
    || item.task.status === status.value
  return matchesQuery && matchesType && matchesStatus
}))

const counts = computed(() => ({
  queued: tasks.value.filter((item) => item.task.status === 'queued').length,
  running: tasks.value.filter((item) => item.task.status === 'running').length,
  review: tasks.value.filter((item) => item.task.status === 'review_required').length,
  failed: tasks.value.filter((item) => item.task.status === 'failed').length,
  completed: tasks.value.filter((item) => item.task.status === 'completed').length,
}))

const stageLabels: Record<string, string> = {
  segmenting: '文本切段', tts: '生成配音', audio_merge: '合并音频', subtitles: '字幕时间轴',
  storyboard: '视觉分镜', asset_search: '素材检索', asset_review: '素材审核', image_generation: '图片生成',
  image_review: '图片审核', scene_render: '场景渲染', visual_track: '视觉轨道', final_render: '最终合成',
  quality_check: '质量检查', quality_review: '质量复核', completed: '任务完成',
}

const statusLabels: Record<string, string> = {
  idle: '空闲', queued: '排队中', running: '运行中', paused: '已暂停', review_required: '等待审核',
  completed: '已完成', failed: '失败', cancelled: '已取消',
}

function tone(value: string) {
  if (value === 'failed') return 'is-danger'
  if (value === 'completed') return 'is-success'
  if (value === 'review_required' || value === 'paused') return 'is-warning'
  if (value === 'running' || value === 'queued') return 'is-running'
  return 'is-neutral'
}

function progress(item: TaskItem) {
  if (item.task.status === 'completed') return 100
  if (item.task.status === 'queued') return 6
  if (item.task.status === 'review_required') return item.task.stage === 'quality_review' ? 92 : 56
  const stages = ['segmenting', 'tts', 'audio_merge', 'subtitles', 'storyboard', 'asset_search', 'asset_review', 'scene_render', 'visual_track', 'final_render', 'quality_check']
  const index = stages.indexOf(item.task.stage || '')
  return index < 0 ? 18 : Math.max(10, Math.round((index + 1) / stages.length * 100))
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const projects = await listProjects()
    const values = await Promise.all(projects.map(async (project) => {
      try { return { project, task: await getProjectTaskStatus(project.id) } }
      catch { return null }
    }))
    tasks.value = values.filter((item): item is TaskItem => Boolean(item && item.task.status !== 'idle'))
  } catch (err) {
    error.value = err instanceof Error ? err.message : '任务中心加载失败'
  } finally {
    loading.value = false
  }
}

async function cancel(item: TaskItem) {
  try {
    await cancelProjectTask(item.project.id)
    await load()
    selected.value = null
  } catch (err) {
    error.value = err instanceof Error ? err.message : '取消任务失败'
  }
}

onMounted(() => {
  void load()
  refreshTimer = window.setInterval(load, 10000)
})
onBeforeUnmount(() => { if (refreshTimer !== undefined) window.clearInterval(refreshTimer) })
</script>

<template>
  <section class="task-center-page">
    <header class="page-header">
      <div><span class="section-eyebrow">BACKGROUND TASKS</span><h1>任务中心</h1><p>离开生产页面后，仍可追踪每个后台任务、恢复点和异常信息。</p></div>
      <button class="primary-button" :disabled="loading" @click="load"><RefreshCw :size="16" /> 刷新任务</button>
    </header>

    <div class="metric-grid task-metrics">
      <button class="metric-card" @click="status = 'queued'"><span>排队中</span><strong>{{ counts.queued }}</strong><Clock3 :size="18" /></button>
      <button class="metric-card accent-card" @click="status = 'running'"><span>运行中</span><strong>{{ counts.running }}</strong><RefreshCw :size="18" /></button>
      <button class="metric-card" @click="status = 'review'"><span>等待审核</span><strong>{{ counts.review }}</strong><PauseCircle :size="18" /></button>
      <button class="metric-card" @click="status = 'failed'"><span>失败</span><strong>{{ counts.failed }}</strong><AlertCircle :size="18" /></button>
      <button class="metric-card" @click="status = 'completed'"><span>今日完成</span><strong>{{ counts.completed }}</strong><CheckCircle2 :size="18" /></button>
    </div>

    <div v-if="error" class="alert alert-danger"><strong>任务状态异常</strong><span>{{ error }}</span></div>

    <div class="panel task-filter-bar">
      <label class="search-field"><ListFilter :size="16" /><input v-model="query" type="search" placeholder="搜索项目或阶段" /></label>
      <select v-model="type" class="filter-select"><option value="all">全部任务类型</option><option value="narration_generation">配音与字幕</option><option value="video_synthesis">视频生产</option></select>
      <select v-model="status" class="filter-select"><option value="all">全部状态</option><option value="queued">排队中</option><option value="running">运行中</option><option value="review">等待审核</option><option value="failed">失败</option><option value="completed">已完成</option></select>
      <label class="checkbox-field compact-checkbox"><input type="checkbox" :checked="status === 'failed'" @change="status = status === 'failed' ? 'all' : 'failed'" /><span><strong>只看异常</strong></span></label>
    </div>

    <article class="panel task-table-panel">
      <div class="task-table task-table-head"><span>任务 / 所属项目</span><span>当前阶段</span><span>进度</span><span>开始时间</span><span>运行耗时</span><span>操作</span></div>
      <button v-for="item in filtered" :key="item.task.id || item.project.id" class="task-table task-table-row" @click="selected = item">
        <span><strong>{{ item.task.workflow === 'video_synthesis' ? '视频生产' : '配音与字幕' }}</strong><small>{{ item.project.name }}</small></span>
        <span><strong>{{ stageLabels[item.task.stage || ''] || item.task.stage || '准备中' }}</strong><small>{{ item.task.error_message || '任务状态正常' }}</small></span>
        <span><span class="task-progress"><i :style="{ width: `${progress(item)}%` }"></i></span><small>{{ progress(item) }}%</small></span>
        <span>{{ item.task.started_at ? formatDateTime(item.task.started_at) : '等待开始' }}</span>
        <span>{{ formatDuration(item.task.workflow_duration_seconds || 0) }}</span>
        <span><span class="status-pill" :class="tone(item.task.status)">{{ statusLabels[item.task.status] }}</span></span>
      </button>
      <div v-if="!filtered.length" class="empty-state compact-empty"><h2>{{ loading ? '正在同步任务…' : '没有匹配的后台任务' }}</h2><p>调整筛选条件，或从项目工作区启动新的生产任务。</p></div>
    </article>

    <div v-if="selected" class="task-drawer-backdrop" @click.self="selected = null">
      <aside class="task-drawer">
        <header><div><span class="section-eyebrow">TASK DETAIL</span><h2>{{ selected.project.name }}</h2></div><button class="icon-button" @click="selected = null"><X :size="19" /></button></header>
        <div class="task-drawer-summary"><span class="status-pill" :class="tone(selected.task.status)">{{ statusLabels[selected.task.status] }}</span><strong>{{ stageLabels[selected.task.stage || ''] || selected.task.stage }}</strong><p>{{ selected.task.error_message || '任务正在按工作流检查点执行。' }}</p></div>
        <dl class="output-path-list">
          <div><dt>任务编号</dt><dd>{{ selected.task.id || '—' }}</dd></div>
          <div><dt>工作流</dt><dd>{{ selected.task.workflow || '—' }}</dd></div>
          <div><dt>创建时间</dt><dd>{{ selected.task.created_at ? formatDateTime(selected.task.created_at) : '—' }}</dd></div>
          <div><dt>开始时间</dt><dd>{{ selected.task.started_at ? formatDateTime(selected.task.started_at) : '—' }}</dd></div>
          <div><dt>恢复补偿次数</dt><dd>{{ selected.task.compensation_count || 0 }}</dd></div>
        </dl>
        <div class="drawer-actions"><RouterLink class="primary-link" :to="`/projects/${selected.project.id}/overview`">进入项目</RouterLink><button v-if="selected.task.running || selected.task.queued" class="danger-button" @click="cancel(selected)">取消任务</button></div>
      </aside>
    </div>
  </section>
</template>
