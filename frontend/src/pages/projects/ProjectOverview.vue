<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { AlertTriangle, ArrowRight, Check, FileAudio2, FileText, Film, Layers3, RefreshCw, Settings2 } from 'lucide-vue-next'

import { listSegments } from '../../api/narration'
import { getProject, getProjectOutputs, type ProjectOutputs } from '../../api/projects'
import { getIntelligentRenderStatus, type IntelligentRenderStatus } from '../../api/renders'
import { getStoryboard } from '../../api/storyboard'
import { getProjectTaskStatus, type ProjectTaskStatus } from '../../api/tasks'
import type { Project } from '../../types/project'
import type { Segment } from '../../types/narration'
import type { VisualScene } from '../../types/storyboard'
import { formatDateTime, formatDuration } from '../../utils/time'

const route = useRoute()
const projectId = String(route.params.id)
const project = ref<Project | null>(null)
const task = ref<ProjectTaskStatus | null>(null)
const outputs = ref<ProjectOutputs | null>(null)
const segments = ref<Segment[]>([])
const scenes = ref<VisualScene[]>([])
const render = ref<IntelligentRenderStatus | null>(null)
const loading = ref(false)
const error = ref('')

const completedSegments = computed(() => segments.value.filter((item) => item.status === 'completed').length)
const confirmedScenes = computed(() => render.value?.assignment_count || 0)
const qaErrors = computed(() => render.value?.qa_report?.summary.error_count || 0)
const statusLabel = computed(() => ({
  created: '待开始', narration_in_progress: '配音生成中', narration_ready: '配音字幕已就绪',
  video_in_progress: '视频生成中', review_required: '等待人工复核', completed: '已完成', failed: '执行失败',
}[project.value?.status || ''] || project.value?.status || '未知'))

const flow = computed(() => {
  if (project.value?.status === 'completed') return ['逐字稿', '配音', '字幕', '分镜', '素材', '渲染', 'QA'].map((label) => ({ label, done: true }))
  const audioReady = outputs.value?.final_audio_exists === true || Boolean(outputs.value?.files.some((file) => /\.(wav|mp3)$/i.test(file.name)))
  const subtitleReady = outputs.value?.final_srt_exists === true || Boolean(outputs.value?.files.some((file) => file.name.toLowerCase().endsWith('.srt')))
  const storyboardReady = scenes.value.length > 0
  const materialReady = storyboardReady && confirmedScenes.value >= scenes.value.length
  const renderReady = Boolean(render.value?.final_video_exists || render.value?.final_fcpxml_exists)
  const qaReady = Boolean(render.value?.qa_report?.passed)
  return [
    { label: '逐字稿', done: segments.value.length > 0 }, { label: '配音', done: audioReady },
    { label: '字幕', done: subtitleReady }, { label: '分镜', done: storyboardReady },
    { label: '素材', done: materialReady }, { label: '渲染', done: renderReady }, { label: 'QA', done: qaReady },
  ]
})

const nextAction = computed(() => {
  if (project.value?.status === 'failed') return { title: '生产任务执行失败', detail: task.value?.error_message || '请查看任务详情并从检查点重新执行。', label: '查看任务', path: '/tasks' }
  if (project.value?.status === 'completed') return { title: '查看并交付最终产物', detail: '项目生产已完成，可在产物中心预览、下载或复制文件路径。', label: '质量与交付', path: `/projects/${projectId}/delivery` }
  if (!segments.value.length) return { title: '准备逐字稿并生成配音', detail: '项目尚未生成口播分段，这是后续字幕与视频生产的前置条件。', label: '编辑逐字稿', path: `/projects/${projectId}/narration` }
  if (!(outputs.value?.final_srt_exists || outputs.value?.files.some((file) => file.name.toLowerCase().endsWith('.srt')))) return { title: '完成配音与字幕时间轴', detail: `已有 ${completedSegments.value}/${segments.value.length} 段配音完成。`, label: '继续生成配音', path: `/projects/${projectId}/narration` }
  if (!scenes.value.length) return { title: '确认字幕并生成视觉分镜', detail: '字幕就绪后，可按叙事语义合并为视觉场景。', label: '校对字幕', path: `/projects/${projectId}/subtitles` }
  if (confirmedScenes.value < scenes.value.length) return { title: '审核场景素材', detail: `还有 ${scenes.value.length - confirmedScenes.value} 个场景没有确认素材。`, label: '审核素材', path: `/projects/${projectId}/media-review` }
  if (!(render.value?.final_video_exists || render.value?.final_fcpxml_exists)) return { title: '开始场景渲染与最终合成', detail: '场景素材已经确认，可以进入渲染工作流。', label: '开始渲染', path: `/projects/${projectId}/render` }
  return { title: qaErrors.value ? '处理质量检查问题' : '查看并交付最终产物', detail: qaErrors.value ? `QA 检测到 ${qaErrors.value} 个错误。` : '核心生产步骤已完成。', label: '质量与交付', path: `/projects/${projectId}/delivery` }
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [p, t, o, s] = await Promise.all([getProject(projectId), getProjectTaskStatus(projectId), getProjectOutputs(projectId), listSegments(projectId)])
    project.value = p; task.value = t; outputs.value = o; segments.value = s
    try { scenes.value = await getStoryboard(projectId) } catch { scenes.value = [] }
    try { render.value = await getIntelligentRenderStatus(projectId) } catch { render.value = null }
  } catch (err) { error.value = err instanceof Error ? err.message : '项目概览加载失败' }
  finally { loading.value = false }
}

