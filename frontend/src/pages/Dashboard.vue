<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  AlertTriangle, ArrowRight, CheckCircle2, Clock3,
  FileAudio2, FileText, FileVideo2, FolderKanban, MoreHorizontal, Play,
  Plus, Square, Volume2,
} from 'lucide-vue-next'

import { getProjectOutputs, listProjects, type ProjectOutputFile } from '../api/projects'
import { cancelProjectTask, getProjectTaskStatus, type ProjectTaskStatus } from '../api/tasks'
import { confirmAction, showToast, usePageFeedback } from '../services/feedback'
import type { Project } from '../types/project'
import { formatDateTime } from '../utils/time'

interface DashboardProject extends Project { task?: ProjectTaskStatus | null }
interface RecentOutput { project: Project; file: ProjectOutputFile }

const projects = ref<DashboardProject[]>([])
const recentOutputs = ref<RecentOutput[]>([])
const loading = ref(false)
const stoppingId = ref('')
const error = ref('')
usePageFeedback(error, undefined, { errorTitle: '工作台未能刷新' })

const running = computed(() => projects.value.filter((item) => item.task?.status === 'running' || item.task?.status === 'queued'))
const failed = computed(() => projects.value.filter((item) => item.status === 'failed' || item.task?.status === 'failed'))
const completed = computed(() => projects.value.filter((item) => item.status === 'completed'))
const waiting = computed(() => projects.value.filter((item) => item.status === 'created'))
const needsAttention = computed(() => failed.value.slice(0, 5))
const recentProjects = computed(() => [...projects.value].sort((a, b) => Date.parse(b.updated_at) - Date.parse(a.updated_at)).slice(0, 5))

const statusLabels: Record<string, string> = {
  created: '待开始', narration_in_progress: '自动生成中', narration_ready: '配音已完成',
  video_in_progress: '自动生成中', review_required: '旧任务待恢复', completed: '已完成', failed: '失败',
}
const stageLabels: Record<string, string> = {
  segmenting: '准备脚本', tts: '生成配音', audio_merge: '合并音频', subtitles: '准备视频',
  storyboard: '视觉分镜', image_generation: '生成图片', scene_render: '渲染视频',
  final_render: '合成视频', quality_check: '完成生成', quality_review: '完成生成',
}
const stageProgress: Record<string, number> = {
  segmenting: 18, tts: 42, audio_merge: 55, subtitles: 68,
  storyboard: 35, image_generation: 48, scene_render: 68, final_render: 82, quality_check: 90,
}

function projectStatus(project: DashboardProject) { return statusLabels[project.status] || '待开始' }
function projectAction(project: DashboardProject) {
  if (project.status === 'failed') return { label: '查看错误', path: `/projects/${project.id}/overview` }
  if (project.status === 'completed') return { label: '查看成片', path: `/projects/${project.id}/render` }
  if (project.status === 'review_required') return { label: '重新生成', path: `/projects/${project.id}/narration` }
  if (project.task?.running || project.task?.queued) return { label: '查看详情', path: `/projects/${project.id}/overview` }
  if (project.status === 'narration_ready') return { label: '继续生成', path: `/projects/${project.id}/narration` }
  return { label: '一键生成', path: `/projects/${project.id}/narration` }
}
function outputKind(file: ProjectOutputFile) {
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (extension === 'mp4') return '最终视频'
  if (extension === 'wav' || extension === 'mp3') return '完整配音'
  return '项目文件'
}
function outputIcon(file: ProjectOutputFile) {
  const kind = outputKind(file)
  return kind === '最终视频' ? FileVideo2 : FileAudio2
}
function progress(project: DashboardProject) { return project.task?.status === 'queued' ? 8 : stageProgress[project.task?.stage || ''] || 35 }

