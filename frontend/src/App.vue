<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import type {
  Config,
  HostProps,
  NfoField,
  PendingPage,
  Report,
  RunSummary,
  Rule,
  RuleSet,
  TranslationInfo,
} from './types'
import NfoFieldSelect from './NfoFieldSelect.vue'
const props = defineProps<HostProps>()
const cfg = ref<Config>()
const servers = ref<string[]>([])
const channels = ref<{ title: string; value: string }[]>([])
const supported = ref<Record<string, string[]>>({})
const nfoFields = ref<NfoField[]>([])
const translation = ref<TranslationInfo>({
  enabled: false,
  policies: [],
  fields: {
    title: '标题(title)',
    plot: '剧情简介(plot)',
    outline: '简短摘要(outline)',
    tagline: '宣传语(tagline)',
  },
})
const translationMode = ref('normal')
const languageOps = ['language_missing', 'language_mismatch', 'language_unknown']
const usesTranslation = (rule: Rule) =>
  ['translate', 'nfo_translate'].includes(rule.action) ||
  rule.conditions.some((c) => languageOps.includes(c.op))
const policyFields = (rule: Rule) =>
  translation.value.policies.find((p) => p.id === rule.translation_policy)?.fields ||
  Object.keys(translation.value.fields)
const pendingCount = ref(0)
const pendingPage = shallowRef<PendingPage>()
const pendingLoading = ref(false)
let pendingRequest = 0
const tab = ref('rules')
const error = ref('')
const notice = ref('')
const saving = ref(false)
const live = ref({ busy: false, run_id: '', error: '' })
const runs = shallowRef<RunSummary[]>([])
const report = shallowRef<Report>()
const viewRunId = ref('')
const recordLoading = ref(false)
const historySelected = ref<string[]>([])
const deleteIds = ref<string[]>([])
const deleting = ref(false)
const historyPage = ref(1)
const historySize = 20
const historyRuns = computed(() =>
  runs.value.slice((historyPage.value - 1) * historySize, historyPage.value * historySize),
)
let reportRequest = 0
let filterTimer: ReturnType<typeof setTimeout> | undefined
let resettingFilters = false
let followNewRun = false
const backups = ref<{ id: string; path: string; created: number; committed: boolean }[]>([])
const selected = ref<string[]>([])
const query = ref('')
const statusFilter = ref('')
const kindFilter = ref('')
const ruleFilter = ref('')
const labels: Record<string, string> = {
  movie: '电影',
  tv: '整部剧',
  season: '季',
  episode: '单集',
  nfo: 'NFO',
  poster: '主图／海报',
  backdrop: '背景图',
  logo: '徽标',
  banner: '横幅',
  landscape: '横版图',
  thumb: '缩略图／单集主图',
  clearart: '透明艺术图',
  disc: '光盘图',
  pending: '待处理',
  complete: '完整',
  report: '仅报告',
  unstable: '等待文件稳定',
  ignored: '已忽略',
  cooldown: '冷却中',
  manual: '待人工处理',
  failed: '失败',
  unimproved: '未改善',
  partial: '部分完成',
  repaired: '已修复',
  unchanged: '内容未变化',
  verified: '同步已验证',
  unconfirmed: '图片更新未确认',
  locked: '字段已锁定',
  submitted: '刷新已提交',
  scanning: '扫描中',
  inspected: '已巡检',
  repairing: '修复中',
  finished: '已完成',
  cancelled: '已停止',
  excluded: '已排除',
  restored: '已恢复',
  batch_limited: '达到批次上限',
  interrupted: '运行被中断',
  sync_pending: '等待 Emby 同步',
  syncing: '同步中',
  paused: '已暂停',
  needs_recheck: '需要重新确认',
  discovering: '发现媒体中',
  unknown: '未确认层级',
  source_empty: '来源为空',
  candidate_rejected: '候选不符合规则',
  network: '网络失败',
  io: '文件读写失败',
  file_conflict: '文件冲突',
  internal: '内部错误',
}
const exitLabels: Record<string, string> = {
  batch_limit: '达到修复批次上限，可继续剩余任务',
  stop: '已按请求停止',
  interrupted: '上次运行中断，等待手动继续',
  error: '运行出错',
  inspected: '巡检结束',
  completed: '本轮处理结束',
}
const ops = [
  { value: 'missing', text: 'NFO 不存在' },
  { value: 'invalid', text: 'XML 损坏或根元素错误' },
  { value: 'empty', text: '字段缺失或为空' },
  { value: 'min_length', text: '字段长度小于' },
  { value: 'regex', text: '字段匹配正则' },
  { value: 'identity_missing', text: '媒体来源 ID 缺失' },
  { value: 'conflict', text: '身份／季集号冲突（仅报告）' },
]
const actions = [
  { value: 'report', text: '仅报告' },
  { value: 'nfo', text: '只更新 NFO' },
  { value: 'matched_images', text: '只更新命中图片' },
  { value: 'selected_images', text: '更新指定图片' },
  { value: 'both', text: '更新 NFO 和图片' },
]
ops.push(
  { value: 'language_missing', text: '缺少目标语言内容' },
  { value: 'language_mismatch', text: '现有内容不是目标语言' },
  { value: 'language_unknown', text: '语言或内容来源无法确认' },
)
actions.push(
  { value: 'translate', text: '仅补齐所选文字字段' },
  { value: 'nfo_translate', text: '重新生成 NFO 并翻译' },
)
const page = ref(1)
const visible = computed(() => report.value?.items || [])
const total = computed(() => report.value?.total || 0)
const filters = () => ({
  query: query.value,
  status: statusFilter.value,
  kind: kindFilter.value,
  rule_set: ruleFilter.value,
})
watch(
  [query, statusFilter, kindFilter, ruleFilter],
  () => {
    if (resettingFilters || !viewRunId.value) return
    selected.value = []
    page.value = 1
    reportRequest++
    recordLoading.value = true
    clearTimeout(filterTimer)
    filterTimer = setTimeout(() => {
      if (tab.value === 'results') guard(() => open(viewRunId.value, false))
    }, 250)
  },
  { flush: 'sync' },
)
watch(tab, (value) => {
  if (value !== 'results') {
    reportRequest++
    recordLoading.value = false
    clearTimeout(filterTimer)
  }
  if (value === 'settings') guard(poll)
  if (value === 'pending') guard(() => loadPending(1))
  else pendingRequest++
  if (value === 'results' && viewRunId.value && !recordLoading.value)
    guard(() => open(viewRunId.value, false))
})
const assetOptions = (set: RuleSet) => [
  ...new Set(set.kinds.flatMap((k) => supported.value[k] || [])),
]
const url = (path: string) => `plugin/${props.pluginId}/${path}`
function message(e: unknown) {
  const v = e as { response?: { data?: { detail?: unknown } }; message?: string }
  return typeof v.response?.data?.detail === 'string'
    ? v.response.data.detail
    : JSON.stringify(v.response?.data?.detail || v.message || '请求失败')
}
async function guard(work: () => Promise<void>) {
  error.value = ''
  try {
    await work()
  } catch (e) {
    error.value = message(e)
  }
}
async function load() {
  const data = await props.api.get<{
    config: Config
    servers: string[]
    channels: { title: string; value: string }[]
    assets: Record<string, string[]>
    nfo_fields: NfoField[]
    translation: TranslationInfo
  }>(url('settings'))
  cfg.value = data.config
  servers.value = data.servers
  channels.value = data.channels
  supported.value = data.assets
  nfoFields.value = data.nfo_fields || []
  if (data.translation) translation.value = data.translation
}
async function poll() {
  const data = await props.api.get<{
    live: typeof live.value
    runs: RunSummary[]
    pending_count: number
    backups?: typeof backups.value
  }>(url('status'), { params: { include_backups: tab.value === 'settings' } })
  live.value = data.live
  runs.value = data.runs
  pendingCount.value = data.pending_count || 0
  if (tab.value === 'pending' && !pendingLoading.value)
    await loadPending(pendingPage.value?.page || 1)
  if (data.backups) backups.value = data.backups
  historyPage.value = Math.min(
    historyPage.value,
    Math.max(1, Math.ceil(runs.value.length / historySize)),
  )
  historySelected.value = historySelected.value.filter((id) => runs.value.some((r) => r.id === id))
  if (data.live.error) error.value = data.live.error
  if (followNewRun && data.live.run_id) {
    followNewRun = false
    await open(data.live.run_id)
    return
  }
  const summary = runs.value.find((r) => r.id === viewRunId.value)
  if (viewRunId.value && !summary && !recordLoading.value) {
    viewRunId.value = ''
    report.value = undefined
    selected.value = []
    return
  }
  if (
    tab.value === 'results' &&
    report.value &&
    summary &&
    summary.updated !== report.value.updated &&
    !recordLoading.value
  )
    await open(report.value.id, false)
}
async function open(id: string, switchTab = true) {
  clearTimeout(filterTimer)
  const request = ++reportRequest
  viewRunId.value = id
  recordLoading.value = true
  if (switchTab) {
    resettingFilters = true
    query.value = ''
    statusFilter.value = ''
    kindFilter.value = ''
    ruleFilter.value = ''
    resettingFilters = false
    selected.value = []
    page.value = 1
    report.value = undefined
    tab.value = 'results'
  }
  try {
    const data = await props.api.get<Report>(url('report'), {
      params: { run_id: id, page: page.value, page_size: 100, ...filters() },
    })
    if (request === reportRequest && tab.value === 'results') {
      report.value = data
      page.value = data.page
    }
  } finally {
    if (request === reportRequest) recordLoading.value = false
  }
}
async function changePage(value: number) {
  page.value = value
  await open(viewRunId.value, false)
}
async function selectAllResults() {
  const id = viewRunId.value
  const request = reportRequest
  const data = await props.api.get<{ ids: string[] }>(url('report'), {
    params: { run_id: id, ids_only: true, ...filters() },
  })
  if (id === viewRunId.value && request === reportRequest) selected.value = data.ids
}
async function deleteRuns() {
  deleting.value = true
  try {
    const ids = [...deleteIds.value]
    const data = await props.api.post<{ deleted: string[] }>(url('delete_runs'), { ids })
    if (ids.includes(viewRunId.value)) {
      reportRequest++
      viewRunId.value = ''
      report.value = undefined
      selected.value = []
      recordLoading.value = false
    }
    deleteIds.value = []
    historySelected.value = historySelected.value.filter((id) => !ids.includes(id))
    notice.value = `已删除 ${data.deleted.length} 条运行记录`
    await poll()
  } finally {
    deleting.value = false
  }
}
async function save() {
  if (!cfg.value) return
  saving.value = true
  try {
    await props.api.post(url('settings'), cfg.value)
    notice.value = '设置已保存'
  } finally {
    saving.value = false
  }
}
async function start(operation: string, extra: Record<string, unknown> = {}) {
  await props.api.post(url('start'), {
    operation,
    run_id: ['run', 'inspect', 'restore', 'refresh_pending'].includes(operation)
      ? null
      : report.value?.id,
    ...extra,
  })
  selected.value = []
  if (['run', 'inspect', 'restore', 'refresh_pending'].includes(operation)) {
    followNewRun = true
    viewRunId.value = ''
    report.value = undefined
  }
  tab.value = 'results'
  await poll()
}
async function loadPending(page: number) {
  const request = ++pendingRequest
  pendingLoading.value = true
  try {
    const data = await props.api.get<PendingPage>(url('pending'), {
      params: { page, page_size: 100 },
    })
    if (request === pendingRequest) pendingPage.value = data
  } finally {
    pendingLoading.value = false
  }
}
function details(value: Record<string, unknown>) {
  return JSON.stringify(value, null, 2)
}
async function launch(dry: boolean) {
  await save()
  await start('run', { dry_run: dry, run_id: null })
}
async function applyTranslation() {
  const mode = translationMode.value
  await start('repair', {
    ids: [...selected.value],
    retry: true,
    translation_overwrite: mode === 'overwrite',
    translation_force: mode === 'force',
  })
  translationMode.value = 'normal'
}
function lines(value: string) {
  return value
    .split('\n')
    .map((v) => v.trim())
    .filter(Boolean)
}
function setLines(object: RuleSet, key: 'roots' | 'excludes', event: Event) {
  object[key] = lines((event.target as HTMLTextAreaElement).value)
}
function addSet() {
  cfg.value?.rule_sets.push({
    id: crypto.randomUUID(),
    name: '新规则集',
    enabled: true,
    roots: [],
    kinds: ['movie', 'tv', 'episode'],
    excludes: [],
    exclude_regex: '',
    exclude_season_zero: false,
    emby: 'off',
    rules: [],
  })
}
function copySet(set: RuleSet) {
  const copied = JSON.parse(JSON.stringify(set)) as RuleSet
  copied.id = crypto.randomUUID()
  copied.name += ' 副本'
  cfg.value?.rule_sets.push(copied)
}
function addRule(set: RuleSet, category: string) {
  set.rules.push({
    id: crypto.randomUUID(),
    name: category === 'nfo' ? 'NFO 完整性' : '图片完整性',
    enabled: true,
    category,
    match: 'any',
    conditions: category === 'nfo' ? [{ op: 'empty', field: 'plot', value: '' }] : [],
    images:
      category === 'image'
        ? [
            {
              type: assetOptions(set)[0] || 'poster',
              missing: true,
              damaged: true,
              min_width: 0,
              min_height: 0,
            },
          ]
        : [],
    action: 'report',
    selected_images: [],
    translation_policy: 'default',
    translation_fields: ['plot', 'outline'],
  })
}
function toggleImage(rule: Rule, asset: string, checked: boolean) {
  if (checked)
    rule.images.push({ type: asset, missing: true, damaged: true, min_width: 0, min_height: 0 })
  else rule.images = rule.images.filter((i) => i.type !== asset)
}
function toggleServer(name: string, checked: boolean) {
  if (!cfg.value) return
  if (checked) cfg.value.emby_servers.push({ name, libraries: [], mappings: [] })
  else cfg.value.emby_servers = cfg.value.emby_servers.filter((s) => s.name !== name)
}
function stamp(time: number) {
  return new Date(time * 1000).toLocaleString()
}
let timer: ReturnType<typeof setInterval>
let polling = false
onMounted(() => {
  guard(async () => {
    await load()
    await poll()
  })
  timer = setInterval(async () => {
    if (polling) return
    polling = true
    try {
      await guard(poll)
    } finally {
      polling = false
    }
  }, 4000)
})
onUnmounted(() => {
  clearInterval(timer)
  clearTimeout(filterTimer)
  reportRequest++
  pendingRequest++
})
</script>

