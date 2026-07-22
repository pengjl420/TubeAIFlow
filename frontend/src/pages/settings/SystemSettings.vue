<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Download, RefreshCw, Save } from 'lucide-vue-next'

import { rememberApiAddress } from '../../api/client'
import { selectDirectory } from '../../api/projects'
import {
  clearSystemSecret,
  getFfmpegStatus,
  getSystemSettings,
  installFfmpeg,
  saveSystemSettings,
  type FfmpegStatus,
  type SystemSettings,
} from '../../api/settings'
import { usePageFeedback } from '../../services/feedback'

const route = useRoute()
const section = computed(() => String(route.params.section || 'general'))
const settings = ref<SystemSettings | null>(null)
const ffmpegStatus = ref<FfmpegStatus | null>(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const message = ref('')
usePageFeedback(error, message, { errorTitle: '系统设置操作失败', messageTitle: '系统设置' })

const copy: Record<string, [string, string]> = {
  general: ['基础与存储', '配置本地服务、工作目录和工具路径'],
  'ai-services': ['AI 服务', '配置文本模型连接参数'],
  tts: ['配音引擎', '配置 Qwen3-TTS 与 CosyVoice'],
  'image-generation': ['图片生成', '配置本地图片模型与生成参数'],
  render: ['渲染与编码', '检测 FFmpeg 与视频编码环境'],
  transitions: ['转场策略', '配置场景转场比例与时长'],
  diagnostics: ['系统诊断', '检查本地运行环境'],
}
const title = computed(() => copy[section.value]?.[0] || '系统设置')
const subtitle = computed(() => copy[section.value]?.[1] || '')
const transitionTotal = computed(() => settings.value?.storyboard_transition_effects
  .filter(item => item.enabled).reduce((sum, item) => sum + item.percentage, 0) || 0)

async function load() {
  loading.value = true
  try {
    [settings.value, ffmpegStatus.value] = await Promise.all([getSystemSettings(), getFfmpegStatus()])
  } catch (err) { error.value = err instanceof Error ? err.message : '系统设置加载失败' }
  finally { loading.value = false }
}

async function save() {
  if (!settings.value) return
  if (transitionTotal.value !== 100) { error.value = `已启用转场比例合计必须为 100%，当前为 ${transitionTotal.value}%`; return }
  saving.value = true
  try {
    settings.value = await saveSystemSettings(settings.value)
    rememberApiAddress(settings.value.app_host, settings.value.app_port)
    message.value = '设置已保存'
  } catch (err) { error.value = err instanceof Error ? err.message : '保存失败' }
  finally { saving.value = false }
}

async function chooseWorkspace() {
  if (!settings.value) return
  const selected = await selectDirectory(settings.value.workspace_dir, '选择工作目录')
  if (selected) settings.value.workspace_dir = selected
}

async function clearDeepseekKey() {
  settings.value = await clearSystemSecret('deepseek_api_key')
  message.value = '密钥已清除'
}

async function downloadFfmpeg() {
  saving.value = true
  try {
    const result = await installFfmpeg()
    settings.value = result.settings
    ffmpegStatus.value = result.status
    message.value = 'FFmpeg 已安装并完成检测'
  } catch (err) { error.value = err instanceof Error ? err.message : 'FFmpeg 安装失败' }
  finally { saving.value = false }
}

function normalizeTransitions() {
  if (!settings.value) return
  const enabled = settings.value.storyboard_transition_effects.filter(item => item.enabled)
  if (!enabled.length) enabled.push(settings.value.storyboard_transition_effects[0])
  settings.value.storyboard_transition_effects.forEach(item => { item.percentage = 0 })
  const base = Math.floor(100 / enabled.length)
  enabled.forEach((item, index) => { item.enabled = true; item.percentage = base + (index < 100 - base * enabled.length ? 1 : 0) })
}

function exportDiagnostics() {
  const report = JSON.stringify({ generated_at: new Date().toISOString(), settings: settings.value, ffmpeg: ffmpegStatus.value }, null, 2)
  const url = URL.createObjectURL(new Blob([report], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url; link.download = 'TubeAIFlow-diagnostics.json'; link.click(); URL.revokeObjectURL(url)
}

onMounted(load)
</script>

<template>
  <section class="settings-page settings-design-page">
    <div v-if="loading" class="settings-loading"><RefreshCw class="spin" :size="22" /> 正在加载系统设置...</div>
    <template v-else-if="settings">
      <div class="settings-page-head"><div><h2>{{ title }}</h2><p>{{ subtitle }}</p></div></div>

      <div v-if="section === 'general'" class="setting-grid two">
        <article class="setting-card"><h3>本地服务</h3><div class="form-list"><label><span>监听地址</span><input v-model="settings.app_host" /></label><label><span>端口</span><input v-model.number="settings.app_port" type="number" /></label></div></article>
        <article class="setting-card"><h3>路径</h3><div class="form-list"><label><span>工作目录</span><div class="input-action"><input v-model="settings.workspace_dir" /><button @click="chooseWorkspace">浏览</button></div></label><label><span>FFmpeg</span><input v-model="settings.ffmpeg_path" /></label><label><span>ffprobe</span><input v-model="settings.ffprobe_path" /></label></div></article>
      </div>

      <article v-else-if="section === 'ai-services'" class="setting-card"><h3>DeepSeek</h3><div class="form-grid compact-form"><label><span>基础 URL</span><input v-model="settings.deepseek_base_url" /></label><label><span>模型</span><select v-model="settings.deepseek_model"><option>deepseek-v4-flash</option><option>deepseek-v4-pro</option></select></label><label><span>API Key</span><input v-model="settings.deepseek_api_key" type="password" /></label><label><span>超时（秒）</span><input v-model.number="settings.deepseek_timeout_seconds" type="number" /></label><button v-if="settings.deepseek_api_key_configured" @click="clearDeepseekKey">清除密钥</button></div></article>

      <div v-else-if="section === 'tts'" class="setting-grid two"><article class="setting-card"><h3>Qwen3-TTS</h3><div class="form-list"><label><span>根目录</span><input v-model="settings.qwen_tts_root" /></label><label><span>Python</span><input v-model="settings.qwen_tts_python" /></label><label><span>模型目录</span><input v-model="settings.qwen_tts_model_dir" /></label><label><span>设备</span><input v-model="settings.qwen_tts_device" /></label></div></article><article class="setting-card"><h3>CosyVoice</h3><div class="form-list"><label><span>根目录</span><input v-model="settings.cosyvoice_root" /></label><label><span>Python</span><input v-model="settings.cosyvoice_python" /></label><label><span>模型目录</span><input v-model="settings.cosyvoice_model_dir" /></label></div></article></div>

      <article v-else-if="section === 'image-generation'" class="setting-card"><h3>本地图片生成</h3><div class="form-grid compact-form"><label><span>模型文件</span><input v-model="settings.image_generation_model_path" /></label><label><span>配置目录</span><input v-model="settings.image_generation_config_dir" /></label><label><span>设备</span><input v-model="settings.image_generation_device" /></label><label><span>宽度</span><input v-model.number="settings.image_generation_width" type="number" /></label><label><span>高度</span><input v-model.number="settings.image_generation_height" type="number" /></label><label><span>步数</span><input v-model.number="settings.image_generation_steps" type="number" /></label><label><span>单场景图片数</span><input v-model.number="settings.image_generation_candidates_per_scene" type="number" min="1" max="4" /></label><label class="wide"><span>负向提示词</span><textarea v-model="settings.image_generation_negative_prompt"></textarea></label></div></article>

      <article v-else-if="section === 'transitions'" class="setting-card"><h3>转场比例（{{ transitionTotal }}%）</h3><div class="transition-table"><label v-for="item in settings.storyboard_transition_effects" :key="item.name"><strong>{{ item.name }}</strong><input v-model.number="item.percentage" type="number" :disabled="!item.enabled" /><input v-model="item.enabled" type="checkbox" @change="normalizeTransitions" /></label></div><label class="field"><span>转场时长</span><input v-model.number="settings.storyboard_transition_duration_seconds" type="number" step="0.05" /></label></article>

      <article v-else class="setting-card"><h3>{{ section === 'render' ? 'FFmpeg 状态' : '本地环境诊断' }}</h3><p>{{ ffmpegStatus?.installed ? ffmpegStatus.version : '未检测到 FFmpeg' }}</p><p>{{ ffmpegStatus?.ffmpeg_path || settings.ffmpeg_path }}</p><button v-if="!ffmpegStatus?.installed" @click="downloadFfmpeg">自动安装 FFmpeg</button></article>

      <footer class="settings-actions"><button class="secondary-button" @click="load"><RefreshCw />重新检测</button><button v-if="section === 'diagnostics'" class="secondary-button" @click="exportDiagnostics"><Download />导出报告</button><button class="primary-button" :disabled="saving" @click="save"><Save />{{ saving ? '保存中...' : '保存设置' }}</button></footer>
    </template>
  </section>
</template>
