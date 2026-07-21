<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { AlertTriangle, ArrowRight, CheckCircle2, Clock3, FileVideo2, FolderKanban, Play, Plus, RefreshCw } from 'lucide-vue-next'

import { getProjectOutputs, listProjects, type ProjectOutputFile } from '../api/projects'
import { getProjectTaskStatus, type ProjectTaskStatus } from '../api/tasks'
import type { Project } from '../types/project'
import { formatDateTime } from '../utils/time'

interface DashboardProject extends Project { task?: ProjectTaskStatus | null }
interface RecentOutput { project: Project; file: ProjectOutputFile }

const projects = ref<DashboardProject[]>([])
const recentOutputs = ref<RecentOutput[]>([])
const loading = ref(false)
const error = ref('')

const running = computed(() => projects.value.filter((item) => item.task?.status === 'running' || item.task?.status === 'queued'))
const review = computed(() => projects.value.filter((item) => item.status === 'review_required' || item.task?.status === 'review_required'))
const failed = computed(() => projects.value.filter((item) => item.status === 'failed' || item.task?.status === 'failed'))
const completed = computed(() => projects.value.filter((item) => item.status === 'completed'))
const needsAttention = computed(() => [...failed.value, ...review.value].slice(0, 5))
const recentProjects = computed(() => [...projects.value].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 6))

const statusLabels: Record<string, string> = {
  created: '待开始', narration_in_progress: '配音生成中', narration_ready: '字幕待确认',
  video_in_progress: '视频生成中', review_required: '等待人工审核', completed: '已完成', failed: '执行失败',
}

const stageLabels: Record<string, string> = {
  segmenting: '文本切段', tts: '生成配音', audio_merge: '合并音频', subtitles: '生成字幕',
  storyboard: '视觉分镜', asset_search: '素材检索', asset_review: '素材审核', scene_render: '场景渲染',
  final_render: '最终合成', quality_check: '质量检查', quality_review: '质量复核',
}

function projectStatus(project: DashboardProject) {
  return statusLabels[project.status] || project.status.split('_').join(' ')
}

function statusTone(project: DashboardProject) {
  if (project.status === 'failed' || project.task?.status === 'failed') return 'is-danger'
  if (project.status === 'completed') return 'is-success'
  if (project.status === 'review_required' || project.task?.status === 'review_required') return 'is-warning'
  if (project.task?.running || project.task?.queued) return 'is-running'
  return 'is-neutral'
}

function projectAction(project: DashboardProject) {
  if (project.status === 'failed') return { label: '查看错误', path: `/projects/${project.id}/overview` }
  if (project.status === 'completed') return { label: '查看产物', path: `/projects/${project.id}/delivery` }
  if (project.status === 'review_required') {
    return project.task?.stage === 'quality_review'
      ? { label: '查看 QA', path: `/projects/${project.id}/delivery` }
      : { label: '审核素材', path: `/projects/${project.id}/media-review` }
  }
  if (project.task?.running || project.task?.queued) return { label: '查看进度', path: `/projects/${project.id}/overview` }
  if (project.status === 'narration_ready') return { label: '校对字幕', path: `/projects/${project.id}/subtitles` }
  return { label: '编辑逐字稿', path: `/projects/${project.id}/narration` }
}

