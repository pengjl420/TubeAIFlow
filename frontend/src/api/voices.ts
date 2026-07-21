import { apiClient, unwrap } from './client'

export type VoiceTtsEngine = 'qwen3_tts' | 'cosyvoice'

export interface VoiceProfile {
  id: string
  name: string
  tts_engine: VoiceTtsEngine
  reference_audio_text: string
  cosyvoice_speed: number
  original_filename: string
  created_at: string
  updated_at: string
  usage_count: number
  running_project_count: number
  tags: string[]
}

export interface SaveVoiceInput {
  name: string
  tts_engine: VoiceTtsEngine
  reference_audio_text: string
  cosyvoice_speed: number
  file?: File | null
  tags: string[]
}

export async function listVoices(): Promise<VoiceProfile[]> {
  return unwrap<VoiceProfile[]>(await apiClient.get('/voices'))
}

export async function createVoice(input: SaveVoiceInput): Promise<VoiceProfile> {
  if (!input.file) throw new Error('请选择参考音频文件')
  const form = toFormData(input)
  return unwrap<VoiceProfile>(await apiClient.post('/voices', form))
}

export async function updateVoice(id: string, input: SaveVoiceInput): Promise<VoiceProfile> {
  const form = toFormData(input)
  return unwrap<VoiceProfile>(await apiClient.put(`/voices/${id}`, form))
}

export async function deleteVoice(id: string): Promise<void> {
  await apiClient.delete(`/voices/${id}`)
}

export async function duplicateVoice(id: string): Promise<VoiceProfile> {
  return unwrap<VoiceProfile>(await apiClient.post(`/voices/${id}/duplicate`))
}

function toFormData(input: SaveVoiceInput): FormData {
  const form = new FormData()
  form.append('name', input.name)
  form.append('tts_engine', input.tts_engine)
  form.append('reference_audio_text', input.reference_audio_text)
  form.append('cosyvoice_speed', String(input.cosyvoice_speed))
  form.append('tags', JSON.stringify(input.tags))
  if (input.file) form.append('file', input.file)
  return form
}
