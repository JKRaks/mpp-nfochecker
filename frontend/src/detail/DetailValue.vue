<script setup lang="ts">
import {fieldLabel,displayValue} from './labels'
defineProps<{value:unknown;field?:string;depth?:number}>()
</script>
<template>
  <div v-if="Array.isArray(value)" class="array"><p v-if="!value.length">（无）</p><div v-for="(entry,index) in value" :key="index" class="entry"><small v-if="typeof entry==='object'">第 {{index+1}} 项</small><DetailValue :value="entry" :depth="(depth||0)+1" /></div></div>
  <dl v-else-if="value!==null&&typeof value==='object'" class="properties"><div v-for="(entry,key) in value" :key="key" class="property"><dt>{{fieldLabel(String(key))}}</dt><dd><DetailValue v-if="(depth||0)<15" :value="entry" :field="String(key)" :depth="(depth||0)+1"/><span v-else>内容层级较深，请切换原始模式查看。</span></dd></div></dl>
  <span v-else class="value">{{displayValue(value,field)}}</span>
</template>
<style scoped>
.properties{margin:0}.property{display:grid;grid-template-columns:minmax(140px,25%) minmax(0,1fr);gap:16px;padding:12px 0;border-bottom:1px solid #8883}dt{font-weight:600;overflow-wrap:anywhere}dd{margin:0;min-width:0}.value{white-space:pre-wrap;overflow-wrap:anywhere}.entry{padding:6px 0}.entry+ .entry{border-top:1px dashed #8884}small{opacity:.65}@media(max-width:650px){.property{grid-template-columns:1fr;gap:6px}}
</style>
