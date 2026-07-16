<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { listBatches, type BatchJob } from '../../api/batches'

const batches = ref<BatchJob[]>([])
const loading = ref(false)
const error = ref('')
const query = ref('')

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
  } catch (err) {
    error.value = err instanceof Error ? err.message : '批次列表加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-title batch-page-title">
      <div>
        <span class="page-kicker">BATCH PRODUCTION</span>
        <h1>批量生产队列</h1>
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
      <p v-else-if="!batches.length" class="muted">还没有批量任务。</p>
      <div v-else-if="filteredBatches.length">
        <RouterLink v-for="batch in filteredBatches" :key="batch.id" class="batch-row" :to="`/batches/${batch.id}`">
          <div>
            <strong>{{ batch.name }}</strong>
            <p class="muted">{{ new Date(batch.created_at).toLocaleString() }}</p>
          </div>
          <span>{{ batch.completed }}/{{ batch.total }}</span>
          <span v-if="batch.failed" class="error-count">失败 {{ batch.failed }}</span>
          <span v-else class="muted">无失败</span>
          <span class="status-pill" :class="statusTone(batch.status)"><i></i>{{ statusLabel(batch.status) }}</span>
        </RouterLink>
      </div>
      <div v-else class="empty-state compact-empty"><h2>没有匹配的批次</h2><p>换一个关键词再试试。</p></div>
    </div>
  </section>
</template>
