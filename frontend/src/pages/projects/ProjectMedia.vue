<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  assetPreviewUrl,
  assignSceneCandidate,
  confirmSceneFallbackAssignments,
  deleteSceneAssignment,
  getProjectAssignmentCoverage,
  generateSceneImages,
  importAssets,
  ingestAsset,
  listAssets,
  listSceneCandidates,
  listSceneAssignments,
  reorderSceneAssignments,
  searchSceneCandidates,
  updateAsset,
  updateSceneAssignmentRender,
  uploadSceneAsset,
} from '../../api/assets'
import { getProject, selectDirectory } from '../../api/projects'
import { getStoryboard } from '../../api/storyboard'
import { startVideoWorkflow } from '../../api/tasks'
import { usePageFeedback } from '../../services/feedback'
import type { LibraryRole, MediaAsset, SceneAssignment, SceneCandidate, SceneCoverage } from '../../types/media'
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
const assignments = ref<SceneAssignment[]>([])
const coverageByScene = ref<Record<string, SceneCoverage>>({})
const selectedSceneId = ref('')
const importDirectory = ref('')
const importRole = ref<LibraryRole>('semantic')
const importFallbackCategory = ref('')
const importMood = ref('')
const roleFilter = ref<'all' | LibraryRole>('all')
const loading = ref(false)
const searching = ref(false)
const importing = ref(false)
const indexingId = ref('')
const updatingId = ref('')
const assigningId = ref('')
const editingTrack = ref(false)
const savingMotionId = ref('')
const confirmingFallback = ref(false)
const uploadInput = ref<HTMLInputElement | null>(null)
const uploadingSceneAsset = ref(false)
const continuing = ref(false)
const message = ref('')
const error = ref('')
usePageFeedback(error, message, { errorTitle: '素材操作未完成', messageTitle: '素材处理状态' })

const selectedScene = computed(() => scenes.value.find((scene) => scene.id === selectedSceneId.value) || null)
const indexedShotCount = computed(() => assets.value.flatMap((asset) => asset.shots).filter((shot) => shot.vector_id !== null).length)
const keyframeCount = computed(() => assets.value.flatMap((asset) => asset.shots).reduce((sum, shot) => sum + shot.keyframes.length, 0))
const selectedCoverage = computed<SceneCoverage>(() => coverageByScene.value[selectedSceneId.value] || {
  covered_ms: 0,
  duration_ms: selectedScene.value ? selectedScene.value.end_ms - selectedScene.value.start_ms : 0,
  remaining_ms: selectedScene.value ? selectedScene.value.end_ms - selectedScene.value.start_ms : 0,
  complete: false,
  review_required: false,
})
const assignedCount = computed(() => scenes.value.filter((scene) => {
  const coverage = coverageByScene.value[scene.id]
  return coverage?.complete && !coverage.review_required
}).length)
const unreviewedScenes = computed(() => scenes.value.filter((scene) => !isSceneReviewed(scene.id)))
const unreviewedCount = computed(() => unreviewedScenes.value.length)
const reviewComplete = computed(() => scenes.value.length > 0 && assignedCount.value === scenes.value.length)
const filteredAssets = computed(() => roleFilter.value === 'all'
  ? assets.value
  : assets.value.filter((asset) => asset.library_role === roleFilter.value))
const usesGeneratedImages = computed(() => project.value?.config?.video_mode === 'ai_generated_images')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [loadedProject, loadedScenes, loadedAssets, loadedCoverage] = await Promise.all([
      getProject(projectId),
      getStoryboard(projectId),
      listAssets(),
      getProjectAssignmentCoverage(projectId),
    ])
    project.value = loadedProject
    scenes.value = loadedScenes
    assets.value = loadedAssets
    coverageByScene.value = loadedCoverage
    const firstPending = loadedScenes.find((scene) => {
      const coverage = loadedCoverage[scene.id]
      return !coverage?.complete || coverage.review_required
    })
    if (loadedScenes.length) await selectScene((firstPending || loadedScenes[0]).id)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材审核工作区加载失败'
  } finally {
    loading.value = false
  }
}

