<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  AlertTriangle, Check, CheckCircle2, ChevronLeft, ChevronRight, CircleUserRound,
  Clock3, FileArchive, FileText, FolderOpen, ListRestart, LoaderCircle, MoreVertical,
  Play, RefreshCw, RotateCcw, Search, Settings2, SlidersHorizontal, Square, X,
} from 'lucide-vue-next'

import { listProjects } from '../api/projects'
import {
  cancelProjectTask, listTasks, startProjectWorkflow, startVideoWorkflow,
  type ProjectTaskStatus,
} from '../api/tasks'
import { confirmAction, showToast, usePageFeedback } from '../services/feedback'
import type { Project } from '../types/project'
import { formatDateTime, formatDuration } from '../utils/time'

interface TaskItem { project: Project; task: ProjectTaskStatus }
interface StageEvent { event: string; stage: string; at: string; error?: string }

const route = useRoute()
const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const query = ref('')
const status = ref(typeof route.query.status === 'string' ? route.query.status : 'all')
const type = ref('all')
const onlyAbnormal = ref(false)
const selected = ref<TaskItem | null>(null)
const error = ref('')
usePageFeedback(error, undefined, { errorTitle: '任务状态异常' })
const page = ref(1)
const pageSize = ref(10)
const acting = ref(false)
const showAllErrors = ref(false)
let refreshTimer: number | undefined

const stageLabels: Record<string, string> = {
  segmenting: '脚本准备', tts: '配音生成', audio_merge: '音频合并', subtitles: '准备视频（旧任务）',
  storyboard: '分镜生成', asset_search: '素材检索', asset_review: '自动选材',
  image_generation: '图片生成', image_review: '自动选图', scene_render: '场景渲染',
  visual_track: '视频合成', final_render: '最终合成', quality_check: '完成生成（旧任务）',
  quality_review: '完成生成（旧任务）', completed: '任务完成',
}
const statusLabels: Record<string, string> = {
  idle: '空闲', queued: '排队中', running: '运行中', paused: '已暂停',
  review_required: '旧任务待恢复', completed: '已完成', failed: '失败', cancelled: '已取消',
}
const narrationStages = ['segmenting', 'tts', 'audio_merge', 'completed']
const videoStages = ['storyboard', 'asset_search', 'asset_review', 'image_generation', 'image_review', 'scene_render', 'visual_track', 'final_render', 'completed']

const filtered = computed(() => tasks.value.filter((item) => {
  const keyword = query.value.trim().toLocaleLowerCase()
  const matchesQuery = !keyword || item.project.name.toLocaleLowerCase().includes(keyword)
    || (item.task.id || '').toLocaleLowerCase().includes(keyword)
    || (item.task.stage || '').toLocaleLowerCase().includes(keyword)
  const matchesType = type.value === 'all' || item.task.workflow === type.value
  const matchesStatus = status.value === 'all'
    || (status.value === 'review' && item.task.status === 'review_required')
    || item.task.status === status.value
  const matchesAbnormal = !onlyAbnormal.value || ['failed', 'paused', 'review_required'].includes(item.task.status)
  return matchesQuery && matchesType && matchesStatus && matchesAbnormal
}))
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)))
const pagedTasks = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
const visiblePages = computed(() => Array.from({ length: Math.min(pageCount.value, 5) }, (_, index) => index + 1))
const counts = computed(() => ({
  queued: tasks.value.filter((item) => item.task.status === 'queued').length,
  running: tasks.value.filter((item) => item.task.status === 'running').length,
  review: tasks.value.filter((item) => item.task.status === 'review_required').length,
  failed: tasks.value.filter((item) => item.task.status === 'failed').length,
  completed: tasks.value.filter((item) => item.task.status === 'completed' && isToday(item.task.finished_at)).length,
}))
const selectedStages = computed(() => selected.value?.task.workflow === 'video_synthesis' ? videoStages : narrationStages)
const selectedStageIndex = computed(() => {
  if (!selected.value) return -1
  if (selected.value.task.status === 'completed') return selectedStages.value.length - 1
  return selectedStages.value.indexOf(selected.value.task.stage || '')
})
const selectedEvents = computed(() => parseEvents(selected.value?.task.checkpoint_json).slice(-3).reverse())
const selectedErrorEvents = computed(() => parseEvents(selected.value?.task.checkpoint_json)
  .filter((event) => event.event === 'failed' || event.error)
  .reverse())

