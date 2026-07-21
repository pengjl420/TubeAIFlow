<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  AlertTriangle, Check, ChevronLeft, ChevronRight, CirclePause, Clock3,
  MoreVertical, Play, Plus, RefreshCw, Search, Settings2, Users,
} from 'lucide-vue-next'

import { listBatches, type BatchJob } from '../../api/batches'
import { usePageFeedback } from '../../services/feedback'
import { formatDateTime, formatDuration } from '../../utils/time'

const batches = ref<BatchJob[]>([])
const loading = ref(false)
const error = ref('')
usePageFeedback(error, undefined, { errorTitle: '批次列表加载失败' })
const query = ref('')
const statusFilter = ref('all')
const attentionOnly = ref(false)
const page = ref(1)
const pageSize = ref(10)

const statusMeta: Record<string, { label: string; tone: string }> = {
  draft: { label: '草稿', tone: 'muted' },
  queued: { label: '运行中', tone: 'blue' },
  running: { label: '运行中', tone: 'blue' },
  paused: { label: '已暂停', tone: 'orange' },
  review_required: { label: '等待人工处理', tone: 'amber' },
  completed: { label: '已完成', tone: 'green' },
  completed_with_errors: { label: '部分失败', tone: 'red' },
  failed: { label: '失败', tone: 'red' },
}

const statusOf = (status: string) => statusMeta[status] || { label: status, tone: 'muted' }
const processed = (batch: BatchJob) => batch.completed + batch.failed
const progress = (batch: BatchJob) => batch.total ? Math.round(processed(batch) / batch.total * 100) : 0
const pending = (batch: BatchJob) => Math.max(0, batch.total - processed(batch))

const counts = computed(() => ({
  running: batches.value.filter((batch) => ['queued', 'running'].includes(batch.status)).length,
  paused: batches.value.filter((batch) => batch.status === 'paused').length,
  review: batches.value.filter((batch) => batch.status === 'review_required').length,
  completed: batches.value.filter((batch) => batch.status === 'completed').length,
  failed: batches.value.filter((batch) => ['failed', 'completed_with_errors'].includes(batch.status)).length,
}))

const filtered = computed(() => {
  const keyword = query.value.trim().toLocaleLowerCase()
  return batches.value.filter((batch) => {
    const matchesQuery = !keyword || batch.name.toLocaleLowerCase().includes(keyword) || batch.id.toLocaleLowerCase().includes(keyword)
    const matchesStatus = statusFilter.value === 'all'
      || (statusFilter.value === 'running' && ['queued', 'running'].includes(batch.status))
      || batch.status === statusFilter.value
    const matchesAttention = !attentionOnly.value || batch.failed > 0 || batch.status === 'review_required'
    return matchesQuery && matchesStatus && matchesAttention
  })
})
const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)))
const pagedBatches = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))

async function load() {
  loading.value = true
  error.value = ''
  try {
    batches.value = await listBatches()
    page.value = 1
  } catch (err) {
    error.value = err instanceof Error ? err.message : '批次列表加载失败'
  } finally {
    loading.value = false
  }
}

function resetPage() { page.value = 1 }

onMounted(load)
</script>

