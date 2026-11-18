<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute } from 'vue-router'
import { AlertTriangle, CheckCircle2, ChevronDown, Download, RefreshCw, Save } from 'lucide-vue-next'

import { rememberApiAddress } from '../../api/client'
import {
  clearSystemSecret,
  getCleanupStatus,
  type CleanupStatus,
  getFfmpegStatus,
  getHardwareStatus,
  getPremiereStatus,
  getSystemSettings,
  installFfmpeg,
  saveSystemSettings,
  type FfmpegStatus,
  type HardwareStatus,
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
const hardwareStatus = ref<HardwareStatus | null>(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const message = ref('')
const savedSnapshot = ref('')
const lastSavedAt = ref<Date | null>(null)
const cleanupStatus = ref<CleanupStatus | null>(null)
const cleanupStatusError = ref('')
let cleanupTimer: ReturnType<typeof setInterval> | undefined
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
  subtitles: ['基础字幕', '按 TTS 段落时长生成原稿字幕'],
  'image-generation': ['图片生成', '配置 Doubao Seedream 5.0 Flash 云端 API'],
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
  if (!Number.isInteger(value.cleanup_retention_days) || value.cleanup_retention_days < 1 || value.cleanup_retention_days > 3650) issues.push('清理保留天数必须为 1–3650 的整数')
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(value.cleanup_daily_time)) issues.push('请选择有效的每日清理时间')
  if (!value.app_host.trim()) issues.push('监听地址不能为空')
  if (!Number.isInteger(value.app_port) || value.app_port < 1 || value.app_port > 65535) issues.push('端口必须为 1–65535 的整数')
  if (transitionTotal.value !== 100) issues.push(`已启用转场比例合计必须为 100%，当前为 ${transitionTotal.value}%`)
  if (value.storyboard_transition_duration_seconds <= 0 || value.storyboard_transition_duration_seconds > 10) issues.push('转场时长必须大于 0 且不超过 10 秒')
  if (value.subtitle_min_cue_duration_ms <= 0 || value.subtitle_max_cue_duration_ms < value.subtitle_min_cue_duration_ms) issues.push('字幕最长时长必须大于或等于最短时长')
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
    if (section.value === 'diagnostics') hardwareStatus.value = await getHardwareStatus()
    savedSnapshot.value = JSON.stringify(settings.value)
    await refreshCleanupStatus()
  } catch (err) { error.value = err instanceof Error ? err.message : '系统设置加载失败' }
  finally { loading.value = false }
}

watch(section, async value => {
  if (value !== 'diagnostics' || hardwareStatus.value) return
  try { hardwareStatus.value = await getHardwareStatus() }
  catch (err) { error.value = err instanceof Error ? err.message : '本地环境检测失败' }
})

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

