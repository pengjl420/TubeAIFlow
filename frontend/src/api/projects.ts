import { apiClient, unwrap } from './client'
import type { Project } from '../types/project'
import type { SceneRevision, StoryboardContent, VisualScene } from '../types/storyboard'

export interface CreateProjectInput {
  name: string
  outputDir: string
  voiceProfileId: string
  ttsEngine: string
}

export interface ProjectTask {
  id: string | null
  status: string
  stage: string | null
  running: boolean
  queued: boolean
  cancelled: boolean
  queue_position: number | null
  error_message?: string | null
  error_code?: string | null
  job_type?: string
  scene_id?: string | null
  resource_class?: string
  progress?: number
  max_retries?: number
  request?: Record<string, unknown>
  result?: Record<string, unknown>
}

export interface ProjectOutput {
  name: string
  path: string
  relative_path: string
  size: number
  modified_at: number
}

export interface ProjectOutputs {
  output_dir: string
  work_dir: string
  final_audio_exists: boolean
  final_srt_exists: boolean
  final_video_exists: boolean
  files: ProjectOutput[]
}

export interface SceneImageVariant {
  id: string
  variant_index: number
  path: string
  prompt: string
  negative_prompt: string
  seed: number
  width: number
  height: number
  status: string
  error_message?: string | null
  selected: boolean
}

export interface SceneAssets {
  scene_id: string
  variants: SceneImageVariant[]
  assignments: Array<{ id: string; path: string; media_type: string }>
  coverage: { covered_ms: number; duration_ms: number; remaining_ms: number; complete: boolean }
}

export interface TimelineClip {
  id: string
  scene_id?: string
  scene_index?: number
  asset_path?: string | null
  media_type?: string
  text?: string
  start_ms: number
  end_ms: number
  sequence_index?: number
  display_duration_ms?: number | null
  source_start_ms?: number | null
  source_end_ms?: number | null
  playback_speed?: number
  motion_type?: string
  zoom_start?: number
  zoom_end?: number
  pan_direction?: string
  crop_anchor?: string
  transition?: string
}

export interface TimelineData {
  format_version: number
  project_id: string
  duration_ms: number
  fps: number
  tracks: Array<{ id: string; type: string; clips: TimelineClip[] }>
}

export async function listProjects(): Promise<Project[]> {
  return unwrap<Project[]>(await apiClient.get('/projects'))
}

export async function getProject(projectId: string): Promise<Project> {
  return unwrap<Project>(await apiClient.get(`/projects/${projectId}`))
}

export async function createProject(input: CreateProjectInput): Promise<Project> {
  const form = new FormData()
  form.append('name', input.name)
  form.append('output_dir', input.outputDir)
  form.append('voice_profile_id', input.voiceProfileId)
  form.append('tts_engine', input.ttsEngine)
  form.append('include_video', 'false')
  form.append('segmentation_mode', 'ai')
  return unwrap<Project>(await apiClient.post('/projects', form))
}

export async function saveProjectScript(projectId: string, text: string): Promise<Project> {
  return unwrap<Project>(await apiClient.post(`/projects/${projectId}/script`, { text }))
}

export async function getProjectScript(projectId: string): Promise<{ text: string; clean_text: string }> {
  return unwrap<{ text: string; clean_text: string }>(
    await apiClient.get(`/projects/${projectId}/script`),
  )
}

export async function startProjectWorkflow(projectId: string): Promise<ProjectTask> {
  return unwrap<ProjectTask>(
    await apiClient.post(`/projects/${projectId}/workflows/narration/start`),
  )
}

export async function getProjectTask(projectId: string): Promise<ProjectTask> {
  return unwrap<ProjectTask>(await apiClient.get(`/projects/${projectId}/tasks/status`))
}

export async function cancelProjectTask(projectId: string): Promise<void> {
  await apiClient.post(`/projects/${projectId}/tasks/cancel`)
}

export async function getProjectOutputs(projectId: string): Promise<ProjectOutputs> {
  return unwrap<ProjectOutputs>(await apiClient.get(`/projects/${projectId}/outputs`))
}

export async function getProjectScenes(projectId: string): Promise<VisualScene[]> {
  const data = unwrap<{ scenes: VisualScene[] }>(
    await apiClient.get(`/projects/${projectId}/storyboard`),
  )
  return data.scenes
}

export async function updateProjectScene(
  projectId: string,
  sceneId: string,
  values: {
    narration?: string
    storyboard?: StoryboardContent
    status?: string
    locked_text?: boolean
    locked_audio?: boolean
    locked_visual?: boolean
  },
): Promise<VisualScene> {
  return unwrap<VisualScene>(
    await apiClient.put(`/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}`, values),
  )
}

