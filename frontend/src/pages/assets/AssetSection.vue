<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { AlertTriangle, CheckCircle2, Database, FolderSearch, HardDrive, Image, Play, RefreshCw, ScanSearch, Video } from 'lucide-vue-next'

import { getAssetLibrary, importAssets, ingestAsset, type AssetLibrarySummary } from '../../api/assets'
import { selectDirectory } from '../../api/projects'
import type { LibraryRole, MediaAsset } from '../../types/media'

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
const error = ref('')
const message = ref('')

const pendingAssets = computed(() => assets.value.filter((asset) => asset.shots.some((shot) => shot.vector_id === null)))
const totalBytes = computed(() => assets.value.reduce((total, asset) => total + asset.size_bytes, 0))
const providerUsage = computed(() => ['local', 'pexels', 'pixabay', 'generated'].map((provider) => ({ provider, bytes: assets.value.filter((asset) => asset.provider === provider).reduce((total, asset) => total + asset.size_bytes, 0) })))

function formatSize(size: number) {
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`
}

async function load() {
  loading.value = true; error.value = ''
  try { const result = await getAssetLibrary({ pageSize: 500 }); assets.value = result.assets; summary.value = result.summary; vectorModel.value = result.vectorModel }
  catch (err) { error.value = err instanceof Error ? err.message : '素材中心加载失败' }
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

async function buildIndex() {
  processing.value = true; error.value = ''; message.value = ''
  try {
    let completed = 0
    for (const asset of pendingAssets.value) { await ingestAsset(asset.id); completed += 1 }
    message.value = `已完成 ${completed} 个素材文件的镜头分析与向量化`
    await load()
  } catch (err) { error.value = err instanceof Error ? err.message : '索引任务失败' }
  finally { processing.value = false }
}

onMounted(load)
</script>

<template>
  <section class="asset-section-page">
    <header class="page-header">
      <div><span class="section-eyebrow">MEDIA OPERATIONS</span><h1>{{ section === 'import' ? '扫描入库' : section === 'indexing' ? '索引任务' : '存储与来源' }}</h1><p>{{ section === 'import' ? '按素材角色扫描目录，在确认重复与冲突后加入全局素材库。' : section === 'indexing' ? '追踪关键帧、镜头切分和向量索引的处理状态。' : '了解本地素材、远程下载、关键帧和索引的存储占用。' }}</p></div>
      <button class="secondary-button" :disabled="loading" @click="load"><RefreshCw :size="16" /> 刷新</button>
    </header>
    <nav class="asset-subnav"><RouterLink to="/assets">素材浏览</RouterLink><RouterLink to="/assets/import">扫描入库</RouterLink><RouterLink to="/assets/indexing">索引任务</RouterLink><RouterLink to="/assets/storage">存储与来源</RouterLink></nav>
    <div v-if="error" class="alert alert-danger"><strong>素材操作失败</strong><span>{{ error }}</span></div><div v-if="message" class="alert alert-success"><strong>素材中心</strong><span>{{ message }}</span></div>

    <template v-if="section === 'import'">
      <div class="import-stepper panel"><span class="is-active"><i>1</i>选择目录</span><span><i>2</i>设定素材角色</span><span><i>3</i>扫描与去重</span><span><i>4</i>确认入库</span><span><i>5</i>生成索引</span></div>
      <div class="asset-import-workspace">
        <article class="panel import-source-card"><div class="section-head"><div><span class="section-eyebrow">SOURCE</span><h2>选择目录</h2></div><FolderSearch :size="22" /></div><button class="directory-dropzone" @click="chooseDirectory"><ScanSearch :size="34" /><strong>{{ directory || '选择需要扫描的素材文件夹' }}</strong><small>支持 MP4、MOV、MKV、JPG、PNG 和 WebP</small></button></article>
        <article class="panel import-config-card"><div class="section-head"><div><span class="section-eyebrow">CLASSIFICATION</span><h2>入库规则</h2></div></div><label class="field"><span>素材角色</span><select v-model="role"><option value="semantic">语义素材</option><option value="themed_fallback">主题化兜底</option><option value="landscape_fallback">纯风景最终兜底</option></select></label><label v-if="role === 'themed_fallback'" class="field"><span>兜底类别</span><select v-model="fallbackCategory"><option>business</option><option>technology</option><option>finance</option><option>history</option><option>crisis</option><option>travel</option><option>city</option><option>transition</option></select></label><label v-if="role !== 'semantic'" class="field"><span>情绪标签</span><input v-model="mood" placeholder="neutral" /></label><div class="import-notice"><AlertTriangle :size="16" /><span>系统会按文件哈希与平台资产 ID 去重，原始文件不会被移动。</span></div><button class="primary-button" :disabled="processing || !directory" @click="startImport">{{ processing ? '正在扫描…' : '扫描目录并预览' }}</button></article>
      </div>
    </template>

    <template v-else-if="section === 'indexing'">
      <div class="metric-grid"><article class="metric-card accent-card"><span>当前视觉模型</span><strong class="metric-model">{{ vectorModel || '未配置' }}</strong><small>用于素材镜头语义检索</small></article><article class="metric-card"><span>待处理文件</span><strong>{{ pendingAssets.length }}</strong><small>{{ summary.shot_count - summary.indexed_shot_count }} 个镜头待索引</small></article><article class="metric-card"><span>已完成镜头</span><strong>{{ summary.indexed_shot_count }}</strong><small>共 {{ summary.shot_count }} 个镜头</small></article><article class="metric-card"><span>预览可用</span><strong>{{ summary.preview_shot_count }}</strong><small>关键帧与缩略图</small></article></div>
      <article class="panel indexing-control"><div><span class="section-eyebrow">VECTOR INDEX</span><h2>镜头分析与向量化</h2><p>先切分可检索镜头、抽取关键帧，再使用当前视觉模型生成向量索引。</p></div><button class="primary-button" :disabled="processing || !pendingAssets.length" @click="buildIndex"><Play :size="16" /> {{ processing ? '索引任务运行中…' : `处理 ${pendingAssets.length} 个待处理文件` }}</button></article>
      <article class="panel indexing-table"><div class="index-row index-head"><span>素材文件</span><span>镜头</span><span>关键帧</span><span>模型版本</span><span>状态</span></div><div v-for="asset in assets.slice(0, 50)" :key="asset.id" class="index-row"><span><component :is="asset.media_type === 'video' ? Video : Image" :size="16" /><strong>{{ asset.filename }}</strong></span><span>{{ asset.shots.length }}</span><span>{{ asset.shots.reduce((total, shot) => total + shot.keyframes.length, 0) }}</span><span>{{ asset.shots.find((shot) => shot.vector_model)?.vector_model || '—' }}</span><span class="status-pill" :class="asset.shots.every((shot) => shot.vector_id !== null) ? 'is-success' : 'is-warning'">{{ asset.shots.every((shot) => shot.vector_id !== null) ? '已索引' : '待处理' }}</span></div></article>
    </template>

    <template v-else>
      <div class="storage-overview panel"><div class="storage-gauge"><HardDrive :size="28" /><strong>{{ formatSize(totalBytes) }}</strong><span>素材文件总占用</span></div><div class="storage-bar"><i :style="{ width: `${Math.min(100, totalBytes / (100 * 1024 * 1024 * 1024) * 100)}%` }"></i></div><div class="storage-stats"><span><strong>{{ summary.asset_count }}</strong><small>素材文件</small></span><span><strong>{{ summary.shot_count }}</strong><small>可检索镜头</small></span><span><strong>{{ summary.preview_shot_count }}</strong><small>预览镜头</small></span></div></div>
      <div class="storage-source-grid"><article v-for="item in providerUsage" :key="item.provider" class="panel"><span class="artifact-icon"><Database :size="20" /></span><div><strong>{{ { local: '本地素材', pexels: 'Pexels 下载', pixabay: 'Pixabay 下载', generated: 'AI 图片' }[item.provider] || item.provider }}</strong><small>{{ formatSize(item.bytes) }}</small></div><span class="status-pill is-neutral">{{ assets.filter((asset) => asset.provider === item.provider).length }} 个</span></article><article class="panel"><span class="artifact-icon"><CheckCircle2 :size="20" /></span><div><strong>关键帧与索引</strong><small>{{ summary.indexed_shot_count }} 个已索引镜头</small></div><RouterLink to="/assets/indexing">管理索引</RouterLink></article></div>
    </template>
  </section>
</template>
