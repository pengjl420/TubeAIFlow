<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CirclePause, Folder, Layers3, Play, RefreshCw, RotateCcw, Upload } from 'lucide-vue-next'
import { createBatch, getBatch, listBatches, pauseBatch, retryBatchItem, startBatch, type BatchJob } from '../../api/batches'
import { listVoices, type VoiceProfile } from '../../api/voices'
import { getSystemSettings, selectDirectory } from '../../api/settings'
import type { VideoGenerationMode } from '../../types/project'
import { usePageFeedback } from '../../services/feedback'

const batches = ref<BatchJob[]>([])
const selected = ref<BatchJob | null>(null)
const voices = ref<VoiceProfile[]>([])
const loading = ref(true)
const operating = ref(false)
const error = ref('')
const message = ref('')
const name = ref('批量生成')
const scripts = ref<File[]>([])
const outputDir = ref('')
const mediaVideoDir = ref('')
const voiceProfileId = ref('')
const videoMode = ref<VideoGenerationMode>('ai_generated_images')
const segmentationMode = ref<'newline' | 'ai'>('ai')
const continueOnError = ref(true)
let timer: number | undefined
usePageFeedback(error, message, { errorTitle: '批量生产错误' })

const needsMedia = computed(() => ['landscape', 'ai_landscape_mix'].includes(videoMode.value))
const canSubmit = computed(() => scripts.value.length > 0 && outputDir.value.trim() && voiceProfileId.value && (!needsMedia.value || mediaVideoDir.value.trim()))

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const rows = await listBatches()
    batches.value = rows
    if (!silent && !voices.value.length) {
      const [voiceRows, settings] = await Promise.all([listVoices(), getSystemSettings()])
      voices.value = voiceRows
      if (!outputDir.value) outputDir.value = `${settings.workspace_dir}\\projects`
      if (!voiceProfileId.value && voiceRows.length) voiceProfileId.value = voiceRows[0].id
    }
    if (selected.value) selected.value = await getBatch(selected.value.id)
  } catch (reason) { if (!silent) error.value = reason instanceof Error ? reason.message : '加载批次失败' }
  finally { if (!silent) loading.value = false }
}

function pickScripts(event: Event) {
  scripts.value = Array.from((event.target as HTMLInputElement).files || []).slice(0, 100)
}

async function chooseDirectory(kind: 'output' | 'media') {
  const current = kind === 'output' ? outputDir.value : mediaVideoDir.value
  const path = await selectDirectory(current, kind === 'output' ? '选择批量输出目录' : '选择横屏素材目录')
  if (path) kind === 'output' ? outputDir.value = path : mediaVideoDir.value = path
}

async function submit() {
  if (!canSubmit.value) return
  operating.value = true
  try {
    selected.value = await createBatch({ name: name.value, scripts: scripts.value, outputDir: outputDir.value, mediaVideoDir: mediaVideoDir.value, videoMode: videoMode.value, voiceProfileId: voiceProfileId.value, segmentationMode: segmentationMode.value, storyboardMode: 'ai', continueOnError: continueOnError.value })
    scripts.value = []
    message.value = `批次 ${selected.value.name} 已创建并开始排队`
    await load(true)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '创建批次失败' }
  finally { operating.value = false }
}

async function openBatch(batch: BatchJob) { selected.value = await getBatch(batch.id) }
async function toggleBatch() {
  if (!selected.value) return
  operating.value = true
  try { selected.value = ['queued', 'running'].includes(selected.value.status) ? await pauseBatch(selected.value.id) : await startBatch(selected.value.id); await load(true) }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '更新批次失败' }
  finally { operating.value = false }
}
async function retry(itemId: string) {
  if (!selected.value || operating.value) return
  operating.value = true
  try {
    await retryBatchItem(selected.value.id, itemId)
    selected.value = await getBatch(selected.value.id)
    await load(true)
    message.value = '失败项目已重新加入队列'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '重试项目失败'
  } finally {
    operating.value = false
  }
}

onMounted(async () => { await load(); timer = window.setInterval(() => void load(true), 4000) })
onBeforeUnmount(() => { if (timer !== undefined) window.clearInterval(timer) })
</script>

