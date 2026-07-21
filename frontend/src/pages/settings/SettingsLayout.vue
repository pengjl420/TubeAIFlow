<script setup lang="ts">
import { Bot, Boxes, CircleGauge, Database, Image, Mic2, MonitorCog, RotateCcw, ServerCog, Sparkles } from 'lucide-vue-next'

const navigation = [
  { path: 'general', label: '基础与存储', icon: Database },
  { path: 'ai-services', label: 'AI 服务', icon: Bot },
  { path: 'tts', label: '配音引擎', icon: Mic2 },
  { path: 'vision', label: '视觉模型', icon: Sparkles },
  { path: 'image-generation', label: '图片生成', icon: Image },
  { path: 'media-platforms', label: '素材平台', icon: Boxes },
  { path: 'render', label: '渲染与编码', icon: MonitorCog },
  { path: 'transitions', label: '转场策略', icon: RotateCcw },
  { path: 'fallback', label: '兜底策略', icon: ServerCog },
  { path: 'diagnostics', label: '系统诊断', icon: CircleGauge },
]
</script>

<template>
  <section class="settings-center">
    <aside class="settings-navigation panel"><div><span class="section-eyebrow">SYSTEM SETTINGS</span><h2>设置中心</h2><p>全局运行环境与生产默认值</p></div><nav><RouterLink v-for="item in navigation" :key="item.path" :to="`/settings/${item.path}`" active-class="is-active"><component :is="item.icon" :size="17" /><span>{{ item.label }}</span></RouterLink></nav></aside>
    <div class="settings-content"><RouterView /></div>
  </section>
</template>
