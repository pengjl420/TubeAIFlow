import { API_BASE_URL, apiClient, unwrap } from './client'
import type {
  AssetImportResult,
  LibraryRole,
  MediaAsset,
  ReviewStatus,
  SceneCandidate,
  SceneAssignmentTrack,
  SceneAssignment,
  SceneCoverage,
  SceneSearchResult,
} from '../types/media'

export interface AssetLibrarySummary {
  asset_count: number
  shot_count: number
  semantic_asset_count: number
  indexed_shot_count: number
  preview_shot_count: number
}

export interface AssetLibraryQuery {
  page?: number
  pageSize?: number
  libraryRole?: LibraryRole
  search?: string
}

export async function getAssetLibrary(query: AssetLibraryQuery = {}): Promise<{
  assets: MediaAsset[]
  vectorModel: string
  page: number
  pageSize: number
  total: number
  summary: AssetLibrarySummary
}> {
  const result = unwrap<{
    assets: MediaAsset[]
    vector_model: string
    page: number
    page_size: number
    total: number
    summary: AssetLibrarySummary
  }>(await apiClient.get('/assets', {
    params: {
      page: query.page ?? 1,
      page_size: query.pageSize ?? 200,
      library_role: query.libraryRole,
      search: query.search?.trim() || undefined,
    },
  }))
  return {
    assets: result.assets,
    vectorModel: result.vector_model,
    page: result.page,
    pageSize: result.page_size,
    total: result.total,
    summary: result.summary,
  }
}

export async function listAssets(): Promise<MediaAsset[]> {
  return (await getAssetLibrary()).assets
}

export async function importAssets(
  directory: string,
  libraryRole: LibraryRole,
  fallbackCategory = '',
  mood = '',
): Promise<AssetImportResult> {
  return unwrap(await apiClient.post('/assets/import', {
    directory,
    library_role: libraryRole,
    fallback_category: fallbackCategory,
    mood,
  }, { timeout: 300_000 }))
}

export async function updateAsset(
  mediaId: string,
  input: {
    library_role: LibraryRole
    fallback_category: string
    mood: string
    review_status: ReviewStatus
    enabled: boolean
  },
): Promise<MediaAsset> {
  return unwrap(await apiClient.patch(`/assets/${encodeURIComponent(mediaId)}`, input))
}

export async function ingestAsset(mediaId: string): Promise<{ asset: MediaAsset; errors: Array<{ shot_id: string; error: string }> }> {
  return unwrap(await apiClient.post(`/assets/${encodeURIComponent(mediaId)}/ingest`, undefined, { timeout: 0 }))
}

export interface AssetDeleteResult {
  deleted_ids: string[]
  missing_ids: string[]
  deleted_preview_files: number
  source_files_preserved: number
}

export async function deleteAsset(mediaId: string): Promise<AssetDeleteResult> {
  return unwrap(await apiClient.delete(`/assets/${encodeURIComponent(mediaId)}`, { timeout: 0 }))
}

export async function deleteAssets(mediaIds: string[]): Promise<AssetDeleteResult> {
  return unwrap(await apiClient.delete('/assets/batch', {
    data: { media_ids: mediaIds },
    timeout: 0,
  }))
}

export async function cleanupAssetCache(): Promise<{ deleted_query_cache_entries: number; source_files_preserved: boolean }> {
  return unwrap(await apiClient.post('/assets/cleanup-cache'))
}

export async function listSceneCandidates(projectId: string, sceneId: string): Promise<SceneCandidate[]> {
  const result = unwrap<{ candidates: SceneCandidate[] }>(await apiClient.get(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/candidates`,
  ))
  return result.candidates
}

export async function searchSceneCandidates(projectId: string, sceneId: string): Promise<SceneSearchResult> {
  return unwrap(await apiClient.post(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/search`,
    undefined,
    { timeout: 0 },
  ))
}

export async function generateSceneImages(projectId: string, sceneId: string): Promise<{
  project_id: string
  scene_count: number
  candidate_count: number
  generated_count: number
  candidates: SceneCandidate[]
}> {
  return unwrap(await apiClient.post(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/generate-images`,
    undefined,
    { timeout: 0 },
  ))
}

export async function assignSceneCandidate(
  projectId: string,
  sceneId: string,
  candidateId: string,
  manualOverride = false,
  append = false,
): Promise<{ id: string; candidate_id: string; media_shot_id: string }> {
  return unwrap(await apiClient.post(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/assign`,
    { candidate_id: candidateId, manual_override: manualOverride, append },
  ))
}

export async function listSceneAssignments(projectId: string, sceneId: string): Promise<SceneAssignmentTrack> {
  return unwrap(await apiClient.get(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/assignments`,
  ))
}

export async function getProjectAssignmentCoverage(projectId: string): Promise<Record<string, SceneCoverage>> {
  const result = unwrap<{ scenes: Record<string, SceneCoverage> }>(await apiClient.get(
    `/projects/${projectId}/storyboard/assignments/coverage`,
  ))
  return result.scenes
}

export async function deleteSceneAssignment(
  projectId: string,
  sceneId: string,
  assignmentId: string,
): Promise<SceneAssignmentTrack> {
  return unwrap(await apiClient.delete(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/assignments/${encodeURIComponent(assignmentId)}`,
  ))
}

export async function reorderSceneAssignments(
  projectId: string,
  sceneId: string,
  assignmentIds: string[],
): Promise<SceneAssignmentTrack> {
  return unwrap(await apiClient.put(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/assignments/order`,
    { assignment_ids: assignmentIds },
  ))
}

export async function updateSceneAssignmentRender(
  projectId: string,
  sceneId: string,
  assignment: SceneAssignment,
): Promise<SceneAssignmentTrack> {
  return unwrap(await apiClient.patch(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/assignments/${encodeURIComponent(assignment.id)}/render`,
    {
      render_mode: assignment.render_mode,
      motion_type: assignment.motion_type,
      zoom_start: assignment.zoom_start,
      zoom_end: assignment.zoom_end,
      pan_direction: assignment.pan_direction,
      crop_anchor: assignment.crop_anchor,
    },
  ))
}

export async function confirmSceneAssignments(
  projectId: string,
  sceneId: string,
): Promise<SceneAssignmentTrack> {
  return unwrap(await apiClient.post(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/assignments/confirm`,
  ))
}

export const confirmSceneFallbackAssignments = confirmSceneAssignments

export async function uploadSceneAsset(
  projectId: string,
  sceneId: string,
  file: File,
): Promise<{ asset: MediaAsset; candidates: SceneCandidate[]; ingestion_errors: Array<{ shot_id: string; error: string }> }> {
  const form = new FormData()
  form.append('file', file)
  return unwrap(await apiClient.post(
    `/projects/${projectId}/storyboard/scenes/${encodeURIComponent(sceneId)}/upload`,
    form,
    { timeout: 0 },
  ))
}

export function assetPreviewUrl(path: string | null): string {
  if (!path) return ''
  const origin = API_BASE_URL.replace(/\/api\/?$/, '')
  return path.startsWith('http') ? path : `${origin}${path}`
}
