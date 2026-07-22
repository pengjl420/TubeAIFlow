<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  ArrowRight, FileAudio2, FileText, Film,
  FolderKanban, Play, Star, Volume2,
} from 'lucide-vue-next'

import { listSegments } from '../../api/narration'
import { getProject, getProjectOutputs, type ProjectOutputs } from '../../api/projects'
import { getIntelligentRenderStatus, type IntelligentRenderStatus } from '../../api/renders'
import { getStoryboard } from '../../api/storyboard'
import { getProjectTaskStatus, type ProjectTaskStatus } from '../../api/tasks'
import { usePageFeedback } from '../../services/feedback'
import type { Project } from '../../types/project'
import type { Segment } from '../../types/narration'
import type { VisualScene } from '../../types/storyboard'
import { formatDuration } from '../../utils/time'

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
usePageFeedback(error, undefined, { errorTitle: '项目概览未能更新' })

const completedSegments = computed(() => segments.value.filter((item) => item.status === 'completed').length)
const confirmedScenes = computed(() => render.value?.assignment_count || 0)
const hasAudio = computed(() => outputs.value?.final_audio_exists === true || Boolean(outputs.value?.files.some((file) => /\.(wav|mp3)$/i.test(file.name))))
const hasVideo = computed(() => Boolean(render.value?.final_video_exists || outputs.value?.final_video_exists))
const statusLabel = computed(() => ({
  created: '待开始', narration_in_progress: '自动生成中', narration_ready: '配音已完成',
  video_in_progress: '自动生成中', review_required: '旧任务待恢复', completed: '已完成', failed: '执行失败',
}[project.value?.status || ''] || '生产中'))

const flow = computed(() => [
  { label: '逐字稿', icon: FileText, done: segments.value.length > 0, path: 'narration' },
  { label: '配音', icon: Volume2, done: hasAudio.value, path: 'narration' },
  { label: '分镜', icon: Film, done: scenes.value.length > 0, path: 'storyboard' },
  { label: '自动选材', icon: FolderKanban, done: scenes.value.length > 0 && confirmedScenes.value >= scenes.value.length, path: 'render' },
  { label: '渲染', icon: Play, done: hasVideo.value, path: 'render' },
])
const activeFlowIndex = computed(() => {
  const index = flow.value.findIndex((item) => !item.done)
  return index < 0 ? flow.value.length - 1 : index
})

const nextAction = computed(() => {
  if (project.value?.status === 'failed') return { title: '生产任务执行失败', detail: task.value?.error_message || '请查看任务详情并从检查点重新执行。', label: '查看详情', path: '/tasks' }
  if (!segments.value.length) return { title: '逐字稿与配音', detail: '项目尚未生成口播分段，完成脚本后才能继续生产。', label: '进入逐字稿', path: `/projects/${projectId}/narration` }
  if (task.value?.status === 'running' || task.value?.status === 'queued') return { title: '正在自动生成', detail: '系统会自动完成剩余步骤，无需人工介入。', label: '查看生成进度', path: `/projects/${projectId}/narration` }
  if (!hasVideo.value) return { title: '开始一键生成', detail: '系统将自动完成配音、分镜、选材和渲染。', label: '进入一键生成', path: `/projects/${projectId}/narration` }
  return { title: '成片已生成', detail: '最终视频已经可以预览。', label: '查看成片', path: `/projects/${projectId}/render` }
})

const recentTasks = computed(() => [
  { type: '配音合成', stage: '逐字稿与配音', time: '18 分钟前', state: hasAudio.value ? '已完成' : '进行中', icon: FileAudio2 },
  { type: '逐字稿生成', stage: '逐字稿与配音', time: '32 分钟前', state: segments.value.length ? '已完成' : '未开始', icon: FileText },
  { type: '素材匹配', stage: '视觉分镜', time: '—', state: scenes.value.length ? '进行中' : '未开始', icon: FolderKanban },
  { type: '视频渲染', stage: '视频渲染', time: '—', state: hasVideo.value ? '已完成' : '未开始', icon: Film },
])
function stateTone(state: string) { return state === '已完成' ? 'green' : state === '进行中' ? 'orange' : 'gray' }
function videoMode() {
  const mode = project.value?.config?.video_mode
  return mode === 'none' ? '仅完整配音' : mode === 'landscape' ? 'Vlog 16:9' : mode === 'ai_generated_images' ? '图文快剪 16:9' : '横版 16:9'
}

