<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { deleteProject, listProjects } from '../../api/projects'
import { cancelProjectTask } from '../../api/tasks'
import { confirmAction, showToast } from '../../services/feedback'
import type { Project } from '../../types/project'
import { formatDateTime, formatDuration } from '../../utils/time'

const projects = ref<Project[]>([])
const loading = ref(false)
const error = ref('')
const query = ref('')
const statusFilter = ref('all')
const actingProjectId = ref('')
const batchDeleting = ref(false)
const selectedProjectIds = ref<Set<string>>(new Set())
const message = ref('')
const clockNow = ref(Date.now())
const router = useRouter()
let clockTimer: number | undefined

const statusLabels: Record<string, string> = {
  created: '待开始',
  script_imported: '逐字稿已导入',
  segmented: '文本已分段',
  segmenting: '文本分段中',
  narration_in_progress: '配音生成中',
  tts: '配音生成中',
  tts_running: '配音生成中',
  tts_completed: '配音已生成',
  audio_merge: '音频合并中',
  audio_merged: '音频已合并',
  subtitles: '字幕生成中',
  narration_ready: '配音字幕已生成',
  video_in_progress: '视频生成中',
  video_composing: '视频合成中',
  rendering: '视频渲染中',
  video_completed: '视频已生成',
  review_required: '等待复核',
  completed: '已完成',
  failed: '生成失败',
  cancelled: '已停止',
}

const editableStatuses = new Set(['created', 'script_imported', 'segmented'])
const generatingStatuses = new Set([
  'narration_in_progress', 'video_in_progress', 'segmenting', 'tts', 'tts_running',
  'audio_merge', 'subtitles', 'rendering', 'video_composing',
])

const filteredProjects = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase()
  return projects.value.filter((project) => {
    const matchesQuery = !keyword || project.name.toLocaleLowerCase().includes(keyword)
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'generating' ? isGenerating(project) : project.status === statusFilter.value)
    return matchesQuery && matchesStatus
  })
})

const activeCount = computed(() => projects.value.filter((item) => isGenerating(item)).length)
const readyCount = computed(() => projects.value.filter((item) => ['narration_ready', 'review_required'].includes(item.status)).length)
const completedCount = computed(() => projects.value.filter((item) => item.status === 'completed').length)
const selectableProjects = computed(() => filteredProjects.value.filter((project) => !isGenerating(project)))
const selectedProjects = computed(() => projects.value.filter((project) => (
  selectedProjectIds.value.has(project.id) && !isGenerating(project)
)))
const allVisibleSelected = computed(() => (
  selectableProjects.value.length > 0
  && selectableProjects.value.every((project) => selectedProjectIds.value.has(project.id))
))
const someVisibleSelected = computed(() => (
  !allVisibleSelected.value
  && selectableProjects.value.some((project) => selectedProjectIds.value.has(project.id))
))

function statusLabel(status: string) {
  return statusLabels[status] || '待处理'
}

function statusTone(status: string) {
  if (status === 'failed') return 'is-danger'
  if (status === 'completed') return 'is-success'
  if (status === 'cancelled') return 'is-warning'
  if (generatingStatuses.has(status)) return 'is-running'
  if (status === 'review_required') return 'is-warning'
  return 'is-neutral'
}

function isEditable(project: Project) {
  return editableStatuses.has(project.status)
}

function isGenerating(project: Project) {
  return generatingStatuses.has(project.status)
}

function projectWorkflowDuration(project: Project) {
  if (project.workflow_started_at && !project.workflow_finished_at && project.latest_task_status === 'running') {
    const started = Date.parse(project.workflow_started_at)
    if (Number.isFinite(started)) return Math.max(0, (clockNow.value - started) / 1000)
  }
  return project.workflow_duration_seconds
}

function openProject(projectId: string) {
  void router.push(`/projects/${projectId}`)
}

function voiceProfileName(project: Project) {
  const profileName = project.config?.voice_profile_name
  if (typeof profileName === 'string' && profileName.trim()) return profileName
  const configuredName = project.config?.reference_audio_filename
  if (typeof configuredName === 'string' && configuredName.trim()) {
    return configuredName.replace(/\.[^.]+$/, '')
  }
  if (!project.reference_audio_path) return '未配置'
  const filename = project.reference_audio_path.split(/[\\/]/).pop() || '参考音频'
  return filename.replace(/\.[^.]+$/, '')
}

