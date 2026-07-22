<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'

import { getProject } from '../../api/projects'
import { usePageFeedback } from '../../services/feedback'
import {
  generateStoryboard,
  getStoryboard,
  updateStoryboardScene,
} from '../../api/storyboard'
import type { Project } from '../../types/project'
import type { StoryboardContent, VisualScene } from '../../types/storyboard'

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
const scenes = ref<VisualScene[]>([])
const drafts = reactive<Record<string, StoryboardDraft>>({})
const warnings = ref<string[]>([])
const modelName = ref('')
const loading = ref(false)
const generating = ref(false)
const savingSceneId = ref('')
const error = ref('')
const message = ref('')
usePageFeedback(error, message, { errorTitle: '分镜操作未完成', messageTitle: '分镜状态' })

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
    const [loadedProject, loadedScenes] = await Promise.all([
      getProject(projectId),
      getStoryboard(projectId),
    ])
    project.value = loadedProject
    replaceScenes(loadedScenes)
  } catch (err) {
    error.value = err instanceof Error ? err.message : '分镜工作区加载失败'
  } finally {
    loading.value = false
  }
}

async function runStoryboard() {
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
        <p>系统根据逐字稿和真实配音时长自动生成视觉语义场景。</p>
      </div>
      <div class="page-title-actions">
        <span v-if="modelName" class="status-pill is-neutral">{{ modelName }}</span>
        <RouterLink v-if="scenes.length" class="primary-link" :to="`/projects/${projectId}/media-review`">进入素材审核</RouterLink>
        <button :class="scenes.length ? 'secondary-button' : 'primary-button'" :disabled="loading || generating" @click="runStoryboard">
          {{ generating ? '生成并保存中…' : scenes.length ? '重新生成分镜' : '生成项目分镜' }}
        </button>
      </div>
    </div>

    <div v-for="warning in warnings" :key="warning" class="alert storyboard-warning">
      <strong>生成提醒</strong><span>{{ warning }}</span>
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
      <p>完成配音后，分镜会由一键生成流程自动创建；也可以在这里重新生成。</p>
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
