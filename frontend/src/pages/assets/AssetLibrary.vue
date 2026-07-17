<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  assetPreviewUrl,
  getAssetLibrary,
  importAssets,
  ingestAsset,
  updateAsset,
} from '../../api/assets'
import { selectDirectory } from '../../api/projects'
import type { LibraryRole, MediaAsset } from '../../types/media'
import { formatDuration } from '../../utils/time'

const assets = ref<MediaAsset[]>([])
const loading = ref(false)
const importing = ref(false)
const processingId = ref('')
const bulkProcessing = ref(false)
const directory = ref('')
const importRole = ref<LibraryRole>('semantic')
const fallbackCategory = ref('')
const mood = ref('')
const roleFilter = ref<'all' | LibraryRole>('all')
const searchText = ref('')
const message = ref('')
const error = ref('')
const currentVectorModel = ref('')

const allShots = computed(() => assets.value.flatMap((asset) => asset.shots))
const semanticAssets = computed(() => assets.value.filter((asset) => asset.library_role === 'semantic'))
const indexedShots = computed(() => allShots.value.filter(
  (shot) => shot.vector_id !== null && shot.vector_model === currentVectorModel.value,
))
const pendingSemanticAssets = computed(() => semanticAssets.value.filter(
  (asset) => asset.enabled
    && asset.review_status === 'approved'
    && asset.shots.some(
      (shot) => shot.vector_id === null || shot.vector_model !== currentVectorModel.value,
    ),
))
const filteredAssets = computed(() => {
  const query = searchText.value.trim().toLocaleLowerCase()
  return assets.value.filter((asset) => {
    if (roleFilter.value !== 'all' && asset.library_role !== roleFilter.value) return false
    if (!query) return true
    return [asset.filename, asset.path, asset.provider, asset.fallback_category, asset.mood]
      .some((value) => value.toLocaleLowerCase().includes(query))
  })
})

async function loadAssets() {
  loading.value = true
  error.value = ''
  try {
    const result = await getAssetLibrary()
    assets.value = result.assets
    currentVectorModel.value = result.vectorModel
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材库加载失败'
  } finally {
    loading.value = false
  }
}

async function chooseDirectory() {
  error.value = ''
  try {
    const selected = await selectDirectory(directory.value, '选择要扫描入库的素材目录')
    if (selected) directory.value = selected
  } catch (err) {
    error.value = err instanceof Error ? err.message : '选择目录失败'
  }
}

async function scanDirectory() {
  if (!directory.value.trim()) {
    error.value = '请先选择素材目录'
    return
  }
  if (importRole.value === 'themed_fallback' && !fallbackCategory.value.trim()) {
    error.value = '主题兜底素材必须填写兜底类别'
    return
  }
  importing.value = true
  error.value = ''
  message.value = '正在扫描文件并写入素材元数据…'
  try {
    const result = await importAssets(
      directory.value.trim(),
      importRole.value,
      fallbackCategory.value.trim(),
      mood.value.trim(),
    )
    await loadAssets()
    message.value = `扫描 ${result.discovered} 个文件，新入库 ${result.imported.length} 个，跳过重复 ${result.skipped.length} 个`
    if (result.errors.length) error.value = `${result.errors.length} 个文件入库失败，请检查格式和 FFmpeg 配置`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材扫描入库失败'
    message.value = ''
  } finally {
    importing.value = false
  }
}

async function processAsset(asset: MediaAsset) {
  processingId.value = asset.id
  error.value = ''
  message.value = asset.library_role === 'semantic'
    ? `正在为 ${asset.filename} 抽帧并生成向量…`
    : `正在为 ${asset.filename} 生成预览关键帧…`
  try {
    const result = await ingestAsset(asset.id)
    replaceAsset(result.asset)
    message.value = result.errors.length
      ? `${asset.filename} 已处理，但 ${result.errors.length} 个镜头失败`
      : `${asset.filename} 已完成${asset.library_role === 'semantic' ? '向量化和落库' : '预览处理'}`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材处理失败'
  } finally {
    processingId.value = ''
  }
}

async function processPendingSemanticAssets() {
  if (!pendingSemanticAssets.value.length) {
    message.value = '没有待向量化的语义素材'
    return
  }
  bulkProcessing.value = true
  error.value = ''
  let completed = 0
  let failedShots = 0
  const targets = [...pendingSemanticAssets.value]
  try {
    for (const asset of targets) {
      processingId.value = asset.id
      message.value = `正在向量化 ${completed + 1}/${targets.length}：${asset.filename}`
      const result = await ingestAsset(asset.id)
      replaceAsset(result.asset)
      failedShots += result.errors.length
      completed += 1
    }
    message.value = `已完成 ${completed} 个语义素材文件的关键帧与向量落库`
    if (failedShots) error.value = `${failedShots} 个镜头处理失败，请逐项重试`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '批量向量化失败'
  } finally {
    processingId.value = ''
    bulkProcessing.value = false
  }
}

