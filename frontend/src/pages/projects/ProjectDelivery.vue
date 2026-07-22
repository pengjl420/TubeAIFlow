<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Clipboard, Download, ExternalLink, FileArchive, FileAudio2, FileCode2, FileText, FileVideo2, Film, FolderOpen, LayoutList, RefreshCw, ScrollText } from 'lucide-vue-next'

import { getProject, getProjectOutputs, projectOutputFileUrl, type ProjectOutputFile, type ProjectOutputs } from '../../api/projects'
import { exportProjectFcpxml, exportProjectPrproj } from '../../api/exports'
import { getIntelligentRenderStatus, getQualityReport, runQualityCheck, type IntelligentRenderStatus, type QaReport } from '../../api/renders'
import AudioPlayer from '../../components/common/AudioPlayer.vue'
import { showToast, usePageFeedback } from '../../services/feedback'
import type { Project } from '../../types/project'
import { formatDuration } from '../../utils/time'

const route = useRoute()
const projectId = String(route.params.id)
const project = ref<Project | null>(null)
const outputs = ref<ProjectOutputs | null>(null)
const render = ref<IntelligentRenderStatus | null>(null)
const qa = ref<QaReport | null>(null)
const loading = ref(false)
const checking = ref(false)
const exporting = ref<'fcpxml' | 'prproj' | null>(null)
const error = ref('')
usePageFeedback(error, undefined, { errorTitle: '交付状态异常' })
const issueFilter = ref('all')
const artifactCategory = ref<ArtifactCategoryId>('delivery')
const artifactPage = ref(1)
const artifactPageSize = 30

type ArtifactCategoryId = 'delivery' | 'narration' | 'visual' | 'render' | 'reports' | 'project'

const artifactCategoryDefinitions = [
  { id: 'delivery', label: '最终交付', description: '成片、配音、字幕与可编辑工程', icon: FileArchive },
  { id: 'narration', label: '配音与字幕', description: '分段音频、时间轴与字幕数据', icon: FileAudio2 },
  { id: 'visual', label: '分镜与素材', description: '视觉分镜、候选素材与选择结果', icon: LayoutList },
  { id: 'render', label: '渲染中间件', description: '场景片段、预览与渲染过程产物', icon: Film },
  { id: 'reports', label: '质量与报告', description: 'QA、渲染报告、来源清单与日志', icon: ScrollText },
  { id: 'project', label: '项目数据', description: '输入、Manifest 与其他项目文件', icon: FolderOpen },
] as const

type ArtifactCategoryDefinition = typeof artifactCategoryDefinitions[number]

type ArtifactCategory = ArtifactCategoryDefinition & {
  files: ProjectOutputFile[]
  size: number
}

const finalVideo = computed(() => outputs.value?.files.find((file) => file.path === outputs.value?.final_video_path)
  || outputs.value?.files.find((file) => !/[\\/]/.test(file.relative_path) && /\.mp4$/i.test(file.name)))
const finalAudio = computed(() => outputs.value?.files.find((file) => file.path === outputs.value?.final_audio_path)
  || outputs.value?.files.find((file) => !/[\\/]/.test(file.relative_path) && /\.(wav|mp3)$/i.test(file.name)))
const filteredIssues = computed(() => (qa.value?.issues || []).filter((issue) => issueFilter.value === 'all' || issue.severity === issueFilter.value))
const durationDiff = computed(() => Math.abs((qa.value?.summary.video_duration_seconds || 0) - (qa.value?.summary.audio_duration_seconds || 0)))
const artifactCategories = computed<ArtifactCategory[]>(() => artifactCategoryDefinitions.map((definition) => {
  const files = (outputs.value?.files || [])
    .filter((file) => artifactCategoryFor(file) === definition.id)
    .sort((left, right) => right.modified_at - left.modified_at)
  return { ...definition, files, size: files.reduce((total, file) => total + file.size, 0) }
}))
const selectedArtifactCategory = computed(() => artifactCategories.value.find((category) => category.id === artifactCategory.value) || artifactCategories.value[0])
const artifactPageCount = computed(() => Math.max(1, Math.ceil(selectedArtifactCategory.value.files.length / artifactPageSize)))
const visibleArtifactFiles = computed(() => {
  const start = (artifactPage.value - 1) * artifactPageSize
  return selectedArtifactCategory.value.files.slice(start, start + artifactPageSize)
})

watch(artifactCategory, () => { artifactPage.value = 1 })

function formatSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function artifactKind(file: ProjectOutputFile) {
  const name = file.name.toLowerCase()
  const relativePath = file.relative_path.replace(/\\/g, '/').toLowerCase()
  if (/\.(wav|mp3)$/.test(name)) return { label: relativePath.startsWith('audio/segments/') ? '分段配音' : '完整配音', icon: FileAudio2, group: '配音' }
  if (name.endsWith('.srt')) return { label: 'SRT 字幕', icon: FileText, group: '字幕' }
  if (name.endsWith('.mp4')) return { label: relativePath.includes('/scenes/') || name.includes('scene') ? '场景视频' : name.includes('preview') ? '预览视频' : '最终视频', icon: FileVideo2, group: '视频' }
  if (name.endsWith('.fcpxml')) return { label: 'FCPXML 工程', icon: FileCode2, group: '工程' }
  if (name.endsWith('.prproj')) return { label: 'Premiere PRPROJ 工程', icon: FileCode2, group: '工程' }
  if (name.endsWith('.log')) return { label: '运行日志', icon: ScrollText, group: '日志' }
  if (name === 'manifest.json') return { label: '项目 Manifest', icon: FileCode2, group: '项目数据' }
  if (name === 'timeline.json') return { label: '配音时间轴', icon: FileCode2, group: '时间轴' }
  if (name === 'segments.json') return { label: '配音分段数据', icon: FileCode2, group: '分段' }
  if (name === 'scenes.json') return { label: '视觉分镜数据', icon: LayoutList, group: '分镜' }
  if (name.includes('candidate') || name.includes('selection') || name.includes('assignment')) return { label: '素材选择数据', icon: LayoutList, group: '素材' }
  if (name === 'qa.json') return { label: 'QA 质量报告', icon: ScrollText, group: '质量' }
  if (name.endsWith('.json') || name.endsWith('.csv')) return { label: relativePath.startsWith('reports/') ? '生产报告' : '结构化数据', icon: FileArchive, group: relativePath.startsWith('reports/') ? '报告' : '数据' }
  return { label: '项目文件', icon: FileArchive, group: '其他' }
}