<template>
  <div class="nfo-app">
    <header>
      <div>
        <h2>元数据巡检</h2>
        <p>按规则补齐 NFO 与图片，同步 Emby 显示。</p>
      </div>
      <span class="badge" :class="{ active: live.busy }">{{
        live.busy ? '任务运行中' : '空闲'
      }}</span>
    </header>
    <div v-if="error" role="alert" class="alert error">
      {{ error }} <button @click="error = ''">关闭</button>
    </div>
    <div v-if="notice" role="status" class="alert">
      {{ notice }} <button @click="notice = ''">关闭</button>
    </div>
    <nav aria-label="插件页面">
      <button
        v-for="t in [
          { id: 'rules', name: '规则' },
          { id: 'results', name: '巡检结果' },
          { id: 'history', name: '运行记录' },
          { id: 'pending', name: '待同步（' + pendingCount + '）' },
          { id: 'settings', name: '设置' },
        ]"
        :key="t.id"
        :class="{ chosen: tab === t.id }"
        @click="tab = t.id"
      >
        {{ t.name }}
      </button>
    </nav>
    <div v-if="cfg" class="toolbar">
      <label
        ><input type="checkbox" v-model="cfg.enabled" :disabled="live.busy" />启用修复及 Emby
        刷新</label
      ><button :disabled="live.busy || saving" @click="guard(save)">保存设置</button
      ><button :disabled="live.busy" @click="guard(() => launch(true))">试运行</button
      ><button
        class="primary"
        :disabled="live.busy || !cfg.enabled"
        @click="guard(() => launch(false))"
      >
        按规则运行</button
      ><button
        v-if="live.busy"
        @click="
          guard(async () => {
            await api.post(url('stop'))
            notice = '已请求停止'
          })
        "
      >
        停止
      </button>
    </div>
    <p v-if="!cfg">正在读取设置…</p>
    <section v-if="cfg && tab === 'rules'">
      <p class="hint">
        所有启用规则独立判断，命中动作合并。同一图片类型有任一合格文件即通过。试运行不会写入媒体文件或刷新
        Emby。
      </p>
      <fieldset v-for="(set, si) in cfg.rule_sets" :key="set.id" :disabled="live.busy" class="card">
        <div class="row">
          <label><input type="checkbox" v-model="set.enabled" />启用</label
          ><input aria-label="规则集名称" v-model="set.name" class="grow" /><button
            @click="copySet(set)"
          >
            复制</button
          ><button @click="cfg.rule_sets.splice(si, 1)">删除规则集</button>
        </div>
        <div class="grid">
          <label
            >检查目录（每行一个）<textarea
              :value="set.roots.join('\n')"
              @input="setLines(set, 'roots', $event)"
              placeholder="/media/115/电影"
            /></label
          ><label
            >排除目录（每行一个）<textarea
              :value="set.excludes.join('\n')"
              @input="setLines(set, 'excludes', $event)"
            />
          </label>
        </div>
        <div class="row">
          <label v-for="kind in ['movie', 'tv', 'season', 'episode']" :key="kind"
            ><input type="checkbox" :value="kind" v-model="set.kinds" />{{ labels[kind] }}</label
          ><label><input type="checkbox" v-model="set.exclude_season_zero" />排除 Season 0</label>
        </div>
        <div class="grid">
          <label>排除路径正则<input v-model="set.exclude_regex" placeholder="留空不排除" /></label
          ><label
            >Emby 联动<select v-model="set.emby">
              <option value="off">关闭</option>
              <option value="changed">本地修改后刷新</option>
              <option value="compare">修改后刷新，并检查 Emby 显示缺失</option>
            </select></label
          >
        </div>
        <article v-for="(rule, ri) in set.rules" :key="rule.id" class="rule">
          <div class="row">
            <label><input type="checkbox" v-model="rule.enabled" />启用</label
            ><input v-model="rule.name" aria-label="规则名称" class="grow" /><span>{{
              rule.category === 'nfo' ? 'NFO' : '图片'
            }}</span
            ><button @click="set.rules.splice(ri, 1)">删除</button>
          </div>
          <div class="grid">
            <label
              >条件关系<select v-model="rule.match">
                <option value="any">任一满足</option>
                <option value="all">全部满足</option>
              </select></label
            ><label
              >命中动作<select v-model="rule.action">
                <option
                  v-for="a in actions.filter((a) =>
                    rule.category === 'image'
                      ? !['translate', 'nfo_translate'].includes(a.value)
                      : a.value !== 'matched_images',
                  )"
                  :value="a.value"
                  :key="a.value"
                >
                  {{ a.text }}
                </option>
              </select></label
            >
          </div>
          <template v-if="rule.category === 'nfo'">
            <div v-for="(cond, ci) in rule.conditions" :key="ci" class="row condition">
              <select aria-label="NFO 判定条件" v-model="cond.op">
                <option v-for="op in ops" :key="op.value" :value="op.value">
                  {{ op.text }}
                </option></select
              ><select
                v-if="languageOps.includes(cond.op)"
                v-model="cond.field"
                aria-label="翻译条件字段"
              >
                <option v-for="(name, field) in translation.fields" :key="field" :value="field">
                  {{ name }}
                </option></select
              ><NfoFieldSelect
                v-if="['empty', 'regex', 'min_length'].includes(cond.op)"
                v-model="cond.field"
                :fields="nfoFields"
                :kinds="set.kinds"
              /><input
                v-if="['regex', 'min_length'].includes(cond.op)"
                aria-label="条件值"
                v-model="cond.value"
                :placeholder="cond.op === 'regex' ? '正则表达式' : '最小字符数'"
              /><button @click="rule.conditions.splice(ci, 1)">移除条件</button>
            </div>
            <p class="hint">
              未找到字段、空标签或内容仅有空白均视为空；重复字段至少有一项非空即通过，0 和 false
              不算空。标准中的可选字段由你按需添加。
            </p>
            <div v-if="usesTranslation(rule)" class="card">
              <p v-if="!translation.enabled" class="hint">
                元数据翻译插件未启用或不可用。请在独立插件中配置服务和策略；图片任务可继续处理。
              </p>
              <label
                >翻译策略<select v-model="rule.translation_policy">
                  <option
                    v-if="!translation.policies.some((p) => p.id === rule.translation_policy)"
                    :value="rule.translation_policy"
                  >
                    {{ rule.translation_policy }}（未找到）
                  </option>
                  <option v-for="p in translation.policies" :key="p.id" :value="p.id">
                    {{ p.name }} · {{ p.target_language }}
                  </option>
                </select></label
              >
              <div class="row">
                <label v-for="(name, field) in translation.fields" :key="field"
                  ><input
                    type="checkbox"
                    :value="field"
                    v-model="rule.translation_fields"
                    :disabled="
                      !policyFields(rule).includes(field) &&
                      !rule.translation_fields.includes(field)
                    "
                  />{{ name }}</label
                >
              </div>
              <p class="hint">
                条件字段也须勾选。仅补齐文字会保留其他 NFO
                节点；重建操作采用官方候选。不同策略同时命中同一 NFO
                时转人工处理。摘要(outline)仅写入本地。
              </p>
            </div>
            <button @click="rule.conditions.push({ op: 'empty', field: 'plot', value: '' })">
              添加 NFO 条件
            </button>
          </template>
          <template v-else>
            <div class="row">
              <label v-for="asset in assetOptions(set)" :key="asset"
                ><input
                  type="checkbox"
                  :checked="rule.images.some((i) => i.type === asset)"
                  @change="toggleImage(rule, asset, ($event.target as HTMLInputElement).checked)"
                />{{ labels[asset] }}</label
              >
            </div>
            <div v-for="check in rule.images" :key="check.type" class="row condition">
              <strong>{{ labels[check.type] }}</strong><label
                ><input type="checkbox" v-model="check.missing" />缺失</label
              ><label><input type="checkbox" v-model="check.damaged" />损坏</label
              ><label>最小宽<input type="number" min="0" v-model.number="check.min_width" /></label
              ><label
                >最小高<input type="number" min="0" v-model.number="check.min_height"
              /></label>
            </div>
          </template>
          <div v-if="['selected_images', 'both'].includes(rule.action)" class="row">
            <span>另行指定更新：</span
            ><label v-for="asset in assetOptions(set)" :key="asset"
              ><input type="checkbox" :value="asset" v-model="rule.selected_images" />{{
                labels[asset]
              }}</label
            >
          </div>
        </article>
        <div class="row">
          <button @click="addRule(set, 'nfo')">添加 NFO 规则</button
          ><button @click="addRule(set, 'image')">添加图片规则</button>
        </div>
      </fieldset>
      <button @click="addSet" :disabled="live.busy">添加规则集</button>
    </section>
    <section v-if="tab === 'results'">
      <p v-if="recordLoading" role="status">正在加载运行记录…</p>
      <div v-if="!report && !recordLoading" class="empty">
        选择试运行，或在运行记录中打开一次巡检。
      </div>
      <template v-if="report">
        <div class="card">
          <strong
            >{{ report.dry_run ? '试运行' : '正式运行' }} · {{ stamp(report.created) }} ·
            {{ labels[report.status] || report.status }}</strong
          >
          <p>{{ report.summary }}</p>
          <p v-if="report.exit_reason">
            {{ exitLabels[report.exit_reason] || report.exit_reason
            }}<span v-if="report.batches"> · 本次执行 {{ report.batches }} 批</span>
          </p>
          <p v-if="report.emby_enabled === false" class="hint">规则已关闭 Emby 联动。</p>
          <p v-for="(e, i) in report.errors" :key="i" class="error">{{ e }}</p>
          <p v-if="report.error_count > report.errors.length">
            共 {{ report.error_count }} 条运行错误，显示前 {{ report.errors.length }} 条。
          </p>
        </div>
        <div class="toolbar">
          <input v-model="query" placeholder="搜索路径" aria-label="搜索路径" /><select
            v-model="statusFilter"
            aria-label="状态筛选"
          >
            <option value="">全部状态</option>
            <option v-for="s in report.statuses" :key="s" :value="s">
              {{ labels[s] || s }}
            </option></select
          ><select v-model="kindFilter" aria-label="层级筛选">
            <option value="">全部层级</option>
            <option v-for="k in ['movie', 'tv', 'season', 'episode']" :key="k" :value="k">
              {{ labels[k] }}
            </option></select
          ><select v-model="ruleFilter" aria-label="规则集筛选">
            <option value="">全部规则集</option>
            <option v-for="s in cfg?.rule_sets" :key="s.id" :value="s.id">{{ s.name }}</option>
          </select>
        </div>
        <fieldset class="toolbar result-actions" :disabled="recordLoading">
          <button
            :disabled="live.busy || report.dry_run || !cfg?.enabled"
            @click="guard(() => start('resume'))"
          >
            继续剩余任务（一批）</button
          ><button @click="selected = [...new Set([...selected, ...visible.map((i) => i.id)])]">
            选择本页</button
          ><button @click="guard(selectAllResults)">选择全部筛选结果</button
          ><button @click="selected = []">清空选择</button
          ><button
            :disabled="live.busy || !selected.length || !cfg?.enabled"
            @click="guard(() => start('repair', { ids: selected }))"
          >
            修复选中</button
          ><button
            :disabled="live.busy || !selected.length || !cfg?.enabled"
            @click="guard(() => start('repair', { ids: selected, retry: true }))"
          >
            清除冷却并重试</button
          ><button
            :disabled="live.busy || !selected.length"
            @click="guard(() => start('ignore', { ids: selected }))"
          >
            忽略选中</button
          ><button
            :disabled="live.busy || !selected.length"
            @click="guard(() => start('ignore', { ids: selected, undo: true }))"
          >
            取消忽略</button
          ><button
            :disabled="live.busy || report.dry_run || !cfg?.enabled"
            @click="guard(() => start('refresh'))"
          >
            仅重试 Emby 同步</button
          ><button
            :disabled="live.busy"
            @click="guard(() => start('inspect', { set_ids: report?.set_ids }))"
          >
            重新巡检</button
          ><span>已选 {{ selected.length }} 项</span>
        </fieldset>
        <fieldset
          class="toolbar result-actions"
          :disabled="live.busy || recordLoading || !selected.length || !cfg?.enabled"
        >
          <label
            >本次选中条目的翻译处理<select v-model="translationMode">
              <option value="normal">补齐未完成字段</option>
              <option value="force">重新翻译插件生成的字段（绕过译文缓存）</option>
              <option value="overwrite">允许替换来源不明或已手工修改的文字</option>
            </select></label
          >
          <button @click="guard(applyTranslation)">应用到选中条目</button>
          <p v-if="translationMode === 'overwrite'" class="hint">
            本次将按命中的翻译规则替换选中字段，备份遵循当前 NFO 备份设置。
          </p>
        </fieldset>
        <div class="table-wrap" :aria-busy="recordLoading">
          <table>
            <thead>
              <tr>
                <th>选择</th>
                <th>媒体／状态</th>
                <th>命中与动作</th>
                <th>修复与同步结果</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in visible" :key="item.id">
                <td>
                  <input
                    type="checkbox"
                    :value="item.id"
                    v-model="selected"
                    :disabled="recordLoading"
                    :aria-label="'选择 ' + item.target.path"
                  />
                </td>
                <td class="path">
                  <span class="badge">{{ labels[item.target.kind] }}</span> {{ item.target.path }}
                  <p>{{ labels[item.status] || item.status }}</p>
                </td>
                <td>
                  <p class="hint">巡检时命中</p>
                  <p v-for="hit in item.hits" :key="hit.set + hit.rule">
                    <strong>{{ hit.name }}</strong><br />{{ hit.reasons.join('；') }}
                  </p>
                  <p v-if="item.conflicts.length" class="error">{{ item.conflicts.join('；') }}</p>
                  <p v-if="item.translation_conflict" class="error">
                    {{ item.translation_conflict }}
                  </p>
                  <p>动作：{{ item.actions.map((a) => labels[a]).join('、') || '仅报告' }}</p>
                  <details v-if="item.remaining_hits?.length">
                    <summary>复查后仍命中 {{ item.remaining_hits.length }} 条规则</summary>
                    <p v-for="hit in item.remaining_hits" :key="hit.set + hit.rule">
                      {{ hit.name }}：{{ hit.reasons.join('；') }}
                    </p>
                  </details>
                  <p>
                    剩余资产：{{
                      item.remaining_assets?.map((a) => labels[a] || a).join('、') || '无'
                    }}
                  </p>
                </td>
                <td>
                  <div v-for="(res, asset) in item.results" :key="asset">
                    <p>
                      {{ labels[asset] }}：{{ labels[res.status] || res.status }} {{ res.message }}
                    </p>
                    <p v-if="res.error_code" class="hint">
                      类型：{{ labels[res.error_code] || res.error_code }}
                    </p>
                    <p v-if="res.translation_pending_fields?.length">
                      待处理字段：{{
                        res.translation_pending_fields
                          .map((f) => translation.fields[f] || f)
                          .join('、')
                      }}
                    </p>
                    <p v-if="res.attempts">连续未改善 {{ res.attempts }} 次</p>
                    <p v-if="res.next_retry_at" class="hint">
                      下次可重试 {{ stamp(res.next_retry_at) }}
                    </p>
                    <details v-if="res.details && Object.keys(res.details).length">
                      <summary>处理详情／字段结果</summary>
                      <pre>{{ details(res.details) }}</pre>
                    </details>
                  </div>
                  <p v-if="item.emby_mode === 'off' && !item.sync.length" class="hint">
                    Emby 联动已关闭
                  </p>
                  <p v-for="(sync, si) in item.sync" :key="si">
                    {{ sync.server }}：{{ labels[sync.status] || sync.status }} {{ sync.message }}
                  </p>
                </td>
              </tr>
            </tbody>
          </table>
          <div class="toolbar">
            <button
              :disabled="recordLoading || page <= 1"
              @click="guard(() => changePage(page - 1))"
            >
              上一页</button
            ><span>第 {{ page }} 页 · {{ total }} 项</span
            ><button
              :disabled="recordLoading || page * 100 >= total"
              @click="guard(() => changePage(page + 1))"
            >
              下一页
            </button>
          </div>
          <p v-if="!total && !recordLoading" class="empty">没有匹配的结果。</p>
        </div>
      </template>
    </section>
    <section v-if="tab === 'pending'">
      <div class="toolbar">
        <button
          :disabled="live.busy || !cfg?.enabled || !pendingCount"
          @click="guard(() => start('refresh_pending', { run_id: null }))"
        >
          重试待同步队列</button
        ><button
          :disabled="pendingLoading"
          @click="guard(() => loadPending(pendingPage?.page || 1))"
        >
          刷新列表</button
        ><span>共 {{ pendingCount }} 项</span>
      </div>
      <p class="hint">
        待同步任务独立保存，删除运行记录后仍可重试。重试会生成新的运行记录；同一已提交版本先复查
        Emby，不重复补刮本地文件。
      </p>
      <p v-if="pendingLoading" role="status">正在读取待同步任务…</p>
      <div v-for="entry in pendingPage?.items" :key="entry.key" class="card path">
        <strong>{{ entry.target?.path || '旧记录目标待确认' }}</strong>
        <p>
          {{ entry.server || '尚未配置 Emby 服务' }} · {{ labels[entry.status] || entry.status }}
        </p>
        <p>{{ entry.message }}</p>
        <small v-if="entry.updated">{{ stamp(entry.updated) }}</small>
      </div>
      <p v-if="pendingPage && !pendingPage.total && !pendingLoading" class="empty">
        没有待同步任务。
      </p>
      <div v-if="pendingPage?.total" class="toolbar">
        <button
          :disabled="pendingLoading || pendingPage.page <= 1"
          @click="guard(() => loadPending((pendingPage?.page || 1) - 1))"
        >
          上一页</button
        ><span>第 {{ pendingPage.page }} 页 · {{ pendingPage.total }} 项</span
        ><button
          :disabled="
            pendingLoading || pendingPage.page * pendingPage.page_size >= pendingPage.total
          "
          @click="guard(() => loadPending((pendingPage?.page || 1) + 1))"
        >
          下一页
        </button>
      </div>
    </section>
    <section v-if="tab === 'history'">
      <div class="toolbar">
        <button
          :disabled="live.busy || deleting || !historyRuns.length"
          @click="historySelected = historyRuns.map((r) => r.id)"
        >
          选择本页记录</button
        ><button :disabled="!historySelected.length || deleting" @click="historySelected = []">
          清空选择</button
        ><button
          :disabled="live.busy || deleting || !historySelected.length"
          @click="deleteIds = [...historySelected]"
        >
          删除选中记录（{{ historySelected.length }}）
        </button>
      </div>
      <div v-if="deleteIds.length" role="alertdialog" aria-label="删除运行记录" class="card">
        <p>
          确定删除这
          {{ deleteIds.length }}
          条运行记录及巡检结果？删除后无法在运行记录中查看；媒体文件、备份、规则和待同步任务保留。
        </p>
        <div class="row">
          <button :disabled="live.busy || deleting" @click="guard(deleteRuns)">确认删除</button
          ><button :disabled="deleting" @click="deleteIds = []">取消删除</button>
        </div>
      </div>
      <p v-if="live.busy" class="hint">任务运行期间暂不可删除记录。</p>
      <div v-for="run in historyRuns" :key="run.id" class="card row">
        <input
          type="checkbox"
          :value="run.id"
          v-model="historySelected"
          :disabled="live.busy || deleting"
          :aria-label="'选择运行记录 ' + stamp(run.created)"
        />
        <div class="grow">
          <strong>{{ stamp(run.created) }} · {{ labels[run.status] || run.status }}</strong>
          <p>{{ run.summary }}</p>
        </div>
        <button @click="guard(() => open(run.id))">查看结果</button
        ><button :disabled="live.busy || deleting" @click="deleteIds = [run.id]">删除记录</button>
      </div>
      <div v-if="runs.length" class="toolbar">
        <button :disabled="historyPage <= 1" @click="historyPage--">上一页记录</button
        ><span>第 {{ historyPage }} 页 · {{ runs.length }} 条记录</span
        ><button :disabled="historyPage * historySize >= runs.length" @click="historyPage++">
          下一页记录
        </button>
      </div>
      <p v-else class="empty">暂无运行记录。</p>
    </section>
    <section v-if="cfg && tab === 'settings'">
      <fieldset :disabled="live.busy" class="card">
        <legend>执行与记录</legend>
        <div class="grid settings-grid">
          <label
            >每轮修复媒体上限<input type="number" min="1" v-model.number="cfg.batch_limit" /></label
          ><label><input type="checkbox" v-model="cfg.auto_continue" />达到每批上限后自动继续</label
          ><label
            >每次运行最多批数（含首批）<input
              type="number"
              min="1"
              max="100"
              v-model.number="cfg.max_batches_per_run"
              :disabled="!cfg.auto_continue" /></label
          ><label>任务间隔（秒）<input type="number" min="0" v-model.number="cfg.interval" /></label
          ><label
            >文件稳定时间（秒）<input
              type="number"
              min="0"
              v-model.number="cfg.stable_seconds" /></label
          ><label
            >未改善冷却（天）<input
              type="number"
              min="0"
              v-model.number="cfg.cooldown_days" /></label
          ><label
            >连续未改善上限<input
              type="number"
              min="1"
              v-model.number="cfg.max_no_improvement" /></label
          ><label
            >运行记录保留（天）<input type="number" min="1" v-model.number="cfg.history_days"
          /></label>
        </div>
        <p class="hint">
          默认每次执行一批，达到上限后手动继续。开启自动继续后最多执行设定批数；“继续剩余任务”始终只执行一批。冷却、忽略、等待稳定的对象不占修复名额。定时由
          MoviePilot 工作流配置。
        </p>
      </fieldset>
      <fieldset :disabled="live.busy" class="card">
        <legend>备份</legend>
        <div class="row">
          <label><input type="checkbox" v-model="cfg.backup.nfo" />覆盖 NFO 前备份</label
          ><label><input type="checkbox" v-model="cfg.backup.images" />覆盖图片前备份</label
          ><label><input type="checkbox" v-model="cfg.backup.cleanup" />自动清理备份</label>
        </div>
        <label
          >备份目录<input v-model="cfg.backup.directory" placeholder="留空使用插件数据目录"
        /></label>
        <div class="grid">
          <label
            >保留天数（0 不限）<input
              type="number"
              min="0"
              v-model.number="cfg.backup.days" /></label
          ><label
            >每文件版本数（0 不限）<input
              type="number"
              min="0"
              v-model.number="cfg.backup.versions"
          /></label>
        </div>
        <p class="hint">启用备份但备份失败时，该文件不覆盖。NFO 更新会整份重建。</p>
      </fieldset>
      <fieldset :disabled="live.busy" class="card">
        <legend>Emby 联动</legend>
        <p class="hint">只发送刷新请求，不上传图片、不替换全部图片。还需在规则集中开启联动。</p>
        <div class="row">
          <label v-for="name in servers" :key="name"
            ><input
              type="checkbox"
              :checked="cfg.emby_servers.some((s) => s.name === name)"
              @change="toggleServer(name, ($event.target as HTMLInputElement).checked)"
            />{{ name }}</label
          >
        </div>
        <p v-if="!servers.length">未发现已启用的 Emby 服务，请先在 MoviePilot 配置。</p>
        <div v-for="server in cfg.emby_servers" :key="server.name" class="rule">
          <h3>{{ server.name }}</h3>
          <label
            >Emby 媒体库 ID（每行一个，留空为该服务全部媒体库）<textarea
              :value="server.libraries.join('\n')"
              @input="server.libraries = lines(($event.target as HTMLTextAreaElement).value)"
            />
          </label>
          <div class="row" v-for="(mapping, mi) in server.mappings" :key="mi">
            <input
              v-model="mapping.local"
              aria-label="MP 本地路径"
              placeholder="MP：/media/115"
            /><span>→</span
            ><input
              v-model="mapping.remote"
              aria-label="Emby 路径"
              placeholder="Emby：/media/115"
            /><button @click="server.mappings.splice(mi, 1)">移除</button>
          </div>
          <button @click="server.mappings.push({ local: '', remote: '' })">添加路径映射</button>
        </div>
        <div class="grid">
          <label>复查间隔（秒）<input type="number" min="1" v-model.number="cfg.emby_poll" /></label
          ><label
            >每条目最长等待（秒，0 仅提交）<input
              type="number"
              min="0"
              max="3600"
              v-model.number="cfg.emby_timeout"
          /></label>
        </div>
      </fieldset>
      <fieldset :disabled="live.busy" class="card">
        <legend>运行通知</legend>
        <label
          >手动运行通知<select v-model="cfg.notify">
            <option value="off">关闭</option>
            <option value="always">每轮汇总</option>
            <option value="issues">仅有问题时通知</option>
          </select></label
        >
        <div class="row">
          <label v-for="channel in channels" :key="channel.value"
            ><input type="checkbox" :value="channel.value" v-model="cfg.notify_channels" />{{
              channel.title
            }}</label
          >
        </div>
        <p class="hint">
          渠道留空沿用 MP 默认通知路由。工作流运行使用末尾的官方通知节点，避免重复发送。
        </p>
      </fieldset>
      <details class="card">
        <summary>备份恢复（{{ backups.length }}）</summary>
        <div v-for="b in backups" :key="b.id" class="row rule">
          <div class="grow path">
            {{ b.path }}
            <p>{{ stamp(b.created) }}</p>
          </div>
          <button
            :disabled="live.busy || !cfg.enabled || !b.committed"
            @click="guard(() => start('restore', { backup_id: b.id, sync: false }))"
          >
            恢复文件</button
          ><button
            :disabled="live.busy || !cfg.enabled || !b.committed"
            @click="guard(() => start('restore', { backup_id: b.id, sync: true }))"
          >
            恢复并刷新 Emby
          </button>
        </div>
      </details>
    </section>
  </div>
