<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  assetPreviewUrl,
  deleteAsset,
  deleteAssets,
  getAssetLibrary,
  importAssets,
  ingestAsset,
  updateAsset,
  type AssetLibrarySummary,
} from '../../api/assets'
import { selectDirectory } from '../../api/projects'
import { confirmAction, usePageFeedback } from '../../services/feedback'
import type { LibraryRole, MediaAsset } from '../../types/media'
import { formatDuration } from '../../utils/time'

const assets = ref<MediaAsset[]>([])
const loading = ref(false)
const importing = ref(false)
const processingId = ref('')
const bulkProcessing = ref(false)
const deleting = ref(false)
const selectedIds = ref<Set<string>>(new Set())
const directory = ref('')
const importRole = ref<LibraryRole>('semantic')
const fallbackCategory = ref('')
const mood = ref('')
const roleFilter = ref<'all' | LibraryRole>('all')
const searchText = ref('')
const message = ref('')
const error = ref('')
usePageFeedback(error, message, { errorTitle: '素材操作失败', messageTitle: '素材库状态' })
const currentVectorModel = ref('')
const page = ref(1)
const pageSize = ref(24)
const total = ref(0)
const summary = ref<AssetLibrarySummary>({
  asset_count: 0,
  shot_count: 0,
  semantic_asset_count: 0,
  indexed_shot_count: 0,
  preview_shot_count: 0,
})
let loadRequestId = 0
let searchTimer: ReturnType<typeof setTimeout> | undefined

const semanticAssets = computed(() => assets.value.filter((asset) => asset.library_role === 'semantic'))
const pendingSemanticAssets = computed(() => semanticAssets.value.filter(
  (asset) => asset.enabled
    && asset.review_status === 'approved'
    && asset.shots.some(
      (shot) => shot.vector_id === null || shot.vector_model !== currentVectorModel.value,
    ),
))
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))
const selectedCount = computed(() => selectedIds.value.size)
const allFilteredSelected = computed(() => (
  assets.value.length > 0
  && assets.value.every((asset) => selectedIds.value.has(asset.id))
))

async function loadAssets() {
  const requestId = ++loadRequestId
  loading.value = true
  error.value = ''
  try {
    const result = await getAssetLibrary({
      page: page.value,
      pageSize: pageSize.value,
      libraryRole: roleFilter.value === 'all' ? undefined : roleFilter.value,
      search: searchText.value,
    })
    if (requestId !== loadRequestId) return
    assets.value = result.assets
    currentVectorModel.value = result.vectorModel
    total.value = result.total
    summary.value = result.summary
    const availableIds = new Set(result.assets.map((asset) => asset.id))
    selectedIds.value = new Set([...selectedIds.value].filter((id) => availableIds.has(id)))
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材库加载失败'
  } finally {
    if (requestId === loadRequestId) loading.value = false
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
    page.value = 1
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
    await loadAssets()
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
    await loadAssets()
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
    await loadAssets()
    message.value = updated.library_role === 'semantic'
      ? `${updated.filename} 已归入语义素材池；点击向量化后才会参与检索`
      : `${updated.filename} 已归入${roleLabel(updated.library_role)}，不会参与普通语义召回`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材分类保存失败'
  } finally {
    processingId.value = ''
  }
}

function setAssetSelected(mediaId: string, selected: boolean) {
  const next = new Set(selectedIds.value)
  if (selected) next.add(mediaId)
  else next.delete(mediaId)
  selectedIds.value = next
}

function onAssetSelectionChange(mediaId: string, event: Event) {
  setAssetSelected(mediaId, (event.target as HTMLInputElement).checked)
}

function toggleFilteredSelection() {
  const next = new Set(selectedIds.value)
  if (allFilteredSelected.value) assets.value.forEach((asset) => next.delete(asset.id))
  else assets.value.forEach((asset) => next.add(asset.id))
  selectedIds.value = next
}

async function removeOne(asset: MediaAsset) {
  const confirmed = await confirmAction({
    eyebrow: '删除本地素材记录',
    title: `删除“${asset.filename}”？`,
    description: '将删除数据库记录、镜头向量和已生成的预览图。',
    detail: '原始素材文件会保留在原路径，不会被删除。已使用该素材的场景需要重新选择素材。',
    confirmText: '删除素材',
    tone: 'danger',
  })
  if (!confirmed) return
  deleting.value = true
  error.value = ''
  try {
    const result = await deleteAsset(asset.id)
    setAssetSelected(asset.id, false)
    if (assets.value.length === 1 && page.value > 1) page.value -= 1
    await loadAssets()
    message.value = `已删除 1 条素材记录和 ${result.deleted_preview_files} 个预览图文件，原始素材已保留`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材删除失败'
  } finally {
    deleting.value = false
  }
}

