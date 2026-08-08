<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { AudioLines, CheckCircle2, Clock3, Download, Loader2, Play, RefreshCw, XCircle } from 'lucide-vue-next'
import { listVoices, type VoiceProfile } from '../api/voices'
import { voiceTagText } from '../utils/tts'
import {
  createVoiceGenerationTask,
  listVoiceGenerationTasks,
  voiceGenerationAudioUrl,
  type VoiceGenerationTask,
} from '../api/voiceGeneration'
import { showToast, usePageFeedback } from '../services/feedback'

const voices = ref<VoiceProfile[]>([])
const tasks = ref<VoiceGenerationTask[]>([])
const voiceProfileId = ref('')
const text = ref('')
const outputFilename = ref('配音.wav')
const submitting = ref(false)
const loading = ref(false)
const error = ref('')
let pollTimer: number | undefined
usePageFeedback(error, undefined, { errorTitle: '配音生成失败' })

const ready = computed(() => Boolean(voiceProfileId.value && text.value.trim() && outputFilename.value.trim()))
const activeCount = computed(() => tasks.value.filter(task => ['queued', 'running'].includes(task.status)).length)

async function loadPage(silent = false) {
  if (!silent) loading.value = true
  try {
    const [voiceItems, taskItems] = await Promise.all([listVoices(), listVoiceGenerationTasks()])
    voices.value = voiceItems
    tasks.value = taskItems
    if (!voiceProfileId.value && voiceItems.length) voiceProfileId.value = voiceItems[0].id
  } catch (err) {
    if (!silent) error.value = err instanceof Error ? err.message : '页面数据加载失败'
  } finally {
    loading.value = false
  }
}

