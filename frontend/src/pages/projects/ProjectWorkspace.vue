<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Check, Settings2 } from 'lucide-vue-next'

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
  const status = project.value?.status || ''
  const narrationDone = ['narration_ready', 'video_in_progress', 'review_required', 'completed'].includes(status)
  const storyboardDone = ['asset_search', 'asset_review', 'scene_render', 'final_render', 'quality_check', 'quality_review', 'completed'].includes(stage) || ['review_required', 'completed'].includes(status)
  const mediaDone = ['scene_render', 'final_render', 'quality_check', 'quality_review', 'completed'].includes(stage) || status === 'completed'
  const renderDone = status === 'completed' || ['quality_check', 'quality_review', 'completed'].includes(stage)
  return [
    { path: 'overview', label: '项目概览', hint: '全局状态与下一步', done: true },
    { path: 'narration', label: '逐字稿与配音', hint: '脚本生成与配音合成', done: narrationDone },
    { path: 'subtitles', label: '字幕与时间轴', hint: '字幕校对与时间轴', done: narrationDone },
    { path: 'storyboard', label: '视觉分镜', hint: '镜头设计与分镜', done: storyboardDone },
    { path: 'media-review', label: '素材审核', hint: '素材筛选与合规审核', done: mediaDone },
    { path: 'render', label: '视频渲染', hint: '视频合成与渲染输出', done: renderDone },
    { path: 'delivery', label: '质量与交付', hint: 'QA 检测与交付', done: status === 'completed' },
  ]
})

async function load() {
  try { [project.value, task.value] = await Promise.all([getProject(projectId.value), getProjectTaskStatus(projectId.value)]) }
  catch { /* child page displays actionable errors */ }
}
onMounted(() => { void load(); timer = window.setInterval(load, 10000) })
onBeforeUnmount(() => { if (timer !== undefined) window.clearInterval(timer) })
</script>

<template>
  <section class="taf-project-workspace">
    <aside class="taf-project-nav">
      <h2>项目导航</h2>
      <nav aria-label="项目生产步骤">
        <RouterLink v-for="(item, index) in items" :key="item.path" :to="`/projects/${projectId}/${item.path}`" active-class="is-active">
          <span class="taf-step-number"><Check v-if="item.done && index > 0" :size="14" /> <template v-else>{{ index + 1 }}</template></span>
          <span><strong>{{ item.label }}</strong><small>{{ item.hint }}</small></span>
        </RouterLink>
        <RouterLink :to="`/projects/${projectId}/settings`" active-class="is-active">
          <span class="taf-step-number">8</span><span><strong>项目设置</strong><small>项目信息与成员权限</small></span>
        </RouterLink>
      </nav>
    </aside>
    <div class="taf-project-outlet"><RouterView /></div>
  </section>
</template>
