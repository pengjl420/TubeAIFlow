<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()

const sectionTitle = computed(() => {
  if (route.path.startsWith('/voices')) return '参考音频'
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
        <span class="brand-mark">T</span>
        <span>
          <strong>TubeAIFlow</strong>
          <small>本地视频工作台</small>
        </span>
      </RouterLink>

      <div class="sidebar-section-label">工作空间</div>
      <nav class="side-nav" aria-label="主要导航">
        <RouterLink to="/" exact-active-class="is-active">
          <span class="nav-icon">项</span>
          <span>项目工作台</span>
        </RouterLink>
        <RouterLink to="/batches" active-class="is-active">
          <span class="nav-icon">批</span>
          <span>批量生产</span>
        </RouterLink>
      </nav>

      <div class="sidebar-spacer"></div>
      <div class="local-status">
        <span class="status-dot"></span>
        <span><strong>本地模式</strong><small>数据仅保存在此设备</small></span>
      </div>
      <nav class="side-nav side-nav-bottom" aria-label="系统导航">
        <RouterLink to="/voices" active-class="is-active">
          <span class="nav-icon">声</span>
          <span>参考音频</span>
        </RouterLink>
        <RouterLink to="/settings" active-class="is-active">
          <span class="nav-icon">设</span>
          <span>系统设置</span>
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
          <RouterLink class="primary-link" to="/projects/new"><span>＋</span> 新建项目</RouterLink>
        </div>
      </header>
      <main><RouterView /></main>
    </div>
  </div>
</template>
