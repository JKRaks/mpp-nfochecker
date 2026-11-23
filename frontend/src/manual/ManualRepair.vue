<script setup lang="ts">
import {computed, onBeforeUnmount, onMounted, ref, shallowRef, watch} from 'vue'
import type {HostProps} from '../types'
import {fieldLabel} from '../detail/labels'
import type {ManualCandidate, ManualCandidateList, ManualChange, ManualDetail, ManualPreview, ManualResult} from './types'

const props = defineProps<{
  api: HostProps['api']
  endpoint: (name: string) => string
  runId: string
  itemId: string
  asset: string
  assetLabel: string
  labels: Record<string, string>
  lastMessage: string
}>()
const emit = defineEmits<{
  (event: 'saved' | 'close'): void
  (event: 'dirty' | 'busy', value: boolean): void
}>()

const params = {run_id: props.runId, item_id: props.itemId, asset: props.asset}
const isNfo = props.asset === 'nfo'
const tmdbField = "uniqueid[@type='tmdb']"
const detail = shallowRef<ManualDetail>()
const field = ref('')
const edits = ref<Record<string,string>>({})
const replacement = ref('')
const fileName = ref('')
const candidates = shallowRef<ManualCandidate[]>([])
const candidateNote = ref('')
const selectedCandidate = shallowRef<ManualCandidate>()
const candidateFills = new Map<string, {previous: string; value: string}>()
const sourcesPanel = ref<HTMLDetailsElement>()
const preview = shallowRef<ManualPreview>()
const reviewedInput = shallowRef<ManualChange>()
const result = shallowRef<ManualResult>()
const error = ref('')
const working = ref('')
const request = new AbortController()
const patching = computed(() => isNfo && !!detail.value?.nfo_valid)
const editableFields = computed(() => Object.keys(detail.value?.fields || {}).filter(key => key !== tmdbField && !detail.value?.blocked_fields.includes(key)))
const canAddTmdb = computed(() => patching.value && detail.value?.fields[tmdbField] === '' && !detail.value.blocked_fields.includes(tmdbField))
const tmdbDraft = computed(() => edits.value[tmdbField] || '')
const hasTmdbDraft = computed(() => canAddTmdb.value && !!tmdbDraft.value)
const validTmdb = computed(() => /^[1-9][0-9]{0,31}$/.test(tmdbDraft.value))
const invalidTmdb = computed(() => hasTmdbDraft.value && !validTmdb.value)
const changes = computed(() => Object.fromEntries(Object.entries(edits.value).filter(([key, value]) => value !== detail.value?.fields[key])))
const localFields = computed(() => Object.keys(reviewedInput.value?.fields || {}).filter(key => ['originaltitle', 'sorttitle', 'outline', tmdbField].includes(key)))
const hasDraft = computed(() => patching.value ? Object.keys(changes.value).length > 0 : !!replacement.value)
const minWidth = computed(() => Math.max(0, ...(detail.value?.requirements || []).map(r => r.min_width || 0)))
const minHeight = computed(() => Math.max(0, ...(detail.value?.requirements || []).map(r => r.min_height || 0)))
const candidateValue = computed(() => {
  if (!selectedCandidate.value?.nfo || !field.value) return ''
  const doc = new DOMParser().parseFromString(selectedCandidate.value.nfo, 'application/xml')
  const nodes = Array.from(doc.documentElement.children).filter(child => child.tagName === field.value)
  return nodes.length === 1 && !nodes[0].childElementCount ? nodes[0].textContent || '' : ''
})
const dirty = computed(() => hasDraft.value && !result.value)
watch(dirty, value => emit('dirty', value), {flush: 'sync'})
watch(tmdbDraft, () => {
  const restored: string[] = []
  for (const [key, fill] of candidateFills) {
    if (edits.value[key] === fill.value) {
      edits.value[key] = fill.previous
      restored.push(fieldLabel(key))
    }
  }
  candidateFills.clear()
  clearCandidates()
  if (restored.length) candidateNote.value = '编号已更改，' + restored.join('、') + '已恢复为选用候选前的内容。'
  backToEdit()
}, {flush: 'sync'})
onBeforeUnmount(() => request.abort())
onMounted(loadDetail)

