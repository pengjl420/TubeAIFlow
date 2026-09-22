import { describe, expect, it, vi } from 'vitest'

import { apiClient } from './client'
import { enqueueSceneStoryboardJob, listVisualStrategies, recordProjectManualAcceptance } from './projects'


describe('project Job API', () => {
  it('queues Scene Storyboard regeneration through the durable Job endpoint', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: {
        success: true,
        data: {
          id: 'job-1',
          status: 'queued',
          stage: 'generate',
          running: false,
          queued: true,
          cancelled: false,
          queue_position: 1,
        },
      },
    })

    const result = await enqueueSceneStoryboardJob('project 1', 'scene/1')

    expect(post).toHaveBeenCalledWith(
      '/projects/project 1/jobs/scenes/scene%2F1/storyboard',
    )
    expect(result).toMatchObject({ id: 'job-1', status: 'queued' })
    post.mockRestore()
  })

  it('loads visual strategy capabilities from the engine', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({
      data: { success: true, data: [{
        id: 'anime_full_coverage', version: '2', display_name: 'Anime',
        description: 'Full coverage', compatible_video_modes: ['ai_generated_images'],
        full_timeline_coverage: true, supports_multiple_beats_per_scene: true,
      }] },
    })
    const result = await listVisualStrategies()
    expect(get).toHaveBeenCalledWith('/visual-strategies')
    expect(result[0].supports_multiple_beats_per_scene).toBe(true)
    get.mockRestore()
  })

  it('records explicit manual delivery acceptance', async () => {
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { success: true, data: { verification_status: 'manually_accepted' } },
    })
    await recordProjectManualAcceptance('project-1', {
      editor: 'Premiere Pro', audio_ok: true, subtitles_ok: true, media_links_ok: true,
    })
    expect(post).toHaveBeenCalledWith('/projects/project-1/quality/manual-acceptance', {
      editor: 'Premiere Pro', audio_ok: true, subtitles_ok: true, media_links_ok: true,
    })
    post.mockRestore()
  })
})
