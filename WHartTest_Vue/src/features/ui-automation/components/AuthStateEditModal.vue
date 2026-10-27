<template>
  <a-modal
    v-model:visible="innerVisible"
    :title="modalTitle"
    width="860px"
    :footer="false"
    :mask-closable="false"
    unmount-on-close
    @cancel="handleClose"
  >
    <a-alert type="info" style="margin-bottom: 12px">
      可直接编辑 Cookie 与 localStorage。JWT 类凭据通常存放在 localStorage 的
      <b>token</b> 键中，会话类系统存放在 Cookie 里。保存后立即对后续执行生效（执行器实时读取快照）。
    </a-alert>

    <a-tabs v-model:active-key="activeTab" type="line" @change="onTabChange">
      <!-- 基本信息 -->
      <a-tab-pane key="basic" title="基本信息">
        <a-form layout="vertical">
          <a-form-item label="登录态名称" required>
            <a-input v-model="basicForm.name" :max-length="64" allow-clear placeholder="如：管理员账号登录态" />
          </a-form-item>
          <a-form-item label="描述">
            <a-textarea
              v-model="basicForm.description"
              :max-length="256"
              :auto-size="{ minRows: 2, maxRows: 4 }"
              placeholder="可选，如：用于验证码已关闭的测试环境"
            />
          </a-form-item>
        </a-form>
      </a-tab-pane>

      <!-- Cookie -->
      <a-tab-pane key="cookies" title="Cookie">
        <div class="tab-toolbar">
          <a-button type="primary" size="small" @click="addCookie">
            <template #icon><icon-plus /></template>
            新增 Cookie
          </a-button>
          <span class="tab-tip">过期时间为 Unix 秒；填 -1 表示会话型 Cookie（关闭浏览器失效）。</span>
        </div>
        <a-table
          :columns="cookieColumns"
          :data="cookies"
          :pagination="false"
          :scroll="{ x: 1080 }"
          row-key="_key"
          size="small"
          bordered
        >
          <template #cookie_name="{ record }">
            <a-input v-model="record.name" placeholder="如 sessionid" allow-clear />
          </template>
          <template #cookie_value="{ record }">
            <a-input-password v-model="record.value" placeholder="Cookie 值" allow-clear />
          </template>
          <template #cookie_domain="{ record }">
            <a-input v-model="record.domain" placeholder="如 192.168.3.112" allow-clear />
          </template>
          <template #cookie_path="{ record }">
            <a-input v-model="record.path" placeholder="/" allow-clear />
          </template>
          <template #cookie_expires="{ record }">
            <a-input-number v-model="record.expires" :precision="0" placeholder="-1" />
          </template>
          <template #cookie_samesite="{ record }">
            <a-select v-model="record.sameSite" allow-clear placeholder="未设置" size="small">
              <a-option value="Strict">Strict</a-option>
              <a-option value="Lax">Lax</a-option>
              <a-option value="None">None</a-option>
            </a-select>
          </template>
          <template #cookie_flags="{ record }">
            <div class="flag-cell">
              <a-checkbox v-model="record.httpOnly">HttpOnly</a-checkbox>
              <a-checkbox v-model="record.secure">Secure</a-checkbox>
            </div>
          </template>
          <template #cookie_ops="{ record, rowIndex }">
            <a-button type="text" status="danger" size="mini" @click="removeCookie(rowIndex)">
              <template #icon><icon-delete /></template>
            </a-button>
          </template>
        </a-table>
      </a-tab-pane>

      <!-- localStorage -->
      <a-tab-pane key="storage" title="localStorage">
        <div class="tab-toolbar">
          <a-button type="primary" size="small" @click="addStorageItem">
            <template #icon><icon-plus /></template>
            新增 localStorage 项
          </a-button>
          <span class="tab-tip">
            origin 需为完整地址（如 {{ envOriginHint }}）；修改 Token 时直接改对应 value 即可。
          </span>
        </div>
        <a-table
          :columns="storageColumns"
          :data="storageItems"
          :pagination="false"
          row-key="_key"
          size="small"
          bordered
        >
          <template #storage_origin="{ record }">
            <a-select
              v-model="record.origin"
              placeholder="选择或输入 origin"
              allow-create
              allow-clear
              filterable
              size="small"
            >
              <a-option v-for="opt in originOptions" :key="opt" :value="opt">{{ opt }}</a-option>
            </a-select>
          </template>
          <template #storage_key="{ record }">
            <a-input v-model="record.name" placeholder="如 token" allow-clear />
          </template>
          <template #storage_value="{ record }">
            <a-input-password v-model="record.value" placeholder="键值" allow-clear />
          </template>
          <template #storage_ops="{ record, rowIndex }">
            <a-button type="text" status="danger" size="mini" @click="removeStorageItem(rowIndex)">
              <template #icon><icon-delete /></template>
            </a-button>
          </template>
        </a-table>
      </a-tab-pane>

      <!-- 原始 JSON -->
      <a-tab-pane key="json" title="原始 JSON">
        <div class="tab-toolbar">
          <a-button size="small" @click="formatJson">格式化</a-button>
          <span class="tab-tip">Playwright storageState 结构：cookies + origins[].localStorage。</span>
        </div>
        <a-textarea
          v-model="rawJson"
          class="json-editor"
          :auto-size="{ minRows: 14, maxRows: 22 }"
          placeholder='{"cookies": [], "origins": []}'
        />
        <div v-if="rawError" class="raw-error">{{ rawError }}</div>
      </a-tab-pane>
    </a-tabs>

    <div class="edit-actions">
      <span class="summary">{{ summaryText }}</span>
      <a-space>
        <a-button @click="handleClose">取消</a-button>
        <a-button type="primary" :loading="submitting" @click="handleSubmit">保存</a-button>
      </a-space>
    </div>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Message } from '@arco-design/web-vue'
