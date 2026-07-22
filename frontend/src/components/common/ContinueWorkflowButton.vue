<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { LoaderCircle, Play } from 'lucide-vue-next'

import {
  continueProjectWorkflow,
  getProjectTaskStatus,
  type ProjectTaskStatus,
} from '../../api/tasks'

const props = defineProps<{ projectId: string }>()
const task = ref<ProjectTaskStatus | null>(null)
const submitting = ref(false)
const message = ref('')
const error = ref('')
let timer: number | undefined

const active = computed(() => task.value?.status === 'queued' || task.value?.status === 'running')
const stageLabels: Record<string, string> = {
  segmenting: '文本切段', tts: '分段配音', audio_merge: '完整配音合成', subtitles: '时间轴与字幕',
  video: '视频合成', storyboard: '视觉分镜', asset_search: '素材检索与自动选择',
  asset_review: '素材自动审核', image_generation: '画面生成', image_review: '画面自动审核',
  scene_render: '场景渲染', visual_track: '画面轨道合成', final_render: '最终视频合成',
  quality_check: '质量检查', quality_review: '质量复核', fcpxml_export: 'FCPXML 导出',
  prproj_export: 'Premiere 工程导出', editable_export: '可编辑工程导出', completed: '全部完成',
}
const statusText = computed(() => {
  if (message.value) return message.value
  if (!active.value) return '系统会从最早缺失的产物开始，连续执行到最终交付。'
  const label = stageLabels[task.value?.stage || ''] || task.value?.stage || '准备任务'
  return task.value?.status === 'queued' ? `已排队：${label}` : `正在执行：${label}`
})

async function refresh() {
  try {
    task.value = await getProjectTaskStatus(props.projectId)
    if (task.value.status === 'failed') error.value = task.value.error_message || '自动流程执行失败'
  } catch { /* The page-level loader will surface connectivity errors. */ }
}

async function runRemainingWorkflow() {
  submitting.value = true
  error.value = ''
  message.value = ''
  try {
    task.value = await continueProjectWorkflow(props.projectId)
    message.value = task.value.status === 'completed'
      ? '全部配置流程已经完成。'
      : '后续全部流程已加入后台任务。'
    await refresh()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '无法启动后续流程'
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  void refresh()
  timer = window.setInterval(refresh, 3000)
})
onBeforeUnmount(() => { if (timer !== undefined) window.clearInterval(timer) })
</script>

<template>
  <section class="continue-workflow-bar" aria-label="后续自动工作流">
    <div>
      <strong>一键执行后续全部流程</strong>
      <span :class="{ error: Boolean(error) }">{{ error || statusText }}</span>
    </div>
    <button class="primary-button" type="button" :disabled="submitting || active" @click="runRemainingWorkflow">
      <LoaderCircle v-if="submitting || active" :size="16" class="spin" />
      <Play v-else :size="16" />
      {{ active ? '自动流程执行中' : submitting ? '正在启动' : '执行后续全部流程' }}
    </button>
  </section>
</template>

<style scoped>
.continue-workflow-bar { align-items: center; background: #edf7f5; border: 1px solid #badbd5; border-radius: 12px; display: flex; gap: 18px; justify-content: space-between; margin-bottom: 16px; padding: 13px 16px; }
.continue-workflow-bar > div { display: grid; gap: 3px; }
.continue-workflow-bar strong { color: #163b3f; font-size: 14px; }
.continue-workflow-bar span { color: #557276; font-size: 12px; }
.continue-workflow-bar span.error { color: #b23b3b; }
.continue-workflow-bar button { align-items: center; display: inline-flex; flex: 0 0 auto; gap: 7px; }
.spin { animation: continue-spin 1s linear infinite; }
@keyframes continue-spin { to { transform: rotate(360deg); } }
@media (max-width: 720px) { .continue-workflow-bar { align-items: stretch; flex-direction: column; } .continue-workflow-bar button { justify-content: center; } }
</style>
