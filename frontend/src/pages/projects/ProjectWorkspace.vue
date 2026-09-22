<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute } from 'vue-router'
import { CheckCircle2, CircleStop, Download, FileAudio, FileText, Folder, History, Info, Loader2, Lock, Play, RefreshCw, Save, Settings2, Video, X } from 'lucide-vue-next'
import { cancelProjectTask, enqueueProjectQualityCheck, enqueueSceneStoryboardJob, exportProjectPrproj, getProject, getProjectOutputs, getProjectQualityReport, getProjectScenes, getProjectScript, getProjectTask, getSceneRevisions, listVisualStrategies, projectOutputUrl, recordProjectManualAcceptance, restoreSceneRevision, saveProjectScript, startProjectWorkflow, updateProjectScene, updateProjectSettings, updateProjectVideoSettings, type ProjectOutputs, type ProjectSettingsInput, type ProjectTask, type QualityIssue, type QualityReport, type VisualStrategyMetadata } from '../../api/projects'
import { listVoices, type VoiceProfile } from '../../api/voices'
import { selectDirectory } from '../../api/settings'
import type { Project, VideoGenerationMode } from '../../types/project'
import type { SceneRevision, VisualScene } from '../../types/storyboard'
import { confirmAction, usePageFeedback } from '../../services/feedback'
import SceneVisualWorkspace from '../../components/projects/SceneVisualWorkspace.vue'

const route = useRoute()
const projectId = computed(() => String(route.params.projectId))
const project = ref<Project | null>(null)
const task = ref<ProjectTask | null>(null)
const outputs = ref<ProjectOutputs | null>(null)
const qualityReport = ref<QualityReport | null>(null)
const qualityChecking = ref(false)
const showAllQualityIssues = ref(false)
const script = ref('')
const savedScript = ref('')
const scenes = ref<VisualScene[]>([])
const selectedSceneId = ref('')
const sceneDraft = ref<VisualScene | null>(null)
const revisions = ref<SceneRevision[]>([])
const selectedStage = ref('script')
const loading = ref(true)
const saving = ref(false)
const operating = ref(false)
const error = ref('')
const message = ref('')
const showSettings = ref(false)
const voices = ref<VoiceProfile[]>([])
const settingsDraft = ref<ProjectSettingsInput>({
  name: '', outputDir: '', outputFilename: '', mediaVideoDir: '', videoMode: 'none',
  ttsEngine: 'index_tts', referenceAudioText: '', voiceProfileId: '',
  storyboardTransitionEnabled: true, segmentationMode: 'ai', storyboardMode: 'ai',
  visualEnrichmentMode: 'auto', visualGenerationMode: 'curated',
})
const visualStrategies = ref<VisualStrategyMetadata[]>([])
let timer: number | undefined
usePageFeedback(error, message, { errorTitle: '项目工作流错误' })

const active = computed(() => Boolean(task.value?.running || task.value?.queued))
const qualityIssues = computed(() => {
  const issues = [...(qualityReport.value?.issues || [])]
  issues.sort((left, right) => Number(right.severity === 'error') - Number(left.severity === 'error'))
  return showAllQualityIssues.value ? issues : issues.slice(0, 30)
})
const qualityStatusText = computed(() => {
  if (!qualityReport.value) return ''
  if (qualityReport.value.stale) return '报告已过期，请重新检查'
  if (!qualityReport.value.passed) return '发现需要处理的问题'
  return qualityReport.value.verification_status === 'manually_accepted'
    ? '自动检查和人工打开验收均已通过'
    : '自动检查通过，仍需在目标剪辑软件中打开验收'
})
const scriptDirty = computed(() => script.value !== savedScript.value)
const selectedScene = computed(() => scenes.value.find(scene => scene.id === selectedSceneId.value) || null)
const sceneDirty = computed(() => Boolean(
  sceneDraft.value && selectedScene.value
  && JSON.stringify(sceneDraft.value) !== JSON.stringify(selectedScene.value),
))
const scriptCharacters = computed(() => script.value.trim().length)
const estimatedMinutes = computed(() => Math.max(0, Math.round(scriptCharacters.value / 260)))
const stages = [
  ['script', '脚本'], ['tts', '配音'], ['subtitles', '字幕'], ['storyboard', '分镜'],
  ['image_generation', '视觉'], ['project_export', '工程导出'], ['delivery_quality_check', '交付检查'], ['completed', '完成'],
]
const stageDetails: Record<string, { description: string, output: string }> = {
  script: { description: '导入并规范化完整逐字稿，作为后续所有阶段的唯一文本来源。', output: 'clean_script.txt' },
  tts: { description: '按自然语义切段生成旁白，保留每段音频和完整合并音频。', output: 'audio/final.wav' },
  subtitles: { description: '将旁白时间与原稿对齐，生成可复核的字幕时间线。', output: 'subtitle/final.srt' },
  storyboard: { description: '根据语义和音频节奏规划 Scene、镜头类型与视觉意图。', output: 'scenes/storyboard.json' },
  image_generation: { description: '匹配本地素材或生成候选视觉，并保留 Provider 与 Prompt。', output: 'assets/generated' },
  project_export: { description: '将旁白、字幕、Scene 与素材链接转换为可继续深度剪辑的真实 PRPROJ 工程。', output: '*.prproj' },
  delivery_quality_check: { description: '核对 PRPROJ 转换证据、旁白、字幕、Scene 覆盖和素材链接。', output: 'reports/qa.json' },
  completed: { description: '交付 PRPROJ、WAV、SRT 与关联素材；不在 TubeAiFolw 内编辑时间线。', output: '*.prproj' },
}
const selectedStageDetail = computed(() => stageDetails[selectedStage.value])
const projectEditable = computed(() => ['created', 'script_imported', 'segmented'].includes(project.value?.status || ''))
const videoSettingsEditable = computed(() => projectEditable.value || ['narration_ready', 'failed', 'completed'].includes(project.value?.status || ''))
const settingsNeedMedia = computed(() => ['landscape', 'ai_landscape_mix'].includes(settingsDraft.value?.videoMode || 'none'))
const compatibleVisualStrategies = computed(() => visualStrategies.value.filter(
  item => item.compatible_video_modes.includes(settingsDraft.value?.videoMode || 'none'),
))

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [projectData, taskData, outputData, scriptData, sceneData] = await Promise.all([
      getProject(projectId.value), getProjectTask(projectId.value), getProjectOutputs(projectId.value), getProjectScript(projectId.value), getProjectScenes(projectId.value),
    ])
    project.value = projectData
    task.value = taskData
    outputs.value = outputData
    if (!taskData.running && !taskData.queued) {
      try { qualityReport.value = await getProjectQualityReport(projectId.value) }
      catch { qualityReport.value = null }
    }
    if (!scriptDirty.value) {
      script.value = scriptData.text
      savedScript.value = scriptData.text
    }
    scenes.value = sceneData
    const currentScene = sceneData.find(scene => scene.id === selectedSceneId.value) || sceneData[0]
    if (!sceneDirty.value && currentScene) setSceneDraft(currentScene)
    if (!currentScene) {
      selectedSceneId.value = ''
      sceneDraft.value = null
    }
    if (taskData?.stage && stages.some(item => item[0] === taskData.stage)) selectedStage.value = taskData.stage
  } catch (reason) {
    if (!silent) error.value = reason instanceof Error ? reason.message : '加载项目失败'
  } finally {
    if (!silent) loading.value = false
  }
}