</template>

<style scoped>
.nfo-app * {
  box-sizing: border-box;
}
.nfo-app {
  font-family: inherit;
  max-width: 1250px;
  margin: auto;
  padding: 20px;
  color: rgb(var(--v-theme-on-surface, 40, 44, 52));
  font-size: 14px;
}
header,
.row,
.toolbar,
nav {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
header {
  justify-content: space-between;
  margin-bottom: 18px;
}
h2 {
  font-size: 24px;
  margin: 0;
}
h3 {
  font-size: 16px;
}
p {
  margin: 8px 0;
  line-height: 1.6;
}
header p,
.hint {
  opacity: 0.72;
}
.card {
  padding: 20px;
  margin: 16px 0;
  border: 1px solid #8885;
  border-radius: 12px;
  min-width: 0;
}
.rule {
  padding: 16px;
  margin: 14px 0;
  border: 1px solid #8884;
  border-radius: 8px;
  background: #88808;
}
legend {
  padding: 0 8px;
  font-weight: 600;
}
.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin: 14px 0;
}
.settings-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}
label {
  display: flex;
  gap: 8px;
  align-items: center;
}
.grid > label,
.card > label,
.rule > label {
  display: flex;
  flex-direction: column;
  align-items: stretch;
}
input,
select,
textarea,
button {
  font: inherit;
  color: inherit;
}
input:not([type='checkbox']),
select,
textarea {
  border: 1px solid #8887;
  border-radius: 6px;
  padding: 9px 10px;
  background: rgb(var(--v-theme-surface, 255, 255, 255));
  min-width: 0;
}
textarea {
  min-height: 80px;
  resize: vertical;
  width: 100%;
}
input[type='number'] {
  width: 110px;
}
.grid input {
  width: 100%;
}
input[type='checkbox'] {
  accent-color: #5269cd;
  width: 16px;
  height: 16px;
}
button {
  padding: 8px 13px;
  border: 1px solid #8886;
  border-radius: 6px;
  cursor: pointer;
  background: transparent;
}
button:hover {
  background: #5269cd18;
}
button:disabled {
  opacity: 0.4;
  cursor: default;
}
.primary,
.chosen {
  background: #5269cd !important;
  color: white;
}
.grow {
  flex: 1;
  min-width: 160px;
}
nav {
  border-bottom: 1px solid #8884;
  padding-bottom: 12px;
  margin-bottom: 16px;
}
.toolbar {
  margin: 16px 0;
}
.badge {
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 5px;
  background: #8882;
  white-space: nowrap;
}
.active {
  background: #5269cd22;
  color: #5269cd;
}
.alert {
  padding: 12px;
  border-radius: 8px;
  background: #5269cd15;
}
.error {
  color: #c74941;
}
.alert.error {
  background: #d6515115;
}
.condition {
  padding: 8px 0;
}
.result-actions {
  border: 0;
  padding: 0;
  min-width: 0;
}
.table-wrap {
  overflow-x: auto;
}
table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}
th,
td {
  padding: 12px;
  border-bottom: 1px solid #8884;
  vertical-align: top;
}
th {
  white-space: nowrap;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-width: 400px;
  font-size: 12px;
}
.path {
  overflow-wrap: anywhere;
  max-width: 440px;
}
.empty {
  text-align: center;
  padding: 40px;
  opacity: 0.7;
}
summary {
  cursor: pointer;
}
fieldset:disabled {
  opacity: 0.7;
}
@media (max-width: 760px) {
  .nfo-app {
    padding: 12px;
  }
  .grid,
  .settings-grid {
    grid-template-columns: 1fr;
  }
  .card {
    padding: 14px;
  }
  .row {
    gap: 8px;
  }
  .condition > * {
    max-width: 100%;
  }
}
</style>
