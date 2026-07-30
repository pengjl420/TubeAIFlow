<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  CheckCircle2,
  Clock3,
  Film,
  Folder,
  Layers3,
  Play,
  Shuffle,
  Sparkles,
} from 'lucide-vue-next'

import {
  composeLocalVideo,
  type LocalVideoMergeResult,
} from '../api/localVideoMerge'
import { selectDirectory } from '../api/projects'
import { showToast, usePageFeedback } from '../services/feedback'

const mediaDir = ref('')
const outputDir = ref('')
const outputFilename = ref('local_merge.mp4')
const durationMinutes = ref(1)
const durationSeconds = ref(0)
const selectingFolder = ref<'media' | 'output' | null>(null)
const composing = ref(false)
const error = ref('')
const result = ref<LocalVideoMergeResult | null>(null)
const PREFERENCES_KEY = 'tubeaiflow-local-video-merge-preferences'
usePageFeedback(error, undefined, { errorTitle: '本地视频合并失败' })

const targetDuration = computed(() => (
  Number(durationMinutes.value) * 60 + Number(durationSeconds.value)
))
const durationValid = computed(() => (
  Number.isInteger(Number(durationMinutes.value))
  && Number.isInteger(Number(durationSeconds.value))
  && Number(durationMinutes.value) >= 0
  && Number(durationMinutes.value) <= 1440
  && Number(durationSeconds.value) >= 0
  && Number(durationSeconds.value) <= 59
  && targetDuration.value > 0
  && targetDuration.value <= 86400
))
const ready = computed(() => (
  Boolean(mediaDir.value.trim() && outputDir.value.trim() && outputFilename.value.trim())
  && durationValid.value
))

function loadPreferences() {
  try {
    const stored = JSON.parse(localStorage.getItem(PREFERENCES_KEY) || '{}')
    if (typeof stored.mediaDir === 'string') mediaDir.value = stored.mediaDir
    if (typeof stored.outputDir === 'string') outputDir.value = stored.outputDir
    if (typeof stored.outputFilename === 'string' && stored.outputFilename.trim()) {
      outputFilename.value = stored.outputFilename
    }
    if (Number.isInteger(stored.durationMinutes) && stored.durationMinutes >= 0) {
      durationMinutes.value = stored.durationMinutes
    }
    if (Number.isInteger(stored.durationSeconds) && stored.durationSeconds >= 0) {
      durationSeconds.value = stored.durationSeconds
    }
  } catch {
    localStorage.removeItem(PREFERENCES_KEY)
  }
}

function savePreferences() {
  localStorage.setItem(PREFERENCES_KEY, JSON.stringify({
    mediaDir: mediaDir.value,
    outputDir: outputDir.value,
    outputFilename: outputFilename.value,
    durationMinutes: durationMinutes.value,
    durationSeconds: durationSeconds.value,
  }))
}

async function chooseFolder(target: 'media' | 'output') {
  selectingFolder.value = target
  error.value = ''
  try {
    const selected = await selectDirectory(
      target === 'media' ? mediaDir.value : outputDir.value,
      target === 'media' ? '选择本地视频素材目录' : '选择合并视频输出目录',
    )
    if (selected && target === 'media') mediaDir.value = selected
    if (selected && target === 'output') outputDir.value = selected
  } catch (err) {
    error.value = err instanceof Error ? err.message : '文件夹选择失败'
  } finally {
    selectingFolder.value = null
  }
}

async function compose() {
  if (!ready.value) {
    error.value = durationValid.value
      ? '请完整填写输出文件名和两个目录'
      : '请填写有效时长：分钟不得小于 0，秒钟范围为 0–59，且总时长必须大于 0'
    return
  }
  composing.value = true
  result.value = null
  error.value = ''
  try {
    result.value = await composeLocalVideo({
      media_dir: mediaDir.value.trim(),
      output_dir: outputDir.value.trim(),
      output_filename: outputFilename.value.trim(),
      target_duration: targetDuration.value,
    })
    showToast({
      title: '视频合并完成',
      description: result.value.output_path,
      tone: 'success',
      duration: 6000,
    })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '视频合并失败'
  } finally {
    composing.value = false
  }
}

watch(
  [mediaDir, outputDir, outputFilename, durationMinutes, durationSeconds],
  savePreferences,
)
onMounted(loadPreferences)
</script>

