<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { API_BASE_URL } from '../../api/client'
import {
  createVoice,
  deleteVoice,
  listVoices,
  updateVoice,
  type VoiceProfile,
  type VoiceTtsEngine,
} from '../../api/voices'
import AudioPlayer from '../../components/common/AudioPlayer.vue'
import { confirmAction, showToast } from '../../services/feedback'

const voices = ref<VoiceProfile[]>([])
const editingId = ref('')
const name = ref('')
const ttsEngine = ref<VoiceTtsEngine>('qwen3_tts')
const referenceAudioText = ref('')
const cosyvoiceSpeed = ref(1.0)
const audioFile = ref<File | null>(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const message = ref('')

const editingVoice = computed(() => voices.value.find((item) => item.id === editingId.value) || null)

function engineLabel(engine: VoiceTtsEngine) {
  return { qwen3_tts: 'Qwen3-TTS', chatterbox: 'Chatterbox', cosyvoice: 'CosyVoice' }[engine]
}

function audioUrl(voice: VoiceProfile) {
  return `${API_BASE_URL}/voices/${voice.id}/audio?v=${encodeURIComponent(voice.updated_at)}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    voices.value = await listVoices()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '音色列表加载失败'
  } finally {
    loading.value = false
  }
}

function selectAudio(event: Event) {
  audioFile.value = (event.target as HTMLInputElement).files?.[0] || null
}

function edit(voice: VoiceProfile) {
  editingId.value = voice.id
  name.value = voice.name
  ttsEngine.value = voice.tts_engine
  referenceAudioText.value = voice.reference_audio_text
  cosyvoiceSpeed.value = voice.cosyvoice_speed
  audioFile.value = null
  error.value = ''
  message.value = ''
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function resetForm() {
  editingId.value = ''
  name.value = ''
  ttsEngine.value = 'qwen3_tts'
  referenceAudioText.value = ''
  cosyvoiceSpeed.value = 1.0
  audioFile.value = null
}

async function save() {
  if (!name.value.trim()) {
    error.value = '请输入音色名称'
    return
  }
  if (!editingId.value && !audioFile.value) {
    error.value = '请选择参考音频文件'
    return
  }
  if (ttsEngine.value === 'cosyvoice' && !referenceAudioText.value.trim()) {
    error.value = 'CosyVoice 需要填写参考音频逐字稿'
    return
  }
  if (
    ttsEngine.value === 'cosyvoice'
    && (!Number.isFinite(cosyvoiceSpeed.value) || cosyvoiceSpeed.value < 0.5 || cosyvoiceSpeed.value > 2)
  ) {
    error.value = 'CosyVoice 语速必须在 0.5 到 2.0 之间'
    return
  }
  saving.value = true
  error.value = ''
  message.value = ''
  try {
    const input = {
      name: name.value.trim(),
      tts_engine: ttsEngine.value,
      reference_audio_text: referenceAudioText.value.trim(),
      cosyvoice_speed: cosyvoiceSpeed.value,
      file: audioFile.value,
    }
    if (editingId.value) await updateVoice(editingId.value, input)
    else await createVoice(input)
    message.value = editingId.value ? '音色配置已更新' : '音色配置已创建'
    resetForm()
    await load()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '音色保存失败'
  } finally {
    saving.value = false
  }
}

async function remove(voice: VoiceProfile) {
  const confirmed = await confirmAction({
    eyebrow: '删除参考音色',
    title: `删除音色“${voice.name}”？`,
    description: '删除后，新项目和批量任务将无法再选择这份参考音色。',
    detail: '已经生成的配音与项目输出不会受到影响。',
    confirmText: '删除音色',
    tone: 'danger',
  })
  if (!confirmed) return
  error.value = ''
  message.value = ''
  try {
    await deleteVoice(voice.id)
    if (editingId.value === voice.id) resetForm()
    message.value = '音色已删除'
    await load()
    showToast({ title: '参考音色已删除', description: `“${voice.name}”已从音色库移除。`, tone: 'success' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '音色删除失败'
    showToast({ title: '音色删除失败', description: error.value, tone: 'danger' })
  }
}

onMounted(load)
</script>

<template>
  <section>
    <div class="page-title">
      <div>
        <span class="page-kicker">VOICE LIBRARY</span>
        <h1>参考音频</h1>
        <p class="muted">统一维护声音克隆参考，项目和批量任务只需选择这里配置好的音色。</p>
      </div>
      <button v-if="editingId" class="secondary-button" type="button" @click="resetForm">取消编辑</button>
    </div>

    <div class="grid voice-settings-grid">
      <div class="panel">
        <div class="section-head"><h2>{{ editingId ? '编辑音色' : '新增音色' }}</h2></div>
        <label class="field reference-field">
          <span>音色名称</span>
          <input v-model="name" maxlength="120" placeholder="例如：纪录片男声" />
        </label>
        <label class="field reference-field">
          <span>TTS 引擎</span>
          <select v-model="ttsEngine">
            <option value="qwen3_tts">Qwen3-TTS（默认）</option>
            <option value="chatterbox">Chatterbox</option>
            <option value="cosyvoice">CosyVoice</option>
          </select>
        </label>
        <label class="field reference-field">
          <span>{{ editingId ? '更换参考音频（可选）' : '参考音频' }}</span>
          <input type="file" accept="audio/wav,audio/mpeg,audio/flac,audio/mp4,.wav,.mp3,.flac,.m4a" @change="selectAudio" />
          <small>{{ audioFile ? `已选择：${audioFile.name}` : editingVoice ? `当前文件：${editingVoice.original_filename}` : '支持 WAV、MP3、FLAC、M4A，最大 100 MB' }}</small>
        </label>
        <label v-if="ttsEngine === 'qwen3_tts' || ttsEngine === 'cosyvoice'" class="field reference-field">
          <span>参考音频逐字稿（{{ ttsEngine === 'cosyvoice' ? '必填' : '推荐' }}）</span>
          <textarea v-model="referenceAudioText" rows="5" placeholder="填写参考音频中实际说出的文字"></textarea>
        </label>
        <label v-if="ttsEngine === 'cosyvoice'" class="field reference-field">
          <span>语速</span>
          <input v-model.number="cosyvoiceSpeed" type="number" min="0.5" max="2" step="0.05" />
          <small>默认 1.0；该语速仅随当前音色生效。</small>
        </label>
        <div class="actions">
          <button class="primary-button" type="button" :disabled="saving" @click="save">
            {{ saving ? '保存中…' : editingId ? '保存修改' : '创建音色' }}
          </button>
        </div>
      </div>

      <div class="panel">
        <div class="section-head"><h2>已配置音色</h2><span class="muted">{{ voices.length }} 个</span></div>
        <p v-if="loading" class="muted">正在加载…</p>
        <div v-else-if="voices.length" class="voice-profile-list">
          <article v-for="voice in voices" :key="voice.id" class="voice-profile-row">
            <div>
              <strong>{{ voice.name }}</strong>
              <p class="muted">
                {{ engineLabel(voice.tts_engine) }} · {{ voice.original_filename }}<template v-if="voice.tts_engine === 'cosyvoice'"> · 语速 {{ voice.cosyvoice_speed }}</template>
              </p>
              <AudioPlayer :src="audioUrl(voice)" />
            </div>
            <div class="actions">
              <button class="mini-button" type="button" @click="edit(voice)">编辑</button>
              <button class="mini-button danger-button" type="button" @click="remove(voice)">删除</button>
            </div>
          </article>
        </div>
        <div v-else class="empty-state">
          <strong>还没有系统音色</strong>
          <p class="muted">先在左侧上传一份参考音频，之后创建项目时即可直接选择。</p>
        </div>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="message" class="success">{{ message }}</p>
  </section>
</template>
