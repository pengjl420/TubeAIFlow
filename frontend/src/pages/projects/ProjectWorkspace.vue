<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute } from 'vue-router'
import { CheckCircle2, CircleStop, FileAudio, FileText, Info, Loader2, Play, RefreshCw, Video } from 'lucide-vue-next'
import { cancelProjectTask, getProject, getProjectOutputs, getProjectScript, getProjectTask, projectOutputUrl, saveProjectScript, startProjectWorkflow, type ProjectOutputs, type ProjectTask } from '../../api/projects'
import type { Project } from '../../types/project'
import { confirmAction, usePageFeedback } from '../../services/feedback'

const route = useRoute()
const projectId = computed(() => String(route.params.projectId))
const project = ref<Project | null>(null)
const task = ref<ProjectTask | null>(null)
const outputs = ref<ProjectOutputs | null>(null)
const script = ref('')
const savedScript = ref('')
const selectedStage = ref('script')
const loading = ref(true)
const saving = ref(false)
const operating = ref(false)
const error = ref('')
const message = ref('')
let timer: number | undefined
usePageFeedback(error, message, { errorTitle: '项目工作流错误' })

const active = computed(() => Boolean(task.value?.running || task.value?.queued))
const scriptDirty = computed(() => script.value !== savedScript.value)
const scriptCharacters = computed(() => script.value.trim().length)
const estimatedMinutes = computed(() => Math.max(0, Math.round(scriptCharacters.value / 260)))
const stages = [
  ['script', '脚本'], ['tts', '配音'], ['subtitles', '字幕'], ['storyboard', '分镜'],
  ['image_generation', '视觉'], ['visual_track', '时间轴'], ['quality_check', '质量'], ['completed', '导出'],
]
const stageDetails: Record<string, { description: string, output: string }> = {
  script: { description: '导入并规范化完整逐字稿，作为后续所有阶段的唯一文本来源。', output: 'clean_script.txt' },
  tts: { description: '按自然语义切段生成旁白，保留每段音频和完整合并音频。', output: 'audio/final.wav' },
  subtitles: { description: '将旁白时间与原稿对齐，生成可复核的字幕时间线。', output: 'subtitle/final.srt' },
  storyboard: { description: '根据语义和音频节奏规划 Scene、镜头类型与视觉意图。', output: 'scenes/storyboard.json' },
  image_generation: { description: '匹配本地素材或生成候选视觉，并保留 Provider 与 Prompt。', output: 'assets/generated' },
  visual_track: { description: '将旁白、字幕和视觉素材组织到可渲染时间轴。', output: 'timeline.json' },
  quality_check: { description: '检查重复画面、字幕、音频和视觉匹配风险。', output: 'quality/report.json' },
  completed: { description: '完成最终渲染并汇总所有可交付产物。', output: 'renders/final' },
}
const selectedStageDetail = computed(() => stageDetails[selectedStage.value])

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [projectData, taskData, outputData, scriptData] = await Promise.all([
      getProject(projectId.value), getProjectTask(projectId.value), getProjectOutputs(projectId.value), getProjectScript(projectId.value),
    ])
    project.value = projectData
    task.value = taskData
    outputs.value = outputData
    if (!scriptDirty.value) {
      script.value = scriptData.text
      savedScript.value = scriptData.text
    }
    if (taskData?.stage && stages.some(item => item[0] === taskData.stage)) selectedStage.value = taskData.stage
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
    savedScript.value = script.value
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

function projectStatusLabel(status: string) {
  return ({ created: '待导入脚本', script_imported: '脚本已导入', segmented: '已分段', narration_in_progress: '正在生成配音', narration_ready: '配音字幕完成', video_in_progress: '正在生成视频', review_required: '等待审核', completed: '已完成', failed: '需要处理' } as Record<string, string>)[status] || status
}

function taskStatusLabel(status?: string) {
  return ({ queued: '排队中', running: '运行中', paused: '已暂停', completed: '已完成', failed: '失败', cancelled: '已取消', idle: '未开始' } as Record<string, string>)[status || 'idle'] || status || '未开始'
}

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!scriptDirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

async function canLeaveProject() {
  if (!scriptDirty.value) return true
  return confirmAction({ title: '脚本尚未保存', description: '离开项目会丢失当前脚本修改。', confirmText: '放弃修改并离开', tone: 'warning' })
}

onBeforeRouteLeave(canLeaveProject)
onBeforeRouteUpdate(canLeaveProject)
onMounted(async () => { window.addEventListener('beforeunload', handleBeforeUnload); await load(); timer = window.setInterval(() => { if (!document.hidden && active.value) void load(true) }, 3000) })
onBeforeUnmount(() => { window.removeEventListener('beforeunload', handleBeforeUnload); if (timer !== undefined) window.clearInterval(timer) })
</script>

