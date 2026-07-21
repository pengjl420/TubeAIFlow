<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import { getProject } from '../../api/projects'
import {
  generateStoryboard,
  getStoryboard,
  importProjectSrt,
  listSubtitleCues,
  updateStoryboardScene,
} from '../../api/storyboard'
import type { Project } from '../../types/project'
import type { StoryboardContent, SubtitleCue, VisualScene } from '../../types/storyboard'

interface StoryboardDraft {
  visual_summary: string
  primary_query: string
  scene_category: string
  mood: string
  alternative_queries: string
  must_include: string
  avoid: string
}

const route = useRoute()
const projectId = String(route.params.id)
const project = ref<Project | null>(null)
const cues = ref<SubtitleCue[]>([])
const scenes = ref<VisualScene[]>([])
const drafts = reactive<Record<string, StoryboardDraft>>({})
const srtContent = ref('')
const selectedFilename = ref('')
const warnings = ref<string[]>([])
const modelName = ref('')
const loading = ref(false)
const importing = ref(false)
const generating = ref(false)
const savingSceneId = ref('')
const error = ref('')
const message = ref('')

const timelineDuration = computed(() => {
  if (!cues.value.length) return 0
  return Math.max(0, cues.value[cues.value.length - 1].end_ms - cues.value[0].start_ms)
})

