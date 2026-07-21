<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertCircle, Check, ChevronDown, FileText, Folder, GripVertical, Headphones,
  Image, Monitor, Play, Scissors, Sparkles, UploadCloud, UserCheck, X,
} from 'lucide-vue-next'

import { createBatch } from '../../api/batches'
import { selectDirectory } from '../../api/projects'
import { listVoices, type VoiceProfile } from '../../api/voices'
import { showToast } from '../../services/feedback'
import type { SegmentationMode, SemanticReviewMode, StoryboardMode, VideoGenerationMode } from '../../types/project'

const router = useRouter()
const today = new Date().toISOString().slice(0, 10).replace(/-/g, '')
const name = ref(`短剧批量生产_${today}_01`)
const scripts = ref<File[]>([])
const voices = ref<VoiceProfile[]>([])
const voiceProfileId = ref('')
const outputDir = ref('')
const mediaVideoDir = ref('')
const videoMode = ref<VideoGenerationMode>('ai_semantic')
const semanticReviewMode = ref<SemanticReviewMode>('automatic')
const segmentationMode = ref<SegmentationMode>('ai')
const storyboardMode = ref<StoryboardMode>('ai')
const continueOnError = ref(true)
const saving = ref(false)
const selectingFolder = ref<'output' | 'video' | null>(null)
const error = ref('')
const dragging = ref(false)

const duplicateNames = computed(() => {
  const names = scripts.value.map((file) => file.name.toLocaleLowerCase())
  return new Set(names.filter((item, index) => names.indexOf(item) !== index))
})
const estimatedCharacters = computed(() => scripts.value.reduce((sum, file) => sum + Math.round(file.size / 2.4), 0))
const estimatedStorage = computed(() => (scripts.value.reduce((sum, file) => sum + file.size, 0) * 1000 / 1024 / 1024 / 1024).toFixed(1))
const selectedVoice = computed(() => voices.value.find((voice) => voice.id === voiceProfileId.value))
const ready = computed(() => Boolean(scripts.value.length && voiceProfileId.value && outputDir.value && !duplicateNames.value.size))

