import { describe, expect, it } from 'vitest'

import { ApiError, toApiError, unwrap } from './client'


describe('API error handling', () => {
  it('preserves the engine error code, status, and response details', () => {
    const error = toApiError({
      message: 'Request failed',
      response: {
        status: 409,
        data: {
          error: '模型尚未安装',
          code: 'MODEL_NOT_INSTALLED',
          model_id: 'whisper-large-v3',
        },
      },
    })

    expect(error).toBeInstanceOf(ApiError)
    expect(error.message).toBe('模型尚未安装')
    expect(error.code).toBe('MODEL_NOT_INSTALLED')
    expect(error.status).toBe(409)
    expect(error.details).toMatchObject({ model_id: 'whisper-large-v3' })
  })

  it('preserves error codes from unsuccessful envelopes', () => {
    expect(() => unwrap({
      data: { success: false, error: '显存不足', code: 'GPU_OUT_OF_MEMORY' },
    })).toThrow(expect.objectContaining({
      name: 'ApiError',
      code: 'GPU_OUT_OF_MEMORY',
    }))
  })
})
