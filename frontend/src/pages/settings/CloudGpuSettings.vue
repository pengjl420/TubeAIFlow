<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ApiError } from '../../api/client'
import { createComputeConnection, listComputeConnections, type ComputeConnection, type ConnectionInput } from '../../api/compute'
const form = reactive<ConnectionInput>({ name: '', public_key: '', private_key: '', region: '', zone: '', project_id: '' })
const connections = ref<ComputeConnection[]>([])
const busy = ref(false)
const error = ref('')
const message = ref('')
async function refresh() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try { connections.value = await listComputeConnections() }
  catch (err) { error.value = err instanceof ApiError ? `${err.message}（${err.code || '请求失败'}）` : '读取连接失败' }
  finally { busy.value = false }
}
async function save() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  message.value = ''
  try {
    const row = await createComputeConnection({ ...form })
    form.public_key = ''
    form.private_key = ''
    form.name = ''
    connections.value.push(row)
    message.value = '平台连接已保存，可前往调试页面查询实例。'
  } catch (err) { error.value = err instanceof ApiError ? `${err.message}（${err.code || '请求失败'}）` : '保存连接失败' }
  finally { busy.value = false }
}
onMounted(refresh)
</script>
<template>
<div class="gpu-page">
<header><h2>云 GPU 平台设置</h2><p class="muted">优云智算 · 配置用于 GPU 实例管理的 AccessKey。</p></header>
<p v-if="error" class="error-box" role="alert">{{ error }}</p>
<p v-if="message" class="success-box" role="status">{{ message }}</p>
<p v-if="busy" role="status">正在处理，请稍候…</p>
<div class="gpu-grid">
      <section class="gpu-card"><h2>配置 AccessKey</h2><p class="muted">使用账户中心 → API 密钥中的公私钥。保存后密钥由本地引擎加密保管。</p>
        <form @submit.prevent="save"><fieldset :disabled="!!busy">
          <label>连接名称<input v-model="form.name" required maxlength="100" placeholder="例如：我的出图实例" /></label>
          <label>AccessKey ID（公钥）<input v-model="form.public_key" type="password" required autocomplete="off" spellcheck="false" /></label>
          <label>AccessKey Secret（私钥）<input v-model="form.private_key" type="password" required autocomplete="new-password" spellcheck="false" /></label>
          <div class="fields"><label>地域（可选）<input v-model="form.region" maxlength="100" placeholder="填写平台 API 标识" /></label><label>可用区（可选）<input v-model="form.zone" maxlength="100" placeholder="填写平台 API 标识" /></label></div>
          <label>项目 ID（可选）<input v-model="form.project_id" maxlength="100" /></label>
          <p class="muted">地域和项目可留空以查询全部实例。此处使用 GPU 管理公私钥，与模型 API Key 不同。</p>
          <button class="primary" type="submit">保存平台连接</button>
        </fieldset></form>
      </section>
<section class="gpu-card">
<div class="section-heading"><h2>已保存连接</h2><button :disabled="busy" @click="refresh">刷新</button></div>
<p class="muted">凭证由本地引擎加密保存，保存后不回显。已有连接可直接继续使用；新凭证请另存为新连接。</p>
<p v-if="!connections.length" class="empty">尚未配置平台连接。</p>
<dl v-for="item in connections" :key="item.id"><dt>连接名称</dt><dd>{{ item.name }}</dd><dt>凭证</dt><dd>已配置 · 加密保存</dd><dt>查询范围</dt><dd>{{ item.region || '全部地域' }} / {{ item.zone || '全部可用区' }}</dd></dl>
<RouterLink class="primary settings-link" to="/cloud-gpu">前往接口调试 →</RouterLink>
<p class="muted">保存仅写入本地配置，不验证平台认证。</p>
<a href="https://www.compshare.cn/docs/gpus/operationexample" target="_blank" rel="noopener noreferrer">官方接口与密钥说明 ↗</a>
</section></div></div>
</template>
<style scoped src="../../cloud-gpu.css"></style>
<style scoped>.settings-link{display:inline-block;padding:12px;border-radius:8px;margin:12px 0}</style>
