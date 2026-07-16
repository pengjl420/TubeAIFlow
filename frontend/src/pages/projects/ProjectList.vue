<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { listProjects } from '../../api/projects'
import type { Project } from '../../types/project'

const projects = ref<Project[]>([])
const loading = ref(false)
const error = ref('')
const query = ref('')
const statusFilter = ref('all')

const statusLabels: Record<string, string> = {
  created: '待开始',
  narration_in_progress: '配音生成中',
  narration_ready: '配音已就绪',
  video_in_progress: '视频合成中',
  review_required: '等待复核',
  completed: '已完成',
  failed: '执行失败',
}

const filteredProjects = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase()
  return projects.value.filter((project) => {
    const matchesQuery = !keyword || project.name.toLocaleLowerCase().includes(keyword)
    const matchesStatus = statusFilter.value === 'all' || project.status === statusFilter.value
    return matchesQuery && matchesStatus
  })
})

const activeCount = computed(() => projects.value.filter((item) => (
  item.status.includes('progress') || ['segmenting', 'tts', 'translation', 'rendering'].includes(item.status)
)).length)
const readyCount = computed(() => projects.value.filter((item) => ['narration_ready', 'review_required'].includes(item.status)).length)
const completedCount = computed(() => projects.value.filter((item) => item.status === 'completed').length)

function statusLabel(status: string) {
  return statusLabels[status] || status.split('_').join(' ')
}

function statusTone(status: string) {
  if (status === 'failed') return 'is-danger'
  if (status === 'completed') return 'is-success'
  if (status.includes('progress')) return 'is-running'
  if (status === 'review_required') return 'is-warning'
  return 'is-neutral'
}

function formatDate(value: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

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
    <div class="page-title dashboard-title">
      <h1>项目工作台</h1>
      <RouterLink class="primary-link hero-action" to="/projects/new"><span>＋</span> 创建新项目</RouterLink>
    </div>

    <div class="metric-grid" aria-label="项目概览">
      <article class="metric-card">
        <span class="metric-label">全部项目</span>
        <strong>{{ projects.length }}</strong>
        <small>当前工作空间</small>
      </article>
      <article class="metric-card accent-card">
        <span class="metric-label">正在生产</span>
        <strong>{{ activeCount }}</strong>
        <small>任务正在后台执行</small>
      </article>
      <article class="metric-card">
        <span class="metric-label">等待处理</span>
        <strong>{{ readyCount }}</strong>
        <small>可继续合成或复核</small>
      </article>
      <article class="metric-card">
        <span class="metric-label">已完成</span>
        <strong>{{ completedCount }}</strong>
        <small>已输出最终文件</small>
      </article>
    </div>

    <div class="section-toolbar">
      <div>
        <h2>最近项目</h2>
        <p>继续未完成的制作，或查看已经生成的文件。</p>
      </div>
      <div class="toolbar-controls">
        <label class="search-field">
          <span>⌕</span>
          <input v-model="query" type="search" placeholder="搜索项目名称" aria-label="搜索项目名称" />
        </label>
        <select v-model="statusFilter" class="filter-select" aria-label="按状态筛选">
          <option value="all">全部状态</option>
          <option value="created">待开始</option>
          <option value="narration_in_progress">生成中</option>
          <option value="narration_ready">配音已就绪</option>
          <option value="review_required">等待复核</option>
          <option value="completed">已完成</option>
          <option value="failed">执行失败</option>
        </select>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger"><strong>项目加载失败</strong><span>{{ error }}</span></div>
    <div v-else-if="loading" class="project-grid" aria-label="正在加载">
      <div v-for="index in 3" :key="index" class="project-card skeleton-card"></div>
    </div>
    <div v-else-if="!projects.length" class="empty-state panel">
      <span class="empty-icon">＋</span>
      <h2>从第一个项目开始</h2>
      <p>准备一段逐字稿并选择系统音色，即可创建配音、字幕并合成视频。</p>
      <RouterLink class="primary-link" to="/projects/new">创建项目</RouterLink>
    </div>
    <div v-else-if="!filteredProjects.length" class="empty-state panel compact-empty">
      <h2>没有匹配的项目</h2>
      <p>试试调整搜索词或状态筛选。</p>
      <button class="secondary-button" @click="query = ''; statusFilter = 'all'">清除筛选</button>
    </div>
    <div v-else class="project-grid">
      <RouterLink v-for="project in filteredProjects" :key="project.id" class="project-card" :to="`/projects/${project.id}`">
        <div class="project-card-top">
          <span class="project-avatar">{{ project.name.slice(0, 1).toUpperCase() }}</span>
          <span class="status-pill" :class="statusTone(project.status)"><i></i>{{ statusLabel(project.status) }}</span>
        </div>
        <div class="project-card-body">
          <h3>{{ project.name }}</h3>
          <p>{{ project.output_dir || '尚未配置输出目录' }}</p>
        </div>
        <div class="project-card-footer">
          <span>更新于 {{ formatDate(project.updated_at || project.created_at) }}</span>
          <strong>进入工作台 →</strong>
        </div>
      </RouterLink>
    </div>
  </section>
</template>
