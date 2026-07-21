<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Check, Download, FileUp, Merge, RefreshCw, Scissors, Undo2, ZoomIn, ZoomOut } from 'lucide-vue-next'

import { createSrt } from '../../api/narration'
import { getProject, getProjectOutputs, projectOutputFileUrl, type ProjectOutputs } from '../../api/projects'
import { importProjectSrt, listSubtitleCues } from '../../api/storyboard'
import AudioPlayer from '../../components/common/AudioPlayer.vue'
import { usePageFeedback } from '../../services/feedback'
import type { Project } from '../../types/project'
import type { SubtitleCue } from '../../types/storyboard'

const route = useRoute()
const projectId = String(route.params.id)
const project = ref<Project | null>(null)
const outputs = ref<ProjectOutputs | null>(null)
const cues = ref<SubtitleCue[]>([])
const selectedId = ref('')
const draftText = ref('')
const draftStart = ref(0)
const draftEnd = ref(0)
const zoom = ref(1)
const loading = ref(false)
const saving = ref(false)
const confirmed = ref(false)
const error = ref('')
const message = ref('')
usePageFeedback(error, message, { errorTitle: '字幕操作失败', messageTitle: '字幕状态' })
const fileInput = ref<HTMLInputElement | null>(null)

const selected = computed(() => cues.value.find((cue) => cue.id === selectedId.value) || null)
const totalDuration = computed(() => cues.value.length ? Math.max(...cues.value.map((cue) => cue.end_ms)) : 0)
const audioUrl = computed(() => outputs.value?.final_audio_exists && outputs.value.final_audio_path ? projectOutputFileUrl(projectId, outputs.value.final_audio_path) : '')
const srtDownloadUrl = computed(() => outputs.value?.final_srt_exists && outputs.value.final_srt_path ? projectOutputFileUrl(projectId, outputs.value.final_srt_path, true) : '')
const timelineWidth = computed(() => Math.max(900, totalDuration.value / 30 * zoom.value))
const issues = computed(() => cues.value.reduce((count, cue, index) => {
  const previous = cues.value[index - 1]
  return count + (cue.text.length > 42 ? 1 : 0) + (cue.end_ms - cue.start_ms < 800 ? 1 : 0) + (previous && cue.start_ms < previous.end_ms ? 1 : 0)
}, 0))

function formatTime(milliseconds: number) {
  const totalSeconds = Math.max(0, milliseconds) / 1000
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = Math.floor(totalSeconds % 60)
  const fraction = Math.floor(milliseconds % 1000)
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(fraction).padStart(3, '0')}`
}

function srtTime(milliseconds: number) {
  const hours = Math.floor(milliseconds / 3_600_000)
  const minutes = Math.floor(milliseconds % 3_600_000 / 60_000)
  const seconds = Math.floor(milliseconds % 60_000 / 1000)
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')},${String(milliseconds % 1000).padStart(3, '0')}`
}

function selectCue(cue: SubtitleCue) {
  selectedId.value = cue.id
  draftText.value = cue.text
  draftStart.value = cue.start_ms
  draftEnd.value = cue.end_ms
}

function applyDraft() {
  if (!selected.value) return
  cues.value = cues.value.map((cue) => cue.id === selectedId.value ? { ...cue, text: draftText.value, start_ms: draftStart.value, end_ms: draftEnd.value } : cue)
  confirmed.value = false
}

function mergeNext() {
  const index = cues.value.findIndex((cue) => cue.id === selectedId.value)
  if (index < 0 || index >= cues.value.length - 1) return
  const current = cues.value[index]
  const next = cues.value[index + 1]
  cues.value.splice(index, 2, { ...current, text: `${current.text}${current.text.endsWith('。') ? '' : ' '}${next.text}`, end_ms: next.end_ms })
  selectCue(cues.value[index])
  confirmed.value = false
}

