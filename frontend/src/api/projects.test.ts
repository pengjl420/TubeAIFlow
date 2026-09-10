import { describe, expect, it, vi } from 'vitest'

import { apiClient } from './client'
import { enqueueSceneStoryboardJob } from './projects'


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
})
