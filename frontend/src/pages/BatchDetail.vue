<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import { getBatch, pauseBatch, retryBatchItem, startBatch, type BatchJob } from '../api/batches'

const route = useRoute()
const batchId = String(route.params.id)
const batch = ref<BatchJob | null>(null)
const loading = ref(false)
const acting = ref(false)
const error = ref('')
let pollTimer: number | undefined

const percent = computed(() => {
  if (!batch.value?.total) return 0
  return Math.round(((batch.value.completed + batch.value.failed) / batch.value.total) * 100)
})

const canPause = computed(() => batch.value?.status === 'queued' || batch.value?.status === 'running')
const canResume = computed(() => batch.value?.status === 'paused' || batch.value?.status === 'draft')

const stageLabels: Record<string, string> = {
  segmenting: '生成切段',
  tts: '生成分段音频',
  audio_merge: '合并完整音频',
  subtitles: '生成中英文字幕',
  video: '生成视频',
  completed: '完成',
}

function stageLabel(stage: string) {
  return stageLabels[stage] || stage
}

function stopPolling() {
  if (pollTimer !== undefined) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    batch.value = await getBatch(batchId)
    if (['completed', 'completed_with_errors'].includes(batch.value.status)) stopPolling()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '批次加载失败'
  } finally {
    loading.value = false
  }
}

async function pause() {
  acting.value = true
  error.value = ''
  try {
    batch.value = await pauseBatch(batchId)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '暂停失败'
  } finally {
    acting.value = false
  }
}

async function resume() {
  acting.value = true
  error.value = ''
  try {
    batch.value = await startBatch(batchId)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '继续失败'
  } finally {
    acting.value = false
  }
}

async function retry(itemId: string) {
  acting.value = true
  error.value = ''
  try {
    await retryBatchItem(batchId, itemId)
    await load(true)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '重试失败'
  } finally {
    acting.value = false
  }
}

onMounted(async () => {
  await load()
  pollTimer = window.setInterval(() => load(true), 1500)
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <section v-if="batch">
    <div class="page-title">
      <div>
        <h1>{{ batch.name }}</h1>
        <span class="muted">创建于 {{ new Date(batch.created_at).toLocaleString() }}</span>
      </div>
      <div class="page-title-actions">
        <button v-if="canPause" class="danger-button" :disabled="acting" @click="pause">终止当前任务并暂停</button>
        <button v-if="canResume" class="primary-button" :disabled="acting" @click="resume">继续执行</button>
        <RouterLink class="secondary-button" to="/batches">返回批次列表</RouterLink>
      </div>
    </div>

    <div class="panel batch-summary">
      <div class="section-head">
        <strong>总进度 {{ percent }}%</strong>
        <span class="status-pill">{{ batch.status }}</span>
      </div>
      <div class="progress-bar"><div class="progress-fill" :style="{ width: `${percent}%` }"></div></div>
      <div class="stats-row">
        <span>总数 {{ batch.total }}</span>
        <span>完成 {{ batch.completed }}</span>
        <span>失败 {{ batch.failed }}</span>
        <span>待处理 {{ Math.max(0, batch.total - batch.completed - batch.failed) }}</span>
      </div>
      <p v-if="error" class="error">{{ error }}</p>
    </div>

    <div class="panel batch-items-panel">
      <div class="batch-item-table batch-item-head">
        <span>顺序</span><span>文件 / 项目</span><span>状态</span><span>当前阶段</span><span>操作</span>
      </div>
      <div v-for="item in batch.items || []" :key="item.id" class="batch-item-table batch-item-row">
        <span>#{{ item.order_index }}</span>
        <div>
          <strong>{{ item.original_filename }}</strong>
          <p class="muted">项目：{{ item.project_name }}</p>
          <p v-if="item.error_message" class="error batch-item-error">{{ item.error_message }}</p>
        </div>
        <span class="status-pill">{{ item.status }}</span>
        <span>{{ stageLabel(item.current_stage) }}</span>
        <div class="batch-item-actions">
          <RouterLink class="mini-button" :to="`/projects/${item.project_id}`">查看项目</RouterLink>
          <button v-if="item.status === 'failed'" class="mini-button" :disabled="acting" @click="retry(item.id)">重试</button>
        </div>
      </div>
    </div>
  </section>

  <section v-else class="panel"><p class="muted">{{ loading ? '加载中' : error }}</p></section>
</template>