watch([query, status, type, onlyAbnormal, pageSize], () => { page.value = 1 })
watch(pageCount, (count) => { if (page.value > count) page.value = count })

function isToday(value?: string | null) {
  if (!value) return false
  const date = new Date(value)
  const today = new Date()
  return date.getFullYear() === today.getFullYear() && date.getMonth() === today.getMonth() && date.getDate() === today.getDate()
}
function parseEvents(raw?: string): StageEvent[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed.stage_history) ? parsed.stage_history : []
  } catch { return [] }
}
function taskProgress(item: TaskItem) {
  if (item.task.status === 'completed') return 100
  if (item.task.status === 'queued') return 0
  const stages = item.task.workflow === 'video_synthesis' ? videoStages : narrationStages
  const index = stages.indexOf(item.task.stage || '')
  return index < 0 ? 8 : Math.min(96, Math.round(((index + .55) / (stages.length - 1)) * 100))
}
function tone(value: string) {
  if (value === 'failed') return 'red'
  if (value === 'completed') return 'green'
  if (value === 'review_required' || value === 'paused') return 'orange'
  if (value === 'running') return 'blue'
  return 'purple'
}
function workflowLabel(item: TaskItem) { return item.task.workflow === 'video_synthesis' ? '视频渲染任务' : '配音生成任务' }
function shortId(item: TaskItem) { return (item.task.id || item.project.id).slice(0, 22) }
function eventLabel(event: StageEvent) {
  if (event.event === 'failed') return `${stageLabels[event.stage] || event.stage}失败`
  if (event.event === 'recovered' || event.event === 'resumed') return `从恢复点继续执行`
  if (event.event === 'completed' || event.event === 'stage_completed') return `${stageLabels[event.stage] || event.stage}完成`
  if (event.event === 'review_required') return '旧版任务停在审核点，可重新执行以自动继续'
  return stageLabels[event.stage] || '任务状态更新'
}
function stageState(index: number) {
  if (!selected.value) return 'waiting'
  if (selected.value.task.status === 'failed' && index === selectedStageIndex.value) return 'failed'
  if (index < selectedStageIndex.value || selected.value.task.status === 'completed') return 'done'
  if (index === selectedStageIndex.value) return selected.value.task.status === 'review_required' ? 'review' : 'active'
  return 'waiting'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [projects, runs] = await Promise.all([listProjects(), listTasks()])
    const byId = new Map(projects.map((project) => [project.id, project]))
    tasks.value = runs.flatMap((task) => {
      const project = task.project_id ? byId.get(task.project_id) : undefined
      return project ? [{ project, task }] : []
    })
    if (selected.value) {
      selected.value = tasks.value.find((item) => item.task.id === selected.value?.task.id) || null
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '任务中心加载失败'
  } finally { loading.value = false }
}
async function cancel(item: TaskItem) {
  if (!await confirmAction({ eyebrow: '取消任务', title: `取消“${item.project.name}”？`, description: '已经生成的中间产物会保留，可稍后重新执行。', confirmText: '确认取消', tone: 'warning' })) return
  acting.value = true
  try { await cancelProjectTask(item.project.id); await load(); showToast({ title: '任务已取消', tone: 'success' }) }
  catch (err) { showToast({ title: '取消失败', description: err instanceof Error ? err.message : '请稍后重试', tone: 'danger' }) }
  finally { acting.value = false }
}
async function restart(item: TaskItem) {
  acting.value = true
  try {
    if (item.task.workflow === 'video_synthesis') await startVideoWorkflow(item.project.id)
    else await startProjectWorkflow(item.project.id)
    await load()
    showToast({ title: '任务已加入队列', description: '系统将从可用检查点继续处理。', tone: 'success' })
  } catch (err) { showToast({ title: '无法重新执行', description: err instanceof Error ? err.message : '请检查项目配置', tone: 'danger' }) }
  finally { acting.value = false }
}
async function retryFailedTasks() {
  if (!selected.value) return
  const batchId = selected.value.task.batch_id
  const candidates = tasks.value.filter((item) => ['failed', 'cancelled'].includes(item.task.status)
    && (batchId ? item.task.batch_id === batchId : item.project.id === selected.value?.project.id))
  if (!candidates.length) {
    showToast({ title: '没有可重试的任务', description: '当前项目或批次中没有失败、已取消的任务。', tone: 'info' })
    return
  }
  if (!await confirmAction({ eyebrow: '批量重试', title: `重新执行 ${candidates.length} 个任务？`, description: '任务会从可用检查点重新进入本地队列。', confirmText: '开始重试', tone: 'warning' })) return
  acting.value = true
  let completed = 0
  const failures: string[] = []
  for (const item of candidates) {
    try {
      if (item.task.workflow === 'video_synthesis') await startVideoWorkflow(item.project.id)
      else await startProjectWorkflow(item.project.id)
      completed += 1
    } catch (err) {
      failures.push(`${item.project.name}: ${err instanceof Error ? err.message : '重试失败'}`)
    }
  }
  await load()
  acting.value = false
  showToast({
    title: `已提交 ${completed} 个重试任务`,
    description: failures.length ? `${failures.length} 个任务未能提交：${failures[0]}` : '系统将从可用检查点继续处理。',
    tone: failures.length ? 'warning' : 'success',
  })
}
function exportTaskReport() {
  if (!selected.value) return
  const report = {
    generated_at: new Date().toISOString(),
    project: selected.value.project,
    task: selected.value.task,
    progress_percent: taskProgress(selected.value),
    stage_history: parseEvents(selected.value.task.checkpoint_json),
  }
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `task-${selected.value.task.id || selected.value.project.id}.json`
  link.click()
  URL.revokeObjectURL(link.href)
  showToast({ title: '任务报告已导出', tone: 'success' })
}
function resetFilters() {
  query.value = ''
  status.value = 'all'
  type.value = 'all'
  onlyAbnormal.value = false
  page.value = 1
}
function selectStatus(value: string) { status.value = status.value === value ? 'all' : value }

