<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { API_BASE_URL } from '../api/client'
import {
  getProject,
  saveProjectSettings,
  selectDirectory,
  type TtsEngine,
  uploadReferenceAudio,
} from '../api/projects'
import AudioPlayer from '../components/AudioPlayer.vue'
import type { Project } from '../types/project'

const route = useRoute()
const router = useRouter()
const projectId = String(route.params.id)
const project = ref<Project | null>(null)
const projectName = ref('')
const referenceAudio = ref<File | null>(null)
const outputDir = ref('')
const outputFilename = ref('')
const mediaVideoDir = ref('')
const includeTranslation = ref(false)
const includeVideo = ref(false)
const ttsEngine = ref<TtsEngine>('index_tts')
const referenceAudioText = ref('')
const loading = ref(false)
const saving = ref(false)
const selectingFolder = ref<'output' | 'video' | null>(null)
const error = ref('')
const message = ref('')

const projectConfig = computed(() => {
  if (!project.value?.config_json) return {}
  try {
    const data = JSON.parse(project.value.config_json)
    return data && typeof data === 'object' ? data : {}
  } catch {
    return {}
  }
})

const referenceAudioName = computed(() => {
  const filename = projectConfig.value.reference_audio_filename
  return typeof filename === 'string' ? filename : ''
})

const referenceAudioUrl = computed(() => {
  if (!project.value?.reference_audio_path) return ''
  return `${API_BASE_URL}/projects/${projectId}/reference-audio?v=${encodeURIComponent(project.value.updated_at)}`
})

function fillForm() {
  if (!project.value) return
  projectName.value = project.value.name
  outputDir.value = project.value.output_dir || ''
  const filename = projectConfig.value.output_filename
  const videoDir = projectConfig.value.media_video_dir
  const configuredTtsEngine = projectConfig.value.tts_engine
  const configuredReferenceText = projectConfig.value.reference_audio_text
  includeTranslation.value = projectConfig.value.include_translation === true
  includeVideo.value = projectConfig.value.include_video === true
  outputFilename.value = typeof filename === 'string' ? filename : ''
  mediaVideoDir.value = typeof videoDir === 'string' ? videoDir : ''
  ttsEngine.value = configuredTtsEngine === 'qwen3_tts' ? 'qwen3_tts' : 'index_tts'
  referenceAudioText.value = typeof configuredReferenceText === 'string' ? configuredReferenceText : ''
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    project.value = await getProject(projectId)
    fillForm()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '项目设置加载失败'
  } finally {
    loading.value = false
  }
}

function selectReferenceAudio(event: Event) {
  referenceAudio.value = (event.target as HTMLInputElement).files?.[0] || null
}

async function chooseFolder(target: 'output' | 'video') {
  selectingFolder.value = target
  error.value = ''
  try {
    const current = target === 'output' ? outputDir.value : mediaVideoDir.value
    const title = target === 'output' ? '选择输出文件夹' : '选择素材视频文件夹'
    const selected = await selectDirectory(current, title)
    if (selected && target === 'output') outputDir.value = selected
    if (selected && target === 'video') mediaVideoDir.value = selected
  } catch (err) {
    error.value = err instanceof Error ? err.message : '系统文件夹选择窗口打开失败'
  } finally {
    selectingFolder.value = null
  }
}

