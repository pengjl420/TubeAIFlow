<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Archive, ArrowDown, ArrowRight, AudioLines, CheckCircle2, ChevronDown, Clock3,
  Download, FileVideo2, Folder, FolderKanban, MoreVertical, Play, Plus, RefreshCw,
  Search, Trash2, Upload, WandSparkles, XCircle,
} from 'lucide-vue-next'

import { deleteProject, listProjects } from '../../api/projects'
import { cancelProjectTask } from '../../api/tasks'
import { confirmAction, showToast } from '../../services/feedback'
import type { Project } from '../../types/project'
import { formatDateTime, formatDuration } from '../../utils/time'

const projects = ref<Project[]>([])
const loading = ref(false)
const error = ref('')
const query = ref('')
const statusFilter = ref('all')
const modeFilter = ref('all')
const selectedProjectIds = ref<Set<string>>(new Set())
const actingProjectId = ref('')
const batchDeleting = ref(false)
const router = useRouter()
const route = useRoute()
let refreshTimer: number | undefined

const statusLabels: Record<string, string> = {
  created: '待开始', script_imported: '待开始', segmented: '待开始', segmenting: '配音生成中',
  narration_in_progress: '配音生成中', tts: '配音生成中', tts_running: '配音生成中',
  tts_completed: '等待字幕', audio_merge: '配音生成中', audio_merged: '等待字幕', subtitles: '字幕生成中',
  narration_ready: '等待审核', video_in_progress: '视频生成中', video_composing: '视频生成中',
  rendering: '视频生成中', video_completed: '等待复核', review_required: '等待审核',
  completed: '已完成', failed: '失败', cancelled: '已停止',
}
const generatingStatuses = new Set(['segmenting', 'narration_in_progress', 'tts', 'tts_running', 'audio_merge', 'subtitles', 'video_in_progress', 'video_composing', 'rendering'])
const waitingStatuses = new Set(['tts_completed', 'audio_merged', 'narration_ready', 'video_completed', 'review_required'])

const filteredProjects = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return projects.value.filter((project) => {
    const matchesQuery = !keyword || project.name.toLowerCase().includes(keyword) || project.id.toLowerCase().includes(keyword)
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'generating' && isGenerating(project))
      || (statusFilter.value === 'waiting' && waitingStatuses.has(project.status))
      || project.status === statusFilter.value
    const mode = project.config?.video_mode || 'none'
    return matchesQuery && matchesStatus && (modeFilter.value === 'all' || mode === modeFilter.value)
  })
})
const activeCount = computed(() => projects.value.filter(isGenerating).length)
const waitingCount = computed(() => projects.value.filter((item) => waitingStatuses.has(item.status)).length)
const completedCount = computed(() => projects.value.filter((item) => item.status === 'completed').length)
const failedCount = computed(() => projects.value.filter((item) => item.status === 'failed').length)
const selectable = computed(() => filteredProjects.value.filter((item) => !isGenerating(item)))
const selectedProjects = computed(() => projects.value.filter((item) => selectedProjectIds.value.has(item.id) && !isGenerating(item)))
const allSelected = computed(() => selectable.value.length > 0 && selectable.value.every((item) => selectedProjectIds.value.has(item.id)))

function isGenerating(project: Project) { return generatingStatuses.has(project.status) || project.latest_task_status === 'running' }
function statusLabel(project: Project) { return statusLabels[project.status] || '待处理' }
function statusTone(project: Project) {
  if (project.status === 'failed') return 'red'
  if (project.status === 'completed') return 'green'
  if (waitingStatuses.has(project.status)) return 'orange'
  if (isGenerating(project)) return 'blue'
  return 'gray'
}
function voiceName(project: Project) {
  const name = project.config?.voice_profile_name || project.config?.reference_audio_filename
  return typeof name === 'string' && name ? name.replace(/\.[^.]+$/, '') : '未配置音色'
}
function videoMode(project: Project) {
  const mode = project.config?.video_mode
  return mode === 'none' ? '仅配音字幕' : mode === 'landscape' ? 'Vlog' : mode === 'ai_generated_images' ? '图文快剪' : '访谈纪实'
}
function projectStage(project: Project) {
  if (project.status === 'failed') return '视频渲染失败'
  if (project.status === 'completed') return '已完成 100%'
  if (project.status === 'review_required') return '素材审核'
  if (project.status === 'narration_ready') return '字幕校对'
  if (project.status === 'video_in_progress' || project.status === 'rendering') return '视频渲染'
  if (isGenerating(project)) return '配音生成'
  return '未开始'
}
function stageProgress(project: Project) {
  if (project.status === 'completed') return 100
  if (project.status === 'review_required') return 42
  if (project.status === 'narration_ready') return 68
  if (project.status === 'video_in_progress' || project.status === 'rendering') return 68
  if (isGenerating(project)) return 60
  return 0
}
function projectTarget(project: Project) {
  if (project.status === 'completed') return `/projects/${project.id}/delivery`
  if (project.status === 'review_required') return `/projects/${project.id}/media-review`
  if (project.status === 'narration_ready') return `/projects/${project.id}/subtitles`
  return `/projects/${project.id}/overview`
}
function actionLabel(project: Project) {
  if (project.status === 'completed') return '查看产物'
  if (project.status === 'review_required') return '审核素材'
  if (project.status === 'narration_ready') return '校对字幕'
  if (project.status === 'failed') return '查看错误'
  if (isGenerating(project)) return '查看进度'
  return '编辑逐字稿'
}
function toggleSelection(id: string) {
  const next = new Set(selectedProjectIds.value)
  next.has(id) ? next.delete(id) : next.add(id)
  selectedProjectIds.value = next
}
function toggleAll() {
  const next = new Set(selectedProjectIds.value)
  if (allSelected.value) selectable.value.forEach((item) => next.delete(item.id))
  else selectable.value.forEach((item) => next.add(item.id))
  selectedProjectIds.value = next
}
async function setWaitingFilter() {
  statusFilter.value = 'waiting'
  await nextTick()
  document.getElementById('project-table')?.scrollIntoView({ behavior: 'smooth' })
}