import { IconPlus, IconDelete } from '@arco-design/web-vue/es/icon'
import { authStateApi } from '../api'
import type { UiAuthState } from '../types'

interface CookieRow {
  _key: string
  name: string
  value: string
  domain: string
  path: string
  expires: number
  httpOnly: boolean
  secure: boolean
  sameSite?: 'Strict' | 'Lax' | 'None'
}

interface StorageRow {
  _key: string
  origin: string
  name: string
  value: string
}

const props = defineProps<{
  visible: boolean
  authState: UiAuthState | null
  /** 环境基础 URL，用于提示可用的 origin */
  baseUrl?: string | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'saved'): void
}>()

let rowSeq = 0
const nextKey = (prefix: string) => `${prefix}-${++rowSeq}`

const innerVisible = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
})

const modalTitle = computed(() => `编辑登录态${props.authState?.name ? ` - ${props.authState.name}` : ''}`)

const envOriginHint = computed(() => {
  const raw = (props.baseUrl || '').trim()
  if (!raw) return 'https://192.168.3.112'
  try {
    const url = new URL(raw)
    return url.origin
  } catch {
    return raw
  }
})

const basicForm = reactive({ name: '', description: '' })
const cookies = ref<CookieRow[]>([])
const storageItems = ref<StorageRow[]>([])
const rawJson = ref('')
const rawError = ref('')
const activeTab = ref<string>('basic')
const submitting = ref(false)

// origin → indexedDB 等未在 UI 暴露的快照，保存时原样带回去，避免手动编辑丢数据
let originExtras: Record<string, Record<string, unknown>> = {}

const originOptions = computed(() => {
  const set = new Set<string>()
  if (props.baseUrl) {
    try {
      set.add(new URL(props.baseUrl).origin)
    } catch {
      /* ignore */
    }
  }
  storageItems.value.forEach((item) => {
    if (item.origin) set.add(item.origin)
  })
  Object.keys(originExtras).forEach((origin) => set.add(origin))
  return Array.from(set)
})

const cookieColumns = [
  { title: '名称', dataIndex: 'name', slotName: 'cookie_name', width: 150 },
  { title: '值', dataIndex: 'value', slotName: 'cookie_value', width: 220 },
  { title: 'Domain', dataIndex: 'domain', slotName: 'cookie_domain', width: 150 },
  { title: 'Path', dataIndex: 'path', slotName: 'cookie_path', width: 90 },
  { title: '过期时间(秒)', dataIndex: 'expires', slotName: 'cookie_expires', width: 130 },
  { title: 'SameSite', dataIndex: 'sameSite', slotName: 'cookie_samesite', width: 110 },
  { title: '属性', slotName: 'cookie_flags', width: 130 },
  { title: '操作', slotName: 'cookie_ops', width: 60, fixed: 'right' as const, align: 'center' as const },
]

const storageColumns = [
  { title: 'Origin', dataIndex: 'origin', slotName: 'storage_origin', width: 240 },
  { title: 'Key', dataIndex: 'name', slotName: 'storage_key', width: 200 },
  { title: 'Value', dataIndex: 'value', slotName: 'storage_value' },
  { title: '操作', slotName: 'storage_ops', width: 60, align: 'center' as const },
]