async function load() {
  loading.value = true; error.value = ''
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
  <section class="taf-project-overview">
    <header class="taf-project-hero">
      <div><div class="taf-project-title"><h1>{{ project?.name || '加载项目...' }}</h1><Star :size="22" /></div><p>生命周期：<b class="taf-status-badge green">{{ statusLabel }}</b><i></i>视频模式：{{ videoMode() }}<i></i>音色：{{ project?.config?.voice_profile_name || '未配置' }}<i></i>总时长：{{ formatDuration(project?.audio_duration_seconds || 0) }}</p></div>
      <div><RouterLink class="primary-link" :to="nextAction.path">{{ hasVideo ? '查看成片' : '进入一键生成' }} <ArrowRight :size="17" /></RouterLink></div>
    </header>


    <section class="taf-card taf-flow-card">
      <h2>生产流程状态</h2>
      <div class="taf-flow-row">
        <template v-for="(item, index) in flow" :key="item.label">
          <RouterLink :to="`/projects/${projectId}/${item.path}`" class="taf-flow-step" :class="{ done: item.done, active: index === activeFlowIndex }"><span><component :is="item.icon" :size="21" /></span><div><strong>{{ item.label }}</strong><small>{{ item.done ? '已完成' : index === activeFlowIndex ? '进行中' : '未开始' }}</small></div></RouterLink>
          <i v-if="index < flow.length - 1" class="taf-flow-line" :class="{ done: item.done }"></i>
        </template>
      </div>
    </section>

    <div class="taf-overview-grid">
      <section class="taf-card taf-current-action-card">
        <h2>当前需要处理</h2>
        <div class="taf-action-box"><div class="taf-action-heading"><span><Play :size="20" /></span><strong>{{ nextAction.title }}</strong><b>· {{ task?.status === 'running' ? '进行中' : hasVideo ? '已完成' : '可开始' }}</b></div><p>{{ nextAction.detail }}</p><div><RouterLink class="primary-link" :to="nextAction.path">{{ nextAction.label }}</RouterLink><RouterLink class="secondary-button" to="/tasks">查看任务</RouterLink></div></div>
      </section>

      <section class="taf-card taf-production-info">
        <h2>生产信息</h2>
        <div class="taf-info-stats"><div><span>配音分段数</span><strong>{{ segments.length }} <small>段</small></strong><em>已完成 {{ completedSegments }}</em></div><div><span>完整配音</span><strong>{{ hasAudio ? '已生成' : '未生成' }}</strong><em>{{ formatDuration(project?.audio_duration_seconds || 0) }}</em></div><div><span>场景数量</span><strong>{{ scenes.length }} <small>个</small></strong><em>{{ scenes.length ? '已生成' : '未开始' }}</em></div><div><span>自动选材场景</span><strong>{{ confirmedScenes }} <small>个</small></strong><em>{{ scenes.length ? Math.round(confirmedScenes / scenes.length * 100) : 0 }}%</em></div></div>
        <div class="taf-info-bottom"><div><span>视频渲染进度</span><i><b :style="{ width: `${render?.scene_count ? (render.rendered_scene_count || 0) / render.scene_count * 100 : 0}%` }"></b></i><strong>{{ render?.scene_count ? Math.round((render.rendered_scene_count || 0) / render.scene_count * 100) : 0 }}%</strong><small>{{ hasVideo ? '已完成' : '未开始' }}</small></div></div>
      </section>
    </div>

    <div class="taf-overview-grid lower">
      <section class="taf-card taf-recent-tasks">
        <header><h2>最近任务</h2><RouterLink to="/tasks">查看全部任务 <ArrowRight :size="14" /></RouterLink></header>
        <div class="taf-recent-task-head"><span>任务类型</span><span>当前阶段</span><span>运行时间</span><span>状态</span><span>操作</span></div>
        <div v-for="item in recentTasks" :key="item.type" class="taf-recent-task-row"><span><component :is="item.icon" :size="15" />{{ item.type }}</span><span>{{ item.stage }}</span><span>{{ item.time }}</span><span><b class="taf-status-badge" :class="stateTone(item.state)">{{ item.state }}</b></span><span><RouterLink to="/tasks">查看详情</RouterLink></span></div>
      </section>

      <section class="taf-card taf-artifact-summary">
        <h2>项目产物摘要</h2>
        <div class="taf-artifact-items">
          <article><strong>配音</strong><div class="taf-wave"><i v-for="n in 20" :key="n" :style="{ height: `${8 + (n * 7) % 26}px` }"></i></div><footer><button><Play :size="14" /></button><span>{{ formatDuration(project?.audio_duration_seconds || 0) }}</span></footer><RouterLink :to="`/projects/${projectId}/narration`">预览</RouterLink></article>
          <article class="video"><strong>最终视频</strong><div class="taf-video-preview"><Film :size="34" /><button><Play :size="14" /></button></div><footer><span>{{ hasVideo ? formatDuration(project?.audio_duration_seconds || 0) : '尚未生成' }}</span></footer><RouterLink :to="`/projects/${projectId}/render`">{{ hasVideo ? '预览' : '查看' }}</RouterLink></article>
        </div>
      </section>
    </div>
  </section>
</template>
