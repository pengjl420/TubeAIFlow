<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { Archive, Beaker, Check, Copy, Image, Loader2, Plus, Save, Sparkles } from 'lucide-vue-next'
import {
  archiveVisualStyle, createVisualStyle, duplicateVisualStyle, listVisualStyles, listVisualStyleTests,
  listVisualStyleAssets, optimizeVisualStyle, publishVisualStyle, runVisualStyleTest,
  updateVisualStyleAssetStatus, updateVisualStyleDraft,
  type StyleAsset, type StyleDraftInput, type StyleTestRun, type VisualStyleProfile,
} from '../api/visualStyles'
import { usePageFeedback } from '../services/feedback'

const styles = ref<VisualStyleProfile[]>([])
const selectedId = ref('')
const loading = ref(true)
const saving = ref(false)
const optimizing = ref(false)
const testing = ref(false)
const error = ref('')
const message = ref('')
const tests = ref<StyleTestRun[]>([])
const assets = ref<StyleAsset[]>([])
const testScene = ref('一位中年历史学者站在昏暗的档案馆中，身后是整齐排列的旧文件盒，侧面窗光照亮人物轮廓。')
const testCandidates = ref(1)
const optimizeGoal = ref('加强全片风格一致性并优化为 Seedream 适用格式')
const optimizeResult = ref<Awaited<ReturnType<typeof optimizeVisualStyle>> | null>(null)
let testPollTimer: ReturnType<typeof setTimeout> | undefined
const pendingTestStorageKey = 'tube_style_test_pending_request'
usePageFeedback(error, message, { errorTitle: '风格中心错误' })

const draft = reactive<StyleDraftInput>({
  name: '', description: '', tags: [], style_prompt: '', negative_prompt: '',
  continuity_rules: [], composition_rules: [],
  motion_preset: { type: 'slow_push', zoom_start: 1, zoom_end: 1.06, pan_direction: 'center', transition: 'cut', subtitle_safe_zone: 0.18 },
})
const tagsText = ref('')
const continuityText = ref('')
const compositionText = ref('')
const selected = computed(() => styles.value.find(item => item.id === selectedId.value) || null)
const activeRevision = computed(() => selected.value?.draft_revision || selected.value?.current_revision || null)
const canEdit = computed(() => Boolean(selected.value && !selected.value.builtin_key))

function hydrate(profile: VisualStyleProfile) {
  stopTestPolling()
  testing.value = false
  selectedId.value = profile.id
  const revision = profile.draft_revision || profile.current_revision
  draft.name = profile.name
  draft.description = profile.description
  draft.tags = [...profile.tags]
  draft.style_prompt = revision?.style_prompt || ''
  draft.negative_prompt = revision?.negative_prompt || ''
  draft.continuity_rules = [...(revision?.continuity_rules || [])]
  draft.composition_rules = [...(revision?.composition_rules || [])]
  draft.motion_preset = { ...(revision?.motion_preset || {}) }
  tagsText.value = profile.tags.join('，')
  continuityText.value = draft.continuity_rules.join('\n')
  compositionText.value = draft.composition_rules.join('\n')
  optimizeResult.value = null
  void loadTests(profile.id).then(() => {
    if (testing.value) scheduleTestPoll(profile.id)
  })
  void loadAssets(profile.id)
}

async function load() {
  loading.value = true
  try {
    styles.value = await listVisualStyles()
    const profile = styles.value.find(item => item.id === selectedId.value) || styles.value[0]
    if (profile) hydrate(profile)
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '读取风格失败' }
  finally { loading.value = false }
}

async function loadTests(id: string) {
  try {
    const values = await listVisualStyleTests(id)
    if (selectedId.value !== id) return
    tests.value = values
    testing.value = values.some(item => ['queued', 'running'].includes(item.status))
  } catch {
    if (selectedId.value === id) tests.value = []
  }
}

async function loadAssets(id: string) {
  try {
    const values = await listVisualStyleAssets(id)
    if (selectedId.value === id) assets.value = values
  } catch {
    if (selectedId.value === id) assets.value = []
  }
}

