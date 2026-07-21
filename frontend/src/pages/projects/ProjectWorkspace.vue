<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowLeft, Check, Circle, Settings2 } from 'lucide-vue-next'

import { getProject } from '../../api/projects'
import { getProjectTaskStatus, type ProjectTaskStatus } from '../../api/tasks'
import type { Project } from '../../types/project'

const route = useRoute()
const projectId = computed(() => String(route.params.id))
const project = ref<Project | null>(null)
const task = ref<ProjectTaskStatus | null>(null)
let timer: number | undefined

const items = computed(() => {
  const stage = task.value?.stage || ''
  const projectStatus = project.value?.status || ''
  const narrationDone = ['narration_ready', 'video_in_progress', 'review_required', 'completed'].includes(projectStatus)
  const subtitleDone = narrationDone
  const storyboardDone = ['asset_search', 'asset_review', 'image_generation', 'image_review', 'scene_render', 'visual_track', 'final_render', 'quality_check', 'quality_review', 'completed'].includes(stage) || ['review_required', 'completed'].includes(projectStatus)
  const mediaDone = ['scene_render', 'visual_track', 'final_render', 'quality_check', 'quality_review', 'completed'].includes(stage) || projectStatus === 'completed'
  const renderDone = projectStatus === 'completed' || ['quality_check', 'quality_review', 'completed'].includes(stage)
  return [
    { path: 'overview', label: '项目概览', done: true },
    { path: 'narration', label: '逐字稿与配音', done: narrationDone },
    { path: 'subtitles', label: '字幕与时间轴', done: subtitleDone },
    { path: 'storyboard', label: '视觉分镜', done: storyboardDone },
    { path: 'media-review', label: '素材审核', done: mediaDone },
    { path: 'render', label: '视频渲染', done: renderDone },
    { path: 'delivery', label: '质量与交付', done: projectStatus === 'completed' },
  ]
})

const statusLabel = computed(() => ({
  created: '待开始', narration_in_progress: '配音生成中', narration_ready: '配音字幕已就绪',
  video_in_progress: '视频生成中', review_required: '等待人工复核', completed: '已完成', failed: '执行失败',
}[project.value?.status || ''] || project.value?.status || '加载中'))

async function load() {
  try {
    const [loadedProject, loadedTask] = await Promise.all([getProject(projectId.value), getProjectTaskStatus(projectId.value)])
    project.value = loadedProject
    task.value = loadedTask
  } catch {
    // Child pages surface actionable API errors.
  }
}

onMounted(() => {
  void load()
  timer = window.setInterval(load, 10000)
})
onBeforeUnmount(() => { if (timer !== undefined) window.clearInterval(timer) })
</script>

<template>
  <section class="project-workspace">
    <header class="project-context-bar">
      <RouterLink class="project-back" to="/projects"><ArrowLeft :size="16" /> 项目</RouterLink>
      <span class="project-context-divider"></span>
      <div><strong>{{ project?.name || '加载项目…' }}</strong><small>{{ statusLabel }}</small></div>
      <span class="project-context-meta">{{ project?.config?.video_mode === 'none' ? '仅配音字幕' : project?.config?.video_output_format === 'fcpxml' ? 'FCPXML 工程' : '完整 MP4' }}</span>
      <RouterLink class="project-settings-link" :to="`/projects/${projectId}/settings`"><Settings2 :size="15" /> 项目设置</RouterLink>
    </header>

    <nav class="project-step-nav" aria-label="项目生产步骤">
      <RouterLink v-for="item in items" :key="item.path" :to="`/projects/${projectId}/${item.path}`" active-class="is-active">
        <span class="step-state"><Check v-if="item.done" :size="13" /><Circle v-else :size="10" /></span>
        <span>{{ item.label }}</span>
      </RouterLink>
      <RouterLink :to="`/projects/${projectId}/settings`" active-class="is-active"><span class="step-state"><Settings2 :size="13" /></span><span>项目设置</span></RouterLink>
    </nav>

    <div class="project-page-outlet"><RouterView /></div>
  </section>
</template>