function outputKind(file: ProjectOutputFile) {
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (extension === 'mp4' || extension === 'fcpxml') return '最终视频'
  if (extension === 'wav' || extension === 'mp3') return '完整配音'
  if (extension === 'srt') return '字幕文件'
  if (extension === 'json') return '生产报告'
  return '项目产物'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const base = await listProjects()
    projects.value = await Promise.all(base.map(async (project) => {
      try { return { ...project, task: await getProjectTaskStatus(project.id) } }
      catch { return { ...project, task: null } }
    }))
    const outputGroups = await Promise.all(recentProjects.value.slice(0, 4).map(async (project) => {
      try {
        const outputs = await getProjectOutputs(project.id)
        return outputs.files.slice(-2).map((file) => ({ project, file }))
      } catch { return [] as RecentOutput[] }
    }))
    recentOutputs.value = outputGroups.flat().sort((a, b) => b.file.modified_at - a.file.modified_at).slice(0, 6)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '工作台加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="dashboard-page">
    <header class="page-header dashboard-title">
      <div><span class="section-eyebrow">PRODUCTION OVERVIEW</span><h1>工作台</h1><p>掌握当前生产状态，并优先处理阻塞视频交付的问题。</p></div>
      <div class="page-title-actions">
        <button class="secondary-button" :disabled="loading" @click="load"><RefreshCw :size="16" /> 刷新</button>
        <RouterLink class="primary-link" to="/projects/new"><Plus :size="17" /> 新建项目</RouterLink>
      </div>
    </header>

    <div v-if="error" class="alert alert-danger"><strong>工作台未能刷新</strong><span>{{ error }}</span></div>

    <div class="metric-grid dashboard-metrics">
      <RouterLink class="metric-card accent-card" to="/tasks?status=running"><span>进行中的项目</span><strong>{{ running.length }}</strong><small>查看当前后台任务</small></RouterLink>
      <RouterLink class="metric-card" to="/tasks?status=review"><span>等待审核</span><strong>{{ review.length }}</strong><small>需要人工确认</small></RouterLink>
      <RouterLink class="metric-card" to="/tasks?status=failed"><span>失败任务</span><strong>{{ failed.length }}</strong><small>需要排查和重试</small></RouterLink>
      <RouterLink class="metric-card" to="/projects?status=completed"><span>已完成</span><strong>{{ completed.length }}</strong><small>可查看交付产物</small></RouterLink>
      <RouterLink class="metric-card" to="/assets"><span>素材中心</span><strong>本地</strong><small>审核、索引与存储</small></RouterLink>
    </div>

    <div class="dashboard-layout">
      <section>
        <div class="section-toolbar"><div><span class="section-eyebrow">ACTION REQUIRED</span><h2>需要处理</h2></div><RouterLink to="/tasks">查看全部任务 <ArrowRight :size="15" /></RouterLink></div>
        <article v-if="!needsAttention.length" class="panel empty-state compact-empty"><CheckCircle2 :size="28" /><h2>当前没有阻塞项</h2><p>需要人工审核或处理的失败任务会出现在这里。</p></article>
        <div v-else class="attention-list">
          <RouterLink v-for="item in needsAttention" :key="item.id" class="panel attention-row" :to="projectAction(item).path">
            <span class="attention-icon" :class="item.status === 'failed' ? 'is-danger' : 'is-warning'"><component :is="item.status === 'failed' ? AlertTriangle : Clock3" :size="18" /></span>
            <div><strong>{{ item.name }}</strong><small>{{ item.status === 'failed' ? (item.task?.error_message || '生产任务执行失败') : '等待人工确认后继续生产' }}</small></div>
            <span class="status-pill" :class="statusTone(item)">{{ projectAction(item).label }}</span>
          </RouterLink>
        </div>
      </section>

      <section>
        <div class="section-toolbar"><div><span class="section-eyebrow">RUNNING NOW</span><h2>正在运行</h2></div><span class="status-pill is-running">{{ running.length }} 个任务</span></div>
        <article class="panel running-panel">
          <div v-if="!running.length" class="empty-state compact-empty"><Play :size="25" /><p>当前没有运行中的后台任务。</p></div>
          <div v-for="item in running.slice(0, 4)" :key="item.id" class="running-task-row">
            <div><strong>{{ item.name }}</strong><small>{{ stageLabels[item.task?.stage || ''] || '准备生产' }}</small></div>
            <div class="task-progress"><span :style="{ width: item.task?.status === 'queued' ? '8%' : '56%' }"></span></div>
            <RouterLink :to="`/projects/${item.id}/overview`">查看</RouterLink>
          </div>
        </article>
      </section>
    </div>

    <section class="dashboard-section">
      <div class="section-toolbar"><div><span class="section-eyebrow">RECENT PROJECTS</span><h2>最近项目</h2></div><RouterLink to="/projects">项目列表 <ArrowRight :size="15" /></RouterLink></div>
      <div class="project-grid">
        <article v-for="project in recentProjects" :key="project.id" class="project-card panel">
          <div class="project-card-top"><span class="project-avatar"><FolderKanban :size="19" /></span><span class="status-pill" :class="statusTone(project)">{{ projectStatus(project) }}</span></div>
          <div><h3>{{ project.name }}</h3><p>{{ stageLabels[project.task?.stage || ''] || '等待开始下一步' }}</p></div>
          <footer><small>{{ formatDateTime(project.updated_at) }}</small><RouterLink :to="projectAction(project).path">{{ projectAction(project).label }} <ArrowRight :size="14" /></RouterLink></footer>
        </article>
      </div>
    </section>

    <section class="dashboard-section">
      <div class="section-toolbar"><div><span class="section-eyebrow">RECENT OUTPUTS</span><h2>最近产物</h2></div></div>
      <div class="artifact-grid">
        <RouterLink v-for="item in recentOutputs" :key="`${item.project.id}-${item.file.path}`" class="panel artifact-card" :to="`/projects/${item.project.id}/delivery`">
          <span class="artifact-icon"><FileVideo2 :size="20" /></span><div><strong>{{ outputKind(item.file) }}</strong><small>{{ item.project.name }} · {{ item.file.name }}</small></div><ArrowRight :size="16" />
        </RouterLink>
        <article v-if="!recentOutputs.length" class="panel empty-state compact-empty"><p>完成项目后，配音、字幕、视频和报告会集中显示在这里。</p></article>
      </div>
    </section>
  </section>
</template>