async function approveAsset(assetId: string) {
  if (!selected.value) return
  try {
    await updateVisualStyleAssetStatus(selected.value.id, assetId, 'approved')
    await loadAssets(selected.value.id)
    message.value = '风格资产已批准，可参与后续项目的本地匹配'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '批准风格资产失败'
  }
}

function stopTestPolling() {
  if (testPollTimer !== undefined) clearTimeout(testPollTimer)
  testPollTimer = undefined
}

function scheduleTestPoll(id: string) {
  stopTestPolling()
  testPollTimer = setTimeout(async () => {
    await loadTests(id)
    if (selectedId.value === id && testing.value) scheduleTestPoll(id)
  }, 2000)
}

function normalizeDraft() {
  draft.tags = tagsText.value.split(/[，,]/).map(item => item.trim()).filter(Boolean)
  draft.continuity_rules = continuityText.value.split('\n').map(item => item.trim()).filter(Boolean)
  draft.composition_rules = compositionText.value.split('\n').map(item => item.trim()).filter(Boolean)
}

async function createStyle() {
  saving.value = true
  try {
    const created = await createVisualStyle({
      name: '未命名风格', description: '', tags: [],
      style_prompt: 'Describe a consistent visual art direction for this long-form series.', negative_prompt: 'watermark, logo, random text',
    })
    await load()
    hydrate(styles.value.find(item => item.id === created.id) || created)
    message.value = '新风格草稿已创建'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '创建失败' }
  finally { saving.value = false }
}

async function saveDraft() {
  const profile = selected.value
  if (!profile || !canEdit.value) return
  normalizeDraft()
  saving.value = true
  try {
    const updated = await updateVisualStyleDraft(profile.id, { ...draft, source: optimizeResult.value ? 'deepseek_optimized' : 'manual' })
    await load()
    hydrate(styles.value.find(item => item.id === updated.id) || updated)
    message.value = '风格草稿已保存'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '保存失败' }
  finally { saving.value = false }
}

async function publish() {
  if (!selected.value || !canEdit.value) return
  saving.value = true
  try {
    await saveDraft()
    const updated = await publishVisualStyle(selected.value.id)
    await load()
    hydrate(styles.value.find(item => item.id === updated.id) || updated)
    message.value = `风格版本 ${updated.current_revision?.version || ''} 已发布`
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '发布失败' }
  finally { saving.value = false }
}

async function duplicate() {
  if (!selected.value) return
  saving.value = true
  try {
    const copied = await duplicateVisualStyle(selected.value.id)
    await load()
    hydrate(styles.value.find(item => item.id === copied.id) || copied)
    message.value = '已复制为可编辑的自定义风格'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '复制失败' }
  finally { saving.value = false }
}

async function archiveStyle() {
  if (!selected.value || !canEdit.value) return
  saving.value = true
  try {
    await archiveVisualStyle(selected.value.id)
    selectedId.value = ''
    await load()
    message.value = '风格已归档，已绑定项目仍可继续使用原发布版本'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : '归档失败' }
  finally { saving.value = false }
}

async function optimize() {
  if (!selected.value || !canEdit.value) return
  optimizing.value = true
  try {
    optimizeResult.value = await optimizeVisualStyle(selected.value.id, {
      style_prompt: draft.style_prompt, negative_prompt: draft.negative_prompt, goal: optimizeGoal.value,
    })
    message.value = 'DeepSeek 已返回优化建议，请确认后应用'
  } catch (reason) { error.value = reason instanceof Error ? reason.message : 'AI 优化失败' }
  finally { optimizing.value = false }
}

function applyOptimization() {
  if (!optimizeResult.value) return
  draft.style_prompt = optimizeResult.value.optimized_style_prompt
  draft.negative_prompt = optimizeResult.value.optimized_negative_prompt
  if (optimizeResult.value.continuity_rules?.length) continuityText.value = optimizeResult.value.continuity_rules.join('\n')
  if (optimizeResult.value.composition_rules?.length) compositionText.value = optimizeResult.value.composition_rules.join('\n')
  message.value = '优化建议已应用到草稿，保存后才会持久化'
}

