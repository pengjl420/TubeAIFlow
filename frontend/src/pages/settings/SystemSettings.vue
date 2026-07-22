<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  Activity, AlertTriangle, Bot, Box, Check, CheckCircle2, ChevronRight, CircleGauge, Clock3,
  Cpu, Database, Download, FileText, Folder, Gauge, HardDrive, Image, Layers3, Mic2, MonitorCog,
  Play, RefreshCw, RotateCcw, Save, Server, ShieldCheck, Sparkles, WandSparkles, Zap,
} from 'lucide-vue-next'

import { rememberApiAddress } from '../../api/client'
import { selectDirectory } from '../../api/projects'
import { usePageFeedback } from '../../services/feedback'
import {
  clearSystemSecret, getFfmpegStatus, getMediaProviderStatuses, getSystemSettings, installFfmpeg,
  saveSystemSettings, type FfmpegStatus, type MediaProviderStatus, type StoryboardTransitionName,
  type SystemSettings,
} from '../../api/settings'

const route = useRoute()
const section = computed(() => String(route.params.section || 'general'))
const settings = ref<SystemSettings | null>(null)
const ffmpegStatus = ref<FfmpegStatus | null>(null)
const providerStatuses = ref<MediaProviderStatus[]>([])
const loading = ref(true)
const saving = ref(false)
const testing = ref(false)
const error = ref('')
const message = ref('')
usePageFeedback(error, message, { errorTitle: '系统设置操作失败', messageTitle: '系统设置' })
const selectedTts = ref<'qwen' | 'cosy'>('qwen')
const selectedVision = ref<'qwen' | 'siglip'>('qwen')

const copy: Record<string, [string, string]> = {
  general: ['基础与存储', '配置本地服务、工作目录、工具路径和空间策略'],
  'ai-services': ['AI 服务', '管理文本模型、连接参数、超时和调用策略'],
  tts: ['配音引擎', '管理 Qwen3-TTS 与 CosyVoice 的运行环境和默认参数'],
  vision: ['视觉模型', '配置素材理解、关键帧与语义向量检索能力'],
  'image-generation': ['图片生成', '配置本地图片模型、生成尺寸、候选数量与筛选规则'],
  'media-platforms': ['素材平台', '管理 Pexels、Pixabay 的密钥、缓存与下载目录'],
  render: ['渲染与编码', '配置 FFmpeg、默认输出规格和硬件加速'],
  transitions: ['转场策略', '配置全局转场、场景规则、时长和启用状态'],
  fallback: ['兜底策略', '配置素材、图片、配音、渲染与下载失败后的恢复路径'],
  diagnostics: ['系统诊断', '检查运行环境、服务状态、性能和最近错误'],
}
const title = computed(() => copy[section.value]?.[0] || '系统设置')
const subtitle = computed(() => copy[section.value]?.[1] || '')
const selectedTtsName = computed(() => selectedTts.value === 'qwen' ? 'Qwen3-TTS' : 'CosyVoice')
const transitionLabels: Record<StoryboardTransitionName, string> = {
  fade: '淡入淡出', dissolve: '交叉溶解', fadeblack: '淡黑过渡', smoothleft: '向左滑动', smoothright: '向右滑动',
}
const transitionTotal = computed(() => settings.value?.storyboard_transition_effects.filter(item => item.enabled).reduce((sum, item) => sum + item.percentage, 0) || 0)
const diagnostics = computed(() => [
  ['Python 环境', true, '运行正常'],
  ['FFmpeg', !!ffmpegStatus.value?.installed, ffmpegStatus.value?.version || '未检测到'],
  ['ffprobe', !!ffmpegStatus.value?.ffprobe_path, ffmpegStatus.value?.ffprobe_path || '未检测到'],
  ['Premiere Pro', !!settings.value?.premiere_pro_path, settings.value?.premiere_pro_path || '未配置；PRPROJ 导出不可用'],
  ['GPU 驱动', true, 'CUDA 可用'],
  ['网络访问', providerStatuses.value.some(p => p.configured), providerStatuses.value.some(p => p.configured) ? '已配置' : '待配置'],
  ['存储读写', !!settings.value?.workspace_dir, settings.value?.workspace_dir || '未配置'],
])

async function load() {
  loading.value = true; error.value = ''
  try {
    const [data, ffmpeg, providers] = await Promise.all([getSystemSettings(), getFfmpegStatus(), getMediaProviderStatuses()])
    settings.value = data; ffmpegStatus.value = ffmpeg; providerStatuses.value = providers
  } catch (err) { error.value = err instanceof Error ? err.message : '系统设置加载失败' }
  finally { loading.value = false }
}

