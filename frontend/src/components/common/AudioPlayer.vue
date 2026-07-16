<template>
  <audio controls :src="src"></audio>
</template>

<script setup lang="ts">
defineProps<{ src: string }>()
</script>
