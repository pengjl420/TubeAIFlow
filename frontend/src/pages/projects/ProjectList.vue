<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Clock3, Film, Folder, FolderKanban, Mic2, Plus, RefreshCw, ShieldCheck, X } from 'lucide-vue-next'
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
const nameInput = ref<HTMLInputElement | null>(null)
const projectDialog = ref<HTMLFormElement | null>(null)
usePageFeedback(error, message, { errorTitle: '项目操作失败' })

const selectedVoice = computed(() => voices.value.find(item => item.id === voiceProfileId.value))
const canCreate = computed(() => Boolean(name.value.trim() && outputDir.value.trim() && voiceProfileId.value && voices.value.length && !creating.value))

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

function closeCreate() {
  if (creating.value) return
  showCreate.value = false
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape' && showCreate.value) closeCreate()
  if (event.key !== 'Tab' || !showCreate.value || !projectDialog.value) return
  const focusable = Array.from(projectDialog.value.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex="-1"])'))
  if (!focusable.length) return
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
}

watch(showCreate, async value => {
  document.body.classList.toggle('has-project-dialog', value)
  if (value) { await nextTick(); nameInput.value?.focus() }
})
onMounted(() => { window.addEventListener('keydown', handleKeydown); void load() })
onBeforeUnmount(() => { window.removeEventListener('keydown', handleKeydown); document.body.classList.remove('has-project-dialog') })
</script>

