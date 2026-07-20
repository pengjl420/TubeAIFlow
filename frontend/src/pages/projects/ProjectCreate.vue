<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { createProject, selectDirectory } from '../../api/projects'
import { listVoices, type VoiceProfile } from '../../api/voices'
import type { SemanticReviewMode, VideoGenerationMode } from '../../types/project'

const router = useRouter()
const name = ref('')
const voices = ref<VoiceProfile[]>([])
const voiceProfileId = ref('')
const outputDir = ref('D:\\video_darft')
const outputFilename = ref('')
const mediaVideoDir = ref('')
const videoMode = ref<VideoGenerationMode>('none')
const semanticReviewMode = ref<SemanticReviewMode>('manual')
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
  if (!voiceProfileId.value) {
    error.value = '请选择系统音色；如尚未配置，请先前往参考音频菜单新增'
    return
  }
  if (!outputDir.value.trim()) {
    error.value = '请选择输出文件夹'
    return
  }
  if (videoMode.value === 'landscape' && !mediaVideoDir.value.trim()) {
    error.value = '纯风景素材拼接必须选择原始素材文件夹'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const project = await createProject({
      name: name.value.trim(),
      voice_profile_id: voiceProfileId.value,
      output_dir: outputDir.value.trim(),
      output_filename: outputFilename.value.trim(),
      media_video_dir: videoMode.value === 'landscape' ? mediaVideoDir.value.trim() : '',
      include_video: videoMode.value !== 'none',
      video_mode: videoMode.value,
      semantic_review_mode: semanticReviewMode.value,
    })
    router.push(`/projects/${project.id}`)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '项目创建失败'
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    voices.value = await listVoices()
    if (voices.value.length === 1) voiceProfileId.value = voices.value[0].id
  } catch (err) {
    error.value = err instanceof Error ? err.message : '系统音色加载失败'
  }
})
</script>

<template>
  <section>
    <div class="page-title create-page-title">
      <div>
        <span class="page-kicker">NEW PRODUCTION</span>
        <h1>创建视频项目</h1>
        <p class="muted">先准备声音和输出位置，创建后再进入工作台添加逐字稿。</p>
      </div>
      <RouterLink class="secondary-button" to="/">取消并返回</RouterLink>
    </div>
    <div class="setup-steps" aria-label="项目创建步骤">
      <span class="is-active"><i>1</i>项目信息</span>
      <span><i>2</i>输出设置</span>
      <span><i>3</i>生成选项</span>
    </div>
    <div class="grid create-form-grid">
      <div class="panel form-section-card">
        <div class="section-head"><h2>基本信息</h2></div>
        <label class="field">
          <span>项目名称</span>
          <input v-model="name" placeholder="例如：第一条解说视频" @keyup.enter="submit" />
        </label>
        <label class="field reference-field">
          <span>系统音色</span>
          <select v-model="voiceProfileId">
            <option value="">请选择已配置的参考音频</option>
            <option v-for="voice in voices" :key="voice.id" :value="voice.id">
              {{ voice.name }} · {{ voice.tts_engine }}
            </option>
          </select>
          <span class="muted">
            项目直接使用系统音色库，不再单独上传文件。
            <RouterLink to="/voices">管理参考音频</RouterLink>
          </span>
        </label>
      </div>

      <div class="panel form-section-card">
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

      <div class="panel form-section-card">
        <div class="section-head"><h2>一键生成选项</h2></div>
        <label class="field reference-field">
          <span>视频生成方式</span>
          <select v-model="videoMode">
            <option value="none">不生成视频（仅配音与原文 SRT）</option>
            <option value="landscape">纯风景素材拼接</option>
            <option value="ai_semantic">AI 语义视频拼接</option>
            <option value="ai_generated_images">本地 AI 分镜图片视频</option>
          </select>
          <span class="muted">三种方式共用切段、TTS、音频合并和 SRT 生成，只在字幕完成后分流。</span>
        </label>
        <label v-if="videoMode === 'landscape'" class="field reference-field">
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
        <label v-if="videoMode === 'ai_semantic' || videoMode === 'ai_generated_images'" class="field reference-field">
          <span>素材审核方式</span>
          <select v-model="semanticReviewMode">
            <option value="manual">人工审核拼接</option>
            <option value="automatic">自动审核拼接</option>
          </select>
          <span class="muted">人工模式保持现有逐分镜确认流程；自动模式按匹配度从高到低选用合格且不重复的素材。</span>
        </label>
      </div>
    </div>
    <div v-if="error" class="alert alert-danger"><strong>还不能创建项目</strong><span>{{ error }}</span></div>
    <div class="actions form-footer">
      <span class="muted">创建后仍可在项目设置中修改这些选项。</span>
      <button class="primary-button" :disabled="saving || selectingFolder !== null" @click="submit">
        {{ saving ? '正在创建…' : '创建并进入工作台 →' }}
      </button>
    </div>
  </section>
</template>