async function selectScene(sceneId: string) {
  selectedSceneId.value = sceneId
  candidates.value = []
  assignments.value = []
  error.value = ''
  try {
    const [loadedCandidates, track] = await Promise.all([
      listSceneCandidates(projectId, sceneId),
      listSceneAssignments(projectId, sceneId),
    ])
    candidates.value = loadedCandidates
    assignments.value = track.assignments
    coverageByScene.value = { ...coverageByScene.value, [sceneId]: track.coverage }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '候选素材加载失败'
  }
}

async function saveMotion(assignment: SceneAssignment) {
  if (!selectedScene.value) return
  savingMotionId.value = assignment.id
  error.value = ''
  try {
    const track = await updateSceneAssignmentRender(
      projectId,
      selectedScene.value.id,
      assignment,
    )
    assignments.value = track.assignments
    coverageByScene.value = {
      ...coverageByScene.value,
      [selectedScene.value.id]: track.coverage,
    }
    message.value = '镜头动态参数已保存；重新渲染时只会刷新受影响的场景'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存镜头动态参数失败'
  } finally {
    savingMotionId.value = ''
  }
}

function isSceneReviewed(sceneId: string) {
  const coverage = coverageByScene.value[sceneId]
  return Boolean(coverage?.complete && !coverage.review_required)
}

function sceneReviewLabel(sceneId: string) {
  const coverage = coverageByScene.value[sceneId]
  if (coverage?.review_required) return '待复核'
  if (coverage?.complete) return '已完成'
  return coverage?.covered_ms ? '待补素材' : '未审核'
}

async function locateNextUnreviewed() {
  if (!unreviewedScenes.value.length) {
    message.value = '全部分镜素材均已审核完成'
    return
  }
  const currentIndex = scenes.value.findIndex((scene) => scene.id === selectedSceneId.value)
  const ordered = [
    ...scenes.value.slice(currentIndex + 1),
    ...scenes.value.slice(0, currentIndex + 1),
  ]
  const target = ordered.find((scene) => !isSceneReviewed(scene.id)) || unreviewedScenes.value[0]
  await selectScene(target.id)
  message.value = `已定位到未审核分镜 ${String(target.scene_index).padStart(2, '0')}`
}

