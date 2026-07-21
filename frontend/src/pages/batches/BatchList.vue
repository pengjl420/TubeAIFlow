<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { deleteBatch, listBatches, type BatchJob } from '../../api/batches'
import { confirmAction, showToast } from '../../services/feedback'

const batches = ref<BatchJob[]>([])
const loading = ref(false)
const error = ref('')
const query = ref('')
const deletingBatchId = ref('')

const filteredBatches = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase()
  return batches.value.filter((batch) => !keyword || batch.name.toLocaleLowerCase().includes(keyword))
})
const runningCount = computed(() => batches.value.filter((batch) => ['queued', 'running'].includes(batch.status)).length)
const issueCount = computed(() => batches.value.reduce((total, batch) => total + batch.failed, 0))

const statusLabels: Record<string, string> = {
  draft: '草稿', queued: '排队中', running: '执行中', paused: '已暂停',
  completed: '已完成', completed_with_errors: '部分失败', failed: '执行失败',
}

function statusLabel(status: string) {
  return statusLabels[status] || status
}

function statusTone(status: string) {
  if (status === 'failed' || status === 'completed_with_errors') return 'is-danger'
  if (status === 'completed') return 'is-success'
  if (status === 'running' || status === 'queued') return 'is-running'
  return 'is-neutral'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    batches.value = await listBatches()
    return true
  } catch (err) {
    error.value = err instanceof Error ? err.message : '批次列表加载失败'
    return false
  } finally {
    loading.value = false
  }
}

async function removeBatch(batch: BatchJob) {
  const confirmed = await confirmAction({
    eyebrow: '删除批次记录',
    title: `删除批次“${batch.name}”？`,
    description: '该批次会从生产记录中移除，之后无法再查看它的汇总进度。',
    detail: '批次创建的项目和已生成文件仍会保留在项目工作台。',
    confirmText: '删除批次',
    tone: 'danger',
  })
  if (!confirmed) return
  deletingBatchId.value = batch.id
  try {
    await deleteBatch(batch.id)
    batches.value = batches.value.filter((item) => item.id !== batch.id)
    const refreshed = await load()
    showToast({
      title: refreshed ? '批次记录已删除' : '批次已删除，列表同步失败',
      description: refreshed ? `“${batch.name}”创建的项目与文件均已保留。` : '请稍后手动刷新批次列表。',
      tone: refreshed ? 'success' : 'warning',
    })
  } catch (err) {
    showToast({
      title: '批次删除失败',
      description: err instanceof Error ? err.message : '请稍后重试。',
      tone: 'danger',
    })
  } finally {
    deletingBatchId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-title batch-page-title">
      <div>
        <span class="page-kicker">BATCH PRODUCTION</span>
        <h1>批量生产</h1>
        <p class="muted">使用同一套声音和生成配置，连续处理多份逐字稿。</p>
      </div>
      <RouterLink class="primary-link" to="/batches/new">新建批次</RouterLink>
    </div>

    <div class="metric-grid batch-metrics">
      <article class="metric-card"><span class="metric-label">全部批次</span><strong>{{ batches.length }}</strong><small>历史生产任务</small></article>
      <article class="metric-card accent-card"><span class="metric-label">正在执行</span><strong>{{ runningCount }}</strong><small>队列中或运行中</small></article>
      <article class="metric-card"><span class="metric-label">待处理异常</span><strong>{{ issueCount }}</strong><small>失败后可单项重试</small></article>
    </div>

    <div class="section-toolbar">
      <div><h2>生产记录</h2><p>查看每个批次的处理进度与失败项目。</p></div>
      <label class="search-field"><span>⌕</span><input v-model="query" type="search" placeholder="搜索批次名称" aria-label="搜索批次名称" /></label>
    </div>

    <div class="panel">
      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="!batches.length" class="muted">还没有批量任务。</p>
      <div v-else-if="filteredBatches.length">
        <div v-for="batch in filteredBatches" :key="batch.id" class="batch-row">
          <RouterLink class="batch-row-link" :to="`/batches/${batch.id}`">
            <div>
              <strong>{{ batch.name }}</strong>
              <p class="muted">{{ new Date(batch.created_at).toLocaleString() }}</p>
            </div>
            <span>{{ batch.completed }}/{{ batch.total }}</span>
            <span v-if="batch.failed" class="error-count">失败 {{ batch.failed }}</span>
            <span v-else class="muted">无失败</span>
            <span class="status-pill" :class="statusTone(batch.status)"><i></i>{{ statusLabel(batch.status) }}</span>
          </RouterLink>
          <button
            class="danger-button batch-delete-button"
            type="button"
            :disabled="deletingBatchId === batch.id || ['queued', 'running'].includes(batch.status)"
            :data-tooltip="['queued', 'running'].includes(batch.status) ? '请先暂停批次再删除' : '删除批次记录并保留项目'"
            @click="removeBatch(batch)"
          >
            {{ deletingBatchId === batch.id ? '删除中…' : '删除' }}
          </button>
        </div>
      </div>
      <div v-else class="empty-state compact-empty"><h2>没有匹配的批次</h2><p>换一个关键词再试试。</p></div>
    </div>
  </section>
</template>
