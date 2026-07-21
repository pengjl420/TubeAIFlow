<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AudioLines,
  Boxes,
  ChevronDown,
  Cpu,
  FolderKanban,
  HardDrive,
  Layers3,
  LayoutDashboard,
  ListTodo,
  Plus,
  Search,
  Settings2,
  WandSparkles,
} from 'lucide-vue-next'

import { listProjects } from './api/projects'
import AppFeedback from './components/common/AppFeedback.vue'
import type { Project } from './types/project'

const route = useRoute()
const router = useRouter()
const projects = ref<Project[]>([])
const search = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const createMenuOpen = ref(false)
const sidebarCollapsed = ref(localStorage.getItem('tubeaiflow.sidebar-collapsed') === 'true')
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
const currentProject = computed(() => {
  const id = typeof route.params.id === 'string' ? route.params.id : ''
  return projects.value.find((project) => project.id === id)
})
const contextName = computed(() => currentProject.value?.name || '默认项目')

async function refreshGlobalState() {
  try { projects.value = await listProjects() } catch { projects.value = [] }
}

function submitSearch() {
  const query = search.value.trim()
  void router.push({ path: '/projects', query: query ? { q: query } : {} })
}

function selectCreate(path: string) {
  createMenuOpen.value = false
  void router.push(path)
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('tubeaiflow.sidebar-collapsed', String(sidebarCollapsed.value))
}

function handleShortcut(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    void nextTick(() => searchInput.value?.focus())
  }
  if (event.key === 'Escape') createMenuOpen.value = false
}

onMounted(() => {
  void refreshGlobalState()
  refreshTimer = window.setInterval(refreshGlobalState, 15000)
  window.addEventListener('keydown', handleShortcut)
})
onBeforeUnmount(() => {
  if (refreshTimer !== undefined) window.clearInterval(refreshTimer)
  window.removeEventListener('keydown', handleShortcut)
})
</script>

<template>
  <div class="app-shell taf-shell" :class="{ 'sidebar-is-collapsed': sidebarCollapsed }">
    <aside class="sidebar taf-sidebar">
      <RouterLink class="brand taf-brand" to="/dashboard" aria-label="返回工作台">
        <span class="brand-mark taf-brand-mark"><span></span></span>
        <strong>TubeAIFlow</strong>
      </RouterLink>

      <nav class="side-nav taf-side-nav" aria-label="一级导航">
        <RouterLink v-for="item in navigation" :key="item.to" :to="item.to" active-class="is-active">
          <component :is="item.icon" :size="20" :stroke-width="1.9" />
          <span class="nav-label">{{ item.label }}</span>
        </RouterLink>
      </nav>

      <div class="sidebar-spacer"></div>
      <div class="taf-system-state">
        <div><span>版本号</span><strong>v2.3.0</strong></div>
        <div><i></i><span>本地模式</span></div>
        <div><span>后端服务</span><b><i></i>运行中</b></div>
      </div>
      <button class="taf-sidebar-collapse" type="button" :aria-label="sidebarCollapsed ? '展开侧栏' : '收起侧栏'" @click="toggleSidebar">{{ sidebarCollapsed ? '››' : '‹‹' }}</button>
    </aside>

    <div class="app-content taf-content">
      <header class="topbar taf-topbar">
        <button class="taf-context-select" type="button" @click="router.push('/projects')">
          <FolderKanban :size="18" /> <strong>{{ contextName }}</strong><ChevronDown :size="16" />
        </button>

        <form class="global-search taf-global-search" role="search" @submit.prevent="submitSearch">
          <Search :size="18" />
          <input ref="searchInput" v-model="search" type="search" placeholder="搜索项目、任务、素材、音色..." aria-label="全局搜索" />
          <kbd>Ctrl + K</kbd>
        </form>

        <div class="topbar-status taf-topbar-status" aria-label="系统状态">
          <RouterLink to="/tasks?status=running" class="taf-status-item blue">
            <span class="taf-status-icon"><Layers3 :size="19" /></span><span>运行中任务<strong>{{ runningCount }}</strong></span>
          </RouterLink>
          <RouterLink to="/tasks?status=review" class="taf-status-item orange">
            <span class="taf-status-icon"><WandSparkles :size="19" /></span><span>待人工审核<strong>{{ reviewCount }}</strong></span>
          </RouterLink>
          <RouterLink to="/tasks" class="taf-status-item green">
            <span class="taf-status-icon"><Cpu :size="19" /></span><span>GPU<strong>2/2 <i></i></strong></span>
          </RouterLink>
          <RouterLink to="/assets/storage" class="taf-status-item storage">
            <span class="taf-status-icon"><HardDrive :size="19" /></span><span>磁盘剩余<strong>1.26 TB <small>/ 2.00 TB</small></strong></span>
          </RouterLink>
        </div>

        <div class="create-menu">
          <button class="primary-button taf-create-button" type="button" :aria-expanded="createMenuOpen" @click="createMenuOpen = !createMenuOpen">
            <Plus :size="20" /> 新建 <ChevronDown :size="15" />
          </button>
          <div v-if="createMenuOpen" class="create-menu-popover" role="menu">
            <button type="button" @click="selectCreate('/projects/new')"><FolderKanban :size="17" /><span><strong>新建项目</strong><small>从一份逐字稿开始</small></span></button>
            <button type="button" @click="selectCreate('/batches/new')"><Layers3 :size="17" /><span><strong>新建批次</strong><small>批量导入多个脚本</small></span></button>
            <button type="button" @click="selectCreate('/assets/import')"><Boxes :size="17" /><span><strong>导入素材</strong><small>扫描本地素材目录</small></span></button>
          </div>
        </div>
      </header>
      <main class="taf-main"><RouterView /></main>
    </div>
    <AppFeedback />
  </div>
</template>