async function advanceAfterSceneCompleted(sceneId: string, completedMessage: string) {
  if (!isSceneReviewed(sceneId)) return
  const currentIndex = scenes.value.findIndex((scene) => scene.id === sceneId)
  const ordered = [
    ...scenes.value.slice(currentIndex + 1),
    ...scenes.value.slice(0, currentIndex),
  ]
  const target = ordered.find((scene) => !isSceneReviewed(scene.id))
  if (!target) {
    message.value = `${completedMessage}；全部 ${scenes.value.length} 个分镜素材均已审核完成`
    return
  }
  await selectScene(target.id)
  message.value = `${completedMessage}；已自动切换到分镜 ${String(target.scene_index).padStart(2, '0')}`
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
    if (importRole.value === 'themed_fallback' && !importFallbackCategory.value.trim()) {
      error.value = '主题兜底素材必须填写兜底类别'
      return
    }
    const result = await importAssets(
      importDirectory.value.trim(),
      importRole.value,
      importFallbackCategory.value.trim(),
      importMood.value.trim(),
    )
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

async function saveAssetClassification(asset: MediaAsset) {
  updatingId.value = asset.id
  error.value = ''
  try {
    const updated = await updateAsset(asset.id, {
      library_role: asset.library_role,
      fallback_category: asset.fallback_category,
      mood: asset.mood,
      review_status: asset.review_status,
      enabled: asset.enabled,
    })
    const index = assets.value.findIndex((item) => item.id === asset.id)
    if (index >= 0) assets.value[index] = updated
    message.value = asset.library_role === 'semantic'
      ? `${asset.filename} 已归入语义素材池；如尚无向量，请重建索引`
      : `${asset.filename} 的素材角色已更新，且不会参与普通语义向量召回`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材分类保存失败'
  } finally {
    updatingId.value = ''
  }
}

function roleLabel(role: LibraryRole) {
  return {
    semantic: '语义素材',
    themed_fallback: '主题兜底',
    landscape_fallback: '纯风景最终兜底',
  }[role]
}

function selectionStageLabel(stage: SceneCandidate['selection_stage']) {
  return {
    local_semantic: '本地语义命中',
    remote_semantic: '在线语义命中',
    themed_fallback: '主题兜底',
    landscape_fallback: '纯风景最终兜底',
    manual_upload: '人工上传',
    local_generated_image: '本地模型生成',
  }[stage]
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
    if (usesGeneratedImages.value) {
      const result = await generateSceneImages(projectId, selectedScene.value.id)
      candidates.value = result.candidates
      const track = await listSceneAssignments(projectId, selectedScene.value.id)
      assignments.value = track.assignments
      coverageByScene.value = { ...coverageByScene.value, [selectedScene.value.id]: track.coverage }
      message.value = `已生成 ${result.candidate_count} 张候选分镜图，请选择一张用于当前场景`
      return
    }
    const result = await searchSceneCandidates(projectId, selectedScene.value.id)
    candidates.value = result.candidates
    const track = await listSceneAssignments(projectId, selectedScene.value.id)
    assignments.value = track.assignments
    coverageByScene.value = { ...coverageByScene.value, [selectedScene.value.id]: track.coverage }
    const onlineProviders = (result.online_search || [])
      .filter((item) => item.downloaded.length)
      .map((item) => item.provider === 'pexels' ? 'Pexels' : 'Pixabay')
    const autoCount = result.auto_fallback?.selected_assignment_ids.length || 0
    message.value = result.candidates.length
      ? `已完成素材检索，返回 ${result.candidates.length} 个候选${onlineProviders.length ? `（已补充 ${onlineProviders.join('、')} 素材）` : ''}${autoCount ? `；已自动添加 ${autoCount} 个兜底镜头` : ''}`
      : '本地与已配置的在线平台均没有可用候选'
    if (track.coverage.complete && !track.coverage.review_required) {
      await advanceAfterSceneCompleted(selectedScene.value.id, message.value)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '素材检索失败'
  } finally {
    searching.value = false
  }
}

async function assign(candidate: SceneCandidate) {
  if (!selectedScene.value) return
  const manualOverride = candidate.status !== 'QUALIFIED'
  assigningId.value = candidate.id
  error.value = ''
  try {
    await assignSceneCandidate(projectId, selectedScene.value.id, candidate.id, manualOverride, true)
    const track = await listSceneAssignments(projectId, selectedScene.value.id)
    assignments.value = track.assignments
    coverageByScene.value = { ...coverageByScene.value, [selectedScene.value.id]: track.coverage }
    selectedScene.value.status = track.coverage.complete ? 'assigned' : 'partially_assigned'
    message.value = track.coverage.complete
      ? `场景 ${String(selectedScene.value.scene_index).padStart(2, '0')} 的镜头轨道已覆盖完整`
      : `已添加 ${candidate.media.filename}，还需要 ${formatMilliseconds(track.coverage.remaining_ms)}`
    if (track.coverage.complete && !track.coverage.review_required) {
      await advanceAfterSceneCompleted(selectedScene.value.id, message.value)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '确认素材失败'
  } finally {
    assigningId.value = ''
  }
}

async function removeTrackItem(assignment: SceneAssignment) {
  if (!selectedScene.value) return
  editingTrack.value = true
  error.value = ''
  try {
    const track = await deleteSceneAssignment(projectId, selectedScene.value.id, assignment.id)
    assignments.value = track.assignments
    coverageByScene.value = { ...coverageByScene.value, [selectedScene.value.id]: track.coverage }
    selectedScene.value.status = track.coverage.complete ? 'assigned' : track.assignments.length ? 'partially_assigned' : 'generated'
    message.value = `已移除 ${assignment.media.filename}，当前覆盖 ${formatMilliseconds(track.coverage.covered_ms)}`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '移除镜头失败'
  } finally {
    editingTrack.value = false
  }
}

async function moveTrackItem(index: number, direction: -1 | 1) {
  if (!selectedScene.value) return
  const target = index + direction
  if (target < 0 || target >= assignments.value.length) return
  const ids = assignments.value.map((item) => item.id)
  ;[ids[index], ids[target]] = [ids[target], ids[index]]
  editingTrack.value = true
  error.value = ''
  try {
    const track = await reorderSceneAssignments(projectId, selectedScene.value.id, ids)
    assignments.value = track.assignments
    coverageByScene.value = { ...coverageByScene.value, [selectedScene.value.id]: track.coverage }
    message.value = '镜头顺序已更新'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '镜头排序失败'
  } finally {
    editingTrack.value = false
  }
}

async function confirmFallbackTrack() {
  if (!selectedScene.value) return
  confirmingFallback.value = true
  error.value = ''
  try {
    const track = await confirmSceneFallbackAssignments(projectId, selectedScene.value.id)
    assignments.value = track.assignments
    coverageByScene.value = { ...coverageByScene.value, [selectedScene.value.id]: track.coverage }
    selectedScene.value.status = track.coverage.complete ? 'assigned' : 'partially_assigned'
    message.value = '本场景的自动兜底镜头已通过人工复核'
    if (track.coverage.complete && !track.coverage.review_required) {
      await advanceAfterSceneCompleted(selectedScene.value.id, message.value)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : '自动兜底确认失败'
  } finally {
    confirmingFallback.value = false
  }
}

function chooseSceneAsset() {
  uploadInput.value?.click()
}

async function uploadReplacement(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !selectedScene.value) return
  uploadingSceneAsset.value = true
  error.value = ''
  message.value = `正在上传并处理 ${file.name}…`
  try {
    const result = await uploadSceneAsset(projectId, selectedScene.value.id, file)
    const uploadedIds = new Set(result.candidates.map((candidate) => candidate.id))
    candidates.value = [
      ...result.candidates,
      ...candidates.value.filter((candidate) => !uploadedIds.has(candidate.id)),
    ]
    assets.value = await listAssets()
    message.value = result.ingestion_errors.length
      ? `${file.name} 已加入候选，但有 ${result.ingestion_errors.length} 个镜头处理失败`
      : `${file.name} 已处理完成，请在下方选择要使用的镜头`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '替换素材上传失败'
    message.value = ''
  } finally {
    uploadingSceneAsset.value = false
    input.value = ''
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

function isCandidateAssigned(candidate: SceneCandidate) {
  return assignments.value.some((assignment) => assignment.candidate_id === candidate.id)
}

onMounted(load)
</script>

<template>
  <section class="media-review-page">
    <div class="project-hero media-review-hero">
      <div>
        <span class="section-eyebrow">MEDIA REVIEW</span>
        <h1>素材审核</h1>
        <p>逐场景审核候选、解释评分与风险，并编排覆盖完整的镜头轨道。</p>
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


    <article v-if="false" class="panel media-import-bar">
      <div>
        <span class="section-eyebrow">LOCAL LIBRARY</span>
        <h2>本地素材入库</h2>
      </div>
      <div class="media-directory-control">
        <select v-model="importRole" class="filter-select" aria-label="导入素材角色">
          <option value="semantic">语义素材</option>
          <option value="themed_fallback">主题化兜底</option>
          <option value="landscape_fallback">纯风景最终兜底</option>
        </select>
        <input
          v-if="importRole === 'themed_fallback'"
          v-model="importFallbackCategory"
          placeholder="兜底类别，例如 business"
        />
        <input
          v-if="importRole !== 'semantic'"
          v-model="importMood"
          placeholder="情绪标签，例如 reflective"
        />
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
        <div class="scene-review-progress">
          <span><strong>{{ unreviewedCount }}</strong> 个未审核</span>
          <button class="mini-button" :disabled="!unreviewedCount" @click="locateNextUnreviewed">
            定位下一个
          </button>
        </div>
        <div v-if="!scenes.length" class="empty-state compact-empty">
          <h2>{{ loading ? '正在加载…' : '暂无视觉场景' }}</h2>
          <p>请先在分镜工作区生成 Storyboard。</p>
        </div>
        <button
          v-for="scene in scenes"
          :key="scene.id"
          class="scene-review-item"
          :class="{
            'is-active': scene.id === selectedSceneId,
            'is-unreviewed': !isSceneReviewed(scene.id),
            'is-reviewed': isSceneReviewed(scene.id),
          }"
          @click="selectScene(scene.id)"
        >
          <span class="scene-index">{{ String(scene.scene_index).padStart(2, '0') }}</span>
          <span>
            <strong>{{ scene.storyboard?.visual_summary || scene.narration }}</strong>
            <small>
              {{ formatMilliseconds(scene.end_ms - scene.start_ms) }} ·
              {{ coverageByScene[scene.id]?.review_required ? '自动兜底待复核' : coverageByScene[scene.id]?.complete ? '轨道完整' : `已覆盖 ${formatMilliseconds(coverageByScene[scene.id]?.covered_ms || 0)}` }}
            </small>
            <span
              class="scene-review-state"
              :class="{
                'is-complete': isSceneReviewed(scene.id),
                'is-review': coverageByScene[scene.id]?.review_required,
              }"
            >
              {{ sceneReviewLabel(scene.id) }}
            </span>
          </span>
        </button>
      </aside>

      <div class="candidate-review-panel">
        <article v-if="selectedScene" class="panel selected-scene-query">
          <div class="section-head">
            <div><span class="section-eyebrow">VECTOR QUERY</span><h2>{{ selectedScene.storyboard?.visual_summary || '待生成视觉查询' }}</h2></div>
            <div class="scene-media-actions">
              <input
                ref="uploadInput"
                class="visually-hidden-file"
                type="file"
                accept="video/mp4,video/quicktime,video/x-matroska,video/webm,video/x-msvideo,image/jpeg,image/png,image/webp,image/bmp,.m4v"
                @change="uploadReplacement"
              />
              <button class="secondary-button" :disabled="uploadingSceneAsset" @click="chooseSceneAsset">
                {{ uploadingSceneAsset ? '正在上传并处理…' : '上传替换素材' }}
              </button>
              <button class="primary-button" :disabled="searching || !selectedScene.storyboard" @click="searchCandidates">
                {{ searching ? (usesGeneratedImages ? '正在生成图片…' : '正在检索素材…') : (usesGeneratedImages ? '重新生成候选图' : '检索素材') }}
              </button>
            </div>
          </div>
          <p class="scene-narration">{{ selectedScene.narration }}</p>
          <div v-if="selectedScene.storyboard" class="query-tags">
            <span>{{ selectedScene.storyboard.primary_query }}</span>
            <span v-for="query in selectedScene.storyboard.alternative_queries" :key="query">{{ query }}</span>
          </div>
        </article>

        <article v-if="selectedScene" class="panel scene-shot-track">
          <div class="section-head">
            <div>
              <span class="section-eyebrow">SHOT TRACK</span>
              <h2>场景镜头轨道</h2>
            </div>
            <span class="status-pill" :class="selectedCoverage.complete && !selectedCoverage.review_required ? 'is-success' : 'is-warning'">
              {{ formatMilliseconds(selectedCoverage.covered_ms) }} / {{ formatMilliseconds(selectedCoverage.duration_ms) }}
            </span>
          </div>
          <div class="coverage-meter" :class="{ 'is-complete': selectedCoverage.complete }">
            <span :style="{ width: `${Math.min(100, selectedCoverage.duration_ms ? selectedCoverage.covered_ms / selectedCoverage.duration_ms * 100 : 0)}%` }"></span>
          </div>
          <div v-if="selectedCoverage.review_required" class="auto-fallback-review">
            <p>
              系统已自动添加兜底镜头。请检查内容相关性、重复情况与画面质量，再确认通过。
              <template v-if="!selectedCoverage.complete">当前还缺 {{ formatMilliseconds(selectedCoverage.remaining_ms) }}。</template>
            </p>
            <button class="primary-button" :disabled="confirmingFallback" @click="confirmFallbackTrack">
              {{ confirmingFallback ? '确认中…' : '确认本场景自动兜底' }}
            </button>
          </div>
          <p v-else-if="!selectedCoverage.complete" class="track-guidance">
            还缺 {{ formatMilliseconds(selectedCoverage.remaining_ms) }}。继续从候选区添加镜头；接近完整时系统最多自动降速到 0.85 倍。
          </p>
          <p v-else class="track-guidance is-complete">场景时长已经覆盖完整，可以继续审核其他场景。</p>
          <div v-if="assignments.length" class="shot-track-list">
            <div v-for="(assignment, index) in assignments" :key="assignment.id" class="shot-track-item" :class="{ 'is-auto-fallback': assignment.is_fallback && assignment.selection_reason.startsWith('系统自动兜底') }">
              <img v-if="assignment.shot.thumbnail_url" :src="assetPreviewUrl(assignment.shot.thumbnail_url)" :alt="assignment.media.filename" />
              <div class="shot-track-index">{{ index + 1 }}</div>
              <div class="shot-track-copy">
                <strong>{{ assignment.media.filename }} · #{{ assignment.shot.shot_index }}</strong>
                <span v-if="assignment.is_fallback && assignment.selection_reason.startsWith('系统自动兜底')" class="auto-fallback-badge">
                  自动兜底{{ assignment.manual_confirmed ? ' · 已复核' : ' · 待复核' }}
                </span>
                <small>
                  {{ formatMilliseconds(assignment.scene_offset_start_ms) }}—{{ formatMilliseconds(assignment.scene_offset_end_ms) }}
                  · {{ assignment.playback_speed.toFixed(2) }}×
                </small>
                <small :data-tooltip="assignment.selection_reason">{{ assignment.selection_reason }}</small>
                <div v-if="assignment.media.media_type === 'image'" class="motion-controls">
                  <label>
                    <span>渲染方式</span>
                    <select v-model="assignment.render_mode">
                      <option value="auto">自动路由</option>
                      <option value="ffmpeg">FFmpeg</option>
                    </select>
                  </label>
                  <label>
                    <span>动态效果</span>
                    <select v-model="assignment.motion_type">
                      <option value="auto">自动选择</option>
                      <option value="static">静止</option>
                      <option value="slow_zoom_in">缓慢推近</option>
                      <option value="slow_zoom_out">缓慢拉远</option>
                      <option value="pan_left_to_right">从左向右</option>
                      <option value="pan_right_to_left">从右向左</option>
                      <option value="pan_top_to_bottom">从上向下</option>
                      <option value="pan_bottom_to_top">从下向上</option>
                      <option value="diagonal_top_left">斜向左上</option>
                      <option value="diagonal_top_right">斜向右上</option>
                      <option value="portrait_push_in">人物推近</option>
                      <option value="environment_pull_out">环境拉远</option>
                      <option value="subtle_breathing">轻微呼吸</option>
                      <option value="random_safe">稳定随机</option>
                    </select>
                  </label>
                  <label><span>起始缩放</span><input v-model.number="assignment.zoom_start" type="number" min="1" max="1.2" step="0.01" /></label>
                  <label><span>结束缩放</span><input v-model.number="assignment.zoom_end" type="number" min="1" max="1.2" step="0.01" /></label>
                  <button class="mini-button" :disabled="savingMotionId === assignment.id" @click="saveMotion(assignment)">
                    {{ savingMotionId === assignment.id ? '保存中…' : '保存动态' }}
                  </button>
                </div>
              </div>
              <div class="shot-track-actions">
                <button class="mini-button" :disabled="editingTrack || index === 0" @click="moveTrackItem(index, -1)">上移</button>
                <button class="mini-button" :disabled="editingTrack || index === assignments.length - 1" @click="moveTrackItem(index, 1)">下移</button>
                <button class="mini-button danger" :disabled="editingTrack" @click="removeTrackItem(assignment)">移除</button>
              </div>
            </div>
          </div>
          <div v-else class="track-empty">尚未添加镜头，请从下方候选素材开始选择。</div>
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
                  :data-tooltip="formatMilliseconds(frame.timestamp_ms)"
                />
              </div>
              <div v-if="candidate.conflicts.length" class="candidate-conflicts">
                <span v-for="conflict in candidate.conflicts" :key="conflict">{{ conflict }}</span>
              </div>
              <div class="candidate-meta">
                <span>{{ candidate.media.width || '—' }} × {{ candidate.media.height || '—' }}</span>
                <span>{{ formatMilliseconds(candidate.shot.end_ms === null ? null : candidate.shot.end_ms - candidate.shot.start_ms) }}</span>
                <span>{{ candidate.retrieval.vector_model || '未建立向量' }}</span>
                <span>{{ selectionStageLabel(candidate.selection_stage) }}</span>
              </div>
              <button
                class="candidate-assign"
                :class="candidate.status === 'QUALIFIED' ? 'primary-button' : 'secondary-button conflict-override-button'"
                :disabled="assigningId === candidate.id || selectedCoverage.complete || isCandidateAssigned(candidate)"
                @click="assign(candidate)"
              >
                {{ assigningId === candidate.id ? '添加中…' : isCandidateAssigned(candidate) ? '已在镜头轨道中' : selectedCoverage.complete ? '场景轨道已完整' : candidate.status === 'QUALIFIED' ? '添加到镜头轨道' : '仍然使用并添加' }}
              </button>
            </div>
          </article>
        </div>
      </div>
    </div>

    <div class="section-toolbar compact-title media-library-title">
      <div><span class="section-eyebrow">ASSET INDEX</span><h2>素材库索引状态</h2><p>检查每个原始文件的镜头、预览帧和向量状态。</p></div>
      <div class="page-title-actions">
        <select v-model="roleFilter" class="filter-select" aria-label="素材池筛选">
          <option value="all">全部素材池</option>
          <option value="semantic">语义素材</option>
          <option value="themed_fallback">主题兜底</option>
          <option value="landscape_fallback">纯风景最终兜底</option>
        </select>
        <span class="status-pill is-neutral">{{ filteredAssets.length }} / {{ assets.length }}</span>
      </div>
    </div>
    <div class="asset-index-grid">
      <article v-for="asset in filteredAssets" :key="asset.id" class="panel asset-index-card">
        <div class="asset-index-head">
          <div>
            <strong>{{ asset.filename }}</strong>
            <small>{{ asset.width || '—' }} × {{ asset.height || '—' }} · {{ asset.shots.length }} 个镜头</small>
            <small>{{ roleLabel(asset.library_role) }} · {{ asset.provider }} · {{ asset.review_status }}</small>
          </div>
          <button class="secondary-button" :disabled="indexingId === asset.id" @click="buildIndex(asset)">{{ indexingId === asset.id ? '处理中…' : '重建预览与索引' }}</button>
        </div>
        <div class="asset-classification-controls">
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
            <span>启用</span>
          </label>
          <button class="secondary-button" :disabled="updatingId === asset.id" @click="saveAssetClassification(asset)">
            {{ updatingId === asset.id ? '保存中…' : '保存分类' }}
          </button>
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