export async function getSceneRevisions(projectId: string, sceneId: string): Promise<SceneRevision[]> {
  return unwrap<SceneRevision[]>(
    await apiClient.get(`/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/revisions`),
  )
}

export async function restoreSceneRevision(
  projectId: string,
  sceneId: string,
  revisionId: string,
): Promise<VisualScene> {
  return unwrap<VisualScene>(
    await apiClient.post(`/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/revisions/${revisionId}/restore`),
  )
}

export async function regenerateProjectScene(
  projectId: string,
  sceneId: string,
): Promise<VisualScene> {
  return unwrap<VisualScene>(
    await apiClient.post(`/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/regenerate`, undefined, { timeout: 120000 }),
  )
}

export async function getSceneAssets(projectId: string, sceneId: string): Promise<SceneAssets> {
  return unwrap<SceneAssets>(await apiClient.get(`/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/assets`))
}

export async function selectSceneImage(projectId: string, sceneId: string, variantId: string): Promise<SceneAssets> {
  return unwrap<SceneAssets>(await apiClient.put(`/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/assets/selection`, { variant_id: variantId }))
}

export async function clearSceneImage(projectId: string, sceneId: string): Promise<SceneAssets> {
  return unwrap<SceneAssets>(await apiClient.delete(`/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/assets/selection`))
}

export async function regenerateSceneImages(projectId: string, sceneId: string): Promise<SceneAssets> {
  return unwrap<SceneAssets>(await apiClient.post(`/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/assets/regenerate`, undefined, { timeout: 600000 }))
}

export async function renderScenePreview(projectId: string, sceneId: string): Promise<{ path: string }> {
  return unwrap<{ path: string }>(await apiClient.post(`/projects/${projectId}/render/scenes/${encodeURIComponent(sceneId)}`, undefined, { timeout: 120000 }))
}

export async function enqueueSceneImageJob(projectId: string, sceneId: string): Promise<ProjectTask> {
  return unwrap<ProjectTask>(await apiClient.post(`/projects/${projectId}/jobs/scenes/${encodeURIComponent(sceneId)}/images`))
}

export async function enqueueScenePreviewJob(projectId: string, sceneId: string): Promise<ProjectTask> {
  return unwrap<ProjectTask>(await apiClient.post(`/projects/${projectId}/jobs/scenes/${encodeURIComponent(sceneId)}/preview`))
}

export async function enqueueTimelinePreviewJob(
  projectId: string,
  startMs: number,
  durationMs: 30000 | 60000,
): Promise<ProjectTask> {
  return unwrap<ProjectTask>(await apiClient.post(`/projects/${projectId}/jobs/preview`, {
    start_ms: startMs,
    duration_ms: durationMs,
  }))
}

export async function enqueueFinalRenderJob(projectId: string): Promise<ProjectTask> {
  return unwrap<ProjectTask>(await apiClient.post(`/projects/${projectId}/jobs/final-render`))
}

export async function getProjectJob(projectId: string, jobId: string): Promise<ProjectTask> {
  return unwrap<ProjectTask>(await apiClient.get(`/projects/${projectId}/jobs/${jobId}`))
}

export async function pauseProjectJob(projectId: string, jobId: string): Promise<ProjectTask> {
  return unwrap<ProjectTask>(await apiClient.post(`/projects/${projectId}/jobs/${jobId}/pause`))
}

export async function resumeProjectJob(projectId: string, jobId: string): Promise<ProjectTask> {
  return unwrap<ProjectTask>(await apiClient.post(`/projects/${projectId}/jobs/${jobId}/resume`))
}

export async function cancelProjectJob(projectId: string, jobId: string): Promise<ProjectTask> {
  return unwrap<ProjectTask>(await apiClient.post(`/projects/${projectId}/jobs/${jobId}/cancel`))
}

export async function getTimelineEditor(projectId: string): Promise<TimelineData> {
  return unwrap<TimelineData>(await apiClient.get(`/projects/${projectId}/timeline/editor`))
}

export async function updateTimelineClip(
  projectId: string,
  clipId: string,
  values: Partial<TimelineClip>,
): Promise<TimelineData> {
  return unwrap<TimelineData>(await apiClient.put(`/projects/${projectId}/timeline/clips/${clipId}`, values))
}

export function projectOutputUrl(projectId: string, path: string, download = false): string {
  const query = new URLSearchParams({ path, download: String(download) })
  return `${apiClient.defaults.baseURL}/projects/${projectId}/outputs/file?${query}`
}