function ttsEngineName(project: Project) {
  const engine = typeof project.config?.tts_engine === 'string'
    ? project.config.tts_engine.toLocaleLowerCase()
    : ''
  return {
    qwen3_tts: 'Qwen3-TTS',
    chatterbox: 'Chatterbox',
    cosyvoice: 'CosyVoice',
  }[engine] || engine
}

function toggleProjectSelection(projectId: string) {
  const next = new Set(selectedProjectIds.value)
  if (next.has(projectId)) next.delete(projectId)
  else next.add(projectId)
  selectedProjectIds.value = next
}

function toggleAllVisible() {
  const next = new Set(selectedProjectIds.value)
  if (allVisibleSelected.value) {
    selectableProjects.value.forEach((project) => next.delete(project.id))
  } else {
    selectableProjects.value.forEach((project) => next.add(project.id))
  }
  selectedProjectIds.value = next
}

async function stopProject(project: Project) {
  const confirmed = await confirmAction({
    eyebrow: '停止生成任务',
    title: `强制停止“${project.name}”？`,
    description: '当前正在执行的生成进程会被终止，尚未完成的步骤将停止。',
    detail: '已经生成并保存的文件不会被删除，之后可重新发起生成。',
    confirmText: '确认停止',
    tone: 'warning',
  })
  if (!confirmed) return
  actingProjectId.value = project.id
  error.value = ''
  message.value = ''
  try {
    const result = await cancelProjectTask(project.id)
    message.value = result.cancelled ? `已向“${project.name}”发送停止指令` : '当前没有可停止的生成任务'
    showToast({
      title: result.cancelled ? '停止指令已发送' : '没有运行中的任务',
      description: result.cancelled ? `“${project.name}”正在安全停止。` : '项目当前无需停止。',
      tone: result.cancelled ? 'warning' : 'info',
    })
    await loadProjects()
  } catch (err) {
    error.value = err instanceof Error ? err.message : '项目停止失败'
    showToast({ title: '项目停止失败', description: error.value, tone: 'danger' })
  } finally {
    actingProjectId.value = ''
  }
}

async function removeProject(project: Project) {
  const confirmed = await confirmAction({
    eyebrow: '删除项目',
    title: `删除“${project.name}”？`,
    description: '项目将从工作台移除，当前配置、生成记录和输出文件将无法继续在这里访问。',
    detail: '项目记录和对应生成文件会被移入系统回收站。',
    confirmText: '移入回收站',
    tone: 'danger',
  })
  if (!confirmed) return
  actingProjectId.value = project.id
  try {
    await deleteProject(project.id)
    projects.value = projects.value.filter((item) => item.id !== project.id)
    const next = new Set(selectedProjectIds.value)
    next.delete(project.id)
    selectedProjectIds.value = next
    const refreshed = await loadProjects()
    showToast({
      title: refreshed ? '项目已移入回收站' : '项目已删除，列表同步失败',
      description: refreshed ? `“${project.name}”已从工作台移除。` : '请稍后手动刷新项目列表。',
      tone: refreshed ? 'success' : 'warning',
    })
  } catch (err) {
    showToast({
      title: '项目删除失败',
      description: err instanceof Error ? err.message : '请稍后重试。',
      tone: 'danger',
    })
  } finally {
    actingProjectId.value = ''
  }
}