<template>
  <section class="project-page">
    <header class="project-head taf-sticky-heading">
      <div><h1>项目</h1><p>集中管理长视频工程与最近生产进度。</p></div>
      <div class="head-actions"><button class="secondary" :disabled="loading" @click="load"><RefreshCw :size="16" />刷新</button><button @click="showCreate = true"><Plus :size="17" />新建项目</button></div>
    </header>

    <Teleport to="body">
      <div v-if="showCreate" class="project-dialog-backdrop" @mousedown.self="closeCreate">
        <form ref="projectDialog" class="project-dialog" role="dialog" aria-modal="true" aria-labelledby="create-project-title" @submit.prevent="submit">
          <header><div><span class="dialog-icon"><FolderKanban :size="22" /></span><div><h2 id="create-project-title">创建长视频项目</h2><p>建立可恢复的项目目录，并选择默认旁白音色。</p></div></div><button type="button" aria-label="关闭新建项目" @click="closeCreate"><X :size="19" /></button></header>
          <div class="project-dialog-content">
            <section class="create-step"><span>1</span><div><strong>项目基础信息</strong><small>后续可在项目设置中修改。</small></div></section>
            <label><span>项目名称 <b>*</b></span><input ref="nameInput" v-model="name" required maxlength="100" placeholder="例如：2008 金融危机纪录片" /><small>建议使用频道内唯一、容易搜索的名称。</small></label>
            <label><span>项目输出目录 <b>*</b></span><div class="field-with-icon"><Folder :size="16" /><input v-model="outputDir" required /></div><small>脚本、Scene、音频、素材和渲染结果都保存在此目录。</small></label>
            <section class="create-step"><span>2</span><div><strong>默认生产配置</strong><small>当前先设置旁白音色，其他配置沿用系统默认值。</small></div></section>
            <label><span>默认音色 <b>*</b></span><div class="field-with-icon"><Mic2 :size="16" /><select v-model="voiceProfileId" required><option disabled value="">请选择音色</option><option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.name }} · {{ voice.tts_engine }}</option></select></div><small v-if="selectedVoice">将使用 {{ selectedVoice.tts_engine }} 生成旁白，可在项目内更换。</small></label>
            <p v-if="!voices.length" class="dialog-warning">请先在“音色中心”创建一个可用音色。</p>
            <div class="local-note"><ShieldCheck :size="17" /><span><strong>本地优先</strong> 项目内容默认只保存在本机，不会自动上传完整脚本。</span></div>
          </div>
          <footer><button class="cancel" type="button" :disabled="creating" @click="closeCreate">取消</button><button class="create" type="submit" :disabled="!canCreate">{{ creating ? '创建中…' : '创建并进入工作区' }}</button></footer>
        </form>
      </div>
    </Teleport>

    <div v-if="loading" class="empty">正在读取本地项目…</div>
    <div v-else-if="!projects.length" class="empty large"><FolderKanban :size="42" /><strong>还没有长视频项目</strong><span>创建第一个项目后，脚本和所有生产产物会保持在同一个可恢复工作流中。</span><button type="button" @click="showCreate = true"><Plus :size="16" />创建第一个项目</button></div>
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
.project-page{color:#172033}.project-head{align-items:flex-end;display:flex;justify-content:space-between;margin-bottom:20px}.project-head>div:first-child>span{color:#1465f5;font-size:10px;font-weight:800;letter-spacing:.12em}.project-head h1{font-size:28px;margin:4px 0}.project-head p{color:#748096;font-size:13px;margin:0}.head-actions{display:flex;gap:8px}.head-actions button{align-items:center;background:#075bf5;border-radius:8px;color:#fff;display:flex;font-size:12px;font-weight:700;gap:6px;min-height:40px;padding:8px 14px}.head-actions .secondary{background:#fff;border:1px solid #dce3ed;color:#536078}.project-grid{display:grid;gap:14px;grid-template-columns:repeat(3,minmax(0,1fr))}.project-card{background:#fff;border:1px solid #e0e6ee;border-radius:12px;color:inherit;display:grid;gap:11px;grid-template-columns:auto 1fr auto;padding:16px;text-align:left;transition:.16s}.project-card:hover{border-color:#8bb2fa;box-shadow:0 8px 26px #315b9b12;transform:translateY(-1px)}.project-icon{align-items:center;background:#eaf2ff;border-radius:9px;color:#075bf5;display:flex;height:40px;justify-content:center;width:40px}.project-card small{color:#8a95a7;font-size:11px}.project-card h2{font-size:15px;margin:2px 0 5px}.project-card p{color:#748096;font-size:12px;margin:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.status{background:#eef2f7;border-radius:999px;color:#657287;font-size:11px;height:max-content;padding:4px 7px}.status.completed,.status.narration_ready{background:#e4f8ef;color:#078d61}.status.failed{background:#fff0f1;color:#c5404b}.status.narration_in_progress,.status.video_in_progress{background:#eaf2ff;color:#075bf5}.project-card footer{align-items:center;border-top:1px solid #edf0f4;color:#7c889a;display:flex;font-size:11px;grid-column:1/-1;justify-content:space-between;padding-top:10px}.project-card footer span{align-items:center;display:flex;gap:4px}.project-card footer b{color:#5c6980}.empty{color:#7b8798;padding:28px;text-align:center}.empty.large{align-items:center;background:#fff;border:1px dashed #cbd5e2;border-radius:12px;display:flex;flex-direction:column;gap:8px;justify-content:center;min-height:280px}.empty.large strong{color:#40506a}.empty.large>button{align-items:center;background:#075bf5;border-radius:8px;color:#fff;display:flex;gap:6px;margin-top:8px;padding:8px 14px}@media(max-width:1100px){.project-grid{grid-template-columns:1fr 1fr}}@media(max-width:700px){.project-head{align-items:flex-start;display:grid;gap:14px}.project-grid{grid-template-columns:1fr}}
</style>

<style>
body.has-project-dialog{overflow:hidden}.project-dialog-backdrop{align-items:center;background:rgba(15,23,42,.42);display:flex;inset:0;justify-content:center;padding:22px;position:fixed;z-index:80}.project-dialog{background:#fff;border:1px solid #dfe5ee;border-radius:14px;box-shadow:0 28px 70px rgba(15,32,60,.22);max-height:calc(100vh - 44px);overflow:auto;width:min(620px,100%)}.project-dialog>header{align-items:flex-start;border-bottom:1px solid #e8edf3;display:flex;justify-content:space-between;padding:18px 20px}.project-dialog>header>div{align-items:center;display:flex;gap:12px}.dialog-icon{align-items:center;background:#eaf2ff;border-radius:9px;color:#075bf5;display:flex;height:42px;justify-content:center;width:42px}.project-dialog h2{font-size:19px;margin:0 0 4px}.project-dialog header p{color:#758197;font-size:12px;margin:0}.project-dialog header>button{align-items:center;background:#f4f6f9;border-radius:7px;color:#647086;display:flex;height:36px;justify-content:center;width:36px}.project-dialog-content{display:grid;gap:13px;padding:18px 20px}.project-dialog-content>label{display:grid;gap:6px}.project-dialog-content>label>span{color:#39465a;font-size:12px;font-weight:700}.project-dialog-content b{color:#dc4552}.project-dialog-content input,.project-dialog-content select{background:#fff;border:1px solid #d9e1ec;border-radius:8px;min-height:42px;padding:0 11px;width:100%}.project-dialog-content input:focus,.project-dialog-content select:focus{border-color:#075bf5;box-shadow:0 0 0 3px rgba(7,91,245,.1);outline:0}.project-dialog-content small{color:#7d899c;font-size:11px}.field-with-icon{align-items:center;border:1px solid #d9e1ec;border-radius:8px;color:#7e8a9d;display:flex;padding-left:11px}.field-with-icon:focus-within{border-color:#075bf5;box-shadow:0 0 0 3px rgba(7,91,245,.1)}.field-with-icon input,.field-with-icon select{border:0;box-shadow:none!important}.create-step{align-items:center;border-top:1px solid #edf0f4;display:flex;gap:10px;margin-top:3px;padding-top:14px}.create-step:first-child{border-top:0;margin-top:0;padding-top:0}.create-step>span{align-items:center;background:#075bf5;border-radius:50%;color:#fff;display:flex;font-size:11px;font-weight:800;height:26px;justify-content:center;width:26px}.create-step>div{display:grid}.create-step strong{font-size:13px}.local-note{align-items:flex-start;background:#f2f7ff;border:1px solid #dce9ff;border-radius:8px;color:#4d6690;display:flex;font-size:11px;gap:8px;padding:10px}.local-note svg{flex:none}.dialog-warning{background:#fff3e3;border-radius:7px;color:#a36608;font-size:11px;margin:0;padding:9px}.project-dialog>footer{align-items:center;background:#fafbfc;border-top:1px solid #e5eaf1;display:flex;gap:10px;justify-content:flex-end;padding:12px 20px}.project-dialog>footer button{border-radius:8px;font-size:12px;font-weight:700;min-width:110px;padding:8px 14px}.project-dialog .cancel{background:#fff;border:1px solid #d8e0eb;color:#536078}.project-dialog .create{background:#075bf5;color:#fff;min-width:180px}@media(max-width:600px){.project-dialog-backdrop{align-items:flex-end;padding:0}.project-dialog{border-radius:16px 16px 0 0;max-height:92vh;width:100%}}
</style>
