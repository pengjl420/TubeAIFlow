<script setup lang="ts">
import { computed, ref } from 'vue'
import { Pause, Play } from 'lucide-vue-next'

defineProps<{ src: string }>()

const audio = ref<HTMLAudioElement | null>(null)
const playing = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const progress = computed(() => (duration.value ? (currentTime.value / duration.value) * 100 : 0))

function formatTime(value: number) {
  if (!Number.isFinite(value)) return '00:00'
  const minutes = Math.floor(value / 60)
  const seconds = Math.floor(value % 60)
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

async function togglePlayback() {
  if (!audio.value) return
  if (audio.value.paused) await audio.value.play()
  else audio.value.pause()
}

function seek(event: Event) {
  if (!audio.value || !duration.value) return
  const value = Number((event.target as HTMLInputElement).value)
  audio.value.currentTime = (value / 100) * duration.value
}
</script>

<template>
  <div class="audio-player">
    <audio
      ref="audio"
      :src="src"
      preload="metadata"
      @loadedmetadata="duration = audio?.duration || 0"
      @timeupdate="currentTime = audio?.currentTime || 0"
      @play="playing = true"
      @pause="playing = false"
      @ended="playing = false"
    ></audio>
    <button class="audio-player-toggle" type="button" :aria-label="playing ? '暂停音频' : '播放音频'" @click="togglePlayback">
      <Pause v-if="playing" :size="15" fill="currentColor" />
      <Play v-else :size="15" fill="currentColor" />
    </button>
    <span class="audio-player-time">{{ formatTime(currentTime) }}</span>
    <input
      class="audio-player-progress"
      type="range"
      min="0"
      max="100"
      step="0.1"
      :value="progress"
      aria-label="音频播放进度"
      @input="seek"
    />
    <span class="audio-player-time">{{ formatTime(duration) }}</span>
  </div>
</template>