async function saveClassification(asset: MediaAsset) {
  processingId.value = asset.id
  error.value = ''
  try {
    const updated = await updateAsset(asset.id, {
      library_role: asset.library_role,
      fallback_category: asset.fallback_category,
      mood: asset.mood,
      review_status: asset.review_status,
      enabled: asset.enabled,
    })
    replaceAsset(updated)
    message.value = updated.library_role === 'semantic'
      ? `${updated.filename} 已归入语义素材池；点击向量化后才会参与检索`
      : `${updated.filename} 已归入${roleLabel(updated.library_role)}，不会参与普通语义召回`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材分类保存失败'
  } finally {
    processingId.value = ''
  }
}

function replaceAsset(asset: MediaAsset) {
  const index = assets.value.findIndex((item) => item.id === asset.id)
  if (index >= 0) assets.value[index] = asset
}

function roleLabel(role: LibraryRole) {
  return {
    semantic: '语义素材',
    themed_fallback: '主题兜底素材',
    landscape_fallback: '纯风景最终兜底',
  }[role]
}

function roleDescription(role: LibraryRole) {
  return {
    semantic: '参与本地向量检索和 API 素材候选排序',
    themed_fallback: '仅在语义检索失败后按类别和情绪选用',
    landscape_fallback: '供空镜快速合成，并作为智能合成最后一级兜底',
  }[role]
}

function assetIndexedCount(asset: MediaAsset) {
  return asset.shots.filter(
    (shot) => shot.vector_id !== null && shot.vector_model === currentVectorModel.value,
  ).length
}

function formatMilliseconds(value: number | null) {
  return value === null ? '—' : formatDuration(value / 1000)
}

onMounted(loadAssets)
</script>