function artifactCategoryFor(file: ProjectOutputFile): ArtifactCategoryId {
  const relativePath = file.relative_path.replace(/\\/g, '/').toLowerCase()
  const finalPaths = [
    outputs.value?.final_audio_path,
    outputs.value?.final_srt_path,
    outputs.value?.final_video_path,
    outputs.value?.final_fcpxml_path,
    outputs.value?.final_prproj_path,
  ].filter((path): path is string => Boolean(path))
  if (finalPaths.includes(file.path)) return 'delivery'
  if (/^(audio|subtitles|segments|timeline)\//.test(relativePath)) return 'narration'
  if (/^(storyboard|media|images|generated_images)\//.test(relativePath)) return 'visual'
  if (/^renders\//.test(relativePath)) return 'render'
  if (/^(reports|logs)\//.test(relativePath) || /(^|\/)(qa|.*report|asset_sources)\.(json|csv)$/.test(relativePath)) return 'reports'
  return 'project'
}

function artifactLocation(file: ProjectOutputFile) {
  const parts = file.relative_path.replace(/\\/g, '/').split('/')
  return parts.length > 1 ? parts.slice(0, -1).join(' / ') : '交付目录'
}

async function copyPath(path: string) {
  await navigator.clipboard.writeText(path)
  showToast({ title: '路径已复制', description: path, tone: 'success' })
}

async function checkQuality() {
  checking.value = true; error.value = ''
  try { qa.value = await runQualityCheck(projectId) }
  catch (err) { error.value = err instanceof Error ? err.message : '质量检查失败' }
  finally { checking.value = false }
}

async function exportEditable(format: 'fcpxml' | 'prproj') {
  exporting.value = format; error.value = ''
  try {
    if (format === 'fcpxml') await exportProjectFcpxml(projectId)
    else await exportProjectPrproj(projectId)
    await load()
    showToast({ title: `${format.toUpperCase()} 工程已生成`, tone: 'success' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '工程导出失败'
  } finally {
    exporting.value = null
  }
}

async function load() {
  loading.value = true; error.value = ''
  try {
    const [p, o] = await Promise.all([getProject(projectId), getProjectOutputs(projectId)])
    project.value = p; outputs.value = o
    try { render.value = await getIntelligentRenderStatus(projectId); qa.value = render.value.qa_report || null } catch { render.value = null }
    if (!qa.value) { try { qa.value = await getQualityReport(projectId) } catch { qa.value = null } }
  } catch (err) { error.value = err instanceof Error ? err.message : '交付中心加载失败' }
  finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <section class="delivery-page">
    <header class="page-header">
      <div><span class="section-eyebrow">QUALITY & DELIVERY</span><h1>质量与交付</h1><p>集中预览最终视频、处理 QA 问题，并获取全部生产产物。</p></div>
      <div class="page-title-actions"><button class="secondary-button" :disabled="loading || exporting !== null" @click="exportEditable('fcpxml')"><FileCode2 :size="16" /> {{ exporting === 'fcpxml' ? '正在生成…' : '生成 FCPXML' }}</button><button class="secondary-button" :disabled="loading || exporting !== null" @click="exportEditable('prproj')"><FileCode2 :size="16" /> {{ exporting === 'prproj' ? '正在转换…' : '生成 PRPROJ' }}</button><button class="secondary-button" :disabled="loading" @click="load"><RefreshCw :size="16" /> 刷新</button><a v-if="finalVideo" class="primary-link" :href="projectOutputFileUrl(projectId, finalVideo.path)" target="_blank"><ExternalLink :size="16" /> 打开最终视频</a></div>
    </header>

    <section class="delivery-video-grid">
      <article class="panel final-video-card">
        <div class="section-head"><div><span class="section-eyebrow">FINAL VIDEO</span><h2>最终视频</h2></div><span class="status-pill" :class="finalVideo ? 'is-success' : 'is-neutral'">{{ finalVideo ? '已生成' : '未生成' }}</span></div>
        <video v-if="finalVideo" controls preload="metadata" :src="projectOutputFileUrl(projectId, finalVideo.path)"></video>
        <div v-else class="video-empty"><FileVideo2 :size="40" /><strong>最终视频尚未生成</strong><p>先完成素材审核与视频渲染，成片会自动出现在这里。</p><RouterLink class="secondary-button" :to="`/projects/${projectId}/render`">前往视频渲染</RouterLink></div>
        <div v-if="finalVideo" class="video-file-meta"><span><strong>1920 × 1080</strong><small>输出分辨率</small></span><span><strong>{{ formatDuration(qa?.summary.video_duration_seconds || project?.audio_duration_seconds || 0) }}</strong><small>成片时长</small></span><span><strong>{{ formatSize(finalVideo.size) }}</strong><small>文件大小</small></span><a :href="projectOutputFileUrl(projectId, finalVideo.path, true)"><Download :size="15" /> 下载</a></div>
      </article>

      <article class="panel qa-summary-card" :class="qa?.passed ? 'is-passed' : qa ? 'is-failed' : ''">
        <div class="qa-result-icon"><component :is="qa?.passed ? CheckCircle2 : AlertTriangle" :size="27" /></div>
        <span class="section-eyebrow">QUALITY STATUS</span><h2>{{ qa ? (qa.passed ? '质量检查通过' : '需要处理质量问题') : '尚未执行质量检查' }}</h2><p>{{ qa?.passed ? '视频、配音、字幕和素材来源检查均符合当前规则。' : qa ? '请处理错误项后重新渲染或再次检查。' : '完成最终合成后运行一次完整质量检查。' }}</p>
        <div class="qa-summary-numbers"><span><strong>{{ qa?.summary.error_count || 0 }}</strong><small>Error</small></span><span><strong>{{ qa?.summary.warning_count || 0 }}</strong><small>Warning</small></span><span><strong>{{ Math.round(durationDiff * 1000) }} ms</strong><small>音视频时长差</small></span></div>
        <button class="secondary-button" :disabled="checking || !finalVideo" @click="checkQuality"><RefreshCw :size="15" /> {{ checking ? '检查中…' : '重新检查' }}</button>
      </article>
    </section>

    <section class="dashboard-section">
      <div class="section-toolbar"><div><span class="section-eyebrow">QA ISSUES</span><h2>质量问题</h2></div><div class="segmented-filter"><button :class="{ active: issueFilter === 'all' }" @click="issueFilter = 'all'">全部 {{ qa?.issues.length || 0 }}</button><button :class="{ active: issueFilter === 'error' }" @click="issueFilter = 'error'">错误 {{ qa?.summary.error_count || 0 }}</button><button :class="{ active: issueFilter === 'warning' }" @click="issueFilter = 'warning'">警告 {{ qa?.summary.warning_count || 0 }}</button></div></div>
      <article class="panel qa-table-panel">
        <div v-if="filteredIssues.length" class="qa-table qa-table-head"><span>级别</span><span>问题类型</span><span>场景 / 字幕</span><span>问题说明与修复建议</span><span>操作</span></div>
        <div v-for="issue in filteredIssues" :key="`${issue.type}-${issue.scene_id}-${issue.subtitle_id}-${issue.message}`" class="qa-table qa-table-row"><span><span class="status-pill" :class="issue.severity === 'error' ? 'is-danger' : 'is-warning'">{{ issue.severity }}</span></span><span>{{ issue.type }}</span><span>{{ issue.scene_id || issue.subtitle_id || '全局' }}</span><span><strong>{{ issue.message }}</strong><small>{{ issue.suggestion || '请定位关联生产步骤检查。' }}</small></span><span><RouterLink class="text-button" :to="issue.scene_id ? `/projects/${projectId}/render` : `/projects/${projectId}/subtitles`">定位</RouterLink></span></div>
        <div v-if="!filteredIssues.length" class="empty-state compact-empty"><CheckCircle2 :size="27" /><h2>{{ qa ? '当前筛选下没有问题' : '尚无 QA 报告' }}</h2><p>{{ qa ? '可以继续检查其他级别的问题。' : '运行质量检查后会显示可定位、可修复的问题列表。' }}</p></div>
      </article>
    </section>

    <section class="dashboard-section artifact-center">
      <div class="section-toolbar"><div><span class="section-eyebrow">ARTIFACT CENTER</span><h2>产物中心</h2><p>按交付件、制作数据和过程文件分类查看，避免全部文件混在一起。</p></div><span class="status-pill is-neutral">{{ outputs?.files.length || 0 }} 个文件</span></div>
      <AudioPlayer v-if="finalAudio" class="delivery-audio-player" :src="projectOutputFileUrl(projectId, finalAudio.path)" />
      <div v-if="outputs?.files.length" class="artifact-category-grid" role="tablist" aria-label="产物分类">
        <button v-for="category in artifactCategories" :key="category.id" class="artifact-category-card" :class="{ active: artifactCategory === category.id }" role="tab" :aria-selected="artifactCategory === category.id" @click="artifactCategory = category.id">
          <span class="artifact-category-icon"><component :is="category.icon" :size="19" /></span>
          <span><strong>{{ category.label }}</strong><small>{{ category.description }}</small></span>
          <span class="artifact-category-meta"><b>{{ category.files.length }}</b><small>{{ formatSize(category.size) }}</small></span>
        </button>
      </div>
      <article v-if="outputs?.files.length" class="panel artifact-file-panel">
        <header><div><span class="section-eyebrow">{{ selectedArtifactCategory.label }}</span><h3>{{ selectedArtifactCategory.description }}</h3></div><span>{{ selectedArtifactCategory.files.length }} 个文件 · {{ formatSize(selectedArtifactCategory.size) }}</span></header>
        <div v-if="selectedArtifactCategory.files.length" class="artifact-file-list">
          <div v-for="file in visibleArtifactFiles" :key="file.path" class="artifact-file-row">
            <span class="artifact-icon"><component :is="artifactKind(file).icon" :size="19" /></span>
            <div class="artifact-file-name"><strong>{{ file.name }}</strong><small>{{ artifactLocation(file) }}</small></div>
            <span class="artifact-file-type"><strong>{{ artifactKind(file).label }}</strong><small>{{ artifactKind(file).group }}</small></span>
            <span class="artifact-file-size">{{ formatSize(file.size) }}</span>
            <div class="artifact-actions"><a class="text-button" :href="projectOutputFileUrl(projectId, file.path)" target="_blank">预览</a><a class="text-button" data-tooltip="下载" :href="projectOutputFileUrl(projectId, file.path, true)"><Download :size="14" /></a><button class="text-button" data-tooltip="复制本地文件路径" @click="copyPath(file.path)"><Clipboard :size="14" /></button></div>
          </div>
        </div>
        <div v-else class="empty-state compact-empty"><FolderOpen :size="28" /><h2>该分类暂无产物</h2><p>完成对应生产步骤后，文件会自动归入这里。</p></div>
        <footer v-if="selectedArtifactCategory.files.length > artifactPageSize" class="artifact-pagination">
          <span>当前显示 {{ (artifactPage - 1) * artifactPageSize + 1 }}–{{ Math.min(artifactPage * artifactPageSize, selectedArtifactCategory.files.length) }} / {{ selectedArtifactCategory.files.length }}</span>
          <div><button class="text-button" :disabled="artifactPage === 1" data-tooltip="上一页" @click="artifactPage--"><ChevronLeft :size="15" /></button><strong>{{ artifactPage }} / {{ artifactPageCount }}</strong><button class="text-button" :disabled="artifactPage === artifactPageCount" data-tooltip="下一页" @click="artifactPage++"><ChevronRight :size="15" /></button></div>
        </footer>
      </article>
      <div v-else class="panel empty-state compact-empty"><FolderOpen :size="28" /><p>生产产物会按最终交付、配音字幕、分镜素材、渲染中间件和质量报告分类显示。</p></div>
    </section>
  </section>
</template>
