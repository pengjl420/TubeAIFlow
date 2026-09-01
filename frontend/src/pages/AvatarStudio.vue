<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { CheckCircle2, CircleUserRound, Clock3, Film, Loader2, Upload, XCircle } from 'lucide-vue-next'

import {
  avatarOutputUrl,
  avatarVideoUrl,
  createAvatarProfile,
  createAvatarTask,
  healthCheckDuix,
  listAvatarProfiles,
  listAvatarTasks,
  retryAvatarTask,
  type AvatarProfile,
  type AvatarTask,
} from '../api/avatars'

const profiles = ref<AvatarProfile[]>([])
const tasks = ref<AvatarTask[]>([])
const selectedProfileId = ref('')
const profileName = ref('')
const profileVideo = ref<File | null>(null)
const audioFile = ref<File | null>(null)
const outputFilename = ref('数字人成片.mp4')
const chunkSeconds = ref(420)
const contextMs = ref(800)
const creatingProfile = ref(false)
const submitting = ref(false)
const loading = ref(false)
const error = ref('')
const retryingTaskId = ref('')
const duixAvailable = ref<boolean | null>(null)
let timer: number | undefined

const selectedProfile = computed(() => profiles.value.find((item) => item.id === selectedProfileId.value))
const canSubmit = computed(() => Boolean(selectedProfileId.value && audioFile.value && outputFilename.value.trim()))
const hasActiveTasks = computed(() => tasks.value.some(item => item.status === 'queued' || item.status === 'running'))

function selectFile(event: Event, target: 'profile' | 'audio') {
  const file = (event.target as HTMLInputElement).files?.[0] || null
  if (target === 'profile') profileVideo.value = file
  else audioFile.value = file
}

