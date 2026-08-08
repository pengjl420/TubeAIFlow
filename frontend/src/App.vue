<script setup lang="ts">
import { AudioLines, CircleUserRound, Merge, Mic2, Settings2 } from 'lucide-vue-next'
import AppFeedback from './components/common/AppFeedback.vue'

const navigation = [
  { to: '/voice-generation', label: '配音生成', icon: Mic2 },
  { to: '/local-video-merge', label: '素材拼接', icon: Merge },
  { to: '/avatars', label: '数字人合成', icon: CircleUserRound },
  { to: '/voices', label: '音色中心', icon: AudioLines },
  { to: '/settings/general', label: '系统设置', icon: Settings2 },
]
</script>

<template>
  <div class="app-shell taf-shell">
    <aside class="sidebar taf-sidebar">
      <RouterLink class="brand taf-brand" to="/voice-generation" aria-label="前往配音生成">
        <span class="brand-mark taf-brand-mark"><span /></span>
        <strong>TubeAIFlow</strong>
      </RouterLink>
      <nav class="side-nav taf-side-nav" aria-label="主导航">
        <RouterLink v-for="item in navigation" :key="item.to" :to="item.to" active-class="is-active">
          <component :is="item.icon" :size="20" :stroke-width="1.9" />
          <span class="nav-label">{{ item.label }}</span>
        </RouterLink>
      </nav>
      <div class="sidebar-spacer" />
      <div class="taf-system-state">
        <div><span>运行模式</span><strong>本地</strong></div>
        <div><i /><span>后端服务运行中</span></div>
      </div>
    </aside>
    <div class="app-content taf-content">
      <header class="topbar taf-topbar streamlined">
        <div><strong>本地音视频工作台</strong><span>专注单项生成与合成工具</span></div>
      </header>
      <main class="taf-main"><RouterView /></main>
    </div>
    <AppFeedback />
  </div>
</template>

<style scoped>
.streamlined{justify-content:flex-start}.streamlined>div{display:grid;gap:3px}.streamlined strong{color:#172033;font-size:14px}.streamlined span{color:#8792a3;font-size:11px}
</style>
