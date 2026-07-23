<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowRight, AudioLines, CheckCircle2, Clock3, Download, FileVideo2, Folder,
  FolderKanban, PauseCircle, Play, Plus, RefreshCw, Search, Trash2,
  WandSparkles, XCircle,
} from 'lucide-vue-next'

import { deleteProject, listProjects } from '../../api/projects'
import { cancelProjectTask } from '../../api/tasks'
import { confirmAction, showToast, usePageFeedback } from '../../services/feedback'
import type { Project } from '../../types/project'
import { formatDateTime, formatDuration } from '../../utils/time'

const projects = ref<Project[]>([])
const loading = ref(false)
const error = ref('')
usePageFeedback(error, undefined, { errorTitle: '项目列表未能更新' })
const query = ref('')
const statusFilter = ref('all')
const modeFilter = ref('all')
const voiceFilter = ref('all')
const sortOrder = ref<'updated_desc' | 'updated_asc' | 'name_asc' | 'name_desc'>('updated_desc')
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
  const filtered = projects.value.filter((project) => {
    const matchesQuery = !keyword || project.name.toLowerCase().includes(keyword) || project.id.toLowerCase().includes(keyword)
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'generating' && isGenerating(project))
      || (statusFilter.value === 'waiting' && waitingStatuses.has(project.status))
      || project.status === statusFilter.value
    const mode = project.config?.video_mode || 'none'
    return matchesQuery
      && matchesStatus
      && (modeFilter.value === 'all' || mode === modeFilter.value)
      && (voiceFilter.value === 'all' || voiceName(project) === voiceFilter.value)
  })
  return filtered.sort((left, right) => {
    if (sortOrder.value === 'name_asc') return left.name.localeCompare(right.name, 'zh-CN')
    if (sortOrder.value === 'name_desc') return right.name.localeCompare(left.name, 'zh-CN')
    const delta = Date.parse(left.updated_at) - Date.parse(right.updated_at)
    return sortOrder.value === 'updated_asc' ? delta : -delta
  })
})
const activeCount = computed(() => projects.value.filter(isGenerating).length)
const waitingCount = computed(() => projects.value.filter((item) => waitingStatuses.has(item.status)).length)
const completedCount = computed(() => projects.value.filter((item) => item.status === 'completed').length)
const failedCount = computed(() => projects.value.filter((item) => item.status === 'failed').length)
const selectable = computed(() => filteredProjects.value.filter((item) => !isGenerating(item)))
const selectedProjects = computed(() => projects.value.filter((item) => selectedProjectIds.value.has(item.id) && !isGenerating(item)))
const allSelected = computed(() => selectable.value.length > 0 && selectable.value.every((item) => selectedProjectIds.value.has(item.id)))
const voiceOptions = computed(() => [...new Set(projects.value.map(voiceName))].sort((a, b) => a.localeCompare(b, 'zh-CN')))
const voiceDistribution = computed(() => {
  const counts = new Map<string, number>()
  projects.value.forEach((project) => counts.set(voiceName(project), (counts.get(voiceName(project)) || 0) + 1))
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 5)
})
const maxVoiceCount = computed(() => Math.max(1, ...voiceDistribution.value.map(([, count]) => count)))

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
  return mode === 'none' ? '仅配音字幕' : mode === 'landscape' ? 'Vlog' : mode === 'ai_landscape_mix' ? 'AI + 风景混剪' : mode === 'ai_generated_images' ? '图文快剪' : '访谈纪实'
}
function projectStage(project: Project) {
  if (project.status === 'failed') return '视频渲染失败'
  if (project.status === 'completed') return '已完成 100%'
  if (project.status === 'review_required') return '旧任务待恢复'
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
  if (project.status === 'review_required') return `/projects/${project.id}/narration`
  if (project.status === 'narration_ready') return `/projects/${project.id}/subtitles`
  return `/projects/${project.id}/overview`
}
function actionLabel(project: Project) {
  if (project.status === 'completed') return '查看产物'
  if (project.status === 'review_required') return '重新生成'
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
  if (!await confirmAction({ eyebrow: '强制暂停生成任务', title: `暂停“${project.name}”？`, description: '将终止当前生成子进程；已生成的文件会保留，可稍后从检查点继续。', confirmText: '确认强制暂停', tone: 'warning' })) return
  actingProjectId.value = project.id
  try {
    await cancelProjectTask(project.id)
    await loadProjects()
    showToast({ title: '强制暂停指令已发送', description: '当前子进程正在终止，已生成文件会保留。', tone: 'success' })
  }
  catch (err) { showToast({ title: '强制暂停失败', description: err instanceof Error ? err.message : '请稍后重试', tone: 'danger' }) }
  finally { actingProjectId.value = '' }
}
async function removeProject(project: Project) {
  if (isGenerating(project)) {
    showToast({ title: '项目仍在生成中', description: '请先强制暂停，确认任务停止后再删除。', tone: 'warning' })
    return
  }
  if (!await confirmAction({
    eyebrow: '删除项目',
    title: `删除“${project.name}”？`,
    description: '项目记录和对应生成文件会移入系统回收站。',
    confirmText: '确认删除',
    tone: 'danger',
  })) return
  actingProjectId.value = project.id
  try {
    await deleteProject(project.id)
    const selected = new Set(selectedProjectIds.value)
    selected.delete(project.id)
    selectedProjectIds.value = selected
    await loadProjects()
    showToast({ title: '项目已删除', description: project.name, tone: 'success' })
  } catch (err) {
    showToast({ title: '删除失败', description: err instanceof Error ? err.message : '请稍后重试', tone: 'danger' })
  } finally {
    actingProjectId.value = ''
  }
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
function exportSelectedList() {
  const targets = selectedProjects.value.length ? selectedProjects.value : filteredProjects.value
  if (!targets.length) {
    showToast({ title: '没有可导出的项目', description: '请调整筛选条件后重试。', tone: 'warning' })
    return
  }
  const quote = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`
  const rows = [
    ['项目 ID', '项目名称', '状态', '视频模式', '音色', '音频时长（秒）', '输出目录', '更新时间'],
    ...targets.map((project) => [project.id, project.name, statusLabel(project), videoMode(project), voiceName(project), project.audio_duration_seconds || '', project.output_dir || '', project.updated_at]),
  ]
  const blob = new Blob([`\uFEFF${rows.map((row) => row.map(quote).join(',')).join('\r\n')}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `TubeAIFlow-projects-${new Date().toISOString().slice(0, 10)}.csv`
  link.click()
  URL.revokeObjectURL(url)
  showToast({ title: `已导出 ${targets.length} 个项目`, description: '项目清单已保存为 CSV。', tone: 'success' })
}

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
      <div class="taf-heading-actions"><RouterLink class="secondary-button" to="/batches/new"><FolderKanban :size="17" /> 批量导入脚本</RouterLink><RouterLink class="primary-link" to="/projects/new"><Plus :size="18" /> 新建项目</RouterLink></div>
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
          <select v-model="modeFilter"><option value="all">全部视频模式</option><option value="ai_generated_images">图文快剪</option><option value="landscape">风景素材拼接</option><option value="none">仅配音字幕</option></select>
          <select v-model="sortOrder" aria-label="项目排序"><option value="updated_desc">最近更新优先</option><option value="updated_asc">最早更新优先</option><option value="name_asc">名称 A–Z</option><option value="name_desc">名称 Z–A</option></select>
          <select v-model="voiceFilter" aria-label="音色筛选"><option value="all">全部音色</option><option v-for="name in voiceOptions" :key="name" :value="name">{{ name }}</option></select>
          <span class="taf-filter-spacer"></span><button class="taf-filter-button" :disabled="loading" @click="loadProjects"><RefreshCw :size="15" /></button>
        </div>

        <div class="taf-project-table-head"><span><input type="checkbox" :checked="allSelected" @change="toggleAll" /></span><span>项目名称</span><span>生命周期状态</span><span>当前阶段</span><span>视频模式</span><span>音色</span><span>总时长</span><span>最近更新时间</span><span>主操作</span><span>项目操作</span></div>
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
          <span class="taf-project-row-actions">
            <button
              class="taf-project-pause-button"
              :disabled="!isGenerating(project) || actingProjectId === project.id"
              :title="isGenerating(project) ? '强制暂停当前生成任务' : '当前没有生成中的任务'"
              @click="stopProject(project)"
            ><PauseCircle :size="13" />强制暂停</button>
            <button
              class="taf-project-delete-button"
              :disabled="isGenerating(project) || actingProjectId === project.id"
              :title="isGenerating(project) ? '请先强制暂停任务' : '删除项目'"
              @click="removeProject(project)"
            ><Trash2 :size="13" />删除</button>
          </span>
        </div>
      </section>

      <aside class="taf-project-aside">
        <section class="taf-card taf-bulk-card">
          <header><h2>批量操作</h2><button @click="selectedProjectIds = new Set()">清空选择</button></header><p>已选中 <b>{{ selectedProjects.length }}</b> 项</p>
          <button @click="exportSelectedList"><Download :size="16" /> {{ selectedProjects.length ? '导出所选清单' : '导出当前清单' }}</button>
          <button class="danger" :disabled="batchDeleting || !selectedProjects.length" @click="removeSelected"><Trash2 :size="16" /> {{ batchDeleting ? '删除中...' : '批量删除' }}</button>
          <button @click="router.push('/voices')"><WandSparkles :size="16" /> 批量分配音色</button>
          <button @click="router.push('/batches/new')"><FolderKanban :size="16" /> 批量移至批次 <ArrowRight :size="14" /></button>
        </section>

        <section class="taf-card taf-donut-card"><h2>项目状态分布</h2><div class="taf-donut" :style="{ '--complete': `${projects.length ? completedCount / projects.length * 100 : 0}%` }"><span><strong>{{ projects.length }}</strong>总项目</span></div><ul><li><i class="blue"></i>配音生成中 <b>{{ activeCount }}</b></li><li><i class="orange"></i>等待审核 <b>{{ waitingCount }}</b></li><li><i class="green"></i>已完成 <b>{{ completedCount }}</b></li><li><i class="red"></i>失败/异常 <b>{{ failedCount }}</b></li></ul></section>

        <section class="taf-card taf-owner-card"><h2>项目音色 Top 5</h2><div v-if="!voiceDistribution.length" class="taf-empty-row">暂无音色数据</div><div v-for="([name, count]) in voiceDistribution" :key="name"><span>{{ name }}</span><i><b :style="{ width: `${count / maxVoiceCount * 100}%` }"></b></i><small>{{ count }}</small></div></section>
      </aside>
    </div>
  </section>
</template>