<template>
  <section v-if="project" class="workspace-page">
    <header><div><RouterLink to="/projects">项目</RouterLink><span>/</span><strong>{{ project.name }}</strong><p>{{ project.output_dir }}</p></div><div class="actions"><button class="secondary" @click="load()"><RefreshCw :size="15" />刷新</button><button v-if="active" class="danger" :disabled="operating" @click="cancelWorkflow"><CircleStop :size="16" />停止</button><button v-else :disabled="operating || !project.script_clean_path" @click="runWorkflow"><Play :size="16" />运行工作流</button></div></header>

    <nav class="stage-bar" aria-label="项目生产阶段"><button v-for="([id, label], index) in stages" :key="id" type="button" :class="{ reached: stageReached(id), current: task?.stage === id, selected: selectedStage === id }" :aria-current="task?.stage === id ? 'step' : undefined" @click="selectedStage = id"><span><CheckCircle2 v-if="stageReached(id)" :size="14" /><b v-else>{{ index + 1 }}</b></span><small>{{ label }}</small></button></nav>
    <section class="stage-context" aria-live="polite"><Info :size="17" /><div><strong>{{ stages.find(item => item[0] === selectedStage)?.[1] }}</strong><span>{{ selectedStageDetail.description }}</span></div><small>预期产物：{{ selectedStageDetail.output }}</small></section>

    <div class="workspace-grid">
      <aside><h2>Scene / 输入</h2><div class="scene-empty"><FileText :size="28" /><strong>{{ task && stageReached('storyboard') ? 'Scene 数据准备中' : '从脚本开始' }}</strong><span>{{ task && stageReached('storyboard') ? '完成分镜后，这里将承载 Scene 级重做、锁定与异常复核。' : '保存脚本并运行工作流后，Scene 会在这里逐步生成。' }}</span></div><div class="input-summary"><span>脚本字符</span><strong>{{ scriptCharacters.toLocaleString() }}</strong><span>预计旁白</span><strong>约 {{ estimatedMinutes }} 分钟</strong></div></aside>
      <main><div class="panel-head"><div><h1>脚本</h1><p>导入完整逐字稿。TTS 分段与字幕切分会保持解耦。</p></div><button :disabled="saving || !script.trim() || active || !scriptDirty" @click="saveScript">{{ saving ? '保存中…' : scriptDirty ? '保存脚本' : '已保存' }}</button></div><textarea v-model="script" :disabled="active" placeholder="在此粘贴 20～60 分钟长视频逐字稿…" /><div class="editor-footer"><span :class="{ dirty: scriptDirty }">{{ scriptDirty ? '有未保存修改' : '脚本已保存' }}</span><span>{{ scriptCharacters.toLocaleString() }} 字符 · 约 {{ estimatedMinutes }} 分钟旁白</span></div><div class="privacy">默认仅在本机处理。当前项目不会自动上传完整脚本到第三方服务。</div></main>
      <aside class="inspector"><h2>项目状态</h2><dl><dt>生命周期</dt><dd>{{ projectStatusLabel(project.status) }}</dd><dt>任务状态</dt><dd>{{ taskStatusLabel(task?.status) }}</dd><dt>当前阶段</dt><dd>{{ stages.find(item => item[0] === task?.stage)?.[1] || '尚未开始' }}</dd><dt>排队位置</dt><dd>{{ task?.queue_position || '—' }}</dd></dl><p v-if="task?.error_message" class="task-error">{{ task.error_message }}</p><h2>产物 <small v-if="outputs?.files.length">{{ outputs.files.length }}</small></h2><div class="artifacts"><a v-for="file in outputs?.files" :key="file.path" :href="projectOutputUrl(projectId, file.path)" target="_blank" rel="noopener"><FileAudio v-if="file.name.endsWith('.wav')" :size="14" /><Video v-else-if="file.name.endsWith('.mp4')" :size="14" /><FileText v-else :size="14" />{{ file.relative_path }}</a><span v-if="!outputs?.files.length">暂无输出文件</span></div></aside>
    </div>
    <footer class="job-strip"><Loader2 v-if="active" class="spin" :size="16" /><CheckCircle2 v-else :size="16" /><strong>{{ active ? `正在执行：${task?.stage}` : '本地 Engine 已就绪' }}</strong><span>所有耗时步骤通过持久化任务运行，关闭页面不会中断任务。</span></footer>
  </section>
  <div v-else class="workspace-loading">{{ loading ? '正在加载项目…' : '项目不存在' }}</div>
</template>

