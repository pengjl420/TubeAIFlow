<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CheckCircle2, ChevronLeft, ChevronRight, Clock3, Film, Folder, Layers3, Loader2, Play, RefreshCw, Search, XCircle } from 'lucide-vue-next'

import {
  createLocalVideoMergeTask,
  listLocalVideoMergeTasks,
  type LocalVideoMergeTask,
} from '../api/localVideoMerge'
import { selectDirectory } from '../api/settings'
import { showToast, usePageFeedback } from '../services/feedback'

const mediaDir = ref('')
const outputDir = ref('')
const outputFilename = ref('local_merge.mp4')
const durationMinutes = ref(1)
const durationSeconds = ref(0)
const selectingFolder = ref<'media' | 'output' | null>(null)
const submitting = ref(false)
const loadingTasks = ref(false)
const error = ref('')
const tasks = ref<LocalVideoMergeTask[]>([])
const taskSearch = ref('')
const statusFilter = ref<'all' | LocalVideoMergeTask['status']>('all')
const taskPage = ref(1)
const pageSize = ref(10)
const lastUpdatedAt = ref<Date | null>(null)
const PREFERENCES_KEY = 'tubeaiflow-local-video-merge-preferences'
let pollTimer: number | undefined
usePageFeedback(error, undefined, { errorTitle: '本地视频拼接失败' })

