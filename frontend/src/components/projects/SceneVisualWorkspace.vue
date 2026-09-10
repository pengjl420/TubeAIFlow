<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { CheckCircle2, CirclePause, FolderSearch, Image, Loader2, Play, Trash2 } from 'lucide-vue-next'
import {
  clearSceneImage, enqueueSceneImageJob, enqueueScenePreviewJob, getProjectJob,
  getLocalAssetCandidates, getSceneAssets, localAssetUrl, pauseProjectJob, projectOutputUrl,
  resumeProjectJob, scanProjectAssets, selectLocalAssetCandidate, selectSceneImage,
  type LocalAssetCandidate, type ProjectTask, type SceneAssets,
} from '../../api/projects'
import type { VisualScene } from '../../types/storyboard'
import { confirmAction, showToast } from '../../services/feedback'

const props = defineProps<{ projectId: string; scene: VisualScene; previewMode?: boolean }>()
const assets = ref<SceneAssets | null>(null)
const loading = ref(false)
const operating = ref(false)
const previewPath = ref('')
const job = ref<ProjectTask | null>(null)
const sourceTab = ref<'generated' | 'local'>('generated')
const localCandidates = ref<LocalAssetCandidate[]>([])
const scanSummary = ref('')

function wait(milliseconds: number) {
  return new Promise(resolve => window.setTimeout(resolve, milliseconds))
}

async function waitForJob(initial: ProjectTask): Promise<ProjectTask> {
  let current = initial
  job.value = current
  while (current.id && ['queued', 'running'].includes(current.status)) {
    await wait(1000)
    current = await getProjectJob(props.projectId, current.id)
    job.value = current
  }
  if (current.status === 'failed') throw new Error(current.error_message || 'Job 执行失败')
  return current
}

