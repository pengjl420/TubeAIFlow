<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { Cloud, RefreshCw, Power, Square, Settings2, X, ScrollText } from 'lucide-vue-next'
import { confirmAction } from '../services/feedback'
import { ApiError } from '../api/client'
import { listComputeConnections, listComputeInstances, powerComputeInstance, type ComputeConnection, type ComputeInstance } from '../api/compute'

type Resource = ComputeInstance & { connection: ComputeConnection }
type Snapshot = { instances: ComputeInstance[]; error: string; updatedAt: string }
const connections = ref<ComputeConnection[]>([])
const snapshots = ref<Record<string, Snapshot>>({})
const refreshing = ref(false)
const error = ref('')
const pending = ref<Record<string, boolean>>({})
const history = ref<{ key: string; time: string; operation: string; result: string }[]>([])
const logTarget = ref<Resource | null>(null)
const resources = computed(() => connections.value.flatMap(connection => (snapshots.value[connection.id]?.instances || []).map(instance => ({ ...instance, connection }))))
const logs = computed(() => history.value.filter(item => item.key === (logTarget.value ? key(logTarget.value) : '')))
const states: Record<string, string> = { Running: '运行中', Stopped: '已关机', Starting: '启动中', Stopping: '关机中', Install: '安装中', Rebooting: '重启中' }
let timer: ReturnType<typeof setInterval> | undefined
let disposed = false
const querying = new Set<string>()
const generations: Record<string, number> = {}
const key = (item: Resource) => `${item.connection.id}:${item.instance_id}`
function describe(err: unknown) {
  return `${err instanceof Error ? err.message : '操作失败'}${err instanceof ApiError && err.code ? `（${err.code}）` : ''}`
}
async function refresh() {
  if (refreshing.value || disposed) return
  refreshing.value = true
  try {
    const rows = await listComputeConnections()
    if (disposed) return
    connections.value = rows
    error.value = ''
    void Promise.allSettled(rows.map(async connection => {
      if (querying.has(connection.id)) return
      querying.add(connection.id)
      const generation = generations[connection.id] || 0
      try {
        const instances: ComputeInstance[] = []
        let offset = 0
        while (!disposed) {
          const page = await listComputeInstances(connection.id, offset, 100)
          instances.push(...page.instances)
          offset += page.instances.length
          if (offset >= page.total) break
          if (!page.instances.length) throw new Error('实例列表尚未读取完整，请稍后刷新')
        }
        if (!disposed && generation === (generations[connection.id] || 0)) snapshots.value[connection.id] = { instances: [...new Map(instances.map(item => [item.instance_id, item])).values()], error: '', updatedAt: new Date().toLocaleString() }
      } catch (err) {
        if (!disposed && generation === (generations[connection.id] || 0)) snapshots.value[connection.id] = { instances: snapshots.value[connection.id]?.instances || [], updatedAt: snapshots.value[connection.id]?.updatedAt || '', error: describe(err) }
      } finally { querying.delete(connection.id) }
    }))
  } catch (err) { if (!disposed) error.value = describe(err) }
  finally { refreshing.value = false }
}
function disabledReason(item: Resource, action: 'start' | 'stop') {
  if (pending.value[key(item)]) return '正在处理此实例的操作'
  if (error.value || snapshots.value[item.connection.id]?.error) return '状态已过期，等待查询恢复'
  if (action === 'stop' && item.is_spot) return '抢占式实例不支持手动关机'
  if (item.state !== (action === 'start' ? 'Stopped' : 'Running')) return action === 'start' ? '仅已关机实例可开机' : '仅运行中实例可关机'
  return ''
}
async function power(item: Resource, action: 'start' | 'stop') {
  if (disabledReason(item, action)) return
  const id = key(item)
  const label = action === 'start' ? '开机' : '关机'
  pending.value[id] = true
  try {
    const confirmed = await confirmAction({ title: `确认${label}实例`, description: `${item.connection.name} · ${item.name || item.instance_id}（${item.instance_id}）`, detail: action === 'start' ? '开机后将按平台规则计费。' : '关机将中断此实例上正在运行的任务。', confirmText: `确认${label}` })
    if (!confirmed || disposed) return
    generations[item.connection.id] = (generations[item.connection.id] || 0) + 1
    let result: string
    try {
      await powerComputeInstance(item.connection.id, item.instance_id, action)
      result = '请求已受理，等待平台状态更新'
    } catch (err) { result = describe(err) + '；请等待状态刷新确认结果，请勿直接重复提交' }
    history.value.unshift({ key: id, time: new Date().toLocaleString(), operation: `${label} · ${item.name || item.instance_id}`, result })
    // Keep this resource disabled until a subsequent successful query completes.
    snapshots.value[item.connection.id] = { ...snapshots.value[item.connection.id]!, error: '操作已提交，正在重新确认实例状态' }
    await refresh()
  } finally { delete pending.value[id] }
}
onMounted(() => { void refresh(); timer = setInterval(() => { void refresh() }, 5000) })
onUnmounted(() => { disposed = true; if (timer) clearInterval(timer) })
</script>