async function save() {
  if (!projectName.value.trim()) {
    error.value = '请输入项目名称'
    return
  }
  if (!outputDir.value.trim()) {
    error.value = '请选择输出文件夹'
    return
  }
  if (includeVideo.value && !mediaVideoDir.value.trim()) {
    error.value = '勾选生成视频后，必须选择原始素材文件夹'
    return
  }

  saving.value = true
  error.value = ''
  message.value = ''
  try {
    project.value = await saveProjectSettings(projectId, {
      name: projectName.value.trim(),
      output_dir: outputDir.value.trim(),
      output_filename: outputFilename.value.trim(),
      media_video_dir: mediaVideoDir.value.trim(),
      include_translation: includeTranslation.value,
      include_video: includeVideo.value,
      tts_engine: ttsEngine.value,
      reference_audio_text: referenceAudioText.value.trim(),
    })
    if (referenceAudio.value) {
      project.value = await uploadReferenceAudio(projectId, referenceAudio.value)
      referenceAudio.value = null
    }
    fillForm()
    message.value = '项目设置已保存'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '项目设置保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section v-if="project">
    <div class="page-title">
      <h1>项目设置</h1>
      <div class="page-title-actions">
        <button class="secondary-button" @click="router.push(`/projects/${project.id}`)">返回项目</button>
        <button class="primary-button" type="button" :disabled="saving || selectingFolder !== null" @click="save">
          {{ saving ? '保存中…' : '保存项目设置' }}
        </button>
      </div>
    </div>

    <div class="grid">
      <div class="panel">
        <div class="section-head"><h2>基本信息</h2></div>
        <label class="field reference-field">
          <span>项目名称</span>
          <input v-model="projectName" maxlength="120" placeholder="请输入项目名称" />
        </label>
      </div>

      <div class="panel">
        <div class="section-head"><h2>输出设置</h2></div>
        <label class="field reference-field">
          <span>输出根目录</span>
          <div class="inline-form">
            <input v-model="outputDir" readonly placeholder="请选择输出文件夹" />
            <button
              class="secondary-button"
              type="button"
              :disabled="selectingFolder !== null"
              @click="chooseFolder('output')"
            >
              {{ selectingFolder === 'output' ? '等待选择…' : '选择文件夹' }}
            </button>
          </div>
          <span class="muted">点击后将打开系统文件夹选择窗口。</span>
        </label>
        <label class="field reference-field">
          <span>默认输出文件名</span>
          <input v-model="outputFilename" placeholder="留空则使用当前时间戳" />
          <span class="muted">中间文件写入同名子文件夹，完整音频输出到根目录下的同名 WAV。</span>
        </label>
      </div>

      <div class="panel">
        <div class="section-head"><h2>一键生成选项</h2></div>
        <label class="checkbox-field">
          <input v-model="includeTranslation" type="checkbox" />
          <span>翻译字幕<small>根据当前逐字稿语种自动选择目标语种；中文逐字稿翻译为英文。</small></span>
        </label>
        <label class="checkbox-field">
          <input v-model="includeVideo" type="checkbox" />
          <span>生成视频<small>开启后，一键生成会在字幕完成后合并视频。</small></span>
        </label>
        <label v-if="includeVideo" class="field reference-field">
          <span>原始素材文件夹</span>
          <div class="inline-form">
            <input v-model="mediaVideoDir" readonly placeholder="请选择原始素材文件夹" />
            <button
              class="secondary-button"
              type="button"
              :disabled="selectingFolder !== null"
              @click="chooseFolder('video')"
            >
              {{ selectingFolder === 'video' ? '等待选择…' : '选择文件夹' }}
            </button>
          </div>
          <span class="muted">生成最终视频时会扫描该目录中的视频素材。</span>
        </label>
      </div>

      <div class="panel">
        <div class="section-head"><h2>参考音频</h2></div>
        <label class="field reference-field">
          <span>TTS 引擎</span>
          <select v-model="ttsEngine">
            <option value="index_tts">Index-TTS</option>
            <option value="qwen3_tts">Qwen3-TTS</option>
          </select>
          <span class="muted">切换引擎后，现有分段会标记为待重新生成。</span>
        </label>
        <div class="reference-box">
          <div>
            <strong>当前参考音频</strong>
            <p class="muted">
              {{ project.reference_audio_path ? referenceAudioName || '参考音频' : '未配置参考音频' }}
            </p>
          </div>
          <AudioPlayer v-if="referenceAudioUrl" :src="referenceAudioUrl" />
        </div>

        <label class="field reference-field">
          <span>更换参考音频</span>
          <input
            type="file"
            accept="audio/wav,audio/mpeg,audio/flac,audio/mp4,.wav,.mp3,.flac,.m4a"
            @change="selectReferenceAudio"
          />
          <span class="muted">
            {{ referenceAudio ? `已选择：${referenceAudio.name}` : '不更换可留空；支持 WAV、MP3、FLAC、M4A' }}
          </span>
        </label>
        <label v-if="ttsEngine === 'qwen3_tts'" class="field reference-field">
          <span>参考音频逐字稿（推荐）</span>
          <textarea v-model="referenceAudioText" rows="4" placeholder="填写当前参考音频中实际说出的文字"></textarea>
          <span class="muted">留空时 Qwen3-TTS 使用仅声纹模式；填写准确文字可以提高克隆质量。</span>
        </label>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="message" class="success">{{ message }}</p>

  </section>

  <section v-else class="panel">
    <p class="muted">{{ loading ? '加载中' : error }}</p>
  </section>
</template>
