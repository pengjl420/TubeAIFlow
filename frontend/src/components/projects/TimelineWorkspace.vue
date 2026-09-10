<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { CirclePause, Loader2, Play, Save } from 'lucide-vue-next'
import {
  cancelProjectJob, enqueueFinalRenderJob, enqueueScenePreviewJob, enqueueTimelinePreviewJob,
  getProjectJob, getTimelineEditor,
  pauseProjectJob, projectOutputUrl, resumeProjectJob, updateTimelineClip,
  type ProjectTask, type TimelineClip, type TimelineData,
} from '../../api/projects'
import type { VisualScene } from '../../types/storyboard'
import { showToast } from '../../services/feedback'

const props = defineProps<{ projectId: string; scene: VisualScene }>()
const timeline = ref<TimelineData | null>(null)
const selectedId = ref('')
const draft = ref<TimelineClip | null>(null)
const saving = ref(false)
const previewPath = ref('')
const job = ref<ProjectTask | null>(null)
const previewStartSeconds = ref(Math.floor(props.scene.start_ms / 1000))
const previewDuration = ref<30000 | 60000>(30000)
const visualTrack = computed(() => timeline.value?.tracks.find(track => track.id === 'visual'))
const selectedSceneClips = computed(() => visualTrack.value?.clips.filter(clip => clip.scene_id === props.scene.id) || [])
const dirty = computed(() => {
  const current = visualTrack.value?.clips.find(clip => clip.id === selectedId.value)
  return Boolean(current && draft.value && JSON.stringify(current) !== JSON.stringify(draft.value))
})

function select(clip: TimelineClip) {
  selectedId.value = clip.id
  draft.value = JSON.parse(JSON.stringify(clip)) as TimelineClip
}