onMounted(() => { void load(); refreshTimer = window.setInterval(load, 10000) })
onBeforeUnmount(() => { if (refreshTimer !== undefined) window.clearInterval(refreshTimer) })
</script>

<template>
  <section class="task-center-page taf-task-center" :class="{ 'detail-open': selected }">
    <header class="task-heading">
      <div><h1>任务中心</h1><p>{{ selected ? '查看任务阶段、错误记录、恢复点与关联产物' : '统一查看系统所有后台任务、异常状态与处理进度' }}</p></div>
      <div class="heading-actions">
        <button v-if="selected" class="outline-button" :disabled="acting" @click="retryFailedTasks">批量重试</button>
        <button v-if="selected" class="primary-action" @click="exportTaskReport">导出任务报告</button>
        <RouterLink v-if="!selected" class="primary-action" to="/projects">创建任务</RouterLink>
        <RouterLink v-if="!selected" class="outline-button" to="/batches/new">任务模板</RouterLink>
      </div>
    </header>

    <div class="task-metric-row">
      <button :class="{ active: status === 'queued' }" @click="selectStatus('queued')"><i class="purple"><Clock3 :size="22" /></i><span><small>排队中</small><strong>{{ counts.queued }}</strong></span></button>
      <button :class="{ active: status === 'running' }" @click="selectStatus('running')"><i class="blue"><Play :size="22" /></i><span><small>运行中</small><strong>{{ counts.running }}</strong></span></button>
      <button :class="{ active: status === 'review' }" @click="selectStatus('review')"><i class="orange"><CircleUserRound :size="22" /></i><span><small>等待审核</small><strong>{{ counts.review }}</strong></span></button>
      <button :class="{ active: status === 'failed' }" @click="selectStatus('failed')"><i class="red"><AlertTriangle :size="22" /></i><span><small>失败</small><strong>{{ counts.failed }}</strong></span></button>
      <button :class="{ active: status === 'completed' }" @click="selectStatus('completed')"><i class="green"><CheckCircle2 :size="22" /></i><span><small>今日完成</small><strong>{{ counts.completed }}</strong></span></button>
    </div>


    <div class="task-content-grid">
      <section class="task-list-card">
        <div class="task-filters">
          <label><span>任务类型</span><select v-model="type"><option value="all">全部</option><option value="narration_generation">配音生成</option><option value="video_synthesis">视频渲染</option></select></label>
          <label><span>状态</span><select v-model="status"><option value="all">全部</option><option value="queued">排队中</option><option value="running">运行中</option><option value="review">等待审核</option><option value="failed">失败</option><option value="completed">已完成</option></select></label>
          <label class="abnormal"><input v-model="onlyAbnormal" type="checkbox" />只看异常</label>
          <label class="task-search"><Search :size="16" /><input v-model="query" type="search" placeholder="搜索任务名称或 ID" /></label>
          <button class="square-button" aria-label="重置筛选" title="重置筛选" @click="resetFilters"><SlidersHorizontal :size="17" /></button>
          <button class="square-button" :disabled="loading" aria-label="刷新任务" @click="load"><RefreshCw :size="17" :class="{ spinning: loading }" /></button>
        </div>

        <div class="task-list-head"><span>任务名称</span><span>所属项目 / 批次</span><span>当前阶段</span><span>进度</span><span>开始时间</span><span>运行耗时</span><span>最近消息</span><span></span></div>
        <button v-for="item in pagedTasks" :key="item.task.id || item.project.id" class="task-list-row" :class="{ selected: selected?.task.id === item.task.id }" @click="selected = item">
          <span class="task-name"><i :class="tone(item.task.status)"><LoaderCircle v-if="item.task.status === 'running'" :size="15" /><Check v-else-if="item.task.status === 'completed'" :size="15" /><AlertTriangle v-else-if="item.task.status === 'failed'" :size="15" /><Clock3 v-else :size="15" /></i><strong>{{ item.project.name }} - {{ workflowLabel(item) }}</strong></span>
          <span>{{ item.project.name }}</span>
          <span><b class="status-chip" :class="tone(item.task.status)">{{ statusLabels[item.task.status] }}</b><small>{{ stageLabels[item.task.stage || ''] || item.task.stage || '准备中' }}</small></span>
          <span class="row-progress"><strong>{{ taskProgress(item) }}%</strong><i><b :class="tone(item.task.status)" :style="{ width: `${taskProgress(item)}%` }"></b></i></span>
          <span>{{ item.task.started_at ? formatDateTime(item.task.started_at) : '—' }}</span>
          <span>{{ formatDuration(item.task.workflow_duration_seconds || 0) }}</span>
          <span class="message">{{ item.task.error_message || (item.task.status === 'queued' ? `队列位置 ${item.task.queue_position || '—'}` : `正在处理 ${stageLabels[item.task.stage || ''] || '任务'}`) }}</span>
          <span><MoreVertical :size="17" /></span>
        </button>
        <div v-if="!pagedTasks.length" class="task-empty"><LoaderCircle v-if="loading" :size="28" class="spinning" /><ListRestart v-else :size="28" /><strong>{{ loading ? '正在同步任务…' : '没有匹配的任务' }}</strong><small>可以调整筛选条件，或从项目页面创建生产任务。</small></div>

        <footer class="task-pagination"><span>共 {{ filtered.length }} 条</span><div><button :disabled="page <= 1" @click="page--"><ChevronLeft :size="16" /></button><button v-for="value in visiblePages" :key="value" :class="{ active: page === value }" @click="page = value">{{ value }}</button><button :disabled="page >= pageCount" @click="page++"><ChevronRight :size="16" /></button></div><label><select v-model="pageSize"><option :value="10">10 条/页</option><option :value="20">20 条/页</option><option :value="50">50 条/页</option></select></label></footer>
      </section>

      <aside v-if="selected" v-click-outside="() => { selected = null }" class="task-detail-card">
        <header><div><h2>任务详情</h2><p>{{ selected.project.name }} - {{ workflowLabel(selected) }} <b class="status-chip" :class="tone(selected.task.status)">{{ statusLabels[selected.task.status] }}</b></p></div><button @click="selected = null"><X :size="19" /></button></header>

        <dl class="task-meta"><div><dt>任务 ID</dt><dd>{{ shortId(selected) }}</dd></div><div><dt>执行器</dt><dd>{{ selected.task.lease_owner || 'local-worker' }}</dd></div><div><dt>所属项目</dt><dd>{{ selected.project.name }}</dd></div><div><dt>优先级</dt><dd><b class="priority">● 普通</b></dd></div><div><dt>任务类型</dt><dd>{{ workflowLabel(selected) }}</dd></div><div><dt>预计完成</dt><dd>按当前阶段动态计算</dd></div><div><dt>创建时间</dt><dd>{{ selected.task.created_at ? formatDateTime(selected.task.created_at) : '—' }}</dd></div><div><dt>重试次数</dt><dd>{{ selected.task.attempt_count || 0 }}</dd></div></dl>

        <section class="detail-section stage-section"><h3>阶段时间线</h3><div class="stage-line"><div v-for="(stageName, index) in selectedStages" :key="stageName" :class="stageState(index)"><span><Check v-if="stageState(index) === 'done'" :size="13" /><AlertTriangle v-else-if="stageState(index) === 'failed'" :size="13" /></span><strong>{{ stageLabels[stageName] }}</strong><small>{{ index < selectedStageIndex ? '已完成' : index === selectedStageIndex ? statusLabels[selected.task.status] : '未开始' }}</small></div></div></section>

        <section class="detail-section detail-progress"><h3>运行进度</h3><p><strong>总进度　{{ taskProgress(selected) }}%</strong><small>{{ stageLabels[selected.task.stage || ''] || '准备中' }}</small></p><i><b :style="{ width: `${taskProgress(selected)}%` }"></b></i></section>

        <div class="detail-mini-grid">
          <section><header><h3>错误记录</h3><button v-if="selectedErrorEvents.length" @click="showAllErrors = !showAllErrors">{{ showAllErrors ? '收起' : '查看全部' }}</button></header><div v-if="selected.task.error_message" class="error-record"><b>ERROR</b><span>{{ selected.task.error_message }}</span></div><template v-if="showAllErrors"><div v-for="event in selectedErrorEvents" :key="`${event.at}-${event.stage}`" class="error-record"><b>{{ event.stage || 'ERROR' }}</b><span>{{ event.error || eventLabel(event) }}</span></div></template><div v-else-if="!selected.task.error_message" class="quiet-record">当前没有错误记录</div></section>
          <section><header><h3>恢复点与重试信息</h3></header><dl><div><dt>最近恢复点</dt><dd>{{ stageLabels[selected.task.stage || ''] || '任务开始' }}</dd></div><div><dt>自动重试次数</dt><dd>{{ selected.task.attempt_count || 0 }} 次</dd></div><div><dt>恢复策略</dt><dd>从最近检查点继续</dd></div></dl></section>
          <section><header><h3>关联产物</h3></header><div class="artifact-row"><RouterLink :to="`/projects/${selected.project.id}/delivery`"><FileText :size="17" />项目产物</RouterLink><RouterLink :to="`/projects/${selected.project.id}/overview`"><FolderOpen :size="17" />项目详情</RouterLink><RouterLink :to="`/projects/${selected.project.id}/render`"><FileArchive :size="17" />渲染记录</RouterLink></div></section>
        </div>

        <section class="detail-section task-log"><header><h3>任务日志</h3><RouterLink :to="`/projects/${selected.project.id}/overview`">查看完整日志</RouterLink></header><div v-if="selectedEvents.length"><p v-for="event in selectedEvents" :key="`${event.at}-${event.stage}`"><time>{{ event.at ? new Date(event.at).toLocaleTimeString('zh-CN', { hour12: false }) : '--:--:--' }}</time><b>[{{ event.event.toUpperCase() }}]</b><span>{{ eventLabel(event) }}</span></p></div><div v-else class="quiet-record">等待任务日志写入…</div></section>

        <footer><RouterLink class="detail-button" :to="`/projects/${selected.project.id}/overview`">查看项目</RouterLink><button v-if="selected.task.running || selected.task.queued" class="detail-button" :disabled="acting" @click="cancel(selected)"><Square :size="14" />取消任务</button><button v-else class="detail-button primary" :disabled="acting" @click="restart(selected)"><RotateCcw :size="15" />重新执行</button></footer>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.taf-task-center{color:#172033;min-width:0}.task-heading{align-items:center;display:flex;justify-content:space-between;margin:0 0 17px}.task-heading h1{font-size:28px;letter-spacing:-.04em;margin:0 0 3px}.task-heading p{color:#6d788d;font-size:13px;margin:0}.heading-actions{display:flex;gap:10px}.primary-action,.outline-button{align-items:center;border-radius:8px;display:inline-flex;font-size:13px;font-weight:650;justify-content:center;min-height:40px;padding:0 19px}.primary-action{background:#075bf5;color:#fff}.outline-button{background:#fff;border:1px solid #cfd9ea;color:#285078}.task-metric-row{display:grid;gap:12px;grid-template-columns:repeat(5,minmax(0,1fr));margin-bottom:14px}.task-metric-row>button{align-items:center;background:#fff;border:1px solid #e2e8f1;border-radius:12px;box-shadow:0 8px 24px rgba(40,66,110,.055);display:flex;gap:12px;min-height:88px;padding:14px;text-align:left}.task-metric-row>button.active{border-color:#8eb3ff;box-shadow:0 0 0 2px rgba(7,91,245,.08)}.task-metric-row i{align-items:center;border-radius:50%;display:flex;height:42px;justify-content:center;width:42px}.task-metric-row span{display:grid}.task-metric-row small{color:#657188;font-size:12px}.task-metric-row strong{font-size:23px}.purple{background:#eeeaff;color:#7156e8}.blue{background:#e9f1ff;color:#1464f4}.orange{background:#fff1df;color:#f09216}.red{background:#ffe9ec;color:#ef4e5b}.green{background:#e4f8f0;color:#08aa75}.task-content-grid{align-items:start;display:grid;gap:14px;grid-template-columns:minmax(0,1fr)}.detail-open .task-content-grid{grid-template-columns:minmax(580px,.95fr) minmax(540px,1.05fr)}.task-list-card,.task-detail-card{background:#fff;border:1px solid #e2e8f1;border-radius:12px;box-shadow:0 10px 28px rgba(35,58,98,.06);min-width:0;overflow:hidden}.task-filters{align-items:center;border-bottom:1px solid #e7ebf2;display:flex;gap:10px;min-height:58px;padding:9px 13px}.task-filters label{align-items:center;display:flex;font-size:11px;gap:7px;white-space:nowrap}.task-filters select,.task-pagination select{background:#fff;border:1px solid #dfe5ee;border-radius:7px;color:#47546a;height:34px;min-height:34px;padding:0 28px 0 10px}.task-filters .abnormal{padding:0 5px}.task-search{border:1px solid #dfe5ee;border-radius:7px;color:#8994a7;margin-left:auto;min-width:190px;padding:0 9px}.task-search input{border:0;box-shadow:none!important;font-size:11px;min-height:32px;padding:0;width:100%}.square-button{align-items:center;background:#fff;border:1px solid #dfe5ee;border-radius:7px;color:#526077;display:flex;height:34px;justify-content:center;width:34px}.task-list-head,.task-list-row{align-items:center;display:grid;gap:8px;grid-template-columns:minmax(170px,1.45fr) minmax(115px,1fr) 105px 92px 108px 76px minmax(130px,1fr) 20px;padding:0 13px}.task-list-head{background:#f7f9fc;color:#667287;font-size:10px;min-height:34px}.task-list-row{background:#fff;border-top:1px solid #edf0f5;color:#536078;font-size:10px;min-height:62px;text-align:left;width:100%}.task-list-row:hover,.task-list-row.selected{background:#f4f7ff}.task-list-row.selected{box-shadow:inset 2px 0 #1464f4}.task-list-row>span{min-width:0}.task-list-row strong,.task-list-row small{display:block}.task-list-row small{color:#7c8799;margin-top:4px}.task-name{align-items:center;display:flex!important;gap:8px}.task-name i{align-items:center;border-radius:6px;display:flex;flex:0 0 auto;height:25px;justify-content:center;width:25px}.task-name strong,.message{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.status-chip{border-radius:5px;display:inline-flex!important;font-size:10px;font-weight:650;padding:3px 7px;width:max-content}.status-chip.blue{background:#e9f1ff;color:#1464f4}.status-chip.orange{background:#fff1df;color:#ed8611}.status-chip.red{background:#ffe9eb;color:#ef4b59}.status-chip.green{background:#e4f8f0;color:#08a875}.status-chip.purple{background:#eeeaff;color:#6b50df}.row-progress{display:grid!important;gap:5px}.row-progress>i,.detail-progress>i{background:#e8edf4;border-radius:8px;height:5px;overflow:hidden}.row-progress>i b,.detail-progress>i b{background:#1464f4;display:block;height:100%}.row-progress>i b.green{background:#08a875}.row-progress>i b.red{background:#ef4b59}.row-progress>i b.orange{background:#ed8611}.task-empty{align-items:center;color:#768297;display:flex;flex-direction:column;gap:7px;justify-content:center;min-height:250px}.task-empty strong{color:#344057}.task-empty small{font-size:11px}.task-pagination{align-items:center;color:#657187;display:flex;font-size:10px;justify-content:space-between;min-height:52px;padding:8px 13px}.task-pagination>div{display:flex;gap:4px}.task-pagination button{align-items:center;background:#fff;border:1px solid transparent;border-radius:6px;color:#526078;display:flex;height:28px;justify-content:center;min-width:28px}.task-pagination button.active{background:#075bf5;color:#fff}.task-detail-card{padding-bottom:0}.task-detail-card>header{align-items:flex-start;border-bottom:1px solid #e7ebf2;display:flex;justify-content:space-between;padding:15px 17px}.task-detail-card>header h2{font-size:16px;margin:0 0 9px}.task-detail-card>header p{align-items:center;display:flex;font-size:13px;font-weight:650;gap:8px;margin:0}.task-detail-card>header button{background:transparent;color:#657187;padding:3px}.task-meta{display:grid;font-size:10px;grid-template-columns:repeat(4,1fr);margin:0;padding:13px 17px;row-gap:9px}.task-meta div{display:grid;gap:3px}.task-meta dt{color:#748095}.task-meta dd{color:#334158;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.priority{color:#f04e5b}.detail-section,.detail-mini-grid>section{border:1px solid #e3e8f0;border-radius:9px;margin:0 13px 9px;padding:10px}.detail-section h3,.detail-mini-grid h3{font-size:11px;margin:0}.stage-line{display:flex;margin-top:13px}.stage-line>div{align-items:center;display:flex;flex:1;flex-direction:column;position:relative;text-align:center}.stage-line>div:not(:last-child)::after{background:#dfe5ee;content:'';height:2px;left:calc(50% + 10px);position:absolute;right:calc(-50% + 10px);top:8px}.stage-line>div.done:not(:last-child)::after{background:#0aaf7a}.stage-line span{align-items:center;background:#fff;border:2px solid #d6ddea;border-radius:50%;color:#fff;display:flex;height:18px;justify-content:center;position:relative;width:18px;z-index:1}.stage-line .done span{background:#0aaf7a;border-color:#0aaf7a}.stage-line .active span{background:#1464f4;border-color:#1464f4;box-shadow:0 0 0 3px #dfebff}.stage-line .failed span{background:#ef4e5b;border-color:#ef4e5b}.stage-line .review span{background:#f09216;border-color:#f09216}.stage-line strong{font-size:9px;margin-top:6px}.stage-line small{color:#8994a6;font-size:8px;margin-top:2px}.detail-progress p{align-items:center;display:flex;font-size:10px;justify-content:space-between;margin:8px 0}.detail-progress p small{color:#677388}.detail-mini-grid{display:grid;gap:8px;grid-template-columns:1.1fr .95fr 1fr;margin:0 13px 9px}.detail-mini-grid>section{margin:0;min-width:0}.detail-mini-grid header,.task-log header{align-items:center;display:flex;justify-content:space-between}.detail-mini-grid header button,.task-log header a{background:transparent;color:#075bf5;font-size:8px}.error-record{align-items:flex-start;display:flex;font-size:8px;gap:5px;margin-top:9px}.error-record b{background:#fff0df;border-radius:4px;color:#f09216;padding:2px 4px}.error-record span{color:#5e6a7d;line-height:1.45}.quiet-record{color:#8792a4;font-size:9px;padding:10px 0}.detail-mini-grid dl{font-size:8px;margin:8px 0 0}.detail-mini-grid dl div{display:flex;justify-content:space-between;margin:5px 0}.detail-mini-grid dt{color:#7d889a}.detail-mini-grid dd{margin:0}.artifact-row{display:grid;gap:5px;margin-top:8px}.artifact-row a{align-items:center;background:#f7f9fc;border-radius:5px;color:#536076;display:flex;font-size:8px;gap:5px;padding:5px}.task-log{min-height:102px}.task-log p{align-items:center;display:grid;font-family:Consolas,monospace;font-size:8px;gap:7px;grid-template-columns:48px 52px 1fr;margin:5px 0}.task-log time{color:#647187}.task-log b{color:#1464f4}.task-detail-card>footer{align-items:center;border-top:1px solid #e3e8f0;display:flex;gap:8px;justify-content:flex-end;padding:9px 13px}.detail-button{align-items:center;background:#fff;border:1px solid #dbe2ec;border-radius:6px;color:#47556b;display:inline-flex;font-size:10px;gap:5px;justify-content:center;min-height:31px;padding:0 13px}.detail-button.primary{background:#075bf5;border-color:#075bf5;color:#fff}.spinning{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:1450px){.detail-open .task-content-grid{grid-template-columns:minmax(500px,.85fr) minmax(510px,1.15fr)}.task-list-head,.task-list-row{grid-template-columns:minmax(160px,1.5fr) 92px 83px 80px 92px minmax(100px,1fr) 18px}.task-list-head>:nth-child(2),.task-list-row>:nth-child(2){display:none}.task-meta{grid-template-columns:repeat(2,1fr)}}
@media(max-width:1150px){.detail-open .task-content-grid{grid-template-columns:1fr}.task-metric-row{grid-template-columns:repeat(3,1fr)}.detail-mini-grid{grid-template-columns:1fr 1fr}.detail-mini-grid>section:last-child{grid-column:1/-1}.task-list-head,.task-list-row{grid-template-columns:minmax(180px,1.5fr) 110px 92px 105px minmax(120px,1fr) 18px}.task-list-head>:nth-child(6),.task-list-row>:nth-child(6){display:none}}
@media(max-width:680px){.task-heading{align-items:flex-start;gap:12px}.heading-actions{flex-wrap:wrap;justify-content:flex-end}.task-metric-row{grid-template-columns:1fr 1fr}.task-filters{flex-wrap:wrap}.task-search{margin-left:0;width:100%}.task-list-card{overflow-x:auto}.task-list-head,.task-list-row{min-width:650px}.task-detail-card{overflow:visible}.task-meta{grid-template-columns:1fr 1fr}.stage-line{overflow-x:auto}.stage-line>div{flex:0 0 90px}.detail-mini-grid{grid-template-columns:1fr}.detail-mini-grid>section:last-child{grid-column:auto}}
</style>