function splitCue() {
  if (!selected.value || draftText.value.length < 2) return
  const index = cues.value.findIndex((cue) => cue.id === selectedId.value)
  const splitAt = Math.floor(draftText.value.length / 2)
  const punctuation = Math.max(draftText.value.lastIndexOf('，', splitAt), draftText.value.lastIndexOf('。', splitAt))
  const pivot = punctuation > 0 ? punctuation + 1 : splitAt
  const middle = Math.round((draftStart.value + draftEnd.value) / 2)
  const first = { ...selected.value, text: draftText.value.slice(0, pivot).trim(), start_ms: draftStart.value, end_ms: middle }
  const second = { ...selected.value, id: `${selected.value.id}-split-${Date.now()}`, cue_index: selected.value.cue_index + 0.5, text: draftText.value.slice(pivot).trim(), start_ms: middle, end_ms: draftEnd.value }
  cues.value.splice(index, 1, first, second)
  selectCue(first)
  confirmed.value = false
}

function buildSrt() {
  return cues.value.map((cue, index) => `${index + 1}\n${srtTime(cue.start_ms)} --> ${srtTime(cue.end_ms)}\n${cue.text}\n`).join('\n')
}

async function saveVersion() {
  saving.value = true; error.value = ''; message.value = ''
  try {
    applyDraft()
    const result = await importProjectSrt(projectId, buildSrt())
    cues.value = result.cues
    confirmed.value = true
    message.value = `字幕版本已确认，共 ${result.count} 条 Cue`
  } catch (err) { error.value = err instanceof Error ? err.message : '字幕保存失败' }
  finally { saving.value = false }
}

async function restoreAutomatic() {
  loading.value = true; error.value = ''; message.value = ''
  try {
    await createSrt(projectId)
    cues.value = await listSubtitleCues(projectId)
    if (cues.value.length) selectCue(cues.value[0])
    message.value = '已恢复根据真实配音时长自动生成的字幕'
  } catch (err) { error.value = err instanceof Error ? err.message : '字幕恢复失败' }
  finally { loading.value = false }
}

async function importSrt(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  loading.value = true; error.value = ''
  try {
    const result = await importProjectSrt(projectId, await file.text())
    cues.value = result.cues
    if (cues.value.length) selectCue(cues.value[0])
    message.value = `已导入 ${result.count} 条字幕`
  } catch (err) { error.value = err instanceof Error ? err.message : 'SRT 导入失败' }
  finally { loading.value = false; if (fileInput.value) fileInput.value.value = '' }
}

