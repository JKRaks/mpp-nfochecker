<script setup lang="ts">
import {computed, ref} from 'vue'
import DetailValue from './DetailValue.vue'
import {catalog, displayValue, fieldLabel} from './labels'

const props = defineProps<{data: unknown; path: string}>()
const raw = ref(false)
const selected = ref('')
const knownFields = new Map(catalog.map(field => [field.value, field]))
function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

const dataRecord = computed(() => record(props.data) ? props.data : {})
const xml = computed(() => typeof dataRecord.value.nfo === 'string' ? dataRecord.value.nfo : null)
const status = computed(() => dataRecord.value.status)
const message = computed(() => dataRecord.value.message)
const original = computed(() => xml.value ?? JSON.stringify(props.data, null, 2))
type Section = {label: string; fields?: unknown; nodes?: Element[]; dimensions?: Record<string, unknown>}

function groupXml(source: string): {sections: Section[]; error?: string} {
  if (/<!DOCTYPE|<!ENTITY/i.test(source)) return {sections: [], error: '含实体声明，无法格式化。可以查看原始 XML。'}
  const doc = new DOMParser().parseFromString(source, 'application/xml')
  if (doc.getElementsByTagName('parsererror').length) return {sections: [], error: 'XML 格式有误，可以查看原始 XML。'}
  const groups = new Map<string, Element[]>()
  for (const node of Array.from(doc.documentElement.children)) {
    const label = knownFields.get(node.tagName)?.group || '其他字段'
    if (!groups.has(label)) groups.set(label, [])
    groups.get(label)!.push(node)
  }
  return {sections: Array.from(groups, ([label, nodes]) => ({label, nodes}))}
}

function nodeValue(node: Element, depth = 0): unknown {
  if (depth > 20) return node.textContent || ''
  const fields: Record<string, unknown> = Object.create(null)
  for (const attr of Array.from(node.attributes)) fields['@' + attr.name] = attr.value
  if (!node.children.length) {
    return node.attributes.length ? {...fields, text: node.textContent || ''} : node.textContent || ''
  }
  for (const child of Array.from(node.children)) {
    const value = nodeValue(child, depth + 1)
    const key = child.tagName
    if (!(key in fields)) fields[key] = value
    else if (Array.isArray(fields[key])) fields[key].push(value)
    else fields[key] = [fields[key], value]
  }
  return fields
}

const parsed = computed(() => xml.value === null ? {sections: []} : groupXml(xml.value))
const sections = computed<Section[]>(() => {
  const groups: Section[] = [...parsed.value.sections]
  const {nfo, status, message, backup, details, ...rest} = dataRecord.value
  if (record(details)) {
    const {actual_width, actual_height, min_width, min_height, ...other} = details
    if ([actual_width, actual_height, min_width, min_height].some(v => v !== undefined)) {
      groups.push({label: '图片尺寸', dimensions: {actual_width, actual_height, min_width, min_height}})
    }
    if (Object.keys(other).length) groups.push({label: '检查结果', fields: other})
  } else if (details != null) groups.push({label: '检查结果', fields: details})
  if (backup !== undefined) groups.push({label: '备份信息', fields: backup})
  if (Object.keys(rest).length) groups.push({label: '处理记录', fields: rest})
  if (!record(props.data) && props.data != null) groups.push({label: '内容', fields: props.data})
  return groups
})
const active = computed(() => sections.value.find(group => group.label === selected.value) ?? sections.value[0])
const rows = computed(() => active.value?.nodes?.map(node => ({
  label: fieldLabel(node.tagName), value: nodeValue(node),
})))
function dimension(value: unknown, minimum = false) {
  if (typeof value !== 'number') return '未知'
  return minimum && !value ? '不限' : value + ' px'
}
</script>