async function runTest() {
  if (!selected.value || !activeRevision.value || !testScene.value.trim()) return
  testing.value = true
  const fingerprint = JSON.stringify({
    style_id: selected.value.id,
    revision_id: activeRevision.value.id,
    scene_description: testScene.value.trim(),
    candidates: testCandidates.value,
  })
  let requestId = crypto.randomUUID()
  try {
    const pending = JSON.parse(localStorage.getItem(pendingTestStorageKey) || 'null')
    if (pending?.fingerprint === fingerprint && typeof pending?.request_id === 'string') {
      requestId = pending.request_id
    }
  } catch { /* Ignore invalid stale browser state. */ }
  localStorage.setItem(pendingTestStorageKey, JSON.stringify({ fingerprint, request_id: requestId }))
  try {
    const result = await runVisualStyleTest(selected.value.id, {
      client_request_id: requestId, revision_id: activeRevision.value.id,
      scene_description: testScene.value, candidates: testCandidates.value,
    })
    localStorage.removeItem(pendingTestStorageKey)
    await loadTests(selected.value.id)
    await loadAssets(selected.value.id)
    scheduleTestPoll(selected.value.id)
    message.value = `Seedream 测试任务已提交（${result.candidate_count} 张候选）`
  } catch (reason) {
    testing.value = false
    const detail = reason instanceof Error ? reason.message : '测试任务提交失败'
    error.value = `${detail}；再次点击会使用同一请求标识安全确认，不会重复创建任务`
  }
}

onMounted(() => void load())
onBeforeUnmount(stopTestPolling)
</script>