<template>
  <section class="local-merge-page">
    <header class="taf-page-heading">
      <div>
        <h1>本地素材拼接</h1>
        <p>从本地目录随机提取不重名视频，在片段之间加入转场并输出完整 MP4。</p>
      </div>
      <span class="local-tool-badge"><Film :size="17" /> 独立工具</span>
    </header>

    <div class="local-merge-layout">
      <article class="local-merge-card config-card">
        <header>
          <span class="card-icon blue"><Layers3 :size="20" /></span>
          <div><h2>合并配置</h2><p>素材目录会递归扫描所有支持的视频文件。</p></div>
        </header>

        <div class="local-merge-form">
          <label class="merge-field wide">
            <span>素材目录 <b>*</b></span>
            <div class="merge-path-input">
              <input v-model="mediaDir" readonly placeholder="请选择包含视频素材的文件夹" />
              <button type="button" :disabled="selectingFolder !== null || composing" @click="chooseFolder('media')">
                <Folder :size="17" /> 选择
              </button>
            </div>
            <small>支持 MP4、MOV、AVI、M4V、MPG、MPEG，并自动遍历子目录。</small>
          </label>

          <label class="merge-field">
            <span>目标视频时长 <b>*</b></span>
            <div class="duration-input">
              <Clock3 :size="17" />
              <label>
                <input v-model.number="durationMinutes" aria-label="目标视频分钟数" type="number" min="0" max="1440" step="1" />
                <em>分</em>
              </label>
              <i></i>
              <label>
                <input v-model.number="durationSeconds" aria-label="目标视频秒数" type="number" min="0" max="59" step="1" />
                <em>秒</em>
              </label>
            </div>
            <small>当前总时长：{{ durationValid ? targetDuration : 0 }} 秒</small>
          </label>

          <label class="merge-field">
            <span>输出文件名 <b>*</b></span>
            <input v-model="outputFilename" maxlength="200" placeholder="例如：精选素材.mp4" />
            <small>未填写扩展名时会自动补充 .mp4。</small>
          </label>

          <label class="merge-field wide">
            <span>输出目录 <b>*</b></span>
            <div class="merge-path-input">
              <input v-model="outputDir" readonly placeholder="请选择成片保存文件夹" />
              <button type="button" :disabled="selectingFolder !== null || composing" @click="chooseFolder('output')">
                <Folder :size="17" /> 选择
              </button>
            </div>
          </label>
        </div>

        <button class="merge-submit" type="button" :disabled="!ready || composing || selectingFolder !== null" @click="compose">
          <span v-if="composing" class="merge-spinner"></span>
          <Play v-else :size="18" />
          {{ composing ? '正在提取素材并合并，请勿关闭页面…' : '开始随机提取并合并' }}
        </button>
      </article>

      <aside class="local-merge-card rules-card">
        <header>
          <span class="card-icon purple"><Sparkles :size="20" /></span>
          <div><h2>处理规则</h2><p>复用系统现有 FFmpeg 粗剪能力。</p></div>
        </header>
        <ol>
          <li><span><Folder :size="17" /></span><div><strong>递归扫描</strong><p>读取素材目录和全部子目录的视频。</p></div></li>
          <li><span><Shuffle :size="17" /></span><div><strong>随机且不重名</strong><p>同名文件只随机选择其中一个参与合并。</p></div></li>
          <li><span><Sparkles :size="17" /></span><div><strong>逐段转场</strong><p>每两个相邻视频之间随机应用已启用的系统转场。</p></div></li>
          <li><span><Film :size="17" /></span><div><strong>统一输出</strong><p>标准化为 1920×1080、30fps、H.264 MP4，并裁到目标时长。</p></div></li>
        </ol>
      </aside>
    </div>

    <article v-if="result" class="local-merge-card result-card">
      <span class="result-check"><CheckCircle2 :size="28" /></span>
      <div>
        <h2>视频合并完成</h2>
        <p>{{ result.output_path }}</p>
      </div>
      <dl>
        <div><dt>扫描素材</dt><dd>{{ result.scanned_file_count }}</dd></div>
        <div><dt>去重后</dt><dd>{{ result.unique_filename_count }}</dd></div>
        <div><dt>实际选用</dt><dd>{{ result.selected_file_count }}</dd></div>
        <div><dt>转场数量</dt><dd>{{ result.transition_count }}</dd></div>
        <div><dt>成片时长</dt><dd>{{ result.actual_duration.toFixed(2) }} 秒</dd></div>
      </dl>
    </article>
  </section>
</template>

