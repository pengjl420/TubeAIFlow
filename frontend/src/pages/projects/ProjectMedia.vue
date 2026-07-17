<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  assetPreviewUrl,
  assignSceneCandidate,
  importAssets,
  ingestAsset,
  listAssets,
  listSceneCandidates,
  searchSceneCandidates,
} from '../../api/assets'
import { getProject, selectDirectory } from '../../api/projects'
import { getStoryboard } from '../../api/storyboard'
import { startVideoWorkflow } from '../../api/tasks'
import type { MediaAsset, SceneCandidate } from '../../types/media'
import type { Project } from '../../types/project'
import type { VisualScene } from '../../types/storyboard'
import { formatDuration } from '../../utils/time'

const route = useRoute()
const router = useRouter()
const projectId = String(route.params.id)
const project = ref<Project | null>(null)
const scenes = ref<VisualScene[]>([])
const assets = ref<MediaAsset[]>([])
const candidates = ref<SceneCandidate[]>([])
const selectedSceneId = ref('')
const importDirectory = ref('')
const loading = ref(false)
const searching = ref(false)
const importing = ref(false)
const indexingId = ref('')
const assigningId = ref('')
const continuing = ref(false)
const message = ref('')
const error = ref('')

const selectedScene = computed(() => scenes.value.find((scene) => scene.id === selectedSceneId.value) || null)
const indexedShotCount = computed(() => assets.value.flatMap((asset) => asset.shots).filter((shot) => shot.vector_id !== null).length)
const keyframeCount = computed(() => assets.value.flatMap((asset) => asset.shots).reduce((sum, shot) => sum + shot.keyframes.length, 0))
const assignedCount = computed(() => scenes.value.filter((scene) => scene.status === 'assigned' || scene.status === 'rendered').length)
const reviewComplete = computed(() => scenes.value.length > 0 && assignedCount.value === scenes.value.length)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [loadedProject, loadedScenes, loadedAssets] = await Promise.all([
      getProject(projectId),
      getStoryboard(projectId),
      listAssets(),
    ])
    project.value = loadedProject
    scenes.value = loadedScenes
    assets.value = loadedAssets
    const configuredDirectory = loadedProject.config?.media_video_dir
    importDirectory.value = typeof configuredDirectory === 'string' ? configuredDirectory : ''
    if (loadedScenes.length) await selectScene(loadedScenes[0].id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材审核工作区加载失败'
  } finally {
    loading.value = false
  }
}

async function selectScene(sceneId: string) {
  selectedSceneId.value = sceneId
  candidates.value = []
  error.value = ''
  try {
    candidates.value = await listSceneCandidates(projectId, sceneId)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '候选素材加载失败'
  }
}

async function chooseDirectory() {
  error.value = ''
  try {
    const selected = await selectDirectory(importDirectory.value, '选择本地素材目录')
    if (selected) importDirectory.value = selected
  } catch (err) {
    error.value = err instanceof Error ? err.message : '选择素材目录失败'
  }
}