<template>
  <section class="style-page">
    <header class="style-title"><div><span>VISUAL STYLE LIBRARY</span><h1>风格中心</h1><p>定义并验证贯穿整部视频的统一画面语言。</p></div><button class="primary" :disabled="saving" @click="createStyle"><Plus :size="16" />新建风格</button></header>
    <div v-if="loading" class="style-loading"><Loader2 class="spin" />正在读取风格库…</div>
    <div v-else class="style-layout">
      <aside class="style-list">
        <button v-for="item in styles" :key="item.id" :class="{ active: item.id === selectedId }" @click="hydrate(item)"><div><strong>{{ item.name }}</strong><small>{{ item.builtin_key ? '内置模板' : item.status === 'published' ? `已发布 v${item.current_revision?.version}` : '草稿' }}</small></div><span>{{ item.tags.slice(0, 2).join(' · ') }}</span></button>
      </aside>
      <main v-if="selected" class="style-editor">
        <div class="panel-heading"><div><span>STYLE DEFINITION</span><h2>{{ selected.name }}</h2></div><div><button @click="duplicate"><Copy :size="15" />复制</button><button v-if="canEdit" :disabled="saving" @click="archiveStyle"><Archive :size="15" />归档</button><button v-if="canEdit" :disabled="saving" @click="saveDraft"><Save :size="15" />保存草稿</button><button v-if="canEdit" class="primary" :disabled="saving" @click="publish"><Check :size="15" />发布版本</button></div></div>
        <div v-if="selected.builtin_key" class="notice">这是内置兼容风格。复制后即可修改，不会破坏旧项目。</div>
        <div class="form-grid">
          <label><span>风格名称</span><input v-model="draft.name" :disabled="!canEdit" /></label><label><span>标签</span><input v-model="tagsText" :disabled="!canEdit" placeholder="纪录片，写实，电影感" /></label>
          <label class="wide"><span>说明</span><input v-model="draft.description" :disabled="!canEdit" /></label>
          <label class="wide"><span>风格主提示词</span><textarea v-model="draft.style_prompt" rows="9" :disabled="!canEdit" /></label>
          <label class="wide"><span>排除提示词</span><textarea v-model="draft.negative_prompt" rows="4" :disabled="!canEdit" /></label>
          <label class="wide"><span>连续性规则 <small>每行一条</small></span><textarea v-model="continuityText" rows="4" :disabled="!canEdit" /></label>
          <label class="wide"><span>构图规则 <small>每行一条</small></span><textarea v-model="compositionText" rows="4" :disabled="!canEdit" /></label>
          <label><span>图片动画</span><select v-model="draft.motion_preset.type" :disabled="!canEdit"><option value="slow_push">慢速推进</option><option value="slow_pull">慢速拉远</option><option value="pan">横向平移</option><option value="static">静态</option></select></label>
          <label><span>平移方向</span><select v-model="draft.motion_preset.pan_direction" :disabled="!canEdit"><option value="center">居中</option><option value="left">向左</option><option value="right">向右</option></select></label>
          <label><span>结束缩放</span><input v-model.number="draft.motion_preset.zoom_end" type="number" min="1" max="1.2" step="0.01" :disabled="!canEdit" /></label>
          <label><span>默认转场</span><select v-model="draft.motion_preset.transition" :disabled="!canEdit"><option value="cut">直接切换</option><option value="crossfade">交叉淡化</option></select></label>
        </div>
        <section v-if="canEdit" class="ai-box"><div class="box-title"><Sparkles :size="18" /><div><h3>DeepSeek 风格优化</h3><p>只优化可复用的风格契约，不添加具体人物、事件或地点。</p></div></div><div class="ai-actions"><select v-model="optimizeGoal"><option>加强全片风格一致性并优化为 Seedream 适用格式</option><option>减少 AI 感并提高材质可信度</option><option>加强人物外观连续性</option><option>压缩冗余提示词</option></select><button class="primary" :disabled="optimizing || !draft.style_prompt.trim()" @click="optimize"><Loader2 v-if="optimizing" class="spin" :size="15" /><Sparkles v-else :size="15" />{{ optimizing ? '优化中…' : '生成优化建议' }}</button></div><div v-if="optimizeResult" class="optimization-result"><strong>{{ optimizeResult.summary || 'DeepSeek 优化建议' }}</strong><p v-for="warning in optimizeResult.warnings || []" :key="warning">提醒：{{ warning }}</p><textarea :value="optimizeResult.optimized_style_prompt" rows="6" readonly /><button @click="applyOptimization">应用到当前草稿</button></div></section>
      </main>
      <aside v-if="selected" class="test-panel"><div class="box-title"><Beaker :size="18" /><div><h3>Seedream 调试</h3><p>测试图隔离保存，并登记到当前风格版本资产库</p></div></div><label><span>测试画面</span><textarea v-model="testScene" rows="7" /></label><label><span>候选数量</span><select v-model.number="testCandidates"><option :value="1">1 张</option><option :value="2">2 张</option><option :value="4">4 张</option></select></label><button class="primary test-button" :disabled="testing || !activeRevision" @click="runTest"><Loader2 v-if="testing" class="spin" :size="15" /><Image v-else :size="15" />{{ testing ? '后台生成中…' : '生成测试图片' }}</button><p class="test-note">任务提交后由后台持续执行。读取超时或应用中断时不会自动重复调用付费 API。</p><section v-if="assets.length" class="asset-library"><header><strong>风格资产库</strong><small>{{ assets.length }} 项</small></header><div class="test-images"><figure v-for="asset in assets.slice(0, 8)" :key="asset.id"><img :src="asset.image_url" alt="风格资产" /><figcaption>{{ asset.status === 'approved' ? `可复用 · ${asset.usage_count} 次` : '待审核' }}</figcaption><button v-if="asset.status === 'unreviewed'" @click="approveAsset(asset.id)">批准复用</button></figure></div></section><div class="test-history"><article v-for="run in tests" :key="run.id"><header><strong>{{ run.status === 'completed' ? '测试完成' : run.status === 'failed' ? '测试失败' : run.status === 'unknown' ? '结果待确认' : `处理中 ${run.completed_candidates}/${run.candidate_count}` }}</strong><small>{{ run.model_id }}</small></header><p>{{ run.scene_description }}</p><div class="test-images"><img v-for="output in run.outputs" :key="output.index" :src="output.image_url" alt="风格测试结果" /></div><details><summary>查看编译提示词</summary><pre>{{ run.compiled_prompt }}</pre><pre v-if="run.compiled_negative_prompt">AVOID: {{ run.compiled_negative_prompt }}</pre></details><span v-if="run.error_message" class="test-error">{{ run.error_message }}</span></article></div></aside>
    </div>
  </section>
