<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { rememberApiAddress } from '../../api/client'
import { selectDirectory } from '../../api/projects'
import {
  clearSystemSecret,
  getFfmpegStatus,
  getFramePackStatus,
  getMediaProviderStatuses,
  getSystemSettings,
  installFfmpeg,
  saveSystemSettings,
  type FfmpegStatus,
  type FramePackStatus,
  type LandscapeTransitionName,
  type MediaProviderStatus,
  type SystemSettings,
} from '../../api/settings'

const settings = ref<SystemSettings | null>(null)
const loading = ref(false)
const saving = ref(false)
const installingFfmpeg = ref(false)
const ffmpegStatus = ref<FfmpegStatus | null>(null)
const framepackStatus = ref<FramePackStatus | null>(null)
const mediaProviderStatuses = ref<MediaProviderStatus[]>([])
const error = ref('')
const message = ref('')

const transitionLabels: Record<LandscapeTransitionName, { label: string; description: string }> = {
  fade: { label: '柔和叠化', description: '最自然的交叉淡化，适合作为主要转场。' },
  dissolve: { label: '轻微溶解', description: '带少量纹理变化的柔和过渡。' },
  fadeblack: { label: '短暂淡黑', description: '快速经过黑场，建议保持较低占比。' },
  smoothleft: { label: '平滑左移', description: '画面柔和向左交接，适合移动镜头。' },
  smoothright: { label: '平滑右移', description: '画面柔和向右交接，可与左移少量搭配。' },
}

const enabledTransitionPercentage = computed(() => (
  settings.value?.landscape_transition_effects
    .filter((item) => item.enabled)
    .reduce((total, item) => total + Number(item.percentage || 0), 0) || 0
))

const enabledTransitionCount = computed(() => (
  settings.value?.landscape_transition_effects.filter((item) => item.enabled).length || 0
))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [loadedSettings, loadedFfmpegStatus, loadedProviderStatuses, loadedFramePackStatus] = await Promise.all([
      getSystemSettings(),
      getFfmpegStatus(),
      getMediaProviderStatuses(),
      getFramePackStatus(),
    ])
    settings.value = loadedSettings
    ffmpegStatus.value = loadedFfmpegStatus
    mediaProviderStatuses.value = loadedProviderStatuses
    framepackStatus.value = loadedFramePackStatus
  } catch (err) {
    error.value = err instanceof Error ? err.message : '系统设置加载失败'
  } finally {
    loading.value = false
  }
}

async function downloadFfmpeg() {
  installingFfmpeg.value = true
  error.value = ''
  message.value = ''
  try {
    const result = await installFfmpeg()
    settings.value = result.settings
    ffmpegStatus.value = result.status
    message.value = `FFmpeg ${result.status.version || ''} 已安装，路径已自动保存。`
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'FFmpeg 自动安装失败'
  } finally {
    installingFfmpeg.value = false
  }
}

async function save() {
  if (!settings.value) return
  if (enabledTransitionCount.value > 0 && enabledTransitionPercentage.value !== 100) {
    error.value = `已启用转场的占比合计必须为 100%，当前为 ${enabledTransitionPercentage.value}%`
    return
  }
  const invalidTransition = settings.value.landscape_transition_effects.some(
    (item) => item.enabled && (!Number.isFinite(item.percentage) || item.percentage <= 0),
  )
  if (invalidTransition) {
    error.value = '已启用转场的占比必须大于 0%'
    return
  }
  saving.value = true
  error.value = ''
  message.value = ''
  try {
    settings.value = await saveSystemSettings(settings.value)
    mediaProviderStatuses.value = await getMediaProviderStatuses()
    rememberApiAddress(settings.value.app_host, settings.value.app_port)
    message.value = '系统设置已保存。监听地址或端口变更需要重启应用后生效。'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '系统设置保存失败'
  } finally {
    saving.value = false
  }
}

async function clearApiKey(field: 'deepseek_api_key' | 'pexels_api_key' | 'pixabay_api_key', label: string) {
  error.value = ''
  message.value = ''
  try {
    settings.value = await clearSystemSecret(field)
    mediaProviderStatuses.value = await getMediaProviderStatuses()
    message.value = `${label} API Key 已清除`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '密钥清除失败'
  }
}

