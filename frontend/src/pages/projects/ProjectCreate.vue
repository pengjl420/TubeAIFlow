<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { createProject, selectDirectory, type TtsEngine } from '../../api/projects'

const router = useRouter()
const name = ref('')
const referenceAudio = ref<File | null>(null)
const ttsEngine = ref<TtsEngine>('index_tts')
const referenceAudioText = ref('')
const outputDir = ref('D:\\video_darft')
const outputFilename = ref('')
const mediaVideoDir = ref('')
const includeTranslation = ref(false)
const includeVideo = ref(false)
const saving = ref(false)
const selectingFolder = ref<'output' | 'video' | null>(null)
const error = ref('')
let outputFilenameEdited = false

watch(name, (value) => {
  if (!outputFilenameEdited) outputFilename.value = value.trim()
})

function markOutputFilenameEdited() {
  outputFilenameEdited = true
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

async function submit() {
  if (!name.value.trim()) {
    error.value = '请输入项目名称'
    return
  }
  if (!referenceAudio.value) {
    error.value = '请选择参考音频文件'
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
  try {
    const project = await createProject({
      name: name.value.trim(),
      reference_audio: referenceAudio.value,
      output_dir: outputDir.value.trim(),
      output_filename: outputFilename.value.trim(),
      media_video_dir: mediaVideoDir.value.trim(),
      include_translation: includeTranslation.value,
      include_video: includeVideo.value,
      tts_engine: ttsEngine.value,
      reference_audio_text: referenceAudioText.value.trim(),
    })
    router.push(`/projects/${project.id}`)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '项目创建失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section>
    <div class="page-title">
      <h1>新建项目</h1>
    </div>
    <div class="grid">
      <div class="panel">
        <div class="section-head"><h2>基本信息</h2></div>
        <label class="field">
          <span>项目名称</span>
          <input v-model="name" placeholder="例如：第一条解说视频" @keyup.enter="submit" />
        </label>
        <label class="field">
          <span>TTS 引擎</span>
          <select v-model="ttsEngine">
            <option value="index_tts">Index-TTS</option>
            <option value="qwen3_tts">Qwen3-TTS</option>
          </select>
        </label>
        <label class="field reference-field">
          <span>参考音频</span>
          <input
            type="file"
            accept="audio/wav,audio/mpeg,audio/flac,audio/mp4,.wav,.mp3,.flac,.m4a"
            @change="selectReferenceAudio"
          />
          <span class="muted">
            {{ referenceAudio ? `已选择：${referenceAudio.name}` : '创建项目时必须配置参考音频' }}
          </span>
        </label>
        <label v-if="ttsEngine === 'qwen3_tts'" class="field reference-field">
          <span>参考音频逐字稿（推荐）</span>
          <textarea v-model="referenceAudioText" rows="4" placeholder="填写参考音频中实际说出的文字"></textarea>
          <span class="muted">留空时使用仅声纹模式，克隆质量可能降低。</span>
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
          <span class="muted">默认保存到 D:\video_darft，也可以选择其他文件夹。</span>
        </label>
        <label class="field reference-field">
          <span>默认输出文件名</span>
          <input v-model="outputFilename" placeholder="默认使用项目名称" @input="markOutputFilenameEdited" />
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
    </div>
    <p v-if="error" class="error">{{ error }}</p>
    <div class="actions">
      <button class="primary-button" :disabled="saving || selectingFolder !== null" @click="submit">
        {{ saving ? '创建中' : '创建项目' }}
      </button>
    </div>
  </section>
</template>
