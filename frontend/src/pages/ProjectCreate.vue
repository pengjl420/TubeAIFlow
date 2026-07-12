<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { createProject } from '../api/projects'

const router = useRouter()
const name = ref('')
const referenceAudio = ref<File | null>(null)
const saving = ref(false)
const error = ref('')

function selectReferenceAudio(event: Event) {
  referenceAudio.value = (event.target as HTMLInputElement).files?.[0] || null
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
  saving.value = true
  error.value = ''
  try {
    const project = await createProject(name.value.trim(), referenceAudio.value)
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
    <div class="panel">
      <label class="field">
        <span>项目名称</span>
        <input v-model="name" placeholder="例如：第一条解说视频" @keyup.enter="submit" />
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
      <p v-if="error" class="error">{{ error }}</p>
      <div class="actions">
        <button class="primary-button" :disabled="saving" @click="submit">
          {{ saving ? '创建中' : '创建项目' }}
        </button>
      </div>
    </div>
  </section>
</template>
