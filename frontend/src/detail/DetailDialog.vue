<script setup lang="ts">
import {computed,ref,watch,nextTick} from 'vue'
import PluginClose from '../PluginClose.vue'
import DetailValue from './DetailValue.vue'
import {catalog,fieldLabel} from './labels'
const props=defineProps<{opened:boolean;title:string;loading:boolean;error:string;data:unknown}>()
const emit=defineEmits(['close'])
const dialog=ref<HTMLDialogElement>(), raw=ref(false)
watch(()=>props.opened,async opened=>{await nextTick();if(opened){raw.value=false;if(!dialog.value?.open)dialog.value?.showModal()}else dialog.value?.close()},{immediate:true})
const xml=computed(()=>{const d=props.data as {nfo?:unknown}|null;return typeof d?.nfo==='string'?d.nfo:''})
const metadata=computed(()=>{if(!xml.value)return props.data;const {nfo,...rest}=props.data as Record<string,unknown>;return rest})
function elementValue(node:Element,depth=0):unknown{
 if(depth>20)return node.textContent||''
 const attrs=Object.fromEntries(Array.from(node.attributes).map(a=>['@'+a.name,a.value]))
 if(!node.children.length)return Object.keys(attrs).length?{...attrs,text:node.textContent||''}:node.textContent||''
 const values:Record<string,unknown>=Object.assign(Object.create(null),attrs)
 for(const child of Array.from(node.children)){const v=elementValue(child,depth+1);if(child.tagName in values){const old=values[child.tagName];values[child.tagName]=Array.isArray(old)?[...old,v]:[old,v]}else values[child.tagName]=v}
 return values
}
const parsed=computed(()=>{
 if(!xml.value)return {error:'',groups:[]}
 if(/<!DOCTYPE|<!ENTITY/i.test(xml.value))return {error:'不支持含实体声明的 NFO，请查看原始内容。',groups:[]}
 const doc=new DOMParser().parseFromString(xml.value,'application/xml')
 if(doc.querySelector('parsererror'))return {error:'NFO XML 格式无效，请切换原始内容查看。',groups:[]}
 const groups:Record<string,{label:string;value:unknown}[]>={}
 for(const node of Array.from(doc.documentElement.children)){const f=catalog.find(f=>f.value===node.tagName);const group=f?.group||'其他字段';(groups[group] ||= []).push({label:fieldLabel(node.tagName),value:elementValue(node)})}
 return {error:'',groups:Object.entries(groups)}
})
const original=computed(()=>xml.value||JSON.stringify(props.data,null,2))
</script>
<template>
 <dialog ref="dialog" class="detail-dialog" aria-labelledby="detail-heading" @cancel.prevent="emit('close')" @close="opened&&emit('close')">
  <header><h2 id="detail-heading">{{title}}</h2><PluginClose @close="emit('close')"/></header>
  <div class="body" :aria-busy="loading">
   <p v-if="loading" role="status">正在读取详情，请稍候…</p><p v-else-if="error" role="alert" class="error">{{error}}</p>
   <template v-else>
    <nav><button :class="{active:!raw}" @click="raw=false">格式化查看</button><button :class="{active:raw}" @click="raw=true">原始{{xml?' XML':'数据'}}</button></nav>
    <pre v-if="raw">{{original}}</pre>
    <template v-else><DetailValue :value="metadata"/><p v-if="parsed.error" class="error">{{parsed.error}}</p><section v-for="[group,rows] in parsed.groups" :key="group"><h3>{{group}}</h3><div v-for="(row,index) in rows" :key="index" class="nfo-row"><h4>{{row.label}}</h4><DetailValue :value="row.value"/></div></section></template>
   </template>
  </div>
 </dialog>
</template>
<style scoped>
.detail-dialog{width:min(1000px,94vw);max-width:94vw;max-height:90dvh;padding:0;border:1px solid #8885;border-radius:12px;background:rgb(var(--v-theme-surface,255,255,255));color:rgb(var(--v-theme-on-surface,40,44,52));box-shadow:0 16px 60px #0005}.detail-dialog::backdrop{background:#0007}.detail-dialog header{display:flex;justify-content:space-between;align-items:center;gap:16px;position:sticky;top:0;z-index:1;padding:12px 20px;background:inherit;border-bottom:1px solid #8883}.detail-dialog h2{font-size:20px;margin:0}.body{padding:20px}nav{display:flex;gap:8px;margin-bottom:18px}button{font:inherit;color:inherit;padding:8px 14px;border:1px solid #8886;border-radius:6px;background:transparent;cursor:pointer}.active{background:#5269cd;color:white}.detail-dialog pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:none;font-size:13px}.error{color:#c74941}section{margin-top:22px}h3{padding:10px;background:#8881;border-radius:6px}.nfo-row{padding:12px 0;border-bottom:1px solid #8883}h4{margin:0 0 8px;overflow-wrap:anywhere}@media(max-width:650px){.body{padding:14px}.detail-dialog header{padding:10px 14px}}
</style>
