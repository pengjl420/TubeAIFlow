import type { VoiceLanguage, VoiceTtsEngine } from '../api/voices'

export const TTS_ENGINE_LABELS: Record<VoiceTtsEngine, string> = {
  index_tts: 'IndexTTS',
  moss_tts: 'MOSS-TTS',
  cosyvoice: 'CosyVoice',
  qwen3_tts: 'Qwen3-TTS',
}

export const VOICE_LANGUAGE_LABELS: Record<VoiceLanguage, string> = {
  'zh-CN': '中文',
  'en-US': 'English',
  'yue-HK': '粤语',
}

export const DEFAULT_ENGINE_BY_LANGUAGE: Record<VoiceLanguage, VoiceTtsEngine> = {
  'zh-CN': 'index_tts',
  'en-US': 'moss_tts',
  'yue-HK': 'cosyvoice',
}

export const engineLabel = (engine: VoiceTtsEngine) => TTS_ENGINE_LABELS[engine] || engine
export const languageLabel = (language: VoiceLanguage) => VOICE_LANGUAGE_LABELS[language] || language
export const voiceTagText = (engine: VoiceTtsEngine, language: VoiceLanguage) => `${languageLabel(language)} · ${engineLabel(engine)}`
