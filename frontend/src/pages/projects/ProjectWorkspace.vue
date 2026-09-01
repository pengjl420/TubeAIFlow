<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { CheckCircle2, CircleStop, FileAudio, FileText, Loader2, Play, RefreshCw, Video } from 'lucide-vue-next'
import { cancelProjectTask, getProject, getProjectOutputs, getProjectScript, getProjectTask, projectOutputUrl, saveProjectScript, startProjectWorkflow, type ProjectOutputs, type ProjectTask } from '../../api/projects'
import type { Project } from '../../types/project'
import { usePageFeedback } from '../../services/feedback'

const route = useRoute()
const projectId = computed(() => String(route.params.projectId))
const project = ref<Project | null>(null)
const task = ref<ProjectTask | null>(null)
const outputs = ref<ProjectOutputs | null>(null)
const script = ref('')
const loading = ref(true)
const saving = ref(false)
const operating = ref(false)
const error = ref('')
const message = ref('')
let timer: number | undefined
usePageFeedback(error, message, { errorTitle: '项目工作流错误' })

const active = computed(() => Boolean(task.value?.running || task.value?.queued))
const stages = [
  ['script', '脚本'], ['tts', '配音'], ['subtitles', '字幕'], ['storyboard', '分镜'],
  ['image_generation', '视觉'], ['visual_track', '时间轴'], ['quality_check', '质量'], ['completed', '导出'],
]

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [projectData, taskData, outputData, scriptData] = await Promise.all([
      getProject(projectId.value), getProjectTask(projectId.value), getProjectOutputs(projectId.value), getProjectScript(projectId.value),
    ])
    project.value = projectData
    task.value = taskData
    outputs.value = outputData
    if (!script.value) script.value = scriptData.text
  } catch (reason) {
    if (!silent) error.value = reason instanceof Error ? reason.message : '加载项目失败'
  } finally {
    if (!silent) loading.value = false
  }
}

async function saveScript() {
  if (!script.value.trim()) return
  saving.value = true
  try {
    project.value = await saveProjectScript(projectId.value, script.value)
    message.value = '脚本已保存，工作流可以开始运行'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '保存脚本失败'
  } finally { saving.value = false }
}

async function runWorkflow() {
  operating.value = true
  try {
    task.value = await startProjectWorkflow(projectId.value)
    message.value = '工作流已加入本地任务队列'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '启动工作流失败'
  } finally { operating.value = false }
}

async function cancelWorkflow() {
  operating.value = true
  try { await cancelProjectTask(projectId.value); await load(true) }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '取消任务失败' }
  finally { operating.value = false }
}

function stageReached(stage: string) {
  if (task.value?.status === 'completed') return true
  const current = stages.findIndex(item => item[0] === task.value?.stage)
  return current >= stages.findIndex(item => item[0] === stage)
}

onMounted(async () => { await load(); timer = window.setInterval(() => void load(true), 3000) })
onBeforeUnmount(() => { if (timer !== undefined) window.clearInterval(timer) })
</script>

<template>
  <section v-if="project" class="workspace-page">
    <header><div><RouterLink to="/projects">项目</RouterLink><span>/</span><strong>{{ project.name }}</strong><p>{{ project.output_dir }}</p></div><div class="actions"><button class="secondary" @click="load()"><RefreshCw :size="15" />刷新</button><button v-if="active" class="danger" :disabled="operating" @click="cancelWorkflow"><CircleStop :size="16" />停止</button><button v-else :disabled="operating || !project.script_clean_path" @click="runWorkflow"><Play :size="16" />运行工作流</button></div></header>

    <nav class="stage-bar"><div v-for="([id, label], index) in stages" :key="id" :class="{ reached: stageReached(id), current: task?.stage === id }"><span><CheckCircle2 v-if="stageReached(id)" :size="14" /><b v-else>{{ index + 1 }}</b></span><small>{{ label }}</small></div></nav>

    <div class="workspace-grid">
      <aside><h2>Scene / 输入</h2><div class="scene-empty"><FileText :size="28" /><strong>脚本工作区</strong><span>完成字幕与语义规划后，这里将显示可单独重做和锁定的 Scene。</span></div></aside>
      <main><div class="panel-head"><div><h1>脚本</h1><p>导入完整逐字稿。TTS 分段与字幕切分会保持解耦。</p></div><button :disabled="saving || !script.trim() || active" @click="saveScript">{{ saving ? '保存中…' : '保存脚本' }}</button></div><textarea v-model="script" :disabled="active" placeholder="在此粘贴 20～60 分钟长视频逐字稿…" /><div class="privacy">默认仅在本机处理。当前项目不会自动上传完整脚本到第三方服务。</div></main>
      <aside class="inspector"><h2>项目状态</h2><dl><dt>生命周期</dt><dd>{{ project.status }}</dd><dt>任务状态</dt><dd>{{ task?.status || 'idle' }}</dd><dt>当前阶段</dt><dd>{{ task?.stage || '尚未开始' }}</dd><dt>排队位置</dt><dd>{{ task?.queue_position || '—' }}</dd></dl><p v-if="task?.error_message" class="task-error">{{ task.error_message }}</p><h2>产物</h2><div class="artifacts"><a v-for="file in outputs?.files.slice(0, 8)" :key="file.path" :href="projectOutputUrl(projectId, file.path)" target="_blank"><FileAudio v-if="file.name.endsWith('.wav')" :size="14" /><Video v-else-if="file.name.endsWith('.mp4')" :size="14" /><FileText v-else :size="14" />{{ file.relative_path }}</a><span v-if="!outputs?.files.length">暂无输出文件</span></div></aside>
    </div>
    <footer class="job-strip"><Loader2 v-if="active" class="spin" :size="16" /><CheckCircle2 v-else :size="16" /><strong>{{ active ? `正在执行：${task?.stage}` : '本地 Engine 已就绪' }}</strong><span>所有耗时步骤通过持久化任务运行，关闭页面不会中断任务。</span></footer>
  </section>
  <div v-else class="workspace-loading">{{ loading ? '正在加载项目…' : '项目不存在' }}</div>
