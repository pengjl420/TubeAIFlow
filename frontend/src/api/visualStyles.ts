import { apiClient, unwrap } from './client'
import type { Project } from '../types/project'

export interface MotionPreset {
  type?: string
  zoom_start?: number
  zoom_end?: number
  pan_direction?: string
  transition?: string
  subtitle_safe_zone?: number
  [key: string]: unknown
}

export interface VisualStyleRevision {
  id: string
  style_profile_id: string
  version: number
  status: 'draft' | 'published'
  style_prompt: string
  negative_prompt: string
  continuity_rules: string[]
  composition_rules: string[]
  motion_preset: MotionPreset
  source: string
  content_hash: string
  created_at: string
  published_at?: string | null
}

export interface VisualStyleProfile {
  id: string
  name: string
  description: string
  tags: string[]
  status: 'draft' | 'published' | 'archived'
  builtin_key?: string | null
  current_revision?: VisualStyleRevision | null
  draft_revision?: VisualStyleRevision | null
  revisions: VisualStyleRevision[]
  created_at: string
  updated_at: string
}

export interface StyleTestRun {
  id: string
  client_request_id?: string | null
  style_revision_id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'unknown'
  candidate_count: number
  completed_candidates: number
  scene_description: string
  compiled_prompt: string
  compiled_negative_prompt: string
  provider_id: string
  model_id: string
  outputs: Array<{ index: number, image_url: string, generation_seconds: number }>
  candidates: Array<{
    index: number
    status: 'queued' | 'submitting' | 'completed' | 'failed' | 'unknown'
    generation_seconds?: number | null
    error_code?: string | null
    error_message?: string | null
  }>
  generation_seconds?: number | null
  error_code?: string | null
  error_message?: string | null
  created_at: string
}

export interface StyleDraftInput {
  name: string
  description: string
  tags: string[]
  style_prompt: string
  negative_prompt: string
  continuity_rules: string[]
  composition_rules: string[]
  motion_preset: MotionPreset
  source?: string
}

export interface StyleAsset {
  id: string
  style_profile_id: string
  style_revision_id: string
  source_type: 'style_test' | 'project_generation' | 'imported'
  status: 'unreviewed' | 'approved' | 'rejected' | 'archived' | 'missing'
  width: number
  height: number
  query_text: string
  provider_id: string
  model_id: string
  usage_count: number
  created_at: string
  image_url: string
}

export async function listVisualStyles(): Promise<VisualStyleProfile[]> {
  return unwrap<VisualStyleProfile[]>(await apiClient.get('/visual-styles'))
}

export async function createVisualStyle(input: Pick<StyleDraftInput, 'name' | 'description' | 'tags' | 'style_prompt' | 'negative_prompt'>): Promise<VisualStyleProfile> {
  return unwrap<VisualStyleProfile>(await apiClient.post('/visual-styles', input))
}

export async function updateVisualStyleDraft(id: string, input: StyleDraftInput): Promise<VisualStyleProfile> {
  return unwrap<VisualStyleProfile>(await apiClient.put(`/visual-styles/${id}/draft`, input))
}

export async function publishVisualStyle(id: string): Promise<VisualStyleProfile> {
  return unwrap<VisualStyleProfile>(await apiClient.post(`/visual-styles/${id}/publish`))
}

export async function duplicateVisualStyle(id: string): Promise<VisualStyleProfile> {
  return unwrap<VisualStyleProfile>(await apiClient.post(`/visual-styles/${id}/duplicate`))
}

export async function archiveVisualStyle(id: string): Promise<VisualStyleProfile> {
  return unwrap<VisualStyleProfile>(await apiClient.post(`/visual-styles/${id}/archive`))
}

export async function optimizeVisualStyle(id: string, input: { style_prompt: string, negative_prompt: string, goal: string }): Promise<{
  optimized_style_prompt: string
  optimized_negative_prompt: string
  continuity_rules?: string[]
  composition_rules?: string[]
  warnings?: string[]
  summary?: string
}> {
  return unwrap(await apiClient.post(`/visual-styles/${id}/optimize`, input))
}

export async function runVisualStyleTest(id: string, input: { client_request_id: string, revision_id?: string, scene_description: string, candidates: number }): Promise<StyleTestRun> {
  return unwrap<StyleTestRun>(await apiClient.post(`/visual-styles/${id}/tests`, input))
}

export async function listVisualStyleTests(id: string): Promise<StyleTestRun[]> {
  return unwrap<StyleTestRun[]>(await apiClient.get(`/visual-styles/${id}/tests`))
}

export async function listVisualStyleAssets(id: string): Promise<StyleAsset[]> {
  return unwrap<StyleAsset[]>(await apiClient.get(`/visual-styles/${id}/assets`))
}

export async function updateVisualStyleAssetStatus(
  styleId: string,
  assetId: string,
  status: 'approved' | 'rejected' | 'archived',
): Promise<StyleAsset> {
  return unwrap<StyleAsset>(await apiClient.put(`/visual-styles/${styleId}/assets/${assetId}`, { status }))
}

export async function getVisualStyleTest(runId: string): Promise<StyleTestRun> {
  return unwrap<StyleTestRun>(await apiClient.get(`/visual-styles/tests/${runId}`))
}

export async function bindProjectVisualStyle(projectId: string, revisionId: string, applyExisting = false): Promise<Project> {
  return unwrap<Project>(await apiClient.put(`/visual-styles/projects/${projectId}`, {
    revision_id: revisionId,
    apply_existing: applyExisting,
  }))
}
