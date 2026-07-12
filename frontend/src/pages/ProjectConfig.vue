<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { API_BASE_URL } from '../api/client'
import {
  getProject,
  listDirectories,
  saveOutputSettings,
  uploadReferenceAudio,
  type DirectoryList,
} from '../api/projects'
import { saveVideoSettings } from '../api/videos'
import AudioPlayer from '../components/AudioPlayer.vue'
import type { Project } from '../types/project'

const route = useRoute()
const router = useRouter()
const projectId = String(route.params.id)
const project = ref<Project | null>(null)
const referenceAudio = ref<File | null>(null)
const outputDir = ref('')
const outputFilename = ref('')
const mediaVideoDir = ref('')
const loading = ref(false)
const savingAudio = ref(false)
const savingOutput = ref(false)
const savingVideo = ref(false)
const pickerOpen = ref(false)
const pickerLoading = ref(false)
const pickerTarget = ref<'output' | 'video'>('output')
const directoryList = ref<DirectoryList | null>(null)
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

function fillOutputForm() {
  if (!project.value) return
  outputDir.value = project.value.output_dir || ''
  const filename = projectConfig.value.output_filename
  const videoDir = projectConfig.value.media_video_dir
  outputFilename.value = typeof filename === 'string' ? filename : ''
  mediaVideoDir.value = typeof videoDir === 'string' ? videoDir : ''
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    project.value = await getProject(projectId)
    fillOutputForm()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '项目配置加载失败'
  } finally {
    loading.value = false
  }
}

function selectReferenceAudio(event: Event) {
  referenceAudio.value = (event.target as HTMLInputElement).files?.[0] || null
}

async function saveReferenceAudio() {
  if (!referenceAudio.value) {
    error.value = '请选择参考音频文件'
    return
  }
  savingAudio.value = true
  error.value = ''
  message.value = ''
  try {
    project.value = await uploadReferenceAudio(projectId, referenceAudio.value)
    referenceAudio.value = null
    message.value = '参考音频已保存'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '参考音频保存失败'
  } finally {
    savingAudio.value = false
  }
}

async function saveOutputConfig() {
  if (!outputDir.value.trim()) {
    error.value = '请选择输出目录'
    return
  }
  savingOutput.value = true
  error.value = ''
  message.value = ''
  const wasBlank = !outputFilename.value.trim()
  try {
    project.value = await saveOutputSettings(projectId, outputDir.value.trim(), outputFilename.value.trim())
    fillOutputForm()
    message.value = wasBlank ? '已使用当前时间戳作为文件名' : '输出配置已保存'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '输出配置保存失败'
  } finally {
    savingOutput.value = false
  }
}

async function saveVideoConfig() {
  if (!mediaVideoDir.value.trim()) {
    error.value = '请选择素材视频目录'
    return
  }
  savingVideo.value = true
  error.value = ''
  message.value = ''
  try {
    project.value = await saveVideoSettings(projectId, mediaVideoDir.value.trim())
    fillOutputForm()
    message.value = '视频素材目录已保存'
  } catch (err) {
    error.value = err instanceof Error ? err.message : '视频素材目录保存失败'
  } finally {
    savingVideo.value = false
  }
}

async function openFolderPicker(target: 'output' | 'video' = 'output') {
  pickerTarget.value = target
  pickerOpen.value = true
  const current = target === 'video' ? mediaVideoDir.value : outputDir.value
  await browseDirectory(current || undefined)
}

async function browseDirectory(path?: string | null) {
  pickerLoading.value = true
  error.value = ''
  try {
    directoryList.value = await listDirectories(path || undefined)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '目录读取失败'
  } finally {
    pickerLoading.value = false
  }
}

function chooseCurrentDirectory() {
  if (directoryList.value) {
    if (pickerTarget.value === 'video') {
      mediaVideoDir.value = directoryList.value.current
    } else {
      outputDir.value = directoryList.value.current
    }
  }
  pickerOpen.value = false
}

onMounted(load)
</script>