</template>

<style scoped>
.workspace-page{color:#172033}.workspace-page>header{align-items:center;display:flex;justify-content:space-between;margin-bottom:14px}.workspace-page header>div:first-child{align-items:center;display:flex;flex-wrap:wrap;font-size:12px;gap:7px}.workspace-page header a{color:#075bf5}.workspace-page header p{color:#8a95a7;flex-basis:100%;font-size:9px;margin:1px 0}.actions{display:flex;gap:7px}.actions button,.panel-head button{align-items:center;background:#075bf5;border-radius:7px;color:#fff;display:flex;font-size:11px;font-weight:700;gap:5px;min-height:36px;padding:7px 12px}.actions .secondary{background:#fff;border:1px solid #dae2ed;color:#536078}.actions .danger{background:#d94956}.stage-bar{background:#fff;border:1px solid #e0e6ef;border-radius:10px;display:grid;grid-template-columns:repeat(8,1fr);margin-bottom:14px;padding:11px 14px}.stage-bar div{align-items:center;color:#98a2b2;display:flex;gap:6px;position:relative}.stage-bar div:not(:last-child):after{background:#e1e6ed;content:'';height:1px;position:absolute;right:7px;width:30%}.stage-bar span{align-items:center;background:#eef1f5;border-radius:50%;display:flex;height:23px;justify-content:center;width:23px}.stage-bar b{font-size:9px}.stage-bar small{font-size:9px}.stage-bar .reached{color:#0a9b6c}.stage-bar .reached span{background:#e4f8ef}.stage-bar .current{color:#075bf5;font-weight:800}.workspace-grid{display:grid;gap:12px;grid-template-columns:210px minmax(420px,1fr) 250px;min-height:520px}.workspace-grid>aside,.workspace-grid>main{background:#fff;border:1px solid #e0e6ee;border-radius:10px;padding:14px}.workspace-grid h2{font-size:11px;margin:0 0 12px}.scene-empty{align-items:center;color:#8490a3;display:flex;flex-direction:column;gap:7px;padding:70px 10px;text-align:center}.scene-empty strong{color:#526078;font-size:11px}.scene-empty span{font-size:9px;line-height:1.6}.panel-head{align-items:start;display:flex;justify-content:space-between}.panel-head h1{font-size:18px;margin:0}.panel-head p{color:#8290a4;font-size:10px;margin:5px 0 12px}.workspace-grid textarea{border:1px solid #dce3ec;border-radius:8px;font-family:inherit;font-size:12px;line-height:1.8;min-height:390px;padding:13px;resize:vertical;width:100%}.privacy{background:#f4f8ff;border-radius:7px;color:#55709b;font-size:9px;margin-top:9px;padding:8px 10px}.inspector dl{display:grid;font-size:10px;gap:7px;grid-template-columns:75px 1fr}.inspector dt{color:#8792a3}.inspector dd{font-weight:700;margin:0;overflow:hidden;text-overflow:ellipsis}.inspector h2:nth-of-type(2){border-top:1px solid #ebeff4;margin-top:16px;padding-top:14px}.task-error{background:#fff0f1;color:#c23d49;font-size:9px;padding:8px}.artifacts{display:grid;gap:5px}.artifacts a{align-items:center;color:#41628e;display:flex;font-size:9px;gap:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.artifacts>span{color:#9aa4b3;font-size:9px}.job-strip{align-items:center;background:#172033;border-radius:9px;color:#fff;display:flex;font-size:10px;gap:7px;margin-top:12px;padding:10px 13px}.job-strip span{color:#aeb9ca;margin-left:auto}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.workspace-loading{color:#7d899b;padding:60px;text-align:center}@media(max-width:1050px){.workspace-grid{grid-template-columns:1fr}.workspace-grid>aside:first-child{display:none}.stage-bar{overflow:auto}.stage-bar div{min-width:90px}}@media(max-width:700px){.workspace-page>header{align-items:flex-start;display:grid;gap:10px}.stage-bar{display:flex}.job-strip span{display:none}}
</style>
