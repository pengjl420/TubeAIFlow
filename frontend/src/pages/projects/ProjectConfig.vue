<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import {
  getProject,
  saveProjectSettings,
  selectDirectory,
} from '../../api/projects'
import { API_BASE_URL } from '../../api/client'
import { listVoices, type VoiceProfile } from '../../api/voices'
import AudioPlayer from '../../components/common/AudioPlayer.vue'
import type { Project, SegmentationMode, SemanticReviewMode, StoryboardMode, VideoGenerationMode, VideoOutputFormat } from '../../types/project'

const route = useRoute()
const router = useRouter()
const projectId = String(route.params.id)
const project = ref<Project | null>(null)
const projectName = ref('')
const voices = ref<VoiceProfile[]>([])
const voiceProfileId = ref('')
const outputDir = ref('')
const outputFilename = ref('')
const mediaVideoDir = ref('')
const videoMode = ref<VideoGenerationMode>('none')
const semanticReviewMode = ref<SemanticReviewMode>('manual')
const videoOutputFormat = ref<VideoOutputFormat>('fcpxml')
const storyboardTransitionEnabled = ref(true)
const segmentationMode = ref<SegmentationMode>('newline')
const storyboardMode = ref<StoryboardMode>('ai')
const loading = ref(false)
const saving = ref(false)
const selectingFolder = ref<'output' | 'video' | null>(null)
const error = ref('')
const message = ref('')

const projectConfig = computed(() => {
  if (project.value?.config) return project.value.config
  if (!project.value?.config_json) return {}
  try {
    const data = JSON.parse(project.value.config_json)
    return data && typeof data === 'object' ? data : {}
  } catch {
    return {}
  }
})

const selectedVoice = computed(() => voices.value.find((item) => item.id === voiceProfileId.value) || null)

const referenceAudioUrl = computed(() => {
  if (!selectedVoice.value) return ''
  return `${API_BASE_URL}/voices/${selectedVoice.value.id}/audio?v=${encodeURIComponent(selectedVoice.value.updated_at)}`
})

function fillForm() {
  if (!project.value) return
  projectName.value = project.value.name
  outputDir.value = project.value.output_dir || ''
  const filename = projectConfig.value.output_filename
  const videoDir = projectConfig.value.media_video_dir
  const configuredMode = projectConfig.value.video_mode
  videoMode.value = configuredMode === 'ai_semantic' || configuredMode === 'ai_generated_images' || configuredMode === 'landscape' || configuredMode === 'none'
    ? configuredMode
    : projectConfig.value.include_video === true ? 'landscape' : 'none'
  semanticReviewMode.value = projectConfig.value.semantic_review_mode === 'automatic'
    ? 'automatic'
    : 'manual'
  videoOutputFormat.value = projectConfig.value.video_output_format === 'fcpxml' ? 'fcpxml' : 'mp4'
  storyboardTransitionEnabled.value = projectConfig.value.storyboard_transition_enabled !== false
  segmentationMode.value = projectConfig.value.segmentation_mode === 'ai' ? 'ai' : 'newline'
  storyboardMode.value = projectConfig.value.storyboard_mode === 'segments' ? 'segments' : 'ai'
  outputFilename.value = typeof filename === 'string' ? filename : ''
  mediaVideoDir.value = typeof videoDir === 'string' ? videoDir : ''
  voiceProfileId.value = typeof projectConfig.value.voice_profile_id === 'string'
    ? projectConfig.value.voice_profile_id
    : ''
}