async function removeSelected() {
  const ids = [...selectedIds.value]
  if (!ids.length) return
  const confirmed = await confirmAction({
    eyebrow: '批量删除本地素材记录',
    title: `删除已选中的 ${ids.length} 个素材？`,
    description: '将批量删除数据库记录、镜头向量和已生成的预览图。',
    detail: '原始素材文件全部保留。已使用这些素材的场景需要重新选择素材。',
    confirmText: `删除 ${ids.length} 个素材`,
    tone: 'danger',
  })
  if (!confirmed) return
  deleting.value = true
  error.value = ''
  try {
    const result = await deleteAssets(ids)
    selectedIds.value = new Set()
    if (result.deleted_ids.length >= assets.value.length && page.value > 1) page.value -= 1
    await loadAssets()
    message.value = `已删除 ${result.deleted_ids.length} 条素材记录和 ${result.deleted_preview_files} 个预览图文件，原始素材已保留`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '批量删除素材失败'
  } finally {
    deleting.value = false
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

function assetPreviewCount(asset: MediaAsset) {
  return asset.shots.filter((shot) => shot.thumbnail_url !== null).length
}

function vectorStatus(asset: MediaAsset) {
  const shotCount = asset.shots.length
  if (asset.library_role !== 'semantic') {
    const previewCount = assetPreviewCount(asset)
    return previewCount === shotCount && shotCount > 0
      ? `无需向量 · 预览 ${previewCount}/${shotCount}`
      : `无需向量 · 待生成预览 ${previewCount}/${shotCount}`
  }
  const indexedCount = assetIndexedCount(asset)
  if (indexedCount === shotCount && shotCount > 0) return `向量已就绪 ${indexedCount}/${shotCount}`
  if (!indexedCount) return `待生成向量 0/${shotCount}`
  return `向量不完整 ${indexedCount}/${shotCount}`
}

const categoryOptions = [
  ['business', '商业'], ['technology', '科技'], ['finance', '金融'], ['history', '历史'],
  ['crisis', '危机'], ['travel', '旅行'], ['city', '城市'], ['transition', '转场'], ['landscape', '风景'],
] as const
const moodOptions = [
  ['neutral', '中性'], ['serious', '严肃'], ['reflective', '沉思'], ['calm', '平静'],
  ['hopeful', '希望'], ['tense', '紧张'], ['somber', '沉重'], ['curious', '好奇'], ['energetic', '活力'],
] as const

function optionLabel(options: readonly (readonly [string, string])[], value: string) {
  return options.find(([key]) => key === value)?.[1] || value || '未设置'
}

function reviewStatusLabel(asset: MediaAsset) {
  if (!asset.enabled) return '已停用'
  return { approved: '已审核', pending: '待审核', rejected: '已拒绝' }[asset.review_status]
}

function goToPage(nextPage: number) {
  const normalized = Math.min(totalPages.value, Math.max(1, nextPage))
  if (normalized === page.value) return
  page.value = normalized
  loadAssets()
}

function formatMilliseconds(value: number | null) {
  return value === null ? '—' : formatDuration(value / 1000)
}

watch(roleFilter, () => {
  page.value = 1
  selectedIds.value = new Set()
  loadAssets()
})
watch(pageSize, () => {
  page.value = 1
  selectedIds.value = new Set()
  loadAssets()
})
watch(searchText, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    selectedIds.value = new Set()
    loadAssets()
  }, 300)
})

onMounted(loadAssets)
</script>