<template>
  <div class="gpu-page">
    <header class="gpu-header compact-header"><h1><Cloud :size="24" />云 GPU 平台</h1><div class="header-actions"><span class="refresh-label">每 5 秒自动刷新</span><button :disabled="refreshing" @click="refresh"><RefreshCw :size="15" />{{ refreshing ? '刷新中…' : '刷新' }}</button><RouterLink class="mode" to="/settings/cloud-gpu"><Settings2 :size="15" />连接设置</RouterLink></div></header>
    <p v-if="error" class="error-box" role="alert">{{ error }}</p>
    <div class="connection-strip">
      <span class="connection-count">{{ connections.length }} 个连接</span>
      <p v-if="!connections.length" class="connection-empty">{{ refreshing ? '正在读取平台连接…' : '尚无连接，请前往连接设置配置 AccessKey。' }}</p>
      <details v-for="connection in connections" :key="connection.id" class="connection-detail">
        <summary><span class="connection-dot" :class="{ failed: snapshots[connection.id]?.error, waiting: !snapshots[connection.id]?.updatedAt }"></span>{{ connection.name }}<span v-if="snapshots[connection.id]?.error" class="failure">查询异常</span></summary>
        <div class="connection-info"><strong>{{ connection.provider === 'compute.compshare' ? '优云智算' : connection.provider }}</strong><span>{{ connection.region || '全部地域' }} / {{ connection.zone || '全部可用区' }}</span><span>最近成功刷新：{{ snapshots[connection.id]?.updatedAt || '等待查询' }}</span></div>
      </details>
    </div>
    <p v-for="connection in connections.filter(item => snapshots[item.id]?.error)" :key="connection.id" class="error-box" role="alert">{{ connection.name }}：{{ snapshots[connection.id]?.error }}（保留上次数据）</p>
    <section class="gpu-card">
      <div class="section-heading"><h2>GPU 实例</h2><span class="instance-count">{{ resources.length }} 个实例</span></div>
      <div class="table-scroll"><table><thead><tr><th>实例 / 平台连接</th><th>状态</th><th>地域 / 可用区</th><th>GPU</th><th>类型</th><th>操作</th></tr></thead><tbody>
        <tr v-for="item in resources" :key="key(item)"><td><strong>{{ item.name || '未命名实例' }}</strong><small>{{ item.instance_id }}</small><small>{{ item.connection.name }}</small></td><td><span class="status-pill" :class="{ running: item.state === 'Running' }">{{ states[item.state] || item.state }}</span><small v-if="error || snapshots[item.connection.id]?.error">状态待更新</small></td><td>{{ item.region || '—' }}<small>{{ item.zone || '—' }}</small></td><td>{{ item.gpu_type || '未提供型号' }} × {{ item.gpu_count }}</td><td>{{ item.is_spot ? '抢占式' : '非抢占式' }}</td><td><div class="row-actions"><span :title="disabledReason(item, 'start')"><button class="primary" :disabled="!!disabledReason(item, 'start')" @click="power(item, 'start')"><Power :size="14" />开机</button></span><span :title="disabledReason(item, 'stop')"><button :disabled="!!disabledReason(item, 'stop')" @click="power(item, 'stop')"><Square :size="14" />关机</button></span><button @click="logTarget = item"><ScrollText :size="14" />操作日志</button></div></td></tr>
        <tr v-if="!resources.length"><td colspan="6" class="empty">{{ refreshing ? '正在读取实例…' : '暂无实例，请检查连接配置和查询范围。' }}</td></tr>
      </tbody></table></div>
    </section>
    <Teleport to="body"><div v-if="logTarget" class="log-backdrop" @click.self="logTarget = null" @keydown.esc="logTarget = null"><aside class="log-drawer" role="dialog" aria-modal="true" aria-label="实例操作日志" tabindex="-1"><div class="section-heading"><h2>操作日志</h2><button autofocus aria-label="关闭操作日志" @click="logTarget = null"><X :size="18" /></button></div><p>{{ logTarget.connection.name }} · {{ logTarget.name || logTarget.instance_id }}</p><p class="muted">{{ logTarget.instance_id }} · 本次页面会话全部操作记录</p><p v-if="!logs.length" class="empty">此实例暂无操作记录。</p><ol class="log-list"><li v-for="(entry, index) in logs" :key="index"><time>{{ entry.time }}</time><strong>{{ entry.operation }}</strong><p>{{ entry.result }}</p></li></ol></aside></div></Teleport>
  </div>
