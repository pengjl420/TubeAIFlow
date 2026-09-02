<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { AudioLines, CheckCircle2, ChevronLeft, ChevronRight, Clock3, Copy, Download, Loader2, Pause, Play, RefreshCw, RotateCcw, Search, Trash2, XCircle } from 'lucide-vue-next'
import { listVoices, type VoiceProfile } from '../api/voices'
import { voiceTagText } from '../utils/tts'
import {
  createVoiceGenerationTask,
  deleteVoiceGenerationTask,
  listVoiceGenerationTasks,
  pauseVoiceGenerationTask,
  resumeVoiceGenerationTask,
  voiceGenerationAudioUrl,
  voiceGenerationSegmentAudioUrl,
  type VoiceGenerationTask,
} from '../api/voiceGeneration'
import { confirmAction, showToast, usePageFeedback } from '../services/feedback'

const voices = ref<VoiceProfile[]>([])
const tasks = ref<VoiceGenerationTask[]>([])
const voiceProfileId = ref('')
const text = ref('')
const outputFilename = ref('配音.wav')
const submitting = ref(false)
const loading = ref(false)
const operatingTaskId = ref('')
const taskSearch = ref('')
const statusFilter = ref('all')
const taskPage = ref(1)
const pageSize = ref(10)
const segmentPages = ref<Record<string, number>>({})
const segmentPageSize = 5
const lastUpdatedAt = ref<Date | null>(null)
const error = ref('')
let pollTimer: number | undefined
usePageFeedback(error, undefined, { errorTitle: '配音生成失败' })

const transcriptLines = computed(() => text.value.split(/\r\n|\n|\r/).map(line => line.trim()).filter(Boolean))
const ready = computed(() => Boolean(voiceProfileId.value && transcriptLines.value.length && outputFilename.value.trim()))
const activeCount = computed(() => tasks.value.filter(task => ['queued', 'running'].includes(task.status)).length)
const filteredTasks = computed(() => {
  const query = taskSearch.value.trim().toLocaleLowerCase()
  const priority: Record<string, number> = { running: 0, queued: 1, paused: 2, failed: 3, completed: 4 }
  return tasks.value.filter(task => statusFilter.value === 'all' || task.status === statusFilter.value)
    .filter(task => !query || [task.output_filename, task.voice_profile_name, task.text].some(value => value.toLocaleLowerCase().includes(query)))
    .slice().sort((a, b) => (priority[a.status] ?? 9) - (priority[b.status] ?? 9) || new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
})
const totalPages = computed(() => Math.max(1, Math.ceil(filteredTasks.value.length / pageSize.value)))
const pagedTasks = computed(() => filteredTasks.value.slice((taskPage.value - 1) * pageSize.value, taskPage.value * pageSize.value))

function taskSegments(task: VoiceGenerationTask) {
  return task.segments || []
}

function segmentTotalPages(task: VoiceGenerationTask) {
  return Math.max(1, Math.ceil(taskSegments(task).length / segmentPageSize))
}

function segmentPage(task: VoiceGenerationTask) {
  return Math.min(segmentPages.value[task.id] || 1, segmentTotalPages(task))
}

function pagedTaskSegments(task: VoiceGenerationTask) {
  const start = (segmentPage(task) - 1) * segmentPageSize
  return taskSegments(task).slice(start, start + segmentPageSize)
}

function setSegmentPage(task: VoiceGenerationTask, page: number) {
  segmentPages.value[task.id] = Math.min(Math.max(1, page), segmentTotalPages(task))
}

async function copyError(message: string) {
  let copied = false
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(message)
      copied = true
    }
  } catch {
    // Fall back to the local selection API when clipboard permission is unavailable.
  }
  if (!copied) {
    const textarea = document.createElement('textarea')
    try {
      textarea.value = message
      textarea.setAttribute('readonly', '')
      textarea.style.position = 'fixed'
      textarea.style.opacity = '0'
      document.body.appendChild(textarea)
      textarea.select()
      copied = document.execCommand('copy')
    } catch {
      copied = false
    } finally {
      textarea.remove()
    }
  }
  showToast(copied
    ? { title: '错误内容已复制', description: '可以粘贴到日志、工单或其他位置。', tone: 'success' }
    : { title: '复制失败', description: '浏览器未允许访问剪贴板，请重试。', tone: 'danger', duration: 4000 })
}