function cloneScene(scene: VisualScene): VisualScene {
  return JSON.parse(JSON.stringify(scene)) as VisualScene
}

function setSceneDraft(scene: VisualScene) {
  selectedSceneId.value = scene.id
  sceneDraft.value = cloneScene(scene)
  void loadRevisions(scene.id)
}

async function loadRevisions(sceneId: string) {
  try { revisions.value = await getSceneRevisions(projectId.value, sceneId) }
  catch { revisions.value = [] }
}

async function selectScene(scene: VisualScene) {
  if (scene.id === selectedSceneId.value) return
  if (sceneDirty.value) {
    const discard = await confirmAction({ title: 'Scene 尚未保存', description: '切换 Scene 会丢失当前修改。', confirmText: '放弃修改', tone: 'warning' })
    if (!discard) return
  }
  setSceneDraft(scene)
}

async function saveScene() {
  const draft = sceneDraft.value
  if (!draft?.storyboard || !draft.narration.trim()) return
  saving.value = true
  try {
    const updated = await updateProjectScene(projectId.value, draft.id, {
      narration: draft.narration,
      storyboard: draft.storyboard,
      status: 'reviewed',
      locked_text: draft.locked_text,
      locked_audio: draft.locked_audio,
      locked_visual: draft.locked_visual,
    })
    const index = scenes.value.findIndex(scene => scene.id === updated.id)
    if (index >= 0) scenes.value[index] = updated
    setSceneDraft(updated)
    message.value = `Scene ${updated.scene_index} 已保存`
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '保存 Scene 失败'
  } finally { saving.value = false }
}

async function restoreRevision(revision: SceneRevision) {
  const restore = await confirmAction({
    title: `恢复 Scene 版本 ${revision.version}`,
    description: '当前版本会先自动保存到历史，然后恢复所选版本。',
    confirmText: '恢复此版本',
    tone: 'warning',
  })
  if (!restore || !sceneDraft.value) return
  operating.value = true
  try {
    const updated = await restoreSceneRevision(projectId.value, sceneDraft.value.id, revision.id)
    const index = scenes.value.findIndex(scene => scene.id === updated.id)
    if (index >= 0) scenes.value[index] = updated
    setSceneDraft(updated)
    message.value = `已恢复到版本 ${revision.version}`
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '恢复 Scene 版本失败'
  } finally { operating.value = false }
}

