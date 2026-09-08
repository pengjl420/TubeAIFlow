<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute } from 'vue-router'
import { AlertTriangle, CheckCircle2, ChevronDown, Cloud, Cpu, Download, RefreshCw, Route, Save } from 'lucide-vue-next'

import { rememberApiAddress } from '../../api/client'
import {
  clearSystemSecret,
  downloadLocalLLMModel,
  getCleanupStatus,
  type CleanupStatus,
  getFfmpegStatus,
  getPremiereStatus,
  getSystemSettings,
  installFfmpeg,
  listLocalLLMModels,
  saveSystemSettings,
  type FfmpegStatus,
  type LocalLLMModel,
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
const cleanupStatus = ref<CleanupStatus | null>(null)
const cleanupStatusError = ref('')
const localLlmModels = ref<LocalLLMModel[]>([])
const downloadingModelId = ref('')
const activeAiPanel = ref<'routing' | 'local' | 'cloud' | null>(null)
const modelCatalogExpanded = ref(false)
let cleanupTimer: ReturnType<typeof setInterval> | undefined
let modelTimer: ReturnType<typeof setInterval> | undefined
async function refreshCleanupStatus() {
  try {
    cleanupStatus.value = await getCleanupStatus()
    cleanupStatusError.value = ''
  } catch {
    cleanupStatus.value = null
    cleanupStatusError.value = '无法读取清理状态。若刚更新应用，请先重启 TubeAiFolw；当前不能确认清理功能已生效。'
  }
}
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
const selectedLocalModel = computed(() => localLlmModels.value.find(model => model.id === settings.value?.local_llm_model))
const installedLocalModelCount = computed(() => localLlmModels.value.filter(model => model.installed).length)
const storyboardStrategyLabel = computed(() => ({
  hybrid: '智能混合',
  local: '完全本地',
  cloud: '云端优先',
}[settings.value?.storyboard_llm_strategy || 'hybrid'] || '未配置'))
const validationErrors = computed(() => {
  const value = settings.value
  if (!value) return []
  const issues: string[] = []
  if (!Number.isInteger(value.cleanup_retention_days) || value.cleanup_retention_days < 1 || value.cleanup_retention_days > 3650) issues.push('清理保留天数必须为 1–3650 的整数')
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value.cleanup_daily_time)) issues.push('请选择有效的每日清理时间')
  if (!value.app_host.trim()) issues.push('监听地址不能为空')
  if (!Number.isInteger(value.app_port) || value.app_port < 1 || value.app_port > 65535) issues.push('端口必须为 1–65535 的整数')
  if (transitionTotal.value !== 100) issues.push(`已启用转场比例合计必须为 100%，当前为 ${transitionTotal.value}%`)
  if (value.storyboard_transition_duration_seconds <= 0 || value.storyboard_transition_duration_seconds > 10) issues.push('转场时长必须大于 0 且不超过 10 秒')
  if (value.subtitle_min_cue_duration_ms <= 0 || value.subtitle_max_cue_duration_ms < value.subtitle_min_cue_duration_ms) issues.push('字幕最长时长必须大于或等于最短时长')
  if (value.subtitle_whisper_beam_size < 1 || value.subtitle_whisper_beam_size > 20) issues.push('Beam size 必须在 1–20 之间')
  if (value.image_generation_width < 256 || value.image_generation_height < 256) issues.push('图片宽高不能小于 256 像素')
  if (value.storyboard_cloud_confidence_threshold < 0 || value.storyboard_cloud_confidence_threshold > 1) issues.push('低置信度升级阈值必须在 0–1 之间')
  if (!Number.isInteger(value.storyboard_cloud_identity_risk_threshold) || value.storyboard_cloud_identity_risk_threshold < 0 || value.storyboard_cloud_identity_risk_threshold > 10) issues.push('身份风险升级阈值必须为 0–10 的整数')
  if (!value.local_llm_model.trim()) issues.push('请选择本地语义模型')
  return issues
})