function describeError(reason: unknown) {
  const err = reason as {response?: {data?: {detail?: unknown}}; message?: string}
  const info = err?.response?.data?.detail
  if (typeof info === 'string') return info
  return err?.message || '请求失败，请稍后重试'
}
async function run(task: string, work: () => Promise<void>) {
  if (working.value) return
  working.value = task
  error.value = ''
  try { await work() }
  catch (reason) { if (!request.signal.aborted) error.value = describeError(reason) }
  finally { working.value = '' }
}
async function loadDetail() {
  await run('loading', async () => {
    const data = await props.api.get<ManualDetail>(props.endpoint('manual_detail'), {params, signal: request.signal})
    detail.value = data
    edits.value = {...data.fields}
    const matched = editableFields.value.filter(key => data.reasons.some(reason => reason.startsWith(fieldLabel(key) + '：')))
    const empty = (key: string) => !data.fields[key].trim()
    field.value = matched.find(empty) || matched[0] || editableFields.value.find(empty) || editableFields.value[0] || ''
  })
}
function clearCandidates() {
  candidates.value = []
  selectedCandidate.value = undefined
  candidateNote.value = ''
}
async function loadCandidates(byTmdb = false) {
  if (!detail.value || byTmdb !== hasTmdbDraft.value || invalidTmdb.value) return
  const version = detail.value.version
  const id = tmdbDraft.value
  const source = byTmdb ? 'TMDB 编号 ' + id : '原刮削来源'
  await run(byTmdb ? 'tmdb-candidates' : 'candidates', async () => {
    clearCandidates()
    if (sourcesPanel.value) sourcesPanel.value.open = true
    candidateNote.value = '正在读取' + source + '的候选…'
    const options = {signal: request.signal, timeout: 120_000}
    try {
      const list = byTmdb
        ? await props.api.post<ManualCandidateList>(props.endpoint('manual_candidates_by_tmdb'), {...params, version, tmdb_id: id}, options)
        : await props.api.get<ManualCandidateList>(props.endpoint('manual_candidates'), {...options, params})
      if (tmdbDraft.value !== id || request.signal.aborted) return
      candidates.value = list.items
      const usable = list.items.filter(candidate => !candidate.error && (candidate.nfo || candidate.image))
      candidateNote.value = source + (usable.length ? '返回 ' + usable.length + ' 个可用候选。' : '没有可用候选。') + (list.message || '')
      if (patching.value && usable.length === 1) useCandidate(usable[0])
    } catch (reason) {
      if (tmdbDraft.value === id && !request.signal.aborted) candidateNote.value = source + '读取失败。' + describeError(reason)
    }
  })
}
function useCandidate(candidate: ManualCandidate) {
  if (candidate.error) return
  if (patching.value) {
    selectedCandidate.value = candidate
  } else {
    replacement.value = (isNfo ? candidate.nfo : candidate.image) || ''
    fileName.value = candidate.label
  }
}
function fillFromCandidate() {
  const key = field.value
  const value = candidateValue.value
  if (!editableFields.value.includes(key) || !value || edits.value[key] === value) return
  const previous = candidateFills.get(key)?.previous ?? edits.value[key]
  candidateFills.set(key, {previous, value})
  edits.value[key] = value
}
function readDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(new Error('读取图片失败，请重新选择。'))
    reader.readAsDataURL(file)
  })
}
async function pickFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  await run('file', async () => {
    const limit = isNfo ? 2 : 20
    if (file.size > limit * 1024 * 1024) throw new Error('请选择小于或等于 ' + limit + ' MiB 的文件。')
    if (isNfo) {
      const bytes = await file.arrayBuffer()
      try { replacement.value = new TextDecoder('utf-8', {fatal:true}).decode(bytes) }
      catch { throw new Error('请将 NFO 文件另存为 UTF-8 后再导入。') }
    } else {
      replacement.value = await readDataUrl(file)
    }
    fileName.value = file.name
  })
}
async function makePreview() {
  if (!detail.value || !hasDraft.value || invalidTmdb.value) return
  const version = detail.value.version
  const input: ManualChange = patching.value ? {fields: {...changes.value}} : isNfo ? {nfo: replacement.value} : {image: replacement.value}
  await run('preview', async () => {
    const data = await props.api.post<ManualPreview>(props.endpoint('manual_preview'), {...params, version, ...input}, {
      signal: request.signal, timeout: 120_000,
    })
    reviewedInput.value = input
    preview.value = data
  })
}
async function save() {
  if (!detail.value || !preview.value?.changed || !reviewedInput.value || result.value || working.value) return
  const payload = {...params, version: detail.value.version, ...reviewedInput.value}
  await run('saving', async () => {
    emit('busy', true)
    try {
      result.value = await props.api.post<ManualResult>(props.endpoint('manual_save'), payload, {timeout: 120_000})
      emit('saved')
    } finally { emit('busy', false) }
  })
}
function backToEdit() {
  preview.value = undefined
  reviewedInput.value = undefined
  error.value = ''
}
</script>

