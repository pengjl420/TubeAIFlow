<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { listProjects } from '../api/projects'
import type { Project } from '../types/project'

const projects = ref<Project[]>([])
const loading = ref(false)
const error = ref('')

async function loadProjects() {
  loading.value = true
  error.value = ''
  try {
    projects.value = await listProjects()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '项目列表加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(loadProjects)
</script>

<template>
  <section>
    <div class="page-title">
      <h1>项目</h1>
      <span class="muted">{{ loading ? '加载中' : `${projects.length} 个项目` }}</span>
    </div>

    <div class="panel">
      <p v-if="error" class="error">{{ error }}</p>
      <p v-else-if="!projects.length" class="muted">还没有项目。</p>
      <div v-else>
        <RouterLink v-for="project in projects" :key="project.id" class="project-row" :to="`/projects/${project.id}`">
          <strong>{{ project.name }}</strong>
          <span class="status-pill">{{ project.status }}</span>
          <span class="muted">{{ new Date(project.created_at).toLocaleString() }}</span>
        </RouterLink>
      </div>
    </div>
  </section>
</template>