watch(videoMode, (value) => {
  if (value === 'none') videoOutputFormat.value = 'fcpxml'
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [loadedProject, loadedVoices] = await Promise.all([getProject(projectId), listVoices()])
    project.value = loadedProject
    voices.value = loadedVoices
    fillForm()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '项目设置加载失败'
  } finally {
    loading.value = false
  }
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
  if (!voiceProfileId.value) {
    error.value = '请选择系统音色'
    return
  }
  if (videoMode.value === 'landscape' && !mediaVideoDir.value.trim()) {
    error.value = '纯风景素材拼接必须选择原始素材文件夹'
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
      media_video_dir: videoMode.value === 'landscape' ? mediaVideoDir.value.trim() : '',
      include_video: videoMode.value !== 'none',
      video_mode: videoMode.value,
      semantic_review_mode: semanticReviewMode.value,
      video_output_format: videoOutputFormat.value,
      voice_profile_id: voiceProfileId.value,
      storyboard_transition_enabled: storyboardTransitionEnabled.value,
      segmentation_mode: segmentationMode.value,
      storyboard_mode: storyboardMode.value,
    })
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
      <div>
        <span class="page-kicker">PROJECT SETTINGS</span>
        <h1>项目设置</h1>
        <p class="muted">管理项目输出、生成选项与声音克隆参考。</p>
      </div>
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
        <label class="field reference-field">
          <span>逐字稿切段方式</span>
          <select v-model="segmentationMode">
            <option value="newline">按换行切段（默认，本地处理）</option>
            <option value="ai">AI 自动切段（DeepSeek 全文理解）</option>
          </select>
          <span class="muted">修改后会使现有切段失效；下次生成将按新方式重新切段。</span>
        </label>
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
        <div class="field reference-field">
          <span>最终交付格式</span>
          <div class="output-format-options" role="radiogroup" aria-label="最终交付格式">
            <label class="output-format-option" :class="{ 'is-selected': videoOutputFormat === 'fcpxml' }">
              <input v-model="videoOutputFormat" type="radio" value="fcpxml" />
              <span><strong>FCPXML 可编辑工程</strong><small>可导入桌面版剪映继续深度剪辑</small></span>
            </label>
            <label class="output-format-option" :class="{ 'is-selected': videoOutputFormat === 'mp4' }">
              <input v-model="videoOutputFormat" type="radio" value="mp4" />
              <span><strong>{{ videoMode === 'none' ? '仅配音与原文 SRT' : '视频文件（MP4）' }}</strong><small>{{ videoMode === 'none' ? '不额外生成 FCPXML 时间线' : '直接渲染可播放的最终视频文件' }}</small></span>
            </label>
          </div>
          <span class="muted">{{ videoMode === 'none' ? 'FCPXML 将创建仅包含完整配音和字幕标题轨的时间线，方便导入剪映后继续铺设画面。' : 'FCPXML 模式跳过视频渲染，输出可继续深度剪辑的时间线工程，并保留 SRT 字幕兜底。' }}</span>
        </div>
        <label v-if="videoMode === 'ai_semantic' || videoMode === 'ai_generated_images'" class="field reference-field">
          <span>分镜头视觉场景切分</span>
          <select v-model="storyboardMode">
            <option value="ai">AI 自动生成分镜头（默认，全文理解）</option>
            <option value="segments">按逐字稿切段生成分镜头</option>
          </select>
          <span class="muted">按切段模式消费最终逐字稿切段；AI 自动模式独立读取全文决定视觉场景边界。</span>
        </label>
        <label v-if="videoMode === 'ai_semantic' || videoMode === 'ai_generated_images'" class="field reference-field">
          <span>素材审核方式</span>
          <select v-model="semanticReviewMode">
            <option value="manual">人工审核拼接</option>
            <option value="automatic">自动审核拼接</option>
          </select>
          <span class="muted">自动模式只会按匹配度选用合格候选，并禁止同一分镜重复使用相同素材内容。</span>
        </label>
        <label class="checkbox-field">
          <input v-model="storyboardTransitionEnabled" type="checkbox" :disabled="videoMode === 'none'" />
          <span>
            <strong>启用分镜头转场</strong>
            <small>合并 MP4 时在部分分镜边界插入系统设置中的一个转场特效。</small>
          </span>
        </label>
      </div>

      <div class="panel">
        <div class="section-head"><h2>参考音频</h2><RouterLink to="/voices">管理系统音色</RouterLink></div>
        <label class="field reference-field">
          <span>系统音色</span>
          <select v-model="voiceProfileId">
            <option value="">请选择已配置的参考音频</option>
            <option v-for="voice in voices" :key="voice.id" :value="voice.id">
              {{ voice.name }} · {{ voice.tts_engine }}
            </option>
          </select>
          <span class="muted">切换音色后，现有分段会标记为待重新生成。</span>
        </label>
        <div v-if="selectedVoice" class="reference-box">
          <div>
            <strong>当前参考音频</strong>
            <p class="muted">{{ selectedVoice.name }} · {{ selectedVoice.original_filename }}</p>
          </div>
          <AudioPlayer v-if="referenceAudioUrl" :src="referenceAudioUrl" />
        </div>
        <p v-else class="notice">当前项目尚未选择系统音色，请从上方列表选择。</p>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="message" class="success">{{ message }}</p>

  </section>

  <section v-else class="panel">
    <p class="muted">{{ loading ? '加载中' : error }}</p>
  </section>
</template>