</template>
<style scoped src="../cloud-gpu.css"></style>
<style scoped>
.gpu-page{gap:12px}.compact-header{padding:0;gap:12px}.compact-header h1{font-size:23px;margin:0}.header-actions{display:flex;align-items:center;gap:8px}.refresh-label,.connection-count,.instance-count{font-size:12px;color:var(--muted);white-space:nowrap}.header-actions button,.header-actions .mode{min-height:34px;padding:7px 10px}.connection-strip{display:flex;align-items:flex-start;gap:8px;flex-wrap:wrap;padding:10px 12px;background:var(--surface);border:1px solid var(--line);border-radius:9px}.connection-count{line-height:28px;margin-right:4px}.connection-detail{max-width:100%;font-size:12px}.connection-detail summary{display:flex;align-items:center;gap:7px;min-height:28px;padding:0 9px;border-radius:6px;background:var(--surface-soft);cursor:pointer;list-style:none}.connection-detail summary::-webkit-details-marker{display:none}.connection-detail summary:after{content:'⌄';color:var(--muted);margin-left:4px}.connection-detail[open] summary:after{content:'⌃'}.connection-info{display:grid;gap:6px;padding:10px;line-height:1.5;color:var(--muted)}.connection-dot{width:6px;height:6px;border-radius:50%;background:var(--success);flex-shrink:0}.connection-dot.waiting{background:var(--muted)}.connection-dot.failed{background:var(--danger)}.connection-empty{font-size:12px;color:var(--muted);margin:5px 0}.gpu-card{padding:16px 18px}.section-heading{margin-bottom:12px}@media(max-width:600px){.compact-header{flex-wrap:wrap}.refresh-label{display:none}.header-actions{flex-wrap:wrap}.compact-header h1{font-size:21px}.gpu-card{padding:14px 12px}}
.failure{color:var(--danger);font-size:13px;overflow-wrap:anywhere}.row-actions{display:flex;gap:8px}.status-pill{padding:6px 10px;border-radius:20px;background:var(--surface-soft);color:var(--muted)}.status-pill.running{background:var(--success-soft);color:var(--success)}.log-backdrop{position:fixed;inset:0;z-index:1000;background:#0006;display:flex;justify-content:flex-end}.log-drawer{width:min(520px,100%);height:100%;overflow-y:auto;background:var(--surface);color:var(--ink);padding:28px;box-shadow:-8px 0 30px #0002;box-sizing:border-box;overflow-wrap:anywhere}.log-drawer h2{margin:0}.log-list{list-style:none;padding:0}.log-list li{border-top:1px solid var(--line);padding:18px 0}.log-list time{display:block;color:var(--muted);font-size:12px;margin-bottom:8px}.log-list p{white-space:pre-wrap;line-height:1.7;margin-bottom:0}
</style>
