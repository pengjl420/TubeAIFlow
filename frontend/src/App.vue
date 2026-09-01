<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { AudioLines, CircleUserRound, FolderKanban, Merge, Mic2, Settings2 } from 'lucide-vue-next'
import AppFeedback from './components/common/AppFeedback.vue'
import { getEngineHealth } from './api/client'

const navigation = [
  { to: '/projects', label: '项目', icon: FolderKanban },
  { to: '/voice-generation', label: '配音生成', icon: Mic2 },
  { to: '/local-video-merge', label: '素材拼接', icon: Merge },
  { to: '/avatars', label: '数字人合成', icon: CircleUserRound },
  { to: '/voices', label: '音色中心', icon: AudioLines },
  { to: '/settings/general', label: '系统设置', icon: Settings2 },
]

const engineOnline = ref(false)
let healthTimer: number | undefined

async function checkEngine() {
  try {
    const health = await getEngineHealth()
    engineOnline.value = health.status === 'ok' && health.product === 'TubeAiFolw'
  } catch {
    engineOnline.value = false
  }
}

onMounted(() => {
  void checkEngine()
  healthTimer = window.setInterval(() => void checkEngine(), 10000)
})
onBeforeUnmount(() => {
  if (healthTimer !== undefined) window.clearInterval(healthTimer)
})
</script>

<template>
  <div class="app-shell taf-shell">
    <aside class="sidebar taf-sidebar">
      <RouterLink class="brand taf-brand" to="/projects" aria-label="前往项目">
        <span class="brand-mark taf-brand-mark"><span /></span>
        <strong>TubeAiFolw</strong>
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
        <div :class="{ offline: !engineOnline }"><i /><span>{{ engineOnline ? '本地 Engine 运行中' : '本地 Engine 未连接' }}</span></div>
      </div>
    </aside>
    <div class="app-content taf-content">
      <header class="topbar taf-topbar streamlined">
        <div><strong>Local-first 长视频生产工作流</strong><span>项目工作流为主，现有单项能力保留在工具入口</span></div>
      </header>
      <main class="taf-main"><RouterView /></main>
    </div>
    <AppFeedback />
  </div>
</template>

<style scoped>
.streamlined{justify-content:flex-start}.streamlined>div{display:grid;gap:3px}.streamlined strong{color:#172033;font-size:14px}.streamlined span{color:#8792a3;font-size:11px}.taf-system-state .offline i{background:#e04b57}.taf-system-state .offline span{color:#c34a55}
</style>