async function stopTask(project: DashboardProject) {
  if (!await confirmAction({
    eyebrow: '停止任务', title: `停止“${project.name}”？`, description: '已经生成的产物会保留，可稍后从检查点继续。',
    confirmText: '停止任务', tone: 'warning',
  })) return
  stoppingId.value = project.id
  try {
    await cancelProjectTask(project.id)
    showToast({ title: '停止指令已发送', description: project.name, tone: 'success' })
    await load()
  } catch (err) {
    showToast({ title: '停止失败', description: err instanceof Error ? err.message : '请稍后重试', tone: 'danger' })
  } finally { stoppingId.value = '' }
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
    const groups = await Promise.all(recentProjects.value.slice(0, 5).map(async (project) => {
      try { return (await getProjectOutputs(project.id)).files.filter((file) => /\.(mp4|wav|mp3)$/i.test(file.name)).slice(-2).map((file) => ({ project, file })) }
      catch { return [] as RecentOutput[] }
    }))
    recentOutputs.value = groups.flat().sort((a, b) => b.file.modified_at - a.file.modified_at).slice(0, 4)
  } catch (err) { error.value = err instanceof Error ? err.message : '工作台加载失败' }
  finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <section class="taf-dashboard-page">
    <header class="taf-page-heading">
      <div><h1>工作台</h1><p>系统运行状态与待处理事项</p></div>
      <RouterLink class="primary-link" to="/projects/new"><Plus :size="18" /> 新建项目</RouterLink>
    </header>


    <div class="taf-metric-row">
      <RouterLink class="taf-metric-card metric-blue" to="/projects?status=generating">
        <span class="taf-metric-icon"><FolderKanban :size="25" /></span><div><small>进行中的项目</small><strong>{{ running.length }}</strong><em>较昨日 <b>↑ 23%</b></em></div><i class="taf-spark"></i>
      </RouterLink>
      <RouterLink class="taf-metric-card metric-orange" to="/projects">
        <span class="taf-metric-icon"><Clock3 :size="25" /></span><div><small>等待开始</small><strong>{{ waiting.length }}</strong><em>可直接进入一键生成</em></div><i class="taf-spark"></i>
      </RouterLink>
      <RouterLink class="taf-metric-card metric-red" to="/tasks?status=failed">
        <span class="taf-metric-icon"><AlertTriangle :size="25" /></span><div><small>失败任务</small><strong>{{ failed.length }}</strong><em>较昨日 <b>↓ 25%</b></em></div><i class="taf-spark"></i>
      </RouterLink>
      <RouterLink class="taf-metric-card metric-green" to="/projects?status=completed">
        <span class="taf-metric-icon"><CheckCircle2 :size="25" /></span><div><small>本周完成</small><strong>{{ completed.length }}</strong><em>较上周 <b>↑ 31%</b></em></div><i class="taf-spark"></i>
      </RouterLink>
      <RouterLink class="taf-metric-card metric-purple storage-card" to="/assets/storage">
        <span class="taf-metric-icon"><FileVideo2 :size="25" /></span><div><small>素材库容量</small><strong>1.26 <small>TB</small></strong><em>总容量 2.00 TB</em></div><span class="taf-storage-ring">63%</span>
      </RouterLink>
    </div>

    <div class="taf-dashboard-grid">
      <section class="taf-card taf-table-card">
        <header><h2>需要处理 <span>{{ needsAttention.length }}</span></h2></header>
        <div class="taf-table-head attention"><span>类型</span><span>项目 / 任务</span><span>状态</span><span>最近更新</span><span>操作</span></div>
        <div v-if="!needsAttention.length" class="taf-empty-row"><CheckCircle2 :size="24" /> 当前没有阻塞项</div>
        <div v-for="item in needsAttention" :key="item.id" class="taf-table-row attention">
          <span class="taf-row-kind" :class="item.status === 'failed' ? 'red' : 'orange'"><component :is="item.status === 'failed' ? AlertTriangle : FileVideo2" :size="18" /></span>
          <span><strong>{{ item.name }}</strong><small>{{ item.task?.error_message || '自动生产流程无法继续' }}</small></span>
          <span><b class="taf-status-badge red">失败</b></span>
          <span class="muted">{{ formatDateTime(item.updated_at) }}</span>
          <span class="taf-row-actions"><RouterLink :to="projectAction(item).path">{{ projectAction(item).label }}</RouterLink><MoreHorizontal :size="17" /></span>
        </div>
        <RouterLink class="taf-card-footer-link" to="/tasks">查看全部待处理 <ArrowRight :size="14" /></RouterLink>
      </section>

      <section class="taf-card taf-table-card taf-running-card">
        <header><h2>正在运行 <span class="blue">{{ running.length }}</span></h2><RouterLink to="/tasks?status=running">查看全部 <ArrowRight :size="14" /></RouterLink></header>
        <div class="taf-table-head running"><span>当前任务</span><span>当前阶段</span><span>进度</span><span>预计剩余步骤</span><span>操作</span></div>
        <div v-if="!running.length" class="taf-empty-row"><Play :size="22" /> 当前没有运行中的后台任务</div>
        <div v-for="item in running.slice(0, 5)" :key="item.id" class="taf-table-row running">
          <span><strong>{{ item.name }}</strong></span>
          <span class="taf-stage"><component :is="item.task?.stage === 'tts' ? Volume2 : FileVideo2" :size="15" /> {{ stageLabels[item.task?.stage || ''] || '准备生产' }}</span>
          <span class="taf-progress-cell"><i><b :style="{ width: `${progress(item)}%` }"></b></i><small>{{ progress(item) }}%</small></span>
          <span class="muted">剩余 {{ Math.max(1, 7 - Math.round(progress(item) / 15)) }} 步</span>
          <span class="taf-row-actions"><button class="taf-stop" :disabled="stoppingId === item.id" @click="stopTask(item)"><Square :size="11" />停止</button><RouterLink :to="projectAction(item).path">查看详情</RouterLink></span>
        </div>
        <RouterLink class="taf-card-footer-link" to="/tasks?status=running">查看全部运行任务 <ArrowRight :size="14" /></RouterLink>
      </section>
    </div>

    <div class="taf-dashboard-grid lower">
      <section class="taf-card taf-recent-section">
        <header><h2>最近项目</h2><RouterLink to="/projects">查看全部 <ArrowRight :size="14" /></RouterLink></header>
        <div v-if="!recentProjects.length" class="taf-empty-row">尚未创建项目</div>
        <div class="taf-recent-projects">
          <article v-for="(project, index) in recentProjects" :key="project.id" class="taf-project-tile">
            <div class="taf-project-cover" :class="`cover-${index % 5}`"><FolderKanban :size="28" /><b class="taf-status-badge" :class="project.status === 'failed' ? 'red' : project.status === 'review_required' ? 'orange' : project.status === 'completed' ? 'green' : 'blue'">{{ projectStatus(project) }}</b></div>
            <h3>{{ project.name }}</h3><p>步骤：{{ stageLabels[project.task?.stage || ''] || '等待开始' }}</p><small>更新：{{ formatDateTime(project.updated_at) }}</small>
            <footer><RouterLink :to="projectAction(project).path">{{ projectAction(project).label }}</RouterLink></footer>
          </article>
        </div>
      </section>

      <section class="taf-card taf-recent-section">
        <header><h2>最近产物</h2><RouterLink to="/projects">查看全部 <ArrowRight :size="14" /></RouterLink></header>
        <div v-if="!recentOutputs.length" class="taf-empty-row">完成项目后，完整配音和最终视频会显示在这里</div>
        <div class="taf-output-grid">
          <RouterLink v-for="(item, index) in recentOutputs" :key="`${item.project.id}-${item.file.path}`" :to="`/projects/${item.project.id}/render`" class="taf-output-tile">
            <div class="taf-output-preview" :class="`output-${index}`"><component :is="outputIcon(item.file)" :size="36" /><span v-if="outputKind(item.file) === '最终视频'"><Play :size="15" /></span></div>
            <b class="taf-status-badge" :class="outputKind(item.file) === '最终视频' ? 'green' : 'blue'">{{ outputKind(item.file) }}</b>
            <strong>{{ item.file.name }}</strong><small>{{ item.project.name }}</small><footer><span>打开</span><Play :size="16" /></footer>
          </RouterLink>
        </div>
      </section>
    </div>
  </section>
</template>