<template>
  <section class="batch-list-page">
    <header class="batch-heading">
      <div><h1>批量生产</h1><p>批量导入逐字稿并统一执行视频生产流程</p></div>
      <RouterLink class="batch-primary" to="/batches/new"><Plus :size="18" />新建批次</RouterLink>
    </header>

    <div class="summary-cards">
      <article class="summary-card blue"><span class="summary-icon"><Play /></span><div><small>运行中</small><strong>{{ counts.running }}</strong><p>正在执行生产任务</p></div></article>
      <article class="summary-card orange"><span class="summary-icon"><CirclePause /></span><div><small>已暂停</small><strong>{{ counts.paused }}</strong><p>可随时继续执行</p></div></article>
      <article class="summary-card amber"><span class="summary-icon"><Users /></span><div><small>等待人工处理</small><strong>{{ counts.review }}</strong><p>需要审核或确认</p></div></article>
      <article class="summary-card green"><span class="summary-icon"><Check /></span><div><small>已完成</small><strong>{{ counts.completed }}</strong><p>生产流程全部完成</p></div></article>
      <article class="summary-card red"><span class="summary-icon"><AlertTriangle /></span><div><small>失败批次</small><strong>{{ counts.failed }}</strong><p>存在待重试项目</p></div></article>
    </div>

    <div class="filter-bar">
      <label class="search-box"><Search :size="17" /><input v-model="query" placeholder="搜索批次名称或批次 ID" @input="resetPage" /></label>
      <label class="select-box"><span>状态</span><select v-model="statusFilter" @change="resetPage"><option value="all">全部</option><option value="running">运行中</option><option value="paused">已暂停</option><option value="review_required">等待人工处理</option><option value="completed">已完成</option><option value="failed">失败</option></select></label>
      <label class="attention-check"><input v-model="attentionOnly" type="checkbox" @change="resetPage" />只看需要处理</label>
      <button class="icon-button" type="button" :disabled="loading" title="刷新" @click="load"><RefreshCw :size="18" :class="{ spinning: loading }" /></button>
      <button class="icon-button" type="button" title="筛选设置"><Settings2 :size="18" /></button>
    </div>


    <div class="batch-content-grid">
      <div class="batch-table-card">
        <div class="batch-table-head"><span>批次名称</span><span>总项目数</span><span>已完成</span><span>失败</span><span>当前阶段</span><span>总进度</span><span>运行时间</span><span>主操作</span></div>
        <RouterLink v-for="batch in pagedBatches" :key="batch.id" class="batch-table-row" :to="`/batches/${batch.id}`">
          <div class="batch-name"><strong>{{ batch.name }}</strong><small>ID: {{ batch.id.slice(0, 12).toUpperCase() }}</small><em :class="statusOf(batch.status).tone">{{ statusOf(batch.status).label }}</em></div>
          <span>{{ batch.total }}</span><span>{{ batch.completed }}</span><span :class="{ 'danger-text': batch.failed }">{{ batch.failed }}</span>
          <span class="stage"><i :class="statusOf(batch.status).tone"></i>{{ batch.status === 'completed' ? '全部完成' : batch.status === 'review_required' ? '等待审核' : pending(batch) ? `剩余 ${pending(batch)} 项` : '准备中' }}</span>
          <div class="progress-cell"><strong>{{ progress(batch) }}%</strong><span><i :class="statusOf(batch.status).tone" :style="{ width: `${progress(batch)}%` }"></i></span></div>
          <span>{{ formatDuration(batch.workflow_duration_seconds, batch.started_at ? '计算中' : '-') }}</span>
          <span class="row-action">{{ batch.failed ? '处理异常' : '查看详情' }}<MoreVertical :size="16" /></span>
        </RouterLink>
        <div v-if="!loading && !pagedBatches.length" class="empty-batches"><strong>暂无匹配批次</strong><p>调整筛选条件，或创建一个新的生产批次。</p></div>
        <footer class="table-footer"><span>共 {{ filtered.length }} 条</span><div><button :disabled="page <= 1" @click="page--"><ChevronLeft :size="16" /></button><strong>{{ page }}</strong><span>/ {{ totalPages }}</span><button :disabled="page >= totalPages" @click="page++"><ChevronRight :size="16" /></button></div><select v-model="pageSize" @change="resetPage"><option :value="10">10 条/页</option><option :value="20">20 条/页</option><option :value="50">50 条/页</option></select></footer>
      </div>

      <aside class="batch-side">
        <article class="side-card"><header><strong>状态分布</strong><span>{{ batches.length }} 个批次</span></header><div class="status-distribution"><div class="donut" :style="{ '--done': `${batches.length ? counts.completed / batches.length * 100 : 0}%` }"><strong>{{ batches.length }}</strong><small>总批次</small></div><ul><li><i class="blue"></i>运行中 <b>{{ counts.running }}</b></li><li><i class="orange"></i>已暂停 <b>{{ counts.paused }}</b></li><li><i class="amber"></i>等待处理 <b>{{ counts.review }}</b></li><li><i class="green"></i>已完成 <b>{{ counts.completed }}</b></li><li><i class="red"></i>失败 <b>{{ counts.failed }}</b></li></ul></div></article>
        <article class="side-card"><header><strong>最近批次事件</strong></header><ul class="recent-events"><li v-for="batch in batches.slice(0, 5)" :key="batch.id"><i :class="statusOf(batch.status).tone"></i><span><b>{{ batch.name }}</b><small>{{ statusOf(batch.status).label }}</small></span><time>{{ formatDateTime(batch.updated_at).slice(11, 16) }}</time></li><li v-if="!batches.length" class="muted-event">暂无批次事件</li></ul></article>
        <article class="side-card quick-card"><header><strong>模板快捷入口</strong><RouterLink to="/batches/new">全部模板</RouterLink></header><div><RouterLink to="/batches/new">营销视频模板</RouterLink><RouterLink to="/batches/new">产品介绍模板</RouterLink><RouterLink to="/batches/new">知识分享模板</RouterLink></div></article>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.batch-list-page{color:#182235}.batch-heading{align-items:flex-start;display:flex;justify-content:space-between;margin-bottom:18px}.batch-heading h1{font-size:28px;line-height:1.2;margin:0 0 7px}.batch-heading p{color:#718096;margin:0}.batch-primary{align-items:center;background:#0864eb;border-radius:9px;color:#fff;display:inline-flex;font-weight:700;gap:7px;padding:11px 18px;text-decoration:none}.summary-cards{display:grid;gap:14px;grid-template-columns:repeat(5,minmax(0,1fr));margin-bottom:16px}.summary-card{align-items:center;background:#fff;border:1px solid #e5eaf2;border-radius:12px;box-shadow:0 4px 14px #25375a0a;display:flex;gap:13px;min-height:96px;padding:16px}.summary-icon{align-items:center;border-radius:50%;display:flex;height:50px;justify-content:center;width:50px}.summary-icon svg{height:23px;width:23px}.summary-card small{color:#657188;display:block}.summary-card strong{display:block;font-size:24px;line-height:1.15;margin:3px 0}.summary-card p{color:#8b96a8;font-size:11px;margin:0}.blue .summary-icon{background:#e9f2ff;color:#1473f3}.orange .summary-icon{background:#fff1e5;color:#f47a19}.amber .summary-icon{background:#fff7df;color:#e7a400}.green .summary-icon{background:#e6f8f1;color:#0fb278}.red .summary-icon{background:#ffeded;color:#ee4b55}.filter-bar{align-items:center;background:#fff;border:1px solid #e5eaf2;border-radius:12px 12px 0 0;display:flex;gap:12px;padding:10px 14px}.search-box{align-items:center;border:1px solid #dfe5ed;border-radius:8px;color:#95a0b2;display:flex;gap:7px;padding:8px 10px;width:255px}.search-box input{border:0;min-width:0;outline:0;width:100%}.select-box{align-items:center;border:1px solid #dfe5ed;border-radius:8px;display:flex;font-size:13px;gap:12px;padding:0 10px}.select-box span{color:#5d6879;font-weight:700}.select-box select{border:0;min-width:120px;outline:0;padding:9px 0}.attention-check{align-items:center;color:#556174;display:flex;font-size:13px;gap:7px;margin-left:auto}.icon-button{align-items:center;background:#fff;border:1px solid #dfe5ed;border-radius:8px;color:#5f6c80;display:flex;height:38px;justify-content:center;width:38px}.spinning{animation:spin 1s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.batch-error{background:#fff0f0;border:1px solid #ffcaca;border-radius:8px;color:#c8343d;padding:10px 14px}.batch-content-grid{display:grid;gap:14px;grid-template-columns:minmax(0,1fr) 312px}.batch-table-card,.side-card{background:#fff;border:1px solid #e5eaf2;box-shadow:0 4px 16px #2c3a5208}.batch-table-card{border-radius:0 0 12px 12px;min-width:0}.batch-table-head,.batch-table-row{align-items:center;display:grid;grid-template-columns:minmax(190px,1.55fr) .58fr .58fr .45fr 1fr .9fr .8fr .8fr;gap:10px;padding:12px 14px}.batch-table-head{background:#f8fafc;color:#536176;font-size:12px;font-weight:700}.batch-table-row{border-top:1px solid #edf0f4;color:#536176;font-size:12px;min-height:67px;text-decoration:none}.batch-table-row:hover{background:#f8fbff}.batch-name{min-width:0;position:relative}.batch-name strong,.batch-name small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.batch-name strong{color:#273244;font-size:13px;padding-right:52px}.batch-name small{color:#929cad;margin-top:4px}.batch-name em{border-radius:5px;font-size:10px;font-style:normal;padding:3px 6px;position:absolute;right:0;top:0}.batch-name em.blue{background:#eaf2ff;color:#126bea}.batch-name em.green{background:#e6f8f1;color:#069f6b}.batch-name em.orange,.batch-name em.amber{background:#fff3df;color:#d77a06}.batch-name em.red{background:#ffebec;color:#df3945}.stage{align-items:center;display:flex;gap:6px}.stage i,.recent-events>li>i,.status-distribution li i{border-radius:50%;height:7px;width:7px}.blue{--tone:#1671ef}.orange{--tone:#f58a22}.amber{--tone:#eaae00}.green{--tone:#0ab477}.red{--tone:#f04953}.muted{--tone:#97a1b2}.stage i,.recent-events>li>i,.status-distribution li i{background:var(--tone)}.danger-text{color:#e33d48}.progress-cell strong{display:block;margin-bottom:5px}.progress-cell>span{background:#e9edf3;border-radius:4px;display:block;height:4px;overflow:hidden}.progress-cell i{background:var(--tone);display:block;height:100%}.row-action{align-items:center;color:#0864eb;display:flex;font-weight:700;gap:8px}.empty-batches{color:#788599;padding:55px;text-align:center}.empty-batches strong{color:#344054}.empty-batches p{margin:5px}.table-footer{align-items:center;border-top:1px solid #edf0f4;color:#718096;display:flex;font-size:12px;justify-content:space-between;padding:12px 15px}.table-footer>div{align-items:center;display:flex;gap:8px}.table-footer button{align-items:center;background:#fff;border:1px solid #dde4ed;border-radius:6px;display:flex;height:28px;justify-content:center;width:28px}.table-footer select{border:1px solid #dde4ed;border-radius:6px;padding:6px}.batch-side{display:grid;gap:14px}.side-card{border-radius:12px;padding:16px}.side-card header{align-items:center;display:flex;justify-content:space-between;margin-bottom:14px}.side-card header span,.side-card header a{color:#1671ef;font-size:11px;text-decoration:none}.status-distribution{align-items:center;display:flex;gap:20px}.donut{align-items:center;background:conic-gradient(#0ab477 0 var(--done),#1671ef var(--done) 72%,#f5a800 72% 83%,#f04953 83% 100%);border-radius:50%;display:flex;flex-direction:column;height:116px;justify-content:center;position:relative;width:116px}.donut:after{background:#fff;border-radius:50%;content:"";inset:17px;position:absolute}.donut strong,.donut small{position:relative;z-index:1}.donut strong{font-size:21px}.donut small{color:#7b8799;font-size:10px}.status-distribution ul{display:grid;flex:1;gap:8px;list-style:none;margin:0;padding:0}.status-distribution li{align-items:center;color:#657188;display:flex;font-size:11px;gap:7px}.status-distribution li b{color:#303b4e;margin-left:auto}.recent-events{display:grid;gap:12px;list-style:none;margin:0;padding:0}.recent-events li{align-items:center;display:flex;gap:9px}.recent-events span{min-width:0}.recent-events b,.recent-events small{display:block;max-width:170px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.recent-events b{font-size:11px}.recent-events small{color:#8a95a7;font-size:10px;margin-top:2px}.recent-events time{color:#9aa4b3;font-size:10px;margin-left:auto}.quick-card>div{display:grid;gap:8px;grid-template-columns:repeat(3,1fr)}.quick-card>div a{background:#f5f8ff;border-radius:8px;color:#47617e;font-size:10px;padding:14px 6px;text-align:center;text-decoration:none}.muted-event{color:#8a95a7;font-size:12px}@media(max-width:1350px){.summary-cards{grid-template-columns:repeat(3,1fr)}.batch-content-grid{grid-template-columns:1fr}.batch-side{grid-template-columns:repeat(3,1fr)}.batch-table-head,.batch-table-row{grid-template-columns:minmax(180px,1.4fr) .55fr .55fr .45fr 1fr .9fr .8fr}.batch-table-head>:nth-child(7),.batch-table-row>:nth-child(7){display:none}}@media(max-width:900px){.summary-cards{grid-template-columns:repeat(2,1fr)}.filter-bar{flex-wrap:wrap}.attention-check{margin-left:0}.batch-table-head{display:none}.batch-table-row{grid-template-columns:1fr auto;gap:8px}.batch-table-row>*{display:none!important}.batch-table-row>.batch-name,.batch-table-row>.row-action{display:flex!important}.batch-table-row>.batch-name{display:block!important}.batch-side{grid-template-columns:1fr}.summary-cards>:last-child{grid-column:1/-1}}@media(max-width:560px){.summary-cards{grid-template-columns:1fr}.summary-cards>:last-child{grid-column:auto}.batch-heading{gap:12px}.batch-heading h1{font-size:24px}.search-box{width:100%}}
</style>
