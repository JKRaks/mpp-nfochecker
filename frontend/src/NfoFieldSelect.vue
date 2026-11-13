<script setup lang="ts">
import { computed, ref } from 'vue'
import type { NfoField } from './types'
const props = defineProps<{ modelValue: string; fields: NfoField[]; kinds: string[] }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: string): void }>()
const custom = ref(false)
const selected = computed(() => props.fields.find((f) => f.value === props.modelValue))
const customMode = computed(() => custom.value || !selected.value)
const groups = computed(() =>
  [...new Set(props.fields.map((f) => f.group))]
    .map((name) => ({
      name,
      fields: props.fields.filter(
        (f) =>
          f.group === name &&
          (f.value === props.modelValue || f.kinds.some((k) => props.kinds.includes(k))),
      ),
    }))
    .filter((g) => g.fields.length),
)
const names: Record<string, string> = { movie: '电影', tv: '整部剧', season: '季', episode: '单集' }
const mixed = computed(
  () => selected.value && props.kinds.some((k) => !selected.value!.kinds.includes(k)),
)
function choose(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  custom.value = value === '__custom__'
  if (!custom.value) emit('update:modelValue', value)
}
</script>

<template>
  <div class="nfo-field">
    <select aria-label="NFO 字段" :value="customMode ? '__custom__' : modelValue" @change="choose">
      <optgroup v-for="group in groups" :key="group.name" :label="group.name">
        <option v-for="field in group.fields" :key="field.value" :value="field.value">
          {{ field.label }}
        </option>
      </optgroup>
      <option value="__custom__">自定义字段路径(XPath)</option>
    </select>
    <input
      v-if="customMode"
      aria-label="XML 字段路径"
      :value="modelValue"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      placeholder="例如 actor/name"
    />
    <small v-if="!customMode && selected"
      >适用：{{ selected.kinds.map((k) => names[k]).join('、') }}。{{ selected.note }}
      <span v-if="mixed"
        >当前规则集包含其他层级，此条件仍检查所有选定层级；建议将专属字段放入单独的规则集。</span
      >
      <span v-if="selected.group === '图片引用'"
        >这里只检查 NFO 中的网址；本地图片完整性请使用图片规则。</span
      >
    </small>
    <small v-else>相对根元素的 XML 路径，例如 actor/name、uniqueid[@type='tmdb']。</small>
  </div>
</template>

<style scoped>
.nfo-field {
  flex: 1 1 300px;
  min-width: 0;
  max-width: 100%;
}
.nfo-field select,
.nfo-field input {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  font: inherit;
  color: inherit;
  background: transparent;
  border: 1px solid #8887;
  border-radius: 6px;
  padding: 8px;
}
.nfo-field select option {
  color: #222;
  background: #fff;
}
.nfo-field input {
  margin-top: 6px;
}
.nfo-field small {
  display: block;
  margin-top: 5px;
  line-height: 1.5;
  opacity: 0.72;
  overflow-wrap: anywhere;
}
</style>