<template>
  <section class="batch-page"><header class="taf-sticky-heading"><div><h1>批量生产</h1><p>一次导入最多 100 份 TXT/Markdown 逐字稿，使用持久任务队列逐项生产。</p></div><button :disabled="loading" @click="load()"><RefreshCw :size="15" />刷新</button></header><div class="batch-layout"><form class="batch-create" @submit.prevent="submit"><h2><Upload :size="17" />新建批次</h2><label><span>批次名称</span><input v-model="name" required /></label><label><span>逐字稿</span><input type="file" accept=".txt,.md,text/plain,text/markdown" multiple required @change="pickScripts" /><small>已选择 {{ scripts.length }} 个文件</small></label><label><span>音色</span><select v-model="voiceProfileId" required><option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.name }} · {{ voice.tts_engine }}</option></select></label><label><span>视频模式</span><select v-model="videoMode"><option value="ai_generated_images">AI 分镜图片</option><option value="ai_landscape_mix">AI + 本地素材</option><option value="landscape">仅本地素材</option><option value="none">仅配音字幕</option></select></label><label><span>分段方式</span><select v-model="segmentationMode"><option value="ai">AI 语义分段</option><option value="newline">按换行分段</option></select></label><label><span>输出目录</span><div><input v-model="outputDir" required /><button type="button" @click="chooseDirectory('output')"><Folder :size="13" />浏览</button></div></label><label v-if="needsMedia"><span>素材目录</span><div><input v-model="mediaVideoDir" required /><button type="button" @click="chooseDirectory('media')"><Folder :size="13" />浏览</button></div></label><label class="check"><input v-model="continueOnError" type="checkbox" />单个项目失败后继续执行</label><button class="primary" type="submit" :disabled="operating || !canSubmit"><Play :size="14" />{{ operating ? '创建中…' : '创建并开始' }}</button></form><main><section class="batch-list"><button v-for="batch in batches" :key="batch.id" :class="{ selected: selected?.id === batch.id }" @click="openBatch(batch)"><Layers3 :size="18" /><span><strong>{{ batch.name }}</strong><small>{{ batch.completed }}/{{ batch.total }} 完成 · {{ batch.failed }} 失败</small></span><em :class="batch.status">{{ batch.status }}</em></button><p v-if="!batches.length && !loading">暂无批次</p></section><section v-if="selected" class="batch-detail"><header><div><h2>{{ selected.name }}</h2><p>{{ selected.id }} · {{ selected.completed }}/{{ selected.total }} 完成</p></div><button :disabled="operating || selected.status === 'completed'" @click="toggleBatch"><CirclePause v-if="['queued','running'].includes(selected.status)" :size="14" /><Play v-else :size="14" />{{ ['queued','running'].includes(selected.status) ? '暂停' : '继续' }}</button></header><div class="progress"><i :style="{ width: `${selected.total ? (selected.completed + selected.failed) / selected.total * 100 : 0}%` }" /></div><article v-for="item in selected.items" :key="item.id"><div><strong>{{ item.project_name }}</strong><small>{{ item.original_filename }} · {{ item.current_stage }}</small><p v-if="item.error_message">{{ item.error_message }}</p></div><span :class="item.status">{{ item.status }}</span><button v-if="item.status === 'failed'" :disabled="operating" @click="retry(item.id)"><RotateCcw :size="13" />重试</button><RouterLink :to="`/projects/${item.project_id}`">打开项目</RouterLink></article></section><section v-else class="batch-empty">选择一个批次查看项目级进度</section></main></div></section>
</template>

<style scoped>
.batch-page>header{align-items:flex-end;display:flex;justify-content:space-between;margin-bottom:16px}.batch-page h1{font-size:27px;margin:0 0 4px}.batch-page header p{color:#78859a;font-size:12px;margin:0}.batch-page>header button,.batch-detail header button{align-items:center;background:#fff;border:1px solid #dce3ed;border-radius:7px;color:#536078;display:flex;gap:5px;padding:8px 11px}.batch-layout{display:grid;gap:14px;grid-template-columns:330px 1fr}.batch-create,.batch-layout>main{background:#fff;border:1px solid #e0e6ee;border-radius:11px;padding:15px}.batch-create{display:grid;gap:11px;height:max-content}.batch-create h2{align-items:center;display:flex;font-size:15px;gap:6px;margin:0 0 3px}.batch-create label{display:grid;gap:5px}.batch-create label span{color:#526078;font-size:11px;font-weight:700}.batch-create input,.batch-create select{border:1px solid #d9e1ec;border-radius:7px;min-height:38px;padding:7px 9px;width:100%}.batch-create label>div{display:flex;gap:6px}.batch-create label>div button{align-items:center;background:#edf3fc;border-radius:7px;color:#38639a;display:flex;gap:3px;padding:7px}.batch-create small{color:#8490a3}.batch-create .check{align-items:center;display:flex;flex-direction:row;font-size:11px}.batch-create .check input{min-height:auto;width:auto}.batch-create .primary{align-items:center;background:#075bf5;border-radius:7px;color:#fff;display:flex;gap:5px;justify-content:center;padding:10px}.batch-list{display:grid;gap:6px}.batch-list>button{align-items:center;background:#f7f9fc;border:1px solid transparent;border-radius:8px;color:#536078;display:grid;gap:8px;grid-template-columns:auto 1fr auto;padding:10px;text-align:left}.batch-list>button.selected{background:#edf4ff;border-color:#9fc0f6}.batch-list span{display:grid}.batch-list strong{font-size:12px}.batch-list small{color:#8490a3;font-size:10px;margin-top:3px}.batch-list em,.batch-detail article>span{background:#edf0f5;border-radius:999px;font-size:9px;font-style:normal;padding:4px 6px}.batch-detail{border-top:1px solid #e8edf3;margin-top:13px;padding-top:13px}.batch-detail header{align-items:center;display:flex;justify-content:space-between}.batch-detail h2{font-size:16px;margin:0}.batch-detail header p{font-size:10px}.progress{background:#e8edf4;border-radius:10px;height:6px;margin:11px 0;overflow:hidden}.progress i{background:#0a9b6c;display:block;height:100%}.batch-detail article{align-items:center;border-top:1px solid #edf0f4;display:grid;gap:8px;grid-template-columns:1fr auto auto auto;padding:10px 2px}.batch-detail article div{display:grid}.batch-detail article small{color:#8490a3;font-size:10px}.batch-detail article p{color:#c5404b;font-size:10px;margin:3px 0 0}.batch-detail article button,.batch-detail article a{align-items:center;color:#075bf5;display:flex;font-size:10px;gap:3px}.batch-empty{color:#8a95a6;padding:70px;text-align:center}@media(max-width:900px){.batch-layout{grid-template-columns:1fr}.batch-detail article{grid-template-columns:1fr auto}.batch-detail article button,.batch-detail article a{grid-row:2}}
</style>
