<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Clock3, Film, FolderKanban, Plus, RefreshCw } from 'lucide-vue-next'
import { createProject, listProjects } from '../../api/projects'
import { listVoices, type VoiceProfile } from '../../api/voices'
import { getSystemSettings } from '../../api/settings'
import type { Project } from '../../types/project'
import { usePageFeedback } from '../../services/feedback'

const router = useRouter()
const projects = ref<Project[]>([])
const voices = ref<VoiceProfile[]>([])
const loading = ref(true)
const creating = ref(false)
const error = ref('')
const message = ref('')
const showCreate = ref(false)
const name = ref('')
const outputDir = ref('')
const voiceProfileId = ref('')
usePageFeedback(error, message, { errorTitle: '项目操作失败' })

const selectedVoice = computed(() => voices.value.find(item => item.id === voiceProfileId.value))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [projectData, voiceData, settings] = await Promise.all([
      listProjects(), listVoices(), getSystemSettings(),
    ])
    projects.value = projectData
    voices.value = voiceData
    if (!outputDir.value) outputDir.value = `${settings.workspace_dir}\\projects`
    if (!voiceProfileId.value && voiceData.length) voiceProfileId.value = voiceData[0].id
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加载项目失败'
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!name.value.trim() || !voiceProfileId.value) return
  creating.value = true
  error.value = ''
  try {
    const project = await createProject({
      name: name.value.trim(),
      outputDir: outputDir.value.trim(),
      voiceProfileId: voiceProfileId.value,
      ttsEngine: selectedVoice.value?.tts_engine || 'index_tts',
    })
    message.value = '项目已创建'
    await router.push(`/projects/${project.id}`)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '创建项目失败'
  } finally {
    creating.value = false
  }
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    created: '待导入脚本',
    script_imported: '脚本已导入',
    segmented: '已分段',
    narration_in_progress: '正在生成配音',
    narration_ready: '配音字幕完成',
    video_in_progress: '正在生成视频',
    review_required: '等待审核',
    completed: '已完成',
    failed: '需要处理',
  }
  return labels[status] || status
}

onMounted(load)
</script>

<template>
  <section class="project-page">
    <header class="project-head">
      <div><span>LONG-FORM WORKFLOW</span><h1>项目</h1><p>从脚本开始，持续保存配音、字幕、Scene、时间轴和成片。</p></div>
      <div class="head-actions"><button class="secondary" :disabled="loading" @click="load"><RefreshCw :size="16" />刷新</button><button @click="showCreate = !showCreate"><Plus :size="17" />新建项目</button></div>
    </header>

    <form v-if="showCreate" class="create-panel" @submit.prevent="submit">
      <div><strong>创建长视频项目</strong><span>开发阶段继续使用本地 Web Engine，项目文件保存在你指定的目录。</span></div>
      <label><span>项目名称</span><input v-model="name" required placeholder="例如：2008 金融危机纪录片" /></label>
      <label><span>项目输出目录</span><input v-model="outputDir" required /></label>
      <label><span>默认音色</span><select v-model="voiceProfileId" required><option disabled value="">请选择音色</option><option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.name }} · {{ voice.tts_engine }}</option></select></label>
      <button type="submit" :disabled="creating || !voices.length">{{ creating ? '创建中…' : '创建并进入工作区' }}</button>
      <p v-if="!voices.length">请先在“音色中心”创建一个可用音色。</p>
    </form>

    <div v-if="loading" class="empty">正在读取本地项目…</div>
    <div v-else-if="!projects.length" class="empty large"><FolderKanban :size="42" /><strong>还没有长视频项目</strong><span>创建第一个项目后，脚本和所有生产产物会保持在同一个可恢复工作流中。</span></div>
    <div v-else class="project-grid">
      <button v-for="project in projects" :key="project.id" class="project-card" @click="router.push(`/projects/${project.id}`)">
        <span class="project-icon"><Film :size="21" /></span>
        <div><small>{{ project.id }}</small><h2>{{ project.name }}</h2><p>{{ project.output_dir }}</p></div>
        <span class="status" :class="project.status">{{ statusLabel(project.status) }}</span>
        <footer><span><Clock3 :size="13" />{{ new Date(project.updated_at).toLocaleString() }}</span><b>{{ Math.round(project.audio_duration_seconds || 0) }} 秒音频</b></footer>
      </button>
    </div>
  </section>
