<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { createBatch } from '../../api/batches'
import { selectDirectory } from '../../api/projects'
import type { TtsEngine } from '../../api/projects'

const router = useRouter()
const name = ref(`批量生成 ${new Date().toLocaleDateString()}`)
const scripts = ref<File[]>([])
const referenceAudio = ref<File | null>(null)
const ttsEngine = ref<TtsEngine>('qwen3_tts')
const referenceAudioText = ref('')
const outputDir = ref('')
const mediaVideoDir = ref('')
const includeVideo = ref(true)
const continueOnError = ref(true)
const saving = ref(false)
const selectingFolder = ref<'output' | 'video' | null>(null)
const error = ref('')

function selectScripts(event: Event) {
  scripts.value = Array.from((event.target as HTMLInputElement).files || [])
}

function selectReferenceAudio(event: Event) {
  referenceAudio.value = (event.target as HTMLInputElement).files?.[0] || null
}

function moveScript(index: number, offset: number) {
  const target = index + offset
  if (target < 0 || target >= scripts.value.length) return
  const next = [...scripts.value]
  const [file] = next.splice(index, 1)
  next.splice(target, 0, file)
  scripts.value = next
}

function removeScript(index: number) {
  scripts.value = scripts.value.filter((_, itemIndex) => itemIndex !== index)
}

async function chooseFolder(target: 'output' | 'video') {
  selectingFolder.value = target
  error.value = ''
  try {
    const current = target === 'output' ? outputDir.value : mediaVideoDir.value
    const title = target === 'output' ? '选择批量输出文件夹' : '选择素材视频文件夹'
    const selected = await selectDirectory(current, title)
    if (selected && target === 'output') outputDir.value = selected
    if (selected && target === 'video') mediaVideoDir.value = selected
  } catch (err) {
    error.value = err instanceof Error ? err.message : '文件夹选择失败'
  } finally {
    selectingFolder.value = null
  }
}

async function submit() {
  if (!scripts.value.length) {
    error.value = '请至少选择一份逐字稿'
    return
  }
  if (!referenceAudio.value) {
    error.value = '请选择参考音频'
    return
  }
  if (!outputDir.value.trim()) {
    error.value = '请选择输出目录'
    return
  }
  if (includeVideo.value && !mediaVideoDir.value.trim()) {
    error.value = '生成视频时必须选择素材视频目录'
    return
  }

  saving.value = true
  error.value = ''
  try {
    const batch = await createBatch({
      name: name.value.trim() || '批量生成',
      scripts: scripts.value,
      referenceAudio: referenceAudio.value,
      outputDir: outputDir.value.trim(),
      mediaVideoDir: mediaVideoDir.value.trim(),
      includeVideo: includeVideo.value,
      continueOnError: continueOnError.value,
      ttsEngine: ttsEngine.value,
      referenceAudioText: referenceAudioText.value.trim(),
    })
    router.push(`/batches/${batch.id}`)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '批次创建失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section>
    <div class="page-title create-page-title">
      <div>
        <span class="page-kicker">NEW BATCH</span>
        <h1>新建批量任务</h1>
        <p class="muted">逐字稿将按照下方顺序创建项目，并共享同一份参考音频与输出配置。</p>
      </div>
      <RouterLink class="secondary-button" to="/batches">取消并返回</RouterLink>
    </div>
    <div class="grid batch-create-grid">
      <div class="panel grid">
        <label class="field">
          <span>批次名称</span>
          <input v-model="name" maxlength="120" />
        </label>

        <label class="field">
          <span>逐字稿文件</span>
          <input type="file" accept=".txt,.md,text/plain,text/markdown" multiple @change="selectScripts" />
          <small>支持 TXT、Markdown，单文件不超过 5 MB，最多 100 个文件。</small>
        </label>

        <div v-if="scripts.length" class="upload-file-list">
          <div v-for="(file, index) in scripts" :key="`${file.name}-${file.lastModified}-${index}`" class="upload-file-row">
            <span class="file-order">{{ index + 1 }}</span>
            <span class="file-name">{{ file.name }}</span>
            <button class="mini-button" type="button" :disabled="index === 0" @click="moveScript(index, -1)">上移</button>
            <button class="mini-button" type="button" :disabled="index === scripts.length - 1" @click="moveScript(index, 1)">下移</button>
            <button class="mini-button danger-button" type="button" @click="removeScript(index)">移除</button>
          </div>
        </div>

        <label class="field">
          <span>TTS 引擎</span>
          <select v-model="ttsEngine">
            <option value="index_tts">Index-TTS</option>
            <option value="qwen3_tts">Qwen3-TTS</option>
          </select>
          <small>本批次中的所有项目都会使用该引擎。</small>
        </label>

        <label class="field">
          <span>公共参考音频</span>
          <input type="file" accept="audio/wav,audio/mpeg,audio/flac,audio/mp4,.wav,.mp3,.flac,.m4a" @change="selectReferenceAudio" />
          <small>{{ referenceAudio ? `已选择：${referenceAudio.name}` : '该音色会用于本批次内的所有逐字稿。' }}</small>
        </label>
        <label v-if="ttsEngine === 'qwen3_tts'" class="field">
          <span>参考音频逐字稿（推荐）</span>
          <textarea v-model="referenceAudioText" rows="4" placeholder="填写公共参考音频中实际说出的文字"></textarea>
          <small>留空时使用仅声纹模式，克隆质量可能降低。</small>
        </label>
      </div>

      <div class="panel grid">
        <label class="field">
          <span>输出根目录</span>
          <div class="inline-form compact-inline-form">
            <input v-model="outputDir" readonly placeholder="请选择输出文件夹" />
            <button class="secondary-button" type="button" :disabled="selectingFolder !== null" @click="chooseFolder('output')">选择</button>
          </div>
        </label>

        <label class="checkbox-field">
          <input v-model="includeVideo" type="checkbox" />
          <span>生成最终视频<small>关闭后只生成配音和中英文字幕。</small></span>
        </label>

        <label v-if="includeVideo" class="field">
          <span>素材视频目录</span>
          <div class="inline-form compact-inline-form">
            <input v-model="mediaVideoDir" readonly placeholder="请选择素材视频文件夹" />
            <button class="secondary-button" type="button" :disabled="selectingFolder !== null" @click="chooseFolder('video')">选择</button>
          </div>
        </label>

        <label class="checkbox-field">
          <input v-model="continueOnError" type="checkbox" />
          <span>单个文件失败后继续<small>失败文件会保留错误信息，可稍后单独重试。</small></span>
        </label>

        <p v-if="error" class="error">{{ error }}</p>
        <div class="actions">
          <button class="primary-button" type="button" :disabled="saving || selectingFolder !== null" @click="submit">
            {{ saving ? '正在创建项目…' : `创建并开始（${scripts.length} 个文件）` }}
          </button>
          <RouterLink class="secondary-button" to="/batches">取消</RouterLink>
        </div>
      </div>
    </div>
  </section>
</template>
