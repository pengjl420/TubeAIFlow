<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { AudioLines, CircleUserRound, FolderKanban, Merge, Mic2, Settings2, Wifi, WifiOff } from 'lucide-vue-next'
import AppFeedback from './components/common/AppFeedback.vue'
import { getEngineHealth } from './api/client'

const route = useRoute()
const navigation = [
  { label: '生产工作区', items: [{ to: '/projects', label: '项目', icon: FolderKanban }] },
  { label: '独立工具', items: [
    { to: '/voice-generation', label: '配音生成', icon: Mic2 },
    { to: '/local-video-merge', label: '素材拼接', icon: Merge },
    { to: '/avatars', label: '数字人合成', icon: CircleUserRound },
  ] },
  { label: '资源与系统', items: [
    { to: '/voices', label: '音色中心', icon: AudioLines },
    { to: '/settings/general', label: '系统设置', icon: Settings2 },
  ] },
]
const pageTitle = computed(() => String(route.meta.title || '本地工作流'))

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
        <img class="brand-mark taf-brand-mark" src="/brand/tubeaifolw-logo.png" alt="" width="32" height="32" />
        <strong>TubeAiFolw</strong>
      </RouterLink>
      <nav class="side-nav taf-side-nav" aria-label="主导航">
        <section v-for="group in navigation" :key="group.label" class="nav-group">
          <span class="nav-group-label">{{ group.label }}</span>
          <RouterLink v-for="item in group.items" :key="item.to" :to="item.to" active-class="is-active" :class="{ 'is-active': item.to.startsWith('/settings') && route.path.startsWith('/settings') }" :title="item.label">
            <component :is="item.icon" :size="20" :stroke-width="1.9" />
            <span class="nav-label">{{ item.label }}</span>
          </RouterLink>
        </section>
      </nav>
      <div class="sidebar-spacer" />
      <div class="taf-system-state">
        <div><span>运行模式</span><strong>本地</strong></div>
        <div :class="{ offline: !engineOnline }"><i /><span>{{ engineOnline ? '本地 Engine 运行中' : '本地 Engine 未连接' }}</span></div>
      </div>
    </aside>
    <div class="app-content taf-content">
      <header class="topbar taf-topbar streamlined">
        <div><strong>{{ pageTitle }}</strong><span>TubeAiFolw · Local-first 长视频生产工作流</span></div>
        <div class="topbar-engine-state" :class="{ offline: !engineOnline }" role="status">
          <Wifi v-if="engineOnline" :size="15" />
          <WifiOff v-else :size="15" />
          <span>{{ engineOnline ? 'Engine 已连接' : 'Engine 未连接' }}</span>
        </div>
      </header>
      <main class="taf-main"><RouterView /></main>
    </div>
    <AppFeedback />
  </div>
</template>

<style scoped>
.streamlined>div:first-child{display:grid;gap:3px}.streamlined strong{color:#172033;font-size:14px}.streamlined span{color:#8792a3;font-size:11px}.taf-system-state .offline i{background:#e04b57}.taf-system-state .offline span{color:#c34a55}
.topbar-engine-state{align-items:center!important;background:#e9f8f2;border:1px solid #cdeee0;border-radius:999px;color:#087b56;display:flex!important;gap:7px!important;margin-left:auto;padding:7px 11px}.topbar-engine-state span{color:inherit;font-size:11px;font-weight:700}.topbar-engine-state.offline{background:#fff0f1;border-color:#ffd7da;color:#c23f4b}
</style>
