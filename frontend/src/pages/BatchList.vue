<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { listBatches, type BatchJob } from '../api/batches'

const batches = ref<BatchJob[]>([])
const loading = ref(false)
const error = ref('')

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
    <div class="page-title">
      <div>
        <h1>批量生成</h1>
        <span class="muted">{{ loading ? '加载中' : `${batches.length} 个批次` }}</span>
      </div>
      <RouterLink class="primary-link" to="/batches/new">新建批次</RouterLink>
    </div>

    <div class="panel">
      <p v-if="error" class="error">{{ error }}</p>
      <p v-else-if="!batches.length" class="muted">还没有批量任务。</p>
      <div v-else>
        <RouterLink v-for="batch in batches" :key="batch.id" class="batch-row" :to="`/batches/${batch.id}`">
          <div>
            <strong>{{ batch.name }}</strong>
            <p class="muted">{{ new Date(batch.created_at).toLocaleString() }}</p>
          </div>
          <span>{{ batch.completed }}/{{ batch.total }}</span>
          <span v-if="batch.failed" class="error-count">失败 {{ batch.failed }}</span>
          <span v-else class="muted">无失败</span>
          <span class="status-pill">{{ batch.status }}</span>
        </RouterLink>
      </div>
    </div>
  </section>
</template>