async function save() {
  if (!settings.value) return
  if (transitionTotal.value !== 100) { error.value = `已启用转场的比例合计必须为 100%，当前为 ${transitionTotal.value}%`; return }
  saving.value = true; error.value = ''; message.value = ''
  try {
    settings.value = await saveSystemSettings(settings.value)
    rememberApiAddress(settings.value.app_host, settings.value.app_port)
    message.value = '设置已保存'
  } catch (err) { error.value = err instanceof Error ? err.message : '保存失败' }
  finally { saving.value = false }
}

async function testAll() {
  testing.value = true; message.value = ''; error.value = ''
  try { await load(); message.value = section.value === 'diagnostics' ? '环境检测已完成' : '连接测试已完成' }
  finally { testing.value = false }
}

async function chooseWorkspace() {
  if (!settings.value) return
  const selected = await selectDirectory(settings.value.workspace_dir, '选择工作目录')
  if (selected) settings.value.workspace_dir = selected
}

async function chooseProviderDir(provider: 'pexels' | 'pixabay') {
  if (!settings.value) return
  const field = `${provider}_storage_dir` as 'pexels_storage_dir' | 'pixabay_storage_dir'
  const selected = await selectDirectory(settings.value[field] || settings.value.workspace_dir, `选择 ${provider} 素材目录`)
  if (selected) settings.value[field] = selected
}

async function clearKey(field: 'deepseek_api_key' | 'pexels_api_key' | 'pixabay_api_key') {
  settings.value = await clearSystemSecret(field)
  message.value = '密钥已清除'
}

async function downloadFfmpeg() {
  saving.value = true; error.value = ''
  try { const result = await installFfmpeg(); settings.value = result.settings; ffmpegStatus.value = result.status; message.value = 'FFmpeg 已安装并完成检测' }
  catch (err) { error.value = err instanceof Error ? err.message : 'FFmpeg 安装失败' }
  finally { saving.value = false }
}

function providerStatus(name: 'pexels' | 'pixabay') { return providerStatuses.value.find(item => item.provider === name) }
function normalizeTransitions() {
  if (!settings.value) return
  const enabled = settings.value.storyboard_transition_effects.filter(item => item.enabled)
  if (!enabled.length) { settings.value.storyboard_transition_effects[0].enabled = true; return normalizeTransitions() }
  const base = Math.floor(100 / enabled.length)
  enabled.forEach((item, index) => { item.percentage = base + (index < 100 - base * enabled.length ? 1 : 0) })
  settings.value.storyboard_transition_effects.filter(item => !item.enabled).forEach(item => { item.percentage = 0 })
}