</template>

<style scoped>
.project-page{color:#172033}.project-head{align-items:flex-end;display:flex;justify-content:space-between;margin-bottom:20px}.project-head>div:first-child>span{color:#1465f5;font-size:10px;font-weight:800;letter-spacing:.12em}.project-head h1{font-size:28px;margin:4px 0}.project-head p{color:#748096;font-size:12px;margin:0}.head-actions{display:flex;gap:8px}.head-actions button,.create-panel>button{align-items:center;background:#075bf5;border-radius:8px;color:#fff;display:flex;font-size:12px;font-weight:700;gap:6px;min-height:39px;padding:8px 14px}.head-actions .secondary{background:#fff;border:1px solid #dce3ed;color:#536078}.create-panel{align-items:end;background:#fff;border:1px solid #dce4ef;border-radius:12px;display:grid;gap:12px;grid-template-columns:1.3fr 1fr 1.5fr 1.2fr auto;margin-bottom:18px;padding:16px}.create-panel>div{display:grid;gap:4px}.create-panel>div span,.create-panel label span{color:#748096;font-size:10px}.create-panel label{display:grid;gap:5px}.create-panel input,.create-panel select{border:1px solid #dbe3ed;border-radius:7px;font-size:11px;height:38px;padding:0 10px}.create-panel p{color:#d04b56;font-size:10px;grid-column:1/-1;margin:0}.project-grid{display:grid;gap:14px;grid-template-columns:repeat(3,minmax(0,1fr))}.project-card{background:#fff;border:1px solid #e0e6ee;border-radius:12px;color:inherit;display:grid;gap:11px;grid-template-columns:auto 1fr auto;padding:16px;text-align:left;transition:.16s}.project-card:hover{border-color:#8bb2fa;box-shadow:0 8px 26px #315b9b12;transform:translateY(-1px)}.project-icon{align-items:center;background:#eaf2ff;border-radius:9px;color:#075bf5;display:flex;height:40px;justify-content:center;width:40px}.project-card small{color:#9aa4b3;font-size:9px}.project-card h2{font-size:14px;margin:2px 0 5px}.project-card p{color:#7b8798;font-size:10px;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.status{background:#eef2f7;border-radius:999px;color:#657287;font-size:9px;height:max-content;padding:4px 7px}.status.completed,.status.narration_ready{background:#e4f8ef;color:#078d61}.status.failed{background:#fff0f1;color:#c5404b}.status.narration_in_progress,.status.video_in_progress{background:#eaf2ff;color:#075bf5}.project-card footer{align-items:center;border-top:1px solid #edf0f4;color:#8792a3;display:flex;font-size:9px;grid-column:1/-1;justify-content:space-between;padding-top:10px}.project-card footer span{align-items:center;display:flex;gap:4px}.project-card footer b{color:#5c6980}.empty{color:#7b8798;padding:28px;text-align:center}.empty.large{align-items:center;background:#fff;border:1px dashed #cbd5e2;border-radius:12px;display:flex;flex-direction:column;gap:8px;justify-content:center;min-height:280px}.empty.large strong{color:#40506a}@media(max-width:1100px){.project-grid{grid-template-columns:1fr 1fr}.create-panel{grid-template-columns:1fr 1fr}.create-panel>div{grid-column:1/-1}}@media(max-width:700px){.project-head{align-items:flex-start;display:grid;gap:14px}.project-grid,.create-panel{grid-template-columns:1fr}}
</style>