async function importAndIndex() {
  if (!importDirectory.value.trim()) {
    error.value = '请先选择本地素材目录'
    return
  }
  importing.value = true
  error.value = ''
  message.value = '正在扫描素材目录…'
  try {
    const result = await importAssets(importDirectory.value.trim())
    const targets = new Map<string, string>()
    for (const asset of result.imported) targets.set(asset.id, asset.filename)
    for (const skipped of result.skipped) targets.set(skipped.media_id, skipped.path.split(/[\\/]/).pop() || skipped.path)
    let ingestionErrors = 0
    for (const [mediaId, filename] of targets) {
      indexingId.value = mediaId
      message.value = `正在生成 ${filename} 的缩略图、关键帧和检索向量…`
      const indexed = await ingestAsset(mediaId)
      ingestionErrors += indexed.errors.length
    }
    assets.value = await listAssets()
    message.value = `扫描到 ${result.discovered} 个文件，新导入 ${result.imported.length} 个，跳过 ${result.skipped.length} 个重复文件`
    if (result.errors.length || ingestionErrors) {
      error.value = `${result.errors.length} 个文件导入失败，${ingestionErrors} 个镜头处理失败，请检查素材格式或 FFmpeg 日志`
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材导入失败'
    message.value = ''
  } finally {
    indexingId.value = ''
    importing.value = false
  }
}

async function buildIndex(asset: MediaAsset) {
  indexingId.value = asset.id
  error.value = ''
  message.value = `正在处理 ${asset.filename}…`
  try {
    const result = await ingestAsset(asset.id)
    const index = assets.value.findIndex((item) => item.id === asset.id)
    if (index >= 0) assets.value[index] = result.asset
    message.value = result.errors.length
      ? `${asset.filename} 已完成，但有 ${result.errors.length} 个镜头处理失败`
      : `${asset.filename} 的缩略图、关键帧和向量索引已更新`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材处理失败'
    message.value = ''
  } finally {
    indexingId.value = ''
  }
}

async function searchCandidates() {
  if (!selectedScene.value?.storyboard) {
    error.value = '当前场景尚未生成 Storyboard 查询'
    return
  }
  searching.value = true
  error.value = ''
  message.value = ''
  try {
    const result = await searchSceneCandidates(projectId, selectedScene.value.id)
    candidates.value = result.candidates
    const onlineProviders = (result.online_search || [])
      .filter((item) => item.downloaded.length)
      .map((item) => item.provider === 'pexels' ? 'Pexels' : 'Pixabay')
    message.value = result.candidates.length
      ? `已完成素材检索，返回 ${result.candidates.length} 个候选${onlineProviders.length ? `（已补充 ${onlineProviders.join('、')} 素材）` : ''}`
      : '本地与已配置的在线平台均没有可用候选'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材检索失败'
  } finally {
    searching.value = false
  }
}

async function assign(candidate: SceneCandidate) {
  if (!selectedScene.value) return
  assigningId.value = candidate.id
  error.value = ''
  try {
    await assignSceneCandidate(projectId, selectedScene.value.id, candidate.id)
    selectedScene.value.status = 'assigned'
    message.value = `场景 ${String(selectedScene.value.scene_index).padStart(2, '0')} 已确认使用 ${candidate.media.filename}`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '确认素材失败'
  } finally {
    assigningId.value = ''
  }
}

async function continueVideoPipeline() {
  if (!reviewComplete.value) {
    error.value = `还有 ${scenes.value.length - assignedCount.value} 个场景未确认素材`
    return
  }
  continuing.value = true
  error.value = ''
  try {
    await startVideoWorkflow(projectId)
    await router.push(`/projects/${projectId}/render`)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '视频工作流启动失败'
  } finally {
    continuing.value = false
  }
}

function percent(value: number) {
  return `${Math.round(value * 100)}%`
}

function formatMilliseconds(value: number | null) {
  return formatDuration((value || 0) / 1000)
}

onMounted(load)
</script>

<template>
  <section class="media-review-page">
    <div class="project-hero media-review-hero">
      <div>
        <RouterLink class="breadcrumb-link" :to="`/projects/${projectId}`">← 返回项目</RouterLink>
        <span class="section-eyebrow">MEDIA REVIEW</span>
        <h1>{{ project?.name || '素材审核' }}</h1>
        <p>按视觉场景检索镜头，核对缩略图与关键帧，并持久化人工选择。</p>
      </div>
      <div class="media-review-metrics">
        <div><strong>{{ assets.length }}</strong><span>素材文件</span></div>
        <div><strong>{{ indexedShotCount }}</strong><span>已索引镜头</span></div>
        <div><strong>{{ keyframeCount }}</strong><span>关键帧</span></div>
      </div>
      <div class="page-title-actions">
        <RouterLink class="secondary-button" :to="`/projects/${projectId}/storyboard`">返回分镜</RouterLink>
        <button class="primary-button" :disabled="!reviewComplete || continuing" @click="continueVideoPipeline">
          {{ continuing ? '正在启动…' : `审核完成并继续（${assignedCount}/${scenes.length}）` }}
        </button>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger"><strong>操作未完成</strong><span>{{ error }}</span></div>
    <div v-if="message" class="alert alert-success"><strong>当前状态</strong><span>{{ message }}</span></div>

    <article class="panel media-import-bar">
      <div>
        <span class="section-eyebrow">LOCAL LIBRARY</span>
        <h2>本地素材入库</h2>
      </div>
      <div class="media-directory-control">
        <input v-model="importDirectory" readonly placeholder="选择包含视频或图片的目录" />
        <button class="secondary-button" :disabled="importing" @click="chooseDirectory">选择目录</button>
        <button class="primary-button" :disabled="importing || !importDirectory" @click="importAndIndex">
          {{ importing ? '正在导入并建立索引…' : '导入并建立索引' }}
        </button>
      </div>
    </article>

    <div class="media-review-layout">
      <aside class="panel scene-review-rail">
        <div class="section-head">
          <div><span class="section-eyebrow">SCENES</span><h2>视觉场景</h2></div>
          <span class="status-pill is-neutral">{{ scenes.length }}</span>
        </div>
        <div v-if="!scenes.length" class="empty-state compact-empty">
          <h2>{{ loading ? '正在加载…' : '暂无视觉场景' }}</h2>
          <p>请先在分镜工作区生成 Storyboard。</p>
        </div>
        <button
          v-for="scene in scenes"
          :key="scene.id"
          class="scene-review-item"
          :class="{ 'is-active': scene.id === selectedSceneId }"
          @click="selectScene(scene.id)"
        >
          <span class="scene-index">{{ String(scene.scene_index).padStart(2, '0') }}</span>
          <span><strong>{{ scene.storyboard?.visual_summary || scene.narration }}</strong><small>{{ formatMilliseconds(scene.end_ms - scene.start_ms) }} · {{ scene.status }}</small></span>
        </button>
      </aside>

      <main class="candidate-review-panel">
        <article v-if="selectedScene" class="panel selected-scene-query">
          <div class="section-head">
            <div><span class="section-eyebrow">VECTOR QUERY</span><h2>{{ selectedScene.storyboard?.visual_summary || '待生成视觉查询' }}</h2></div>
            <button class="primary-button" :disabled="searching || !selectedScene.storyboard" @click="searchCandidates">
              {{ searching ? '正在检索素材…' : '检索素材' }}
            </button>
          </div>
          <p class="scene-narration">{{ selectedScene.narration }}</p>
          <div v-if="selectedScene.storyboard" class="query-tags">
            <span>{{ selectedScene.storyboard.primary_query }}</span>
            <span v-for="query in selectedScene.storyboard.alternative_queries" :key="query">{{ query }}</span>
          </div>
        </article>

        <div v-if="selectedScene && !candidates.length" class="empty-state panel candidate-empty">
          <h2>尚无候选素材</h2>
          <p>先完成素材入库与向量索引，再检索当前视觉场景。</p>
        </div>

        <div class="candidate-grid">
          <article v-for="candidate in candidates" :key="candidate.id" class="panel candidate-card">
            <div class="candidate-preview">
              <img v-if="candidate.shot.thumbnail_url" :src="assetPreviewUrl(candidate.shot.thumbnail_url)" :alt="candidate.media.filename" />
              <div v-else class="candidate-no-preview">暂无缩略图</div>
              <span class="candidate-score">{{ percent(candidate.scores.total) }}</span>
              <span class="status-pill" :class="candidate.status === 'QUALIFIED' ? 'is-success' : 'is-warning'">{{ candidate.status }}</span>
            </div>
            <div class="candidate-body">
              <div class="candidate-title"><strong>{{ candidate.media.filename }}</strong><span>#{{ candidate.shot.shot_index }}</span></div>
              <p>{{ candidate.shot.description || '无镜头描述' }}</p>
              <div class="score-breakdown">
                <span>向量 <strong>{{ percent(candidate.scores.semantic) }}</strong></span>
                <span>文本 <strong>{{ percent(candidate.scores.text) }}</strong></span>
                <span>标签 <strong>{{ percent(candidate.scores.tags) }}</strong></span>
                <span>质量 <strong>{{ percent(candidate.scores.technical) }}</strong></span>
              </div>
              <div v-if="candidate.shot.keyframes.length" class="keyframe-strip">
                <img
                  v-for="frame in candidate.shot.keyframes"
                  :key="frame.id"
                  :src="assetPreviewUrl(frame.url)"
                  :alt="`${candidate.media.filename} ${frame.frame_index}`"
                  :title="formatMilliseconds(frame.timestamp_ms)"
                />
              </div>
              <div v-if="candidate.conflicts.length" class="candidate-conflicts">
                <span v-for="conflict in candidate.conflicts" :key="conflict">{{ conflict }}</span>
              </div>
              <div class="candidate-meta">
                <span>{{ candidate.media.width || '—' }} × {{ candidate.media.height || '—' }}</span>
                <span>{{ formatMilliseconds(candidate.shot.end_ms === null ? null : candidate.shot.end_ms - candidate.shot.start_ms) }}</span>
                <span>{{ candidate.retrieval.vector_model || '未建立向量' }}</span>
              </div>
              <button class="primary-button candidate-assign" :disabled="candidate.status !== 'QUALIFIED' || assigningId === candidate.id" @click="assign(candidate)">
                {{ assigningId === candidate.id ? '确认中…' : candidate.status === 'QUALIFIED' ? '确认使用此镜头' : '需人工处理冲突' }}
              </button>
            </div>
          </article>
        </div>
      </main>
    </div>

    <div class="section-toolbar compact-title media-library-title">
      <div><span class="section-eyebrow">ASSET INDEX</span><h2>素材库索引状态</h2><p>检查每个原始文件的镜头、预览帧和向量状态。</p></div>
      <span class="status-pill is-neutral">{{ assets.length }} 个文件</span>
    </div>
    <div class="asset-index-grid">
      <article v-for="asset in assets" :key="asset.id" class="panel asset-index-card">
        <div class="asset-index-head">
          <div><strong>{{ asset.filename }}</strong><small>{{ asset.width || '—' }} × {{ asset.height || '—' }} · {{ asset.shots.length }} 个镜头</small></div>
          <button class="secondary-button" :disabled="indexingId === asset.id" @click="buildIndex(asset)">{{ indexingId === asset.id ? '处理中…' : '重建预览与索引' }}</button>
        </div>
        <div class="asset-shot-list">
          <div v-for="shot in asset.shots" :key="shot.id" class="asset-shot-row">
            <img v-if="shot.thumbnail_url" :src="assetPreviewUrl(shot.thumbnail_url)" :alt="asset.filename" />
            <div v-else class="asset-shot-placeholder">{{ shot.shot_index }}</div>
            <span><strong>镜头 {{ shot.shot_index }}</strong><small>{{ shot.keyframes.length }} 帧 · {{ shot.vector_model || '未索引' }}</small></span>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