function taskSegmentCount(task: VoiceGenerationTask) {
  return task.segment_count || task.text.split(/\r\n|\n|\r/).filter(line => line.trim()).length
}

async function loadPage(silent = false) {
  if (!silent) loading.value = true
  try {
    const [voiceItems, taskItems] = await Promise.all([listVoices(), listVoiceGenerationTasks()])
    voices.value = voiceItems
    tasks.value = taskItems
    lastUpdatedAt.value = new Date()
    if (!voiceProfileId.value && voiceItems.length) voiceProfileId.value = voiceItems[0].id
  } catch (err) {
    if (!silent) error.value = err instanceof Error ? err.message : '页面数据加载失败'
  } finally {
    loading.value = false
  }
}

async function submitTask() {
  if (!ready.value) {
    error.value = '请选择参考音色，并填写逐字稿和输出音频文件名'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    const task = await createVoiceGenerationTask({
      voice_profile_id: voiceProfileId.value,
      text: text.value,
      output_filename: outputFilename.value.trim(),
    })
    tasks.value = [task, ...tasks.value.filter(item => item.id !== task.id)]
    showToast({
      title: `已提交 ${taskSegmentCount(task)} 个分段`,
      description: '系统将逐条生成并自动合并完整音频',
      tone: 'success',
    })
    text.value = ''
  } catch (err) {
    error.value = err instanceof Error ? err.message : '配音任务提交失败'
  } finally {
    submitting.value = false
  }
}

function statusText(task: VoiceGenerationTask) {
  if (task.status === 'running') return '逐段生成中'
  if (task.status === 'queued') return task.queue_position ? `排队第 ${task.queue_position} 位` : '排队中'
  if (task.status === 'paused') return '已暂停'
  return task.status === 'completed' ? '生成完成' : '生成失败'
}

function replaceTask(task: VoiceGenerationTask) {
  tasks.value = tasks.value.map(item => item.id === task.id ? task : item)
}

