<script setup lang="ts">
import { Bot, Captions, CircleGauge, Database, Image, Mic2, MonitorCog, RotateCcw } from 'lucide-vue-next'

const navigation = [
  { path: 'general', label: '基础与存储', icon: Database },
  { path: 'ai-services', label: 'AI 服务', icon: Bot },
  { path: 'tts', label: '配音引擎', icon: Mic2 },
  { path: 'subtitles', label: '字幕对齐', icon: Captions },
  { path: 'image-generation', label: '图片生成', icon: Image },
  { path: 'render', label: '渲染与编码', icon: MonitorCog },
  { path: 'transitions', label: '转场策略', icon: RotateCcw },
  { path: 'diagnostics', label: '系统诊断', icon: CircleGauge },
]
</script>

<template>
  <section class="settings-center settings-design-shell">
    <header class="settings-title">
      <h1>系统设置</h1>
      <p>本地环境、模型、服务与生产默认值</p>
    </header>
    <div class="settings-workspace">
      <aside class="settings-navigation">
        <nav aria-label="系统设置分类">
          <RouterLink v-for="item in navigation" :key="item.path" :to="`/settings/${item.path}`" active-class="is-active">
            <component :is="item.icon" :size="17" :stroke-width="1.8" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </nav>
      </aside>
      <div class="settings-content"><RouterView /></div>
    </div>
  </section>
</template>
