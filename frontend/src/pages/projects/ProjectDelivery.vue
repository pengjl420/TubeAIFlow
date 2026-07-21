<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { AlertTriangle, CheckCircle2, Clipboard, Download, ExternalLink, FileArchive, FileAudio2, FileCode2, FileText, FileVideo2, FolderOpen, RefreshCw } from 'lucide-vue-next'

import { getProject, getProjectOutputs, projectOutputFileUrl, type ProjectOutputFile, type ProjectOutputs } from '../../api/projects'
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
const error = ref('')
usePageFeedback(error, undefined, { errorTitle: '交付状态异常' })
const issueFilter = ref('all')

const finalVideo = computed(() => outputs.value?.files.find((file) => file.path === outputs.value?.final_video_path || file.name.toLowerCase().endsWith('.mp4')))
const finalAudio = computed(() => outputs.value?.files.find((file) => file.path === outputs.value?.final_audio_path || /\.(wav|mp3)$/i.test(file.name)))
const filteredIssues = computed(() => (qa.value?.issues || []).filter((issue) => issueFilter.value === 'all' || issue.severity === issueFilter.value))
const durationDiff = computed(() => Math.abs((qa.value?.summary.video_duration_seconds || 0) - (qa.value?.summary.audio_duration_seconds || 0)))

function formatSize(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function artifactKind(file: ProjectOutputFile) {
  const name = file.name.toLowerCase()
  if (/\.(wav|mp3)$/.test(name)) return { label: '完整配音', icon: FileAudio2, group: '配音' }
  if (name.endsWith('.srt')) return { label: 'SRT 字幕', icon: FileText, group: '字幕' }
  if (name.endsWith('.mp4')) return { label: name.includes('scene') ? '场景视频' : '最终视频', icon: FileVideo2, group: '视频' }
  if (name.endsWith('.fcpxml')) return { label: 'FCPXML 工程', icon: FileCode2, group: '工程' }
  if (name.endsWith('.json') || name.endsWith('.csv')) return { label: '生产报告', icon: FileArchive, group: '报告' }
  return { label: '项目文件', icon: FileArchive, group: '其他' }
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
      <div class="page-title-actions"><button class="secondary-button" :disabled="loading" @click="load"><RefreshCw :size="16" /> 刷新</button><a v-if="finalVideo" class="primary-link" :href="projectOutputFileUrl(projectId, finalVideo.path)" target="_blank"><ExternalLink :size="16" /> 打开最终视频</a></div>
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

    <section class="dashboard-section">
      <div class="section-toolbar"><div><span class="section-eyebrow">ARTIFACT CENTER</span><h2>产物中心</h2></div><span class="status-pill is-neutral">{{ outputs?.files.length || 0 }} 个文件</span></div>
      <AudioPlayer v-if="finalAudio" class="delivery-audio-player" :src="projectOutputFileUrl(projectId, finalAudio.path)" />
      <div class="delivery-artifact-grid">
        <article v-for="file in outputs?.files" :key="file.path" class="panel delivery-artifact-card">
          <span class="artifact-icon"><component :is="artifactKind(file).icon" :size="20" /></span><div><span class="section-eyebrow">{{ artifactKind(file).group }}</span><h3>{{ artifactKind(file).label }}</h3><p>{{ file.name }}</p><small>{{ formatSize(file.size) }}</small></div>
          <div class="artifact-actions"><a class="text-button" :href="projectOutputFileUrl(projectId, file.path)" target="_blank">预览</a><a class="text-button" :href="projectOutputFileUrl(projectId, file.path, true)"><Download :size="14" /></a><button class="text-button" data-tooltip="复制本地文件路径" @click="copyPath(file.path)"><Clipboard :size="14" /></button></div>
        </article>
        <article v-if="!outputs?.files.length" class="panel empty-state compact-empty"><FolderOpen :size="28" /><p>生产产物会按配音、字幕、分镜、素材、视频和报告集中显示。</p></article>
      </div>
    </section>
  </section>
</template>