async function load() {
  loading.value = true
  previewPath.value = ''
  try { assets.value = await getSceneAssets(props.projectId, props.scene.id) }
  catch (reason) { showToast({ title: '加载 Scene 素材失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
  finally { loading.value = false }
}

async function select(variantId: string) {
  operating.value = true
  try {
    assets.value = await selectSceneImage(props.projectId, props.scene.id, variantId)
    previewPath.value = ''
    showToast({ title: '素材已分配', description: '旧的 Scene 预览与下游成片已标记失效。', tone: 'success' })
  } catch (reason) { showToast({ title: '分配素材失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
  finally { operating.value = false }
}

async function scanAndMatch() {
  operating.value = true
  try {
    const result = await scanProjectAssets(props.projectId)
    localCandidates.value = await getLocalAssetCandidates(props.projectId, props.scene.id)
    scanSummary.value = `发现 ${result.discovered}，新增索引 ${result.indexed}，跳过 ${result.skipped}`
  } catch (reason) { showToast({ title: '本地素材索引失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
  finally { operating.value = false }
}

async function loadLocalCandidates() {
  sourceTab.value = 'local'
  operating.value = true
  try { localCandidates.value = await getLocalAssetCandidates(props.projectId, props.scene.id) }
  catch { localCandidates.value = [] }
  finally { operating.value = false }
}

async function selectLocal(candidateId: string) {
  operating.value = true
  try {
    assets.value = await selectLocalAssetCandidate(props.projectId, props.scene.id, candidateId)
    previewPath.value = ''
    showToast({ title: '本地素材已分配', description: '该 Scene 的下游渲染已标记失效。', tone: 'success' })
  } catch (reason) { showToast({ title: '分配本地素材失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
  finally { operating.value = false }
}

async function clearSelection() {
  const confirmed = await confirmAction({ title: '清除素材分配', description: 'Scene 将暂时无法预览或进入最终渲染。', confirmText: '清除分配', tone: 'warning' })
  if (!confirmed) return
  operating.value = true
  try { assets.value = await clearSceneImage(props.projectId, props.scene.id); previewPath.value = '' }
  catch (reason) { showToast({ title: '清除素材失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
  finally { operating.value = false }
}

async function renderPreview() {
  operating.value = true
  try {
    const result = await waitForJob(await enqueueScenePreviewJob(props.projectId, props.scene.id))
    previewPath.value = String(result.result?.path || '')
  } catch (reason) { showToast({ title: 'Scene Preview 失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
  finally { operating.value = false }
}

async function regenerateCandidates() {
  const confirmed = await confirmAction({ title: '重新生成图片候选', description: '现有候选和素材分配会失效，并重新运行当前 Scene 的本地图片模型。', confirmText: '重新生成', tone: 'warning' })
  if (!confirmed) return
  operating.value = true
  try {
    await waitForJob(await enqueueSceneImageJob(props.projectId, props.scene.id))
    assets.value = await getSceneAssets(props.projectId, props.scene.id)
    previewPath.value = ''
  } catch (reason) { showToast({ title: '重新生成候选失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
  finally { operating.value = false }
}

async function pauseJob() {
  if (!job.value?.id) return
  job.value = await pauseProjectJob(props.projectId, job.value.id)
}

async function resumeJob() {
  if (!job.value?.id) return
  operating.value = true
  try {
    const result = await waitForJob(await resumeProjectJob(props.projectId, job.value.id))
    if (result.status === 'completed' && result.job_type === 'scene_preview_render') {
      previewPath.value = String(result.result?.path || '')
    }
    assets.value = await getSceneAssets(props.projectId, props.scene.id)
  } catch (reason) { showToast({ title: '恢复 Job 失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
  finally { operating.value = false }
}

watch(() => props.scene.id, () => { localCandidates.value = []; scanSummary.value = ''; sourceTab.value = 'generated'; void load() })
onMounted(load)
</script>

<template>
  <main class="visual-workspace">
    <header><div><h1>Scene {{ scene.scene_index }} · {{ previewMode ? '预览' : '素材审阅' }}</h1><p>{{ scene.storyboard?.visual_summary }}</p></div><div class="header-actions"><button v-if="!previewMode" :disabled="operating || scene.locked_visual" @click="regenerateCandidates">重新生成候选</button><button v-if="assets?.assignments.length" class="clear" :disabled="operating" @click="clearSelection"><Trash2 :size="13" />清除分配</button></div></header>
    <div v-if="job && ['queued', 'running', 'paused'].includes(job.status)" class="job-status"><Loader2 v-if="job.status !== 'paused'" class="spin" :size="15" /><CirclePause v-else :size="15" /><span>{{ job.status === 'queued' ? 'Job 排队中' : job.status === 'paused' ? 'Job 已暂停' : `正在执行 ${job.stage}` }}</span><b>{{ Math.round(job.progress || 0) }}%</b><button v-if="job.status === 'paused'" @click="resumeJob">继续</button><button v-else @click="pauseJob">暂停</button></div>
    <div v-if="loading" class="empty"><Loader2 class="spin" :size="24" />加载素材…</div>
    <template v-else-if="previewMode">
      <video v-if="previewPath" controls autoplay :src="projectOutputUrl(projectId, previewPath)" />
      <div v-else class="preview-empty"><Play :size="30" /><strong>生成当前 Scene 的低范围预览</strong><span>只渲染当前 Scene，不会重新合成完整视频。</span><button :disabled="operating || !assets?.coverage.complete" @click="renderPreview">{{ operating ? '渲染中…' : '生成 Scene Preview' }}</button><small v-if="!assets?.coverage.complete">请先为 Scene 选择可覆盖完整时长的素材</small></div>
    </template>
    <template v-else>
      <nav class="source-tabs"><button :class="{ active: sourceTab === 'generated' }" @click="sourceTab = 'generated'">AI 图片</button><button :class="{ active: sourceTab === 'local' }" @click="loadLocalCandidates">本地素材</button></nav>
      <template v-if="sourceTab === 'generated'"><div v-if="assets?.variants.length" class="candidate-grid"><article v-for="variant in assets.variants" :key="variant.id" :class="{ selected: variant.selected }"><div class="image-wrap"><img v-if="variant.status === 'completed'" :src="projectOutputUrl(projectId, variant.path)" :alt="`候选 ${variant.variant_index}`" /><div v-else><Image :size="24" />{{ variant.status }}</div><span v-if="variant.selected"><CheckCircle2 :size="14" />已选</span></div><div><strong>候选 {{ variant.variant_index }}</strong><small>{{ variant.width }}×{{ variant.height }} · Seed {{ variant.seed }}</small><p>{{ variant.prompt }}</p><button :disabled="operating || variant.status !== 'completed' || variant.selected" @click="select(variant.id)">{{ variant.selected ? '当前素材' : '使用此素材' }}</button></div></article></div><div v-else class="empty"><Image :size="30" /><strong>暂无图片候选</strong><span>运行视觉生成阶段后，可在这里比较并人工选择素材。</span></div></template>
      <template v-else><div class="local-toolbar"><div><strong>Scene 语义匹配</strong><small>{{ scanSummary || '按文件名、标签、画面规格与项目内重复情况排序' }}</small></div><button :disabled="operating || scene.locked_visual" @click="scanAndMatch"><FolderSearch :size="14" />扫描并匹配</button></div><div v-if="localCandidates.length" class="candidate-grid local-grid"><article v-for="candidate in localCandidates" :key="candidate.id"><div class="image-wrap"><img v-if="candidate.media_type === 'image'" :src="localAssetUrl(projectId, candidate.path)" :alt="candidate.filename" /><video v-else muted preload="metadata" :src="localAssetUrl(projectId, candidate.path)" /><span>{{ Math.round(candidate.score * 100) }}% · {{ candidate.status }}</span></div><div><strong>{{ candidate.filename }}</strong><small>{{ candidate.width || '—' }}×{{ candidate.height || '—' }}<template v-if="candidate.duration_ms"> · {{ (candidate.duration_ms / 1000).toFixed(1) }} 秒</template></small><p>{{ candidate.description }}<template v-if="candidate.conflicts.length"> · 已在本项目使用</template></p><button :disabled="operating || scene.locked_visual" @click="selectLocal(candidate.id)">使用此素材</button></div></article></div><div v-else class="empty"><FolderSearch :size="30" /><strong>暂无本地素材候选</strong><span>在项目设置中配置素材目录，然后扫描建立本地索引。</span><button :disabled="operating || scene.locked_visual" @click="scanAndMatch">扫描素材目录</button></div></template>
    </template>
  </main>
</template>

<style scoped>
.visual-workspace{min-width:0}.visual-workspace>header{align-items:flex-start;display:flex;justify-content:space-between;margin-bottom:14px}.visual-workspace h1{font-size:18px;margin:0}.visual-workspace header p{color:#7b8799;font-size:11px;margin:5px 0;max-width:650px}.visual-workspace button{align-items:center;background:#075bf5;border-radius:7px;color:#fff;display:flex;font-size:11px;font-weight:700;gap:5px;padding:8px 11px}.visual-workspace button:disabled{opacity:.5}.visual-workspace .clear{background:#fff;border:1px solid #dce3ec;color:#657187}.candidate-grid{display:grid;gap:12px;grid-template-columns:repeat(2,minmax(0,1fr))}.candidate-grid article{border:1px solid #e0e6ee;border-radius:9px;overflow:hidden}.candidate-grid article.selected{border-color:#4c91f2;box-shadow:0 0 0 2px rgba(7,91,245,.1)}.image-wrap{aspect-ratio:16/9;background:#eef1f5;position:relative}.image-wrap img{height:100%;object-fit:cover;width:100%}.image-wrap>div{align-items:center;color:#8792a4;display:flex;height:100%;justify-content:center}.image-wrap>span{align-items:center;background:#075bf5;border-radius:12px;color:#fff;display:flex;font-size:10px;gap:3px;padding:4px 7px;position:absolute;right:7px;top:7px}.candidate-grid article>div:last-child{padding:10px}.candidate-grid strong,.candidate-grid small{display:block}.candidate-grid small{color:#8792a4;font-size:9px;margin-top:3px}.candidate-grid p{color:#5d697d;display:-webkit-box;font-size:10px;line-height:1.5;overflow:hidden;-webkit-box-orient:vertical;-webkit-line-clamp:3}.empty,.preview-empty{align-items:center;color:#8490a3;display:flex;flex-direction:column;gap:8px;justify-content:center;min-height:360px;text-align:center}.empty strong,.preview-empty strong{color:#536078}.preview-empty span,.preview-empty small,.empty span{font-size:11px}.visual-workspace video{background:#111;border-radius:9px;max-height:480px;width:100%}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:720px){.candidate-grid{grid-template-columns:1fr}}
</style>

<style scoped>
.header-actions{display:flex;gap:7px}
.source-tabs{display:flex;gap:5px;margin-bottom:12px}.source-tabs button{background:#eef2f7;color:#617087}.source-tabs button.active{background:#075bf5;color:#fff}.local-toolbar{align-items:center;background:#f5f8fc;border-radius:8px;display:flex;justify-content:space-between;margin-bottom:12px;padding:9px 11px}.local-toolbar>div{display:grid}.local-toolbar strong{font-size:11px}.local-toolbar small{color:#8490a3;font-size:9px;margin-top:2px}.local-grid video{height:100%;object-fit:cover;width:100%}
.job-status{align-items:center;background:#172033;border-radius:8px;color:#fff;display:flex;font-size:11px;gap:8px;margin-bottom:12px;padding:9px 11px}.job-status span{flex:1}.job-status b{font-size:10px}.job-status button{background:#fff;color:#26354d;padding:5px 8px}
</style>