const summaryText = computed(
  () => `cookies=${cookies.value.filter((c) => c.name.trim()).length}，localStorage=${storageItems.value.filter((i) => i.name.trim()).length}`,
)

const addCookie = () => {
  cookies.value.push({
    _key: nextKey('cookie'),
    name: '',
    value: '',
    domain: '',
    path: '/',
    expires: -1,
    httpOnly: false,
    secure: false,
    sameSite: undefined,
  })
}

const removeCookie = (index: number) => {
  cookies.value.splice(index, 1)
}

const addStorageItem = () => {
  const fallbackOrigin = originOptions.value[0] || envOriginHint.value
  storageItems.value.push({
    _key: nextKey('storage'),
    origin: fallbackOrigin,
    name: '',
    value: '',
  })
}

const removeStorageItem = (index: number) => {
  storageItems.value.splice(index, 1)
}

/** 把 state_json 解析进结构化表单 */
const loadFromState = (state: Record<string, unknown> | null | undefined) => {
  cookies.value = []
  storageItems.value = []
  originExtras = {}
  const snapshot = (state || {}) as Record<string, unknown>

  const rawCookies = Array.isArray(snapshot.cookies) ? snapshot.cookies : []
  rawCookies.forEach((item) => {
    const cookie = (item || {}) as Record<string, unknown>
    const sameSite = cookie.sameSite ? String(cookie.sameSite) : ''
    cookies.value.push({
      _key: nextKey('cookie'),
      name: String(cookie.name ?? ''),
      value: String(cookie.value ?? ''),
      domain: String(cookie.domain ?? ''),
      path: String(cookie.path ?? '/') || '/',
      expires: Number.isFinite(Number(cookie.expires)) ? Number(cookie.expires) : -1,
      httpOnly: Boolean(cookie.httpOnly),
      secure: Boolean(cookie.secure),
      sameSite: ['Strict', 'Lax', 'None'].includes(sameSite)
        ? (sameSite as 'Strict' | 'Lax' | 'None')
        : undefined,
    })
  })

  const rawOrigins = Array.isArray(snapshot.origins) ? snapshot.origins : []
  rawOrigins.forEach((item) => {
    const origin = (item || {}) as Record<string, unknown>
    const originUrl = String(origin.origin ?? '').replace(/\/+$/, '')
    if (origin.indexedDB !== undefined) {
      originExtras[originUrl] = { ...(originExtras[originUrl] || {}), indexedDB: origin.indexedDB }
    }
    const items = Array.isArray(origin.localStorage) ? origin.localStorage : []
    items.forEach((entry) => {
      const pair = (entry || {}) as Record<string, unknown>
      storageItems.value.push({
        _key: nextKey('storage'),
        origin: originUrl,
        name: String(pair.name ?? ''),
        value: String(pair.value ?? ''),
      })
    })
  })
}

/** 结构化表单 → state_json */
const buildStateJson = (): Record<string, unknown> => {
  const state: Record<string, unknown> = {}

  const cookieList = cookies.value
    .filter((c) => c.name.trim())
    .map((c) => {
      const cookie: Record<string, unknown> = {
        name: c.name.trim(),
        value: c.value,
        domain: (c.domain || '').trim(),
        path: (c.path || '/').trim() || '/',
        expires: Number.isFinite(Number(c.expires)) ? Number(c.expires) : -1,
        httpOnly: Boolean(c.httpOnly),
        secure: Boolean(c.secure),
      }
      if (c.sameSite) cookie.sameSite = c.sameSite
      return cookie
    })
  if (cookieList.length) state.cookies = cookieList

  const grouped = new Map<string, { name: string; value: string }[]>()
  storageItems.value
    .filter((item) => item.name.trim() && item.origin.trim())
    .forEach((item) => {
      const origin = item.origin.trim().replace(/\/+$/, '')
      if (!grouped.has(origin)) grouped.set(origin, [])
      grouped.get(origin)!.push({ name: item.name.trim(), value: item.value })
    })
  if (grouped.size) {
    state.origins = Array.from(grouped.entries()).map(([origin, localStorage]) => {
      const entry: Record<string, unknown> = { origin, localStorage }
      const extra = originExtras[origin]
      if (extra && extra.indexedDB !== undefined) entry.indexedDB = extra.indexedDB
      return entry
    })
  }

  return state
}