async function pauseTask(task: VoiceGenerationTask) {
  operatingTaskId.value = task.id
  try {
    replaceTask(await pauseVoiceGenerationTask(task.id))
    showToast({ title: '任务已暂停', description: '恢复后会重新加入队列。', tone: 'success' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '暂停任务失败'
  } finally {
    operatingTaskId.value = ''
  }
}

async function resumeTask(task: VoiceGenerationTask) {
  operatingTaskId.value = task.id
  try {
    replaceTask(await resumeVoiceGenerationTask(task.id))
    showToast({ title: '任务已恢复', description: '任务已重新加入生成队列。', tone: 'success' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '恢复任务失败'
  } finally {
    operatingTaskId.value = ''
  }
}

async function deleteTask(task: VoiceGenerationTask) {
  const confirmed = await confirmAction({
    title: '删除配音任务',
    description: `确定删除“${task.output_filename}”吗？`,
    detail: task.output_path ? '任务记录和生成文件将移入系统回收站。' : '该任务记录将被永久删除。',
    confirmText: '删除任务',
    tone: 'danger',
  })
  if (!confirmed) return
  operatingTaskId.value = task.id
  try {
    await deleteVoiceGenerationTask(task.id)
    tasks.value = tasks.value.filter(item => item.id !== task.id)
    showToast({ title: '任务已删除', description: '生成文件（如有）已移入系统回收站。', tone: 'success' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '删除任务失败'
  } finally {
    operatingTaskId.value = ''
  }
}

const formatDate = (value: string | null) => value ? new Date(value).toLocaleString() : '—'
function formatDuration(value: number | null | undefined) {
  if (value === null || value === undefined) return '—'
  const seconds = Number(value)
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  const rounded = Math.round(seconds)
  const hours = Math.floor(rounded / 3600)
  const minutes = Math.floor((rounded % 3600) / 60)
  const remainingSeconds = rounded % 60
  const clock = `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`
  return hours ? `${String(hours).padStart(2, '0')}:${clock}` : clock
}

watch([taskSearch, statusFilter, pageSize], () => { taskPage.value = 1 })
watch(totalPages, value => { if (taskPage.value > value) taskPage.value = value })

onMounted(async () => {
  await loadPage()
  pollTimer = window.setInterval(() => { if (!document.hidden && activeCount.value > 0) void loadPage(true) }, 2500)
})
onBeforeUnmount(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
})
</script>

<template>
  <section class="voice-page">
    <header class="taf-page-heading">
      <div><h1>配音生成</h1><p>逐字稿仅按换行符自动切段；每行生成一条音频，最后自动合并完整音频。</p></div>
      <span class="queue-badge"><Clock3 :size="17" /> 生成队列 {{ activeCount }}</span>
    </header>

    <div class="page-layout">
      <article class="panel">
        <header><span class="panel-icon"><AudioLines :size="21" /></span><div><h2>生成配音</h2><p>点击按钮时自动切段，无需提前执行切段操作。</p></div></header>
        <div class="form-grid">
          <label class="field">
            <span>参考音色 <b>*</b></span>
            <select v-model="voiceProfileId">
              <option value="" disabled>请选择参考音色</option>
              <option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.name }} · {{ voiceTagText(voice.tts_engine, voice.language) }}</option>
            </select>
            <small v-if="!voices.length">暂无音色，请先前往“音色中心”添加。</small>
          </label>
          <label class="field">
            <span>输出音频文件名 <b>*</b></span>
            <input v-model="outputFilename" maxlength="200" aria-label="输出音频文件名" placeholder="例如：人物开场白.wav" />
            <small>完整音频保留该名称；分段命名为“人物开场白_0001.wav”。</small>
          </label>
          <label class="field wide">
            <span>逐字稿文本 <b>*</b><em>{{ text.length }} / 50000 · {{ transcriptLines.length }} 段</em></span>
            <textarea v-model="text" maxlength="50000" rows="12" aria-label="逐字稿文本" placeholder="每行输入一个需要单独生成的配音段落……" />
            <small>仅以换行符作为分段边界；空行会被忽略，不按标点或字数二次切分。</small>
          </label>
        </div>
        <div v-if="transcriptLines.length" class="segment-preview">
          <strong>切段预览</strong>
          <ol><li v-for="(line, index) in transcriptLines.slice(0, 6)" :key="index"><b>{{ String(index + 1).padStart(4, '0') }}</b><span>{{ line }}</span></li></ol>
          <small v-if="transcriptLines.length > 6">另有 {{ transcriptLines.length - 6 }} 段将在提交时一并生成</small>
        </div>
        <button class="submit-button" type="button" :disabled="!ready || submitting" @click="submitTask">
          <Loader2 v-if="submitting" class="spin" :size="18" /><Play v-else :size="18" />
          {{ submitting ? '正在提交…' : `生成配音（${transcriptLines.length} 段）` }}
        </button>
      </article>

      <aside class="panel flow-info">
        <header><span class="panel-icon purple"><Clock3 :size="21" /></span><div><h2>当前工作流程</h2><p>所有音色引擎遵循同一流程。</p></div></header>
        <ol>
          <li><b>换行切段</b><span>过滤空行，保留每行文本内容和顺序。</span></li>
          <li><b>逐段生成</b><span>所选 TTS 服务依次输出独立 WAV。</span></li>
          <li><b>自动合并</b><span>全部分段成功后，按原顺序合并完整 WAV。</span></li>
          <li><b>同时保留</b><span>任务结果可试听、下载完整音频和每个分段。</span></li>
        </ol>
      </aside>
    </div>

    <article class="panel task-panel">
      <header>
        <span class="panel-icon purple"><AudioLines :size="21" /></span><div><h2>生成记录</h2><p>{{ activeCount ? '任务运行期间自动刷新' : '当前没有运行中的任务' }}<span v-if="lastUpdatedAt"> · {{ lastUpdatedAt.toLocaleTimeString() }} 更新</span></p></div>
        <button class="refresh" type="button" :disabled="loading" @click="loadPage()"><RefreshCw :class="{ spin: loading }" :size="15" />{{ loading ? '刷新中' : '刷新' }}</button>
      </header>
      <div v-if="tasks.length" class="task-toolbar">
        <label><Search :size="16" /><input v-model="taskSearch" type="search" aria-label="搜索配音任务" placeholder="搜索文件、音色或文本…" /></label>
        <select v-model="statusFilter" aria-label="配音任务状态筛选"><option value="all">全部状态</option><option value="running">正在生成</option><option value="queued">排队中</option><option value="paused">已暂停</option><option value="failed">失败</option><option value="completed">已完成</option></select>
        <span>{{ filteredTasks.length }} 个匹配任务</span>
      </div>
      <div v-if="!tasks.length" class="empty">尚未生成配音。</div>
      <div v-else-if="!pagedTasks.length" class="empty">没有匹配的配音任务。</div>
      <div v-else class="task-list">
        <div v-for="task in pagedTasks" :key="task.id" class="task-row">
          <span class="status-icon" :class="task.status">
            <Loader2 v-if="task.status === 'running'" class="spin" :size="19" /><Clock3 v-else-if="task.status === 'queued'" :size="19" /><Pause v-else-if="task.status === 'paused'" :size="19" /><CheckCircle2 v-else-if="task.status === 'completed'" :size="19" /><XCircle v-else :size="19" />
          </span>
          <div class="task-main">
            <div><strong>{{ task.output_filename }}</strong><span>{{ task.voice_profile_name }}</span><span>{{ voiceTagText(task.tts_engine, task.language) }}</span><span>{{ taskSegmentCount(task) }} 段</span></div>
            <p>{{ task.text }}</p>
            <div v-if="task.error_message" class="task-error-wrap" tabindex="0" :aria-describedby="`task-error-${task.id}`">
              <span class="task-error-preview">{{ task.error_message }}</span>
              <div :id="`task-error-${task.id}`" class="task-error-tooltip" role="tooltip">
                <p>{{ task.error_message }}</p>
                <button type="button" aria-label="复制完整错误内容" @click.stop="copyError(task.error_message)"><Copy :size="13" />复制错误</button>
              </div>
            </div>
            <div v-if="task.audio_url" class="full-audio"><b>完整音频</b><audio controls preload="metadata" :src="voiceGenerationAudioUrl(task)" /><a :href="voiceGenerationAudioUrl(task, true)"><Download :size="14" /> 下载</a></div>
            <details v-if="taskSegments(task).length" class="segment-results">
              <summary><span>分段音频</span><b>{{ taskSegments(task).length }} 段</b></summary>
              <div v-for="segment in pagedTaskSegments(task)" :key="segment.index" class="segment-result">
                <b>{{ String(segment.index).padStart(4, '0') }}</b><span>{{ segment.text }}</span><small>{{ formatDuration(segment.duration) }}</small>
                <audio v-if="segment.audio_url" controls preload="metadata" :src="voiceGenerationSegmentAudioUrl(segment)" />
                <a v-if="segment.audio_url" :href="voiceGenerationSegmentAudioUrl(segment, true)"><Download :size="13" /> {{ segment.filename }}</a>
              </div>
              <footer v-if="segmentTotalPages(task) > 1" class="segment-pagination">
                <span>每页 {{ segmentPageSize }} 段</span>
                <button type="button" :disabled="segmentPage(task) <= 1" aria-label="上一页分段音频" @click="setSegmentPage(task, segmentPage(task) - 1)"><ChevronLeft :size="14" /></button>
                <strong>{{ segmentPage(task) }} / {{ segmentTotalPages(task) }}</strong>
                <button type="button" :disabled="segmentPage(task) >= segmentTotalPages(task)" aria-label="下一页分段音频" @click="setSegmentPage(task, segmentPage(task) + 1)"><ChevronRight :size="14" /></button>
              </footer>
            </details>
          </div>
          <div class="task-meta">
            <b :class="task.status">{{ statusText(task) }}</b><span>完整音频 {{ formatDuration(task.duration) }}</span><span>{{ formatDate(task.created_at) }}</span>
            <div class="task-actions">
              <button v-if="task.status === 'queued' || task.status === 'running'" type="button" :disabled="operatingTaskId === task.id" title="暂停任务" @click="pauseTask(task)"><Pause :size="14" />暂停</button>
              <button v-if="task.status === 'paused'" type="button" :disabled="operatingTaskId === task.id" title="恢复任务" @click="resumeTask(task)"><RotateCcw :size="14" />恢复</button>
              <button type="button" class="danger" :disabled="operatingTaskId === task.id || task.status === 'running'" :title="task.status === 'running' ? '请先暂停任务' : '删除任务'" @click="deleteTask(task)"><Trash2 :size="14" />删除</button>
            </div>
          </div>
        </div>
      </div>
      <footer v-if="filteredTasks.length" class="task-pagination"><span>共 {{ filteredTasks.length }} 条</span><label>每页 <select v-model="pageSize" aria-label="每页配音任务数"><option :value="10">10</option><option :value="20">20</option><option :value="50">50</option></select></label><button type="button" :disabled="taskPage <= 1" aria-label="上一页" @click="taskPage--"><ChevronLeft :size="16" /></button><strong>{{ taskPage }} / {{ totalPages }}</strong><button type="button" :disabled="taskPage >= totalPages" aria-label="下一页" @click="taskPage++"><ChevronRight :size="16" /></button></footer>
    </article>
  </section>
</template>

<style scoped>
.voice-page{color:#172033}.queue-badge{align-items:center;background:#eaf2ff;border:1px solid #cfe0ff;border-radius:999px;color:#075bf5;display:flex;font-size:12px;font-weight:750;gap:7px;padding:8px 13px}.page-layout{align-items:start;display:grid;gap:16px;grid-template-columns:minmax(560px,1.45fr) minmax(300px,.65fr)}.panel{background:#fff;border:1px solid #e1e7ef;border-radius:13px;box-shadow:0 5px 22px #34435f0a;padding:20px}.panel>header{align-items:center;border-bottom:1px solid #edf0f4;display:flex;gap:11px;margin:-2px 0 20px;padding-bottom:15px}.panel h2{font-size:16px;margin:0}.panel header p{color:#7b8799;font-size:11px;margin:4px 0 0}.panel-icon{align-items:center;background:#eaf2ff;border-radius:9px;color:#0864eb;display:flex;height:38px;justify-content:center;width:38px}.panel-icon.purple{background:#f1ecff;color:#7654d7}.form-grid{display:grid;gap:17px;grid-template-columns:1fr 1fr}.field{display:grid;gap:8px}.field.wide{grid-column:1/-1}.field>span{font-size:12px;font-weight:750}.field>span em{color:#8792a3;float:right;font-size:10px;font-style:normal;font-weight:500}.field b{color:#e13e49}.field input,.field select,.field textarea{background:#fff;border:1px solid #dce3ec;border-radius:8px;box-sizing:border-box;font:inherit;outline:none;padding:11px 12px;width:100%}.field textarea{line-height:1.7;resize:vertical}.field input:focus,.field select:focus,.field textarea:focus{border-color:#0864eb;box-shadow:0 0 0 3px #0864eb12}.field small{color:#8792a3;font-size:10px}.segment-preview{background:#f7f9fc;border:1px solid #e5eaf1;border-radius:9px;margin-top:17px;padding:13px}.segment-preview>strong{font-size:11px}.segment-preview ol{display:grid;gap:7px;list-style:none;margin:10px 0 4px;padding:0}.segment-preview li{display:grid;font-size:10px;gap:9px;grid-template-columns:34px 1fr}.segment-preview li b{color:#0864eb}.segment-preview li span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.segment-preview small{color:#8792a3;font-size:9px}.submit-button{align-items:center;background:#0864eb;border:0;border-radius:9px;color:#fff;display:flex;font-size:13px;font-weight:750;gap:8px;justify-content:center;margin-top:18px;min-height:46px;width:100%}.submit-button:disabled{cursor:not-allowed;opacity:.55}.flow-info>ol{display:grid;gap:17px;list-style:none;margin:0;padding:0}.flow-info li{display:grid;gap:4px;padding-left:22px;position:relative}.flow-info li:before{background:#0864eb;border-radius:50%;color:#fff;content:counter(list-item);font-size:9px;height:16px;left:0;line-height:16px;position:absolute;text-align:center;width:16px}.flow-info li b{font-size:12px}.flow-info li span{color:#68768a;font-size:10px;line-height:1.6}.task-panel{margin-top:16px}.refresh{align-items:center;background:#f7f9fc;border:1px solid #dce3ec;border-radius:7px;color:#46556b;display:flex;gap:6px;margin-left:auto;padding:7px 13px}.empty{color:#8792a3;font-size:12px;padding:25px;text-align:center}.task-list{display:grid;gap:9px}.task-row{align-items:start;border:1px solid #e8edf3;border-radius:9px;display:grid;gap:12px;grid-template-columns:auto minmax(0,1fr) auto;padding:13px}.status-icon{align-items:center;background:#f3f0ff;border-radius:50%;color:#7654d7;display:flex;height:38px;justify-content:center;width:38px}.status-icon.running{background:#eaf2ff;color:#0864eb}.status-icon.completed{background:#e6f8f1;color:#079e6b}.status-icon.failed{background:#fff0f1;color:#d63b49}.task-main{display:grid;gap:8px;min-width:0}.task-main>div:first-child{align-items:center;display:flex;flex-wrap:wrap;gap:9px}.task-main strong{font-size:12px}.task-main>div:first-child span{background:#f2f5f9;border-radius:5px;color:#657389;font-size:9px;padding:3px 6px}.task-main>p{color:#68768a;display:-webkit-box;font-size:10px;line-height:1.5;margin:0;overflow:hidden;white-space:pre-line;-webkit-box-orient:vertical;-webkit-line-clamp:2}.task-error{color:#d63b49;font-size:10px}.full-audio{align-items:center!important;background:#f7fafc;border-radius:8px;display:grid!important;gap:9px!important;grid-template-columns:auto minmax(180px,420px) auto;padding:8px}.full-audio audio{height:32px;width:100%}.full-audio a,.segment-result a{align-items:center;color:#075bf5;display:flex;font-size:10px;font-weight:700;gap:4px}.segment-results{border-top:1px solid #edf0f4;padding-top:8px}.segment-results summary{color:#46556b;cursor:pointer;font-size:11px;font-weight:700}.segment-result{align-items:center;border-bottom:1px solid #f0f2f5;display:grid;gap:8px;grid-template-columns:34px minmax(120px,1fr) 52px minmax(180px,280px) auto;padding:8px 3px}.segment-result>b{color:#0864eb;font-size:9px}.segment-result>span{font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.segment-result>small{color:#8792a3;font-size:9px}.segment-result audio{height:28px;width:100%}.task-meta{display:grid;gap:5px;justify-items:end;text-align:right}.task-meta b{color:#7654d7;font-size:11px}.task-meta b.running{color:#0864eb}.task-meta b.completed{color:#079e6b}.task-meta b.failed{color:#d63b49}.task-meta span{color:#8792a3;font-size:9px}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:1000px){.page-layout{grid-template-columns:1fr}}@media(max-width:750px){.form-grid{grid-template-columns:1fr}.field.wide{grid-column:auto}.task-row{grid-template-columns:auto 1fr}.task-meta{grid-column:2;justify-items:start;text-align:left}.segment-result{grid-template-columns:34px 1fr 52px}.segment-result audio,.segment-result a{grid-column:2/-1}.full-audio{grid-template-columns:1fr}.full-audio audio{grid-column:1}}

/* Keep this page isolated from the global settings form grid. */
.voice-page .form-grid .field {
  align-items: stretch;
  display: grid;
  gap: 8px;
  grid-template-columns: minmax(0, 1fr);
  min-width: 0;
}
.voice-page .form-grid .field > span:first-child {
  align-items: center;
  display: flex;
  gap: 4px;
  min-width: 0;
  white-space: nowrap;
}
.voice-page .form-grid .field > span:first-child em {
  float: none;
  margin-left: auto;
  white-space: nowrap;
}
.voice-page .form-grid .field > small {
  grid-column: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.taf-page-heading > div,
.panel > header > div,
.task-main,
.task-main > div:first-child {
  min-width: 0;
}
.taf-page-heading p,
.panel > header p,
.queue-badge,
.task-main > div:first-child > span,
.task-meta > * {
  white-space: nowrap;
}
.taf-page-heading p,
.panel > header p {
  overflow: hidden;
  text-overflow: ellipsis;
}
.task-main > div:first-child > strong {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-main > p {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.flow-info > ol {
  counter-reset: flow-step;
}
.flow-info li {
  counter-increment: flow-step;
}
.flow-info li::before {
  content: counter(flow-step);
}
.flow-info li b,
.flow-info li span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.segment-result > a {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status-icon.paused{background:#fff7df;color:#b57900}.task-meta b.paused{color:#b57900}.task-actions{display:flex;gap:6px;margin-top:4px}.task-actions button{align-items:center;background:#f7f9fc;border:1px solid #dce3ec;border-radius:6px;color:#46556b;display:flex;font-size:10px;gap:4px;padding:5px 8px}.task-actions button:hover:not(:disabled){border-color:#8ba5ca;color:#075bf5}.task-actions button.danger{color:#c73743}.task-actions button.danger:hover:not(:disabled){border-color:#e1a4aa;color:#a91f2b}.task-actions button:disabled{cursor:not-allowed;opacity:.45}

@media(max-width:750px){
  .voice-page .form-grid .field > small,
  .taf-page-heading p,
  .panel > header p,
  .flow-info li span {
    overflow: visible;
    text-overflow: clip;
    white-space: normal;
  }
  .queue-badge {
    flex: 0 0 auto;
  }
}
</style>

<style scoped>
.task-toolbar{align-items:center;display:flex;gap:9px;margin-bottom:12px}.task-toolbar>label{align-items:center;border:1px solid #dce3ec;border-radius:8px;color:#8290a3;display:flex;height:38px;padding:0 10px;width:min(360px,45%)}.task-toolbar input{border:0;min-width:0;outline:0;padding:0 8px;width:100%}.task-toolbar select,.task-pagination select{background:#fff;border:1px solid #dce3ec;border-radius:7px;min-height:38px;padding:0 28px 0 10px}.task-toolbar>span{color:#7a8699;font-size:11px;margin-left:auto}.task-pagination{align-items:center;border-top:1px solid #edf0f4;display:flex;gap:9px;margin-top:14px;padding-top:12px}.task-pagination>span{color:#718096;font-size:12px;margin-right:auto}.task-pagination label{align-items:center;color:#718096;display:flex;font-size:11px;gap:6px}.task-pagination select{min-height:32px}.task-pagination button{align-items:center;background:#fff;border:1px solid #dce3ec;border-radius:6px;color:#536078;display:flex;height:34px;justify-content:center;min-height:34px;width:34px}.task-pagination strong{font-size:11px}@media(max-width:650px){.task-toolbar{align-items:stretch;display:grid;grid-template-columns:1fr 140px}.task-toolbar>label{width:100%}.task-toolbar>span{grid-column:1/-1;margin:0}.task-pagination{flex-wrap:wrap}.task-pagination>span{flex-basis:100%}}

/* Keep generation history compact; segment audio stays collapsed until requested. */
.task-list{gap:7px;grid-template-columns:repeat(2,minmax(0,1fr))}
.task-row{gap:10px;padding:11px 12px}
.status-icon{height:34px;width:34px}
.task-main{gap:6px}
.task-main>div:first-child{gap:7px}
.task-meta{gap:4px}
.full-audio{gap:8px!important;padding:6px 8px}
.full-audio audio{height:30px}
.segment-results{padding-top:6px}
.segment-results summary{align-items:center;display:flex;font-size:10px;gap:7px;list-style:none;min-height:24px;width:max-content}
.segment-results summary::-webkit-details-marker{display:none}
.segment-results summary::before{border-bottom:4px solid transparent;border-left:5px solid #8290a3;border-top:4px solid transparent;content:"";transition:transform .15s ease}
.segment-results[open] summary::before{transform:rotate(90deg)}
.segment-results summary b{background:#f2f5f9;border-radius:999px;color:#657389;font-size:9px;padding:2px 7px}
.segment-results summary::after{color:#8792a3;content:"展开查看";font-size:9px;font-weight:500}
.segment-results[open] summary::after{content:"收起"}
.segment-pagination{align-items:center;border-top:1px solid #edf0f4;display:flex;gap:7px;justify-content:flex-end;padding-top:8px}.segment-pagination>span{color:#8792a3;font-size:9px;margin-right:auto}.segment-pagination button{align-items:center;background:#fff;border:1px solid #dce3ec;border-radius:5px;color:#536078;display:flex;height:28px;justify-content:center;width:28px}.segment-pagination button:disabled{cursor:not-allowed;opacity:.4}.segment-pagination strong{font-size:9px;white-space:nowrap}
.task-row:hover,.task-row:focus-within{position:relative;z-index:10}.task-error-wrap{color:#d63b49;font-size:10px;min-width:0;outline:none;position:relative}.task-error-preview{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.task-error-tooltip{background:#172033;border-radius:7px;box-shadow:0 7px 22px #17203333;color:#fff;font-size:11px;font-weight:500;left:0;line-height:1.55;max-width:min(420px,70vw);opacity:0;padding:9px 10px;pointer-events:none;position:absolute;top:calc(100% + 6px);transform:translateY(-3px);transition:opacity .15s ease,transform .15s ease;visibility:hidden;width:max-content;z-index:20}.task-error-tooltip p{margin:0;max-height:180px;overflow:auto;white-space:pre-wrap}.task-error-tooltip button{align-items:center;background:#ffffff14;border:1px solid #ffffff38;border-radius:5px;color:#fff;display:flex;font-size:10px;font-weight:700;gap:5px;margin-top:8px;padding:5px 8px}.task-error-tooltip button:hover,.task-error-tooltip button:focus-visible{background:#ffffff24;border-color:#ffffff70;outline:none}.task-error-wrap:hover .task-error-tooltip,.task-error-wrap:focus-within .task-error-tooltip{opacity:1;pointer-events:auto;transform:translateY(0);visibility:visible}
@media(max-width:1050px){.task-list{grid-template-columns:1fr}}
</style>