<template>
  <section v-if="project">
    <div class="page-title">
      <h1>项目配置</h1>
      <button class="secondary-button" @click="router.push(`/projects/${project.id}`)">返回项目</button>
    </div>

    <div class="grid">
      <div class="panel">
        <div class="section-head">
          <h2>输出设置</h2>
        </div>
        <label class="field reference-field">
          <span>输出根目录</span>
          <div class="inline-form">
            <input v-model="outputDir" readonly placeholder="请选择输出文件夹" />
            <button class="secondary-button" type="button" @click="openFolderPicker('output')">选择文件夹</button>
          </div>
          <span class="muted">每次生成会按文件名创建子文件夹，例如 D:\测试\4-0715。</span>
        </label>
        <label class="field reference-field">
          <span>默认输出文件名</span>
          <input v-model="outputFilename" placeholder="留空则使用当前时间戳" />
          <span class="muted">中间文件写入同名子文件夹，完整音频输出到根目录下的同名 WAV。</span>
        </label>
        <div class="actions">
          <button class="primary-button" :disabled="savingOutput" @click="saveOutputConfig">
            {{ savingOutput ? '保存中' : '保存输出配置' }}
          </button>
        </div>
      </div>

      <div class="panel">
        <div class="section-head">
          <h2>视频素材</h2>
        </div>
        <label class="field reference-field">
          <span>素材视频目录</span>
          <div class="inline-form">
            <input v-model="mediaVideoDir" readonly placeholder="请选择素材视频文件夹" />
            <button class="secondary-button" type="button" @click="openFolderPicker('video')">选择文件夹</button>
          </div>
          <span class="muted">生成最终视频时会扫描该目录，按标题归类后每类随机选取一个素材。</span>
        </label>
        <div class="actions">
          <button class="primary-button" :disabled="savingVideo" @click="saveVideoConfig">
            {{ savingVideo ? '保存中' : '保存视频素材配置' }}
          </button>
        </div>
      </div>

      <div class="panel">
        <div class="section-head">
          <h2>参考音频</h2>
        </div>
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
            {{ referenceAudio ? `已选择：${referenceAudio.name}` : '支持 WAV、MP3、FLAC、M4A' }}
          </span>
        </label>

        <div class="actions">
          <button class="primary-button" :disabled="savingAudio" @click="saveReferenceAudio">
            {{ savingAudio ? '保存中' : '保存参考音频' }}
          </button>
        </div>
      </div>
    </div>

    <p v-if="error" class="error">{{ error }}</p>
    <p v-if="message" class="success">{{ message }}</p>

    <div v-if="pickerOpen" class="modal-backdrop">
      <div class="modal-panel">
        <div class="section-head">
          <h2>{{ pickerTarget === 'video' ? '选择素材视频文件夹' : '选择输出文件夹' }}</h2>
          <button class="secondary-button" type="button" @click="pickerOpen = false">关闭</button>
        </div>

        <div class="folder-current">
          <span class="muted">当前目录</span>
          <strong>{{ directoryList?.current || '加载中' }}</strong>
        </div>

        <div class="folder-roots">
          <button
            v-for="root in directoryList?.roots || []"
            :key="root"
            class="secondary-button"
            type="button"
            @click="browseDirectory(root)"
          >
            {{ root }}
          </button>
        </div>

        <div class="folder-list">
          <button
            v-if="directoryList?.parent"
            class="folder-row"
            type="button"
            @click="browseDirectory(directoryList.parent)"
          >
            ..
          </button>
          <button
            v-for="directory in directoryList?.directories || []"
            :key="directory.path"
            class="folder-row"
            type="button"
            @click="browseDirectory(directory.path)"
          >
            {{ directory.name }}
          </button>
          <p v-if="!pickerLoading && directoryList && !directoryList.directories.length" class="muted">
            当前目录没有可进入的子文件夹。
          </p>
        </div>

        <div class="actions">
          <button class="primary-button" type="button" :disabled="!directoryList" @click="chooseCurrentDirectory">
            使用当前文件夹
          </button>
          <button class="secondary-button" type="button" @click="pickerOpen = false">取消</button>
        </div>
      </div>
    </div>
  </section>

  <section v-else class="panel">
    <p class="muted">{{ loading ? '加载中' : error }}</p>
  </section>
</template>