async function regenerateScene() {
  if (!sceneDraft.value || sceneDraft.value.locked_visual) return
  const regenerate = await confirmAction({
    title: `重新生成 Scene ${sceneDraft.value.scene_index}`,
    description: '将重新生成视觉规划并解除当前素材分配；当前版本会保存在历史中。',
    confirmText: '重新生成',
    tone: 'warning',
  })
  if (!regenerate) return
  operating.value = true
  try {
    task.value = await enqueueSceneStoryboardJob(projectId.value, sceneDraft.value.id)
    message.value = `Scene ${sceneDraft.value.scene_index} 已加入重生成队列`
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '重新生成 Scene 失败'
  } finally { operating.value = false }
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

async function openProjectSettings() {
  if (!project.value || !videoSettingsEditable.value) return
  try {
    if (!voices.value.length) voices.value = await listVoices()
    if (!visualStrategies.value.length) visualStrategies.value = await listVisualStrategies()
    const config = project.value.config || {}
    const selectedVoice = voices.value.find(item => item.id === config.voice_profile_id)
    settingsDraft.value = {
      name: project.value.name,
      outputDir: project.value.output_dir || '',
      outputFilename: String(config.output_filename || project.value.name),
      mediaVideoDir: String(config.media_video_dir || ''),
      videoMode: (config.video_mode || (config.include_video ? 'landscape' : 'none')) as VideoGenerationMode,
      ttsEngine: String(config.tts_engine || selectedVoice?.tts_engine || 'index_tts'),
      referenceAudioText: String(config.reference_audio_text || selectedVoice?.reference_audio_text || ''),
      voiceProfileId: String(config.voice_profile_id || selectedVoice?.id || voices.value[0]?.id || ''),
      storyboardTransitionEnabled: config.storyboard_transition_enabled !== false,
      segmentationMode: config.segmentation_mode === 'newline' ? 'newline' : 'ai',
      storyboardMode: config.storyboard_mode === 'segments' ? 'segments' : 'ai',
      visualEnrichmentMode: ['advanced', 'basic'].includes(String(config.visual_enrichment_mode))
        ? config.visual_enrichment_mode as 'advanced' | 'basic'
        : 'auto',
      visualGenerationMode: config.visual_generation_mode === 'anime_full_coverage'
        ? 'anime_full_coverage'
        : 'curated',
    }
    showSettings.value = true
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '读取项目设置失败' }
}

async function chooseSettingsDirectory(kind: 'output' | 'media') {
  if (!settingsDraft.value) return
  const current = kind === 'output' ? settingsDraft.value.outputDir : settingsDraft.value.mediaVideoDir
  const selected = await selectDirectory(current, kind === 'output' ? '选择项目输出目录' : '选择横屏视频素材目录')
  if (!selected) return
  if (kind === 'output') settingsDraft.value.outputDir = selected
  else settingsDraft.value.mediaVideoDir = selected
}

async function saveSettings() {
  if (!settingsDraft.value || !project.value) return
  const voice = voices.value.find(item => item.id === settingsDraft.value?.voiceProfileId)
  if (voice) {
    settingsDraft.value.ttsEngine = voice.tts_engine
    settingsDraft.value.referenceAudioText = voice.reference_audio_text
  }
  if (!compatibleVisualStrategies.value.some(
    item => item.id === settingsDraft.value?.visualGenerationMode,
  )) settingsDraft.value.visualGenerationMode = 'curated'
  saving.value = true
  try {
    project.value = projectEditable.value
      ? await updateProjectSettings(project.value.id, settingsDraft.value)
      : await updateProjectVideoSettings(project.value.id, settingsDraft.value)
    showSettings.value = false
    message.value = '项目生产配置已保存'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '保存项目设置失败' }
  finally { saving.value = false }
}

async function createEditableExport() {
  operating.value = true
  try {
    await exportProjectPrproj(projectId.value)
    await load(true)
    message.value = 'PRPROJ 剪辑工程已生成'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '生成可编辑工程失败' }
  finally { operating.value = false }
}

async function checkDelivery() {
  qualityChecking.value = true
  try {
    task.value = await enqueueProjectQualityCheck(projectId.value)
    message.value = '交付质量检查已加入队列'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '质量检查启动失败' }
  finally { qualityChecking.value = false }
}

async function confirmManualAcceptance() {
  if (!qualityReport.value?.delivery_verified || qualityReport.value.stale) return
  const confirmed = await confirmAction({
    title: '确认工程人工验收',
    description: '请仅在 Premiere Pro 和目标剪映版本中实际打开工程，并确认旁白、字幕和素材链接均正常后继续。',
    confirmText: '三项均已确认',
    tone: 'warning',
  })
  if (!confirmed) return
  operating.value = true
  try {
    qualityReport.value = await recordProjectManualAcceptance(projectId.value, {
      editor: 'Premiere Pro + Jianying Pro',
      audio_ok: true,
      subtitles_ok: true,
      media_links_ok: true,
    })
    message.value = '已记录人工打开验收'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '记录人工验收失败'
  } finally { operating.value = false }
}

async function focusQualityIssue(issue: QualityIssue) {
  if (issue.scene_id) {
    const scene = scenes.value.find(item => item.id === issue.scene_id)
    if (scene) {
      await selectScene(scene)
      if (selectedSceneId.value === scene.id) selectedStage.value = 'storyboard'
    }
  }
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

function formatTime(milliseconds: number) {
  const totalSeconds = Math.max(0, Math.floor(milliseconds / 1000))
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!scriptDirty.value && !sceneDirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

async function canLeaveProject() {
  if (!scriptDirty.value && !sceneDirty.value) return true
  return confirmAction({ title: '修改尚未保存', description: '离开项目会丢失当前脚本或 Scene 修改。', confirmText: '放弃修改并离开', tone: 'warning' })
}

onBeforeRouteLeave(canLeaveProject)
onBeforeRouteUpdate(canLeaveProject)
onMounted(async () => { window.addEventListener('beforeunload', handleBeforeUnload); await load(); timer = window.setInterval(() => { if (!document.hidden && active.value) void load(true) }, 3000) })
onBeforeUnmount(() => { window.removeEventListener('beforeunload', handleBeforeUnload); if (timer !== undefined) window.clearInterval(timer) })
</script>

<template>
  <section v-if="project" class="workspace-page">
    <header class="taf-sticky-heading"><div><RouterLink to="/projects">项目</RouterLink><span>/</span><strong>{{ project.name }}</strong><p>{{ project.output_dir }}</p></div><div class="actions"><button v-if="videoSettingsEditable" class="secondary" @click="openProjectSettings"><Settings2 :size="15" />项目设置</button><button class="secondary" @click="load()"><RefreshCw :size="15" />刷新</button><button v-if="selectedStage === 'storyboard' && sceneDraft" class="secondary" :disabled="operating || active || sceneDirty || sceneDraft.locked_visual" @click="regenerateScene"><RefreshCw :size="15" />重做 Scene</button><button v-if="active" class="danger" :disabled="operating" @click="cancelWorkflow"><CircleStop :size="16" />停止</button><button v-else :disabled="operating || !project.script_clean_path" @click="runWorkflow"><Play :size="16" />{{ project.status === 'narration_ready' && project.config?.include_video ? '继续生成视频' : '运行工作流' }}</button></div></header>
    <Teleport to="body"><div v-if="showSettings && settingsDraft" class="project-settings-backdrop" @mousedown.self="showSettings = false"><form class="project-settings-dialog" @submit.prevent="saveSettings"><header><div><Settings2 :size="20" /><div><h2>项目生产配置</h2><p>{{ projectEditable ? '生成开始后，旁白与输出基础配置将锁定。' : '旁白已完成；当前只允许调整后续视频配置。' }}</p></div></div><button type="button" aria-label="关闭" @click="showSettings = false"><X :size="18" /></button></header><div class="project-settings-grid"><label><span>项目名称</span><input v-model="settingsDraft.name" required :disabled="!projectEditable" /></label><label><span>输出文件名</span><input v-model="settingsDraft.outputFilename" required :disabled="!projectEditable" /></label><label class="wide"><span>输出目录</span><div><input v-model="settingsDraft.outputDir" required :disabled="!projectEditable" /><button v-if="projectEditable" type="button" @click="chooseSettingsDirectory('output')"><Folder :size="14" />浏览</button></div></label><label><span>默认音色</span><select v-model="settingsDraft.voiceProfileId" required :disabled="!projectEditable"><option v-for="voice in voices" :key="voice.id" :value="voice.id">{{ voice.name }} · {{ voice.tts_engine }}</option></select></label><label><span>TTS 分段</span><select v-model="settingsDraft.segmentationMode" :disabled="!projectEditable"><option value="ai">AI 语义分段</option><option value="newline">按换行分段</option></select></label><label><span>视频生产模式</span><select v-model="settingsDraft.videoMode"><option value="ai_generated_images">AI 分镜图片</option><option value="ai_landscape_mix">AI 图片 + 本地横屏素材</option><option value="landscape">仅本地横屏素材</option><option value="none">仅配音与字幕</option></select></label><label><span>分镜方式</span><select v-model="settingsDraft.storyboardMode" :disabled="settingsDraft.videoMode === 'none'"><option value="ai">AI 语义分镜</option><option value="segments">沿用 TTS 分段</option></select></label><label v-if="compatibleVisualStrategies.length"><span>画面生成方式</span><select v-model="settingsDraft.visualGenerationMode"><option v-for="strategy in compatibleVisualStrategies" :key="strategy.id" :value="strategy.id">{{ strategy.display_name }}</option></select><small>{{ compatibleVisualStrategies.find(item => item.id === settingsDraft.visualGenerationMode)?.description }}</small></label><label v-if="settingsNeedMedia" class="wide"><span>横屏素材目录</span><div><input v-model="settingsDraft.mediaVideoDir" required /><button type="button" @click="chooseSettingsDirectory('media')"><Folder :size="14" />浏览</button></div></label><label class="check wide"><input v-model="settingsDraft.storyboardTransitionEnabled" type="checkbox" />启用基础转场</label></div><footer><button type="button" @click="showSettings = false">取消</button><button class="primary" type="submit" :disabled="saving || !settingsDraft.name.trim() || !settingsDraft.outputDir.trim() || !settingsDraft.voiceProfileId || (settingsNeedMedia && !settingsDraft.mediaVideoDir.trim())">{{ saving ? '保存中…' : '保存配置' }}</button></footer></form></div></Teleport>

    <nav class="stage-bar" aria-label="项目生产阶段"><button v-for="([id, label], index) in stages" :key="id" type="button" :class="{ reached: stageReached(id), current: task?.stage === id, selected: selectedStage === id }" :aria-current="task?.stage === id ? 'step' : undefined" @click="selectedStage = id"><span><CheckCircle2 v-if="stageReached(id)" :size="14" /><b v-else>{{ index + 1 }}</b></span><small>{{ label }}</small></button></nav>
    <section class="stage-context" aria-live="polite"><Info :size="17" /><div><strong>{{ stages.find(item => item[0] === selectedStage)?.[1] }}</strong><span>{{ selectedStageDetail.description }}</span></div><small>预期产物：{{ selectedStageDetail.output }}</small></section>

    <div class="workspace-grid" :class="{ 'visual-mode': selectedStage === 'image_generation' }">
      <SceneVisualWorkspace v-if="sceneDraft && selectedStage === 'image_generation'" :project-id="projectId" :scene="sceneDraft" />
      <aside class="scene-sidebar"><h2>Scene <small v-if="scenes.length">{{ scenes.length }}</small></h2><div v-if="scenes.length" class="scene-list"><button v-for="scene in scenes" :key="scene.id" type="button" :class="{ selected: scene.id === selectedSceneId }" @click="selectScene(scene)"><span><b>{{ String(scene.scene_index).padStart(2, '0') }}</b><small>{{ formatTime(scene.start_ms) }}–{{ formatTime(scene.end_ms) }}</small></span><strong>{{ scene.storyboard?.visual_summary || scene.narration }}</strong><em>{{ scene.status === 'reviewed' ? '已复核' : scene.status === 'generated' ? '已生成' : '草稿' }}</em></button></div><div v-else class="scene-empty"><FileText :size="28" /><strong>{{ task && stageReached('storyboard') ? 'Scene 数据准备中' : '从脚本开始' }}</strong><span>{{ task && stageReached('storyboard') ? 'Storyboard 完成后将在这里显示 Scene。' : '保存脚本并运行工作流后，Scene 会在这里逐步生成。' }}</span></div><div class="input-summary"><span>脚本字符</span><strong>{{ scriptCharacters.toLocaleString() }}</strong><span>预计旁白</span><strong>约 {{ estimatedMinutes }} 分钟</strong></div></aside>
      <main v-if="selectedStage === 'storyboard' && sceneDraft?.storyboard" class="scene-editor"><div class="panel-head"><div><h1>Scene {{ sceneDraft.scene_index }}</h1><p>{{ formatTime(sceneDraft.start_ms) }}–{{ formatTime(sceneDraft.end_ms) }} · {{ ((sceneDraft.end_ms - sceneDraft.start_ms) / 1000).toFixed(1) }} 秒 · 版本 {{ sceneDraft.version }}</p></div><button :disabled="saving || active || !sceneDirty || !sceneDraft.narration.trim()" @click="saveScene"><Save :size="14" />{{ saving ? '保存中…' : sceneDirty ? '保存 Scene' : '已保存' }}</button></div><div class="lock-bar"><Lock :size="14" /><label><input v-model="sceneDraft.locked_text" type="checkbox" />锁定文本</label><label><input v-model="sceneDraft.locked_audio" type="checkbox" />锁定音频</label><label><input v-model="sceneDraft.locked_visual" type="checkbox" />锁定视觉</label><small>锁定内容不会被自动工作流覆盖</small></div><div class="scene-form"><label class="wide"><span>旁白文本</span><textarea v-model="sceneDraft.narration" rows="5" :disabled="selectedScene?.locked_text" /></label><label><span>视觉类型</span><input v-model="sceneDraft.storyboard.visual_type" :disabled="selectedScene?.locked_visual" /></label><label><span>推荐来源</span><select v-model="sceneDraft.storyboard.recommended_source" :disabled="selectedScene?.locked_visual"><option value="stock_video">Stock Video</option><option value="archive">Archive</option><option value="generated_image">AI Image</option><option value="generated_video">AI Video</option><option value="chart">Chart</option><option value="map">Map</option><option value="timeline">Timeline</option><option value="document">Document</option><option value="text_card">Text Card</option></select></label><label class="wide"><span>视觉摘要</span><textarea v-model="sceneDraft.storyboard.visual_summary" rows="3" :disabled="selectedScene?.locked_visual" /></label><label><span>场景分类</span><input v-model="sceneDraft.storyboard.scene_category" :disabled="selectedScene?.locked_visual" /></label><label><span>情绪</span><input v-model="sceneDraft.storyboard.mood" :disabled="selectedScene?.locked_visual" /></label><label class="wide"><span>素材搜索词</span><input v-model="sceneDraft.storyboard.primary_query" :disabled="selectedScene?.locked_visual" /></label><label class="wide"><span>图片 Prompt</span><textarea v-model="sceneDraft.storyboard.image_prompt" rows="5" :disabled="selectedScene?.locked_visual" /></label><label class="wide"><span>Negative Prompt</span><textarea v-model="sceneDraft.storyboard.negative_prompt" rows="3" :disabled="selectedScene?.locked_visual" /></label></div><div class="editor-footer"><span :class="{ dirty: sceneDirty }">{{ sceneDirty ? '有未保存修改' : 'Scene 已保存' }}</span><span>置信度 {{ Math.round((sceneDraft.confidence || 0) * 100) }}% · 事实风险 {{ sceneDraft.storyboard.fact_risk }}</span></div></main>
      <main v-else-if="selectedStage === 'storyboard'" class="scene-editor-empty"><FileText :size="34" /><h1>暂无可编辑 Scene</h1><p>先运行到 Storyboard 阶段，系统会根据旁白节奏生成 Scene。</p></main>
      <main v-else-if="selectedStage === 'project_export' || selectedStage === 'delivery_quality_check' || selectedStage === 'completed'" class="delivery-panel">
        <div><CheckCircle2 :size="34" /><h1>剪辑工程交付</h1><p>PRPROJ 链接旁白、字幕和已选择素材，可导入支持 PR 工程导入的剪映专业版继续深度剪辑；移动项目后可能需要重新链接素材。</p></div>
        <a v-if="outputs?.final_prproj_exists" :href="projectOutputUrl(projectId, outputs.final_prproj_path, true)"><Download :size="17" />下载 PRPROJ 工程</a>
        <a v-if="outputs?.final_audio_exists" :href="projectOutputUrl(projectId, outputs.final_audio_path, true)"><FileAudio :size="17" />下载完整旁白</a>
        <a v-if="outputs?.final_srt_exists" :href="projectOutputUrl(projectId, outputs.final_srt_path, true)"><FileText :size="17" />下载 SRT 字幕</a>
        <button v-if="!outputs?.final_prproj_exists" :disabled="operating" @click="createEditableExport"><Download :size="17" />生成 PRPROJ 工程</button>
        <section class="quality-panel">
          <header><div><h2>交付质量检查</h2><p v-if="qualityReport">{{ qualityStatusText }} · 错误 {{ qualityReport.summary.error_count }} · 提醒 {{ qualityReport.summary.warning_count }}</p><p v-else>检查工程、旁白、字幕、Scene 和关联素材。</p></div><button :disabled="qualityChecking || active" @click="checkDelivery"><RefreshCw :size="14" />{{ qualityChecking ? '排队中…' : '重新检查' }}</button></header>
          <ul v-if="qualityReport?.issues.length"><li v-for="(issue, index) in qualityIssues" :key="`${issue.type}-${index}`" :class="issue.severity"><strong>{{ issue.severity === 'error' ? '错误' : '提醒' }}</strong><span>{{ issue.message }}<small v-if="issue.subtitle_cue_index">SRT 第 {{ issue.subtitle_cue_index }} 条 · {{ formatTime(issue.subtitle_start_ms || 0) }}</small><small v-if="issue.file_path">{{ issue.file_path }}</small><small v-if="issue.suggestion">{{ issue.suggestion }}</small></span><button v-if="issue.scene_id" @click="focusQualityIssue(issue)">定位 Scene</button></li></ul>
          <button v-if="qualityReport && qualityReport.issues.length > 30" @click="showAllQualityIssues = !showAllQualityIssues">{{ showAllQualityIssues ? '只显示前 30 项' : `显示全部 ${qualityReport.issues.length} 项` }}</button>
          <p v-else-if="qualityReport">未发现交付问题。</p>
          <button v-if="qualityReport?.delivery_verified && qualityReport.manual_acceptance_required && !qualityReport.stale" :disabled="operating" @click="confirmManualAcceptance">记录 Premiere / 剪映人工打开验收</button>
        </section>
      </main>
      <main v-else><div class="panel-head"><div><h1>脚本</h1><p>导入完整逐字稿。TTS 分段与字幕切分会保持解耦。</p></div><button :disabled="saving || !script.trim() || active || !scriptDirty" @click="saveScript">{{ saving ? '保存中…' : scriptDirty ? '保存脚本' : '已保存' }}</button></div><textarea v-model="script" :disabled="active" placeholder="在此粘贴 20～60 分钟长视频逐字稿…" /><div class="editor-footer"><span :class="{ dirty: scriptDirty }">{{ scriptDirty ? '有未保存修改' : '脚本已保存' }}</span><span>{{ scriptCharacters.toLocaleString() }} 字符 · 约 {{ estimatedMinutes }} 分钟旁白</span></div><div class="privacy">默认仅在本机处理。当前项目不会自动上传完整脚本到第三方服务。</div></main>
      <aside class="inspector"><template v-if="selectedStage === 'storyboard' && sceneDraft"><h2><History :size="13" />版本历史 <small>当前 v{{ sceneDraft.version }}</small></h2><div class="revision-list"><button v-for="revision in revisions" :key="revision.id" type="button" :disabled="operating" @click="restoreRevision(revision)"><span>版本 {{ revision.version }}</span><small>{{ new Date(revision.created_at).toLocaleString() }}</small></button><span v-if="!revisions.length">保存修改后会在这里保留历史版本</span></div></template><template v-else><h2>项目状态</h2><dl><dt>生命周期</dt><dd>{{ projectStatusLabel(project.status) }}</dd><dt>任务状态</dt><dd>{{ taskStatusLabel(task?.status) }}</dd><dt>当前阶段</dt><dd>{{ stages.find(item => item[0] === task?.stage)?.[1] || '尚未开始' }}</dd><dt>排队位置</dt><dd>{{ task?.queue_position || '—' }}</dd></dl><p v-if="task?.error_message" class="task-error">{{ task.error_message }}</p></template><h2>产物 <small v-if="outputs?.files.length">{{ outputs.files.length }}</small></h2><div class="artifacts"><a v-for="file in outputs?.files" :key="file.path" :href="projectOutputUrl(projectId, file.path)" target="_blank" rel="noopener"><FileAudio v-if="file.name.endsWith('.wav')" :size="14" /><Video v-else-if="file.name.endsWith('.mp4')" :size="14" /><FileText v-else :size="14" />{{ file.relative_path }}</a><span v-if="!outputs?.files.length">暂无输出文件</span></div></aside>
    </div>
    <footer class="job-strip"><Loader2 v-if="active" class="spin" :size="16" /><CheckCircle2 v-else :size="16" /><strong>{{ active ? `正在执行：${task?.stage}` : '本地 Engine 已就绪' }}</strong><span>所有耗时步骤通过持久化任务运行，关闭页面不会中断任务。</span></footer>
  </section>
  <div v-else class="workspace-loading">{{ loading ? '正在加载项目…' : '项目不存在' }}</div>
</template>

<style scoped>
.workspace-page{color:#172033}.workspace-page>header{align-items:center;display:flex;justify-content:space-between;margin-bottom:14px}.workspace-page header>div:first-child{align-items:center;display:flex;flex-wrap:wrap;font-size:12px;gap:7px}.workspace-page header a{color:#075bf5}.workspace-page header p{color:#7f8a9d;flex-basis:100%;font-size:11px;margin:1px 0}.actions{display:flex;gap:7px}.actions button,.panel-head button{align-items:center;background:#075bf5;border-radius:7px;color:#fff;display:flex;font-size:12px;font-weight:700;gap:5px;min-height:38px;padding:7px 12px}.actions .secondary{background:#fff;border:1px solid #dae2ed;color:#536078}.actions .danger{background:#d94956}.stage-bar{background:#fff;border:1px solid #e0e6ef;border-radius:10px;display:grid;grid-template-columns:repeat(8,1fr);margin-bottom:8px;padding:8px}.stage-bar button{align-items:center;background:transparent;border-radius:7px;color:#8d98a9;display:flex;gap:7px;min-height:42px;padding:6px;position:relative}.stage-bar button:not(:last-child):after{background:#e1e6ed;content:'';height:1px;position:absolute;right:2px;width:22%}.stage-bar button:hover,.stage-bar button.selected{background:#f4f7fb}.stage-bar button.selected{box-shadow:inset 0 0 0 1px #c9dcff}.stage-bar span{align-items:center;background:#eef1f5;border-radius:50%;display:flex;height:25px;justify-content:center;width:25px}.stage-bar b{font-size:10px}.stage-bar small{font-size:11px}.stage-bar .reached{color:#0a9b6c}.stage-bar .reached span{background:#e4f8ef}.stage-bar .current{color:#075bf5;font-weight:800}.stage-context{align-items:center;background:#f3f7ff;border:1px solid #dce8ff;border-radius:8px;color:#58709a;display:flex;gap:9px;margin-bottom:12px;padding:9px 11px}.stage-context>div{display:grid;gap:2px}.stage-context strong{color:#29466f;font-size:12px}.stage-context span{font-size:11px}.stage-context>small{font-size:10px;margin-left:auto}.workspace-grid{display:grid;gap:12px;grid-template-columns:230px minmax(420px,1fr) 250px;min-height:520px}.workspace-grid>aside,.workspace-grid>main{background:#fff;border:1px solid #e0e6ee;border-radius:10px;padding:14px}.workspace-grid h2{font-size:13px;margin:0 0 12px}.workspace-grid h2 small{color:#8490a3;float:right;font-size:11px}.scene-empty,.scene-editor-empty{align-items:center;color:#8490a3;display:flex;flex-direction:column;gap:7px;padding:50px 10px;text-align:center}.scene-empty strong{color:#526078;font-size:13px}.scene-empty span,.scene-editor-empty p{font-size:11px;line-height:1.6}.scene-editor-empty h1{color:#526078;font-size:16px;margin:4px 0 0}.scene-list{display:grid;gap:6px;max-height:390px;overflow:auto}.scene-list button{background:#f7f9fc;border:1px solid transparent;border-radius:8px;color:#536078;display:grid;gap:5px;padding:9px;text-align:left;width:100%}.scene-list button:hover{border-color:#cbd9ee}.scene-list button.selected{background:#edf4ff;border-color:#9fc0f6}.scene-list button>span{align-items:center;display:flex;justify-content:space-between}.scene-list b{color:#075bf5;font-size:11px}.scene-list small{color:#8490a3;font-size:9px}.scene-list strong{display:-webkit-box;font-size:11px;font-weight:650;line-height:1.45;overflow:hidden;-webkit-box-orient:vertical;-webkit-line-clamp:2}.scene-list em{color:#8090a7;font-size:9px;font-style:normal}.input-summary{border-top:1px solid #edf0f4;display:grid;font-size:11px;gap:7px;grid-template-columns:1fr auto;margin-top:12px;padding-top:12px}.input-summary span{color:#7f8a9d}.panel-head{align-items:start;display:flex;justify-content:space-between}.panel-head h1{font-size:19px;margin:0}.panel-head p{color:#8290a4;font-size:11px;margin:5px 0 12px}.workspace-grid>main:not(.scene-editor) textarea{border:1px solid #dce3ec;border-radius:8px;font-family:inherit;font-size:13px;line-height:1.8;min-height:390px;padding:13px;resize:vertical;width:100%}.scene-form{display:grid;gap:11px;grid-template-columns:1fr 1fr}.scene-form label{display:grid;gap:5px}.scene-form label.wide{grid-column:1/-1}.scene-form label>span{color:#526078;font-size:11px;font-weight:700}.scene-form input,.scene-form select,.scene-form textarea{background:#fff;border:1px solid #dce3ec;border-radius:7px;font:inherit;font-size:12px;line-height:1.55;min-height:38px;padding:8px;width:100%}.scene-form textarea{min-height:auto;resize:vertical}.scene-form input:focus,.scene-form select:focus,.scene-form textarea:focus{border-color:#75a8f5;box-shadow:0 0 0 3px rgba(7,91,245,.08);outline:0}.editor-footer{align-items:center;color:#7b8799;display:flex;font-size:11px;justify-content:space-between;padding-top:7px}.editor-footer span:first-child{color:#0a9567}.editor-footer .dirty{color:#a96a08}.privacy{background:#f4f8ff;border-radius:7px;color:#55709b;font-size:11px;margin-top:9px;padding:8px 10px}.inspector dl{display:grid;font-size:11px;gap:8px;grid-template-columns:75px 1fr}.inspector dt{color:#7f8a9d}.inspector dd{font-weight:700;margin:0;overflow:hidden;text-overflow:ellipsis}.inspector h2:nth-of-type(2){border-top:1px solid #ebeff4;margin-top:16px;padding-top:14px}.task-error{background:#fff0f1;color:#c23d49;font-size:11px;padding:8px}.artifacts{display:grid;gap:6px;max-height:300px;overflow:auto}.artifacts a{align-items:center;color:#41628e;display:flex;font-size:11px;gap:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.artifacts>span{color:#9aa4b3;font-size:11px}.job-strip{align-items:center;background:#172033;border-radius:9px;color:#fff;display:flex;font-size:11px;gap:7px;margin-top:12px;padding:11px 13px}.job-strip span{color:#aeb9ca;margin-left:auto}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.workspace-loading{color:#7d899b;padding:60px;text-align:center}@media(max-width:1050px){.workspace-grid{grid-template-columns:1fr}.workspace-grid>aside:first-child{display:block}.stage-bar{overflow:auto}.stage-bar button{min-width:105px}.stage-context>small{display:none}}@media(max-width:700px){.workspace-page>header{align-items:flex-start;display:grid;gap:10px}.stage-bar{display:flex}.stage-context span{display:none}.job-strip span{display:none}.editor-footer{align-items:flex-start;display:grid;gap:3px}.scene-form{grid-template-columns:1fr}.scene-form label.wide{grid-column:auto}}
</style>

<style>
.project-settings-backdrop{align-items:center;background:rgba(15,23,42,.44);display:flex;inset:0;justify-content:center;padding:22px;position:fixed;z-index:90}.project-settings-dialog{background:#fff;border-radius:14px;box-shadow:0 28px 70px rgba(15,32,60,.24);max-height:calc(100vh - 44px);overflow:auto;width:min(680px,100%)}.project-settings-dialog>header{align-items:flex-start;border-bottom:1px solid #e6ebf2;display:flex;justify-content:space-between;padding:18px 20px}.project-settings-dialog>header>div{align-items:center;display:flex;gap:11px}.project-settings-dialog h2{font-size:18px;margin:0}.project-settings-dialog header p{color:#7c8899;font-size:11px;margin:4px 0 0}.project-settings-dialog header>button{align-items:center;background:#f1f4f8;border-radius:7px;color:#68758a;display:flex;height:34px;justify-content:center;width:34px}.project-settings-grid{display:grid;gap:13px;grid-template-columns:1fr 1fr;padding:18px 20px}.project-settings-grid label{display:grid;gap:5px}.project-settings-grid label>span{color:#526078;font-size:11px;font-weight:700}.project-settings-grid .wide{grid-column:1/-1}.project-settings-grid input,.project-settings-grid select{border:1px solid #d9e1ec;border-radius:7px;min-height:39px;padding:7px 9px;width:100%}.project-settings-grid label>div{display:flex;gap:7px}.project-settings-grid label>div button{align-items:center;background:#edf3fc;border-radius:7px;color:#38639a;display:flex;gap:4px;padding:7px 11px;white-space:nowrap}.project-settings-grid .check{align-items:center;display:flex;flex-direction:row;font-size:12px}.project-settings-grid .check input{min-height:auto;width:auto}.project-settings-dialog>footer{background:#fafbfc;border-top:1px solid #e5eaf1;display:flex;gap:8px;justify-content:flex-end;padding:12px 20px}.project-settings-dialog>footer button{background:#fff;border:1px solid #d8e0eb;border-radius:7px;color:#536078;padding:8px 14px}.project-settings-dialog>footer .primary{background:#075bf5;border-color:#075bf5;color:#fff}@media(max-width:650px){.project-settings-backdrop{align-items:flex-end;padding:0}.project-settings-dialog{border-radius:15px 15px 0 0;max-height:92vh}.project-settings-grid{grid-template-columns:1fr}.project-settings-grid .wide{grid-column:auto}}
.delivery-panel{align-content:center;display:grid;gap:9px;grid-template-columns:1fr 1fr}.delivery-panel>div{grid-column:1/-1;text-align:center}.delivery-panel>div svg{color:#0a9b6c}.delivery-panel h1{font-size:20px;margin:7px 0 3px}.delivery-panel p{color:#7d899b;font-size:11px;margin:0 0 12px}.delivery-panel>a,.delivery-panel>button{align-items:center;background:#f4f7fb;border:1px solid #dce4ef;border-radius:8px;color:#31577f;display:flex;font-size:11px;font-weight:700;gap:7px;justify-content:center;min-height:44px;padding:9px}.delivery-panel>a:first-of-type{background:#075bf5;border-color:#075bf5;color:#fff}@media(max-width:650px){.delivery-panel{grid-template-columns:1fr}.delivery-panel>div{grid-column:auto}}
.quality-panel{border-top:1px solid #e5eaf1;grid-column:1/-1;margin-top:12px;padding-top:14px}.quality-panel header{align-items:flex-start;display:flex;justify-content:space-between}.quality-panel h2{font-size:13px;margin:0 0 3px}.quality-panel header p{margin:0}.quality-panel button{background:#edf3fc;border-radius:6px;color:#31577f;font-size:11px;padding:7px 9px}.quality-panel header button{align-items:center;display:flex;gap:5px}.quality-panel button:disabled{opacity:.5}.quality-panel ul{display:grid;gap:7px;list-style:none;margin:12px 0 0;padding:0}.quality-panel li{align-items:start;background:#f7f9fc;border-left:3px solid #b8892b;border-radius:5px;display:flex;gap:9px;padding:9px}.quality-panel li.error{background:#fff5f5;border-left-color:#d94956}.quality-panel li strong{font-size:10px;white-space:nowrap}.quality-panel li span{font-size:11px;line-height:1.5;min-width:0;overflow-wrap:anywhere}.quality-panel li small{color:#718096;display:block}.quality-panel li button{margin-left:auto;white-space:nowrap}
</style>

<style scoped>
.lock-bar{align-items:center;background:#f7f9fc;border:1px solid #e4e9f1;border-radius:8px;display:flex;font-size:11px;gap:12px;margin-bottom:12px;padding:9px}.lock-bar label{align-items:center;display:flex;gap:5px}.lock-bar small{color:#8490a3;margin-left:auto}.scene-form input:disabled,.scene-form select:disabled,.scene-form textarea:disabled{background:#f2f4f7;color:#8b95a5}.revision-list{display:grid;gap:6px;max-height:210px;overflow:auto}.revision-list>button{background:#f7f9fc;border:1px solid #e2e7ef;border-radius:7px;display:grid;gap:2px;padding:8px;text-align:left}.revision-list>button:hover{border-color:#9fc0f6}.revision-list span{font-size:10px}.revision-list small{color:#8792a4;font-size:9px}.revision-list>span{color:#929cad;line-height:1.5}.inspector h2{align-items:center;display:flex;gap:5px}.inspector h2 small{margin-left:auto}@media(max-width:700px){.lock-bar{align-items:flex-start;flex-wrap:wrap}.lock-bar small{flex-basis:100%;margin-left:0}}
.workspace-grid.visual-mode>.scene-sidebar{grid-column:1}.workspace-grid.visual-mode>.visual-workspace{grid-column:2}.workspace-grid.visual-mode>main:not(.visual-workspace){display:none}.workspace-grid.visual-mode>.inspector{grid-column:3}@media(max-width:1050px){.workspace-grid.visual-mode>.scene-sidebar,.workspace-grid.visual-mode>.visual-workspace,.workspace-grid.visual-mode>.inspector{grid-column:1}}
</style>
