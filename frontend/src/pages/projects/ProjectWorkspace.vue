<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Check } from 'lucide-vue-next'

import { getProject } from '../../api/projects'
import { getProjectTaskStatus, type ProjectTaskStatus } from '../../api/tasks'
import ContinueWorkflowButton from '../../components/common/ContinueWorkflowButton.vue'
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
  const storyboardDone = ['asset_search', 'asset_review', 'scene_render', 'final_render', 'completed'].includes(stage) || status === 'completed'
  const reviewDone = ['scene_render', 'visual_track', 'final_render', 'completed'].includes(stage) || status === 'completed'
  const renderDone = status === 'completed'
  return [
    { path: 'overview', label: '项目概览', hint: '生成状态与结果', done: true },
    { path: 'narration', label: '一键生成', hint: '脚本、配音与成片', done: narrationDone },
    { path: 'storyboard', label: '视觉分镜', hint: '自动生成的镜头方案', done: storyboardDone },
    { path: 'media-review', label: '素材审核', hint: '逐分镜确认图片与视频', done: reviewDone },
    { path: 'render', label: '成片预览', hint: '查看最终视频', done: renderDone },
    { path: 'delivery', label: '质量与交付', hint: '质量检查与工程导出', done: renderDone },
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
      </nav>
    </aside>
    <div class="taf-project-outlet">
      <ContinueWorkflowButton :project-id="projectId" />
      <RouterView />
    </div>
  </section>
</template>
