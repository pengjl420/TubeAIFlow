<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  AlertTriangle,
  AudioLines,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Clock3,
  Copy,
  Download,
  FileAudio,
  FileText,
  FolderOpen,
  Mic2,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Settings2,
  SlidersHorizontal,
  Trash2,
  Upload,
  Volume2,
  X,
} from 'lucide-vue-next'

import { API_BASE_URL } from '../../api/client'
import {
  createVoice,
  deleteVoice,
  duplicateVoice as duplicateVoiceProfile,
  listVoices,
  updateVoice,
  type VoiceProfile,
  type VoiceTtsEngine,
} from '../../api/voices'
import AudioPlayer from '../../components/common/AudioPlayer.vue'
import { confirmAction, showToast } from '../../services/feedback'

const voices = ref<VoiceProfile[]>([])
const selectedVoiceId = ref('')
const drawerOpen = ref(false)
const name = ref('')
const ttsEngine = ref<VoiceTtsEngine>('qwen3_tts')
const referenceAudioText = ref('')
const cosyvoiceSpeed = ref(1)
const audioFile = ref<File | null>(null)
const audioInput = ref<HTMLInputElement | null>(null)
const batchInput = ref<HTMLInputElement | null>(null)
const loading = ref(false)
const saving = ref(false)
const importing = ref(false)
const error = ref('')
const message = ref('')
const search = ref('')
const engineFilter = ref('')
const textFilter = ref('')
const page = ref(1)
const pageSize = ref(10)
const onlyExceptions = ref(false)
const recentOnly = ref(false)
const tags = ref<string[]>([])
const newTag = ref('')

const selectedVoice = computed(() => voices.value.find((item) => item.id === selectedVoiceId.value) || null)
const filteredVoices = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return voices.value.filter((voice) => {
    const matchesKeyword = !keyword || [voice.name, voice.original_filename, engineLabel(voice.tts_engine)]
      .some((value) => value.toLowerCase().includes(keyword))
    const matchesEngine = !engineFilter.value || voice.tts_engine === engineFilter.value
    const hasText = Boolean(voice.reference_audio_text.trim())
    const matchesText = !textFilter.value || (textFilter.value === 'ready' ? hasText : !hasText)
    const matchesException = !onlyExceptions.value || !hasText
    const matchesRecent = !recentOnly.value || new Date(voice.created_at).getTime() >= Date.now() - 7 * 24 * 60 * 60 * 1000
    return matchesKeyword && matchesEngine && matchesText && matchesException && matchesRecent
  })
})
const totalPages = computed(() => Math.max(1, Math.ceil(filteredVoices.value.length / pageSize.value)))
const pagedVoices = computed(() => {
  if (page.value > totalPages.value) page.value = totalPages.value
  const start = (page.value - 1) * pageSize.value
  return filteredVoices.value.slice(start, start + pageSize.value)
})
const textReadyCount = computed(() => voices.value.filter((voice) => voice.reference_audio_text.trim()).length)
const exceptionCount = computed(() => voices.value.length - textReadyCount.value)
const recentCount = computed(() => {
  const threshold = Date.now() - 7 * 24 * 60 * 60 * 1000
  return voices.value.filter((voice) => new Date(voice.created_at).getTime() >= threshold).length
})
const drawerTitle = computed(() => selectedVoice.value ? '音色编辑' : '新建音色')
const previewUrl = computed(() => {
  if (audioFile.value) return URL.createObjectURL(audioFile.value)
  return selectedVoice.value ? audioUrl(selectedVoice.value) : ''
})

function engineLabel(engine: VoiceTtsEngine) {
  return engine === 'cosyvoice' ? 'CosyVoice' : 'Qwen3-TTS'
}

function audioUrl(voice: VoiceProfile) {
  return `${API_BASE_URL}/voices/${voice.id}/audio?v=${encodeURIComponent(voice.updated_at)}`
}

