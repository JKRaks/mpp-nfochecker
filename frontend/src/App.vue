<script setup lang="ts">
import {provide, reactive, toRefs} from 'vue'
import type {HostProps} from './types'
import PluginHeader from './PluginHeader.vue'
import DetailDialog from './detail/DetailDialog.vue'
import {useDetail} from './detail/useDetail'
import {createNfoState, NFO_KEY, VIEWER_KEY} from './nfoState'
import RulesTab from './tabs/RulesTab.vue'
import ResultsTab from './tabs/ResultsTab.vue'
import PendingTab from './tabs/PendingTab.vue'
import HistoryTab from './tabs/HistoryTab.vue'
import SettingsTab from './tabs/SettingsTab.vue'

const props = defineProps<HostProps & {configView?: boolean}>()
const emit = defineEmits(['close'])
// 页面状态只在这里创建一次，各页签通过 provide/inject 读取，避免逐层传参。
const viewer = useDetail()
const state = reactive(createNfoState(props, viewer))
provide(NFO_KEY, state)
provide(VIEWER_KEY, viewer)
let {cfg, live, error, notice, saving, tab, pendingCount, statusText, enabledSetCount, ruleCount, lastRun, labels, stamp, guard, save, launch, api, url} = toRefs(state)
</script>
<template>
<div class="nfo-app">
  <PluginHeader :title="configView ? '元数据巡检 - 插件配置' : '元数据巡检'" @close="emit('close')" />
  <div class="plugin-content">
  <p class="hint">按规则补齐 NFO 与图片，同步 Emby 显示。 <span class="badge" :class="{active:live.busy}">{{live.busy?'任务运行中':'空闲'}}</span></p>
  <div v-if="cfg" class="status-strip" role="status" aria-live="polite">
    <p><strong>{{statusText}}</strong></p>
    <p class="hint">规则集 {{enabledSetCount}}/{{cfg.rule_sets.length}} 个启用 · 规则 {{ruleCount}} 条 · 待同步 {{pendingCount}} 项<template v-if="lastRun"> · 上次运行 {{stamp(lastRun.created)}}（{{labels[lastRun.status]||lastRun.status}}）</template></p>
  </div>
  <div v-if="error" role="alert" class="alert error">{{error}} <button @click="error=''">关闭</button></div>
  <div v-if="notice" role="status" class="alert">{{notice}} <button @click="notice=''">关闭</button></div>
  <nav aria-label="插件页面"><button v-for="t in [{id:'rules',name:'规则'},{id:'results',name:'巡检结果'},{id:'history',name:'运行记录'},{id:'pending',name:'待同步（'+pendingCount+'）'},{id:'settings',name:'设置'}]" :key="t.id" :class="{chosen:tab===t.id}" @click="tab=t.id">{{t.name}}</button></nav>
  <div v-if="cfg" class="toolbar"><label><input type="checkbox" v-model="cfg.enabled" :disabled="live.busy">启用修复及 Emby 刷新</label><button :disabled="live.busy||saving" @click="guard(save)">保存设置</button><button :disabled="live.busy" @click="guard(()=>launch(true))">试运行</button><button class="primary" :disabled="live.busy||!cfg.enabled" @click="guard(()=>launch(false))">按规则运行</button><button v-if="live.busy" @click="guard(async()=>{await api.post(url('stop'));notice='已请求停止'})">停止</button></div>
  <p v-if="!cfg">正在读取设置…</p>
  <RulesTab v-if="cfg && tab==='rules'" />
  <ResultsTab v-if="tab==='results'" />
  <PendingTab v-if="tab==='pending'" />
  <HistoryTab v-if="tab==='history'" />
  <SettingsTab v-if="cfg && tab==='settings'" />
  </div>
  <DetailDialog :opened="viewer.opened.value" :title="viewer.title.value" :loading="viewer.loading.value" :error="viewer.error.value" :data="viewer.data.value" @close="viewer.close" />
</div>
</template>

<style src="./nfo.css"></style>