<template>
  <div class="manual-editor">
    <p v-if="working === 'loading'" role="status">正在读取文件…</p>
    <p v-if="error" role="alert" class="problem">{{error}}</p>
    <button v-if="!detail && error" type="button" @click="loadDetail">重新读取</button>

    <template v-if="result">
      <h3>{{result.message || (result.changed ? '文件已保存' : '文件没有变化')}}</h3>
      <ul v-if="result.remaining_reasons?.length" aria-label="仍需处理">
        <li v-for="reason in result.remaining_reasons" :key="reason">{{reason}}</li>
      </ul>
      <p v-if="localFields.length">{{localFields.map(fieldLabel).join('、')}}仅写入本地 NFO。</p>
      <template v-if="result.sync.length">
        <h4>保存时的同步状态</h4>
        <p v-for="sync in result.sync" :key="sync.server">
          Emby {{sync.server}} · {{labels[sync.status] || sync.status}} {{sync.message}}
        </p>
        <p>最终状态请在巡检结果中查看。</p>
      </template>
      <button type="button" @click="emit('close')">返回巡检结果</button>
    </template>
    <template v-else-if="detail">
      <p class="file-path">{{detail.path}}</p>
      <p v-if="lastMessage"><strong>上次处理</strong>　{{lastMessage}}</p>
      <div v-if="detail.reasons.length" class="reasons">
        <strong>当前命中的规则</strong>
        <ul><li v-for="reason in detail.reasons" :key="reason">{{reason}}</li></ul>
      </div>
      <p v-if="!isNfo && (minWidth || minHeight)">
        规则要求<span v-if="minWidth">宽度至少 {{minWidth}} 像素</span><span v-if="minWidth && minHeight">，</span><span v-if="minHeight">高度至少 {{minHeight}} 像素</span>
      </p>

      <div v-if="!isNfo" class="comparison">
        <figure>
          <figcaption>当前{{assetLabel}} <span v-if="detail.image && 'width' in detail.image">{{detail.image.width}} × {{detail.image.height}}</span></figcaption>
          <img v-if="detail.image_url" :src="detail.image_url" alt="当前图片">
          <p v-else>{{detail.exists ? '当前图片无法预览' : '还没有这张图'}}</p>
        </figure>
        <figure v-if="replacement">
          <figcaption>待替换图片 <span v-if="preview?.image">{{preview.image.width}} × {{preview.image.height}}</span></figcaption>
          <img :src="replacement" alt="待替换图片"><small>{{fileName}}</small>
        </figure>
      </div>

      <template v-if="!preview">
        <fieldset :disabled="!!working">
          <template v-if="patching">
            <div v-if="canAddTmdb" class="tmdb-entry">
              <label>TMDB 编号
                <input v-model.trim="edits[tmdbField]" type="text" inputmode="numeric" autocomplete="off"
                  spellcheck="false" :aria-invalid="invalidTmdb" aria-describedby="manual-tmdb-help">
              </label>
              <p id="manual-tmdb-help" :class="{problem: invalidTmdb}">
                <template v-if="invalidTmdb">请输入 1 至 32 位正整数，首位不能是 0。</template>
                <template v-else-if="detail.kind === 'episode'">填写这一集在 TMDB 的单集编号。整剧和季有各自的编号。</template>
                <template v-else-if="detail.kind === 'season'">填写这一季在 TMDB 的季编号。整剧和单集有各自的编号。</template>
                <template v-else>填写当前{{detail.kind === 'movie' ? '电影' : '剧集'}}在 TMDB 的编号。</template>
              </p>
              <button type="button" :disabled="!validTmdb || !!working" @click="loadCandidates(true)">{{working === 'tmdb-candidates' ? '正在按编号读取…' : '按此编号读取候选'}}</button>
              <small>读取候选后，可以挑选要填入的文字。点击「保存 NFO」才会写入文件。</small>
            </div>
            <label v-if="editableFields.length">编辑字段
              <select v-model="field">
                <option v-for="key in editableFields" :key="key" :value="key">{{fieldLabel(key)}}</option>
              </select>
            </label>
            <div v-if="field" class="comparison">
              <div><strong>当前内容</strong><p class="text">{{detail.fields[field] || '（空）'}}</p></div>
              <label>改成<textarea v-model="edits[field]" rows="5" @input="candidateFills.delete(field)"></textarea></label>
            </div>
            <p v-if="detail.blocked_fields?.length">仅供查看的字段：{{detail.blocked_fields.map(fieldLabel).join('、')}}</p>
            <p v-if="Object.keys(changes).length">已编辑 {{Object.keys(changes).map(fieldLabel).join('、')}}</p>
          </template>
          <template v-else>
            <label>{{isNfo ? '导入完整 NFO（UTF-8）' : '选择替换图片'}}
              <input type="file" :accept="isNfo ? '.nfo,.xml,text/xml,application/xml' : 'image/*'" @change="pickFile">
            </label>
            <template v-if="isNfo">
              <p>{{detail.exists ? '现有 NFO 无法按字段编辑，保存会替换整份文件。' : '本次会创建新的 NFO 文件。'}}</p>
              <details v-if="detail.nfo"><summary>查看现有文件</summary><pre>{{detail.nfo}}</pre></details>
              <label>待写入的 XML<textarea v-model="replacement" rows="7" spellcheck="false"></textarea></label>
            </template>
          </template>
        </fieldset>

        <details ref="sourcesPanel" class="sources">
          <summary>从刮削来源选择</summary>
          <button v-if="!hasTmdbDraft" type="button" :disabled="!!working" @click="loadCandidates()">{{working === 'candidates' ? '正在读取候选…' : '从原刮削来源读取候选'}}</button>
          <p v-if="candidateNote" role="status">{{candidateNote}}</p>
          <div v-for="(candidate,index) in candidates" :key="index" class="candidate">
            <img v-if="candidate.image" :src="candidate.image" alt="" loading="lazy">
            <div>{{candidate.label}}<p v-if="candidate.error">{{candidate.error}}</p></div>
            <button v-if="!candidate.error && (candidate.nfo || candidate.image)" type="button" :disabled="!!working || selectedCandidate === candidate" @click="useCandidate(candidate)">{{selectedCandidate === candidate ? '正在查看' : patching ? '查看字段' : '选用'}}</button>
          </div>
          <div v-if="patching && selectedCandidate && field">
            <p>{{selectedCandidate.label}}</p>
            <strong>{{fieldLabel(field)}}</strong><p class="text">{{candidateValue || '候选没有可用的单值内容。'}}</p>
            <button v-if="candidateValue" type="button" :disabled="!!working || candidateValue === edits[field]" @click="fillFromCandidate">{{candidateValue === edits[field] ? '已与草稿一致' : '填入此字段'}}</button>
          </div>
        </details>
        <footer><button type="button" class="commit" :disabled="!!working || !hasDraft || invalidTmdb" @click="makePreview">{{working === 'preview' ? '正在检查…' : '预览修改'}}</button></footer>
      </template>

      <template v-else>
        <h3>保存前确认</h3>
        <p v-if="!preview.changed">文件内容相同。</p>
        <div v-for="(diff,key) in preview.fields" :key="key" class="field-diff">
          <h4>{{fieldLabel(String(key))}}</h4>
          <div class="comparison"><div><strong>原值</strong><p class="text">{{diff.before || '（空）'}}</p></div><div><strong>新值</strong><p class="text">{{diff.after || '（空）'}}</p></div></div>
        </div>
        <template v-if="isNfo && !patching">
          <p>{{detail.exists ? '保存将覆盖整个 NFO 文件。' : '保存将创建整个 NFO 文件。'}}</p>
          <details><summary>查看要写入的 XML</summary><pre>{{replacement}}</pre></details>
        </template>
        <p v-if="localFields.length">{{localFields.map(fieldLabel).join('、')}}仅写入本地 NFO。</p>
        <div v-if="preview.remaining_reasons?.length">
          <strong>保存后仍需处理</strong><ul><li v-for="reason in preview.remaining_reasons" :key="reason">{{reason}}</li></ul>
        </div>
        <footer>
          <button type="button" :disabled="!!working" @click="backToEdit">返回编辑</button>
          <button type="button" class="commit" :disabled="!!working || !preview.changed" @click="save">{{working === 'saving' ? '正在保存并复查…' : isNfo ? '保存 NFO' : '替换' + assetLabel}}</button>
        </footer>
      </template>
    </template>
  </div>
