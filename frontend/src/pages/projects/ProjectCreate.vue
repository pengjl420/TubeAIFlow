<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import { createProject, selectDirectory } from '../../api/projects'
import { listVoices, type VoiceProfile } from '../../api/voices'
import { usePageFeedback } from '../../services/feedback'
import type { SegmentationMode, StoryboardMode, VideoGenerationMode } from '../../types/project'

const router = useRouter()
const name = ref('')
const voices = ref<VoiceProfile[]>([])
const voiceProfileId = ref('')
const outputDir = ref('D:\\video_darft')
const outputFilename = ref('')
const mediaVideoDir = ref('')
const videoMode = ref<VideoGenerationMode>('ai_generated_images')
const storyboardTransitionEnabled = ref(true)
const segmentationMode = ref<SegmentationMode>('newline')
const storyboardMode = ref<StoryboardMode>('ai')
const saving = ref(false)
const selectingFolder = ref<'output' | 'video' | null>(null)
const error = ref('')
usePageFeedback(error, undefined, { errorTitle: '还不能创建项目' })
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
  if (['landscape', 'ai_landscape_mix'].includes(videoMode.value) && !mediaVideoDir.value.trim()) {
    error.value = '当前视频模式必须选择风景素材文件夹'
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
      media_video_dir: ['landscape', 'ai_landscape_mix'].includes(videoMode.value) ? mediaVideoDir.value.trim() : '',
      include_video: videoMode.value !== 'none',
      video_mode: videoMode.value,
      storyboard_transition_enabled: storyboardTransitionEnabled.value,
      segmentation_mode: segmentationMode.value,
      storyboard_mode: storyboardMode.value,
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
      <RouterLink class="secondary-button" to="/projects">取消并返回</RouterLink>
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
          <span>逐字稿切段方式</span>
          <select v-model="segmentationMode">
            <option value="newline">按换行切段（默认，本地处理）</option>
            <option value="ai">AI 自动切段（DeepSeek 全文理解）</option>
          </select>
          <span class="muted">AI 模式会提交完整逐字稿，只选择切分边界，不改写原文，并同步生成视觉描述。</span>
        </label>
        <label class="field reference-field">
          <span>视频生成方式</span>
          <select v-model="videoMode">
            <option value="none">不生成视频（仅生成完整配音）</option>
            <option value="landscape">纯风景素材拼接</option>
            <option value="ai_generated_images">本地 AI 分镜图片视频</option>
            <option value="ai_landscape_mix">本地 AI 分镜 + 风景素材混合视频</option>
          </select>
          <span class="muted">选择后，一键生成会自动完成配音、素材匹配与最终 MP4 合成。</span>
        </label>
        <label v-if="videoMode === 'landscape' || videoMode === 'ai_landscape_mix'" class="field reference-field">
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
        <label v-if="videoMode === 'ai_generated_images' || videoMode === 'ai_landscape_mix'" class="field reference-field">
          <span>分镜头视觉场景切分</span>
          <select v-model="storyboardMode">
            <option value="segments">按逐字稿切段生成分镜头（默认）</option>
            <option value="ai">AI 自动生成分镜头（全文理解）</option>
          </select>
          <span class="muted">按切段模式严格沿用最终切段结果；上方切段方式变化时，分镜边界也会随之变化。</span>
        </label>
        <label class="checkbox-field">
          <input v-model="storyboardTransitionEnabled" type="checkbox" :disabled="videoMode === 'none'" />
          <span>
            <strong>启用分镜头转场</strong>
            <small>默认开启；合并 MP4 时在部分分镜边界插入系统设置中的一个转场特效，可手动关闭。</small>
          </span>
        </label>
      </div>
    </div>
    <div class="actions form-footer">
      <span class="muted">创建后进入项目即可粘贴逐字稿并开始一键生成。</span>
      <button class="primary-button" :disabled="saving || selectingFolder !== null" @click="submit">
        {{ saving ? '正在创建…' : '创建并进入工作台 →' }}
      </button>
    </div>
  </section>
</template>