/** 原始 JSON → 结构化表单（失败返回 false） */
const applyRawJson = (notify = true): boolean => {
  rawError.value = ''
  const text = rawJson.value.trim()
  if (!text) {
    rawError.value = 'JSON 不能为空'
    if (notify) Message.error(rawError.value)
    return false
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(text)
  } catch (err) {
    rawError.value = `JSON 解析失败：${(err as Error).message}`
    if (notify) Message.error(rawError.value)
    return false
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    rawError.value = 'JSON 顶层必须是对象（{ "cookies": [...], "origins": [...] }）'
    if (notify) Message.error(rawError.value)
    return false
  }
  loadFromState(parsed as Record<string, unknown>)
  return true
}

const formatJson = () => {
  if (!applyRawJson()) return
  rawJson.value = JSON.stringify(buildStateJson(), null, 2)
  Message.success('已格式化')
}

/**
 * 页签切换：进入 JSON 页时用当前结构化数据序列化；离开时尽量把 JSON 解析回表格。
 * 解析失败不强行阻止切换（Arco 的受控回退不可靠），而是保留未应用状态，
 * 保存时会再次解析并拦截，避免静默丢失用户改动。
 */
let prevTab = 'basic'
let lastSerialized = ''
const onTabChange = (key: string | number) => {
  const next = String(key)
  if (prevTab === 'json' && next !== 'json') {
    if (!applyRawJson(false)) {
      Message.warning('原始 JSON 解析失败，保存前请先到「原始 JSON」页修正')
    }
  }
  if (next === 'json') {
    rawJson.value = JSON.stringify(buildStateJson(), null, 2)
    lastSerialized = rawJson.value
    rawError.value = ''
  }
  prevTab = next
}

const resetState = () => {
  activeTab.value = 'basic'
  prevTab = 'basic'
  rawJson.value = ''
  lastSerialized = ''
  rawError.value = ''
  submitting.value = false
  basicForm.name = String(props.authState?.name ?? '')
  basicForm.description = String(props.authState?.description ?? '')
  loadFromState(props.authState?.state_json as Record<string, unknown> | null | undefined)
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) resetState()
  },
  { immediate: true },
)

const handleClose = () => {
  innerVisible.value = false
}

const handleSubmit = async () => {
  if (!props.authState) return

  const name = basicForm.name.trim()
  if (!name) {
    Message.error('登录态名称不能为空')
    activeTab.value = 'basic'
    return
  }

  // 原始 JSON 有未应用的改动（或当前停留在 JSON 页）时，以 JSON 内容为准
  if (activeTab.value === 'json' || rawJson.value !== lastSerialized) {
    if (!applyRawJson()) {
      Message.warning('请先在「原始 JSON」页修正内容后再保存')
      return
    }
  }

  // 结构校验（与后端规则对齐，先本地拦一道给出更精确的提示）
  const invalidCookie = cookies.value.find((c) => !c.name.trim() && (c.value || c.domain))
  if (invalidCookie) {
    Message.error('存在只填了值/域名、缺少名称的 Cookie，请补全名称或删除该行')
    activeTab.value = 'cookies'
    return
  }
  const invalidStorage = storageItems.value.find(
    (item) => (item.name.trim() || item.value) && !item.name.trim(),
  )
  if (invalidStorage) {
    Message.error('存在缺少 Key 的 localStorage 项，请补全或删除该行')
    activeTab.value = 'storage'
    return
  }
  const badOrigin = storageItems.value.find(
    (item) => item.name.trim() && !/^https?:\/\//i.test(item.origin.trim()),
  )
  if (badOrigin) {
    Message.error('localStorage 的 origin 必须是 http:// 或 https:// 开头的完整地址')
    activeTab.value = 'storage'
    return
  }

  const stateJson = buildStateJson()
  const hasCookie = Array.isArray(stateJson.cookies) && stateJson.cookies.length > 0
  const hasStorage = Array.isArray(stateJson.origins) && stateJson.origins.length > 0
  if (!hasCookie && !hasStorage) {
    Message.error('登录态不能为空，至少需要一项 Cookie 或 localStorage')
    return
  }

  submitting.value = true
  try {
    await authStateApi.update(props.authState.id, {
      name,
      description: basicForm.description.trim(),
      state_json: stateJson,
    })
    Message.success('登录态已保存')
    innerVisible.value = false
    emit('saved')
  } catch (err) {
    const detail =
      (err as { detail?: string; message?: string })?.detail ||
      (err as { message?: string })?.message
    Message.error(detail || '保存失败')
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.tab-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.tab-tip {
  color: var(--color-text-3);
  font-size: 12px;
}

.flag-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
}

.json-editor :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
}

.raw-error {
  margin-top: 8px;
  color: rgb(var(--danger-6));
  font-size: 12px;
}

.edit-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--color-border-2);
}

.summary {
  color: var(--color-text-3);
  font-size: 12px;
}
</style>