<style scoped>
.workspace-page{color:#172033}.workspace-page>header{align-items:center;display:flex;justify-content:space-between;margin-bottom:14px}.workspace-page header>div:first-child{align-items:center;display:flex;flex-wrap:wrap;font-size:12px;gap:7px}.workspace-page header a{color:#075bf5}.workspace-page header p{color:#7f8a9d;flex-basis:100%;font-size:11px;margin:1px 0}.actions{display:flex;gap:7px}.actions button,.panel-head button{align-items:center;background:#075bf5;border-radius:7px;color:#fff;display:flex;font-size:12px;font-weight:700;gap:5px;min-height:38px;padding:7px 12px}.actions .secondary{background:#fff;border:1px solid #dae2ed;color:#536078}.actions .danger{background:#d94956}.stage-bar{background:#fff;border:1px solid #e0e6ef;border-radius:10px;display:grid;grid-template-columns:repeat(8,1fr);margin-bottom:8px;padding:8px}.stage-bar button{align-items:center;background:transparent;border-radius:7px;color:#8d98a9;display:flex;gap:7px;min-height:42px;padding:6px;position:relative}.stage-bar button:not(:last-child):after{background:#e1e6ed;content:'';height:1px;position:absolute;right:2px;width:22%}.stage-bar button:hover,.stage-bar button.selected{background:#f4f7fb}.stage-bar button.selected{box-shadow:inset 0 0 0 1px #c9dcff}.stage-bar span{align-items:center;background:#eef1f5;border-radius:50%;display:flex;height:25px;justify-content:center;width:25px}.stage-bar b{font-size:10px}.stage-bar small{font-size:11px}.stage-bar .reached{color:#0a9b6c}.stage-bar .reached span{background:#e4f8ef}.stage-bar .current{color:#075bf5;font-weight:800}.stage-context{align-items:center;background:#f3f7ff;border:1px solid #dce8ff;border-radius:8px;color:#58709a;display:flex;gap:9px;margin-bottom:12px;padding:9px 11px}.stage-context>div{display:grid;gap:2px}.stage-context strong{color:#29466f;font-size:12px}.stage-context span{font-size:11px}.stage-context>small{font-size:10px;margin-left:auto}.workspace-grid{display:grid;gap:12px;grid-template-columns:210px minmax(420px,1fr) 250px;min-height:520px}.workspace-grid>aside,.workspace-grid>main{background:#fff;border:1px solid #e0e6ee;border-radius:10px;padding:14px}.workspace-grid h2{font-size:13px;margin:0 0 12px}.workspace-grid h2 small{color:#8490a3;float:right;font-size:11px}.scene-empty{align-items:center;color:#8490a3;display:flex;flex-direction:column;gap:7px;padding:50px 10px;text-align:center}.scene-empty strong{color:#526078;font-size:13px}.scene-empty span{font-size:11px;line-height:1.6}.input-summary{border-top:1px solid #edf0f4;display:grid;font-size:11px;gap:7px;grid-template-columns:1fr auto;padding-top:12px}.input-summary span{color:#7f8a9d}.panel-head{align-items:start;display:flex;justify-content:space-between}.panel-head h1{font-size:19px;margin:0}.panel-head p{color:#8290a4;font-size:11px;margin:5px 0 12px}.workspace-grid textarea{border:1px solid #dce3ec;border-radius:8px;font-family:inherit;font-size:13px;line-height:1.8;min-height:390px;padding:13px;resize:vertical;width:100%}.editor-footer{align-items:center;color:#7b8799;display:flex;font-size:11px;justify-content:space-between;padding-top:7px}.editor-footer span:first-child{color:#0a9567}.editor-footer .dirty{color:#a96a08}.privacy{background:#f4f8ff;border-radius:7px;color:#55709b;font-size:11px;margin-top:9px;padding:8px 10px}.inspector dl{display:grid;font-size:11px;gap:8px;grid-template-columns:75px 1fr}.inspector dt{color:#7f8a9d}.inspector dd{font-weight:700;margin:0;overflow:hidden;text-overflow:ellipsis}.inspector h2:nth-of-type(2){border-top:1px solid #ebeff4;margin-top:16px;padding-top:14px}.task-error{background:#fff0f1;color:#c23d49;font-size:11px;padding:8px}.artifacts{display:grid;gap:6px;max-height:300px;overflow:auto}.artifacts a{align-items:center;color:#41628e;display:flex;font-size:11px;gap:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.artifacts>span{color:#9aa4b3;font-size:11px}.job-strip{align-items:center;background:#172033;border-radius:9px;color:#fff;display:flex;font-size:11px;gap:7px;margin-top:12px;padding:11px 13px}.job-strip span{color:#aeb9ca;margin-left:auto}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.workspace-loading{color:#7d899b;padding:60px;text-align:center}@media(max-width:1050px){.workspace-grid{grid-template-columns:1fr}.workspace-grid>aside:first-child{display:none}.stage-bar{overflow:auto}.stage-bar button{min-width:105px}.stage-context>small{display:none}}@media(max-width:700px){.workspace-page>header{align-items:flex-start;display:grid;gap:10px}.stage-bar{display:flex}.stage-context span{display:none}.job-strip span{display:none}.editor-footer{align-items:flex-start;display:grid;gap:3px}}
</style>