async function submitTask() {
  if (!ready.value) {
    error.value = '请选择参考音色，并填写文本和输出文件名'
    return
  }
  submitting.value = true
  error.value = ''
  try {
    const task = await createVoiceGenerationTask({
      voice_profile_id: voiceProfileId.value,
      text: text.value.trim(),
      output_filename: outputFilename.value.trim(),
    })
    tasks.value = [task, ...tasks.value.filter(item => item.id !== task.id)]
    showToast({
      title: '配音任务已加入队列',
      description: task.queue_position ? `当前队列位置：${task.queue_position}` : '任务即将开始',
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
  if (task.status === 'running') return '正在生成'
  if (task.status === 'queued') return task.queue_position ? `排队第 ${task.queue_position} 位` : '排队中'
  return task.status === 'completed' ? '已完成' : '生成失败'
}

const formatDate = (value: string | null) => value ? new Date(value).toLocaleString() : '—'
const formatDuration = (value: number | null) => value === null ? '—' : `${value.toFixed(1)} 秒`

onMounted(async () => {
  await loadPage()
  pollTimer = window.setInterval(() => void loadPage(true), 2500)
})
onBeforeUnmount(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
})
</script>

<template>
  <section class="voice-page">
    <header class="taf-page-heading">
      <div><h1>配音生成</h1><p>选择参考音色并直接生成一条完整音频，不执行文本切段。</p></div>
      <span class="queue-badge"><Clock3 :size="17" /> 队列中 {{ activeCount }}</span>
    </header>

    <div class="page-layout">
      <article class="panel">
        <header><span class="panel-icon"><AudioLines :size="21" /></span><div><h2>新建配音任务</h2><p>提交后可继续创建任务，系统会按顺序生成。</p></div></header>
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
            <input v-model="outputFilename" maxlength="200" placeholder="例如：人物开场白.wav" />
            <small>未填写扩展名时会自动添加 .wav。</small>
          </label>
          <label class="field wide">
            <span>文本内容 <b>*</b><em>{{ text.length }} / 50000</em></span>
            <textarea v-model="text" maxlength="50000" rows="11" placeholder="输入需要生成配音的完整文本……"></textarea>
            <small>文本将作为一个整体提交给 TTS，不会自动切段。</small>
          </label>
        </div>
        <button class="submit-button" type="button" :disabled="!ready || submitting" @click="submitTask">
          <Loader2 v-if="submitting" class="spin" :size="18" /><Play v-else :size="18" />
          {{ submitting ? '正在提交…' : '生成配音' }}
        </button>
      </article>

      <aside class="panel queue-info">
        <header><span class="panel-icon purple"><Clock3 :size="21" /></span><div><h2>任务队列</h2><p>关闭页面不会中断生成。</p></div></header>
        <ol>
          <li>任务按照提交顺序逐个处理，同一时刻只生成一个配音任务。</li>
          <li>每个任务只生成一条完整 WAV，不创建分段、字幕或时间轴。</li>
          <li>结果保存在本地工作区，可在下方直接试听或下载。</li>
          <li>后端重启后，未完成的任务会自动重新排队。</li>
        </ol>
      </aside>
    </div>

    <article class="panel task-panel">
      <header>
        <span class="panel-icon purple"><AudioLines :size="21" /></span><div><h2>配音任务</h2><p>状态每 2.5 秒自动刷新。</p></div>
        <button class="refresh" type="button" :disabled="loading" @click="loadPage()"><RefreshCw :class="{ spin: loading }" :size="15" />{{ loading ? '刷新中' : '刷新' }}</button>
      </header>
      <div v-if="!tasks.length" class="empty">尚未提交配音任务。</div>
      <div v-else class="task-list">
        <div v-for="task in tasks" :key="task.id" class="task-row">
          <span class="status-icon" :class="task.status">
            <Loader2 v-if="task.status === 'running'" class="spin" :size="19" /><Clock3 v-else-if="task.status === 'queued'" :size="19" /><CheckCircle2 v-else-if="task.status === 'completed'" :size="19" /><XCircle v-else :size="19" />
          </span>
          <div class="task-main">
            <div><strong>{{ task.output_filename }}</strong><span>{{ task.voice_profile_name }}</span><span>{{ voiceTagText(task.tts_engine, task.language) }}</span></div>
            <p>{{ task.text }}</p>
            <span v-if="task.error_message" class="task-error">{{ task.error_message }}</span>
            <audio v-if="task.audio_url" controls preload="none" :src="voiceGenerationAudioUrl(task)"></audio>
          </div>
          <div class="task-meta">
            <b :class="task.status">{{ statusText(task) }}</b><span>音频 {{ formatDuration(task.duration) }}</span><span>{{ formatDate(task.created_at) }}</span>
            <a v-if="task.audio_url" :href="voiceGenerationAudioUrl(task, true)"><Download :size="14" /> 下载</a>
          </div>
        </div>
      </div>
    </article>
  </section>
</template>

<style scoped>
.voice-page{color:#172033}.queue-badge{align-items:center;background:#eaf2ff;border:1px solid #cfe0ff;border-radius:999px;color:#075bf5;display:flex;font-size:12px;font-weight:750;gap:7px;padding:8px 13px}.page-layout{align-items:start;display:grid;gap:16px;grid-template-columns:minmax(560px,1.45fr) minmax(300px,.65fr)}.panel{background:#fff;border:1px solid #e1e7ef;border-radius:13px;box-shadow:0 5px 22px #34435f0a;padding:20px}.panel>header{align-items:center;border-bottom:1px solid #edf0f4;display:flex;gap:11px;margin:-2px 0 20px;padding-bottom:15px}.panel h2{font-size:16px;margin:0}.panel header p{color:#7b8799;font-size:11px;margin:4px 0 0}.panel-icon{align-items:center;background:#eaf2ff;border-radius:9px;color:#0864eb;display:flex;height:38px;justify-content:center;width:38px}.panel-icon.purple{background:#f1ecff;color:#7654d7}.form-grid{display:grid;gap:17px;grid-template-columns:1fr 1fr}.field{display:grid;gap:8px}.field.wide{grid-column:1/-1}.field>span{font-size:12px;font-weight:750}.field>span em{color:#8792a3;float:right;font-size:10px;font-style:normal;font-weight:500}.field b{color:#e13e49}.field input,.field select,.field textarea{background:#fff;border:1px solid #dce3ec;border-radius:8px;box-sizing:border-box;font:inherit;outline:none;padding:11px 12px;width:100%}.field textarea{line-height:1.7;resize:vertical}.field input:focus,.field select:focus,.field textarea:focus{border-color:#0864eb;box-shadow:0 0 0 3px #0864eb12}.field small{color:#8792a3;font-size:10px}.submit-button{align-items:center;background:#0864eb;border:0;border-radius:9px;color:#fff;display:flex;font-size:13px;font-weight:750;gap:8px;justify-content:center;margin-top:22px;min-height:46px;width:100%}.submit-button:disabled{cursor:not-allowed;opacity:.55}.queue-info ol{color:#59687c;display:grid;font-size:12px;gap:14px;line-height:1.6;margin:0;padding-left:20px}.task-panel{margin-top:16px}.refresh{align-items:center;background:#f7f9fc;border:1px solid #dce3ec;border-radius:7px;color:#46556b;display:flex;gap:6px;margin-left:auto;padding:7px 13px}.empty{color:#8792a3;font-size:12px;padding:25px;text-align:center}.task-list{display:grid;gap:9px}.task-row{align-items:start;border:1px solid #e8edf3;border-radius:9px;display:grid;gap:12px;grid-template-columns:auto minmax(0,1fr) auto;padding:13px}.status-icon{align-items:center;background:#f3f0ff;border-radius:50%;color:#7654d7;display:flex;height:38px;justify-content:center;width:38px}.status-icon.running{background:#eaf2ff;color:#0864eb}.status-icon.completed{background:#e6f8f1;color:#079e6b}.status-icon.failed{background:#fff0f1;color:#d63b49}.task-main{display:grid;gap:7px;min-width:0}.task-main>div{align-items:center;display:flex;gap:9px}.task-main strong{font-size:12px}.task-main>div span{background:#f2f5f9;border-radius:5px;color:#657389;font-size:9px;padding:3px 6px}.task-main p{color:#68768a;display:-webkit-box;font-size:10px;line-height:1.5;margin:0;overflow:hidden;-webkit-box-orient:vertical;-webkit-line-clamp:2}.task-main .task-error{color:#d63b49;font-size:10px}.task-main audio{height:32px;max-width:440px;width:100%}.task-meta{display:grid;gap:5px;justify-items:end;text-align:right}.task-meta b{color:#7654d7;font-size:11px}.task-meta b.running{color:#0864eb}.task-meta b.completed{color:#079e6b}.task-meta b.failed{color:#d63b49}.task-meta span{color:#8792a3;font-size:9px}.task-meta a{align-items:center;color:#075bf5;display:flex;font-size:10px;font-weight:700;gap:4px;margin-top:3px}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:1000px){.page-layout{grid-template-columns:1fr}}@media(max-width:650px){.form-grid{grid-template-columns:1fr}.field.wide{grid-column:auto}.task-row{grid-template-columns:auto 1fr}.task-meta{grid-column:2;justify-items:start;text-align:left}}
</style>