async function load() {
  try {
    timeline.value = await getTimelineEditor(props.projectId)
    const clip = selectedSceneClips.value.find(item => item.id === selectedId.value) || selectedSceneClips.value[0]
    if (clip) select(clip)
    else { selectedId.value = ''; draft.value = null }
  } catch (reason) { showToast({ title: '加载 Timeline 失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
}

async function save() {
  if (!draft.value) return
  saving.value = true
  try {
    timeline.value = await updateTimelineClip(props.projectId, draft.value.id, {
      sequence_index: draft.value.sequence_index,
      display_duration_ms: draft.value.display_duration_ms,
      playback_speed: draft.value.playback_speed,
      motion_type: draft.value.motion_type,
      zoom_start: draft.value.zoom_start,
      zoom_end: draft.value.zoom_end,
      pan_direction: draft.value.pan_direction,
      crop_anchor: draft.value.crop_anchor,
      transition: draft.value.transition,
    })
    const updated = visualTrack.value?.clips.find(clip => clip.id === draft.value?.id)
    if (updated) select(updated)
    showToast({ title: 'Timeline Clip 已保存', description: '当前 Scene 和下游合成已标记为需要重新渲染。', tone: 'success' })
  } catch (reason) { showToast({ title: '保存 Timeline 失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
  finally { saving.value = false }
}

function wait(milliseconds: number) {
  return new Promise(resolve => window.setTimeout(resolve, milliseconds))
}

async function waitForJob(initial: ProjectTask): Promise<ProjectTask> {
  let current = initial
  job.value = current
  while (current.id && ['queued', 'running'].includes(current.status)) {
    await wait(1000)
    current = await getProjectJob(props.projectId, current.id)
    job.value = current
  }
  if (current.status === 'failed') throw new Error(current.error_message || 'Scene Preview Job 执行失败')
  return current
}

async function renderPreview() {
  try {
    const result = await waitForJob(await enqueueScenePreviewJob(props.projectId, props.scene.id))
    previewPath.value = String(result.result?.path || '')
  } catch (reason) { showToast({ title: 'Scene Preview 失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
}

async function renderRangePreview() {
  try {
    const result = await waitForJob(await enqueueTimelinePreviewJob(
      props.projectId,
      Math.max(0, Math.round(previewStartSeconds.value * 1000)),
      previewDuration.value,
    ))
    previewPath.value = String(result.result?.path || '')
  } catch (reason) { showToast({ title: '范围预览失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
}

async function renderFinal() {
  try {
    const result = await waitForJob(await enqueueFinalRenderJob(props.projectId))
    previewPath.value = String(result.result?.path || '')
    showToast({ title: '最终视频已生成', description: '已完成视觉轨、主音频和字幕烧录。', tone: 'success' })
  } catch (reason) { showToast({ title: '最终渲染失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
}

async function pauseJob() {
  if (job.value?.id) job.value = await pauseProjectJob(props.projectId, job.value.id)
}

async function resumeJob() {
  if (!job.value?.id) return
  try {
    const result = await waitForJob(await resumeProjectJob(props.projectId, job.value.id))
    previewPath.value = String(result.result?.path || '')
  } catch (reason) { showToast({ title: '恢复 Preview Job 失败', description: reason instanceof Error ? reason.message : String(reason), tone: 'danger' }) }
}

async function cancelJob() {
  if (job.value?.id) job.value = await cancelProjectJob(props.projectId, job.value.id)
}

function width(clip: TimelineClip) {
  return `${Math.max(3, (clip.end_ms - clip.start_ms) / Math.max(1, timeline.value?.duration_ms || 1) * 100)}%`
}

function left(clip: TimelineClip) {
  return `${clip.start_ms / Math.max(1, timeline.value?.duration_ms || 1) * 100}%`
}

watch(() => props.scene.id, () => { previewPath.value = ''; job.value = null; previewStartSeconds.value = Math.floor(props.scene.start_ms / 1000); load() })
onMounted(load)
</script>

<template>
  <main class="visual-workspace timeline-workspace">
    <header><div><h1>Timeline V1</h1><p>{{ timeline ? `${(timeline.duration_ms / 1000).toFixed(1)} 秒 · ${timeline.fps} FPS · 3 条基础轨道` : '加载中…' }}</p></div><button :disabled="saving || !dirty || scene.locked_visual" @click="save"><Save :size="13" />{{ saving ? '保存中…' : '保存 Clip' }}</button></header>
    <section v-if="timeline" class="tracks"><article v-for="track in timeline.tracks" :key="track.id"><strong>{{ track.id }}</strong><div style="min-height:32px;position:relative"><button v-for="clip in track.clips" :key="clip.id" :class="[{ selected: clip.id === selectedId }, `clip-${track.type}`]" :style="{ height: '32px', left: left(clip), position: 'absolute', width: width(clip) }" :title="clip.text || clip.asset_path || clip.id" @click="track.id === 'visual' && select(clip)">{{ clip.scene_index ? `S${clip.scene_index}` : clip.text || '' }}</button></div></article></section>
    <section class="preview-panel"><div><strong>Render</strong><small>Scene 预览、30/60 秒草稿或最终成片都通过可恢复 Job 执行。</small></div><label><span>起点（秒）</span><input v-model.number="previewStartSeconds" type="number" min="0" /></label><label><span>范围</span><select v-model.number="previewDuration"><option :value="30000">30 秒</option><option :value="60000">60 秒</option></select></label><button :disabled="!selectedSceneClips.length || ['queued', 'running'].includes(job?.status || '')" @click="renderPreview"><Play :size="13" />Scene</button><button :disabled="['queued', 'running'].includes(job?.status || '')" @click="renderRangePreview">范围预览</button><button class="final" :disabled="['queued', 'running'].includes(job?.status || '')" @click="renderFinal">最终渲染</button></section>
    <div v-if="job && ['queued', 'running', 'paused'].includes(job.status)" class="preview-job"><Loader2 v-if="job.status !== 'paused'" class="spin" :size="14" /><CirclePause v-else :size="14" /><span>{{ job.status }} · {{ job.stage }}</span><b>{{ Math.round(job.progress || 0) }}%</b><button v-if="job.status === 'paused'" @click="resumeJob">继续</button><button v-else @click="pauseJob">暂停</button><button class="cancel" @click="cancelJob">取消</button></div>
    <video v-if="previewPath" controls :src="projectOutputUrl(projectId, previewPath)" />
    <section v-if="draft" class="clip-editor"><div><h2>Scene {{ draft.scene_index }} · Clip {{ draft.sequence_index }}</h2><small>{{ (draft.start_ms / 1000).toFixed(2) }}–{{ (draft.end_ms / 1000).toFixed(2) }} 秒</small></div><label><span>顺序</span><input v-model.number="draft.sequence_index" type="number" min="1" /></label><label><span>显示时长 ms</span><input v-model.number="draft.display_duration_ms" type="number" min="34" /></label><label><span>播放速度</span><input v-model.number="draft.playback_speed" type="number" min="0.25" max="4" step="0.05" /></label><label><span>Motion</span><select v-model="draft.motion_type"><option value="auto">Auto</option><option value="static">Static</option><option value="slow_zoom_in">Zoom In</option><option value="slow_zoom_out">Zoom Out</option><option value="pan_left_to_right">Pan Right</option><option value="pan_right_to_left">Pan Left</option></select></label><label><span>Zoom Start</span><input v-model.number="draft.zoom_start" type="number" min="1" max="2" step="0.01" /></label><label><span>Zoom End</span><input v-model.number="draft.zoom_end" type="number" min="1" max="2" step="0.01" /></label><label><span>裁切锚点</span><select v-model="draft.crop_anchor"><option value="center">Center</option><option value="left">Left</option><option value="right">Right</option><option value="top">Top</option><option value="bottom">Bottom</option></select></label><label><span>Transition</span><select v-model="draft.transition"><option value="cut">Cut</option><option value="crossfade">Crossfade</option><option value="fade">Fade</option><option value="dip_to_black">Dip to Black</option></select></label></section>
    <div v-else class="empty">当前 Scene 尚未分配视觉 Clip。</div>
  </main>
</template>

<style scoped>
.timeline-workspace{min-width:0}.timeline-workspace>header{align-items:flex-start;display:flex;justify-content:space-between}.timeline-workspace h1{font-size:18px;margin:0}.timeline-workspace header p{color:#7f8a9d;font-size:11px;margin:5px 0}.timeline-workspace button{background:#075bf5;border-radius:7px;color:#fff;font-size:11px;padding:8px 10px}.timeline-workspace button:disabled{opacity:.5}.tracks{background:#f7f9fc;border:1px solid #e1e7ef;border-radius:9px;display:grid;gap:7px;margin:14px 0;padding:10px}.tracks article{align-items:center;display:grid;gap:8px;grid-template-columns:70px 1fr}.tracks article>strong{color:#67748a;font-size:10px}.tracks article>div{display:flex;min-height:32px}.tracks article button{border:2px solid #f7f9fc;border-radius:5px;min-width:24px;overflow:hidden;padding:5px;text-overflow:ellipsis;white-space:nowrap}.tracks .clip-video{background:#3f7ee8}.tracks .clip-audio{background:#18a275}.tracks .clip-subtitle{background:#8a67d5}.tracks article button.selected{border-color:#172033}.clip-editor{border-top:1px solid #e5eaf1;display:grid;gap:10px;grid-template-columns:repeat(4,1fr);padding-top:14px}.clip-editor>div{grid-column:1/-1}.clip-editor h2{font-size:14px;margin:0}.clip-editor small{color:#8490a3}.clip-editor label{display:grid;gap:4px}.clip-editor label span{color:#667389;font-size:10px;font-weight:700}.clip-editor input,.clip-editor select{border:1px solid #dce3ec;border-radius:6px;min-height:36px;padding:6px;width:100%}.empty{align-items:center;color:#8a95a6;display:flex;justify-content:center;min-height:260px}@media(max-width:800px){.clip-editor{grid-template-columns:repeat(2,1fr)}}
</style>

<style scoped>
.preview-panel label{display:grid;gap:2px}.preview-panel label span{color:#6d788b;font-size:9px}.preview-panel input,.preview-panel select{background:#fff;border:1px solid #dbe2ec;border-radius:5px;font-size:10px;height:30px;padding:4px 6px;width:82px}.preview-panel .final{background:#0a9567}@media(max-width:900px){.preview-panel{align-items:stretch;display:grid;gap:7px;grid-template-columns:1fr 1fr}.preview-panel>div{grid-column:1/-1}}
</style>

<style scoped>
.preview-panel{align-items:center;background:#f4f7fb;border-radius:8px;display:flex;justify-content:space-between;margin:12px 0;padding:9px 11px}.preview-panel div{display:grid;gap:2px}.preview-panel strong{font-size:11px}.preview-panel small{color:#7d899b;font-size:10px}.preview-job{align-items:center;background:#172033;border-radius:8px;color:#fff;display:flex;font-size:10px;gap:7px;margin-bottom:10px;padding:8px 10px}.preview-job span{flex:1}.preview-job button{background:#fff;color:#26354d;padding:5px 8px}.preview-job .cancel{background:#d94956;color:#fff}.timeline-workspace video{background:#111;border-radius:8px;margin-bottom:12px;max-height:320px;width:100%}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
</style>
