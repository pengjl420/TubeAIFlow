<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import {
  AudioLines,
  Boxes,
  ChevronRight,
  FolderKanban,
  Layers3,
  Plus,
  Settings2,
  Sparkles,
} from 'lucide-vue-next'

import AppFeedback from './components/common/AppFeedback.vue'

const route = useRoute()

const primaryNavigation = [
  { to: '/', label: '项目工作台', icon: FolderKanban, exact: true },
  { to: '/batches', label: '批量生产', icon: Layers3 },
  { to: '/assets', label: '本地素材库', icon: Boxes },
]

const systemNavigation = [
  { to: '/voices', label: '参考音频', icon: AudioLines },
  { to: '/settings', label: '系统设置', icon: Settings2 },
]

const sectionTitle = computed(() => {
  if (route.path.startsWith('/voices')) return '参考音频'
  if (route.path.startsWith('/assets')) return '本地素材库'
  if (route.path.startsWith('/batches')) return '批量生产'
  if (route.path.startsWith('/settings')) return '系统设置'
  if (route.path.includes('/config')) return '项目设置'
  if (route.path.startsWith('/projects/new')) return '创建项目'
  if (route.path.startsWith('/projects/')) return '项目工作台'
  return '创作总览'
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <RouterLink class="brand" to="/" aria-label="返回项目总览">
        <span class="brand-mark"><Sparkles :size="20" :stroke-width="2.2" /></span>
        <span>
          <strong>TubeAIFlow</strong>
          <small>AI 视频生产工作台</small>
        </span>
      </RouterLink>

      <div class="sidebar-section-label">工作空间</div>
      <nav class="side-nav" aria-label="主要导航">
        <RouterLink
          v-for="item in primaryNavigation"
          :key="item.to"
          :to="item.to"
          :exact-active-class="item.exact ? 'is-active' : undefined"
          active-class="is-active"
        >
          <span class="nav-icon"><component :is="item.icon" :size="18" :stroke-width="1.9" /></span>
          <span class="nav-label">{{ item.label }}</span>
          <ChevronRight class="nav-chevron" :size="15" />
        </RouterLink>
      </nav>

      <div class="sidebar-spacer"></div>
      <div class="local-status">
        <span class="status-dot"></span>
        <span><strong>本地模式</strong><small>数据仅保存在此设备</small></span>
      </div>
      <nav class="side-nav side-nav-bottom" aria-label="系统导航">
        <RouterLink v-for="item in systemNavigation" :key="item.to" :to="item.to" active-class="is-active">
          <span class="nav-icon"><component :is="item.icon" :size="18" :stroke-width="1.9" /></span>
          <span class="nav-label">{{ item.label }}</span>
          <ChevronRight class="nav-chevron" :size="15" />
        </RouterLink>
      </nav>
    </aside>

    <div class="app-content">
      <header class="topbar">
        <div>
          <span class="topbar-eyebrow">TubeAIFlow</span>
          <strong>{{ sectionTitle }}</strong>
        </div>
        <div class="topbar-actions">
          <RouterLink class="secondary-button topbar-batch-link" to="/batches/new">新建批次</RouterLink>
          <RouterLink class="primary-link" to="/projects/new"><Plus :size="17" /> 新建项目</RouterLink>
        </div>
      </header>
      <main><RouterView /></main>
    </div>
    <AppFeedback />
  </div>
</template>