function formatTime(milliseconds: number) {
  const totalSeconds = Math.floor(milliseconds / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  const ms = milliseconds % 1000
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}.${String(ms).padStart(3, '0')}`
}

function joinLines(values: string[]) {
  return values.join('\n')
}

function parseLines(value: string) {
  const seen = new Set<string>()
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter((item) => {
      const key = item.toLocaleLowerCase()
      if (!item || seen.has(key)) return false
      seen.add(key)
      return true
    })
}

function setDraft(scene: VisualScene) {
  if (!scene.storyboard) return
  drafts[scene.id] = {
    visual_summary: scene.storyboard.visual_summary,
    primary_query: scene.storyboard.primary_query,
    scene_category: scene.storyboard.scene_category,
    mood: scene.storyboard.mood,
    alternative_queries: joinLines(scene.storyboard.alternative_queries),
    must_include: joinLines(scene.storyboard.must_include),
    avoid: joinLines(scene.storyboard.avoid),
  }
}

function replaceScenes(values: VisualScene[]) {
  scenes.value = values
  for (const key of Object.keys(drafts)) delete drafts[key]
  for (const scene of values) setDraft(scene)
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [loadedProject, loadedCues, loadedScenes] = await Promise.all([
      getProject(projectId),
      listSubtitleCues(projectId),
      getStoryboard(projectId),
    ])
    project.value = loadedProject
    cues.value = loadedCues
    replaceScenes(loadedScenes)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '分镜工作区加载失败'
  } finally {
    loading.value = false
  }
}

async function chooseSrtFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  error.value = ''
  try {
    srtContent.value = await file.text()
    selectedFilename.value = file.name
    message.value = `已读取 ${file.name}，确认内容后导入项目`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '读取字幕文件失败'
  } finally {
    input.value = ''
  }
}

async function importSrt() {
  if (!srtContent.value.trim()) {
    error.value = '请先选择 SRT 文件或粘贴字幕内容'
    return
  }
  importing.value = true
  error.value = ''
  message.value = ''
  warnings.value = []
  try {
    const result = await importProjectSrt(projectId, srtContent.value)
    cues.value = result.cues
    if (result.changed) replaceScenes([])
    message.value = result.changed
      ? `已导入 ${result.count} 条字幕；旧分镜已失效，请重新生成`
      : `字幕内容未变化，共 ${result.count} 条`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '导入字幕失败'
  } finally {
    importing.value = false
  }
}

async function runStoryboard() {
  if (!cues.value.length) {
    error.value = '项目中还没有字幕，请先导入 SRT 或完成配音字幕流程'
    return
  }
  generating.value = true
  error.value = ''
  message.value = '正在生成并保存项目分镜…'
  warnings.value = []
  try {
    const result = await generateStoryboard(projectId)
    replaceScenes(result.scenes)
    warnings.value = result.warnings
    modelName.value = result.model
    message.value = `已生成并保存 ${result.scenes.length} 个视觉场景`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '生成项目分镜失败'
    message.value = ''
  } finally {
    generating.value = false
  }
}

function buildStoryboard(scene: VisualScene): StoryboardContent | null {
  const current = scene.storyboard
  const draft = drafts[scene.id]
  if (!current || !draft) return null
  return {
    ...current,
    visual_summary: draft.visual_summary.trim(),
    primary_query: draft.primary_query.trim(),
    scene_category: draft.scene_category.trim(),
    mood: draft.mood.trim(),
    alternative_queries: parseLines(draft.alternative_queries),
    must_include: parseLines(draft.must_include),
    avoid: parseLines(draft.avoid),
  }
}

async function saveScene(scene: VisualScene) {
  const storyboard = buildStoryboard(scene)
  if (!storyboard) return
  if (!storyboard.visual_summary || !storyboard.primary_query || !storyboard.scene_category || !storyboard.mood) {
    error.value = '视觉摘要、主查询、场景类别和情绪不能为空'
    return
  }
  savingSceneId.value = scene.id
  error.value = ''
  message.value = ''
  try {
    const saved = await updateStoryboardScene(projectId, scene.id, storyboard)
    const index = scenes.value.findIndex((item) => item.id === scene.id)
    if (index >= 0) scenes.value[index] = saved
    setDraft(saved)
    message.value = `场景 ${String(saved.scene_index).padStart(2, '0')} 已保存`
  } catch (err) {
    error.value = err instanceof Error ? err.message : '保存场景失败'
  } finally {
    savingSceneId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="storyboard-page">
    <div class="project-hero storyboard-hero">
      <div>
        <span class="section-eyebrow">PROJECT STORYBOARD</span>
        <h1>视觉分镜</h1>
        <p>将已确认字幕组织为视觉语义场景，并编辑画面与检索策略。</p>
      </div>
      <div class="page-title-actions">
        <span v-if="modelName" class="status-pill is-neutral">{{ modelName }}</span>
        <RouterLink v-if="scenes.length" class="primary-link" :to="`/projects/${projectId}/media-review`">进入素材审核</RouterLink>
        <button :class="scenes.length ? 'secondary-button' : 'primary-button'" :disabled="loading || generating || !cues.length" @click="runStoryboard">
          {{ generating ? '生成并保存中…' : scenes.length ? '重新生成分镜' : '生成项目分镜' }}
        </button>
      </div>
    </div>

    <div v-if="error" class="alert alert-danger"><strong>操作未完成</strong><span>{{ error }}</span></div>
    <div v-if="message" class="alert alert-success"><strong>当前状态</strong><span>{{ message }}</span></div>
    <div v-for="warning in warnings" :key="warning" class="alert storyboard-warning">
      <strong>生成提醒</strong><span>{{ warning }}</span>
    </div>

    <div v-if="!scenes.length" class="storyboard-input-grid project-storyboard-input">
      <article class="panel">
        <div class="section-head">
          <div><span class="section-eyebrow">SOURCE TIMELINE</span><h2>项目字幕</h2></div>
          <span class="status-pill is-neutral">{{ cues.length }} 条</span>
        </div>
        <p class="muted">如果配音流程已经生成字幕，这里会直接读取；也可以手动导入一份 SRT。</p>
        <label class="srt-file-picker">
          <input type="file" accept=".srt,text/plain" @change="chooseSrtFile" />
          <span class="secondary-button">选择 SRT 文件</span>
          <small>{{ selectedFilename || '或在下方粘贴字幕内容' }}</small>
        </label>
        <label class="field">
          <span>SRT 内容</span>
          <textarea v-model="srtContent" class="srt-input" placeholder="粘贴标准 SRT 字幕内容"></textarea>
        </label>
        <div class="actions">
          <button class="secondary-button" :disabled="importing || !srtContent.trim()" @click="importSrt">
            {{ importing ? '导入中…' : '导入项目字幕' }}
          </button>
          <span class="muted">时间轴 {{ formatTime(timelineDuration) }}</span>
        </div>
      </article>

      <aside class="panel subtitle-preview-panel">
        <div class="section-head">
          <div><span class="section-eyebrow">CUES</span><h2>字幕时间轴预览</h2></div>
          <span class="muted">{{ formatTime(timelineDuration) }}</span>
        </div>
        <div v-if="!cues.length" class="empty-state compact-empty">
          <h2>暂无项目字幕</h2><p>完成配音字幕流程或手动导入 SRT 后再生成分镜。</p>
        </div>
        <div v-else class="cue-list">
          <div v-for="cue in cues" :key="cue.id" class="cue-row">
            <span>{{ cue.cue_index }}</span>
            <div><small>{{ formatTime(cue.start_ms) }} → {{ formatTime(cue.end_ms) }}</small><p>{{ cue.text }}</p></div>
          </div>
        </div>
      </aside>
    </div>

    <div class="section-toolbar compact-title storyboard-section-title">
      <div>
        <span class="section-eyebrow">PERSISTED VISUAL SCENES</span>
        <h2>项目视觉场景</h2>
        <p>编辑后的查询约束会持久化，并作为下一阶段素材检索的输入。</p>
      </div>
      <span class="status-pill is-neutral">{{ scenes.length }} 个场景</span>
    </div>

    <div v-if="!scenes.length" class="empty-state panel">
      <h2>{{ loading ? '正在加载…' : '尚未生成项目分镜' }}</h2>
      <p>字幕准备完成后，点击“生成项目分镜”。</p>
    </div>

    <div class="scene-card-list">
      <article v-for="scene in scenes" :key="scene.id" class="panel scene-card">
        <div class="scene-card-head">
          <div><span class="scene-index">{{ String(scene.scene_index).padStart(2, '0') }}</span><strong>{{ scene.storyboard?.visual_summary }}</strong></div>
          <div><span class="status-pill is-neutral">{{ scene.status }}</span><span class="scene-time">{{ formatTime(scene.start_ms) }} – {{ formatTime(scene.end_ms) }}</span></div>
        </div>
        <p class="scene-narration">{{ scene.narration }}</p>

        <div v-if="scene.storyboard && drafts[scene.id]" class="storyboard-edit-grid">
          <label class="field field-wide"><span>视觉摘要</span><textarea v-model="drafts[scene.id].visual_summary" rows="2"></textarea></label>
          <label class="field field-wide"><span>主查询</span><input v-model="drafts[scene.id].primary_query" /></label>
          <label class="field"><span>场景类别</span><input v-model="drafts[scene.id].scene_category" /></label>
          <label class="field"><span>情绪</span><input v-model="drafts[scene.id].mood" /></label>
          <label class="field"><span>备用查询（每行一个）</span><textarea v-model="drafts[scene.id].alternative_queries" rows="3"></textarea></label>
          <label class="field"><span>必须包含（每行一个）</span><textarea v-model="drafts[scene.id].must_include" rows="3"></textarea></label>
          <label class="field"><span>应避免（每行一个）</span><textarea v-model="drafts[scene.id].avoid" rows="3"></textarea></label>
          <div class="storyboard-scene-meta">
            <span>类型：{{ scene.storyboard.visual_type }}</span>
            <span>年代：{{ scene.storyboard.time_period || '未指定' }}</span>
            <span>置信度：{{ Math.round((scene.storyboard.confidence || 0) * 100) }}%</span>
          </div>
        </div>
        <div class="actions scene-save-actions">
          <button class="primary-button" :disabled="savingSceneId === scene.id" @click="saveScene(scene)">
            {{ savingSceneId === scene.id ? '保存中…' : '保存场景修改' }}
          </button>
        </div>
      </article>
    </div>
  </section>
</template>