function formatModelSize(bytes: number) {
  return `${(bytes / 1_000_000_000).toFixed(1)} GB`
}

function toggleAiPanel(panel: 'routing' | 'local' | 'cloud') {
  activeAiPanel.value = activeAiPanel.value === panel ? null : panel
}

async function refreshLocalModels() {
  try {
    localLlmModels.value = await listLocalLLMModels()
    const active = localLlmModels.value.some(item => ['queued', 'running'].includes(item.download?.status || ''))
    if (!active && modelTimer) { clearInterval(modelTimer); modelTimer = undefined }
  } catch (err) {
    if (section.value === 'ai-services') error.value = err instanceof Error ? err.message : '无法读取本地模型列表'
  }
}

async function downloadModel(model: LocalLLMModel) {
  if (dirty.value) {
    error.value = '请先保存模型目录和模型选择，再开始后台下载。'
    return
  }
  downloadingModelId.value = model.id
  try {
    await downloadLocalLLMModel(model.id)
    message.value = `${model.display_name} 已加入后台下载队列`
    await refreshLocalModels()
    if (!modelTimer) modelTimer = setInterval(() => { void refreshLocalModels() }, 1500)
  } catch (err) { error.value = err instanceof Error ? err.message : '模型下载任务创建失败' }
  finally { downloadingModelId.value = '' }
}

async function load() {
  loading.value = true
  try {
    [settings.value, ffmpegStatus.value, premiereStatus.value] = await Promise.all([
      getSystemSettings(),
      getFfmpegStatus(),
      getPremiereStatus(),
    ])
    savedSnapshot.value = JSON.stringify(settings.value)
    await refreshCleanupStatus()
    await refreshLocalModels()
  } catch (err) { error.value = err instanceof Error ? err.message : '系统设置加载失败' }
  finally { loading.value = false }
}

async function save() {
  if (!settings.value) return
  if (typeof settings.value.cleanup_enabled !== 'boolean') {
    error.value = '当前后端尚未加载自动清理功能，请重启 TubeAiFolw 后重新设置。'
    return
  }
  if (validationErrors.value.length) { error.value = validationErrors.value[0]; return }
  saving.value = true
  try {
    settings.value = await saveSystemSettings(settings.value)
    savedSnapshot.value = JSON.stringify(settings.value)
    lastSavedAt.value = new Date()
    rememberApiAddress(settings.value.app_host, settings.value.app_port)
    message.value = '设置已保存'
    await refreshCleanupStatus()
    await refreshLocalModels()
  } catch (err) { error.value = err instanceof Error ? err.message : '保存失败' }
  finally { saving.value = false }
}

async function chooseWorkspace() {
  if (!settings.value) return
  const selected = await selectDirectory(settings.value.workspace_dir, '选择工作目录')
  if (selected) settings.value.workspace_dir = selected
}

