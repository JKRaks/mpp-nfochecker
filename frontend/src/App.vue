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
const viewer = useDetail()
const state = reactive(createNfoState(props, viewer))
provide(NFO_KEY, state)
provide(VIEWER_KEY, viewer)
const {cfg,live,error,notice,saving,dirty,configurationIssue,tab,pendingCount,statusText,enabledSetCount,ruleCount,lastRun,labels,stamp,guard,save,launch,api,url}=toRefs(state)
</script>
<template>
<div class="nfo-app">
  <PluginHeader :title="configView ? '元数据巡检 - 插件配置' : '元数据巡检'" @close="emit('close')"/>
  <div class="plugin-content">
    <div class="intro-row"><span class="hint">检查 NFO 与图片，按规则修复并同步 Emby</span><span class="badge" :class="{'success':!live.busy,'active':live.busy}">{{live.busy?'任务运行中':'空闲'}}</span></div>
    <nav class="page-tabs" aria-label="插件页面"><button v-for="t in [{id:'rules',name:'规则'},{id:'results',name:'巡检结果'},{id:'history',name:'运行记录'},{id:'pending',name:'待同步'},{id:'settings',name:'设置'}]" :key="t.id" :class="{'is-current':tab===t.id}" :aria-current="tab===t.id?'page':undefined" @click="tab=t.id">{{t.name}}<span v-if="t.id==='pending'" class="tab-count">{{pendingCount}}</span></button></nav>
    <div v-if="error" role="alert" class="alert error">{{error}} <button class="text-button" @click="error=''">关闭</button></div>
    <div v-if="notice" role="status" class="alert">{{notice}} <button class="text-button" @click="notice=''">关闭</button></div>
    <div v-if="cfg && (tab==='rules'||live.busy)" class="status-strip">
      <div role="status" aria-live="polite"><strong>{{statusText}}</strong><p class="hint">{{enabledSetCount}} 个规则集已启用 · {{ruleCount}} 条规则 · 待同步 {{pendingCount}} 项<template v-if="lastRun"> · 上次 {{stamp(lastRun.created)}}（{{labels[lastRun.status]||lastRun.status}}）</template></p></div>
      <div v-if="!live.busy" class="setup-steps" aria-label="配置步骤"><span>① 选择目录</span><span>→</span><span>② 配置规则</span><span>→</span><span>③ 试运行确认</span></div>
      <button v-if="live.busy" class="danger" @click="guard(async()=>{await api.post(url('stop'));notice='已请求停止'})">停止任务</button><button v-else-if="pendingCount" @click="tab='pending'">查看待同步</button>
    </div>
    <p v-if="!cfg" role="status">正在读取设置…</p>
    <RulesTab v-if="cfg" v-show="tab==='rules'"/>
    <ResultsTab v-if="tab==='results'"/>
    <PendingTab v-if="tab==='pending'"/>
    <HistoryTab v-if="tab==='history'"/>
    <SettingsTab v-if="cfg" v-show="tab==='settings'"/>
    <div v-if="cfg && ['rules','settings'].includes(tab)" class="config-actions">
      <div class="row"><label><input type="checkbox" role="switch" v-model="cfg.enabled" :disabled="live.busy||saving">启用修复与 Emby 刷新</label><span :class="dirty?'warning':'hint'">{{dirty?'● 有未保存修改':'✓ 已保存'}}</span></div>
      <div class="row"><button :class="{primary:tab==='settings'}" :disabled="live.busy||saving||!dirty" @click="guard(save)">{{saving?'正在保存…':'保存配置'}}</button><template v-if="tab==='rules'"><button :disabled="live.busy||saving||!!configurationIssue" @click="guard(()=>launch(true))">{{dirty?'保存并试运行':'试运行'}}</button><button class="primary" :disabled="live.busy||saving||!cfg.enabled||!!configurationIssue" @click="guard(()=>launch(false))">{{dirty?'保存并运行':'按规则运行'}}</button></template></div>
    </div>
  </div>
  <DetailDialog :opened="viewer.opened.value" :title="viewer.title.value" :loading="viewer.loading.value" :error="viewer.error.value" :data="viewer.data.value" @close="viewer.close"/>
</div>
</template>
<style src="./nfo.css"></style>