async function removeSelectedProjects() {
  const targets = [...selectedProjects.value]
  if (!targets.length) return
  const confirmed = await confirmAction({
    eyebrow: '批量删除项目',
    title: `删除已选中的 ${targets.length} 个项目？`,
    description: '这些项目将从工作台中移除，删除过程开始后不能在本页撤销。',
    detail: '对应的项目记录和生成文件会被移入系统回收站。',
    confirmText: `删除 ${targets.length} 个项目`,
    tone: 'danger',
  })
  if (!confirmed) return

  batchDeleting.value = true
  const deletedIds = new Set<string>()
  const failed: string[] = []
  for (const project of targets) {
    actingProjectId.value = project.id
    try {
      await deleteProject(project.id)
      deletedIds.add(project.id)
    } catch (err) {
      const reason = err instanceof Error ? err.message : '删除失败'
      failed.push(`${project.name}：${reason}`)
    }
  }

  projects.value = projects.value.filter((project) => !deletedIds.has(project.id))
  selectedProjectIds.value = new Set(
    [...selectedProjectIds.value].filter((projectId) => !deletedIds.has(projectId)),
  )
  const refreshed = await loadProjects()
  if (failed.length || !refreshed) {
    showToast({
      title: `已删除 ${deletedIds.size} 个，${failed.length} 个未删除`,
      description: [failed.join('；'), refreshed ? '' : '项目列表同步失败'].filter(Boolean).join('；'),
      tone: 'warning',
      duration: 6000,
    })
  } else {
    showToast({
      title: `已删除 ${deletedIds.size} 个项目`,
      description: '项目列表已刷新，相关文件已移入系统回收站。',
      tone: 'success',
    })
  }
  actingProjectId.value = ''
  batchDeleting.value = false
}

async function loadProjects() {
  loading.value = true
  error.value = ''
  try {
    projects.value = await listProjects()
    const availableIds = new Set(
      projects.value.filter((project) => !isGenerating(project)).map((project) => project.id),
    )
    selectedProjectIds.value = new Set(
      [...selectedProjectIds.value].filter((projectId) => availableIds.has(projectId)),
    )
    return true
  } catch (err) {
    error.value = err instanceof Error ? err.message : '项目列表加载失败'
    return false
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void loadProjects()
  clockTimer = window.setInterval(() => {
    clockNow.value = Date.now()
  }, 1000)
})

onBeforeUnmount(() => {
  if (clockTimer !== undefined) window.clearInterval(clockTimer)
})
</script>