async function stopProject(project: Project) {
  if (!await confirmAction({ eyebrow: '停止生成任务', title: `停止“${project.name}”？`, description: '已生成的文件会保留，可稍后从检查点继续。', confirmText: '确认停止', tone: 'warning' })) return
  actingProjectId.value = project.id
  try { await cancelProjectTask(project.id); await loadProjects() }
  catch (err) { showToast({ title: '停止失败', description: err instanceof Error ? err.message : '请稍后重试', tone: 'danger' }) }
  finally { actingProjectId.value = '' }
}
async function removeSelected() {
  const targets = [...selectedProjects.value]
  if (!targets.length || !await confirmAction({ eyebrow: '批量删除', title: `删除已选中的 ${targets.length} 个项目？`, description: '项目记录和对应生成文件会移入系统回收站。', confirmText: '移入回收站', tone: 'danger' })) return
  batchDeleting.value = true
  const deleted = new Set<string>()
  for (const project of targets) {
    try { await deleteProject(project.id); deleted.add(project.id) } catch { /* show final count */ }
  }
  selectedProjectIds.value = new Set()
  await loadProjects()
  showToast({ title: `已删除 ${deleted.size} 个项目`, description: '相关内容已移入回收站', tone: deleted.size === targets.length ? 'success' : 'warning' })
  batchDeleting.value = false
}
function unsupported(label: string) { showToast({ title: `${label}暂未启用`, description: '当前版本尚未提供对应的批量接口。', tone: 'info' }) }

async function loadProjects() {
  loading.value = true; error.value = ''
  try { projects.value = await listProjects() }
  catch (err) { error.value = err instanceof Error ? err.message : '项目列表加载失败' }
  finally { loading.value = false }
}

onMounted(() => {
  if (typeof route.query.q === 'string') query.value = route.query.q
  if (typeof route.query.status === 'string') statusFilter.value = route.query.status
  void loadProjects()
  refreshTimer = window.setInterval(loadProjects, 15000)
})
onBeforeUnmount(() => { if (refreshTimer !== undefined) window.clearInterval(refreshTimer) })
</script>

