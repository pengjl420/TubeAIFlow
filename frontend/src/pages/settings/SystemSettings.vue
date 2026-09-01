<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute } from 'vue-router'
import { AlertTriangle, CheckCircle2, Download, RefreshCw, Save } from 'lucide-vue-next'

import { rememberApiAddress } from '../../api/client'
import {
  clearSystemSecret,
  getFfmpegStatus,
  getPremiereStatus,
  getSystemSettings,
  installFfmpeg,
  saveSystemSettings,
  type FfmpegStatus,
  type PremiereStatus,
  type SystemSettings,
  selectDirectory,
} from '../../api/settings'
import { confirmAction, usePageFeedback } from '../../services/feedback'

const route = useRoute()
const section = computed(() => String(route.params.section || 'general'))
const settings = ref<SystemSettings | null>(null)
const ffmpegStatus = ref<FfmpegStatus | null>(null)
const premiereStatus = ref<PremiereStatus | null>(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const message = ref('')
const savedSnapshot = ref('')
const lastSavedAt = ref<Date | null>(null)
usePageFeedback(error, message, { errorTitle: '系统设置操作失败', messageTitle: '系统设置' })

const copy: Record<string, [string, string]> = {
  general: ['基础与存储', '配置本地服务、工作目录和工具路径'],
  'ai-services': ['AI 服务', '配置文本模型连接参数'],
  tts: ['配音引擎', '中文 IndexTTS、英文 MOSS-TTS、粤语 CosyVoice，保留 Qwen3-TTS'],
  subtitles: ['字幕对齐', '配置完全离线的原稿保真中英文字幕时间对齐'],
  'image-generation': ['图片生成', '配置本地图片模型与生成参数'],
  render: ['渲染与编码', '检测 FFmpeg 与视频编码环境'],
  transitions: ['转场策略', '配置场景转场比例与时长'],
  diagnostics: ['系统诊断', '检查本地运行环境'],
}
const title = computed(() => copy[section.value]?.[0] || '系统设置')
const subtitle = computed(() => copy[section.value]?.[1] || '')
const transitionTotal = computed(() => settings.value?.storyboard_transition_effects
  .filter(item => item.enabled).reduce((sum, item) => sum + item.percentage, 0) || 0)
const currentSnapshot = computed(() => settings.value ? JSON.stringify(settings.value) : '')
const dirty = computed(() => Boolean(settings.value && savedSnapshot.value && currentSnapshot.value !== savedSnapshot.value))
const validationErrors = computed(() => {
  const value = settings.value
  if (!value) return []
  const issues: string[] = []
  if (!value.app_host.trim()) issues.push('监听地址不能为空')
  if (!Number.isInteger(value.app_port) || value.app_port < 1 || value.app_port > 65535) issues.push('端口必须为 1–65535 的整数')
  if (transitionTotal.value !== 100) issues.push(`已启用转场比例合计必须为 100%，当前为 ${transitionTotal.value}%`)
  if (value.storyboard_transition_duration_seconds <= 0 || value.storyboard_transition_duration_seconds > 10) issues.push('转场时长必须大于 0 且不超过 10 秒')
  if (value.subtitle_min_cue_duration_ms <= 0 || value.subtitle_max_cue_duration_ms < value.subtitle_min_cue_duration_ms) issues.push('字幕最长时长必须大于或等于最短时长')
  if (value.subtitle_whisper_beam_size < 1 || value.subtitle_whisper_beam_size > 20) issues.push('Beam size 必须在 1–20 之间')
  if (value.image_generation_width < 256 || value.image_generation_height < 256) issues.push('图片宽高不能小于 256 像素')
  return issues
})

async function load() {
  loading.value = true
  try {
    [settings.value, ffmpegStatus.value, premiereStatus.value] = await Promise.all([
      getSystemSettings(),
      getFfmpegStatus(),
      getPremiereStatus(),
    ])
    savedSnapshot.value = JSON.stringify(settings.value)
  } catch (err) { error.value = err instanceof Error ? err.message : '系统设置加载失败' }
  finally { loading.value = false }
}

async function save() {
  if (!settings.value) return
  if (validationErrors.value.length) { error.value = validationErrors.value[0]; return }
  saving.value = true
  try {
    settings.value = await saveSystemSettings(settings.value)
    savedSnapshot.value = JSON.stringify(settings.value)
    lastSavedAt.value = new Date()
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
  const confirmed = await confirmAction({
    title: '清除 DeepSeek API Key？',
    description: '清除后，依赖 DeepSeek 的工作流将无法运行，直到重新配置密钥。',
    confirmText: '清除密钥',
    tone: 'danger',
  })
  if (!confirmed) return
  settings.value = await clearSystemSecret('deepseek_api_key')
  savedSnapshot.value = JSON.stringify(settings.value)
  message.value = '密钥已清除'
}

async function reloadSettings() {
  if (dirty.value) {
    const confirmed = await confirmAction({
      title: '放弃未保存的修改？',
      description: '重新检测会重新读取本地配置，当前修改将丢失。',
      confirmText: '放弃并重新检测',
      tone: 'warning',
    })
    if (!confirmed) return
  }
  await load()
}

async function downloadFfmpeg() {
  saving.value = true
  try {
    const result = await installFfmpeg()
    settings.value = result.settings
    savedSnapshot.value = JSON.stringify(settings.value)
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

function useDetectedPremiere() {
  if (settings.value && premiereStatus.value?.path) {
    settings.value.premiere_pro_path = premiereStatus.value.path
  }
}

function exportDiagnostics() {
  const report = JSON.stringify({
    generated_at: new Date().toISOString(),
    settings: settings.value,
    ffmpeg: ffmpegStatus.value,
    premiere: premiereStatus.value,
  }, null, 2)
  const url = URL.createObjectURL(new Blob([report], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url; link.download = 'TubeAiFolw-diagnostics.json'; link.click(); URL.revokeObjectURL(url)
}

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!dirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

async function canLeaveSettings() {
  if (!dirty.value) return true
  const confirmed = await confirmAction({
    title: '有未保存的设置',
    description: '离开此页面会丢失当前修改。',
    confirmText: '放弃修改并离开',
    tone: 'warning',
  })
  if (confirmed && settings.value && savedSnapshot.value) settings.value = JSON.parse(savedSnapshot.value) as SystemSettings
  return confirmed
}

onBeforeRouteLeave(canLeaveSettings)
onBeforeRouteUpdate(canLeaveSettings)
onMounted(() => { window.addEventListener('beforeunload', handleBeforeUnload); void load() })
onBeforeUnmount(() => window.removeEventListener('beforeunload', handleBeforeUnload))
</script>

<template>
  <section class="settings-page settings-design-page">
    <div v-if="loading" class="settings-loading"><RefreshCw class="spin" :size="22" /> 正在加载系统设置...</div>
    <template v-else-if="settings">
      <div class="settings-page-head"><div><h2>{{ title }}</h2><p>{{ subtitle }}</p></div><span v-if="dirty" class="settings-dirty-badge">有未保存修改</span></div>
      <div v-if="validationErrors.length" class="settings-validation" role="alert"><AlertTriangle :size="17" /><div><strong>请先修正以下配置</strong><span v-for="item in validationErrors" :key="item">{{ item }}</span></div></div>

      <div v-if="section === 'general'" class="setting-grid two">
        <article class="setting-card"><h3>本地服务</h3><div class="form-list"><label><span>监听地址</span><input v-model="settings.app_host" /></label><label><span>端口</span><input v-model.number="settings.app_port" type="number" /></label></div></article>
        <article class="setting-card"><h3>路径</h3><div class="form-list"><label><span>工作目录</span><div class="input-action"><input v-model="settings.workspace_dir" /><button @click="chooseWorkspace">浏览</button></div></label><label><span>FFmpeg</span><input v-model="settings.ffmpeg_path" /></label><label><span>ffprobe</span><input v-model="settings.ffprobe_path" /></label><label><span>Adobe Premiere Pro</span><div class="input-action"><input v-model="settings.premiere_pro_path" placeholder="Adobe Premiere Pro.exe 的完整路径" /><button v-if="premiereStatus?.path" type="button" @click="useDetectedPremiere">使用检测结果</button></div><small :class="premiereStatus?.installed ? 'status-ok' : 'status-warning'">{{ premiereStatus?.installed ? `已检测：${premiereStatus.path}` : '未检测到 Premiere Pro' }}</small></label></div></article>
      </div>

      <article v-else-if="section === 'ai-services'" class="setting-card"><h3>DeepSeek</h3><div class="form-grid compact-form"><label><span>基础 URL</span><input v-model="settings.deepseek_base_url" /></label><label><span>模型</span><select v-model="settings.deepseek_model"><option>deepseek-v4-flash</option><option>deepseek-v4-pro</option></select></label><label><span>API Key</span><input v-model="settings.deepseek_api_key" type="password" /></label><label><span>超时（秒）</span><input v-model.number="settings.deepseek_timeout_seconds" type="number" /></label><button v-if="settings.deepseek_api_key_configured" @click="clearDeepseekKey">清除密钥</button></div></article>

      <div v-else-if="section === 'tts'" class="setting-grid two">
        <article class="setting-card"><h3>中文 <small>IndexTTS</small></h3><div class="form-list"><label><span>根目录</span><input v-model="settings.index_tts_root" /></label><label><span>Python</span><input v-model="settings.index_tts_python" /></label><label><span>模型目录</span><input v-model="settings.index_tts_model_dir" /></label><label><span>设备</span><input v-model="settings.index_tts_device" /></label></div></article>
        <article class="setting-card"><h3>English <small>MOSS-TTS</small></h3><div class="form-list"><label><span>根目录</span><input v-model="settings.moss_tts_root" /></label><label><span>Python</span><input v-model="settings.moss_tts_python" /></label><label><span>模型目录</span><input v-model="settings.moss_tts_model_dir" /></label><label><span>音频 Tokenizer</span><input v-model="settings.moss_tts_codec_dir" /></label><label><span>设备</span><input v-model="settings.moss_tts_device" /></label></div></article>
        <article class="setting-card"><h3>粤语 <small>CosyVoice</small></h3><div class="form-list"><label><span>根目录</span><input v-model="settings.cosyvoice_root" /></label><label><span>Python</span><input v-model="settings.cosyvoice_python" /></label><label><span>模型目录</span><input v-model="settings.cosyvoice_model_dir" /></label></div></article>
        <article class="setting-card"><h3>兼容引擎 <small>Qwen3-TTS</small></h3><div class="form-list"><label><span>根目录</span><input v-model="settings.qwen_tts_root" /></label><label><span>Python</span><input v-model="settings.qwen_tts_python" /></label><label><span>模型目录</span><input v-model="settings.qwen_tts_model_dir" /></label><label><span>设备</span><input v-model="settings.qwen_tts_device" /></label></div></article>
      </div>

      <article v-else-if="section === 'subtitles'" class="setting-card"><h3>SATPA 本地字幕对齐</h3><div class="form-grid compact-form"><label><span>启用原稿保真对齐</span><input v-model="settings.subtitle_alignment_enabled" type="checkbox" /></label><label class="wide"><span>Whisper large-v3 CTranslate2 本地模型目录</span><input v-model="settings.subtitle_whisper_model_path" placeholder="未配置时使用比例计时并标记人工复核" /></label><label><span>设备</span><select v-model="settings.subtitle_whisper_device"><option value="cuda">CUDA</option><option value="cpu">CPU</option></select></label><label><span>计算精度</span><select v-model="settings.subtitle_whisper_compute_type"><option value="float16">float16</option><option value="int8_float16">int8_float16</option><option value="int8">int8</option><option value="float32">float32</option></select></label><label><span>Beam size</span><input v-model.number="settings.subtitle_whisper_beam_size" type="number" min="1" max="20" /></label><label><span>中文单条上限</span><input v-model.number="settings.subtitle_max_display_units" type="number" min="8" max="80" /></label><label><span>最短时长（ms）</span><input v-model.number="settings.subtitle_min_cue_duration_ms" type="number" /></label><label><span>最长时长（ms）</span><input v-model.number="settings.subtitle_max_cue_duration_ms" type="number" /></label></div><p>模型仅从本地路径加载，不会在运行时联网下载。最终 SRT 文字只取自原始逐字稿；ASR 结果仅用于定位时间。</p></article>

      <article v-else-if="section === 'image-generation'" class="setting-card"><h3>本地图片生成</h3><div class="form-grid compact-form"><label><span>模型文件</span><input v-model="settings.image_generation_model_path" /></label><label><span>配置目录</span><input v-model="settings.image_generation_config_dir" /></label><label><span>设备</span><input v-model="settings.image_generation_device" /></label><label><span>宽度</span><input v-model.number="settings.image_generation_width" type="number" /></label><label><span>高度</span><input v-model.number="settings.image_generation_height" type="number" /></label><label><span>步数</span><input v-model.number="settings.image_generation_steps" type="number" /></label><label><span>单场景图片数</span><input v-model.number="settings.image_generation_candidates_per_scene" type="number" min="1" max="4" /></label><label class="wide"><span>负向提示词</span><textarea v-model="settings.image_generation_negative_prompt"></textarea></label></div></article>

      <article v-else-if="section === 'transitions'" class="setting-card"><h3>转场比例（{{ transitionTotal }}%）</h3><div class="transition-table"><label v-for="item in settings.storyboard_transition_effects" :key="item.name"><strong>{{ item.name }}</strong><input v-model.number="item.percentage" type="number" :aria-label="`${item.name} 转场比例`" :disabled="!item.enabled" /><input v-model="item.enabled" type="checkbox" :aria-label="`启用 ${item.name} 转场`" @change="normalizeTransitions" /></label></div><label class="field"><span>转场时长</span><input v-model.number="settings.storyboard_transition_duration_seconds" type="number" min="0.05" max="10" step="0.05" aria-label="转场时长（秒）" /></label></article>

      <article v-else class="setting-card"><h3>{{ section === 'render' ? 'FFmpeg 状态' : '本地环境诊断' }}</h3><p>{{ ffmpegStatus?.installed ? ffmpegStatus.version : '未检测到 FFmpeg' }}</p><p>{{ ffmpegStatus?.ffmpeg_path || settings.ffmpeg_path }}</p><button v-if="!ffmpegStatus?.installed" @click="downloadFfmpeg">自动安装 FFmpeg</button></article>

      <footer class="settings-actions">
        <div class="settings-save-state" :class="{ dirty }"><CheckCircle2 v-if="!dirty" :size="16" /><AlertTriangle v-else :size="16" /><span>{{ dirty ? '修改尚未保存' : lastSavedAt ? `${lastSavedAt.toLocaleTimeString()} 已保存` : '当前设置已同步' }}</span></div>
        <button class="secondary-button" type="button" @click="reloadSettings"><RefreshCw />重新检测</button>
        <button v-if="section === 'diagnostics'" class="secondary-button" type="button" @click="exportDiagnostics"><Download />导出报告</button>
        <button class="primary-button" type="button" :disabled="saving || !dirty || validationErrors.length > 0" @click="save"><Save />{{ saving ? '保存中...' : dirty ? '保存设置' : '已保存' }}</button>
      </footer>
    </template>
  </section>
</template>