async function chooseLocalLlmModelsDirectory() {
  if (!settings.value) return
  const selected = await selectDirectory(settings.value.local_llm_models_dir, '选择本地语义模型目录')
  if (selected) {
    settings.value.local_llm_models_dir = selected
  }
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
onMounted(() => { cleanupTimer = setInterval(() => { void refreshCleanupStatus() }, 15000) })
onBeforeUnmount(() => { if (cleanupTimer) clearInterval(cleanupTimer) })
onBeforeUnmount(() => { if (modelTimer) clearInterval(modelTimer) })
</script>

<template>
  <section class="settings-page settings-design-page">
    <div v-if="loading" class="settings-loading"><RefreshCw class="spin" :size="22" /> 正在加载系统设置...</div>
    <template v-else-if="settings">
      <div class="settings-page-head"><div><h2>{{ title }}</h2><p>{{ subtitle }}</p></div><span v-if="dirty" class="settings-dirty-badge">有未保存修改</span></div>
      <div v-if="validationErrors.length" class="settings-validation" role="alert"><AlertTriangle :size="17" /><div><strong>请先修正以下配置</strong><span v-for="item in validationErrors" :key="item">{{ item }}</span></div></div>

      <div v-if="section === 'general'" class="setting-grid two">
        <article class="setting-card"><h3>自动清理</h3><div class="form-list">
          <label><span>启用每日自动清理</span><input v-model="settings.cleanup_enabled" type="checkbox" /></label>
          <div aria-live="polite">
            <p v-if="cleanupStatusError" role="alert">{{ cleanupStatusError }}</p>
            <template v-if="cleanupStatus">
              <p><strong>已保存配置：{{ cleanupStatus.enabled ? '已启用' : '已关闭' }}</strong> · 保留 {{ cleanupStatus.retention_days }} 天 · 每天 {{ cleanupStatus.daily_time }} · {{ cleanupStatus.completed_voice_tasks ? '包含已完成配音音频' : '仅历史日志' }}</p>
              <p>调度器：{{ cleanupStatus.worker_alive ? '运行中' : '未运行，请重启应用' }}</p>
              <p>下次执行：{{ !cleanupStatus.enabled ? '未启用' : cleanupStatus.catchup_pending ? '等待补执行（通常一分钟内）' : cleanupStatus.next_run_at ? new Date(cleanupStatus.next_run_at).toLocaleString() : '未知' }}</p>
              <p v-if="cleanupStatus.last_run">最近执行：{{ new Date(cleanupStatus.last_run.finished_at).toLocaleString() }}；删除 {{ cleanupStatus.last_run.deleted_tasks }} 个任务、{{ cleanupStatus.last_run.deleted_logs }} 个日志；失败 {{ cleanupStatus.last_run.errors }} 项。</p>
              <p v-else>最近执行：尚无执行记录。保存设置不会立即同步执行清理。</p>
              <p v-if="cleanupStatus.error" role="alert">{{ cleanupStatus.error }}</p>
            </template>
            <button type="button" @click="refreshCleanupStatus">刷新清理状态</button>
          </div>
          <label><span>保留天数</span><input v-model.number="settings.cleanup_retention_days" type="number" min="1" max="3650" /></label>
          <label><span>每天执行时间（本机时间）</span><input v-model="settings.cleanup_daily_time" type="time" /></label>
          <label><span>同时删除过期的已完成配音任务和音频</span><input v-model="settings.cleanup_completed_voice_tasks" type="checkbox" /></label>
        </div><details class="setting-help"><summary>查看清理范围与保留规则 <ChevronDown /></summary><div><p>永久删除超过保留天数的引擎轮转日志、已完成配音任务的日志；勾选音频清理后，也会删除对应任务记录与生成文件，不进入回收站。任务按完成时间、日志按最后修改时间计算。</p><p>保留运行中、排队、暂停、失败任务，以及视频项目、音色、模型和当前运行日志。应用运行时每天执行，错过时间会在下次启动后补执行。</p></div></details></article>
        <article class="setting-card"><h3>本地服务</h3><div class="form-list"><label><span>监听地址</span><input v-model="settings.app_host" /></label><label><span>端口</span><input v-model.number="settings.app_port" type="number" /></label></div></article>
        <article class="setting-card"><h3>路径</h3><div class="form-list"><label><span>工作目录</span><div class="input-action"><input v-model="settings.workspace_dir" /><button @click="chooseWorkspace">浏览</button></div></label><label><span>FFmpeg</span><input v-model="settings.ffmpeg_path" /></label><label><span>ffprobe</span><input v-model="settings.ffprobe_path" /></label><label><span>Adobe Premiere Pro</span><div class="input-action"><input v-model="settings.premiere_pro_path" placeholder="Adobe Premiere Pro.exe 的完整路径" /><button v-if="premiereStatus?.path" type="button" @click="useDetectedPremiere">使用检测结果</button></div><small :class="premiereStatus?.installed ? 'status-ok' : 'status-warning'">{{ premiereStatus?.installed ? `已检测：${premiereStatus.path}` : '未检测到 Premiere Pro' }}</small></label></div></article>
      </div>

      <div v-else-if="section === 'ai-services'" class="ai-settings-accordion">
        <article class="setting-card ai-settings-panel" :class="{ expanded: activeAiPanel === 'routing' }">
          <button class="ai-panel-summary" type="button" :aria-expanded="activeAiPanel === 'routing'" aria-controls="ai-routing-panel" @click="toggleAiPanel('routing')">
            <span class="ai-panel-icon"><Route /></span>
            <span class="ai-panel-copy"><strong>分镜智能路由</strong><small>决定何时使用本地模型或云端增强</small></span>
            <span class="ai-panel-status"><b>{{ storyboardStrategyLabel }}</b><small>缓存{{ settings.storyboard_llm_cache_enabled ? '已开启' : '已关闭' }}</small></span>
            <ChevronDown class="ai-panel-chevron" />
          </button>
          <div v-show="activeAiPanel === 'routing'" id="ai-routing-panel" class="ai-panel-content">
            <div class="form-list">
              <label><span>执行策略</span><select v-model="settings.storyboard_llm_strategy"><option value="hybrid">智能混合（推荐）</option><option value="local">完全本地</option><option value="cloud">质量优先（云端）</option></select></label>
              <label><span>低置信度升级阈值</span><input v-model.number="settings.storyboard_cloud_confidence_threshold" type="number" min="0" max="1" step="0.01" /><small>低于此置信度时升级至云端，建议 0.68。</small></label>
              <label><span>身份风险升级阈值</span><input v-model.number="settings.storyboard_cloud_identity_risk_threshold" type="number" min="0" max="10" /><small>人物、品牌或具体物体风险达到此值时升级，建议 8。</small></label>
              <label class="switch-row"><span>复用相同输入结果</span><input v-model="settings.storyboard_llm_cache_enabled" type="checkbox" /></label>
            </div>
            <p class="ai-panel-note">混合模式优先使用本地模型，仅在结果不确定、身份风险较高或本地服务不可用时调用云端模型。</p>
          </div>
        </article>

        <article class="setting-card ai-settings-panel" :class="{ expanded: activeAiPanel === 'local' }">
          <button class="ai-panel-summary" type="button" :aria-expanded="activeAiPanel === 'local'" aria-controls="ai-local-panel" @click="toggleAiPanel('local')">
            <span class="ai-panel-icon local"><Cpu /></span>
            <span class="ai-panel-copy"><strong>本地语义模型</strong><small>Qwen / llama.cpp · 数据保留在本机</small></span>
            <span class="ai-panel-status"><b>{{ selectedLocalModel?.display_name || '未选择模型' }}</b><small>{{ installedLocalModelCount }} 个模型已安装</small></span>
            <ChevronDown class="ai-panel-chevron" />
          </button>
          <div v-show="activeAiPanel === 'local'" id="ai-local-panel" class="ai-panel-content">
            <div class="form-list">
              <label><span>默认模型</span><select v-model="settings.local_llm_model"><option v-for="model in localLlmModels" :key="model.id" :value="model.id">{{ model.display_name }}{{ model.recommended ? '（推荐）' : '' }}{{ model.installed ? ' · 已安装' : ' · 未安装' }}</option></select><small>8B 平衡速度与质量；4B 更快，14B 质量更高。</small></label>
              <label><span>模型目录</span><div class="input-action"><input v-model="settings.local_llm_models_dir" /><button type="button" @click="chooseLocalLlmModelsDirectory">浏览</button></div></label>
              <div class="ai-advanced-grid">
                <label><span>服务 URL</span><input v-model="settings.local_llm_base_url" /></label>
                <label><span>超时（秒）</span><input v-model.number="settings.local_llm_timeout_seconds" type="number" /></label>
                <label><span>最大输出 Token</span><input v-model.number="settings.local_llm_max_tokens" type="number" /></label>
              </div>
            </div>
            <button class="ai-subpanel-toggle" type="button" :aria-expanded="modelCatalogExpanded" aria-controls="local-model-catalog" @click="modelCatalogExpanded = !modelCatalogExpanded">
              <span><strong>模型下载与管理</strong><small>{{ localLlmModels.length }} 个可用模型 · {{ installedLocalModelCount }} 个已安装</small></span>
              <ChevronDown :class="{ rotated: modelCatalogExpanded }" />
            </button>
            <div v-show="modelCatalogExpanded" id="local-model-catalog" class="ai-model-catalog">
              <div v-for="model in localLlmModels" :key="model.id" class="reference-file">
                <span><strong>{{ model.display_name }} <small v-if="model.recommended">推荐</small></strong><small>{{ model.description }}</small><small>{{ formatModelSize(model.size_bytes) }} · 最低内存 {{ model.min_ram_gb }} GB · 建议显存 {{ model.recommended_vram_gb }} GB · {{ model.license }}</small><small v-if="model.download?.status === 'failed'" class="status-warning">{{ model.download.error || '下载失败' }}</small></span>
                <div v-if="model.download && ['queued', 'running'].includes(model.download.status)" class="ai-model-progress"><small>{{ model.download.message }}</small><div class="progress-bar"><i class="progress-fill" :style="{ width: `${model.download.progress}%` }"></i></div><small>{{ Math.round(model.download.progress) }}%</small></div>
                <div><span v-if="model.installed" class="status-ok">已安装</span><button v-else type="button" :disabled="downloadingModelId === model.id || ['queued', 'running'].includes(model.download?.status || '')" @click="downloadModel(model)"><Download :size="14" />{{ model.download?.status === 'failed' ? '重新下载' : '后台下载' }}</button></div>
              </div>
            </div>
          </div>
        </article>

        <article class="setting-card ai-settings-panel" :class="{ expanded: activeAiPanel === 'cloud' }">
          <button class="ai-panel-summary" type="button" :aria-expanded="activeAiPanel === 'cloud'" aria-controls="ai-cloud-panel" @click="toggleAiPanel('cloud')">
            <span class="ai-panel-icon cloud"><Cloud /></span>
            <span class="ai-panel-copy"><strong>云端增强</strong><small>DeepSeek · 使用自己的 API Key</small></span>
            <span class="ai-panel-status" :class="{ configured: settings.deepseek_api_key_configured || settings.deepseek_api_key }"><b>{{ settings.deepseek_model }}</b><small>{{ settings.deepseek_api_key_configured || settings.deepseek_api_key ? '密钥已配置' : '等待配置密钥' }}</small></span>
            <ChevronDown class="ai-panel-chevron" />
          </button>
          <div v-show="activeAiPanel === 'cloud'" id="ai-cloud-panel" class="ai-panel-content">
            <div class="form-list">
              <label><span>基础 URL</span><input v-model="settings.deepseek_base_url" /></label>
              <label><span>模型</span><select v-model="settings.deepseek_model"><option>deepseek-v4-flash</option><option>deepseek-v4-pro</option></select></label>
              <label><span>API Key</span><input v-model="settings.deepseek_api_key" type="password" :placeholder="settings.deepseek_api_key_configured ? '已安全保存；输入新密钥可替换' : '输入 DeepSeek API Key'" /></label>
              <label><span>超时（秒）</span><input v-model.number="settings.deepseek_timeout_seconds" type="number" /></label>
            </div>
            <div v-if="settings.deepseek_api_key_configured" class="ai-danger-row"><span>密钥由系统安全存储，不会写入项目文件。</span><button type="button" @click="clearDeepseekKey">清除密钥</button></div>
          </div>
        </article>
      </div>

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