async function chooseProviderStorage(provider: 'pexels' | 'pixabay') {
  if (!settings.value) return
  const field = `${provider}_storage_dir` as 'pexels_storage_dir' | 'pixabay_storage_dir'
  error.value = ''
  try {
    const selected = await selectDirectory(
      settings.value[field] || settings.value.workspace_dir,
      `选择 ${provider === 'pexels' ? 'Pexels' : 'Pixabay'} 素材存储文件夹`,
    )
    if (selected) settings.value[field] = selected
  } catch (err) {
    error.value = err instanceof Error ? err.message : '无法打开文件夹选择器'
  }
}

function providerStatus(provider: 'pexels' | 'pixabay') {
  return mediaProviderStatuses.value.find((item) => item.provider === provider)
}

function providerStatusLabel(provider: 'pexels' | 'pixabay') {
  const status = providerStatus(provider)
  if (!status?.configured) return '未配置'
  if (status.status === 'cooldown') return '额度冷却中'
  if (status.status === 'error') return '请求异常'
  return '可用'
}

function providerQuotaText(provider: 'pexels' | 'pixabay') {
  const status = providerStatus(provider)
  if (!status?.configured) return '配置 API Key 后启用在线素材检索。'
  const parts: string[] = []
  if (status.remaining !== null) parts.push(`剩余请求 ${status.remaining}`)
  if (status.rate_limit !== null) parts.push(`当前限制 ${status.rate_limit}`)
  if (status.reset_at) parts.push(`重置时间 ${new Date(status.reset_at).toLocaleString()}`)
  if (status.last_error) parts.push(status.last_error)
  return parts.length ? parts.join('；') : '尚未发起请求，首次在线检索后显示配额状态。'
}

onMounted(load)
</script>