<template>
  <div class="readout">
    <div v-if="message || status" class="summary">
      <span v-if="status" class="status-label">{{displayValue(status, 'status')}}</span>
      <p v-if="message">{{message}}</p>
    </div>
    <p v-if="path" class="full-path">{{path}}</p>
    <div class="view-options" role="group" aria-label="显示方式">
      <button type="button" :aria-pressed="!raw" @click="raw=false">格式化查看</button>
      <button type="button" :aria-pressed="raw" @click="raw=true">{{xml !== null ? '原始 XML' : '原始数据'}}</button>
    </div>
    <pre v-if="raw" class="raw">{{original}}</pre>
    <template v-else>
      <p v-if="parsed.error" class="error" role="alert">{{parsed.error}}</p>
      <div v-if="active" class="groups" :class="{multiple:sections.length > 1}">
        <template v-if="sections.length > 1">
          <nav aria-label="详情分组">
            <button v-for="group in sections" :key="group.label" type="button"
                    :aria-current="active.label === group.label ? 'true' : undefined"
                    @click="selected=group.label">{{group.label}}</button>
          </nav>
          <label class="group-picker">查看分组
            <select :value="active.label" @change="selected=($event.target as HTMLSelectElement).value">
              <option v-for="group in sections" :key="group.label">{{group.label}}</option>
            </select>
          </label>
        </template>
        <section class="group-content" :aria-label="active.label">
          <h3>{{active.label}}</h3>
          <table v-if="active.dimensions" class="dimensions">
            <thead><tr><th scope="col">尺寸</th><th scope="col">候选图片</th><th scope="col">规则下限</th></tr></thead>
            <tbody>
              <tr><th scope="row">宽度</th><td>{{dimension(active.dimensions.actual_width)}}</td><td>{{dimension(active.dimensions.min_width, true)}}</td></tr>
              <tr><th scope="row">高度</th><td>{{dimension(active.dimensions.actual_height)}}</td><td>{{dimension(active.dimensions.min_height, true)}}</td></tr>
            </tbody>
          </table>
          <dl v-else-if="rows" class="nfo-values">
            <div v-for="(row, index) in rows" :key="index">
              <dt>{{row.label}}</dt>
              <dd><DetailValue :value="row.value"/></dd>
            </div>
          </dl>
          <DetailValue v-else :value="active.fields"/>
        </section>
      </div>
      <p v-else-if="!parsed.error && !message && !status">没有更多详情。</p>
    </template>
  </div>
</template>

<style scoped>
.readout {padding: 16px 20px 22px; min-width: 0}
.summary {display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px}
.summary p {margin: 0; font-weight: 600; overflow-wrap: anywhere}
.status-label {padding: 2px 8px; border-radius: 4px; color: var(--accent); background: var(--tint)}
.full-path {margin: 4px 0 12px; color: var(--muted); font-size: 13px; overflow-wrap: anywhere}
button, select {font: inherit; color: inherit; cursor: pointer}
button:focus-visible, select:focus-visible {outline: 2px solid var(--accent); outline-offset: 2px}
.view-options {display: inline-flex; max-width: 100%; margin: 6px 0 16px; padding: 2px; border: 1px solid var(--line); border-radius: 7px; gap: 2px}
.view-options button {padding: 6px 10px; border: 0; background: transparent; border-radius: 4px}
.view-options button[aria-pressed=true], nav button[aria-current=true] {background: var(--tint); color: var(--accent); font-weight: 600}
.groups.multiple {display: grid; grid-template-columns: minmax(115px, 22%) minmax(0,1fr); gap: 16px; align-items: start}
nav {display: flex; flex-direction: column; gap: 2px; padding-inline-end: 10px; border-inline-end: 1px solid var(--line)}
nav button {padding: 8px; text-align: start; border: 0; border-radius: 4px; background: transparent}
.group-picker {display: none}
.group-content {min-width: 0}
.group-content h3 {margin: 0 0 8px; font-size: 16px}
.nfo-values, .nfo-values dd {margin: 0}
.nfo-values > div {padding: 8px 0; border-top: 1px solid var(--line)}
.nfo-values dt {color: var(--muted); overflow-wrap: anywhere; font-size: 13px; margin-bottom: 4px}
.raw {margin: 0; max-width: 100%; padding: 12px; border-radius: 6px; background: var(--tint); white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.6 monospace}
.dimensions {width: 100%; border-collapse: collapse}
.dimensions th, .dimensions td {padding: 8px; border-bottom: 1px solid var(--line); text-align: start}
.error {color: rgb(var(--v-theme-error, 169, 41, 49)); margin: 0 0 12px}
@media(max-width:700px) {
  .readout {padding: 12px 14px 20px}
  .groups.multiple {display: block}
  nav {display: none}
  .group-picker {display: flex; gap: 10px; align-items: center; margin-bottom: 14px}
  .group-picker select {flex: 1; min-width: 0; padding: 8px; border: 1px solid var(--line); border-radius: 6px; background: rgb(var(--v-theme-surface,255,255,255)); appearance: auto}
  .readout button {min-height: 40px}
}
</style>