const targetDuration = computed(() => Number(durationMinutes.value) * 60 + Number(durationSeconds.value))
const durationValid = computed(() =>
  Number.isInteger(Number(durationMinutes.value))
  && Number.isInteger(Number(durationSeconds.value))
  && Number(durationMinutes.value) >= 0
  && Number(durationMinutes.value) <= 1440
  && Number(durationSeconds.value) >= 0
  && Number(durationSeconds.value) <= 59
  && targetDuration.value > 0
  && targetDuration.value <= 86400,
)
const ready = computed(() =>
  Boolean(mediaDir.value.trim() && outputDir.value.trim() && outputFilename.value.trim())
  && durationValid.value,
)
const activeCount = computed(() => tasks.value.filter(task => task.status === 'queued' || task.status === 'running').length)
const filteredTasks = computed(() => {
  const query = taskSearch.value.trim().toLocaleLowerCase()
  const priority: Record<LocalVideoMergeTask['status'], number> = { running: 0, queued: 1, failed: 2, completed: 3 }
  return tasks.value
    .filter(task => statusFilter.value === 'all' || task.status === statusFilter.value)
    .filter(task => !query || [task.output_filename, task.media_dir, task.output_dir, task.error_message || '']
      .some(value => value.toLocaleLowerCase().includes(query)))
    .slice()
    .sort((a, b) => priority[a.status] - priority[b.status]
      || new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
})
const totalPages = computed(() => Math.max(1, Math.ceil(filteredTasks.value.length / pageSize.value)))
const pagedTasks = computed(() => filteredTasks.value.slice((taskPage.value - 1) * pageSize.value, taskPage.value * pageSize.value))
const taskRange = computed(() => {
  if (!filteredTasks.value.length) return '0 条'
  const start = (taskPage.value - 1) * pageSize.value + 1
  return `${start}–${Math.min(start + pageSize.value - 1, filteredTasks.value.length)} / ${filteredTasks.value.length} 条`
})

function loadPreferences() {
  try {
    const stored = JSON.parse(localStorage.getItem(PREFERENCES_KEY) || '{}')
    if (typeof stored.mediaDir === 'string') mediaDir.value = stored.mediaDir
    if (typeof stored.outputDir === 'string') outputDir.value = stored.outputDir
    if (typeof stored.outputFilename === 'string' && stored.outputFilename.trim()) outputFilename.value = stored.outputFilename
    if (Number.isInteger(stored.durationMinutes) && stored.durationMinutes >= 0) durationMinutes.value = stored.durationMinutes
    if (Number.isInteger(stored.durationSeconds) && stored.durationSeconds >= 0) durationSeconds.value = stored.durationSeconds
  } catch {
    localStorage.removeItem(PREFERENCES_KEY)
  }
}

function savePreferences() {
  localStorage.setItem(PREFERENCES_KEY, JSON.stringify({
    mediaDir: mediaDir.value,
    outputDir: outputDir.value,
    outputFilename: outputFilename.value,
    durationMinutes: durationMinutes.value,
    durationSeconds: durationSeconds.value,
  }))
}

async function chooseFolder(target: 'media' | 'output') {
  selectingFolder.value = target
  error.value = ''
  try {
    const selected = await selectDirectory(
      target === 'media' ? mediaDir.value : outputDir.value,
      target === 'media' ? '选择本地视频素材目录' : '选择合并视频输出目录',
    )
    if (selected && target === 'media') mediaDir.value = selected
    if (selected && target === 'output') outputDir.value = selected
  } catch (err) {
    error.value = err instanceof Error ? err.message : '文件夹选择失败'
  } finally {
    selectingFolder.value = null
  }
}

async function loadTasks(silent = false) {
  if (!silent) loadingTasks.value = true
  try {
    tasks.value = await listLocalVideoMergeTasks(500)
    lastUpdatedAt.value = new Date()
  } catch (err) {
    if (!silent) error.value = err instanceof Error ? err.message : '任务列表加载失败'
  } finally {
    loadingTasks.value = false
  }
}

async function submitTask() {
  if (!ready.value) {
    error.value = durationValid.value ? '请完整填写文件名和两个目录' : '请填写有效的目标时长'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    const task = await createLocalVideoMergeTask({
      media_dir: mediaDir.value.trim(),
      output_dir: outputDir.value.trim(),
      output_filename: outputFilename.value.trim(),
      target_duration: targetDuration.value,
    })
    tasks.value = [task, ...tasks.value.filter(item => item.id !== task.id)]
    showToast({
      title: '拼接任务已提交',
      description: task.queue_position ? `当前队列位置：${task.queue_position}` : '任务即将开始',
      tone: 'success',
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '任务提交失败'
  } finally {
    submitting.value = false
  }
}

function taskStatus(task: LocalVideoMergeTask) {
  if (task.status === 'running') return '正在拼接'
  if (task.status === 'queued') return task.queue_position ? `排队第 ${task.queue_position} 位` : '排队中'
  if (task.status === 'completed') return '已完成'
  return '失败'
}

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : '—'
}

function handleVisibilityChange() {
  if (!document.hidden) void loadTasks(true)
}

watch([mediaDir, outputDir, outputFilename, durationMinutes, durationSeconds], savePreferences)
watch([taskSearch, statusFilter, pageSize], () => { taskPage.value = 1 })
watch(totalPages, value => { if (taskPage.value > value) taskPage.value = value })
onMounted(async () => {
  loadPreferences()
  await loadTasks()
  pollTimer = window.setInterval(() => { if (!document.hidden && activeCount.value > 0) void loadTasks(true) }, 2500)
  document.addEventListener('visibilitychange', handleVisibilityChange)
})
onBeforeUnmount(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<template>
  <section class="local-merge-page">
    <header class="taf-page-heading">
      <div>
        <h1>本地素材拼接</h1>
        <p>提交多个拼接任务后，系统按提交顺序逐个处理；关闭页面不会中断队列。</p>
      </div>
      <span class="local-tool-badge"><Film :size="17" /> 队列模式</span>
    </header>

    <div class="local-merge-layout">
      <article class="local-merge-card">
        <header>
          <span class="card-icon"><Layers3 :size="20" /></span>
          <div><h2>新建拼接任务</h2><p>每次提交都会加入持久任务队列。</p></div>
        </header>

        <div class="local-merge-form">
          <label class="merge-field wide">
            <span>素材目录 <b>*</b></span>
            <div class="merge-path-input">
              <input v-model="mediaDir" readonly aria-label="素材目录" placeholder="请选择包含视频素材的文件夹" />
              <button type="button" :disabled="selectingFolder !== null" @click="chooseFolder('media')"><Folder :size="17" /> 选择</button>
            </div>
            <small>递归读取 MP4、MOV、AVI、M4V、MPG、MPEG 文件。</small>
          </label>

          <label class="merge-field">
            <span>目标时长 <b>*</b></span>
            <div class="duration-input">
              <Clock3 :size="17" />
              <label><input v-model.number="durationMinutes" type="number" min="0" max="1440" aria-label="目标时长分钟" /><em>分</em></label>
              <i></i>
              <label><input v-model.number="durationSeconds" type="number" min="0" max="59" aria-label="目标时长秒数" /><em>秒</em></label>
            </div>
          </label>

          <label class="merge-field">
            <span>输出文件名 <b>*</b></span>
            <input v-model="outputFilename" maxlength="200" aria-label="输出文件名" placeholder="例如：精选素材.mp4" />
          </label>

          <label class="merge-field wide">
            <span>输出目录 <b>*</b></span>
            <div class="merge-path-input">
              <input v-model="outputDir" readonly aria-label="输出目录" placeholder="请选择成片保存文件夹" />
              <button type="button" :disabled="selectingFolder !== null" @click="chooseFolder('output')"><Folder :size="17" /> 选择</button>
            </div>
          </label>
        </div>

        <button class="merge-submit" type="button" :disabled="!ready || submitting || selectingFolder !== null" @click="submitTask">
          <Loader2 v-if="submitting" class="spin" :size="18" />
          <Play v-else :size="18" />
          {{ submitting ? '正在提交…' : '加入拼接队列' }}
        </button>
      </article>

      <aside class="local-merge-card queue-summary">
        <header><span class="card-icon purple"><Clock3 :size="20" /></span><div><h2>队列说明</h2><p>当前待处理 {{ activeCount }} 个任务</p></div></header>
        <ol>
          <li>任务严格按提交顺序执行，同一时间只运行一个拼接任务。</li>
          <li>任务与结果持久保存在本地数据库，后端重启后会自动重新排队。</li>
          <li>任务失败不会阻塞后续任务，可在列表中查看具体原因。</li>
          <li>每个任务仍会生成 MP4 和对应的 manifest.json。</li>
        </ol>
      </aside>
    </div>

    <article class="local-merge-card task-card">
      <header>
        <span class="card-icon purple"><Film :size="20" /></span>
        <div><h2>拼接任务</h2><p>{{ activeCount ? '任务运行期间自动刷新' : '当前没有运行中的任务' }}<span v-if="lastUpdatedAt"> · {{ lastUpdatedAt.toLocaleTimeString() }} 更新</span></p></div>
        <button class="refresh-button" type="button" :disabled="loadingTasks" aria-label="刷新拼接任务" @click="loadTasks()"><RefreshCw :class="{ spin: loadingTasks }" :size="15" />{{ loadingTasks ? '刷新中…' : '刷新' }}</button>
      </header>
      <div v-if="tasks.length" class="task-toolbar">
        <label class="task-search"><Search :size="16" /><input v-model="taskSearch" type="search" aria-label="搜索拼接任务" placeholder="搜索文件名、目录或错误…" /></label>
        <label><span class="sr-only">任务状态</span><select v-model="statusFilter" aria-label="任务状态筛选"><option value="all">全部状态</option><option value="running">正在运行</option><option value="queued">排队中</option><option value="failed">失败</option><option value="completed">已完成</option></select></label>
        <span class="task-count">{{ filteredTasks.length }} 个匹配任务</span>
      </div>
      <div v-if="!tasks.length" class="empty">尚未提交拼接任务。</div>
      <div v-else-if="!pagedTasks.length" class="empty"><strong>没有匹配的任务</strong><button type="button" @click="taskSearch = ''; statusFilter = 'all'">清除筛选</button></div>
      <div v-else class="task-list">
        <div v-for="task in pagedTasks" :key="task.id" class="task-row">
          <span class="status-icon" :class="task.status">
            <Loader2 v-if="task.status === 'running'" class="spin" :size="18" />
            <Clock3 v-else-if="task.status === 'queued'" :size="18" />
            <CheckCircle2 v-else-if="task.status === 'completed'" :size="18" />
            <XCircle v-else :size="18" />
          </span>
          <div class="task-main">
            <strong>{{ task.output_filename }}</strong>
            <span>{{ task.media_dir }}</span>
            <span v-if="task.result">{{ task.result.output_path }}</span>
            <span v-if="task.error_message" class="task-error">{{ task.error_message }}</span>
          </div>
          <div class="task-meta">
            <b :class="task.status">{{ taskStatus(task) }}</b>
            <span>目标 {{ task.target_duration }} 秒</span>
            <span>{{ formatTime(task.created_at) }}</span>
          </div>
        </div>
      </div>
      <footer v-if="filteredTasks.length" class="task-pagination">
        <span>{{ taskRange }}</span>
        <label>每页 <select v-model="pageSize" aria-label="每页任务数"><option :value="10">10</option><option :value="20">20</option><option :value="50">50</option></select></label>
        <button type="button" :disabled="taskPage <= 1" aria-label="上一页" @click="taskPage--"><ChevronLeft :size="16" /></button>
        <strong>{{ taskPage }} / {{ totalPages }}</strong>
        <button type="button" :disabled="taskPage >= totalPages" aria-label="下一页" @click="taskPage++"><ChevronRight :size="16" /></button>
      </footer>
    </article>
  </section>
</template>

<style scoped>
.local-merge-page{color:#172033}.local-tool-badge{align-items:center;background:#eaf2ff;border:1px solid #cfe0ff;border-radius:999px;color:#075bf5;display:flex;font-size:12px;font-weight:750;gap:7px;padding:8px 13px}.local-merge-layout{align-items:start;display:grid;gap:16px;grid-template-columns:minmax(560px,1.45fr) minmax(300px,.65fr)}.local-merge-card{background:#fff;border:1px solid #e1e7ef;border-radius:13px;box-shadow:0 5px 22px #34435f0a;padding:20px}.local-merge-card>header{align-items:center;border-bottom:1px solid #edf0f4;display:flex;gap:11px;margin:-2px 0 20px;padding-bottom:15px}.local-merge-card h2{font-size:17px;margin:0}.local-merge-card header p{color:#7b8799;font-size:12px;margin:4px 0 0}.card-icon{align-items:center;background:#eaf2ff;border-radius:9px;color:#0864eb;display:flex;height:38px;justify-content:center;width:38px}.card-icon.purple{background:#f1ecff;color:#7654d7}.local-merge-form{display:grid;gap:17px;grid-template-columns:1fr 1fr}.merge-field{display:grid;gap:8px}.merge-field.wide{grid-column:1/-1}.merge-field>span{font-size:13px;font-weight:750}.merge-field b{color:#e13e49}.merge-field>input,.merge-path-input input,.duration-input{background:#fff;border:1px solid #dce3ec;border-radius:8px;box-sizing:border-box;min-height:43px;outline:none;padding:10px 12px;width:100%}.merge-field input:focus,.duration-input:focus-within{border-color:#0864eb;box-shadow:0 0 0 3px #0864eb12}.merge-field small{color:#8792a3;font-size:11px}.merge-path-input{display:flex}.merge-path-input input{border-radius:8px 0 0 8px}.merge-path-input button{align-items:center;background:#f7f9fc;border:1px solid #dce3ec;border-left:0;border-radius:0 8px 8px 0;color:#46556b;display:flex;font-weight:700;gap:6px;padding:0 14px}.duration-input{align-items:center;color:#758196;display:flex;gap:9px;padding:0 12px}.duration-input>label{align-items:center;display:flex;flex:1;gap:6px}.duration-input input{border:0;min-width:0;outline:0;padding:10px 0;text-align:right;width:100%}.duration-input em{font-size:12px;font-style:normal}.duration-input>i{background:#dce3ec;height:22px;width:1px}.merge-submit{align-items:center;background:#0864eb;border:0;border-radius:9px;color:#fff;display:flex;font-size:13px;font-weight:750;gap:8px;justify-content:center;margin-top:22px;min-height:46px;width:100%}.merge-submit:disabled{cursor:not-allowed;opacity:.55}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.queue-summary ol{color:#59687c;display:grid;font-size:12px;gap:14px;line-height:1.6;margin:0;padding-left:20px}.task-card{margin-top:16px}.task-card>header .refresh-button{align-items:center;background:#f7f9fc;border:1px solid #dce3ec;border-radius:7px;color:#46556b;display:flex;gap:6px;margin-left:auto;padding:7px 13px}.task-toolbar{align-items:center;display:flex;gap:9px;margin-bottom:12px}.task-search{align-items:center;border:1px solid #dce3ec;border-radius:8px;color:#8290a3;display:flex;min-height:38px;padding:0 10px;width:min(360px,45%)}.task-search input{border:0;min-width:0;outline:0;padding:0 8px;width:100%}.task-toolbar select,.task-pagination select{background:#fff;border:1px solid #dce3ec;border-radius:7px;min-height:38px;padding:0 30px 0 10px}.task-count{color:#7a8699;font-size:11px;margin-left:auto}.empty{color:#8792a3;font-size:12px;padding:25px;text-align:center}.empty strong{display:block;margin-bottom:8px}.empty button{background:none;color:#075bf5}.task-list{display:grid;gap:9px}.task-row{align-items:center;border:1px solid #e8edf3;border-radius:9px;display:grid;gap:12px;grid-template-columns:auto minmax(0,1fr) auto;padding:12px}.status-icon{align-items:center;background:#f3f0ff;border-radius:50%;color:#7654d7;display:flex;height:36px;justify-content:center;width:36px}.status-icon.running{background:#eaf2ff;color:#0864eb}.status-icon.completed{background:#e6f8f1;color:#079e6b}.status-icon.failed{background:#fff0f1;color:#d63b49}.task-main{display:grid;gap:3px;min-width:0}.task-main strong{font-size:13px}.task-main span{color:#7f8a9b;font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.task-main .task-error{color:#d63b49}.task-meta{display:grid;gap:4px;text-align:right}.task-meta b{color:#7654d7;font-size:12px}.task-meta b.running{color:#0864eb}.task-meta b.completed{color:#079e6b}.task-meta b.failed{color:#d63b49}.task-meta span{color:#7f8a9b;font-size:11px}.task-pagination{align-items:center;border-top:1px solid #edf0f4;display:flex;gap:9px;margin-top:14px;padding-top:12px}.task-pagination>span{color:#718096;font-size:12px;margin-right:auto}.task-pagination label{align-items:center;color:#718096;display:flex;font-size:11px;gap:6px}.task-pagination select{min-height:32px;padding-right:24px}.task-pagination button{align-items:center;background:#fff;border:1px solid #dce3ec;border-radius:6px;color:#536078;display:flex;height:34px;justify-content:center;min-height:34px;width:34px}.task-pagination strong{font-size:11px}.sr-only{clip:rect(0,0,0,0);clip-path:inset(50%);height:1px;overflow:hidden;position:absolute;white-space:nowrap;width:1px}@media(max-width:1000px){.local-merge-layout{grid-template-columns:1fr}}@media(max-width:650px){.local-merge-form{grid-template-columns:1fr}.merge-field.wide{grid-column:auto}.task-toolbar{align-items:stretch;display:grid;grid-template-columns:1fr 140px}.task-search{width:100%}.task-count{grid-column:1/-1;margin:0}.task-row{grid-template-columns:auto 1fr}.task-meta{grid-column:2;text-align:left}.task-pagination{flex-wrap:wrap}.task-pagination>span{flex-basis:100%}}
</style>
