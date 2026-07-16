<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { rememberApiAddress } from '../../api/client'
import {
  clearSystemSecret,
  getSystemSettings,
  saveSystemSettings,
  type SystemSettings,
} from '../../api/settings'

const settings = ref<SystemSettings | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const message = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    settings.value = await getSystemSettings()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '系统设置加载失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!settings.value) return
  saving.value = true
  error.value = ''
  message.value = ''
  try {
    settings.value = await saveSystemSettings(settings.value)
    rememberApiAddress(settings.value.app_host, settings.value.app_port)
    message.value = '系统设置已保存。监听地址或端口变更需要重启应用后生效。'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '系统设置保存失败'
  } finally {
    saving.value = false
  }
}

async function clearDeepSeekKey() {
  error.value = ''
  message.value = ''
  try {
    settings.value = await clearSystemSecret('deepseek_api_key')
    message.value = 'DeepSeek API Key 已清除'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '密钥清除失败'
  }
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-title">
      <div>
        <h1>系统设置</h1>
        <p class="muted">配置保存在本机 SQLite 数据库中，不会读取 .env 文件。</p>
      </div>
    </div>

    <p v-if="loading" class="muted">正在加载…</p>
    <div v-else-if="settings" class="grid settings-grid">
      <div class="panel">
        <div class="section-head"><h2>基础设置</h2></div>
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
        <div class="notice">系统设置数据库固定保存在 <code>backend/workspace/app.db</code>，不会随着“工作目录”一起移动。</div>
      </div>

      <div class="panel">
        <div class="section-head"><h2>IndexTTS</h2></div>
        <p class="section-description">这里填写已安装好的 IndexTTS 环境位置。三个路径必须真实存在，系统会使用指定的 Python 运行项目内的批量生成脚本。</p>
        <div class="form-grid">
          <label class="field full-width">
            <span>IndexTTS 根目录</span>
            <input v-model="settings.index_tts_root" placeholder="例如 D:\IndexTTS" />
            <small>填写 IndexTTS 项目的顶层文件夹，即包含 IndexTTS 源码、配置或运行文件的目录。运行 TTS 时会把它作为工作目录。</small>
          </label>
          <label class="field full-width">
            <span>Python 可执行文件</span>
            <input v-model="settings.index_tts_python" placeholder="例如 D:\IndexTTS\.venv\Scripts\python.exe" />
            <small>填写已经安装 IndexTTS 依赖的 Python，不要填写 TubeAIFlow 自己的 Python。Windows 虚拟环境通常位于 <code>.venv\Scripts\python.exe</code>。</small>
          </label>
          <label class="field full-width">
            <span>模型目录</span>
            <input v-model="settings.index_tts_model_dir" placeholder="例如 D:\IndexTTS\checkpoints" />
            <small>填写下载好的 IndexTTS 模型文件夹。该目录必须包含 <code>config.yaml</code>，并同时放有模型运行所需的权重文件。</small>
          </label>
          <label class="checkbox-field">
            <input v-model="settings.index_tts_fp16" type="checkbox" />
            <span><strong>使用 FP16</strong><small>显卡支持半精度时建议勾选，可降低显存占用并加快生成；遇到兼容性或音频异常时取消勾选。</small></span>
          </label>
        </div>
      </div>

      <div class="panel">
        <div class="section-head"><h2>Qwen3-TTS</h2></div>
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

      <div class="panel">
        <div class="section-head"><h2>DeepSeek 翻译服务</h2></div>
        <p class="section-description">英文字幕翻译仅使用 DeepSeek。先在 DeepSeek 开放平台创建 API Key，再在此配置。</p>
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
            <small>字幕批量翻译推荐 Flash；更重视复杂语境和表达质量时可选择 Pro。</small>
          </label>
          <label class="field">
            <span>请求超时（秒）</span>
            <input v-model.number="settings.translation_timeout_seconds" type="number" min="1" max="600" />
            <small>单次请求最多等待多久，默认 60 秒。网络较慢或批量较大时可适当增加。</small>
          </label>
          <label class="field">
            <span>每批字幕数量</span>
            <input v-model.number="settings.translation_batch_size" type="number" min="1" max="200" />
            <small>每次发送的字幕条数，默认 30。过大会增加超时和返回格式错误概率。</small>
          </label>
          <label class="field">
            <span>最大输出 Token</span>
            <input v-model.number="settings.translation_max_tokens" type="number" min="1" max="65536" />
            <small>限制单次翻译响应长度，通常保持默认值即可；字幕很多且返回被截断时再提高。</small>
          </label>
          <label class="field">
            <span>失败重试次数</span>
            <input v-model.number="settings.translation_retry_count" type="number" min="0" max="10" />
            <small>请求失败或返回内容不完整时自动重试，建议设置为 1～2 次。</small>
          </label>
        </div>
        <div class="secret-row deepseek-key-row">
          <label class="field">
            <span>DeepSeek API Key</span>
            <input v-model="settings.deepseek_api_key" type="password" :placeholder="settings.deepseek_api_key_configured ? '已配置；留空保持不变' : '请输入 API Key'" autocomplete="new-password" />
            <small>密钥只保存在本机数据库中，保存后页面不会再次显示明文。</small>
          </label>
          <span class="status-pill">{{ settings.deepseek_api_key_configured ? '已配置' : '未配置' }}</span>
          <button v-if="settings.deepseek_api_key_configured" class="secondary-button" type="button" @click="clearDeepSeekKey">清除</button>
        </div>
      </div>

      <div class="actions">
        <button class="primary-button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存系统设置' }}</button>
      </div>
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="message" class="success">{{ message }}</p>
  </section>
</template>