<template>
  <section class="taf-project-list-page">
    <header class="taf-page-heading">
      <div><h1>项目</h1><p>管理所有单视频项目，快速进入生产流程</p></div>
      <div class="taf-heading-actions"><button class="secondary-button" @click="unsupported('导入项目')"><Upload :size="17" /> 导入项目</button><RouterLink class="primary-link" to="/projects/new"><Plus :size="18" /> 新建项目</RouterLink></div>
    </header>

    <div class="taf-project-metrics">
      <button class="taf-project-metric blue" @click="statusFilter = 'all'"><span><Folder :size="25" /></span><div><small>全部项目</small><strong>{{ projects.length }}</strong><em>较昨日 <b>↑ 18%</b></em></div><i></i></button>
      <button class="taf-project-metric orange" @click="statusFilter = 'generating'"><span><Play :size="24" /></span><div><small>进行中</small><strong>{{ activeCount }}</strong><em>较昨日 <b>↑ 23%</b></em></div><i></i></button>
      <button class="taf-project-metric yellow" @click="setWaitingFilter"><span><Clock3 :size="24" /></span><div><small>等待审核</small><strong>{{ waitingCount }}</strong><em>较昨日 <b>↑ 12%</b></em></div><i></i></button>
      <button class="taf-project-metric green" @click="statusFilter = 'completed'"><span><CheckCircle2 :size="24" /></span><div><small>已完成</small><strong>{{ completedCount }}</strong><em>较昨日 <b>↑ 8%</b></em></div><i></i></button>
      <button class="taf-project-metric red" @click="statusFilter = 'failed'"><span><XCircle :size="24" /></span><div><small>失败/异常</small><strong>{{ failedCount }}</strong><em>较昨日 <b>↓ 20%</b></em></div><i></i></button>
    </div>

    <div class="taf-project-layout">
      <section id="project-table" class="taf-card taf-project-table-card">
        <div class="taf-project-filters">
          <label><Search :size="17" /><input v-model="query" type="search" placeholder="搜索项目名称" /></label>
          <select v-model="statusFilter"><option value="all">全部状态</option><option value="generating">生成中</option><option value="waiting">等待处理</option><option value="review_required">等待审核</option><option value="completed">已完成</option><option value="failed">失败/异常</option></select>
          <select v-model="modeFilter"><option value="all">全部视频模式</option><option value="ai_generated_images">图文快剪</option><option value="ai_semantic">访谈纪实</option><option value="landscape">Vlog</option><option value="none">仅配音字幕</option></select>
          <button class="taf-filter-button">最近更新时间 <ChevronDown :size="14" /></button>
          <button class="taf-filter-button">负责人 / 音色 <ChevronDown :size="14" /></button>
          <span class="taf-filter-spacer"></span><button class="taf-filter-button" :disabled="loading" @click="loadProjects"><RefreshCw :size="15" /></button>
        </div>

        <div v-if="error" class="alert alert-danger"><strong>项目列表未能更新</strong><span>{{ error }}</span></div>
        <div class="taf-project-table-head"><span><input type="checkbox" :checked="allSelected" @change="toggleAll" /></span><span>项目名称</span><span>生命周期状态</span><span>当前阶段</span><span>视频模式</span><span>音色</span><span>总时长</span><span>最近更新时间</span><span>主操作</span><span></span></div>
        <div v-if="loading && !projects.length" class="taf-empty-row">正在加载项目...</div>
        <div v-else-if="!filteredProjects.length" class="taf-empty-row">没有匹配的项目</div>
        <div v-for="(project, index) in filteredProjects" :key="project.id" class="taf-project-table-row" :class="{ selected: selectedProjectIds.has(project.id) }">
          <span><input type="checkbox" :checked="selectedProjectIds.has(project.id)" :disabled="isGenerating(project)" @change="toggleSelection(project.id)" /></span>
          <span class="taf-project-name"><i :class="`thumb-${index % 5}`"><FileVideo2 :size="20" /></i><span><strong>{{ project.name }}</strong><small>{{ project.id.slice(0, 16).toUpperCase() }}</small></span></span>
          <span><b class="taf-status-badge" :class="statusTone(project)">{{ statusLabel(project) }}</b></span>
          <span class="taf-stage-progress"><strong :class="project.status === 'failed' ? 'error' : ''">{{ projectStage(project) }}</strong><i><b :class="statusTone(project)" :style="{ width: `${stageProgress(project)}%` }"></b></i></span>
          <span>{{ videoMode(project) }}</span>
          <span class="taf-voice"><AudioLines :size="16" /> {{ voiceName(project) }}</span>
          <span>{{ formatDuration(project.audio_duration_seconds || null, '—') }}</span>
          <span class="taf-date"><strong>{{ formatDateTime(project.updated_at) }}</strong><small>本地项目</small></span>
          <span><RouterLink class="taf-table-action" :to="projectTarget(project)">{{ actionLabel(project) }} <ArrowRight :size="13" /></RouterLink></span>
          <span><button v-if="isGenerating(project)" class="taf-icon-button" :disabled="actingProjectId === project.id" @click="stopProject(project)"><MoreVertical :size="17" /></button><button v-else class="taf-icon-button" @click="router.push(`/projects/${project.id}/settings`)"><MoreVertical :size="17" /></button></span>
        </div>
      </section>

      <aside class="taf-project-aside">
        <section class="taf-card taf-bulk-card">
          <header><h2>批量操作</h2><button @click="selectedProjectIds = new Set()">清空选择</button></header><p>已选中 <b>{{ selectedProjects.length }}</b> 项</p>
          <button @click="unsupported('批量归档')"><Archive :size="16" /> 批量归档</button>
          <button class="danger" :disabled="batchDeleting || !selectedProjects.length" @click="removeSelected"><Trash2 :size="16" /> {{ batchDeleting ? '删除中...' : '批量删除' }}</button>
          <button @click="router.push('/voices')"><WandSparkles :size="16" /> 批量分配音色</button>
          <button @click="router.push('/batches/new')"><FolderKanban :size="16" /> 批量移至批次 <ArrowRight :size="14" /></button>
        </section>

        <section class="taf-card taf-donut-card"><h2>项目状态分布</h2><div class="taf-donut" :style="{ '--complete': `${projects.length ? completedCount / projects.length * 100 : 0}%` }"><span><strong>{{ projects.length }}</strong>总项目</span></div><ul><li><i class="blue"></i>配音生成中 <b>{{ activeCount }}</b></li><li><i class="orange"></i>等待审核 <b>{{ waitingCount }}</b></li><li><i class="green"></i>已完成 <b>{{ completedCount }}</b></li><li><i class="red"></i>失败/异常 <b>{{ failedCount }}</b></li></ul></section>

        <section class="taf-card taf-owner-card"><h2>项目负责人 Top 5</h2><div v-for="(name, index) in ['张三', '李四', '王五', '赵六', '孙七']" :key="name"><span>{{ name }}</span><i><b :style="{ width: `${88 - index * 12}%` }"></b></i><small>{{ Math.max(1, projects.length - index) }}</small></div></section>
      </aside>
    </div>
  </section>
</template>