onMounted(load)
</script>

<template>
  <section class="project-overview-page">
    <header class="page-header">
      <div><span class="section-eyebrow">PROJECT COCKPIT</span><div class="project-title-row"><h1>项目概览</h1><span class="status-pill" :class="project?.status === 'failed' ? 'is-danger' : project?.status === 'completed' ? 'is-success' : project?.status === 'review_required' ? 'is-warning' : 'is-neutral'">{{ statusLabel }}</span></div><p>{{ project?.name }} 的生产驾驶舱，集中显示当前进度、阻塞项与交付状态。</p></div>
      <div class="page-title-actions"><button class="secondary-button" :disabled="loading" @click="load"><RefreshCw :size="16" /> 刷新</button><RouterLink class="primary-link" :to="nextAction.path">{{ nextAction.label }} <ArrowRight :size="15" /></RouterLink></div>
    </header>

    <div v-if="error" class="alert alert-danger"><strong>概览未能更新</strong><span>{{ error }}</span></div>

    <div class="overview-facts panel">
      <div><span>视频模式</span><strong>{{ project?.config?.video_mode || '未配置' }}</strong></div>
      <div><span>当前音色</span><strong>{{ project?.config?.voice_profile_name || '未配置' }}</strong></div>
      <div><span>配音时长</span><strong>{{ formatDuration(project?.audio_duration_seconds || 0) }}</strong></div>
      <div><span>最近更新</span><strong>{{ project?.updated_at ? formatDateTime(project.updated_at) : '—' }}</strong></div>
      <RouterLink :to="`/projects/${projectId}/settings`"><Settings2 :size="15" /> 设置</RouterLink>
    </div>

    <div class="production-flow panel">
      <div v-for="(item, index) in flow" :key="item.label" class="production-flow-step" :class="{ 'is-done': item.done }"><span>{{ item.done ? '✓' : index + 1 }}</span><strong>{{ item.label }}</strong></div>
    </div>

    <article class="panel next-action-panel" :class="{ 'has-error': project?.status === 'failed' }">
      <span class="next-action-icon"><component :is="project?.status === 'failed' ? AlertTriangle : ArrowRight" :size="22" /></span>
      <div><span class="section-eyebrow">NEXT ACTION</span><h2>{{ nextAction.title }}</h2><p>{{ nextAction.detail }}</p></div>
      <RouterLink class="primary-link" :to="nextAction.path">{{ nextAction.label }} <ArrowRight :size="15" /></RouterLink>
    </article>

    <div class="overview-stat-grid">
      <article class="panel"><FileAudio2 :size="20" /><span>配音分段</span><strong>{{ completedSegments }}/{{ segments.length }}</strong><small>已完成</small></article>
      <article class="panel"><FileText :size="20" /><span>字幕数量</span><strong>{{ segments.length }}</strong><small>基于真实音频时间轴</small></article>
      <article class="panel"><Layers3 :size="20" /><span>视觉场景</span><strong>{{ scenes.length }}</strong><small>{{ confirmedScenes }} 个已确认素材</small></article>
      <article class="panel"><Film :size="20" /><span>场景渲染</span><strong>{{ render?.rendered_scene_count || 0 }}/{{ render?.scene_count || scenes.length }}</strong><small>中间片段</small></article>
      <article class="panel"><AlertTriangle :size="20" /><span>QA 错误</span><strong>{{ qaErrors }}</strong><small>{{ render?.qa_report?.summary.warning_count || 0 }} 个警告</small></article>
    </div>

    <div class="overview-bottom-grid">
      <article class="panel"><div class="section-head"><div><span class="section-eyebrow">LATEST TASK</span><h2>最近任务</h2></div><span class="status-pill is-neutral">{{ task?.status || 'idle' }}</span></div><dl class="output-path-list"><div><dt>当前阶段</dt><dd>{{ task?.stage || '尚未启动' }}</dd></div><div><dt>任务编号</dt><dd>{{ task?.id || '—' }}</dd></div><div><dt>运行耗时</dt><dd>{{ formatDuration(task?.workflow_duration_seconds || 0) }}</dd></div></dl></article>
      <article class="panel"><div class="section-head"><div><span class="section-eyebrow">OUTPUTS</span><h2>项目产物摘要</h2></div><RouterLink :to="`/projects/${projectId}/delivery`">全部产物</RouterLink></div><div class="artifact-summary-list"><span :class="{ ready: outputs?.final_audio_exists || outputs?.files.some((file) => /\.(wav|mp3)$/i.test(file.name)) }"><Check :size="14" /> 完整配音</span><span :class="{ ready: outputs?.final_srt_exists || outputs?.files.some((file) => file.name.toLowerCase().endsWith('.srt')) }"><Check :size="14" /> SRT 字幕</span><span :class="{ ready: render?.final_video_exists || render?.final_fcpxml_exists || outputs?.final_video_exists || outputs?.final_fcpxml_exists }"><Check :size="14" /> 最终视频</span><span :class="{ ready: render?.qa_report }"><Check :size="14" /> QA 报告</span></div></article>
    </div>
  </section>
</template>