<template>
  <section class="settings-page">
    <div class="page-title settings-sticky-header">
      <div>
        <span class="page-kicker">LOCAL SYSTEM</span>
        <h1>系统设置</h1>
        <p class="muted">配置保存在本机 SQLite 数据库中，不会读取 .env 文件。</p>
      </div>
      <div v-if="error || message" class="settings-save-status" aria-live="polite">
        <span v-if="error" class="error">{{ error }}</span>
        <span v-else class="success">{{ message }}</span>
      </div>
      <button v-if="settings" class="primary-button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存全部设置' }}</button>
    </div>

    <p v-if="loading" class="muted">正在加载…</p>
    <div v-else-if="settings" class="grid settings-grid">
      <details class="panel settings-disclosure">
        <summary>
          <span class="settings-disclosure-heading">
            <strong>基础设置</strong>
            <small>本地服务、工作目录与 FFmpeg</small>
          </span>
          <span class="settings-disclosure-icon" aria-hidden="true">⌄</span>
        </summary>
        <div class="settings-disclosure-content">
        <p class="section-description">控制本地服务地址、项目数据存放位置，以及音频处理工具的位置。一般只需确认工作目录和 FFmpeg 配置。</p>
        <div class="form-grid">
          <label class="field">
            <span>后端监听地址</span>
            <input v-model="settings.app_host" placeholder="127.0.0.1" />
            <small>本机使用请填写 <code>127.0.0.1</code>。保存后需要重启应用；不建议设置为公网地址。</small>
          </label>
          <label class="field">
            <span>后端端口</span>
            <input v-model.number="settings.app_port" type="number" min="1" max="65535" placeholder="18080" />
            <small>后端 HTTP 服务使用的端口，默认 <code>18080</code>。端口被占用时可换成其他未使用端口，保存后需要重启。</small>
          </label>
          <label class="field full-width">
            <span>工作目录</span>
            <input v-model="settings.workspace_dir" placeholder="F:\TubeAIFlow\backend\workspace" />
            <small>用于保存项目、分段音频、字幕、日志和导出文件。请填写具有读写权限的文件夹绝对路径；修改后不会自动搬迁旧项目。</small>
          </label>
          <label class="field">
            <span>FFmpeg 命令或路径</span>
            <input v-model="settings.ffmpeg_path" placeholder="ffmpeg" />
            <small>已加入系统 PATH 时填写 <code>ffmpeg</code>；否则填写 <code>ffmpeg.exe</code> 的完整路径，用于音频转换和拼接。</small>
          </label>
          <label class="field">
            <span>FFprobe 命令或路径</span>
            <input v-model="settings.ffprobe_path" placeholder="ffprobe" />
            <small>已加入系统 PATH 时填写 <code>ffprobe</code>；否则填写 <code>ffprobe.exe</code> 的完整路径，用于读取真实音频时长。</small>
          </label>
        </div>
        <div class="ffmpeg-install-row">
          <div>
            <strong>{{ ffmpegStatus?.installed ? 'FFmpeg 已可用' : '未检测到可用的 FFmpeg' }}</strong>
            <small v-if="ffmpegStatus?.installed">
              {{ ffmpegStatus.version ? `版本 ${ffmpegStatus.version}` : '版本未知' }}；FFmpeg 与 FFprobe 路径已检测通过。
            </small>
            <small v-else-if="ffmpegStatus?.platform_supported">
              可自动下载适用于 Windows 64 位的 release essentials 构建，并将两个可执行文件路径写入当前配置。
            </small>
            <small v-else>自动安装目前仅支持 Windows 10/11 64 位系统。</small>
          </div>
          <button
            class="secondary-button"
            type="button"
            :disabled="installingFfmpeg || ffmpegStatus?.platform_supported === false"
            @click="downloadFfmpeg"
          >
            {{ installingFfmpeg ? '正在下载并校验…' : (ffmpegStatus?.installed ? '重新检测并安装最新版' : '自动下载安装') }}
          </button>
        </div>
        <div class="notice">系统设置数据库固定保存在 <code>backend/workspace/app.db</code>，不会随着“工作目录”一起移动。</div>
        </div>
      </details>

      <details class="panel settings-disclosure">
        <summary>
          <span class="settings-disclosure-heading"><strong>FramePack 图片转视频</strong><small>独立常驻 Worker 与混合渲染</small></span>
          <span class="settings-disclosure-icon" aria-hidden="true">⌄</span>
        </summary>
        <div class="settings-disclosure-content">
          <p class="section-description">FramePack 在独立 Python 环境中常驻并串行生成重点镜头；不可用、超时、OOM 或质量不合格时自动降级到 FFmpeg。</p>
          <div class="notice">
            Worker：{{ framepackStatus?.health?.status || 'unavailable' }}；
            模型：{{ framepackStatus?.health?.model_loaded ? '已加载' : '未加载' }}；
            GPU：{{ framepackStatus?.health?.gpu || '未检测' }}
            <template v-if="framepackStatus?.health?.error">；{{ framepackStatus.health.error }}</template>
          </div>
          <div class="form-grid">
            <label class="checkbox-field"><input v-model="settings.framepack_enabled" type="checkbox" /><span><strong>启用混合渲染</strong><small>只对符合风险规则的重点图片镜头启用。</small></span></label>
            <label class="checkbox-field"><input v-model="settings.framepack_auto_start_worker" type="checkbox" /><span><strong>自动启动 Worker</strong><small>需要先配置独立 Python 环境。</small></span></label>
            <label class="field full-width"><span>FramePack Python</span><input v-model="settings.framepack_python" placeholder="D:\FramePack\.venv\Scripts\python.exe" /></label>
            <label class="field full-width"><span>Hugging Face 模型缓存目录</span><input v-model="settings.framepack_cache_dir" placeholder="D:\FramePack\hf_download" /></label>
            <label class="field"><span>Worker 地址</span><input v-model="settings.framepack_worker_host" /></label>
            <label class="field"><span>Worker 端口</span><input v-model.number="settings.framepack_worker_port" type="number" min="1" max="65535" /></label>
            <label class="field full-width"><span>FramePack Transformer</span><input v-model="settings.framepack_model_id" /></label>
            <label class="field full-width"><span>HunyuanVideo 基础模型</span><input v-model="settings.framepack_base_model_id" /></label>
            <label class="field"><span>采样策略</span><select v-model="settings.framepack_sampling_type"><option value="vanilla">F1 vanilla</option><option value="inverted_anti_drifting">Inverted anti-drifting</option></select></label>
            <label class="checkbox-field"><input v-model="settings.framepack_allow_model_download" type="checkbox" /><span><strong>允许下载模型</strong><small>首次可能下载超过 30GB，默认关闭。</small></span></label>
            <label class="field"><span>生成宽度</span><input v-model.number="settings.framepack_width" type="number" min="256" max="1920" step="16" /></label>
            <label class="field"><span>生成高度</span><input v-model.number="settings.framepack_height" type="number" min="256" max="1088" step="16" /></label>
            <label class="field"><span>采样步数</span><input v-model.number="settings.framepack_steps" type="number" min="1" max="100" /></label>
            <label class="field"><span>Guidance Scale</span><input v-model.number="settings.framepack_guidance_scale" type="number" min="1" max="32" step="0.1" /></label>
            <label class="field"><span>最大镜头比例</span><input v-model.number="settings.framepack_max_ratio" type="number" min="0" max="1" step="0.05" /></label>
            <label class="field"><span>失败重试次数</span><input v-model.number="settings.framepack_max_retries" type="number" min="0" max="3" /></label>
            <label class="checkbox-field"><input v-model="settings.framepack_cpu_offload" type="checkbox" /><span><strong>CPU Offload</strong><small>8GB 显存建议开启。</small></span></label>
          </div>
        </div>
      </details>

      <details class="panel settings-disclosure">
        <summary>
          <span class="settings-disclosure-heading">
            <strong>纯风景视频转场</strong>
            <small>短转场效果、启用状态与随机占比</small>
          </span>
          <span class="settings-disclosure-icon" aria-hidden="true">⌄</span>
        </summary>
        <div class="settings-disclosure-content">
          <p class="section-description">
            系统会把视频随机分成 2–5 个一组，并在每组中选择 1–2 个镜头边界应用转场，其余位置保持硬切。单次转场约 0.45 秒。
          </p>
          <div class="transition-settings-list">
            <div
              v-for="effect in settings.landscape_transition_effects"
              :key="effect.name"
              class="transition-setting-row"
              :class="{ 'is-disabled': !effect.enabled }"
            >
              <label class="transition-effect-toggle">
                <input v-model="effect.enabled" type="checkbox" />
                <span>
                  <strong>{{ transitionLabels[effect.name].label }}</strong>
                  <small>{{ transitionLabels[effect.name].description }}</small>
                </span>
              </label>
              <label class="transition-percentage-field">
                <span>选中占比</span>
                <span class="transition-percentage-input">
                  <input
                    v-model.number="effect.percentage"
                    type="number"
                    min="1"
                    max="100"
                    step="1"
                    :disabled="!effect.enabled"
                  />
                  <b>%</b>
                </span>
              </label>
            </div>
          </div>
          <div
            class="transition-percentage-summary"
            :class="{ 'is-invalid': enabledTransitionCount > 0 && enabledTransitionPercentage !== 100 }"
          >
            <span>已启用 {{ enabledTransitionCount }} 种效果</span>
            <strong>占比合计 {{ enabledTransitionPercentage }}%</strong>
          </div>
          <div class="notice">
            可以取消全部勾选来关闭纯风景视频转场。启用任意效果时，已启用效果的占比合计必须为 100%。
          </div>
        </div>
      </details>

      <details class="panel settings-disclosure">
        <summary>
          <span class="settings-disclosure-heading"><strong>本地分镜图片生成</strong><small>SDXL 单文件模型</small></span>
          <span class="settings-disclosure-icon" aria-hidden="true">⌄</span>
        </summary>
        <div class="settings-disclosure-content">
          <p class="section-description">用于 ai_generated_images 模式。模型在独立子进程中批量加载，生成完成后释放显存。</p>
          <div class="form-grid">
            <label class="field full-width">
              <span>模型文件</span>
              <input v-model="settings.image_generation_model_path" placeholder="D:\TubeAIFlow\models\image_generation\...\checkpoint.safetensors" />
            </label>
            <label class="field full-width"><span>SDXL 管线配置目录</span><input v-model="settings.image_generation_config_dir" placeholder="D:\TubeAIFlow\models\image_generation\...\diffusers_config" /></label>
            <label class="field full-width">
              <span>Python 可执行文件（可选）</span>
              <input v-model="settings.image_generation_python" placeholder="留空时使用后端 Python；环境需安装 diffusers" />
            </label>
            <label class="field"><span>运行设备</span><input v-model="settings.image_generation_device" placeholder="cuda:0" /></label>
            <label class="field">
              <span>计算精度</span>
              <select v-model="settings.image_generation_dtype"><option value="float16">FP16</option><option value="bfloat16">BF16</option><option value="float32">FP32</option></select>
            </label>
            <label class="field"><span>图片宽度</span><input v-model.number="settings.image_generation_width" type="number" min="512" max="2048" step="64" /></label>
            <label class="field"><span>图片高度</span><input v-model.number="settings.image_generation_height" type="number" min="512" max="2048" step="64" /></label>
            <label class="field"><span>采样步数</span><input v-model.number="settings.image_generation_steps" type="number" min="1" max="100" /></label>
            <label class="field"><span>CFG</span><input v-model.number="settings.image_generation_guidance_scale" type="number" min="0" max="30" step="0.1" /></label>
            <label class="field"><span>每场景候选数</span><input v-model.number="settings.image_generation_candidates_per_scene" type="number" min="1" max="4" /></label>
            <label class="checkbox-field"><input v-model="settings.image_generation_cpu_offload" type="checkbox" /><span><strong>CPU Offload</strong><small>8GB 显存建议开启，降低显存峰值。</small></span></label>
            <label class="field full-width"><span>全局负面提示词</span><textarea v-model="settings.image_generation_negative_prompt" rows="3"></textarea></label>
          </div>
        </div>
      </details>

      <details class="panel settings-disclosure">
        <summary>
          <span class="settings-disclosure-heading"><strong>Qwen3-TTS</strong><small>默认本地声音克隆引擎</small></span>
          <span class="settings-disclosure-icon" aria-hidden="true">⌄</span>
        </summary>
        <div class="settings-disclosure-content">
        <p class="section-description">配置本地 Qwen3-TTS 源码、独立 Python 环境和 Base 声音克隆模型。模型会在每次项目生成任务开始时加载一次。</p>
        <div class="form-grid">
          <label class="field full-width">
            <span>Qwen3-TTS 根目录</span>
            <input v-model="settings.qwen_tts_root" placeholder="例如 D:\Qwen3-TTS" />
            <small>填写包含 <code>qwen_tts</code> 源码目录的项目根目录。</small>
          </label>
          <label class="field full-width">
            <span>Python 可执行文件</span>
            <input v-model="settings.qwen_tts_python" placeholder="默认共用 D:\TubeAIFlow\backend\.venv\Scripts\python.exe" />
            <small>必须使用已经安装 Qwen3-TTS、PyTorch 和 soundfile 的独立 Python 环境。</small>
          </label>
          <label class="field full-width">
            <span>Base 模型目录</span>
            <input v-model="settings.qwen_tts_model_dir" placeholder="例如 D:\Qwen3-TTS\Qwen3-TTS-12Hz-1.7B-Base" />
            <small>声音克隆必须使用 Base 模型；目录中应包含 <code>config.json</code> 和模型权重。</small>
          </label>
          <label class="field">
            <span>运行设备</span>
            <input v-model="settings.qwen_tts_device" placeholder="cuda:0" />
            <small>推荐使用 <code>cuda:0</code>；CPU 推理速度会非常慢。</small>
          </label>
          <label class="field">
            <span>计算精度</span>
            <select v-model="settings.qwen_tts_dtype">
              <option value="bfloat16">BF16（推荐）</option>
              <option value="float16">FP16</option>
              <option value="float32">FP32</option>
            </select>
            <small>RTX 4060 Ti 推荐 BF16；FP32 会显著增加显存占用。</small>
          </label>
          <label class="field">
            <span>合成语言</span>
            <input v-model="settings.qwen_tts_language" placeholder="Chinese" />
            <small>中文项目填写 <code>Chinese</code>，也可以填写 <code>Auto</code> 自动识别。</small>
          </label>
          <label class="field">
            <span>最大生成 Token</span>
            <input v-model.number="settings.qwen_tts_max_new_tokens" type="number" min="128" max="16384" />
            <small>默认 2048，适合当前项目的短文本分段，同时限制显存峰值和异常超长输出。</small>
          </label>
        </div>
        <div class="notice">未填写参考音频逐字稿时会自动使用仅声纹模式；填写准确逐字稿可获得更好的声音克隆效果。</div>
        </div>
      </details>

      <details class="panel settings-disclosure">
        <summary>
          <span class="settings-disclosure-heading"><strong>CosyVoice</strong><small>Zero-shot 本地声音克隆引擎</small></span>
          <span class="settings-disclosure-icon" aria-hidden="true">⌄</span>
        </summary>
        <div class="settings-disclosure-content">
        <p class="section-description">配置 CosyVoice 源码、独立 Python 环境和本地 zero-shot 模型。支持 CosyVoice 1、2 与 Fun-CosyVoice 3 的本地模型目录。</p>
        <div class="form-grid">
          <label class="field full-width">
            <span>CosyVoice 根目录</span>
            <input v-model="settings.cosyvoice_root" placeholder="例如 D:\CosyVoice" />
            <small>应包含 <code>cosyvoice</code> 与 <code>third_party\Matcha-TTS</code>，克隆仓库时需要同时初始化子模块。</small>
          </label>
          <label class="field full-width">
            <span>Python 可执行文件</span>
            <input v-model="settings.cosyvoice_python" placeholder="例如 D:\CosyVoice\.venv\Scripts\python.exe" />
            <small>填写已安装 CosyVoice 依赖、PyTorch 和 torchaudio 的独立 Python 3.10 环境。</small>
          </label>
          <label class="field full-width">
            <span>zero-shot 模型目录</span>
            <input v-model="settings.cosyvoice_model_dir" placeholder="例如 D:\CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B" />
            <small>推荐使用 Fun-CosyVoice3-0.5B；不要选择仅支持预置音色的 SFT 模型。</small>
          </label>
          <label class="checkbox-field">
            <input v-model="settings.cosyvoice_fp16" type="checkbox" />
            <span><strong>使用 FP16</strong><small>使用 CUDA 时可降低显存占用；CPU 环境请取消勾选。</small></span>
          </label>
          <label class="field full-width">
            <span>CosyVoice 3 系统指令</span>
            <input v-model="settings.cosyvoice_instruction" placeholder="You are a helpful assistant." />
            <small>仅对 CosyVoice 3 的 zero-shot 提示生效；系统会自动添加 <code>&lt;|endofprompt|&gt;</code>。</small>
          </label>
        </div>
        <div class="notice">CosyVoice zero-shot 必须填写与参考音频准确对应的逐字稿；请在“参考音频”菜单中统一配置，项目和批量任务只需选择音色。</div>
        </div>
      </details>

      <details class="panel settings-disclosure">
        <summary>
          <span class="settings-disclosure-heading"><strong>DeepSeek</strong><small>系统 AI 能力平台</small></span>
          <span class="settings-disclosure-icon" aria-hidden="true">⌄</span>
        </summary>
        <div class="settings-disclosure-content">
        <p class="section-description">DeepSeek 作为系统通用 AI 能力平台，为后续的分镜生成、内容理解等智能功能提供基础。请先在 DeepSeek 开放平台创建 API Key，再在此配置。</p>
        <div class="form-grid">
          <label class="field full-width">
            <span>DeepSeek API 地址</span>
            <input v-model="settings.deepseek_base_url" placeholder="https://api.deepseek.com" />
            <small>使用官方服务时保持默认值 <code>https://api.deepseek.com</code>。只有使用兼容代理服务时才需要修改。</small>
          </label>
          <label class="field">
            <span>DeepSeek 模型</span>
            <select v-model="settings.deepseek_model">
              <option value="deepseek-v4-flash">DeepSeek V4 Flash（推荐，速度快、成本低）</option>
              <option value="deepseek-v4-pro">DeepSeek V4 Pro（质量优先、成本较高）</option>
            </select>
            <small>一般任务推荐 Flash；更重视复杂推理和表达质量时可选择 Pro。</small>
          </label>
          <label class="field">
            <span>请求超时（秒）</span>
            <input v-model.number="settings.deepseek_timeout_seconds" type="number" min="1" max="600" />
            <small>单次 DeepSeek 请求最多等待多久，默认 60 秒。</small>
          </label>
          <label class="field">
            <span>最大输出 Token</span>
            <input v-model.number="settings.deepseek_max_tokens" type="number" min="1" max="65536" />
            <small>限制单次 DeepSeek 响应长度，通常保持默认值即可。</small>
          </label>
          <label class="field">
            <span>失败重试次数</span>
            <input v-model.number="settings.deepseek_retry_count" type="number" min="0" max="10" />
            <small>DeepSeek 请求失败时自动重试，建议设置为 1～2 次。</small>
          </label>
        </div>
        <div class="secret-row deepseek-key-row">
          <label class="field">
            <span>DeepSeek API Key</span>
            <input v-model="settings.deepseek_api_key" type="password" :placeholder="settings.deepseek_api_key_configured ? '已配置；留空保持不变' : '请输入 API Key'" autocomplete="new-password" />
            <small>密钥只保存在本机数据库中，保存后页面不会再次显示明文。</small>
          </label>
          <span class="status-pill">{{ settings.deepseek_api_key_configured ? '已配置' : '未配置' }}</span>
          <button v-if="settings.deepseek_api_key_configured" class="secondary-button" type="button" @click="clearApiKey('deepseek_api_key', 'DeepSeek')">清除</button>
        </div>
        </div>
      </details>

      <details class="panel settings-disclosure">
        <summary>
          <span class="settings-disclosure-heading"><strong>在线素材平台</strong><small>Pexels 与 Pixabay 素材检索</small></span>
          <span class="settings-disclosure-icon" aria-hidden="true">⌄</span>
        </summary>
        <div class="settings-disclosure-content">
          <p class="section-description">当本地素材库没有合格结果时，系统依次使用已配置的平台搜索在线素材。可以只配置其中一个平台；API Key 保存后不会再次显示明文。</p>
          <div class="secret-row">
            <label class="field">
              <span>Pexels API Key</span>
              <input v-model="settings.pexels_api_key" type="password" :placeholder="settings.pexels_api_key_configured ? '已配置；留空保持不变' : '请输入 API Key'" autocomplete="new-password" />
              <small>
                用于从 Pexels 搜索候选图片和视频，仅在本地素材不足时调用。
                <a href="https://www.pexels.com/api/key/" target="_blank" rel="noopener noreferrer">获取 Pexels API Key</a>
              </small>
            </label>
            <span class="status-pill">{{ providerStatusLabel('pexels') }}</span>
            <button v-if="settings.pexels_api_key_configured" class="secondary-button" type="button" @click="clearApiKey('pexels_api_key', 'Pexels')">清除</button>
          </div>
          <div class="notice">Pexels：{{ providerQuotaText('pexels') }}</div>
          <div class="secret-row">
            <label class="field">
              <span>Pixabay API Key</span>
              <input v-model="settings.pixabay_api_key" type="password" :placeholder="settings.pixabay_api_key_configured ? '已配置；留空保持不变' : '请输入 API Key'" autocomplete="new-password" />
              <small>
                用于从 Pixabay 搜索候选图片和视频，仅在本地素材不足时调用。
                <a href="https://pixabay.com/api/docs/#api_search_images" target="_blank" rel="noopener noreferrer">获取 Pixabay API Key</a>
              </small>
            </label>
            <span class="status-pill">{{ providerStatusLabel('pixabay') }}</span>
            <button v-if="settings.pixabay_api_key_configured" class="secondary-button" type="button" @click="clearApiKey('pixabay_api_key', 'Pixabay')">清除</button>
          </div>
          <div class="notice">Pixabay：{{ providerQuotaText('pixabay') }}</div>
          <div class="form-grid">
            <label class="field">
              <span>查询缓存时长（小时）</span>
              <input v-model.number="settings.media_search_cache_hours" type="number" min="24" max="168" />
              <small>至少缓存 24 小时，避免相同查询重复消耗平台额度。</small>
            </label>
            <label class="field">
              <span>每个平台最多下载候选数</span>
              <input v-model.number="settings.media_search_download_limit" type="number" min="1" max="5" />
              <small>推荐保持 3；先搜索和筛选，再只下载少量候选入库。</small>
            </label>
          </div>
          <div class="notice">检索顺序固定为本地素材 → Pexels → Pixabay。平台返回 429 时会进入冷却并自动尝试下一平台，不会轮换同平台的其他 Key。</div>
          <div class="form-grid provider-storage-grid">
            <label class="field full-width">
              <span>Pexels 素材存储文件夹</span>
              <span class="inline-form">
                <input v-model="settings.pexels_storage_dir" placeholder="留空时使用工作目录下的 assets/downloads/pexels" />
                <span class="provider-storage-actions">
                  <button class="secondary-button" type="button" @click="chooseProviderStorage('pexels')">选择文件夹</button>
                  <button v-if="settings.pexels_storage_dir" class="secondary-button" type="button" @click="settings.pexels_storage_dir = null">恢复默认</button>
                </span>
              </span>
              <small>下载的视频以及生成的缩略图和关键帧都会保存在此文件夹中。</small>
            </label>
            <label class="field full-width">
              <span>Pixabay 素材存储文件夹</span>
              <span class="inline-form">
                <input v-model="settings.pixabay_storage_dir" placeholder="留空时使用工作目录下的 assets/downloads/pixabay" />
                <span class="provider-storage-actions">
                  <button class="secondary-button" type="button" @click="chooseProviderStorage('pixabay')">选择文件夹</button>
                  <button v-if="settings.pixabay_storage_dir" class="secondary-button" type="button" @click="settings.pixabay_storage_dir = null">恢复默认</button>
                </span>
              </span>
              <small>下载的视频以及生成的缩略图和关键帧都会保存在此文件夹中。</small>
            </label>
          </div>
          <div class="form-grid fallback-settings-grid">
            <label class="checkbox-field full-width">
              <input v-model="settings.auto_fallback_enabled" type="checkbox" />
              <span>语义素材无合格结果时，自动从主题兜底素材池填充镜头轨道</span>
            </label>
            <label class="checkbox-field full-width">
              <input v-model="settings.auto_landscape_fallback_enabled" type="checkbox" :disabled="!settings.auto_fallback_enabled" />
              <span>允许自动使用纯风景最终兜底（仍需场景明确允许）</span>
            </label>
            <label class="checkbox-field full-width">
              <input v-model="settings.auto_fallback_review_required" type="checkbox" :disabled="!settings.auto_fallback_enabled" />
              <span>自动兜底后暂停工作流，等待人工复核</span>
            </label>
            <label class="field">
              <span>单条视频兜底素材警戒占比（%）</span>
              <input v-model.number="settings.auto_fallback_max_ratio_percent" type="number" min="0" max="100" :disabled="!settings.auto_fallback_enabled" />
              <small>超过该占比仍会填充，但会强制进入人工复核。</small>
            </label>
            <label class="field">
              <span>单场景连续自动兜底镜头上限</span>
              <input v-model.number="settings.auto_fallback_max_consecutive_shots" type="number" min="1" max="5" :disabled="!settings.auto_fallback_enabled" />
              <small>避免长场景被大量随机兜底镜头连续占满。</small>
            </label>
          </div>
        </div>
      </details>
    </div>
  </section>
</template>
