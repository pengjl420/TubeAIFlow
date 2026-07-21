<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AudioLines,
  Boxes,
  ChevronDown,
  CircleGauge,
  FolderKanban,
  HardDrive,
  Layers3,
  LayoutDashboard,
  ListTodo,
  Plus,
  Search,
  Settings2,
  Sparkles,
  WandSparkles,
} from 'lucide-vue-next'

import { listProjects } from './api/projects'
import AppFeedback from './components/common/AppFeedback.vue'
import type { Project } from './types/project'

const route = useRoute()
const router = useRouter()
const projects = ref<Project[]>([])
const search = ref('')
const createMenuOpen = ref(false)
let refreshTimer: number | undefined

const navigation = [
  { to: '/dashboard', label: '工作台', icon: LayoutDashboard },
  { to: '/projects', label: '项目', icon: FolderKanban },
  { to: '/batches', label: '批量生产', icon: Layers3 },
  { to: '/tasks', label: '任务中心', icon: ListTodo },
  { to: '/assets', label: '素材中心', icon: Boxes },
  { to: '/voices', label: '音色中心', icon: AudioLines },
  { to: '/settings/general', label: '系统设置', icon: Settings2 },
]

const runningCount = computed(() => projects.value.filter((project) => (
  project.latest_task_status === 'running'
  || project.status.includes('progress')
  || ['tts', 'tts_running', 'rendering', 'video_composing'].includes(project.status)
)).length)
const reviewCount = computed(() => projects.value.filter((project) => project.status === 'review_required').length)
const failedCount = computed(() => projects.value.filter((project) => project.status === 'failed').length)

const currentProject = computed(() => {
  const id = typeof route.params.id === 'string' ? route.params.id : ''
  return projects.value.find((project) => project.id === id)
})

const sectionTitle = computed(() => {
  if (route.path.startsWith('/dashboard')) return '工作台'
  if (route.path.startsWith('/projects/new')) return '新建项目'
  if (route.path.startsWith('/projects/')) return currentProject.value?.name || '项目生产工作区'
  if (route.path.startsWith('/projects')) return '项目'
  if (route.path.startsWith('/batches')) return '批量生产'
  if (route.path.startsWith('/tasks')) return '任务中心'
  if (route.path.startsWith('/assets')) return '素材中心'
  if (route.path.startsWith('/voices')) return '音色中心'
  return '系统设置'
})

async function refreshGlobalState() {
  try {
    projects.value = await listProjects()
  } catch {
    projects.value = []
  }
}

function submitSearch() {
  const query = search.value.trim()
  void router.push({ path: '/projects', query: query ? { q: query } : {} })
}

function selectCreate(path: string) {
  createMenuOpen.value = false
  void router.push(path)
}

onMounted(() => {
  void refreshGlobalState()
  refreshTimer = window.setInterval(refreshGlobalState, 15000)
})

onBeforeUnmount(() => {
  if (refreshTimer !== undefined) window.clearInterval(refreshTimer)
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/dashboard" aria-label="返回工作台">
        <span class="brand-mark"><Sparkles :size="20" :stroke-width="2.2" /></span>
        <span><strong>TubeAIFlow</strong><small>本地视频生产系统</small></span>
      </RouterLink>

      <div class="sidebar-section-label">生产工作区</div>
      <nav class="side-nav" aria-label="一级导航">
        <RouterLink v-for="item in navigation" :key="item.to" :to="item.to" active-class="is-active">
          <span class="nav-icon"><component :is="item.icon" :size="18" :stroke-width="1.9" /></span>
          <span class="nav-label">{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar-spacer"></div>
      <div class="local-status">
        <span class="status-dot"></span>
        <span><strong>本地模式</strong><small>后端服务已连接</small></span>
      </div>
      <div class="sidebar-version"><span>TubeAIFlow</span><small>v0.1 · Local</small></div>
    </aside>

    <div class="app-content">
      <header class="topbar">
        <div class="topbar-context">
          <span class="topbar-eyebrow">CURRENT CONTEXT</span>
          <strong>{{ sectionTitle }}</strong>
        </div>

        <form class="global-search" role="search" @submit.prevent="submitSearch">
          <Search :size="16" />
          <input v-model="search" type="search" placeholder="搜索项目…" aria-label="搜索项目" />
          <kbd>Enter</kbd>
        </form>

        <div class="topbar-status" aria-label="全局任务状态">
          <RouterLink to="/tasks?status=running"><span class="status-signal is-running"></span>运行中 {{ runningCount }}</RouterLink>
          <RouterLink to="/tasks?status=review"><span class="status-signal is-review"></span>待审核 {{ reviewCount }}</RouterLink>
          <RouterLink v-if="failedCount" to="/tasks?status=failed"><span class="status-signal is-failed"></span>失败 {{ failedCount }}</RouterLink>
          <span class="system-chip" data-tooltip="GPU 状态由本地任务调度器管理"><CircleGauge :size="15" /> GPU 就绪</span>
          <span class="system-chip" data-tooltip="项目与素材保存在本机"><HardDrive :size="15" /> 本地存储</span>
        </div>

        <div class="create-menu">
          <button class="primary-button" type="button" aria-haspopup="menu" :aria-expanded="createMenuOpen" @click="createMenuOpen = !createMenuOpen">
            <Plus :size="17" /> 新建 <ChevronDown :size="14" />
          </button>
          <div v-if="createMenuOpen" class="create-menu-popover" role="menu">
            <button type="button" @click="selectCreate('/projects/new')"><FolderKanban :size="17" /><span><strong>新建项目</strong><small>从一份逐字稿开始</small></span></button>
            <button type="button" @click="selectCreate('/batches/new')"><Layers3 :size="17" /><span><strong>新建批次</strong><small>批量导入多份脚本</small></span></button>
            <button type="button" @click="selectCreate('/assets/import')"><Boxes :size="17" /><span><strong>导入素材</strong><small>扫描本地素材目录</small></span></button>
            <button type="button" @click="selectCreate('/voices')"><WandSparkles :size="17" /><span><strong>新建音色</strong><small>创建复用声音档案</small></span></button>
          </div>
        </div>
      </header>
      <main><RouterView /></main>
    </div>
    <AppFeedback />
  </div>
</template>