function addScripts(files: File[]) {
  const accepted = files.filter((file) => /\.(txt|md)$/i.test(file.name) && file.size <= 20 * 1024 * 1024)
  scripts.value = [...scripts.value, ...accepted]
  if (accepted.length !== files.length) error.value = '部分文件格式不支持或超过 20 MB，已自动忽略。'
}
function selectScripts(event: Event) { addScripts(Array.from((event.target as HTMLInputElement).files || [])) }
function dropScripts(event: DragEvent) { dragging.value = false; addScripts(Array.from(event.dataTransfer?.files || [])) }
function moveScript(index: number, offset: number) {
  const target = index + offset
  if (target < 0 || target >= scripts.value.length) return
  const next = [...scripts.value]
  const [file] = next.splice(index, 1)
  next.splice(target, 0, file)
  scripts.value = next
}
function removeScript(index: number) { scripts.value = scripts.value.filter((_, itemIndex) => itemIndex !== index) }
function formatSize(bytes: number) { return bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB` }

async function chooseFolder(target: 'output' | 'video') {
  selectingFolder.value = target
  error.value = ''
  try {
    const selected = await selectDirectory(target === 'output' ? outputDir.value : mediaVideoDir.value, target === 'output' ? '选择批量输出文件夹' : '选择风景素材文件夹')
    if (selected && target === 'output') outputDir.value = selected
    if (selected && target === 'video') mediaVideoDir.value = selected
  } catch (err) { error.value = err instanceof Error ? err.message : '文件夹选择失败' }
  finally { selectingFolder.value = null }
}

function saveDraft() {
  localStorage.setItem('tubeaiflow-batch-draft', JSON.stringify({ name: name.value, voiceProfileId: voiceProfileId.value, outputDir: outputDir.value, mediaVideoDir: mediaVideoDir.value, videoMode: videoMode.value, semanticReviewMode: semanticReviewMode.value, segmentationMode: segmentationMode.value, storyboardMode: storyboardMode.value, continueOnError: continueOnError.value }))
  showToast({ title: '批次配置草稿已保存', description: '文件列表受浏览器安全限制，请下次重新选择。', tone: 'success' })
}

async function submit() {
  if (!scripts.value.length) return void (error.value = '请至少上传一份逐字稿文件')
  if (duplicateNames.value.size) return void (error.value = '请移除重复文件后再创建批次')
  if (!voiceProfileId.value) return void (error.value = '请选择系统音色')
  if (!outputDir.value.trim()) return void (error.value = '请选择输出目录')
  if (videoMode.value === 'landscape' && !mediaVideoDir.value.trim()) return void (error.value = '风景素材拼接模式需要选择素材目录')
  saving.value = true; error.value = ''
  try {
    const batch = await createBatch({ name: name.value.trim() || '批量生产', scripts: scripts.value, voiceProfileId: voiceProfileId.value, outputDir: outputDir.value.trim(), mediaVideoDir: videoMode.value === 'landscape' ? mediaVideoDir.value.trim() : '', includeVideo: videoMode.value !== 'none', videoMode: videoMode.value, semanticReviewMode: semanticReviewMode.value, segmentationMode: segmentationMode.value, storyboardMode: storyboardMode.value, continueOnError: continueOnError.value })
    localStorage.removeItem('tubeaiflow-batch-draft')
    await router.push(`/batches/${batch.id}`)
  } catch (err) { error.value = err instanceof Error ? err.message : '批次创建失败' }
  finally { saving.value = false }
}

onMounted(async () => {
  try {
    voices.value = await listVoices()
    const raw = localStorage.getItem('tubeaiflow-batch-draft')
    if (raw) {
      const draft = JSON.parse(raw)
      name.value = draft.name || name.value; voiceProfileId.value = draft.voiceProfileId || ''; outputDir.value = draft.outputDir || ''; mediaVideoDir.value = draft.mediaVideoDir || ''; videoMode.value = draft.videoMode || videoMode.value; semanticReviewMode.value = draft.semanticReviewMode || semanticReviewMode.value; segmentationMode.value = draft.segmentationMode || segmentationMode.value; storyboardMode.value = draft.storyboardMode || storyboardMode.value; continueOnError.value = draft.continueOnError ?? true
    }
    if (!voiceProfileId.value && voices.value.length === 1) voiceProfileId.value = voices.value[0].id
  } catch (err) { error.value = err instanceof Error ? err.message : '系统音色加载失败' }
})
</script>

<template>
  <section class="batch-create-page">
    <header class="create-heading"><div><h1>新建批次</h1><p>通过向导快速创建批量生产任务</p></div><RouterLink to="/batches">返回批次列表</RouterLink></header>
    <div class="stepper"><div class="active"><i>1</i><strong>导入脚本</strong></div><span></span><div class="active"><i>2</i><strong>统一生产配置</strong></div><span></span><div :class="{ active: ready }"><i>3</i><strong>确认和开始</strong></div></div>

    <div class="create-columns">
      <article class="create-card scripts-card"><h2><i>1</i>导入脚本</h2><label class="field"><span>批次名称 <b>*</b></span><div class="count-input"><input v-model="name" maxlength="50" /><small>{{ name.length }}/50</small></div></label>
        <div class="field"><span>上传脚本文件 <b>*</b></span><label class="dropzone" :class="{ dragging }" @dragenter.prevent="dragging=true" @dragover.prevent @dragleave.prevent="dragging=false" @drop.prevent="dropScripts"><UploadCloud :size="25"/><strong>点击上传或拖拽文件到此处</strong><small>支持 .txt、.md 格式，单文件不超过 20MB</small><em>选择文件</em><input type="file" accept=".txt,.md,text/plain,text/markdown" multiple @change="selectScripts" /></label></div>
        <div v-if="scripts.length" class="uploaded"><header><span>已上传文件（拖拽可调整顺序）</span><strong>共 {{ scripts.length }} 个项目</strong></header><div class="file-list"><div v-for="(file,index) in scripts" :key="`${file.name}-${file.lastModified}-${index}`" :class="{ duplicate: duplicateNames.has(file.name.toLocaleLowerCase()) }"><GripVertical :size="15"/><i>{{ index+1 }}</i><FileText :size="16"/><span><strong>{{ file.name }}</strong><small>{{ formatSize(file.size) }}<em v-if="duplicateNames.has(file.name.toLocaleLowerCase())">重复</em></small></span><button :disabled="index===0" title="上移" @click="moveScript(index,-1)">↑</button><button :disabled="index===scripts.length-1" title="下移" @click="moveScript(index,1)">↓</button><button title="移除" @click="removeScript(index)"><X :size="15"/></button></div></div></div>
        <div class="field"><span>文件名到项目名规则</span><select><option>按文件名（去除扩展名）作为项目名</option></select></div><div class="duplicate-state" :class="{ danger: duplicateNames.size }"><Check v-if="!duplicateNames.size" :size="15"/><AlertCircle v-else :size="15"/>{{ duplicateNames.size ? `发现 ${duplicateNames.size} 个重复文件名` : '未发现重复文件' }}</div>
      </article>

      <article class="create-card settings-card"><h2><i>2</i>统一生产配置</h2><div class="settings-grid">
        <label class="setting"><span><Headphones/>系统音色 <b>*</b></span><select v-model="voiceProfileId"><option value="">请选择系统音色</option><option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.name }} · {{ voice.tts_engine }}</option></select></label>
        <div class="setting"><span><Folder/>输出目录 <b>*</b></span><div class="path-input"><input v-model="outputDir" readonly placeholder="请选择输出文件夹"/><button @click="chooseFolder('output')"><Folder :size="16"/></button></div></div>
        <label class="setting"><span><Scissors/>切段方式 <b>*</b></span><select v-model="segmentationMode"><option value="ai">AI 自动切段（推荐）</option><option value="newline">按换行切段</option></select></label>
        <label class="setting"><span><Monitor/>视频模式 <b>*</b></span><select v-model="videoMode"><option value="ai_semantic">AI 语义视频拼接</option><option value="ai_generated_images">本地 AI 分镜图片视频</option><option value="landscape">风景素材拼接</option><option value="none">仅配音与字幕</option></select></label>
        <label class="setting" v-if="videoMode==='ai_semantic'||videoMode==='ai_generated_images'"><span><Sparkles/>分镜方式 <b>*</b></span><select v-model="storyboardMode"><option value="ai">AI 自动分镜（推荐）</option><option value="segments">按逐字稿切段生成</option></select></label>
        <label class="setting" v-if="videoMode==='ai_semantic'||videoMode==='ai_generated_images'"><span><UserCheck/>审核方式 <b>*</b></span><select v-model="semanticReviewMode"><option value="automatic">自动通过（无需人工审核）</option><option value="manual">人工审核</option></select></label>
        <div class="setting wide" v-if="videoMode==='landscape'"><span><Image/>风景素材目录 <b>*</b></span><div class="path-input"><input v-model="mediaVideoDir" readonly placeholder="请选择素材文件夹"/><button @click="chooseFolder('video')"><Folder :size="16"/></button></div></div>
        <label class="setting continue"><span><AlertCircle/>失败后是否继续 <b>*</b></span><select v-model="continueOnError"><option :value="true">继续处理后续项目</option><option :value="false">立即暂停批次</option></select></label>
      </div><div class="config-tip"><AlertCircle :size="17"/><span><strong>配置提示</strong>以上配置将应用于本批次的所有项目，创建后不可修改。请确保输出目录拥有足够的可用空间。</span></div></article>

      <article class="create-card confirm-card"><h2><i>3</i>确认和开始</h2><div class="summary-box"><h3>批次概要</h3><dl><dt>项目数量</dt><dd class="accent">{{ scripts.length }} 个</dd><dt>脚本文件</dt><dd>{{ scripts.length }} 个文件</dd><dt>总字符数（估算）</dt><dd>约 {{ estimatedCharacters.toLocaleString() }} 字</dd><dt>预计磁盘占用</dt><dd>约 {{ estimatedStorage }} GB</dd></dl><h3>配置摘要</h3><dl><dt>系统音色</dt><dd>{{ selectedVoice?.name || '未选择' }}</dd><dt>输出目录</dt><dd class="path">{{ outputDir || '未选择' }}</dd><dt>切段方式</dt><dd>{{ segmentationMode==='ai'?'AI 自动切段':'按换行切段' }}</dd><dt>视频模式</dt><dd>{{ videoMode==='none'?'仅配音与字幕':videoMode==='landscape'?'风景素材拼接':'AI 语义生产' }}</dd><dt>审核方式</dt><dd>{{ semanticReviewMode==='automatic'?'自动通过':'人工审核' }}</dd></dl><h3>预计磁盘占用 <b>约 {{ estimatedStorage }} GB</b></h3><div class="storage-bar"><i :style="{width: `${Math.min(100,Number(estimatedStorage))}%`}"></i></div><div class="ready-state" :class="{ ready }"><Check :size="17"/>{{ ready ? '已就绪，可以创建' : '请完成左侧必填配置' }}</div></div></article>
    </div>
    <p v-if="error" class="create-error"><AlertCircle :size="17"/>{{ error }}</p>
    <footer class="create-actions"><RouterLink to="/batches">取消</RouterLink><button class="draft" @click="saveDraft">保存草稿</button><button class="submit" :disabled="saving || selectingFolder!==null" @click="submit"><Play :size="18"/>{{ saving?'正在创建项目…':'创建并开始' }}</button></footer>
  </section>
</template>

<style scoped>
.batch-create-page{color:#1d2738;padding-bottom:74px}.create-heading{align-items:flex-start;display:flex;justify-content:space-between}.create-heading h1{font-size:27px;margin:0 0 6px}.create-heading p{color:#758196;margin:0}.create-heading>a{border:1px solid #dfe5ed;border-radius:8px;color:#536176;padding:9px 13px;text-decoration:none}.stepper{align-items:center;display:flex;justify-content:center;margin:0 auto 24px;max-width:650px}.stepper>div{align-items:center;color:#6e7a8d;display:flex;font-size:13px;gap:9px}.stepper i,.create-card h2 i{align-items:center;border:1px solid #cbd4df;border-radius:50%;display:inline-flex;font-style:normal;height:27px;justify-content:center;width:27px}.stepper .active{color:#243248}.stepper .active i,.create-card h2 i{background:#0864eb;border-color:#0864eb;color:#fff}.stepper>span{background:#dbe2ea;height:1px;margin:0 22px;width:115px}.create-columns{display:grid;gap:16px;grid-template-columns:1.1fr 1.25fr .92fr}.create-card{background:#fff;border:1px solid #e4e9f0;border-radius:13px;box-shadow:0 5px 20px #34435f0a;padding:17px}.create-card h2{align-items:center;display:flex;font-size:15px;gap:9px;margin:0 0 20px}.create-card h2 i{font-size:12px;height:22px;width:22px}.field{display:block;margin-bottom:16px}.field>span,.setting>span{display:flex;font-size:12px;font-weight:700;margin-bottom:8px}.field b,.setting b{color:#f04451;margin-left:4px}.count-input{position:relative}.count-input input,.field select,.setting select,.path-input input{border:1px solid #dce3ec;border-radius:7px;box-sizing:border-box;outline:none;padding:10px 12px;width:100%}.count-input small{color:#8d98a9;position:absolute;right:10px;top:11px}.dropzone{align-items:center;border:1px dashed #b7c5d8;border-radius:8px;color:#66758b;cursor:pointer;display:flex;flex-direction:column;gap:7px;padding:18px}.dropzone.dragging{background:#eef5ff;border-color:#0864eb}.dropzone svg{color:#0864eb}.dropzone strong{font-size:12px}.dropzone small{font-size:10px}.dropzone em{border:1px solid #dbe3ec;border-radius:15px;color:#46556b;font-size:10px;font-style:normal;padding:5px 12px}.dropzone input{display:none}.uploaded header{display:flex;font-size:11px;justify-content:space-between;margin-bottom:7px}.uploaded header strong{color:#556277}.file-list{border:1px solid #e2e7ee;border-radius:8px;max-height:178px;overflow:auto}.file-list>div{align-items:center;border-bottom:1px solid #edf0f4;display:flex;gap:7px;padding:8px}.file-list>div:last-child{border:0}.file-list>div.duplicate{background:#fff5f5}.file-list>div>i{align-items:center;background:#f0f3f8;border-radius:4px;display:flex;font-size:10px;font-style:normal;height:19px;justify-content:center;width:19px}.file-list>div>span{min-width:0;flex:1}.file-list strong,.file-list small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.file-list strong{font-size:10px}.file-list small{color:#8e99aa;font-size:9px}.file-list small em{color:#e13e49;font-style:normal;margin-left:6px}.file-list button{background:transparent;border:0;color:#7d899a;padding:2px}.duplicate-state{align-items:center;background:#e9f8f2;border-radius:6px;color:#08a06c;display:flex;font-size:10px;gap:5px;justify-content:flex-end;padding:7px}.duplicate-state.danger{background:#fff0f1;color:#de3c48}.settings-grid{display:grid;gap:14px;grid-template-columns:1fr 1fr}.setting{background:#fcfdff;border:1px solid #e3e8ef;border-radius:8px;display:block;padding:12px}.setting>span{align-items:center}.setting>span svg{color:#1671ef;height:16px;margin-right:7px;width:16px}.setting select{background:#fff;padding:9px}.setting.wide{grid-column:1/-1}.path-input{display:flex}.path-input input{border-radius:7px 0 0 7px}.path-input button{background:#fff;border:1px solid #dce3ec;border-left:0;border-radius:0 7px 7px 0;color:#526179;padding:0 10px}.config-tip{align-items:flex-start;background:#fff8e8;border:1px solid #f7dfaa;border-radius:8px;color:#8a6720;display:flex;font-size:10px;gap:8px;margin-top:15px;padding:11px}.config-tip strong{display:block;margin-bottom:4px}.summary-box{border:1px solid #e1e7ef;border-radius:8px;padding:14px}.summary-box h3{font-size:12px;margin:0 0 11px}.summary-box h3:not(:first-child){border-top:1px solid #edf0f4;margin-top:14px;padding-top:14px}.summary-box h3 b{color:#0864eb;float:right}.summary-box dl{display:grid;grid-template-columns:1fr 1.35fr;margin:0;row-gap:9px}.summary-box dt,.summary-box dd{font-size:10px;margin:0}.summary-box dt{color:#68768a}.summary-box dd{color:#344155;overflow:hidden;text-align:right;text-overflow:ellipsis;white-space:nowrap}.summary-box dd.accent{color:#0864eb;font-size:16px;font-weight:800}.storage-bar{background:#e8edf4;border-radius:3px;height:5px}.storage-bar i{background:#1671ef;border-radius:3px;display:block;height:100%}.ready-state{align-items:center;background:#f2f4f7;border-radius:7px;color:#8a94a4;display:flex;font-size:11px;gap:6px;margin-top:15px;padding:9px}.ready-state.ready{background:#e6f8f1;color:#079e6b}.create-error{align-items:center;background:#fff0f0;border:1px solid #ffc9cd;border-radius:8px;color:#cf3641;display:flex;gap:7px;padding:10px 14px}.create-actions{align-items:center;background:#fff;border-top:1px solid #e1e6ed;bottom:0;display:flex;gap:12px;justify-content:flex-end;left:184px;padding:14px 28px;position:fixed;right:0;z-index:4}.create-actions a,.create-actions button{border:1px solid #dce3ec;border-radius:8px;font-weight:700;padding:11px 22px;text-decoration:none}.create-actions a,.draft{background:#fff;color:#48566b}.create-actions .submit{align-items:center;background:#0864eb;color:#fff;display:flex;gap:7px}.create-actions .submit:disabled{opacity:.55}@media(max-width:1400px){.create-columns{grid-template-columns:1fr 1fr}.confirm-card{grid-column:1/-1}.summary-box dl{grid-template-columns:1fr 2fr}}@media(max-width:900px){.create-columns{grid-template-columns:1fr}.confirm-card{grid-column:auto}.stepper{margin-top:22px}.stepper>span{width:40px}.create-actions{left:76px}}@media(max-width:600px){.settings-grid{grid-template-columns:1fr}.setting.wide{grid-column:auto}.stepper>span{margin:0 7px;width:14px}.stepper strong{display:none}.create-actions{left:0;padding:10px 12px}.create-actions a{display:none}}
</style>