<template>
  <section class="asset-library-page">
    <div class="page-header asset-library-hero">
      <div>
        <span class="section-eyebrow">GLOBAL MEDIA LIBRARY</span>
        <h1>素材浏览</h1>
        <p>统一浏览本地与远程素材，检查审核状态、来源、镜头与向量索引。</p>
      </div>
      <div class="page-title-actions">
        <button class="secondary-button" :disabled="loading" @click="loadAssets">刷新</button>
        <RouterLink class="primary-link" to="/assets/indexing">查看索引任务</RouterLink>
      </div>
    </div>

    <nav class="asset-subnav"><RouterLink to="/assets">素材浏览</RouterLink><RouterLink to="/assets/import">扫描入库</RouterLink><RouterLink to="/assets/indexing">索引任务</RouterLink><RouterLink to="/assets/storage">存储与来源</RouterLink></nav>

    <div class="asset-library-metrics">
      <div><span>素材文件</span><strong>{{ summary.asset_count }}</strong></div>
      <div><span>素材镜头</span><strong>{{ summary.shot_count }}</strong></div>
      <div><span>语义素材</span><strong>{{ summary.semantic_asset_count }}</strong></div>
      <div><span>向量 / 预览</span><strong>{{ summary.indexed_shot_count }} / {{ summary.preview_shot_count }}</strong></div>
    </div>


    <article v-if="false" class="panel asset-import-panel">
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
          <select v-model="fallbackCategory">
            <option value="">请选择类别</option>
            <option v-for="([value, label]) in categoryOptions" :key="value" :value="value">{{ label }}</option>
          </select>
        </label>
        <label v-if="importRole !== 'semantic'" class="field asset-mood-field">
          <span>情绪标签</span>
          <select v-model="mood">
            <option value="">未设置</option>
            <option v-for="([value, label]) in moodOptions" :key="value" :value="value">{{ label }}</option>
          </select>
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

    <article v-if="false" class="panel vector-help-panel">
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
      <select v-model="pageSize" class="filter-select" aria-label="每页素材数">
        <option :value="18">每页 18 个</option>
        <option :value="24">每页 24 个</option>
        <option :value="36">每页 36 个</option>
        <option :value="48">每页 48 个</option>
        <option :value="100">每页 100 个</option>
        <option :value="200">每页 200 个</option>
        <option :value="500">每页 500 个</option>
      </select>
      <button class="secondary-button" :disabled="!assets.length || deleting" @click="toggleFilteredSelection">
        {{ allFilteredSelected ? '取消本页全选' : '全选本页' }}
      </button>
      <button class="danger-button" :disabled="!selectedCount || deleting || bulkProcessing || !!processingId" @click="removeSelected">
        {{ deleting ? '删除中…' : `批量删除（${selectedCount}）` }}
      </button>
      <span class="status-pill is-neutral">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 个</span>
    </div>

    <div v-if="!loading && !assets.length" class="empty-state panel">
      <h2>素材库暂无匹配内容</h2>
      <p>选择一个本地目录并完成“扫描并入库”。</p>
    </div>

    <div class="asset-library-grid">
      <article v-for="asset in assets" :key="asset.id" class="panel asset-library-card">
        <div class="asset-library-preview">
          <label class="asset-select-checkbox" @click.stop>
            <input
              type="checkbox"
              :checked="selectedIds.has(asset.id)"
              :disabled="deleting || processingId === asset.id"
              @change="onAssetSelectionChange(asset.id, $event)"
            />
            <span>选择</span>
          </label>
          <img
            v-if="asset.shots[0]?.thumbnail_url"
            :src="assetPreviewUrl(asset.shots[0].thumbnail_url)"
            :alt="asset.filename"
          />
          <div v-else class="asset-preview-placeholder">等待生成预览</div>
          <span class="status-pill" :class="asset.enabled && asset.review_status === 'approved' ? 'is-success' : 'is-warning'">
            {{ reviewStatusLabel(asset) }}
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
            <span class="asset-index-status">{{ vectorStatus(asset) }}</span>
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
              <select v-if="asset.library_role === 'themed_fallback'" v-model="asset.fallback_category">
                <option v-if="asset.fallback_category && !categoryOptions.some(([value]) => value === asset.fallback_category)" :value="asset.fallback_category">
                  {{ optionLabel(categoryOptions, asset.fallback_category) }}
                </option>
                <option value="">请选择类别</option>
                <option v-for="([value, label]) in categoryOptions" :key="value" :value="value">{{ label }}</option>
              </select>
              <span v-else class="asset-readonly-value">纯风景</span>
            </label>
            <label v-if="asset.library_role !== 'semantic'" class="field">
              <span>情绪</span>
              <select v-model="asset.mood">
                <option v-if="asset.mood && !moodOptions.some(([value]) => value === asset.mood)" :value="asset.mood">
                  {{ optionLabel(moodOptions, asset.mood) }}
                </option>
                <option value="">未设置</option>
                <option v-for="([value, label]) in moodOptions" :key="value" :value="value">{{ label }}</option>
              </select>
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
            <button class="danger-button" :disabled="deleting || !!processingId || bulkProcessing" @click="removeOne(asset)">
              删除
            </button>
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

    <nav v-if="total > 0" class="asset-pagination" aria-label="素材分页">
      <button class="secondary-button" :disabled="page <= 1 || loading" @click="goToPage(1)">首页</button>
      <button class="secondary-button" :disabled="page <= 1 || loading" @click="goToPage(page - 1)">上一页</button>
      <span>第 <strong>{{ page }}</strong> 页，共 {{ totalPages }} 页</span>
      <button class="secondary-button" :disabled="page >= totalPages || loading" @click="goToPage(page + 1)">下一页</button>
      <button class="secondary-button" :disabled="page >= totalPages || loading" @click="goToPage(totalPages)">末页</button>
    </nav>
  </section>
</template>