<template>
  <section class="asset-library-page">
    <div class="page-header asset-library-hero">
      <div>
        <span class="section-eyebrow">GLOBAL MEDIA LIBRARY</span>
        <h1>本地素材库</h1>
        <p>统一管理语义素材、主题兜底和纯风景空镜；扫描入库与向量化是两个独立步骤。</p>
      </div>
      <div class="page-title-actions">
        <button class="secondary-button" :disabled="loading" @click="loadAssets">刷新</button>
        <button class="primary-button" :disabled="bulkProcessing || !pendingSemanticAssets.length" @click="processPendingSemanticAssets">
          {{ bulkProcessing ? '批量向量化中…' : `向量化待处理素材（${pendingSemanticAssets.length}）` }}
        </button>
      </div>
    </div>

    <div class="asset-library-metrics">
      <div><span>素材文件</span><strong>{{ assets.length }}</strong></div>
      <div><span>可检索镜头</span><strong>{{ allShots.length }}</strong></div>
      <div><span>语义素材</span><strong>{{ semanticAssets.length }}</strong></div>
      <div><span>已落库向量</span><strong>{{ indexedShots.length }}</strong></div>
    </div>

    <div v-if="error" class="alert alert-danger"><strong>操作未完成</strong><span>{{ error }}</span></div>
    <div v-if="message" class="alert alert-success"><strong>素材库状态</strong><span>{{ message }}</span></div>

    <article class="panel asset-import-panel">
      <div class="section-head">
        <div>
          <span class="section-eyebrow">STEP 1 · INGEST</span>
          <h2>扫描目录并入库</h2>
          <p>先登记文件、来源、技术参数和镜头；此步骤不会自动执行批量向量化。</p>
        </div>
      </div>
      <div class="asset-import-form" :class="`is-${importRole}`">
        <label class="field asset-role-field">
          <span>素材角色</span>
          <select v-model="importRole">
            <option value="semantic">语义素材</option>
            <option value="themed_fallback">主题兜底素材</option>
            <option value="landscape_fallback">纯风景最终兜底</option>
          </select>
          <small>{{ roleDescription(importRole) }}</small>
        </label>
        <label v-if="importRole === 'themed_fallback'" class="field asset-category-field">
          <span>兜底类别</span>
          <input v-model="fallbackCategory" placeholder="business / technology / history" />
        </label>
        <label v-if="importRole !== 'semantic'" class="field asset-mood-field">
          <span>情绪标签</span>
          <input v-model="mood" placeholder="neutral / serious / reflective" />
        </label>
        <label class="field asset-directory-field">
          <span>素材目录</span>
          <span class="inline-form">
            <input v-model="directory" readonly placeholder="选择包含视频或图片的目录" />
            <button class="secondary-button" :disabled="importing" @click="chooseDirectory">选择目录</button>
          </span>
        </label>
        <button class="primary-button asset-import-submit" :disabled="importing || !directory" @click="scanDirectory">
          {{ importing ? '正在扫描入库…' : '扫描并入库' }}
        </button>
      </div>
    </article>

    <article class="panel vector-help-panel">
      <div>
        <span class="section-eyebrow">STEP 2 · VECTOR INDEX</span>
        <h2>生成关键帧并向量化</h2>
        <p>点击顶部批量按钮，或在单个素材卡片中处理。只有“语义素材”会写入检索向量；两类兜底素材只生成预览帧。</p>
      </div>
      <div class="vector-model-note">
        <span>当前模型</span>
        <strong>{{ currentVectorModel || '未配置' }}</strong>
        <small>使用镜头描述和最多 4 张代表性关键帧生成多模态向量；旧模型生成的向量会自动列入待重建队列。</small>
      </div>
    </article>

    <div class="asset-library-toolbar">
      <label class="search-field">
        <span class="asset-search-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none">
            <circle cx="11" cy="11" r="6.5" />
            <path d="m16 16 4 4" />
          </svg>
        </span>
        <input v-model="searchText" placeholder="文件名、路径、平台、类别或情绪" />
      </label>
      <select v-model="roleFilter" class="filter-select" aria-label="素材角色筛选">
        <option value="all">全部素材角色</option>
        <option value="semantic">语义素材</option>
        <option value="themed_fallback">主题兜底</option>
        <option value="landscape_fallback">纯风景最终兜底</option>
      </select>
      <span class="status-pill is-neutral">显示 {{ filteredAssets.length }} / {{ assets.length }}</span>
    </div>

    <div v-if="!loading && !filteredAssets.length" class="empty-state panel">
      <h2>素材库暂无匹配内容</h2>
      <p>选择一个本地目录并完成“扫描并入库”。</p>
    </div>

    <div class="asset-library-grid">
      <article v-for="asset in filteredAssets" :key="asset.id" class="panel asset-library-card">
        <div class="asset-library-preview">
          <img
            v-if="asset.shots[0]?.thumbnail_url"
            :src="assetPreviewUrl(asset.shots[0].thumbnail_url)"
            :alt="asset.filename"
          />
          <div v-else class="asset-preview-placeholder">等待生成预览</div>
          <span class="status-pill" :class="asset.enabled && asset.review_status === 'approved' ? 'is-success' : 'is-warning'">
            {{ asset.enabled ? asset.review_status : 'disabled' }}
          </span>
        </div>
        <div class="asset-library-card-body">
          <div class="asset-card-title">
            <div><strong>{{ asset.filename }}</strong><small>{{ asset.path }}</small></div>
            <span>{{ roleLabel(asset.library_role) }}</span>
          </div>
          <div class="asset-card-meta">
            <span>{{ asset.provider }}</span>
            <span>{{ asset.width || '—' }} × {{ asset.height || '—' }}</span>
            <span>{{ formatMilliseconds(asset.duration_ms) }}</span>
            <span>{{ asset.shots.length }} 个镜头</span>
            <span>{{ assetIndexedCount(asset) }}/{{ asset.shots.length }} 个向量</span>
          </div>

          <div class="asset-card-settings">
            <label class="field">
              <span>素材角色</span>
              <select v-model="asset.library_role">
                <option value="semantic">语义素材</option>
                <option value="themed_fallback">主题兜底</option>
                <option value="landscape_fallback">纯风景最终兜底</option>
              </select>
            </label>
            <label v-if="asset.library_role !== 'semantic'" class="field">
              <span>兜底类别</span>
              <input v-model="asset.fallback_category" placeholder="landscape / business" />
            </label>
            <label v-if="asset.library_role !== 'semantic'" class="field">
              <span>情绪</span>
              <input v-model="asset.mood" placeholder="neutral / reflective" />
            </label>
            <label class="field">
              <span>审核状态</span>
              <select v-model="asset.review_status">
                <option value="approved">已审核</option>
                <option value="pending">待审核</option>
                <option value="rejected">已拒绝</option>
              </select>
            </label>
            <label class="checkbox-field">
              <input v-model="asset.enabled" type="checkbox" />
              <span>允许使用</span>
            </label>
          </div>

          <div class="asset-card-actions">
            <button class="secondary-button" :disabled="processingId === asset.id || bulkProcessing" @click="saveClassification(asset)">
              保存分类
            </button>
            <button class="primary-button" :disabled="processingId === asset.id || bulkProcessing" @click="processAsset(asset)">
              {{ processingId === asset.id
                ? '处理中…'
                : asset.library_role === 'semantic' ? '生成/重建向量' : '生成/重建预览' }}
            </button>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