</template>

<style scoped>
.manual-editor {color:inherit;min-width:0;overflow-wrap:anywhere;padding:12px clamp(12px,3vw,22px)}
h3, h4 {margin:1rem 0 .5rem}
p, ul {margin:.4rem 0 .8rem}
ul {padding-inline-start:1.4rem}
.file-path, small {font-size:.875em;opacity:.8}
.problem {color:rgb(var(--v-theme-error,176,39,39))}
.reasons {padding:.7rem .8rem;background:rgba(var(--v-theme-on-surface,128,128,128),.06);border-radius:.5rem}
.comparison {display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,230px),1fr));gap:1rem;margin:.7rem 0}
.comparison > * {min-width:0}
.text, pre {white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%}
pre {max-height:14rem;overflow:auto}
figure {margin:0}
figcaption {margin-bottom:.4rem;font-weight:600}
figcaption span {font-size:.875em;font-weight:400}
figure img {display:block;width:100%;height:clamp(130px,25vh,240px);object-fit:contain;background:rgba(128,128,128,.08);border-radius:.4rem}
fieldset {min-inline-size:0;border:0;padding:0;margin:.8rem 0}
label {display:flex;flex-direction:column;align-items:stretch;gap:.4rem}
input, select, textarea, button {font:inherit;color:inherit}
input,select,textarea,button {min-width:0;max-width:100%;box-sizing:border-box;padding:.5rem .75rem;border:1px solid rgba(128,128,128,.48);border-radius:.4rem;background:rgb(var(--v-theme-surface,255,255,255))}
.tmdb-entry {margin-bottom:1rem}
.tmdb-entry input {width:min(100%,18rem)}
.tmdb-entry small {display:block;margin-top:.4rem}
select {align-self:flex-start}
textarea {width:100%;resize:vertical}
button, summary {cursor:pointer}
button:disabled {opacity:.5;cursor:default}
summary {padding:.5rem 0;font-weight:500}
.sources {margin-block:.7rem;border-block:1px solid rgba(128,128,128,.28);padding-block:.25rem}
.sources[open] {padding-bottom:.75rem}
.candidate {display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;margin-top:.6rem}
.candidate img {width:72px;height:66px;object-fit:contain}
.field-diff {padding-block:.25rem;border-bottom:1px solid rgba(128,128,128,.28)}
footer {display:flex;gap:.5rem;justify-content:flex-end;flex-wrap:wrap;position:sticky;bottom:0;padding:.7rem 0;background:rgb(var(--v-theme-surface,255,255,255));border-top:1px solid rgba(128,128,128,.25)}
.commit {background:rgb(var(--v-theme-primary,82,105,205));color:rgb(var(--v-theme-on-primary,255,255,255))}
</style>