<template>
  <section>
    <div class="page-title dashboard-title">
      <h1>项目工作台</h1>
      <RouterLink class="primary-link hero-action" to="/projects/new"><span>＋</span> 创建新项目</RouterLink>
    </div>

    <div class="metric-grid" aria-label="项目概览">
      <article class="metric-card">
        <span class="metric-label">全部项目</span>
        <strong>{{ projects.length }}</strong>
        <small>当前工作空间</small>
      </article>
      <article class="metric-card accent-card">
        <span class="metric-label">正在生产</span>
        <strong>{{ activeCount }}</strong>
        <small>任务正在后台执行</small>
      </article>
      <article class="metric-card">
        <span class="metric-label">等待处理</span>
        <strong>{{ readyCount }}</strong>
        <small>可继续合成或复核</small>
      </article>
      <article class="metric-card">
        <span class="metric-label">已完成</span>
        <strong>{{ completedCount }}</strong>
        <small>已输出最终文件</small>
      </article>
    </div>

    <div class="section-toolbar">
      <div>
        <h2>最近项目</h2>
        <p>继续未完成的制作，或查看已经生成的文件。</p>
      </div>
      <div class="toolbar-controls">
        <label class="search-field">
          <span>⌕</span>
          <input v-model="query" type="search" placeholder="搜索项目名称" aria-label="搜索项目名称" />
        </label>
        <select v-model="statusFilter" class="filter-select" aria-label="按状态筛选">
          <option value="all">全部状态</option>
          <option value="created">待开始</option>
          <option value="generating">生成中</option>
          <option value="narration_ready">配音已就绪</option>
          <option value="review_required">等待复核</option>
          <option value="completed">已完成</option>
          <option value="failed">执行失败</option>
        </select>
      </div>
    </div>

    <div v-if="filteredProjects.length" class="project-bulk-toolbar">
      <label class="project-bulk-select">
        <input
          type="checkbox"
          :checked="allVisibleSelected"
          :indeterminate="someVisibleSelected"
          :disabled="batchDeleting || !selectableProjects.length"
          @change="toggleAllVisible"
        />
        <span>全选当前可删除项目</span>
      </label>
      <span class="muted">已选 {{ selectedProjects.length }} 项</span>
      <button
        class="danger-button"
        type="button"
        :disabled="batchDeleting || !selectedProjects.length"
        @click="removeSelectedProjects"
      >
        {{ batchDeleting ? '批量删除中…' : '删除已选' }}
      </button>
    </div>

    <div v-if="error" class="alert alert-danger"><strong>操作失败</strong><span>{{ error }}</span></div>
    <div v-if="message" class="alert alert-success"><strong>操作完成</strong><span>{{ message }}</span></div>
    <div v-if="loading" class="project-grid" aria-label="正在加载">
      <div v-for="index in 3" :key="index" class="project-card skeleton-card"></div>
    </div>
    <div v-else-if="!projects.length" class="empty-state panel">
      <span class="empty-icon">＋</span>
      <h2>从第一个项目开始</h2>
      <p>准备一段逐字稿并选择系统音色，即可创建配音、字幕并合成视频。</p>
      <RouterLink class="primary-link" to="/projects/new">创建项目</RouterLink>
    </div>
    <div v-else-if="!filteredProjects.length" class="empty-state panel compact-empty">
      <h2>没有匹配的项目</h2>
      <p>试试调整搜索词或状态筛选。</p>
      <button class="secondary-button" @click="query = ''; statusFilter = 'all'">清除筛选</button>
    </div>
    <div v-else class="project-grid">
      <article
        v-for="project in filteredProjects"
        :key="project.id"
        class="project-card"
        :class="{ 'is-selected': selectedProjectIds.has(project.id) }"
        role="link"
        tabindex="0"
        :aria-label="`进入项目 ${project.name}`"
        @click="openProject(project.id)"
        @keydown.enter.self="openProject(project.id)"
        @keydown.space.self.prevent="openProject(project.id)"
      >
        <div class="project-card-top">
          <div class="project-card-leading">
            <input
              type="checkbox"
              :checked="selectedProjectIds.has(project.id)"
              :disabled="isGenerating(project) || batchDeleting"
              :aria-label="isGenerating(project) ? `${project.name} 生成中，不能删除` : `选择 ${project.name}`"
              @click.stop
              @change="toggleProjectSelection(project.id)"
            />
            <span class="project-avatar">{{ project.name.slice(0, 1).toUpperCase() }}</span>
            <h3 :title="project.name">{{ project.name }}</h3>
          </div>
          <span class="status-pill" :class="statusTone(project.status)"><i></i>{{ statusLabel(project.status) }}</span>
        </div>
        <div class="project-card-body">
          <p class="project-reference-audio" :title="`${voiceProfileName(project)} ${ttsEngineName(project)}`">
            <span>参考音频</span>
            <strong>{{ voiceProfileName(project) }}</strong>
            <span v-if="ttsEngineName(project)" class="project-engine">{{ ttsEngineName(project) }}</span>
          </p>
          <div class="project-runtime-metrics">
            <span><small>音频时长</small><strong>{{ formatDuration(project.audio_duration_seconds || null, '未生成') }}</strong></span>
            <span><small>流程用时</small><strong>{{ formatDuration(projectWorkflowDuration(project), project.workflow_started_at ? '计算中' : '未开始') }}</strong></span>
          </div>
        </div>
        <div class="project-card-footer">
          <div class="project-card-times">
            <span>创建于 {{ formatDateTime(project.created_at) }}</span>
            <span>实际开始于 {{ formatDateTime(project.workflow_started_at, '尚未开始') }}</span>
          </div>
          <div class="project-card-actions">
            <RouterLink v-if="isEditable(project)" class="text-button" :to="`/projects/${project.id}/config`" @click.stop>修改</RouterLink>
            <button
              v-if="isGenerating(project)"
              class="danger-button"
              type="button"
              :disabled="batchDeleting || actingProjectId === project.id"
              @click.stop="stopProject(project)"
            >
              {{ actingProjectId === project.id ? '停止中…' : '强制停止' }}
            </button>
            <button
              v-else
              class="danger-button"
              type="button"
              :disabled="batchDeleting || actingProjectId === project.id"
              @click.stop="removeProject(project)"
            >
              {{ actingProjectId === project.id ? '删除中…' : '删除' }}
            </button>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>