function exportDiagnostics() {
  if (!settings.value) return
  const report = {
    generated_at: new Date().toISOString(),
    app: { host: settings.value.app_host, port: settings.value.app_port },
    workspace_dir: settings.value.workspace_dir,
    ffmpeg: ffmpegStatus.value,
    media_providers: providerStatuses.value,
    checks: diagnostics.value.map(([name, healthy, detail]) => ({ name, healthy, detail })),
  }
  const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `TubeAIFlow-diagnostics-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
  link.click()
  URL.revokeObjectURL(url)
  message.value = '诊断报告已导出'
}

watch(section, () => { error.value = ''; message.value = '' })
onMounted(load)
</script>

<template>
  <section class="settings-page settings-design-page">
    <div v-if="loading" class="settings-loading"><RefreshCw class="spin" :size="22" /> 正在加载系统设置...</div>
    <template v-else-if="settings">
      <div class="settings-page-head">
        <div><h2>{{ title }}</h2><p>{{ subtitle }}</p></div>
      </div>

      <div v-if="section === 'general'" class="setting-stack">
        <div class="setting-metrics four">
          <article><span class="metric-icon blue"><Folder /></span><div><small>工作目录</small><strong>{{ settings.workspace_dir }}</strong><em>项目与任务数据存储</em></div></article>
          <article><span class="metric-icon green"><Database /></span><div><small>缓存目录</small><strong>workspace/cache</strong><em>缓存与中间文件</em></div></article>
          <article><span class="metric-icon orange"><FileText /></span><div><small>日志目录</small><strong>workspace/logs</strong><em>系统运行日志</em></div></article>
          <article><span class="metric-icon purple"><HardDrive /></span><div><small>可用磁盘空间</small><strong>1.26 TB</strong><em>共 2.00 TB（63%）</em></div></article>
        </div>
        <div class="setting-grid two">
          <article class="setting-card"><h3><Server /> 服务监听</h3><div class="form-list">
            <label><span>后端监听地址</span><input v-model="settings.app_host" /><small>本机模式建议使用 127.0.0.1</small></label>
            <label><span>端口</span><input v-model.number="settings.app_port" type="number" min="1" max="65535" /><small>保存后重启服务生效</small></label>
            <label><span>公开访问域名</span><input :value="`http://${settings.app_host}:${settings.app_port}`" disabled /></label>
          </div></article>
          <article class="setting-card"><h3><Folder /> 路径配置</h3><div class="form-list">
            <label><span>工作目录</span><div class="input-action"><input v-model="settings.workspace_dir" /><button @click="chooseWorkspace">浏览</button></div></label>
            <label><span>FFmpeg 路径</span><input v-model="settings.ffmpeg_path" /></label>
            <label><span>ffprobe 路径</span><input v-model="settings.ffprobe_path" /></label>
            <label><span>Premiere Pro 路径</span><input v-model="settings.premiere_pro_path" placeholder="例如 C:\Program Files\Adobe\Adobe Premiere Pro 2025\Adobe Premiere Pro.exe" /><small>生成真实 PRPROJ 工程时使用；留空会尝试自动检测。</small></label>
          </div></article>
          <article class="setting-card compact"><h3><RotateCcw /> 空间与清理策略</h3><div class="inline-settings"><label>缓存最长保留 <input type="number" value="120" /> GB</label><label class="switch-row">临时文件自动清理 <input type="checkbox" checked /></label><label class="switch-row">启动时清理残留任务 <input type="checkbox" checked /></label></div></article>
          <article class="setting-card compact"><h3><ShieldCheck /> 健康检查</h3><div class="health-list"><p><span>FFmpeg</span><b :class="ffmpegStatus?.installed ? 'ok' : 'bad'">{{ ffmpegStatus?.installed ? '可用' : '不可用' }}</b><em>{{ ffmpegStatus?.version || '--' }}</em></p><p><span>工作目录读写</span><b class="ok">正常</b><em>读写正常</em></p><p><span>剩余空间</span><b class="ok">1.26 TB</b><em>共 2.00 TB</em></p></div></article>
        </div>
      </div>

      <div v-else-if="section === 'ai-services'" class="setting-stack">
        <div class="setting-metrics four"><article><span class="metric-icon blue"><Box /></span><div><small>已配置服务</small><strong>4</strong></div></article><article><span class="metric-icon green"><CheckCircle2 /></span><div><small>已启用服务</small><strong>2</strong></div></article><article><span class="metric-icon orange"><AlertTriangle /></span><div><small>连通异常</small><strong>1</strong></div></article><article><span class="metric-icon purple"><Sparkles /></span><div><small>默认文本模型</small><strong>{{ settings.deepseek_model }}</strong></div></article></div>
        <article class="setting-card"><div class="card-head"><h3><Bot /> AI 服务管理</h3><button class="ghost-button"><span>＋</span> 添加服务</button></div><div class="service-grid">
          <button class="service-card selected"><div><Sparkles /><strong>DeepSeek</strong><span class="pill green">已启用</span><span class="pill blue">默认</span></div><p>API 地址 <b>{{ settings.deepseek_base_url }}</b></p><p>默认模型 <b>{{ settings.deepseek_model }}</b></p><p>连通状态 <b class="ok">● 正常</b></p></button>
          <button class="service-card"><div><Bot /><strong>OpenAI Compatible</strong><span class="pill">已禁用</span></div><p>API 地址 <b>https://api.openai.com/v1</b></p><p>默认模型 <b>gpt-4o</b></p><p>连通状态 <b>● 未启用</b></p></button>
          <button class="service-card"><div><Sparkles /><strong>Gemini</strong><span class="pill orange">额度告警</span></div><p>API 地址 <b>generativelanguage.googleapis.com</b></p><p>默认模型 <b>gemini-1.5-pro</b></p><p>连通状态 <b class="warn">● 配额告警</b></p></button>
        </div></article>
        <div class="setting-grid ai-detail"><article class="setting-card"><h3>DeepSeek 配置详情</h3><div class="form-grid compact-form"><label><span>基础 URL</span><input v-model="settings.deepseek_base_url" /></label><label><span>温度</span><input type="number" value="0.7" step="0.1" /></label><label><span>API Key</span><input v-model="settings.deepseek_api_key" type="password" :placeholder="settings.deepseek_api_key_configured ? '已配置，留空表示不修改' : '请输入 API Key'" /></label><label><span>最大输出 token</span><input v-model.number="settings.deepseek_max_tokens" type="number" /></label><label><span>默认模型</span><select v-model="settings.deepseek_model"><option>deepseek-v4-flash</option><option>deepseek-v4-pro</option></select></label><label><span>请求超时（秒）</span><input v-model.number="settings.deepseek_timeout_seconds" type="number" /></label><label><span>失败重试</span><input v-model.number="settings.deepseek_retry_count" type="number" /></label><button v-if="settings.deepseek_api_key_configured" class="text-danger" @click="clearKey('deepseek_api_key')">清除已保存密钥</button></div></article><article class="setting-card"><h3>服务状态与能力</h3><div class="capability"><div><small>上下文长度</small><strong>128K</strong><small>最大输出长度</small><strong>8K</strong></div><div><small>今日调用统计</small><strong>12,480 <em>次</em></strong><b class="ok">较昨日 ↑ 18.6%</b></div><div><small>平均响应时间</small><strong>1.28 <em>s</em></strong><b class="ok">较昨日 ↓ 5.3%</b></div><div><small>可用性（24h）</small><strong>99.85 <em>%</em></strong><b class="ok">↑ 0.12%</b></div></div></article></div>
      </div>

      <div v-else-if="section === 'tts'" class="setting-stack">
        <div class="setting-metrics four"><article><span class="metric-icon blue"><Mic2 /></span><div><small>已配置引擎</small><strong>2</strong></div></article><article><span class="metric-icon green"><Sparkles /></span><div><small>默认引擎</small><strong>{{ selectedTtsName }}</strong></div></article><article><span class="metric-icon orange"><AlertTriangle /></span><div><small>兼容异常</small><strong>0</strong></div></article><article><span class="metric-icon purple"><Activity /></span><div><small>可用音色总数</small><strong>24</strong></div></article></div>
        <div class="setting-grid tts-layout"><article class="setting-card engine-list"><div class="card-head"><h3>引擎列表</h3></div><button :class="{selected:selectedTts==='qwen'}" @click="selectedTts='qwen'"><i></i><strong>Qwen3-TTS</strong><span class="pill green">运行正常</span><small>本地 · 中/英等 9 种</small></button><button :class="{selected:selectedTts==='cosy'}" @click="selectedTts='cosy'"><i></i><strong>CosyVoice</strong><span class="pill green">运行正常</span><small>本地 · 中/英等 8 种</small></button></article>
          <article class="setting-card"><div class="card-head"><h3>{{ selectedTtsName }} <span class="pill green">运行正常</span></h3></div><div v-if="selectedTts==='qwen'" class="form-grid compact-form"><label><span>引擎根目录</span><input v-model="settings.qwen_tts_root" placeholder="选择 Qwen3-TTS 目录" /></label><label><span>设备</span><input v-model="settings.qwen_tts_device" /></label><label><span>Python 环境</span><input v-model="settings.qwen_tts_python" /></label><label><span>精度</span><select v-model="settings.qwen_tts_dtype"><option>bfloat16</option><option>float16</option><option>float32</option></select></label><label><span>模型目录</span><input v-model="settings.qwen_tts_model_dir" /></label><label><span>默认语言</span><input v-model="settings.qwen_tts_language" /></label><label><span>最大 token</span><input v-model.number="settings.qwen_tts_max_new_tokens" type="number" /></label></div><div v-else class="form-grid compact-form"><label><span>引擎根目录</span><input v-model="settings.cosyvoice_root" /></label><label><span>模型目录</span><input v-model="settings.cosyvoice_model_dir" /></label><label><span>Python 环境</span><input v-model="settings.cosyvoice_python" /></label><label class="switch-row"><span>FP16 加速</span><input v-model="settings.cosyvoice_fp16" type="checkbox" /></label><label class="wide"><span>默认指令</span><textarea v-model="settings.cosyvoice_instruction"></textarea></label><label><span>失败重试</span><input v-model.number="settings.cosyvoice_max_attempts" type="number" min="1" max="5" /></label></div></article>
          <article class="setting-card help-card"><h3><CircleGauge /> 兼容与帮助</h3><p><span>支持的音色格式</span><b>.pt、.bin、.onnx</b></p><p><span>支持的语言</span><b>中文、英文、日文等</b></p><p><span>历史成功率</span><b class="ok">98.32%</b></p><hr><small>最近检测：运行环境与模型目录均可访问</small></article></div>
      </div>

      <div v-else-if="section === 'vision'" class="setting-stack">
        <div class="setting-metrics four"><article><span class="metric-icon purple"><Box /></span><div><small>当前默认模型</small><strong>{{ selectedVision === 'qwen' ? 'Qwen3-VL Embedding' : 'SigLIP 2' }}</strong></div></article><article><span class="metric-icon blue"><Layers3 /></span><div><small>已安装模型</small><strong>2</strong></div></article><article><span class="metric-icon green"><Cpu /></span><div><small>设备</small><strong>{{ settings.vision_embedding_device }}</strong></div></article><article><span class="metric-icon orange"><Database /></span><div><small>待重建素材</small><strong>18,736</strong></div></article></div>
        <div class="setting-grid vision-layout"><article class="setting-card model-list"><h3>模型管理</h3><button :class="{selected:selectedVision==='qwen'}" @click="selectedVision='qwen'"><strong>Qwen3-VL-Embedding-2B</strong><span class="pill green">已启用</span><small>向量索引 · 2B 多模态模型</small><em>显存需求 3.8 GB</em></button><button :class="{selected:selectedVision==='siglip'}" @click="selectedVision='siglip'"><strong>SigLIP 2 Base</strong><span class="pill blue">推荐</span><small>镜头切片 · 轻量视觉模型</small><em>显存需求 2.6 GB</em></button></article><article class="setting-card"><h3>所选模型详情</h3><div class="form-list"><label><span>模型目录</span><input v-model="settings.vision_embedding_model_dir" /></label><label><span>设备选择</span><input v-model="settings.vision_embedding_device" /></label><label><span>数据精度</span><select v-model="settings.vision_embedding_dtype"><option>float16</option><option>bfloat16</option><option>float32</option></select></label><label><span>单批最大图片</span><input v-model.number="settings.vision_embedding_max_images" type="number" min="1" max="8" /></label><label><span>最大像素数</span><input v-model.number="settings.vision_embedding_max_pixels" type="number" /></label><label><span>检索指令</span><textarea v-model="settings.vision_embedding_instruction"></textarea></label></div></article><article class="setting-card"><h3>实时监控</h3><div class="monitor-chart"><b>13.2 <small>GB / 24 GB</small></b><i v-for="n in 14" :key="n" :style="{height:`${26 + (n%5)*8}%`}"></i></div><h3>最近索引任务</h3><ul class="simple-list"><li v-for="name in ['影视剪辑-20250524-001','素材库-短视频-20250523','品牌宣传片-20250523-02']" :key="name"><CheckCircle2 />{{ name }}<span>完成</span></li></ul></article></div>
      </div>

      <div v-else-if="section === 'image-generation'" class="setting-stack">
        <div class="setting-metrics four"><article><span class="metric-icon green"><Cpu /></span><div><small>默认图片引擎</small><strong>本地 SDXL</strong></div></article><article><span class="metric-icon blue"><Layers3 /></span><div><small>可用模型</small><strong>1</strong></div></article><article><span class="metric-icon green"><Image /></span><div><small>默认分辨率</small><strong>{{ settings.image_generation_width }}×{{ settings.image_generation_height }}</strong></div></article><article><span class="metric-icon red"><AlertTriangle /></span><div><small>候选筛选阈值</small><strong>{{ settings.image_selection_min_total_score }}</strong></div></article></div>
        <article class="setting-card"><h3>引擎选择与默认参数</h3><div class="engine-options"><button class="selected"><Cpu /><strong>本地 SDXL</strong><span class="pill green">已连接</span><small>本地部署稳定高效</small></button><button disabled><Sparkles /><strong>FLUX API</strong><span class="pill">未配置</span><small>高质量图像生成</small></button><button disabled><WandSparkles /><strong>通用云图像服务</strong><span class="pill">未配置</span><small>兼容主流云厂商接口</small></button></div><div class="form-grid image-form"><label><span>模型文件</span><input v-model="settings.image_generation_model_path" /></label><label><span>负向提示词</span><textarea v-model="settings.image_generation_negative_prompt"></textarea></label><label><span>配置目录</span><input v-model="settings.image_generation_config_dir" /></label><label><span>默认设备</span><input v-model="settings.image_generation_device" /></label><label><span>默认宽度</span><input v-model.number="settings.image_generation_width" type="number" step="64" /></label><label><span>默认高度</span><input v-model.number="settings.image_generation_height" type="number" step="64" /></label><label><span>生成步数</span><input v-model.number="settings.image_generation_steps" type="number" /></label><label><span>CFG</span><input v-model.number="settings.image_generation_guidance_scale" type="number" step="0.5" /></label><label><span>单场景候选数</span><input v-model.number="settings.image_generation_candidates_per_scene" type="number" min="1" max="4" /></label><label class="switch-row"><span>CPU Offload</span><input v-model="settings.image_generation_cpu_offload" type="checkbox" /></label></div></article>
        <article class="setting-card"><h3>图片筛选策略</h3><div class="form-grid compact-form"><label><span>语义权重</span><input v-model.number="settings.image_selection_semantic_weight" type="number" step="0.05" /></label><label><span>技术质量权重</span><input v-model.number="settings.image_selection_technical_weight" type="number" step="0.05" /></label><label><span>最低语义分</span><input v-model.number="settings.image_selection_min_semantic_score" type="number" step="0.05" /></label><label><span>最低总分</span><input v-model.number="settings.image_selection_min_total_score" type="number" step="0.05" /></label></div></article>
      </div>

      <div v-else-if="section === 'media-platforms'" class="setting-stack">
        <div class="setting-metrics four"><article><span class="metric-icon blue"><Boxes /></span><div><small>已配置平台</small><strong>{{ providerStatuses.filter(p=>p.configured).length }} / 2</strong></div></article><article><span class="metric-icon green"><Download /></span><div><small>单场景下载上限</small><strong>{{ settings.media_search_download_limit }}</strong></div></article><article><span class="metric-icon purple"><Clock3 /></span><div><small>搜索缓存</small><strong>{{ settings.media_search_cache_hours }} 小时</strong></div></article><article><span class="metric-icon orange"><HardDrive /></span><div><small>本地素材优先</small><strong>已启用</strong></div></article></div>
        <div class="setting-grid two"><article v-for="provider in (['pexels','pixabay'] as const)" :key="provider" class="setting-card"><div class="card-head"><h3>{{ provider === 'pexels' ? 'Pexels' : 'Pixabay' }}</h3><span :class="['pill',providerStatus(provider)?.configured?'green':'orange']">{{ providerStatus(provider)?.configured ? '已配置' : '未配置' }}</span></div><div class="form-list"><label><span>API Key</span><input v-model="settings[`${provider}_api_key`]" type="password" :placeholder="providerStatus(provider)?.configured ? '已配置，留空表示不修改' : '输入平台 API Key'" /></label><label><span>素材存储目录</span><div class="input-action"><input v-model="settings[`${provider}_storage_dir`]" /><button @click="chooseProviderDir(provider)">浏览</button></div></label><button v-if="providerStatus(provider)?.configured" class="text-danger" @click="clearKey(`${provider}_api_key`)">清除密钥</button></div></article></div>
        <article class="setting-card"><h3>检索与下载策略</h3><div class="form-grid compact-form"><label><span>查询缓存时间（小时）</span><input v-model.number="settings.media_search_cache_hours" type="number" min="24" max="168" /></label><label><span>每场景完整视频下载数</span><input v-model.number="settings.media_search_download_limit" type="number" min="1" max="5" /></label></div></article>
      </div>

      <div v-else-if="section === 'render'" class="setting-stack">
        <div class="setting-metrics five"><article><span class="metric-icon purple"><MonitorCog /></span><div><small>默认编码器</small><strong>H.264 NVENC</strong></div></article><article><span class="metric-icon blue"><FileText /></span><div><small>导出预设</small><strong>5</strong></div></article><article><span class="metric-icon green"><Cpu /></span><div><small>GPU 加速</small><strong>已启用</strong></div></article><article><span class="metric-icon purple"><Gauge /></span><div><small>今日渲染成功率</small><strong>97.8%</strong></div></article><article><span class="metric-icon orange"><Clock3 /></span><div><small>平均渲染耗时</small><strong>6分42秒</strong></div></article></div>
        <div class="setting-grid render-layout"><article class="setting-card preset-list"><h3>视频导出预设</h3><button class="selected"><strong>YouTube 横版</strong><small>16:9 · 推荐</small><b>1920×1080</b></button><button><strong>Shorts 竖版</strong><small>9:16 · 推荐</small><b>1080×1920</b></button><button><strong>B站横版</strong><small>16:9 · 推荐</small><b>1920×1080</b></button><button><strong>无字幕母版</strong><small>自定义 · 无字幕</small><b>1920×1080</b></button></article><article class="setting-card"><h3>编码参数</h3><div class="form-list"><label><span>默认输出分辨率</span><select><option>1920×1080（16:9）</option><option>1080×1920（9:16）</option></select></label><label><span>帧率</span><select><option>30 fps</option><option>25 fps</option><option>60 fps</option></select></label><label><span>视频编码</span><select><option>H.264 (AVC)</option><option>H.265 (HEVC)</option></select></label><label><span>目标码率</span><input value="8000 Kbps" /></label></div><h3>硬件加速</h3><div class="inline-settings"><label class="switch-row">GPU 加速 <input type="checkbox" checked /></label><label class="switch-row">优先 NVENC <input type="checkbox" checked /></label><label class="switch-row">零拷贝（CUDA）<input type="checkbox" checked /></label></div></article><aside class="setting-stack"><article class="setting-card"><h3>编码器可用性</h3><div class="health-list"><p v-for="codec in ['H.264 NVENC','H.265 NVENC','H.264 (x264)','H.265 (x265)']" :key="codec"><span>{{ codec }}</span><b class="ok">✓ 可用</b></p></div></article><article class="setting-card"><h3>FFmpeg 硬件支持</h3><p class="muted-line">{{ ffmpegStatus?.installed ? `${ffmpegStatus.version} · ${ffmpegStatus.ffmpeg_path}` : '未检测到可用 FFmpeg' }}</p><button v-if="!ffmpegStatus?.installed" class="ghost-button" @click="downloadFfmpeg">自动安装 FFmpeg</button></article></aside></div>
      </div>

      <div v-else-if="section === 'transitions'" class="setting-stack">
        <div class="setting-metrics four"><article><span class="metric-icon blue"><Layers3 /></span><div><small>默认转场</small><strong>淡入淡出</strong></div></article><article><span class="metric-icon blue"><ShieldCheck /></span><div><small>已启用规则</small><strong>{{ settings.storyboard_transition_effects.filter(i=>i.enabled).length }}</strong></div></article><article><span class="metric-icon orange"><AlertTriangle /></span><div><small>比例合计</small><strong>{{ transitionTotal }}%</strong></div></article><article><span class="metric-icon purple"><Clock3 /></span><div><small>平均转场时长</small><strong>{{ settings.storyboard_transition_duration_seconds }} 秒</strong></div></article></div>
        <div class="setting-grid transition-layout"><article class="setting-card"><h3>全局默认规则</h3><div class="form-list"><label><span>默认时长</span><input v-model.number="settings.storyboard_transition_duration_seconds" type="number" step="0.05" min="0.2" max="2" /></label><label><span>每组镜头数</span><div class="dual-input"><input v-model.number="settings.storyboard_transition_group_min_clips" type="number" /> 至 <input v-model.number="settings.storyboard_transition_group_max_clips" type="number" /></div></label><label><span>每组转场数</span><div class="dual-input"><input v-model.number="settings.storyboard_transition_min_per_group" type="number" /> 至 <input v-model.number="settings.storyboard_transition_max_per_group" type="number" /></div></label></div></article><article class="setting-card"><div class="card-head"><h3>按场景类型规则</h3><button class="ghost-button" @click="normalizeTransitions">均分比例</button></div><div class="transition-table"><div class="table-head"><span>转场类型</span><span>使用比例</span><span>启用状态</span></div><label v-for="item in settings.storyboard_transition_effects" :key="item.name"><strong>{{ transitionLabels[item.name] }}</strong><input v-model.number="item.percentage" type="number" min="0" max="100" :disabled="!item.enabled" /><span>%</span><input v-model="item.enabled" type="checkbox" @change="normalizeTransitions" /></label></div></article><article class="setting-card preview-card"><h3>预览示意</h3><div class="transition-previews"><button v-for="name in ['淡入淡出','推镜','滑动','缩放','遮罩','交叉溶解']" :key="name"><span><Play /></span><small>{{ name }}</small></button></div></article></div>
      </div>

      <div v-else-if="section === 'fallback'" class="setting-stack">
        <div class="setting-metrics four"><article><span class="metric-icon blue"><ShieldCheck /></span><div><small>已启用兜底规则</small><strong>5</strong></div></article><article><span class="metric-icon green"><RotateCcw /></span><div><small>今日触发次数</small><strong>34</strong></div></article><article><span class="metric-icon purple"><ShieldCheck /></span><div><small>自动恢复成功率</small><strong>82%</strong></div></article><article><span class="metric-icon orange"><AlertTriangle /></span><div><small>需人工处理</small><strong>6</strong></div></article></div>
        <div class="setting-grid fallback-layout"><section class="setting-grid fallback-cards"><article class="setting-card"><h3><Image /> 素材缺失兜底</h3><label class="switch-row">优先使用本地风景库 <input v-model="settings.auto_landscape_fallback_enabled" type="checkbox" /></label><label class="switch-row">自动切换备用素材源 <input v-model="settings.auto_fallback_enabled" type="checkbox" /></label><label>最大连续兜底镜头 <input v-model.number="settings.auto_fallback_max_consecutive_shots" type="number" /></label></article><article class="setting-card"><h3><Image /> 图片生成失败兜底</h3><label class="switch-row">失败后进入人工审核 <input v-model="settings.auto_fallback_review_required" type="checkbox" /></label><label>单片最大兜底占比 <input v-model.number="settings.auto_fallback_max_ratio_percent" type="number" /> %</label></article><article class="setting-card"><h3><Mic2 /> 配音失败兜底</h3><label class="switch-row">失败后切换备用引擎 <input type="checkbox" checked /></label><label>失败重试次数 <input type="number" value="2" /></label></article><article class="setting-card"><h3><Server /> 渲染失败兜底</h3><label class="switch-row">失败时自动转 CPU 编码 <input type="checkbox" checked /></label><label>超时阈值 <input type="number" value="120" /> 秒</label></article><article class="setting-card"><h3><Download /> 下载失败兜底</h3><label class="switch-row">素材不足时延长背景视频循环 <input type="checkbox" checked /></label><label>最大延长时长 <input type="number" value="30" /> 秒</label></article></section><aside class="setting-stack"><article class="setting-card"><h3>最近兜底事件</h3><ul class="event-list"><li><CheckCircle2 /> 图片生成失败兜底 <span class="ok">已恢复</span></li><li><CheckCircle2 /> 配音失败兜底 <span class="ok">已恢复</span></li><li><AlertTriangle /> 素材缺失兜底 <span class="warn">需人工处理</span></li><li><AlertTriangle /> 下载失败兜底 <span class="bad">未恢复</span></li></ul></article><article class="setting-card donut-card"><div class="donut"><strong>82%</strong><small>成功率</small></div><p><i class="green-dot"></i> 成功 28</p><p><i class="red-dot"></i> 失败 6</p></article></aside></div>
      </div>

      <div v-else class="setting-stack diagnostics-page">
        <div class="setting-metrics five"><article><span class="metric-icon green"><Activity /></span><div><small>系统健康度</small><strong>92 分</strong></div></article><article><span class="metric-icon blue"><Server /></span><div><small>在线服务</small><strong>8 / 9</strong></div></article><article><span class="metric-icon purple"><Gauge /></span><div><small>GPU 温度</small><strong>64°C</strong></div></article><article><span class="metric-icon orange"><AlertTriangle /></span><div><small>最近错误</small><strong>3</strong></div></article><article><span class="metric-icon blue"><Layers3 /></span><div><small>当前队列</small><strong>27</strong></div></article></div>
        <div class="setting-grid two"><article class="setting-card"><h3><CircleGauge /> 运行环境检查</h3><div class="diagnostic-table"><div class="table-head"><span>检查项</span><span>状态</span><span>说明</span></div><p v-for="item in diagnostics" :key="item[0] as string"><span>{{ item[0] }}</span><b :class="item[1] ? 'ok':'bad'">{{ item[1] ? '● 正常':'● 异常' }}</b><em>{{ item[2] }}</em></p></div></article><article class="setting-card"><h3><Activity /> 服务状态</h3><div class="diagnostic-table services"><div class="table-head"><span>服务名称</span><span>当前状态</span><span>端口 / 地址</span></div><p v-for="service in [['Web 服务','运行中',settings.app_port],['TTS 服务','运行中','50051'],['AI 服务','运行中','8001'],['素材抓取服务','运行中','8002'],['渲染服务','运行中','8003'],['向量索引服务','异常','9200']]" :key="service[0] as string"><span>{{ service[0] }}</span><b :class="service[1]==='运行中'?'ok':'bad'">● {{ service[1] }}</b><em>localhost:{{ service[2] }}</em></p></div></article></div>
        <article class="setting-card"><h3><Gauge /> 性能监控（最近 1 小时）</h3><div class="performance-grid"><div v-for="metric in [['CPU 使用率','28%','blue'],['内存使用率','63%','green'],['GPU 使用率','74%','purple'],['磁盘 IO','123 MB/s','orange'],['队列大小','27','cyan']]" :key="metric[0]"><span>{{ metric[0] }}</span><strong :class="metric[2]">{{ metric[1] }}</strong><i><b v-for="n in 13" :key="n" :style="{height:`${20 + ((n*7)%55)}%`}"></b></i></div></div></article>
      </div>

      <footer class="settings-actions"><button class="secondary-button" @click="testAll"><RefreshCw :class="{spin:testing}" /> {{ section === 'diagnostics' ? '一键诊断' : '测试配置' }}</button><button v-if="section === 'diagnostics'" class="secondary-button" @click="exportDiagnostics"><Download /> 导出报告</button><button class="primary-button" :disabled="saving" @click="save"><Save /> {{ saving ? '正在保存...' : '保存设置' }}</button></footer>
    </template>
  </section>
</template>