async function load(silent = false) {
  if (!silent) loading.value = true
  try {
    const [profileData, taskData, health] = await Promise.all([
      listAvatarProfiles(),
      listAvatarTasks(),
      healthCheckDuix(),
    ])
    profiles.value = profileData
    tasks.value = taskData
    duixAvailable.value = health.available
    if (!selectedProfileId.value && profileData.length) selectedProfileId.value = profileData[0].id
  } catch (reason) {
    if (!silent) error.value = reason instanceof Error ? reason.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function addProfile() {
  if (!profileName.value.trim() || !profileVideo.value) return
  creatingProfile.value = true
  error.value = ''
  try {
    const profile = await createAvatarProfile(profileName.value, profileVideo.value)
    profiles.value.unshift(profile)
    selectedProfileId.value = profile.id
    profileName.value = ''
    profileVideo.value = null
    const input = document.querySelector<HTMLInputElement>('#avatar-profile-video')
    if (input) input.value = ''
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '人物形象创建失败'
  } finally {
    creatingProfile.value = false
  }
}

async function submit() {
  if (!audioFile.value || !canSubmit.value) return
  submitting.value = true
  error.value = ''
  try {
    const task = await createAvatarTask(
      selectedProfileId.value,
      audioFile.value,
      outputFilename.value,
      chunkSeconds.value,
      contextMs.value,
    )
    tasks.value.unshift(task)
    audioFile.value = null
    const input = document.querySelector<HTMLInputElement>('#avatar-audio')
    if (input) input.value = ''
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '数字人任务提交失败'
  } finally {
    submitting.value = false
  }
}

function formatDuration(milliseconds: number | null) {
  if (!milliseconds) return '—'
  const total = Math.round(milliseconds / 1000)
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
}

function statusLabel(task: AvatarTask) {
  if (task.status === 'queued') return task.queue_position ? `排队第 ${task.queue_position} 位` : '排队中'
  if (task.status === 'running') return `生成第 ${task.current_chunk || 1}/${task.total_chunks || '…'} 段`
  if (task.status === 'completed') return '已完成'
  return '生成失败'
}

async function retryTask(task: AvatarTask) {
  retryingTaskId.value = task.id
  error.value = ''
  try {
    const updated = await retryAvatarTask(task.id)
    const index = tasks.value.findIndex((item) => item.id === task.id)
    if (index >= 0) tasks.value[index] = updated
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '重试任务失败'
  } finally {
    retryingTaskId.value = ''
  }
}

onMounted(async () => {
  await load()
  timer = window.setInterval(() => { if (!document.hidden && hasActiveTasks.value) void load(true) }, 3000)
})
onBeforeUnmount(() => {
  if (timer !== undefined) window.clearInterval(timer)
})
</script>

<template>
  <section class="avatar-page">
    <header class="taf-page-heading">
      <div><h1>数字人合成</h1><p>直接使用完整旁白音频驱动 Duix，不执行 TTS；长音频按 5–10 分钟章节生成并合成为一个视频。</p></div>
      <span v-if="duixAvailable" class="health ok"><i></i>Duix 服务正常</span>
      <RouterLink v-else class="health bad" to="/settings/diagnostics" title="前往系统诊断"><i></i>Duix 服务不可用 · 检查配置</RouterLink>
    </header>

    <p v-if="error" class="avatar-error">{{ error }}</p>

    <div class="avatar-grid">
      <article class="avatar-card">
        <header><CircleUserRound :size="21" /><div><h2>1. 选择参考人物形象</h2><p>选择已保存模板，或上传一个新的 Duix 人物模板视频。</p></div></header>
        <div v-if="profiles.length" class="profile-list">
          <label v-for="profile in profiles" :key="profile.id" :class="{ selected: selectedProfileId === profile.id }">
            <input v-model="selectedProfileId" type="radio" :value="profile.id" />
            <video :src="avatarVideoUrl(profile.id)" muted preload="metadata"></video>
            <span><strong>{{ profile.name }}</strong><small>{{ profile.width }}×{{ profile.height }} · {{ formatDuration(profile.duration_ms) }}</small></span>
            <CheckCircle2 v-if="selectedProfileId === profile.id" :size="18" />
          </label>
        </div>
        <div v-else class="empty">还没有人物形象，请先上传模板视频。</div>
        <div class="new-profile">
          <input v-model="profileName" aria-label="人物形象名称" placeholder="人物形象名称" />
          <label class="file-button"><Upload :size="16" />{{ profileVideo?.name || '选择模板视频' }}<input id="avatar-profile-video" type="file" accept="video/*" aria-label="选择人物模板视频" @change="selectFile($event, 'profile')" /></label>
          <button :disabled="creatingProfile || !profileName.trim() || !profileVideo" @click="addProfile">{{ creatingProfile ? '正在保存…' : '保存人物形象' }}</button>
        </div>
      </article>

      <article class="avatar-card">
        <header><Film :size="21" /><div><h2>2. 提交完整音频</h2><p>支持 30–50 分钟成品旁白；最终视频始终使用该文件作为唯一音轨。</p></div></header>
        <label class="upload-zone">
          <Upload :size="25" />
          <strong>{{ audioFile?.name || '选择完整音频文件' }}</strong>
          <small>WAV、MP3、M4A、AAC、FLAC 或 OGG</small>
          <input id="avatar-audio" type="file" accept="audio/*,.wav,.mp3,.m4a,.aac,.flac,.ogg" aria-label="选择数字人音频文件" @change="selectFile($event, 'audio')" />
        </label>
        <div class="task-fields three">
          <label><span>输出文件名</span><input v-model="outputFilename" aria-label="数字人视频输出文件名" /></label>
          <label><span>章节目标时长</span><select v-model.number="chunkSeconds"><option :value="300">5 分钟</option><option :value="420">7 分钟（推荐）</option><option :value="480">8 分钟</option><option :value="600">10 分钟</option></select></label>
          <label><span>口型预滚</span><select v-model.number="contextMs"><option :value="400">400 ms</option><option :value="600">600 ms（推荐）</option><option :value="800">800 ms</option><option :value="1000">1000 ms</option></select></label>
        </div>
        <div class="summary"><span>人物形象</span><strong>{{ selectedProfile?.name || '尚未选择' }}</strong><span>音频</span><strong>{{ audioFile?.name || '尚未选择' }}</strong></div>
        <button class="submit" :disabled="!canSubmit || submitting || duixAvailable === false" @click="submit"><Loader2 v-if="submitting" class="spin" :size="18" /><Film v-else :size="18" />{{ submitting ? '正在上传…' : '提交数字人任务' }}</button>
      </article>
    </div>

    <article class="avatar-card task-card">
      <header><Clock3 :size="21" /><div><h2>生成任务</h2><p>任务按顺序串行使用 GPU，页面关闭后仍会继续。</p></div><button @click="load()">刷新</button></header>
      <div v-if="!tasks.length && !loading" class="empty">尚未提交数字人任务。</div>
      <div v-for="task in tasks" :key="task.id" class="task-row">
        <span class="task-icon" :class="task.status"><Loader2 v-if="task.status === 'running'" class="spin" :size="19" /><CheckCircle2 v-else-if="task.status === 'completed'" :size="19" /><XCircle v-else-if="task.status === 'failed'" :size="19" /><Clock3 v-else :size="19" /></span>
        <div class="task-info"><strong>{{ task.output_filename }}</strong><small>{{ formatDuration(task.audio_duration_ms) }} · 章节目标 {{ Math.round(task.chunk_seconds / 60) }} 分钟 · 预滚 {{ task.context_ms }}ms · {{ task.completed_chunks }}/{{ task.total_chunks || '…' }} 段</small><small v-if="task.continuity_report">接缝检查 {{ task.continuity_report.seam_count }} 处，需复核 {{ task.continuity_report.warning_count }} 处</small><p v-if="task.error_message">{{ task.error_message }}</p><div class="bar"><i :style="{ width: `${task.progress || 0}%` }"></i></div></div>
        <div class="task-state"><b :class="task.status">{{ statusLabel(task) }}</b><span>{{ Math.round(task.progress || 0) }}%</span><button v-if="task.status === 'failed'" :disabled="retryingTaskId === task.id" @click="retryTask(task)">{{ retryingTaskId === task.id ? '恢复中…' : '继续任务' }}</button><a v-if="task.status === 'completed'" :href="avatarOutputUrl(task.id, true)">下载视频</a></div>
      </div>
    </article>
  </section>
</template>

<style scoped>
.avatar-page{color:#172033}.health{align-items:center;background:#fff0f1;border:1px solid #ffd1d5;border-radius:999px;color:#c83b47;display:flex;font-size:12px;font-weight:750;gap:7px;padding:8px 13px}.health.ok{background:#e9f8f2;border-color:#c5efdf;color:#078b60}.health i{background:currentColor;border-radius:50%;height:7px;width:7px}.avatar-error{background:#fff0f1;border:1px solid #ffd5d8;border-radius:8px;color:#c63845;padding:10px 13px}.avatar-grid{align-items:start;display:grid;gap:16px;grid-template-columns:1fr 1fr}.avatar-card{background:#fff;border:1px solid #e1e7ef;border-radius:13px;box-shadow:0 5px 22px #34435f0a;padding:20px}.avatar-card>header{align-items:center;border-bottom:1px solid #edf0f4;display:flex;gap:11px;margin-bottom:17px;padding-bottom:14px}.avatar-card>header>svg{background:#eaf2ff;border-radius:9px;color:#0864eb;box-sizing:content-box;padding:9px}.avatar-card h2{font-size:17px;margin:0}.avatar-card header p{color:#7b8799;font-size:12px;margin:4px 0 0}.profile-list{display:grid;gap:9px;max-height:300px;overflow:auto}.profile-list label{align-items:center;border:1px solid #e3e8ef;border-radius:9px;cursor:pointer;display:grid;gap:10px;grid-template-columns:auto 74px 1fr auto;padding:8px}.profile-list label.selected{background:#f5f9ff;border-color:#75a7fa}.profile-list input{display:none}.profile-list video{background:#111;border-radius:6px;height:50px;object-fit:cover;width:74px}.profile-list span{display:grid;gap:4px}.profile-list small{color:#8390a2;font-size:11px}.profile-list svg{color:#0872e5}.new-profile{border-top:1px solid #edf0f4;display:grid;gap:9px;grid-template-columns:1fr 1fr auto;margin-top:14px;padding-top:14px}.new-profile input,.task-fields input,.task-fields select{border:1px solid #dce3ec;border-radius:8px;min-height:41px;padding:8px 11px}.new-profile button,.submit,.task-card header button{background:#0864eb;border:0;border-radius:8px;color:#fff;font-weight:700;padding:0 14px}.new-profile button:disabled,.submit:disabled{opacity:.5}.file-button{align-items:center;border:1px dashed #aebdd1;border-radius:8px;color:#53647b;display:flex;font-size:12px;gap:7px;justify-content:center;overflow:hidden;padding:8px}.file-button input,.upload-zone input{display:none}.upload-zone{align-items:center;background:#f8faff;border:1px dashed #aebfda;border-radius:10px;color:#62738b;cursor:pointer;display:flex;flex-direction:column;gap:6px;justify-content:center;min-height:128px}.upload-zone strong{color:#273449}.upload-zone small{font-size:11px}.task-fields{display:grid;gap:12px;grid-template-columns:1fr 1fr;margin-top:14px}.task-fields label{display:grid;gap:6px}.task-fields span{font-size:12px;font-weight:700}.summary{background:#f8faff;border-radius:8px;display:grid;font-size:12px;gap:5px;grid-template-columns:80px 1fr;margin-top:14px;padding:11px}.summary span{color:#8490a2}.submit{align-items:center;display:flex;gap:7px;justify-content:center;margin-top:14px;min-height:45px;width:100%}.task-card{margin-top:16px}.task-card>header button{margin-left:auto;min-height:36px}.task-row{align-items:center;border-top:1px solid #edf0f4;display:grid;gap:12px;grid-template-columns:auto 1fr auto;padding:13px 2px}.task-icon{align-items:center;background:#f1edff;border-radius:50%;color:#7153ce;display:flex;height:38px;justify-content:center;width:38px}.task-icon.running{background:#eaf2ff;color:#0864eb}.task-icon.completed{background:#e7f8f1;color:#078b60}.task-icon.failed{background:#fff0f1;color:#c83b47}.task-info{display:grid;gap:4px}.task-info small{color:#7d899b;font-size:11px}.task-info p{color:#c83b47;font-size:11px;margin:0}.bar{background:#e8edf4;border-radius:10px;height:5px;margin-top:4px;overflow:hidden}.bar i{background:#0864eb;display:block;height:100%}.task-state{display:grid;gap:4px;text-align:right}.task-state b{color:#7153ce;font-size:12px}.task-state b.running{color:#0864eb}.task-state b.completed{color:#078b60}.task-state b.failed{color:#c83b47}.task-state span{color:#8490a2;font-size:11px}.task-state a{color:#0864eb;font-size:12px;font-weight:700}.empty{color:#8490a2;padding:24px;text-align:center}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:1050px){.avatar-grid{grid-template-columns:1fr}}@media(max-width:680px){.new-profile,.task-fields{grid-template-columns:1fr}.task-row{grid-template-columns:auto 1fr}.task-state{grid-column:2;text-align:left}}
.task-fields.three{grid-template-columns:1.2fr .8fr .8fr}@media(max-width:680px){.task-fields.three{grid-template-columns:1fr}}
.task-state button{background:none;border:0;color:#0864eb;font-size:11px;font-weight:700;padding:0}.task-state button:disabled{opacity:.5}
</style>
