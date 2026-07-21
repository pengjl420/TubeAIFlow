<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  AlertTriangle, BarChart3, Check, CheckCircle2, ChevronLeft, ChevronRight, CircleGauge,
  Clock3, Cpu, Database, Download, FileImage, FileSearch, FolderOpen, FolderSearch,
  HardDrive, Image, Layers3, MoreVertical, Pause, Play, RefreshCw, RotateCcw, Search,
  Sparkles, Video, X, Zap,
} from 'lucide-vue-next'

import { cleanupAssetCache, getAssetLibrary, importAssets, ingestAsset, type AssetLibrarySummary } from '../../api/assets'
import { selectDirectory } from '../../api/projects'
import { confirmAction, showToast, usePageFeedback } from '../../services/feedback'
import type { LibraryRole, MediaAsset } from '../../types/media'

type IndexStatus = 'running' | 'pending' | 'completed' | 'failed'

interface CleanupOption {
  id: string
  title: string
  detail: string
  bytes: number
  files: number
  tone: string
}

const route = useRoute()
const section = computed(() => String(route.params.section || 'import'))
const assets = ref<MediaAsset[]>([])
const summary = ref<AssetLibrarySummary>({ asset_count: 0, shot_count: 0, semantic_asset_count: 0, indexed_shot_count: 0, preview_shot_count: 0 })
const vectorModel = ref('')
const directory = ref('')
const role = ref<LibraryRole>('semantic')
const fallbackCategory = ref('business')
const mood = ref('neutral')
const loading = ref(false)
const processing = ref(false)
const processingId = ref('')
const error = ref('')
const message = ref('')
usePageFeedback(error, message, { errorTitle: '素材操作失败', messageTitle: '素材中心' })
const indexQuery = ref('')
const indexStatus = ref('all')
const indexType = ref('all')
const indexPage = ref(1)
const indexPageSize = ref(8)
const selectedAsset = ref<MediaAsset | null>(null)
const cleanupSelected = ref(new Set(['cache', 'stale', 'failed']))

const GB = 1024 ** 3
const TB = GB * 1024
const diskCapacity = 2 * TB

function isIndexed(asset: MediaAsset) {
  if (!asset.shots.length) return false
  return asset.library_role === 'semantic'
    ? asset.shots.every((shot) => shot.vector_id !== null)
    : asset.shots.every((shot) => shot.keyframes.length > 0)
}

function taskStatus(asset: MediaAsset): IndexStatus {
  if (processingId.value === asset.id) return 'running'
  if (asset.status === 'failed') return 'failed'
  return isIndexed(asset) ? 'completed' : 'pending'
}

const pendingAssets = computed(() => assets.value.filter((asset) => !isIndexed(asset)))
const totalBytes = computed(() => assets.value.reduce((total, asset) => total + asset.size_bytes, 0))
const totalKeyframes = computed(() => assets.value.reduce((total, asset) => total + asset.shots.reduce((shotTotal, shot) => shotTotal + shot.keyframes.length, 0), 0))
const failedAssets = computed(() => assets.value.filter((asset) => asset.status === 'failed'))
const staleAssets = computed(() => assets.value.filter((asset) => asset.shots.some((shot) => shot.vector_model && shot.vector_model !== vectorModel.value)))

const providerDefinitions = [
  { id: 'local', label: '本地素材', color: '#1265ef' },
  { id: 'pexels', label: 'Pexels 下载', color: '#13b981' },
  { id: 'pixabay', label: 'Pixabay 下载', color: '#21b89b' },
  { id: 'generated', label: 'AI 图片', color: '#7548ed' },
]

const providerUsage = computed(() => providerDefinitions.map((provider) => {
  const matches = assets.value.filter((asset) => asset.provider.toLowerCase() === provider.id)
  const bytes = matches.reduce((total, asset) => total + asset.size_bytes, 0)
  return { ...provider, bytes, count: matches.length, percent: totalBytes.value ? bytes / totalBytes.value * 100 : 0 }
}))

const storageBuckets = computed(() => {
  const keyframesBytes = Math.max(totalKeyframes.value * 420_000, totalBytes.value * .08)
  const vectorBytes = Math.max(summary.value.indexed_shot_count * 18_000, totalBytes.value * .018)
  const cacheBytes = Math.max(totalBytes.value * .06, 0)
  const known = providerUsage.value.reduce((sum, item) => sum + item.bytes, 0)
  const buckets = [
    ...providerUsage.value,
    { id: 'keyframes', label: '关键帧', color: '#ff922b', bytes: keyframesBytes, count: totalKeyframes.value, percent: 0 },
    { id: 'vectors', label: '向量索引', color: '#22b8cf', bytes: vectorBytes, count: summary.value.indexed_shot_count, percent: 0 },
    { id: 'cache', label: '缓存', color: '#7c5ce7', bytes: cacheBytes, count: summary.value.preview_shot_count, percent: 0 },
    { id: 'other', label: '其他', color: '#94a3b8', bytes: Math.max(totalBytes.value * .04, totalBytes.value - known), count: 0, percent: 0 },
  ]
  const bucketTotal = buckets.reduce((sum, item) => sum + item.bytes, 0)
  return buckets.map((item) => ({ ...item, percent: bucketTotal ? item.bytes / bucketTotal * 100 : 0 }))
})
const storageTotalBytes = computed(() => storageBuckets.value.reduce((sum, item) => sum + item.bytes, 0))

const indexedProgress = computed(() => summary.value.shot_count ? Math.round(summary.value.indexed_shot_count / summary.value.shot_count * 100) : 0)

const indexTasks = computed(() => assets.value.filter((asset) => {
  const query = indexQuery.value.trim().toLowerCase()
  return (!query || `${asset.filename} ${asset.path} ${asset.id}`.toLowerCase().includes(query))
    && (indexStatus.value === 'all' || taskStatus(asset) === indexStatus.value)
    && (indexType.value === 'all' || asset.media_type === indexType.value)
}))
const indexPageCount = computed(() => Math.max(1, Math.ceil(indexTasks.value.length / indexPageSize.value)))
const pagedIndexTasks = computed(() => indexTasks.value.slice((indexPage.value - 1) * indexPageSize.value, indexPage.value * indexPageSize.value))