<style scoped>
.local-merge-page{color:#172033}.local-tool-badge{align-items:center;background:#eaf2ff;border:1px solid #cfe0ff;border-radius:999px;color:#075bf5;display:flex;font-size:12px;font-weight:750;gap:7px;padding:8px 13px}.local-merge-layout{align-items:start;display:grid;gap:16px;grid-template-columns:minmax(560px,1.45fr) minmax(300px,.65fr)}.local-merge-card{background:#fff;border:1px solid #e1e7ef;border-radius:13px;box-shadow:0 5px 22px #34435f0a;padding:20px}.local-merge-card>header{align-items:center;border-bottom:1px solid #edf0f4;display:flex;gap:11px;margin:-2px 0 20px;padding-bottom:15px}.local-merge-card h2{font-size:16px;margin:0}.local-merge-card header p{color:#7b8799;font-size:11px;margin:4px 0 0}.card-icon{align-items:center;border-radius:9px;display:flex;height:38px;justify-content:center;width:38px}.card-icon.blue{background:#eaf2ff;color:#0864eb}.card-icon.purple{background:#f1ecff;color:#7654d7}.local-merge-form{display:grid;gap:17px;grid-template-columns:1fr 1fr}.merge-field{display:grid;gap:8px}.merge-field.wide{grid-column:1/-1}.merge-field>span{font-size:12px;font-weight:750}.merge-field b{color:#e13e49}.merge-field>input,.merge-path-input input,.duration-input{background:#fff;border:1px solid #dce3ec;border-radius:8px;box-sizing:border-box;min-height:43px;outline:none;padding:10px 12px;width:100%}.merge-field input:focus,.duration-input:focus-within{border-color:#0864eb;box-shadow:0 0 0 3px #0864eb12}.merge-field small{color:#8792a3;font-size:10px}.merge-path-input{display:flex}.merge-path-input input{border-radius:8px 0 0 8px}.merge-path-input button{align-items:center;background:#f7f9fc;border:1px solid #dce3ec;border-left:0;border-radius:0 8px 8px 0;color:#46556b;display:flex;font-weight:700;gap:6px;padding:0 14px}.duration-input{align-items:center;color:#758196;display:flex;gap:9px;padding:0 12px}.duration-input>label{align-items:center;display:flex;flex:1;gap:6px}.duration-input input{border:0;min-width:0;outline:0;padding:10px 0;text-align:right;width:100%}.duration-input em{font-size:11px;font-style:normal;white-space:nowrap}.duration-input>i{background:#dce3ec;height:22px;width:1px}.merge-submit{align-items:center;background:#0864eb;border:0;border-radius:9px;color:#fff;display:flex;font-size:13px;font-weight:750;gap:8px;justify-content:center;margin-top:22px;min-height:46px;width:100%}.merge-submit:disabled{cursor:not-allowed;opacity:.55}.merge-spinner{animation:spin .8s linear infinite;border:2px solid #ffffff66;border-radius:50%;border-top-color:#fff;height:16px;width:16px}@keyframes spin{to{transform:rotate(360deg)}}.rules-card ol{display:grid;gap:4px;list-style:none;margin:0;padding:0}.rules-card li{align-items:flex-start;border-bottom:1px solid #edf0f4;display:flex;gap:11px;padding:13px 2px}.rules-card li:last-child{border:0}.rules-card li>span{align-items:center;background:#f3f6fa;border-radius:7px;color:#61718a;display:flex;height:32px;justify-content:center;width:32px}.rules-card strong{font-size:12px}.rules-card li p{color:#7b8799;font-size:10px;line-height:1.55;margin:4px 0 0}.result-card{align-items:center;border-color:#bfe6d6;display:grid;gap:16px;grid-template-columns:auto minmax(250px,1fr) auto;margin-top:16px}.result-check{align-items:center;background:#e6f8f1;border-radius:50%;color:#079e6b;display:flex;height:48px;justify-content:center;width:48px}.result-card h2{margin-bottom:5px}.result-card p{color:#617086;font-size:11px;margin:0;overflow-wrap:anywhere}.result-card dl{display:flex;gap:22px;margin:0}.result-card dl div{display:grid;gap:4px;text-align:center}.result-card dt{color:#8792a3;font-size:9px}.result-card dd{font-size:14px;font-weight:800;margin:0}@media(max-width:1100px){.local-merge-layout{grid-template-columns:1fr}.result-card{grid-template-columns:auto 1fr}.result-card dl{grid-column:1/-1;justify-content:space-around;width:100%}}@media(max-width:650px){.local-merge-form{grid-template-columns:1fr}.merge-field.wide{grid-column:auto}.result-card dl{display:grid;grid-template-columns:repeat(2,1fr)}}
</style>