async function clearSeedreamKey() {
  const confirmed = await confirmAction({
    title: '清除 Seedream API Key？',
    description: '清除后，使用 Doubao Seedream 5.0 Flash 的图片生成任务将无法运行。',
    confirmText: '清除密钥',
    tone: 'danger',
  })
  if (!confirmed) return
  settings.value = await clearSystemSecret('seedream_api_key')
  savedSnapshot.value = JSON.stringify(settings.value)
  message.value = 'Seedream 密钥已清除'
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
    hardware: hardwareStatus.value,
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
        <article class="setting-card"><h3>本地服务</h3><div class="form-list"><label><span>监听地址</span><select v-model="settings.app_host"><option value="127.0.0.1">127.0.0.1（仅本机）</option><option value="localhost">localhost（仅本机）</option></select></label><label><span>端口</span><input v-model.number="settings.app_port" type="number" /></label></div><small>Engine 固定为仅本机访问，避免项目文件和 BYOK 操作暴露到局域网。</small></article>
        <article class="setting-card"><h3>路径</h3><div class="form-list"><label><span>工作目录</span><div class="input-action"><input v-model="settings.workspace_dir" /><button @click="chooseWorkspace">浏览</button></div></label><label><span>FFmpeg</span><input v-model="settings.ffmpeg_path" /></label><label><span>ffprobe</span><input v-model="settings.ffprobe_path" /></label><label><span>Adobe Premiere Pro</span><div class="input-action"><input v-model="settings.premiere_pro_path" placeholder="Adobe Premiere Pro.exe 的完整路径" /><button v-if="premiereStatus?.path" type="button" @click="useDetectedPremiere">使用检测结果</button></div><small :class="premiereStatus?.installed ? 'status-ok' : 'status-warning'">{{ premiereStatus?.installed ? `已检测：${premiereStatus.path}` : '未检测到 Premiere Pro' }}</small></label></div></article>
      </div>

      <div v-else-if="section === 'ai-services'" class="ai-settings-accordion">
        <article class="setting-card"><h3>DeepSeek 云端文本模型</h3><p>AI 分段与语义分镜使用此服务。</p><div class="form-list">
              <label><span>基础 URL</span><input v-model="settings.deepseek_base_url" /></label>
              <label><span>模型</span><select v-model="settings.deepseek_model"><option>deepseek-v4-flash</option><option>deepseek-v4-pro</option></select></label>
              <label><span>API Key</span><input v-model="settings.deepseek_api_key" type="password" :placeholder="settings.deepseek_api_key_configured ? '已安全保存；输入新密钥可替换' : '输入 DeepSeek API Key'" /></label>
              <label><span>超时（秒）</span><input v-model.number="settings.deepseek_timeout_seconds" type="number" /></label><label><span>复用相同输入结果</span><input v-model="settings.storyboard_llm_cache_enabled" type="checkbox" /></label>
            </div>
            <div v-if="settings.deepseek_api_key_configured" class="ai-danger-row"><span>密钥由系统安全存储，不会写入项目文件。</span><button type="button" @click="clearDeepseekKey">清除密钥</button></div>
        </article>
      </div>

      <div v-else-if="section === 'tts'" class="setting-grid two">
        <article class="setting-card"><h3>中文 <small>IndexTTS</small></h3><div class="form-list"><label><span>根目录</span><input v-model="settings.index_tts_root" /></label><label><span>Python</span><input v-model="settings.index_tts_python" /></label><label><span>模型目录</span><input v-model="settings.index_tts_model_dir" /></label><label><span>设备</span><input v-model="settings.index_tts_device" /></label></div></article>
        <article class="setting-card"><h3>English <small>MOSS-TTS</small></h3><div class="form-list"><label><span>根目录</span><input v-model="settings.moss_tts_root" /></label><label><span>Python</span><input v-model="settings.moss_tts_python" /></label><label><span>模型目录</span><input v-model="settings.moss_tts_model_dir" /></label><label><span>音频 Tokenizer</span><input v-model="settings.moss_tts_codec_dir" /></label><label><span>设备</span><input v-model="settings.moss_tts_device" /></label></div></article>
        <article class="setting-card"><h3>粤语 <small>CosyVoice</small></h3><div class="form-list"><label><span>根目录</span><input v-model="settings.cosyvoice_root" /></label><label><span>Python</span><input v-model="settings.cosyvoice_python" /></label><label><span>模型目录</span><input v-model="settings.cosyvoice_model_dir" /></label></div></article>
        <article class="setting-card"><h3>兼容引擎 <small>Qwen3-TTS</small></h3><div class="form-list"><label><span>根目录</span><input v-model="settings.qwen_tts_root" /></label><label><span>Python</span><input v-model="settings.qwen_tts_python" /></label><label><span>模型目录</span><input v-model="settings.qwen_tts_model_dir" /></label><label><span>设备</span><input v-model="settings.qwen_tts_device" /></label></div></article>
      </div>

      <article v-else-if="section === 'subtitles'" class="setting-card"><h3>基础字幕</h3><p>按 TTS 段落实际音频时长分配字幕时间，文字取自原稿；请在剪辑软件中人工复核边界。</p><div class="form-list"><label><span>单条显示长度上限</span><input v-model.number="settings.subtitle_max_display_units" type="number" min="8" max="80" /></label><label><span>最短时长（ms）</span><input v-model.number="settings.subtitle_min_cue_duration_ms" type="number" /></label><label><span>最长时长（ms）</span><input v-model.number="settings.subtitle_max_cue_duration_ms" type="number" /></label></div></article>

      <div v-else-if="section === 'image-generation'" class="setting-stack">
        <article class="setting-card"><h3>Doubao Seedream 5.0 <small>火山方舟 · BYOK</small></h3><div class="form-grid compact-form"><label><span>图片模型</span><select v-model="settings.image_generation_provider_id"><option value="image.seedream_5_flash">Seedream 5.0 Flash</option></select></label><label><span>单场景图片数</span><input v-model.number="settings.image_generation_candidates_per_scene" type="number" min="1" max="4" /></label><label class="wide"><span>API Key</span><input v-model="settings.seedream_api_key" type="password" :placeholder="settings.seedream_api_key_configured ? '已由 Windows DPAPI 安全保存；输入新密钥可替换' : '输入火山方舟 API Key'" /></label><label class="wide"><span>全局排除内容</span><textarea v-model="settings.image_generation_negative_prompt"></textarea></label></div><p>使用火山方舟 API Key。输出固定为 16:9、2848×1600、PNG、无明水印和 Base64 本地持久化；请求串行执行，仅对连接未建立或明确拒绝的限流请求重试，结果不确定时不自动重发。</p><p>TubeAiFolw 已禁用本地图片模型，图片只能通过用户配置的云端 API 生成。</p><div v-if="settings.seedream_api_key_configured" class="ai-danger-row"><span>密钥不会写入项目文件、任务快照或日志。</span><button type="button" @click="clearSeedreamKey">清除密钥</button></div></article>
      </div>

      <article v-else-if="section === 'transitions'" class="setting-card"><h3>转场比例（{{ transitionTotal }}%）</h3><div class="transition-table"><label v-for="item in settings.storyboard_transition_effects" :key="item.name"><strong>{{ item.name }}</strong><input v-model.number="item.percentage" type="number" :aria-label="`${item.name} 转场比例`" :disabled="!item.enabled" /><input v-model="item.enabled" type="checkbox" :aria-label="`启用 ${item.name} 转场`" @change="normalizeTransitions" /></label></div><label class="field"><span>转场时长</span><input v-model.number="settings.storyboard_transition_duration_seconds" type="number" min="0.05" max="10" step="0.05" aria-label="转场时长（秒）" /></label></article>

      <article v-else-if="section === 'render'" class="setting-card"><h3>FFmpeg 状态</h3><p>{{ ffmpegStatus?.installed ? ffmpegStatus.version : '未检测到 FFmpeg' }}</p><p>{{ ffmpegStatus?.ffmpeg_path || settings.ffmpeg_path }}</p><button v-if="!ffmpegStatus?.installed" @click="downloadFfmpeg">自动安装 FFmpeg</button></article>

      <div v-else class="setting-stack diagnostics-stack">
        <div v-if="hardwareStatus" class="setting-metrics four">
          <article><div><small>运行能力</small><strong :class="`rating-${hardwareStatus.rating}`">{{ hardwareStatus.rating === 'recommended' ? '推荐配置' : hardwareStatus.rating === 'compatible' ? '兼容配置' : '受限配置' }}</strong><em>{{ hardwareStatus.ffmpeg_available ? 'FFmpeg 可用' : '需要安装 FFmpeg' }}</em></div></article>
          <article><div><small>内存</small><strong>{{ hardwareStatus.memory.total_gb ?? '未知' }} GB</strong><em v-if="hardwareStatus.memory.load_percent !== undefined">当前负载 {{ hardwareStatus.memory.load_percent }}%</em></div></article>
          <article><div><small>工作盘可用空间</small><strong>{{ hardwareStatus.disk.free_gb }} GB</strong><em>{{ hardwareStatus.disk.path }}</em></div></article>
          <article><div><small>推荐编码器</small><strong>{{ hardwareStatus.recommended_encoder }}</strong><em>{{ hardwareStatus.hardware_encoders.length ? '已检测硬件编码' : '软件编码回退' }}</em></div></article>
        </div>
        <article v-if="hardwareStatus" class="setting-card diagnostic-table">
          <h3>本地运行环境</h3>
          <div class="table-head"><span>组件</span><span>状态</span><span>详情</span></div>
          <p><strong>操作系统</strong><b class="ok">可用</b><em>{{ hardwareStatus.os.name }} {{ hardwareStatus.os.release }} · {{ hardwareStatus.os.version }}</em></p>
          <p><strong>CPU</strong><b class="ok">{{ hardwareStatus.cpu.logical_cores ?? '—' }} 线程</b><em>{{ hardwareStatus.cpu.name }}</em></p>
          <p><strong>GPU / CUDA</strong><b :class="hardwareStatus.gpus.length ? 'ok' : 'warn'">{{ hardwareStatus.gpus.length ? `${hardwareStatus.gpus.length} 张` : '未检测' }}</b><em>{{ hardwareStatus.gpus.length ? hardwareStatus.gpus.map(gpu => `${gpu.name} · ${gpu.vram_total_mb ?? '未知'} MB`).join('；') : '仍可使用 CPU 与软件编码' }}{{ hardwareStatus.cuda_version ? ` · CUDA ${hardwareStatus.cuda_version}` : '' }}</em></p>
          <p><strong>硬件编码</strong><b :class="hardwareStatus.hardware_encoders.length ? 'ok' : 'warn'">{{ hardwareStatus.hardware_encoders.length ? '可用' : '回退' }}</b><em>{{ hardwareStatus.hardware_encoders.join('、') || 'libx264' }}</em></p>
          <p><strong>FFmpeg</strong><b :class="hardwareStatus.ffmpeg_available ? 'ok' : 'bad'">{{ hardwareStatus.ffmpeg_available ? '可用' : '缺失' }}</b><em>{{ ffmpegStatus?.ffmpeg_path || settings.ffmpeg_path }}</em></p>
        </article>
      </div>

      <footer class="settings-actions">
        <div class="settings-save-state" :class="{ dirty }"><CheckCircle2 v-if="!dirty" :size="16" /><AlertTriangle v-else :size="16" /><span>{{ dirty ? '修改尚未保存' : lastSavedAt ? `${lastSavedAt.toLocaleTimeString()} 已保存` : '当前设置已同步' }}</span></div>
        <button class="secondary-button" type="button" @click="reloadSettings"><RefreshCw />重新检测</button>
        <button v-if="section === 'diagnostics'" class="secondary-button" type="button" @click="exportDiagnostics"><Download />导出报告</button>
        <button class="primary-button" type="button" :disabled="saving || !dirty || validationErrors.length > 0" @click="save"><Save />{{ saving ? '保存中...' : dirty ? '保存设置' : '已保存' }}</button>
      </footer>
    </template>
  </section>
</template>