function formatDate(value: string) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })}\n${date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })}`
}

function filenameWithoutExtension(filename: string) {
  return filename.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim() || '未命名音色'
}

async function load(selectFirst = false) {
  loading.value = true
  error.value = ''
  try {
    voices.value = await listVoices()
    if (selectFirst && voices.value.length && !selectedVoiceId.value) openEditor(voices.value[0])
  } catch (err) {
    error.value = err instanceof Error ? err.message : '音色列表加载失败'
  } finally {
    loading.value = false
  }
}

function openEditor(voice: VoiceProfile) {
  selectedVoiceId.value = voice.id
  name.value = voice.name
  ttsEngine.value = voice.tts_engine
  referenceAudioText.value = voice.reference_audio_text
  cosyvoiceSpeed.value = voice.cosyvoice_speed
  tags.value = [...(voice.tags || [])]
  newTag.value = ''
  audioFile.value = null
  error.value = ''
  message.value = ''
  drawerOpen.value = true
}

function openCreate() {
  selectedVoiceId.value = ''
  name.value = ''
  ttsEngine.value = 'qwen3_tts'
  referenceAudioText.value = ''
  cosyvoiceSpeed.value = 1
  tags.value = []
  newTag.value = ''
  audioFile.value = null
  error.value = ''
  message.value = ''
  drawerOpen.value = true
}

function closeDrawer() {
  drawerOpen.value = false
  audioFile.value = null
}

function selectAudio(event: Event) {
  audioFile.value = (event.target as HTMLInputElement).files?.[0] || null
}

async function save() {
  if (!name.value.trim()) return void (error.value = '请输入音色名称')
  if (!selectedVoiceId.value && !audioFile.value) return void (error.value = '请选择参考音频文件')
  if (ttsEngine.value === 'cosyvoice' && !referenceAudioText.value.trim()) {
    return void (error.value = 'CosyVoice 需要填写参考音频逐字稿')
  }
  if (!Number.isFinite(cosyvoiceSpeed.value) || cosyvoiceSpeed.value < 0.5 || cosyvoiceSpeed.value > 2) {
    return void (error.value = '语速必须在 0.5 到 2.0 之间')
  }
  saving.value = true
  error.value = ''
  try {
    const input = {
      name: name.value.trim(),
      tts_engine: ttsEngine.value,
      reference_audio_text: referenceAudioText.value.trim(),
      cosyvoice_speed: cosyvoiceSpeed.value,
      tags: tags.value,
      file: audioFile.value,
    }
    const saved = selectedVoiceId.value
      ? await updateVoice(selectedVoiceId.value, input)
      : await createVoice(input)
    selectedVoiceId.value = saved.id
    message.value = '音色已保存'
    await load()
    showToast({ title: '保存成功', description: `“${saved.name}”的音色配置已更新。`, tone: 'success' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '音色保存失败'
  } finally {
    saving.value = false
  }
}

async function duplicateVoice() {
  if (!selectedVoice.value) return
  saving.value = true
  error.value = ''
  try {
    const duplicated = await duplicateVoiceProfile(selectedVoice.value.id)
    await load()
    openEditor(voices.value.find((voice) => voice.id === duplicated.id) || duplicated)
    showToast({ title: '音色已复制', description: `已创建“${duplicated.name}”。`, tone: 'success' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '复制音色失败'
  } finally {
    saving.value = false
  }
}

function showCompatibility() {
  showToast({
    title: '引擎兼容说明',
    description: 'Qwen3-TTS 支持无参考文本克隆；CosyVoice 必须填写参考音频逐字稿。两种引擎均建议使用清晰、无背景音乐的 WAV、MP3、FLAC 或 M4A 音频。',
    tone: 'info',
  })
}

function showRecent() {
  recentOnly.value = true
  page.value = 1
}

async function remove(voice: VoiceProfile) {
  const confirmed = await confirmAction({
    eyebrow: '删除参考音色',
    title: `删除音色“${voice.name}”？`,
    description: '删除后，新项目和批量任务将无法再选择这份参考音色。',
    detail: '已经生成的配音与项目输出不会受到影响。',
    confirmText: '删除音色',
    tone: 'danger',
  })
  if (!confirmed) return
  try {
    await deleteVoice(voice.id)
    if (selectedVoiceId.value === voice.id) closeDrawer()
    await load()
    showToast({ title: '参考音色已删除', description: `“${voice.name}”已从音色库移除。`, tone: 'success' })
  } catch (err) {
    error.value = err instanceof Error ? err.message : '音色删除失败'
  }
}

async function batchImport(event: Event) {
  const files = Array.from((event.target as HTMLInputElement).files || [])
  if (!files.length) return
  importing.value = true
  error.value = ''
  let completed = 0
  for (const file of files) {
    try {
      await createVoice({
        name: filenameWithoutExtension(file.name),
        tts_engine: 'qwen3_tts',
        reference_audio_text: '',
        cosyvoice_speed: 1,
        tags: [],
        file,
      })
      completed += 1
    } catch (err) {
      error.value = `${file.name} 导入失败：${err instanceof Error ? err.message : '未知错误'}`
      break
    }
  }
  importing.value = false
  if (batchInput.value) batchInput.value.value = ''
  await load()
  if (completed) showToast({ title: '批量导入完成', description: `已成功导入 ${completed} 个音色。`, tone: 'success' })
}

function resetFilters() {
  search.value = ''
  engineFilter.value = ''
  textFilter.value = ''
  onlyExceptions.value = false
  recentOnly.value = false
  page.value = 1
}

function addTag() {
  const value = newTag.value.trim().slice(0, 20)
  if (value && !tags.value.includes(value) && tags.value.length < 8) tags.value.push(value)
  newTag.value = ''
}

function removeTag(tag: string) {
  tags.value = tags.value.filter((item) => item !== tag)
}

onMounted(() => load(true))
onBeforeUnmount(() => { if (previewUrl.value.startsWith('blob:')) URL.revokeObjectURL(previewUrl.value) })
</script>

<template>
  <section class="voice-center" :class="{ 'has-drawer': drawerOpen }">
    <header class="voice-page-header">
      <div>
        <h1>音色中心</h1>
        <p>统一管理配音音色、参考音频与引擎兼容状态</p>
      </div>
      <div class="voice-header-actions">
        <button class="voice-primary" type="button" @click="openCreate"><Pencil :size="17" /> 新建音色</button>
        <button class="voice-outline" type="button" :disabled="importing" @click="batchInput?.click()">
          <Upload :size="17" /> {{ importing ? '导入中…' : '批量导入' }}
        </button>
        <input ref="batchInput" hidden multiple type="file" accept="audio/wav,audio/mpeg,audio/flac,audio/mp4,.wav,.mp3,.flac,.m4a" @change="batchImport" />
        <button class="voice-help" type="button" @click="showCompatibility"><CircleHelp :size="17" /> 引擎兼容说明</button>
      </div>
    </header>

    <div class="voice-metrics">
      <article class="voice-metric metric-blue"><span><Mic2 /></span><div><small>总音色数</small><strong>{{ voices.length }}</strong><em>来自音色库</em></div><i></i></article>
      <article class="voice-metric metric-green"><span><Check /></span><div><small>可用音色</small><strong>{{ voices.length }}</strong><em>占比 {{ voices.length ? 100 : 0 }}%</em></div><i></i></article>
      <article class="voice-metric metric-orange"><span><AlertTriangle /></span><div><small>待补全参考文本</small><strong>{{ exceptionCount }}</strong><em>{{ exceptionCount ? '建议尽快补全' : '状态正常' }}</em></div><i></i></article>
      <article class="voice-metric metric-purple"><span><FolderOpen /></span><div><small>有参考文本</small><strong>{{ textReadyCount }}</strong><em>占比 {{ voices.length ? Math.round(textReadyCount / voices.length * 100) : 0 }}%</em></div><i></i></article>
      <article class="voice-metric metric-cyan"><span><AudioLines /></span><div><small>近 7 日新增</small><strong>{{ recentCount }}</strong><em>实时统计</em></div><i></i></article>
    </div>

    <div class="voice-toolbar">
      <label class="voice-search"><Search :size="16" /><input v-model="search" type="search" placeholder="搜索音色名称、文件或引擎…" @input="page = 1" /></label>
      <select v-model="engineFilter" @change="page = 1"><option value="">配音引擎</option><option value="qwen3_tts">Qwen3-TTS</option><option value="cosyvoice">CosyVoice</option></select>
      <select @change="page = 1"><option>语言</option><option>普通话</option></select>
      <select @change="page = 1"><option>可用性</option><option>可用</option></select>
      <select v-model="textFilter" @change="page = 1"><option value="">参考文本状态</option><option value="ready">已上传参考文本</option><option value="missing">缺少参考文本</option></select>
      <label class="exception-toggle"><span>只看异常</span><input v-model="onlyExceptions" type="checkbox" @change="page = 1" /><i></i></label>
      <button class="icon-button" title="刷新" type="button" @click="load()"><RefreshCw :size="16" /></button>
      <button class="icon-button" title="重置筛选" type="button" @click="resetFilters"><Settings2 :size="16" /></button>
    </div>

    <div class="voice-table-card">
      <div class="voice-table-head">
        <span>音色名称</span><span>配音引擎</span><span>原始文件</span><span>参考文本状态</span><span>可用性</span><span>使用项目数</span><span>试听</span><span>最近更新</span><span>操作</span>
      </div>
      <div v-if="loading" class="voice-table-empty"><RefreshCw class="spin" :size="22" /> 正在加载音色…</div>
      <div v-else-if="!pagedVoices.length" class="voice-table-empty"><Mic2 :size="25" /><strong>没有匹配的音色</strong><button type="button" @click="resetFilters">清除筛选</button></div>
      <article v-for="(voice, index) in pagedVoices" v-else :key="voice.id" class="voice-table-row" :class="{ selected: voice.id === selectedVoiceId }" @click="openEditor(voice)">
        <span class="voice-name"><i :class="`avatar-${index % 5}`"><Mic2 :size="15" /></i><strong>{{ voice.name }}</strong></span>
        <span>{{ engineLabel(voice.tts_engine) }}</span>
        <span class="voice-file"><strong>{{ voice.original_filename }}</strong><small>音频文件</small></span>
        <span><b class="voice-badge" :class="voice.reference_audio_text.trim() ? 'green' : 'orange'">{{ voice.reference_audio_text.trim() ? '已上传参考文本' : '缺少参考文本' }}</b></span>
        <span><b class="voice-badge green">可用</b></span>
        <span>{{ voice.usage_count || 0 }}</span>
        <span class="table-audio" @click.stop><AudioPlayer :src="audioUrl(voice)" /></span>
        <span class="voice-date">{{ formatDate(voice.updated_at) }}</span>
        <span class="voice-row-actions" @click.stop><button type="button" @click="openEditor(voice)">编辑</button><button type="button" @click="openEditor(voice)">更多 <ChevronDown :size="12" /></button></span>
      </article>
      <footer class="voice-pagination">
        <span>共 {{ filteredVoices.length }} 条</span>
        <div><button type="button" :disabled="page <= 1" @click="page--"><ChevronLeft :size="15" /></button><button class="active" type="button">{{ page }}</button><span>/ {{ totalPages }}</span><button type="button" :disabled="page >= totalPages" @click="page++"><ChevronRight :size="15" /></button></div>
        <select v-model="pageSize"><option :value="10">10 条/页</option><option :value="20">20 条/页</option><option :value="50">50 条/页</option></select>
      </footer>
    </div>

    <div class="voice-bottom-cards">
      <article><span class="red"><AlertTriangle /></span><div><small>缺少参考文本</small><strong>{{ exceptionCount }}</strong><button type="button" @click="onlyExceptions = true">查看详情 <ChevronRight :size="13" /></button></div></article>
      <article><span class="orange"><FileText /></span><div><small>文本已就绪</small><strong>{{ textReadyCount }}</strong><button type="button" @click="textFilter = 'ready'">查看详情 <ChevronRight :size="13" /></button></div></article>
      <article><span class="blue"><Clock3 /></span><div><small>最近新增</small><strong>{{ recentCount }}</strong><button type="button" @click="showRecent">查看详情 <ChevronRight :size="13" /></button></div></article>
    </div>

    <Transition name="drawer">
      <aside v-if="drawerOpen" class="voice-drawer">
        <header><div><strong>{{ drawerTitle }}</strong><b>可用</b></div><button type="button" aria-label="关闭" @click="closeDrawer"><X :size="18" /></button></header>
        <div class="drawer-content">
          <section class="drawer-section"><h2><i>1</i>基本信息</h2>
            <label class="drawer-field wide"><span>音色名称</span><input v-model="name" maxlength="120" placeholder="例如：纪录片女声" /></label>
            <div class="drawer-field-row"><label class="drawer-field"><span>配音引擎</span><select v-model="ttsEngine"><option value="qwen3_tts">Qwen3-TTS</option><option value="cosyvoice">CosyVoice</option></select></label><label class="drawer-field"><span>语言</span><select><option>普通话</option></select></label></div>
            <div class="tag-row"><span>标签</span><div><b v-for="tag in tags" :key="tag">{{ tag }} <button type="button" :aria-label="`删除标签 ${tag}`" @click="removeTag(tag)"><X :size="10" /></button></b><input v-model="newTag" maxlength="20" placeholder="添加标签" @keyup.enter="addTag" /><button type="button" aria-label="添加标签" :disabled="!newTag.trim() || tags.length >= 8" @click="addTag"><Plus :size="12" /></button></div></div>
          </section>

          <section class="drawer-section"><h2><i>2</i>参考音频</h2>
            <div class="reference-card">
              <div class="reference-file"><span><strong>{{ audioFile?.name || selectedVoice?.original_filename || '尚未选择音频' }}</strong><small>{{ audioFile ? `${(audioFile.size / 1024 / 1024).toFixed(1)} MB` : 'WAV / MP3 / FLAC / M4A' }}</small></span><div><button type="button" @click="audioInput?.click()">{{ selectedVoice ? '更换音频' : '选择音频' }}</button><a v-if="selectedVoice" :href="audioUrl(selectedVoice)" :download="selectedVoice.original_filename"><Download :size="14" /> 下载原文件</a></div></div>
              <AudioPlayer v-if="previewUrl" :key="previewUrl" :src="previewUrl" />
              <button v-else class="audio-drop" type="button" @click="audioInput?.click()"><FileAudio :size="25" /><span>选择参考音频文件</span></button>
              <input ref="audioInput" hidden type="file" accept="audio/wav,audio/mpeg,audio/flac,audio/mp4,.wav,.mp3,.flac,.m4a" @change="selectAudio" />
            </div>
          </section>

          <section class="drawer-section"><h2><i>3</i>参考文本 <small>{{ referenceAudioText.length }}/300</small></h2>
            <textarea v-model="referenceAudioText" maxlength="300" rows="4" placeholder="填写参考音频中实际说出的文字"></textarea>
            <p class="text-check"><Check :size="13" /> {{ referenceAudioText.trim() ? '已填写参考文本' : '建议补充参考文本以提升克隆效果' }}</p>
          </section>

          <section class="drawer-section"><h2><i>4</i>音频检测</h2>
            <div class="quality-grid"><div><span>文件检测</span><strong>通过</strong></div><div><span>格式支持</span><strong>兼容</strong></div><div><span>参考文本</span><strong>{{ referenceAudioText.trim() ? '良好' : '待补充' }}</strong></div><div><span>语速</span><strong>{{ ttsEngine === 'cosyvoice' ? cosyvoiceSpeed.toFixed(2) : '自动' }}</strong></div></div>
          </section>

          <section v-if="ttsEngine === 'cosyvoice'" class="drawer-section"><h2><i>5</i>引擎参数</h2><label class="speed-control"><span>语速</span><input v-model.number="cosyvoiceSpeed" type="range" min="0.5" max="2" step="0.05" /><b>{{ cosyvoiceSpeed.toFixed(2) }}×</b></label></section>
          <section class="drawer-section"><h2><i>{{ ttsEngine === 'cosyvoice' ? 6 : 5 }}</i>引擎兼容提示</h2><div class="compatibility"><p><span></span>当前引擎兼容：<strong>{{ engineLabel(ttsEngine) }}</strong></p><p><em></em>建议保留清晰、无背景音乐的参考音频。</p></div></section>
          <section v-if="selectedVoice" class="drawer-section"><h2><i>{{ ttsEngine === 'cosyvoice' ? 7 : 6 }}</i>关联项目</h2><div class="project-relation"><span>当前绑定项目：<strong>{{ selectedVoice.usage_count || 0 }}</strong></span><span>运行中项目：<strong>{{ selectedVoice.running_project_count || 0 }}</strong></span></div></section>
        </div>
        <p v-if="error" class="drawer-error">{{ error }}</p><p v-if="message" class="drawer-success">{{ message }}</p>
        <footer><button v-if="selectedVoice" class="delete" type="button" @click="remove(selectedVoice)"><Trash2 :size="15" /> 删除音色</button><span></span><button v-if="selectedVoice" class="copy" type="button" @click="duplicateVoice"><Copy :size="15" /> 复制音色</button><button class="save" type="button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存' }}</button></footer>
      </aside>
    </Transition>
  </section>
</template>

<style scoped>
.voice-center{color:#182235;min-width:0;transition:padding-right .2s}.voice-center.has-drawer{padding-right:470px}.voice-page-header{align-items:center;display:flex;justify-content:space-between;margin:0 0 18px}.voice-page-header h1{font-size:26px;letter-spacing:-.03em;margin:0 0 3px}.voice-page-header p{color:#69758a;font-size:13px;margin:0}.voice-header-actions{display:flex;gap:10px}.voice-header-actions button,.reference-file button,.reference-file a{align-items:center;border-radius:7px;display:inline-flex;font-size:12px;font-weight:650;gap:6px;justify-content:center;min-height:38px;padding:8px 13px}.voice-primary{background:#075bf5;color:#fff}.voice-outline{background:#fff;border:1px solid #87affd;color:#075bf5}.voice-help{background:#fff;border:1px solid #dfe5ee;color:#48556b}.voice-metrics{display:grid;gap:14px;grid-template-columns:repeat(5,minmax(0,1fr));margin-bottom:16px}.voice-metric{align-items:center;background:#fff;border:1px solid #e3e8f0;border-radius:12px;display:flex;gap:12px;min-height:106px;padding:16px;position:relative}.voice-metric>span{align-items:center;background:#eaf1ff;border-radius:50%;color:#1465f5;display:flex;flex:none;height:44px;justify-content:center;width:44px}.voice-metric svg{height:21px}.voice-metric>div{display:grid;gap:1px}.voice-metric small{color:#69758a;font-size:12px}.voice-metric strong{font-size:22px}.voice-metric em{color:#8a95a7;font-size:10px;font-style:normal;white-space:nowrap}.metric-green>span{background:#e4f8f0;color:#0aaa76}.metric-orange>span{background:#fff0e1;color:#f78a12}.metric-purple>span{background:#f0eaff;color:#7654e9}.metric-cyan>span{background:#e3f8fa;color:#0baab7}.voice-metric>i{border-bottom:2px solid currentColor;color:#1767f6;height:18px;margin-left:auto;transform:skewY(-22deg);width:40px}.metric-green>i{color:#10b57c}.metric-orange>i{color:#f49017}.metric-purple>i{color:#7654e9}.metric-cyan>i{color:#0babb8}.voice-toolbar{align-items:center;display:flex;gap:9px;margin-bottom:10px}.voice-search{align-items:center;background:#fff;border:1px solid #dfe5ed;border-radius:7px;color:#8591a5;display:flex;height:36px;padding:0 10px;width:220px}.voice-search input{border:0;box-shadow:none!important;font-size:11px;min-height:32px;padding:0 7px;width:100%}.voice-toolbar select{background-color:#fff;border:1px solid #dfe5ed;border-radius:7px;color:#526078;font-size:11px;height:36px;min-width:98px;padding-left:10px}.exception-toggle{align-items:center;color:#657188;display:flex;font-size:11px;gap:7px;margin-left:auto;white-space:nowrap}.exception-toggle input{display:none}.exception-toggle i{background:#b4bdca;border-radius:20px;height:20px;position:relative;width:34px}.exception-toggle i:after{background:#fff;border-radius:50%;content:'';height:16px;left:2px;position:absolute;top:2px;transition:.15s;width:16px}.exception-toggle input:checked+i{background:#075bf5}.exception-toggle input:checked+i:after{left:16px}.icon-button{align-items:center;background:#fff;border:1px solid #dfe5ed;border-radius:7px;color:#526078;display:flex;height:36px;justify-content:center;width:36px}.voice-table-card{background:#fff;border:1px solid #e1e6ee;border-radius:11px;overflow:hidden}.voice-table-head,.voice-table-row{align-items:center;display:grid;gap:10px;grid-template-columns:minmax(135px,1.35fr) 92px minmax(115px,1.2fr) 112px 62px 72px minmax(155px,1.25fr) 84px 106px;padding:0 12px}.voice-table-head{background:#f7f9fc;color:#68748a;font-size:10px;min-height:38px}.voice-table-row{border-top:1px solid #edf0f5;cursor:pointer;font-size:10px;min-height:58px;transition:.15s}.voice-table-row:hover,.voice-table-row.selected{background:#f8fbff}.voice-table-row>span{min-width:0}.voice-name{align-items:center;display:flex;gap:8px}.voice-name i{align-items:center;background:#2d6cf3;border-radius:50%;color:#fff;display:flex;flex:none;height:27px;justify-content:center;width:27px}.voice-name i.avatar-1{background:#129adf}.voice-name i.avatar-2{background:#844be8}.voice-name i.avatar-3{background:#f58312}.voice-name i.avatar-4{background:#f3a20b}.voice-name strong,.voice-file strong{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.voice-file small{background:#eef1f5;border-radius:3px;color:#69758a;display:inline-block;font-size:8px;margin-top:2px;padding:1px 4px}.voice-badge{border-radius:5px;display:inline-flex;font-size:9px;padding:3px 6px;white-space:nowrap}.voice-badge.green{background:#e4f8f0;color:#09a873}.voice-badge.orange{background:#fff0df;color:#ee8712}.voice-date{white-space:pre-line}.voice-row-actions{display:flex;gap:4px}.voice-row-actions button{align-items:center;background:#fff;border:1px solid #d5e1f6;border-radius:5px;color:#075bf5;display:flex;font-size:9px;gap:2px;padding:4px 6px}.table-audio :deep(.audio-player){background:transparent;border:0;gap:5px;grid-template-columns:27px minmax(45px,1fr) 31px;min-height:34px;padding:0}.table-audio :deep(.audio-player-toggle){height:27px;width:27px}.table-audio :deep(.audio-player-time:first-of-type){display:none}.table-audio :deep(.audio-player-time){font-size:8px}.voice-table-empty{align-items:center;color:#7a8698;display:flex;flex-direction:column;gap:8px;justify-content:center;min-height:220px}.voice-table-empty strong{color:#435067}.voice-table-empty button{background:none;color:#075bf5}.voice-pagination{align-items:center;border-top:1px solid #edf0f5;color:#718096;display:flex;font-size:10px;justify-content:flex-end;min-height:46px;padding:0 14px}.voice-pagination>span{margin-right:auto}.voice-pagination>div{align-items:center;display:flex;gap:5px}.voice-pagination button{align-items:center;background:#fff;border:1px solid #dfe5ed;border-radius:5px;color:#59677c;display:flex;height:26px;justify-content:center;min-width:26px}.voice-pagination button.active{background:#075bf5;color:#fff}.voice-pagination select{background-color:#fff;border:1px solid #dfe5ed;border-radius:5px;font-size:10px;height:28px;margin-left:14px}.voice-bottom-cards{display:grid;gap:14px;grid-template-columns:repeat(3,1fr);margin-top:16px}.voice-bottom-cards article{align-items:center;background:#fff;border:1px solid #e2e7ef;border-radius:11px;display:flex;gap:13px;min-height:96px;padding:15px}.voice-bottom-cards article>span{align-items:center;background:#ffe9eb;border-radius:50%;color:#f24e5b;display:flex;height:42px;justify-content:center;width:42px}.voice-bottom-cards article>span.orange{background:#fff1e1;color:#f18b12}.voice-bottom-cards article>span.blue{background:#e9f1ff;color:#1465f5}.voice-bottom-cards article>div{display:grid}.voice-bottom-cards small{color:#69758a}.voice-bottom-cards strong{font-size:20px}.voice-bottom-cards button{align-items:center;background:none;color:#65748b;display:flex;font-size:9px;gap:3px;margin-top:5px;padding:0}.voice-drawer{background:#fff;border-left:1px solid #e2e7ef;bottom:0;box-shadow:-8px 0 22px rgba(26,42,70,.06);display:flex;flex-direction:column;position:fixed;right:0;top:72px;width:470px;z-index:12}.voice-drawer>header{align-items:center;border-bottom:1px solid #e7ebf1;display:flex;justify-content:space-between;min-height:50px;padding:0 18px}.voice-drawer>header>div{align-items:center;display:flex;gap:8px}.voice-drawer>header strong{font-size:15px}.voice-drawer>header b{background:#e3f8ef;border-radius:5px;color:#09a873;font-size:9px;padding:3px 7px}.voice-drawer>header button{background:none;color:#647086}.drawer-content{flex:1;overflow:auto;padding:0 16px}.drawer-section{border-bottom:1px solid #e8ecf2;padding:12px 0}.drawer-section h2{align-items:center;display:flex;font-size:11px;margin:0 0 11px}.drawer-section h2 i{align-items:center;background:#075bf5;border-radius:4px;color:#fff;display:inline-flex;font-size:8px;font-style:normal;height:16px;justify-content:center;margin-right:7px;width:16px}.drawer-section h2 small{color:#7a8699;font-size:9px;font-weight:500;margin-left:auto}.drawer-field-row{display:grid;gap:14px;grid-template-columns:1fr 1fr}.drawer-field{align-items:center;display:grid;gap:9px;grid-template-columns:72px 1fr;margin-bottom:9px}.drawer-field span,.tag-row>span{color:#526078;font-size:10px}.drawer-field input,.drawer-field select,.drawer-section textarea{background-color:#fff;border:1px solid #dce3ed;border-radius:6px;font-size:10px;min-height:33px;padding:7px 9px;width:100%}.drawer-field-row .drawer-field{grid-template-columns:62px 1fr}.tag-row{align-items:center;display:grid;grid-template-columns:72px 1fr}.tag-row>div{align-items:center;border:1px solid #dce3ed;border-radius:6px;display:flex;gap:4px;min-height:33px;padding:4px}.tag-row b{align-items:center;background:#f0f2f6;border-radius:4px;color:#58657a;display:flex;font-size:9px;gap:3px;padding:3px 6px}.tag-row button{align-items:center;background:none;color:#758196;display:flex}.reference-card{border:1px solid #dfe5ed;border-radius:7px;padding:9px}.reference-file{align-items:center;display:flex;justify-content:space-between;margin-bottom:8px}.reference-file>span{display:grid}.reference-file strong{font-size:10px}.reference-file small{color:#7b8799;font-size:8px}.reference-file>div{display:flex;gap:5px}.reference-file button,.reference-file a{background:#fff;border:1px solid #8cb3fc;color:#075bf5;font-size:9px;min-height:25px;padding:4px 7px}.reference-card :deep(.audio-player){background:#fff;border:0;padding-inline:0}.audio-drop{align-items:center;background:#f8faff;border:1px dashed #b9c9e8;border-radius:7px;color:#5e7bab;display:flex;gap:8px;justify-content:center;min-height:55px;width:100%}.audio-drop span{font-size:10px}.drawer-section textarea{line-height:1.55;resize:none}.text-check{align-items:center;color:#08a873;display:flex;font-size:9px;gap:5px;margin:5px 0 0}.quality-grid{display:grid;gap:8px;grid-template-columns:repeat(4,1fr)}.quality-grid>div{background:#fafbfc;border:1px solid #e2e7ef;border-radius:7px;display:grid;gap:3px;padding:8px;text-align:center}.quality-grid span{color:#667288;font-size:8px}.quality-grid strong{color:#08a873;font-size:11px}.compatibility{border:1px solid #dfe5ed;border-radius:7px;padding:8px 10px}.compatibility p{color:#536078;font-size:9px;margin:3px 0}.compatibility span,.compatibility em{background:#09af79;border-radius:50%;display:inline-block;height:6px;margin-right:6px;width:6px}.compatibility em{background:#f39a18}.speed-control{align-items:center;display:grid;font-size:10px;gap:9px;grid-template-columns:42px 1fr 38px}.project-relation{display:flex;font-size:9px;justify-content:space-between}.project-relation strong{margin-left:6px}.drawer-error,.drawer-success{background:#fff1f1;color:#d4444f;font-size:10px;margin:0;padding:8px 16px}.drawer-success{background:#eaf9f3;color:#079a69}.voice-drawer>footer{align-items:center;border-top:1px solid #e3e8ef;display:flex;gap:10px;min-height:68px;padding:10px 16px}.voice-drawer>footer span{flex:1}.voice-drawer>footer button{align-items:center;background:#fff;border:1px solid #d8e1ef;border-radius:7px;display:flex;font-size:10px;gap:5px;justify-content:center;min-height:36px;padding:7px 16px}.voice-drawer>footer .delete{border-color:#ff9fa5;color:#ef4d59}.voice-drawer>footer .copy{border-color:#9dbafb;color:#075bf5}.voice-drawer>footer .save{background:#075bf5;border-color:#075bf5;color:#fff;min-width:120px}.drawer-enter-active,.drawer-leave-active{transition:transform .2s}.drawer-enter-from,.drawer-leave-to{transform:translateX(100%)}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:1450px){.voice-center.has-drawer{padding-right:0}.voice-drawer{box-shadow:-18px 0 45px rgba(25,42,72,.14)}.voice-metrics{grid-template-columns:repeat(3,1fr)}.voice-toolbar{flex-wrap:wrap}.exception-toggle{margin-left:0}.voice-table-card{overflow-x:auto}.voice-table-head,.voice-table-row{min-width:1050px}}
@media(max-width:900px){.voice-center.has-drawer{padding-right:0}.voice-drawer{top:58px;width:min(470px,100%)}.voice-page-header{align-items:flex-start;gap:12px}.voice-header-actions{flex-wrap:wrap;justify-content:flex-end}.voice-metrics{grid-template-columns:repeat(2,1fr)}.voice-bottom-cards{grid-template-columns:1fr}}
@media(max-width:680px){.voice-page-header{display:block}.voice-header-actions{justify-content:flex-start;margin-top:12px}.voice-header-actions .voice-help{display:none}.voice-metrics{grid-template-columns:1fr 1fr}.voice-metric{min-height:90px;padding:11px}.voice-metric:nth-child(5){grid-column:1/-1}.voice-toolbar select{display:none}.voice-search{flex:1}.voice-drawer{bottom:64px}.quality-grid{grid-template-columns:1fr 1fr}.voice-drawer>footer .copy{display:none}}
</style>