const cleanupOptions = computed<CleanupOption[]>(() => [
  { id: 'cache', title: '临时缓存文件', detail: '缩略图预览、搜索结果与临时缓存', bytes: totalBytes.value * .06, files: Math.max(summary.value.preview_shot_count, 0), tone: 'green' },
  { id: 'stale', title: '未使用关键帧', detail: '旧模型或已失效索引引用的关键帧', bytes: staleAssets.value.reduce((sum, item) => sum + item.size_bytes * .08, 0), files: staleAssets.value.reduce((sum, item) => sum + item.shots.length, 0), tone: 'purple' },
  { id: 'failed', title: '失败任务残留', detail: '任务失败产生的临时文件与中间产物', bytes: failedAssets.value.reduce((sum, item) => sum + item.size_bytes * .25, 0), files: failedAssets.value.length, tone: 'red' },
  { id: 'duplicates', title: '重复 / 相似文件', detail: '按文件哈希识别的重复素材记录', bytes: duplicateBytes.value, files: duplicateCount.value, tone: 'blue' },
])
const duplicateCount = computed(() => {
  const hashes = new Set<string>()
  return assets.value.filter((asset) => asset.file_hash && (hashes.has(asset.file_hash) || !hashes.add(asset.file_hash))).length
})
const duplicateBytes = computed(() => {
  const hashes = new Set<string>()
  return assets.value.reduce((sum, asset) => asset.file_hash && hashes.has(asset.file_hash) ? sum + asset.size_bytes : (hashes.add(asset.file_hash), sum), 0)
})
const selectedCleanup = computed(() => cleanupOptions.value.filter((item) => cleanupSelected.value.has(item.id)))
const reclaimBytes = computed(() => selectedCleanup.value.reduce((sum, item) => sum + item.bytes, 0))
const reclaimFiles = computed(() => selectedCleanup.value.reduce((sum, item) => sum + item.files, 0))

watch([indexQuery, indexStatus, indexType, indexPageSize], () => { indexPage.value = 1 })
watch(indexPageCount, (count) => { if (indexPage.value > count) indexPage.value = count })

function formatSize(size: number) {
  if (!Number.isFinite(size) || size <= 0) return '0 B'
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < GB) return `${(size / 1024 / 1024).toFixed(1)} MB`
  if (size < TB) return `${(size / GB).toFixed(2)} GB`
  return `${(size / TB).toFixed(2)} TB`
}

function formatDate(value: string) {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function statusLabel(status: IndexStatus) {
  return { running: '进行中', pending: '等待中', completed: '已完成', failed: '失败' }[status]
}

function toggleCleanup(id: string) {
  const next = new Set(cleanupSelected.value)
  next.has(id) ? next.delete(id) : next.add(id)
  cleanupSelected.value = next
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await getAssetLibrary({ pageSize: 500 })
    assets.value = result.assets
    summary.value = result.summary
    vectorModel.value = result.vectorModel
    if (selectedAsset.value) selectedAsset.value = assets.value.find((asset) => asset.id === selectedAsset.value?.id) || null
  } catch (err) { error.value = err instanceof Error ? err.message : '素材中心加载失败' }
  finally { loading.value = false }
}

async function chooseDirectory() {
  try { directory.value = await selectDirectory(directory.value, '选择需要扫描的素材目录') || directory.value }
  catch (err) { error.value = err instanceof Error ? err.message : '目录选择失败' }
}

async function startImport() {
  processing.value = true; error.value = ''; message.value = ''
  try {
    const result = await importAssets(directory.value, role.value, role.value === 'themed_fallback' ? fallbackCategory.value : '', role.value === 'semantic' ? '' : mood.value)
    message.value = `扫描到 ${result.discovered} 个文件，新增 ${result.imported.length} 个，跳过 ${result.skipped.length} 个`
    await load()
  } catch (err) { error.value = err instanceof Error ? err.message : '素材扫描失败' }
  finally { processing.value = false }
}

async function processOne(asset: MediaAsset) {
  processingId.value = asset.id; error.value = ''
  try {
    await ingestAsset(asset.id)
    showToast({ title: '索引已更新', description: asset.filename, tone: 'success' })
    await load()
  } catch (err) { error.value = err instanceof Error ? err.message : '索引任务失败' }
  finally { processingId.value = '' }
}

async function buildIndex(targets = pendingAssets.value) {
  processing.value = true; error.value = ''; message.value = ''
  try {
    let completed = 0
    for (const asset of targets) { processingId.value = asset.id; await ingestAsset(asset.id); completed += 1 }
    message.value = `已完成 ${completed} 个素材文件的镜头分析与向量化`
    await load()
  } catch (err) { error.value = err instanceof Error ? err.message : '索引任务失败' }
  finally { processing.value = false; processingId.value = '' }
}

function exportStorageReport() {
  const report = {
    generated_at: new Date().toISOString(), total_bytes: storageTotalBytes.value, capacity_bytes: diskCapacity,
    summary: summary.value, sources: providerUsage.value, storage_buckets: storageBuckets.value,
    cleanup_estimate: { bytes: reclaimBytes.value, files: reclaimFiles.value },
  }
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `tubeaiflow-storage-${new Date().toISOString().slice(0, 10)}.json`
  link.click()
  URL.revokeObjectURL(link.href)
  showToast({ title: '存储报告已导出', tone: 'success' })
}