</template>

<style scoped>
.style-page{padding:32px;min-height:100vh}.style-title{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:24px}.style-title span,.panel-heading span{font-size:11px;font-weight:800;letter-spacing:.13em;color:var(--teal)}.style-title h1{font-size:30px;margin:4px 0}.style-title p,.box-title p{margin:0;color:var(--muted)}button{display:inline-flex;align-items:center;justify-content:center;gap:7px;border:1px solid var(--line);border-radius:9px;background:#fff;padding:9px 13px;color:var(--ink)}button.primary{background:var(--teal);color:#fff;border-color:var(--teal)}.style-layout{display:grid;grid-template-columns:220px minmax(480px,1fr) 360px;gap:18px;align-items:start}.style-list,.style-editor,.test-panel{background:var(--surface);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}.style-list{padding:8px}.style-list>button{width:100%;display:block;text-align:left;border-color:transparent;padding:12px}.style-list>button.active{background:var(--teal-soft);border-color:#c6e5e1}.style-list div{display:flex;justify-content:space-between;gap:8px}.style-list small,.style-list span{font-size:11px;color:var(--muted)}.style-list span{display:block;margin-top:5px}.style-editor{padding:20px}.panel-heading{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:18px}.panel-heading h2{margin:3px 0}.panel-heading>div:last-child{display:flex;gap:7px}.notice{padding:10px 12px;background:var(--warning-soft);color:var(--warning);border-radius:9px;margin-bottom:16px}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px}.form-grid label,.test-panel label{display:flex;flex-direction:column;gap:7px}.form-grid label.wide{grid-column:1/-1}label span{font-size:12px;font-weight:700;color:var(--ink-soft)}input,textarea,select{width:100%;border:1px solid var(--line-strong);border-radius:8px;padding:10px 11px;background:#fff;color:var(--ink)}textarea{resize:vertical;line-height:1.55}.ai-box{margin-top:18px;padding:16px;background:var(--surface-soft);border:1px solid var(--line);border-radius:12px}.box-title{display:flex;gap:9px;align-items:flex-start}.box-title h3{margin:0 0 3px;font-size:15px}.box-title p{font-size:12px}.ai-actions{display:flex;gap:9px;margin-top:14px}.ai-actions select{flex:1}.optimization-result{margin-top:14px;display:grid;gap:9px}.optimization-result p{margin:0;color:var(--warning);font-size:12px}.test-panel{padding:17px;position:sticky;top:20px;display:grid;gap:14px}.test-button{width:100%}.test-note{margin:0;font-size:11px;line-height:1.5;color:var(--muted)}.test-history{display:grid;gap:12px;max-height:600px;overflow:auto}.test-history article{border-top:1px solid var(--line);padding-top:12px}.test-history header{display:flex;justify-content:space-between}.test-history header small{color:var(--muted)}.test-history p{font-size:12px;line-height:1.45;color:var(--ink-soft)}.test-images{display:grid;grid-template-columns:repeat(2,1fr);gap:6px}.test-images img{width:100%;border-radius:7px}.test-history pre{white-space:pre-wrap;font-size:10px;background:var(--surface-soft);padding:8px}.test-error{font-size:12px;color:var(--danger)}.style-loading{padding:50px;display:flex;gap:10px;justify-content:center}.spin{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:1250px){.style-layout{grid-template-columns:190px 1fr}.test-panel{grid-column:2;position:static}}@media(max-width:780px){.style-page{padding:18px}.style-layout{grid-template-columns:1fr}.style-list,.test-panel{grid-column:auto}.form-grid{grid-template-columns:1fr}.panel-heading{align-items:flex-start;flex-direction:column}}
.asset-library{border-top:1px solid var(--line);padding-top:12px}.asset-library>header{display:flex;justify-content:space-between;margin-bottom:8px}.asset-library header small,.asset-library figcaption{font-size:10px;color:var(--muted)}.asset-library figure{margin:0}
</style>