async function load() {
  loading.value = true; error.value = ''
  try {
    const [p, o, loadedCues] = await Promise.all([getProject(projectId), getProjectOutputs(projectId), listSubtitleCues(projectId)])
    project.value = p; outputs.value = o; cues.value = loadedCues
    if (cues.value.length) selectCue(cues.value[0])
  } catch (err) { error.value = err instanceof Error ? err.message : '字幕时间轴加载失败' }
  finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <section class="subtitle-workspace-page">
    <header class="page-header">
      <div><span class="section-eyebrow">SUBTITLE TIMELINE</span><h1>字幕与时间轴</h1><p>基于真实配音时长校对字幕文字、边界、空隙与重叠。</p></div>
      <div class="page-title-actions">
        <input ref="fileInput" class="visually-hidden-file" type="file" accept=".srt,text/plain" @change="importSrt" />
        <button class="secondary-button" @click="fileInput?.click()"><FileUp :size="16" /> 导入 SRT</button>
        <a v-if="srtDownloadUrl" class="secondary-button" :href="srtDownloadUrl"><Download :size="16" /> 导出 SRT</a>
        <button class="primary-button" :disabled="saving || !cues.length" @click="saveVersion"><Check :size="16" /> {{ saving ? '保存中…' : confirmed ? '字幕已确认' : '确认字幕' }}</button>
      </div>
    </header>

    <div class="subtitle-context-strip panel">
      <span><strong>{{ cues.length }}</strong><small>字幕 Cue</small></span><span><strong>{{ formatTime(totalDuration) }}</strong><small>完整时长</small></span><span><strong>{{ issues }}</strong><small>可读性问题</small></span><span><strong>{{ confirmed ? '已确认' : '编辑中' }}</strong><small>当前版本</small></span>
      <button class="text-button" @click="restoreAutomatic"><Undo2 :size="14" /> 恢复自动结果</button>
    </div>

    <div class="subtitle-workspace">
      <aside class="panel subtitle-cue-list">
        <div class="section-head"><div><span class="section-eyebrow">CUES</span><h2>字幕列表</h2></div><span class="status-pill is-neutral">{{ cues.length }}</span></div>
        <div class="cue-scroll">
          <button v-for="cue in cues" :key="cue.id" :class="{ 'is-active': cue.id === selectedId }" @click="selectCue(cue)">
            <span>{{ String(Math.floor(cue.cue_index)).padStart(3, '0') }}</span><div><strong>{{ cue.text }}</strong><small>{{ formatTime(cue.start_ms) }} — {{ formatTime(cue.end_ms) }}</small></div><i v-if="cue.text.length > 42 || cue.end_ms - cue.start_ms < 800"></i>
          </button>
        </div>
      </aside>

      <section class="panel subtitle-timeline-panel">
        <div class="section-head"><div><span class="section-eyebrow">AUDIO TIMELINE</span><h2>音频波形与字幕轨道</h2></div><div class="timeline-zoom"><button @click="zoom = Math.max(.6, zoom - .2)"><ZoomOut :size="15" /></button><span>{{ Math.round(zoom * 100) }}%</span><button @click="zoom = Math.min(2.4, zoom + .2)"><ZoomIn :size="15" /></button></div></div>
        <AudioPlayer v-if="audioUrl" :src="audioUrl" />
        <div v-else class="timeline-audio-empty">完整配音生成后，可在此同步播放音频与字幕。</div>
        <div class="timeline-scroll">
          <div class="timeline-canvas" :style="{ width: `${timelineWidth}px` }">
            <div class="waveform" aria-hidden="true"><i v-for="index in 110" :key="index" :style="{ height: `${18 + (index * 17 % 52)}%` }"></i></div>
            <button v-for="cue in cues" :key="cue.id" class="timeline-cue" :class="{ 'is-active': cue.id === selectedId }" :style="{ left: `${totalDuration ? cue.start_ms / totalDuration * 100 : 0}%`, width: `${totalDuration ? Math.max(1, (cue.end_ms - cue.start_ms) / totalDuration * 100) : 1}%` }" @click="selectCue(cue)">{{ cue.text }}</button>
          </div>
        </div>
        <div class="timeline-legend"><span><i class="is-normal"></i> 正常</span><span><i class="is-selected"></i> 当前字幕</span><span><i class="is-warning"></i> 需检查</span></div>
      </section>

      <aside class="panel subtitle-properties">
        <div class="section-head"><div><span class="section-eyebrow">PROPERTIES</span><h2>字幕属性</h2></div></div>
        <template v-if="selected">
          <label class="field"><span>字幕原文</span><textarea v-model="draftText" rows="7" @blur="applyDraft"></textarea><small>{{ draftText.length }} 字 · 建议不超过 42 字</small></label>
          <div class="subtitle-time-fields"><label class="field"><span>开始时间（ms）</span><input v-model.number="draftStart" type="number" @change="applyDraft" /></label><label class="field"><span>结束时间（ms）</span><input v-model.number="draftEnd" type="number" @change="applyDraft" /></label></div>
          <dl class="output-path-list"><div><dt>显示时长</dt><dd>{{ ((draftEnd - draftStart) / 1000).toFixed(2) }} 秒</dd></div><div><dt>来源配音段</dt><dd>{{ selected.source_segment_id }}</dd></div><div><dt>检查结果</dt><dd>{{ draftText.length > 42 ? '字幕过长' : draftEnd - draftStart < 800 ? '显示时间过短' : '正常' }}</dd></div></dl>
          <div class="subtitle-edit-actions"><button class="secondary-button" :disabled="cues.findIndex((cue) => cue.id === selectedId) >= cues.length - 1" @click="mergeNext"><Merge :size="15" /> 与下一条合并</button><button class="secondary-button" @click="splitCue"><Scissors :size="15" /> 拆分字幕</button></div>
        </template>
        <div v-else class="empty-state compact-empty"><p>{{ loading ? '正在加载字幕…' : '请选择一条字幕进行校对。' }}</p></div>
      </aside>
    </div>
  </section>
</template>
