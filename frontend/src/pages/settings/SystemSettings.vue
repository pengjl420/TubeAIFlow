<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { rememberApiAddress } from '../../api/client'
import {
  clearSystemSecret,
  getFfmpegStatus,
  getMediaProviderStatuses,
  getSystemSettings,
  installFfmpeg,
  saveSystemSettings,
  type FfmpegStatus,
  type MediaProviderStatus,
  type SystemSettings,
} from '../../api/settings'

const settings = ref<SystemSettings | null>(null)
const loading = ref(false)
const saving = ref(false)
const installingFfmpeg = ref(false)
const ffmpegStatus = ref<FfmpegStatus | null>(null)
const mediaProviderStatuses = ref<MediaProviderStatus[]>([])
const error = ref('')
const message = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [loadedSettings, loadedFfmpegStatus, loadedProviderStatuses] = await Promise.all([
      getSystemSettings(),
      getFfmpegStatus(),
      getMediaProviderStatuses(),
    ])
    settings.value = loadedSettings
    ffmpegStatus.value = loadedFfmpegStatus
    mediaProviderStatuses.value = loadedProviderStatuses
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
            <input v-model="settings.qwen_tts_python" placeholder="例如 D:\Qwen3-TTS\.venv\Scripts\python.exe" />
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
          <span class="settings-disclosure-heading"><strong>Chatterbox</strong><small>多语言本地配音引擎</small></span>
          <span class="settings-disclosure-icon" aria-hidden="true">⌄</span>
        </summary>
        <div class="settings-disclosure-content">
        <p class="section-description">配置 Chatterbox Multilingual 本地环境。中文配音默认使用 V3 模型，参考音频只用于声音条件，不要求填写逐字稿。</p>
        <div class="form-grid">
          <label class="field full-width">
            <span>Chatterbox 源码目录（可选）</span>
            <input v-model="settings.chatterbox_root" placeholder="例如 D:\chatterbox" />
            <small>使用源码安装时填写项目根目录；如果 Python 环境已经通过 pip 安装 <code>chatterbox-tts</code>，可以留空。</small>
          </label>
          <label class="field full-width">
            <span>Python 可执行文件</span>
            <input v-model="settings.chatterbox_python" placeholder="例如 D:\chatterbox\.venv\Scripts\python.exe" />
            <small>填写已安装 Chatterbox、PyTorch 和 torchaudio 的独立 Python 3.11 环境。</small>
          </label>
          <label class="field full-width">
            <span>本地模型目录</span>
            <input v-model="settings.chatterbox_model_dir" placeholder="例如 D:\models\chatterbox" />
            <small>使用完整的 Multilingual 模型快照，避免生成任务运行时联网下载模型。</small>
          </label>
          <label class="field">
            <span>运行设备</span>
            <input v-model="settings.chatterbox_device" placeholder="cuda" />
            <small>可填写 <code>cuda</code>、<code>cpu</code> 或 <code>mps</code>。</small>
          </label>
          <label class="field">
            <span>模型版本</span>
            <select v-model="settings.chatterbox_t3_model">
              <option value="v3">Multilingual V3（推荐）</option>
              <option value="v2">Multilingual V2</option>
            </select>
          </label>
          <label class="field">
            <span>语言代码</span>
            <input v-model="settings.chatterbox_language" placeholder="zh" />
            <small>中文使用 <code>zh</code>；每次生成只能指定一种语言。</small>
          </label>
          <label class="field">
            <span>表达强度</span>
            <input v-model.number="settings.chatterbox_exaggeration" type="number" min="0" max="2" step="0.1" />
            <small>默认 0.5；数值越高通常越有表现力，也可能加快语速。</small>
          </label>
          <label class="field">
            <span>CFG 权重</span>
            <input v-model.number="settings.chatterbox_cfg_weight" type="number" min="0" max="1" step="0.1" />
            <small>默认 0.5；参考说话人语速较快时可尝试 0.3。</small>
          </label>
          <label class="field">
            <span>采样温度</span>
            <input v-model.number="settings.chatterbox_temperature" type="number" min="0.1" max="5" step="0.1" />
            <small>默认 0.8；提高会增加变化，同时降低稳定性。</small>
          </label>
        </div>
        <div class="notice">Chatterbox 生成的音频包含模型内置的不可感知水印。参考音频语言应与这里的语言代码一致，以减少口音迁移。</div>
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
          <label class="field">
            <span>语速</span>
            <input v-model.number="settings.cosyvoice_speed" type="number" min="0.5" max="2" step="0.05" />
            <small>默认 1.0；所有分段使用相同语速。</small>
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
        </div>
      </details>
    </div>
  </section>
</template>