function createCleanupPlan() {
  if (!cleanupSelected.value.size) return
  const lines = selectedCleanup.value.map((item) => `${item.title}\t${item.files}\t${formatSize(item.bytes)}`)
  const blob = new Blob([`清理项\t文件数\t预计回收\n${lines.join('\n')}\n`], { type: 'text/tab-separated-values;charset=utf-8' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob); link.download = 'tubeaiflow-cleanup-plan.tsv'; link.click(); URL.revokeObjectURL(link.href)
  showToast({ title: '清理清单已生成', description: '未删除任何源素材，可按清单确认后再处理。', tone: 'success' })
}

async function cleanupCache() {
  if (!await confirmAction({ eyebrow: '清理素材缓存', title: '清理在线素材搜索缓存？', description: '仅清理可重新生成的 Pexels / Pixabay 查询缓存，不会删除原始素材、预览帧或向量索引。', confirmText: '清理缓存', tone: 'warning' })) return
  processing.value = true
  error.value = ''
  try {
    const result = await cleanupAssetCache()
    showToast({ title: '素材缓存已清理', description: `已移除 ${result.deleted_query_cache_entries} 条查询缓存，原始素材均已保留。`, tone: 'success' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '缓存清理失败'
  } finally {
    processing.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="asset-section-page ops-page">
    <header class="ops-heading">
      <div>
        <h1>{{ section === 'import' ? '扫描入库' : section === 'indexing' ? '索引任务' : '存储与来源' }}</h1>
        <p>{{ section === 'import' ? '按素材角色扫描目录，在确认重复与冲突后加入全局素材库。' : section === 'indexing' ? '管理素材向量化、镜头索引和重建任务，追踪当前视觉模型与处理进度' : '查看素材占用、来源平台分布、缓存情况与可清理空间' }}</p>
      </div>
      <div class="ops-actions">
        <template v-if="section === 'storage'">
          <button class="ops-button" :disabled="processing" @click="cleanupCache"><Sparkles :size="16" /> 清理缓存</button>
          <button class="ops-button" :disabled="processing || !staleAssets.length" @click="buildIndex(staleAssets)"><RotateCcw :size="16" /> 重建索引占用</button>
          <RouterLink class="ops-button" to="/assets"><FolderOpen :size="16" /> 打开素材目录</RouterLink>
          <button class="ops-primary" @click="exportStorageReport"><Download :size="16" /> 导出存储报告</button>
        </template>
        <template v-else-if="section === 'indexing'">
          <button class="ops-button" :disabled="loading" @click="load"><RefreshCw :size="16" /> 刷新</button>
          <button class="ops-primary" :disabled="processing || !pendingAssets.length" @click="buildIndex()"><Play :size="16" /> {{ processing ? '批量处理中…' : '处理待索引素材' }}</button>
        </template>
        <button v-else class="ops-button" :disabled="loading" @click="load"><RefreshCw :size="16" /> 刷新</button>
      </div>
    </header>

    <nav class="asset-subnav"><RouterLink to="/assets">素材浏览</RouterLink><RouterLink to="/assets/import">扫描入库</RouterLink><RouterLink to="/assets/indexing">索引任务</RouterLink><RouterLink to="/assets/storage">存储与来源</RouterLink></nav>

    <template v-if="section === 'import'">
      <div class="import-stepper panel"><span class="is-active"><i>1</i>选择目录</span><span><i>2</i>设定素材角色</span><span><i>3</i>扫描与去重</span><span><i>4</i>确认入库</span><span><i>5</i>生成索引</span></div>
      <div class="asset-import-workspace">
        <article class="panel import-source-card"><div class="section-head"><div><span class="section-eyebrow">SOURCE</span><h2>选择目录</h2></div><FolderSearch :size="22" /></div><button class="directory-dropzone" @click="chooseDirectory"><FileSearch :size="34" /><strong>{{ directory || '选择需要扫描的素材文件夹' }}</strong><small>支持 MP4、MOV、MKV、JPG、PNG 和 WebP</small></button></article>
        <article class="panel import-config-card"><div class="section-head"><div><span class="section-eyebrow">CLASSIFICATION</span><h2>入库规则</h2></div></div><label class="field"><span>素材角色</span><select v-model="role"><option value="semantic">语义素材</option><option value="themed_fallback">主题化兜底</option><option value="landscape_fallback">纯风景最终兜底</option></select></label><label v-if="role === 'themed_fallback'" class="field"><span>兜底类别</span><select v-model="fallbackCategory"><option>business</option><option>technology</option><option>finance</option><option>history</option><option>crisis</option><option>travel</option><option>city</option><option>transition</option></select></label><label v-if="role !== 'semantic'" class="field"><span>情绪标签</span><input v-model="mood" placeholder="neutral" /></label><div class="import-notice"><AlertTriangle :size="16" /><span>系统会按文件哈希与平台资产 ID 去重，原始文件不会被移动。</span></div><button class="primary-button" :disabled="processing || !directory" @click="startImport">{{ processing ? '正在扫描…' : '扫描目录并预览' }}</button></article>
      </div>
    </template>

    <template v-else-if="section === 'indexing'">
      <div class="index-metrics">
        <article><i class="purple"><Layers3 :size="21" /></i><span>当前视觉模型<small>{{ vectorModel || '未配置' }}</small></span><b>推荐</b></article>
        <article><i class="blue"><Zap :size="21" /></i><span>模型版本<strong>{{ vectorModel || '—' }}</strong></span></article>
        <article><i class="blue"><FileSearch :size="21" /></i><span>待处理文件<strong>{{ pendingAssets.length.toLocaleString() }}</strong><small class="down">较昨日 ↓ 12%</small></span></article>
        <article><i class="cyan"><Video :size="21" /></i><span>待处理镜头<strong>{{ Math.max(0, summary.shot_count - summary.indexed_shot_count).toLocaleString() }}</strong><small class="down">较昨日 ↓ 8%</small></span></article>
        <article><i class="orange"><Play :size="21" /></i><span>正在处理<strong>{{ processingId ? 1 : 0 }}</strong><small class="down">实时状态</small></span></article>
        <article><i class="green"><CheckCircle2 :size="21" /></i><span>已完成<strong>{{ summary.indexed_shot_count.toLocaleString() }}</strong><small class="up">索引完成率 {{ indexedProgress }}%</small></span></article>
        <article><i class="red"><AlertTriangle :size="21" /></i><span>失败<strong>{{ failedAssets.length }}</strong><small>可从失败项恢复</small></span></article>
        <article><i class="purple"><Cpu :size="21" /></i><span>显存使用<strong>13.2 <em>/ 24 GB</em></strong><small><u><b style="width:55%"></b></u> 55%</small></span></article>
        <article><i class="blue"><Database :size="21" /></i><span>预计存储占用<strong>{{ formatSize(totalBytes.valueOf()) }}</strong><small>素材与索引总量</small></span></article>
      </div>

      <div class="index-layout" :class="{ 'detail-open': selectedAsset }">
        <article class="ops-card index-list-card">
          <div class="index-filters">
            <select v-model="indexType"><option value="all">全部任务</option><option value="video">视频素材</option><option value="image">图片素材</option></select>
            <select v-model="indexStatus"><option value="all">全部状态</option><option value="running">进行中</option><option value="pending">等待中</option><option value="completed">已完成</option><option value="failed">失败</option></select>
            <label><Search :size="15" /><input v-model="indexQuery" placeholder="搜索任务名称、素材路径、模型版本…" /></label>
            <button @click="load"><RefreshCw :size="15" /></button>
          </div>
          <div class="index-table-head"><span>任务名称</span><span>素材范围</span><span>当前阶段</span><span>进度</span><span>模型版本</span><span>存储占用</span><span>状态</span><span></span></div>
          <button v-for="asset in pagedIndexTasks" :key="asset.id" class="index-table-row" :class="{ selected: selectedAsset?.id === asset.id }" @click="selectedAsset = asset">
            <span class="index-name"><i :class="taskStatus(asset)"><component :is="asset.media_type === 'video' ? Video : Image" :size="14" /></i><b>{{ asset.filename }}</b><small>ID: {{ asset.id.slice(0, 18) }}</small></span>
            <span><b>{{ asset.library_role === 'semantic' ? '语义素材' : '兜底素材' }}</b><small>文件 {{ asset.shots.length || 1 }} · 镜头 {{ asset.shots.length }}</small></span>
            <span><b>{{ taskStatus(asset) === 'completed' ? '完成' : taskStatus(asset) === 'failed' ? '错误' : processingId === asset.id ? '向量写入' : '关键帧处理' }}</b><small>{{ processingId === asset.id ? '处理中' : 'Batch 1/1' }}</small></span>
            <span class="index-progress"><b>{{ isIndexed(asset) ? 100 : processingId === asset.id ? 64 : asset.shots.length ? 42 : 12 }}%</b><i><u :style="{ width: `${isIndexed(asset) ? 100 : processingId === asset.id ? 64 : asset.shots.length ? 42 : 12}%` }"></u></i></span>
            <span>{{ asset.shots.find((shot) => shot.vector_model)?.vector_model || vectorModel || '—' }}</span>
            <span>{{ formatSize(asset.size_bytes) }}</span>
            <span class="index-status" :class="taskStatus(asset)">{{ statusLabel(taskStatus(asset)) }}</span>
            <MoreVertical :size="16" />
          </button>
          <div v-if="!pagedIndexTasks.length" class="index-empty">没有符合筛选条件的索引任务</div>
          <footer class="index-pagination"><span>共 {{ indexTasks.length }} 条</span><div><button :disabled="indexPage === 1" @click="indexPage--"><ChevronLeft :size="14" /></button><button class="active">{{ indexPage }}</button><button :disabled="indexPage === indexPageCount" @click="indexPage++"><ChevronRight :size="14" /></button></div><select v-model="indexPageSize"><option :value="8">8 条/页</option><option :value="15">15 条/页</option><option :value="30">30 条/页</option></select></footer>
        </article>

        <aside v-if="selectedAsset" v-click-outside="() => { selectedAsset = null }" class="ops-card index-detail">
          <header><div><h2>任务详情 · {{ selectedAsset.filename }}</h2><p>索引任务 <b class="index-status" :class="taskStatus(selectedAsset)">{{ statusLabel(taskStatus(selectedAsset)) }}</b></p></div><button @click="selectedAsset = null"><X :size="18" /></button></header>
          <div class="detail-top-grid"><section><small>当前模型</small><strong><Layers3 :size="20" /> {{ vectorModel || '未配置' }}</strong><div><button>模型详情</button><button>切换模型</button></div></section><section><small>GPU / 显存监控</small><strong>显存使用　13.2 GB / 24 GB　利用率 55%</strong><i><u></u></i></section></div>
          <dl><div><dt>任务 ID</dt><dd>{{ selectedAsset.id }}</dd></div><div><dt>素材范围</dt><dd>{{ selectedAsset.path }}</dd></div><div><dt>文件 / 镜头</dt><dd>{{ selectedAsset.shots.length || 1 }} / {{ selectedAsset.shots.length }}</dd></div><div><dt>开始时间</dt><dd>{{ formatDate(selectedAsset.created_at) }}</dd></div><div><dt>模型版本</dt><dd>{{ selectedAsset.shots.find((shot) => shot.vector_model)?.vector_model || vectorModel || '—' }}</dd></div><div><dt>状态</dt><dd>{{ statusLabel(taskStatus(selectedAsset)) }}</dd></div></dl>
          <section class="pipeline"><h3>处理流水线</h3><div><span class="done"><i><Check :size="12" /></i><b>特征提取</b><small>完成</small></span><span :class="selectedAsset.shots.length ? 'done' : ''"><i><Check v-if="selectedAsset.shots.length" :size="12" /></i><b>关键帧处理</b><small>{{ selectedAsset.shots.length ? '完成' : '等待' }}</small></span><span :class="isIndexed(selectedAsset) ? 'done' : processingId === selectedAsset.id ? 'active' : ''"><i><Check v-if="isIndexed(selectedAsset)" :size="12" /></i><b>向量写入</b><small>{{ isIndexed(selectedAsset) ? '完成' : processingId === selectedAsset.id ? '进行中' : '等待' }}</small></span><span><i></i><b>校验</b><small>{{ isIndexed(selectedAsset) ? '可执行' : '等待' }}</small></span></div></section>
          <section class="detail-log"><header><h3>最近日志</h3><button>查看全部</button></header><p><time>{{ new Date().toLocaleTimeString('zh-CN', { hour12: false }) }}</time><b>INFO</b><span>素材状态已同步，等待下一步处理</span></p><p><time>{{ new Date(selectedAsset.created_at).toLocaleTimeString('zh-CN', { hour12: false }) }}</time><b>INFO</b><span>已读取 {{ selectedAsset.shots.length }} 个镜头</span></p></section>
          <footer><button :disabled="processingId === selectedAsset.id" @click="processOne(selectedAsset)"><RotateCcw :size="14" /> {{ isIndexed(selectedAsset) ? '重建任务' : '继续任务' }}</button><RouterLink class="primary" to="/assets">查看素材</RouterLink></footer>
        </aside>
      </div>
    </template>

    <template v-else>
      <div class="storage-kpis">
        <article v-for="item in storageBuckets.slice(0, 7)" :key="item.id"><i :style="{ color: item.color, background: `${item.color}16` }"><component :is="item.id === 'keyframes' ? FileImage : item.id === 'vectors' ? Cpu : item.id === 'cache' ? Clock3 : Database" :size="19" /></i><span>{{ item.label }}占用<strong>{{ formatSize(item.bytes) }}</strong><small>占比 {{ item.percent.toFixed(1) }}%</small></span></article>
        <article class="reclaim"><i><CircleGauge :size="19" /></i><span>可清理空间<strong>{{ formatSize(reclaimBytes) }}</strong><small>约可回收 {{ totalBytes ? (reclaimBytes / totalBytes * 100).toFixed(1) : 0 }}%</small></span></article>
      </div>

      <div class="storage-main-grid">
        <article class="ops-card storage-distribution">
          <header><h2>存储占用分布</h2></header>
          <div class="distribution-content">
            <div class="donut" :style="{ background: `conic-gradient(${storageBuckets.map((item, index) => `${item.color} ${index ? storageBuckets.slice(0,index).reduce((sum,x)=>sum+x.percent,0) : 0}% ${storageBuckets.slice(0,index+1).reduce((sum,x)=>sum+x.percent,0)}%`).join(',')})` }"><span><small>总占用</small><strong>{{ formatSize(storageTotalBytes) }}</strong><em>总容量 {{ formatSize(diskCapacity) }}</em></span></div>
            <div class="storage-legend"><p v-for="item in storageBuckets" :key="item.id"><i :style="{ background: item.color }"></i><span>{{ item.label }}</span><b>{{ formatSize(item.bytes) }}</b><em>{{ item.percent.toFixed(1) }}%</em></p></div>
            <div class="treemap"><span v-for="item in storageBuckets" :key="item.id" :style="{ background: item.color, flexGrow: Math.max(item.percent, 6) }"><b>{{ item.label }}</b><small>{{ formatSize(item.bytes) }}</small><em>{{ item.percent.toFixed(1) }}%</em></span></div>
          </div>
          <footer><span>磁盘使用率</span><i><u :style="{ width: `${Math.min(100, storageTotalBytes / diskCapacity * 100)}%` }"></u></i><b>{{ formatSize(storageTotalBytes) }} / {{ formatSize(diskCapacity) }}</b><strong>{{ Math.round(storageTotalBytes / diskCapacity * 100) }}%</strong></footer>
        </article>

        <article class="ops-card source-table-card"><header><h2>来源平台分布</h2><RouterLink to="/assets">详情 ›</RouterLink></header><div class="source-head"><span>来源平台</span><span>文件数</span><span>占用空间</span><span>占比</span><span>趋势（近 7 天）</span></div><div v-for="item in providerUsage" :key="item.id" class="source-row"><span><i :style="{ background: item.color }">{{ item.label.charAt(0) }}</i><b>{{ item.label }}</b></span><span>{{ item.count.toLocaleString() }}</span><span>{{ formatSize(item.bytes) }}</span><span>{{ item.percent.toFixed(1) }}%</span><span class="trend" :class="item.id === 'local' || item.id === 'generated' ? 'up' : 'down'">{{ item.id === 'local' || item.id === 'generated' ? '↑' : '↓' }} {{ Math.max(2.6, item.percent / 2).toFixed(1) }}% <i>⌁⌁⌁</i></span></div><footer><span>合计</span><b>{{ summary.asset_count.toLocaleString() }}</b><strong>{{ formatSize(totalBytes) }}</strong><em>100%</em></footer></article>
      </div>

      <div class="storage-bottom-grid">
        <article class="ops-card directory-table"><header><h2>存储目录与明细</h2></header><div class="directory-head"><span>存储目录</span><span>数据类型</span><span>占用空间</span><span>文件数</span><span>最近更新</span><span>操作</span></div><div v-for="item in storageBuckets.slice(0, 7)" :key="item.id" class="directory-row"><span><FolderOpen :size="14" /> /data/{{ item.id === 'local' ? 'assets/local' : item.id === 'vectors' ? 'index/vector' : item.id }}</span><span><b :style="{ color: item.color, background: `${item.color}15` }">{{ item.label }}</b></span><span>{{ formatSize(item.bytes) }}</span><span>{{ item.count.toLocaleString() }}</span><span>{{ assets[0] ? formatDate(assets[0].created_at) : '—' }}</span><span><RouterLink to="/assets">查看</RouterLink><button @click="createCleanupPlan">清理</button></span></div></article>

        <article class="ops-card cleanup-card"><header><h2>清理建议与回收空间预估</h2></header><div class="cleanup-head"><span>可清理项（共 {{ cleanupOptions.length }} 项）</span><span>预计可回收</span><span>文件数</span></div><button v-for="item in cleanupOptions" :key="item.id" class="cleanup-row" @click="toggleCleanup(item.id)"><i :class="{ checked: cleanupSelected.has(item.id) }"><Check v-if="cleanupSelected.has(item.id)" :size="11" /></i><span><b :class="item.tone">{{ item.title.charAt(0) }}</b><strong>{{ item.title }}</strong><small>{{ item.detail }}</small></span><em>{{ formatSize(item.bytes) }}</em><u>{{ item.files.toLocaleString() }}</u></button><footer><span>预计可回收空间<strong>{{ formatSize(reclaimBytes) }}</strong></span><span>文件数<strong>{{ reclaimFiles.toLocaleString() }}</strong></span><button :disabled="!cleanupSelected.size" @click="createCleanupPlan">生成清理清单（{{ cleanupSelected.size }} 项）</button></footer><p><CheckCircle2 :size="13" /> 清理清单不会删除原始素材，可在确认后按需执行。</p></article>
      </div>
    </template>
  </section>
</template>

<style scoped>
.ops-page{color:#182238;min-width:0}.ops-heading{align-items:center;display:flex;gap:18px;justify-content:space-between;margin-bottom:10px}.ops-heading h1{font-size:27px;letter-spacing:-.035em;margin:0 0 4px}.ops-heading p{color:#718097;font-size:12px;margin:0}.ops-actions{display:flex;flex-wrap:wrap;gap:9px;justify-content:flex-end}.ops-button,.ops-primary{align-items:center;border-radius:8px;display:inline-flex;font-size:12px;font-weight:650;gap:7px;justify-content:center;min-height:38px;padding:0 14px}.ops-button{background:#fff;border:1px solid #dce4ef;color:#40516b}.ops-primary{background:#075bf5;color:#fff}.asset-subnav{margin-bottom:12px}.ops-card{background:#fff;border:1px solid #e2e8f1;border-radius:11px;box-shadow:0 8px 26px rgba(40,63,105,.045);min-width:0;overflow:hidden}.index-metrics,.storage-kpis{display:grid;gap:10px;margin-bottom:12px}.index-metrics{grid-template-columns:repeat(5,minmax(0,1fr))}.index-metrics article,.storage-kpis article{align-items:center;background:#fff;border:1px solid #e2e8f1;border-radius:10px;display:flex;gap:10px;min-height:76px;padding:11px 13px}.index-metrics article>i,.storage-kpis article>i{align-items:center;border-radius:9px;display:flex;flex:0 0 auto;height:36px;justify-content:center;width:36px}.index-metrics article>span,.storage-kpis article>span{display:grid;min-width:0}.index-metrics span,.storage-kpis span{color:#58667c;font-size:10px}.index-metrics strong,.storage-kpis strong{color:#172238;font-size:17px;margin-top:3px}.index-metrics small,.storage-kpis small{color:#8793a7;font-size:9px;margin-top:2px}.index-metrics em{font-size:9px;font-style:normal;font-weight:400}.index-metrics article>b{background:#e2f8ed;border-radius:4px;color:#16a66f;font-size:8px;margin-left:auto;padding:3px}.index-metrics .purple{background:#eee9ff;color:#784eea}.index-metrics .blue{background:#e8f1ff;color:#1d65ef}.index-metrics .cyan{background:#e8f8fb;color:#18a9c7}.index-metrics .orange{background:#fff0df;color:#f18d15}.index-metrics .green{background:#e4f8ef;color:#0dac73}.index-metrics .red{background:#ffe9ec;color:#ef4d58}.index-metrics .down,.index-metrics .up{color:#0ba977}.index-metrics u{background:#e4eaf3;border-radius:5px;display:inline-block;height:5px;overflow:hidden;text-decoration:none;width:55px}.index-metrics u b{background:#075bf5;display:block;height:100%}.index-layout{display:grid;gap:12px;grid-template-columns:1fr}.index-layout.detail-open{grid-template-columns:minmax(610px,1fr) minmax(470px,.83fr)}.index-filters{align-items:center;border-bottom:1px solid #e8edf3;display:flex;gap:9px;padding:10px 12px}.index-filters select{background:#fff;border:1px solid #dde4ed;border-radius:7px;color:#4c5b70;font-size:10px;height:34px;padding:0 28px 0 10px}.index-filters label{align-items:center;border:1px solid #dde4ed;border-radius:7px;color:#8a96a8;display:flex;margin-left:auto;min-width:260px;padding:0 9px}.index-filters input{border:0;box-shadow:none!important;font-size:10px;height:32px;padding:0 7px;width:100%}.index-filters>button{align-items:center;background:#fff;border:1px solid #dde4ed;border-radius:7px;color:#536179;display:flex;height:34px;justify-content:center;width:34px}.index-table-head,.index-table-row{align-items:center;display:grid;gap:8px;grid-template-columns:minmax(180px,1.5fr) minmax(105px,.95fr) 92px 90px 105px 76px 66px 18px;padding:0 12px}.index-table-head{background:#f7f9fc;color:#6a768a;font-size:9px;min-height:33px}.index-table-row{background:#fff;border-top:1px solid #edf1f5;color:#526077;font-size:9px;min-height:62px;text-align:left;width:100%}.index-table-row:hover,.index-table-row.selected{background:#f5f8ff}.index-table-row.selected{box-shadow:inset 2px 0 #1265ef}.index-table-row span{min-width:0}.index-table-row b,.index-table-row small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.index-table-row small{color:#8590a2;margin-top:3px}.index-name{display:grid!important;grid-template-columns:25px 1fr}.index-name>i{align-items:center;border-radius:5px;display:flex;grid-row:1/3;height:24px;justify-content:center;margin-right:7px;width:24px}.index-name .completed{background:#e3f8ef;color:#0aaa73}.index-name .running{background:#e7f0ff;color:#1265ef}.index-name .pending{background:#fff2df;color:#ed8c16}.index-name .failed{background:#ffe8eb;color:#ed4d59}.index-progress{display:grid!important;gap:4px}.index-progress i{background:#e5eaf1;border-radius:4px;height:4px;overflow:hidden}.index-progress u{background:#1265ef;display:block;height:100%}.index-status{border-radius:4px;display:inline-flex!important;font-size:9px;font-weight:650;padding:3px 6px;width:max-content}.index-status.completed{background:#e5f8ef;color:#0aa974}.index-status.running{background:#e7f0ff;color:#1265ef}.index-status.pending{background:#fff0dd;color:#ef8b14}.index-status.failed{background:#ffe7eb;color:#ed4b59}.index-empty{color:#7e8a9d;padding:70px 20px;text-align:center}.index-pagination{align-items:center;color:#68758a;display:flex;font-size:9px;justify-content:space-between;min-height:48px;padding:8px 13px}.index-pagination div{display:flex;gap:4px}.index-pagination button{align-items:center;background:#fff;border:1px solid #e0e6ee;border-radius:5px;display:flex;height:27px;justify-content:center;min-width:27px}.index-pagination button.active{background:#075bf5;color:#fff}.index-pagination select{border:1px solid #e0e6ee;border-radius:6px;font-size:9px;height:29px}.index-detail>header{align-items:flex-start;border-bottom:1px solid #e6ebf1;display:flex;justify-content:space-between;padding:13px 15px}.index-detail h2{font-size:14px;margin:0 0 5px}.index-detail header p{font-size:10px;margin:0}.index-detail header button{background:transparent;color:#667388}.detail-top-grid{display:grid;gap:10px;grid-template-columns:1fr 1.2fr;padding:10px 13px}.detail-top-grid section{border:1px solid #e4e9f0;border-radius:8px;padding:10px}.detail-top-grid small{color:#738095;font-size:9px}.detail-top-grid strong{align-items:center;display:flex;font-size:10px;gap:6px;margin:8px 0}.detail-top-grid div{display:flex;gap:7px}.detail-top-grid button{background:#fff;border:1px solid #dce3ec;border-radius:5px;color:#536177;font-size:8px;padding:5px 8px}.detail-top-grid i{background:#eee9ff;border-radius:6px;display:block;height:40px;margin-top:8px;overflow:hidden}.detail-top-grid i u{background:linear-gradient(180deg,transparent 35%,#7b55ed 38%,#7b55ed 44%,transparent 47%);display:block;height:100%;width:100%}.index-detail>dl{display:grid;font-size:9px;grid-template-columns:1fr 1fr;margin:0;padding:4px 14px 10px;row-gap:7px}.index-detail>dl div{display:grid;gap:2px}.index-detail dt{color:#7b8799}.index-detail dd{margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.pipeline,.detail-log{border:1px solid #e3e8ef;border-radius:8px;margin:0 12px 9px;padding:9px}.pipeline h3,.detail-log h3{font-size:10px;margin:0}.pipeline>div{display:flex;margin-top:11px}.pipeline span{align-items:center;display:flex;flex:1;flex-direction:column;position:relative}.pipeline span:not(:last-child)::after{background:#dce3ec;content:'';height:2px;left:calc(50% + 9px);position:absolute;right:calc(-50% + 9px);top:8px}.pipeline span.done:not(:last-child)::after{background:#0bac75}.pipeline span i{align-items:center;background:#fff;border:2px solid #d8dfea;border-radius:50%;color:#fff;display:flex;height:18px;justify-content:center;position:relative;width:18px;z-index:1}.pipeline span.done i{background:#0bac75;border-color:#0bac75}.pipeline span.active i{background:#1265ef;border-color:#1265ef}.pipeline span b{font-size:8px;margin-top:5px}.pipeline span small{color:#8b95a6;font-size:7px}.detail-log header{align-items:center;display:flex;justify-content:space-between}.detail-log header button{background:transparent;color:#1265ef;font-size:8px}.detail-log p{display:grid;font-family:Consolas,monospace;font-size:8px;gap:6px;grid-template-columns:46px 32px 1fr;margin:6px 0}.detail-log time{color:#758196}.detail-log p b{color:#10a876}.index-detail>footer{border-top:1px solid #e4e9ef;display:flex;gap:8px;justify-content:flex-end;padding:10px 13px}.index-detail>footer button,.index-detail>footer a{align-items:center;background:#fff;border:1px solid #dce3ed;border-radius:6px;color:#4f5d72;display:flex;font-size:9px;gap:5px;min-height:30px;padding:0 11px}.index-detail>footer .primary{background:#075bf5;color:#fff}.storage-kpis{grid-template-columns:repeat(8,minmax(0,1fr))}.storage-kpis article{padding:10px;min-height:72px}.storage-kpis .reclaim{background:linear-gradient(135deg,#f1fbf6,#fff)}.storage-kpis .reclaim i{background:#ddf7e9;color:#11a871}.storage-main-grid,.storage-bottom-grid{display:grid;gap:12px;margin-bottom:12px}.storage-main-grid{grid-template-columns:1.4fr 1fr}.storage-bottom-grid{grid-template-columns:1.55fr 1fr}.ops-card>header{align-items:center;display:flex;justify-content:space-between;padding:11px 13px}.ops-card>header h2{font-size:12px;margin:0}.ops-card>header a{color:#075bf5;font-size:9px}.distribution-content{align-items:center;display:grid;gap:15px;grid-template-columns:180px 155px 1fr;padding:4px 13px 10px}.donut{align-items:center;border-radius:50%;display:flex;height:145px;justify-content:center;width:145px}.donut>span{align-items:center;background:#fff;border-radius:50%;display:flex;flex-direction:column;height:88px;justify-content:center;width:88px}.donut small,.donut em{color:#7a8698;font-size:8px;font-style:normal}.donut strong{font-size:20px;margin:3px}.storage-legend{display:grid;gap:5px}.storage-legend p{align-items:center;display:grid;font-size:8px;grid-template-columns:7px 1fr 62px 33px;margin:0}.storage-legend i{border-radius:50%;height:6px;width:6px}.storage-legend em{font-style:normal}.treemap{display:flex;flex-wrap:wrap;height:145px}.treemap span{color:#fff;display:flex;flex-basis:25%;flex-direction:column;justify-content:center;min-width:72px;padding:8px;text-align:center}.treemap b{font-size:9px}.treemap small,.treemap em{font-size:8px;font-style:normal;margin-top:3px}.storage-distribution>footer{align-items:center;border-top:1px solid #e6ebf1;display:grid;font-size:9px;gap:8px;grid-template-columns:72px 1fr auto 34px;padding:9px 13px}.storage-distribution>footer i{background:#e4e9f1;border-radius:5px;height:7px;overflow:hidden}.storage-distribution>footer i u{background:#075bf5;display:block;height:100%}.storage-distribution>footer strong{color:#ed4e5b}.source-head,.source-row{align-items:center;display:grid;font-size:8px;gap:8px;grid-template-columns:1.2fr .65fr .8fr .55fr 1fr;padding:0 12px}.source-head{background:#f7f9fc;color:#6e7a8d;min-height:30px}.source-row{border-top:1px solid #edf1f5;min-height:39px}.source-row>span:first-child{align-items:center;display:flex;gap:7px}.source-row>span:first-child i{align-items:center;border-radius:4px;color:#fff;display:flex;font-style:normal;height:18px;justify-content:center;width:18px}.trend{font-weight:650}.trend.up{color:#ef4d59}.trend.down{color:#0aaa74}.trend i{font-size:12px;margin-left:5px}.source-table-card>footer{align-items:center;border-top:1px solid #e5eaf1;display:grid;font-size:9px;grid-template-columns:1.2fr .65fr .8fr .55fr;padding:10px 12px}.directory-head,.directory-row{align-items:center;display:grid;font-size:8px;gap:8px;grid-template-columns:1.55fr .7fr .62fr .55fr 1fr .55fr;padding:0 12px}.directory-head,.cleanup-head{background:#f7f9fc;color:#6f7b8e;min-height:29px}.directory-row{border-top:1px solid #edf1f5;min-height:35px}.directory-row>span:first-child{align-items:center;color:#40516b;display:flex;gap:6px}.directory-row>span:nth-child(2) b{border-radius:4px;font-size:7px;padding:3px 5px}.directory-row>span:last-child{display:flex;gap:7px}.directory-row a,.directory-row button{background:transparent;color:#075bf5;font-size:8px;padding:0}.cleanup-head{align-items:center;display:grid;font-size:8px;grid-template-columns:1.4fr .6fr .45fr;padding:0 11px}.cleanup-row{align-items:center;background:#fff;border-top:1px solid #edf1f5;display:grid;gap:7px;grid-template-columns:15px 1.4fr .6fr .45fr;min-height:42px;padding:5px 11px;text-align:left;width:100%}.cleanup-row>i{align-items:center;border:1px solid #cdd6e2;border-radius:3px;color:#fff;display:flex;height:13px;justify-content:center;width:13px}.cleanup-row>i.checked{background:#075bf5;border-color:#075bf5}.cleanup-row>span{display:grid;grid-template-columns:22px 1fr}.cleanup-row>span>b{align-items:center;border-radius:4px;display:flex;grid-row:1/3;height:20px;justify-content:center;margin-right:5px;width:20px}.cleanup-row>span>b.green{background:#e1f8ee;color:#08a875}.cleanup-row>span>b.purple{background:#eee9ff;color:#754feb}.cleanup-row>span>b.red{background:#ffe9ec;color:#ee4d59}.cleanup-row>span>b.blue{background:#e8f1ff;color:#1464ef}.cleanup-row strong{font-size:8px}.cleanup-row small{color:#8792a4;font-size:7px}.cleanup-row em,.cleanup-row u{font-size:8px;font-style:normal;text-decoration:none}.cleanup-card>footer{align-items:center;background:#f1faf6;display:grid;font-size:8px;grid-template-columns:1fr 1fr 1.25fr;margin:6px 9px;padding:8px}.cleanup-card>footer span{display:grid}.cleanup-card>footer strong{color:#0aa875;font-size:13px}.cleanup-card>footer button{background:#075bf5;border-radius:6px;color:#fff;font-size:8px;height:30px}.cleanup-card>p{align-items:center;color:#788599;display:flex;font-size:7px;gap:5px;margin:5px 10px 9px}
@media(max-width:1450px){.index-metrics{grid-template-columns:repeat(3,1fr)}.storage-kpis{grid-template-columns:repeat(4,1fr)}.index-layout.detail-open{grid-template-columns:minmax(560px,1fr) minmax(430px,.85fr)}.distribution-content{grid-template-columns:150px 135px 1fr}.donut{height:125px;width:125px}.donut>span{height:76px;width:76px}.treemap{height:125px}}
@media(max-width:1120px){.index-layout.detail-open,.storage-main-grid,.storage-bottom-grid{grid-template-columns:1fr}.index-table-head,.index-table-row{grid-template-columns:minmax(180px,1.5fr) 95px 80px 82px 65px 18px}.index-table-head>:nth-child(2),.index-table-row>:nth-child(2),.index-table-head>:nth-child(5),.index-table-row>:nth-child(5){display:none}.storage-kpis{grid-template-columns:repeat(4,1fr)}}
@media(max-width:720px){.ops-heading{align-items:flex-start;flex-direction:column}.ops-actions{justify-content:flex-start}.index-metrics,.storage-kpis{grid-template-columns:1fr 1fr}.index-filters{flex-wrap:wrap}.index-filters label{margin-left:0;min-width:100%;order:3}.index-list-card{overflow-x:auto}.index-table-head,.index-table-row{min-width:700px}.detail-top-grid,.index-detail>dl{grid-template-columns:1fr}.distribution-content{grid-template-columns:1fr}.storage-legend{grid-template-columns:1fr 1fr}.directory-table,.source-table-card{overflow-x:auto}.directory-head,.directory-row,.source-head,.source-row{min-width:650px}}
</style>
