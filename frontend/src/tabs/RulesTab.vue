<script setup lang="ts">
import {inject, ref, toRefs} from 'vue'
import {NFO_KEY} from '../nfoState'
import type {Rule, RuleSet} from '../types'
import RuleEditor from '../RuleEditor.vue'
const {cfg,live,saving,labels,nfoFields,ops,actions,setLines,addSet,copySet,addRule}=toRefs(inject(NFO_KEY)!)
const expandedSet=ref(cfg.value?.rule_sets[0]?.id||''), expandedRule=ref('')
const rangeSet=ref(cfg.value?.rule_sets.find(s=>!s.roots.length)?.id||'')
const showTemplates=ref(false)
const deletion=ref<{set:RuleSet;rule?:Rule}>()
const embyLabels:Record<string,string>={off:'关闭',changed:'本地修改后刷新',compare:'修改后刷新，并检查显示缺失'}
function createSet(template='custom') {
  addSet.value()
  const set=cfg.value!.rule_sets[cfg.value!.rule_sets.length-1]
  if(template!=='custom'){
    set.name=template==='nfo'?'NFO 基础完整性':'图片完整性'
    addRule.value(set,template==='nfo'?'nfo':'image')
    const rule=set.rules[0]
    if(template==='nfo'){
      rule.conditions=[{op:'missing',field:'plot',value:''},{op:'invalid',field:'plot',value:''},{op:'empty',field:'title',value:''},{op:'empty',field:'plot',value:''}]
      rule.action='nfo'
    }else rule.action='matched_images'
  }
  expandedSet.value=set.id;expandedRule.value='';rangeSet.value=set.id;showTemplates.value=false
}
function duplicate(set:RuleSet) {copySet.value(set);const copy=cfg.value!.rule_sets[cfg.value!.rule_sets.length-1];expandedSet.value=copy.id;rangeSet.value=copy.id;expandedRule.value=''}
function createRule(set:RuleSet,category:string) {addRule.value(set,category);expandedRule.value=set.rules[set.rules.length-1].id}
function remove() {
  if(!deletion.value||!cfg.value)return
  const {set,rule}=deletion.value
  if(rule)set.rules=set.rules.filter(r=>r.id!==rule.id)
  else {cfg.value.rule_sets=cfg.value.rule_sets.filter(s=>s.id!==set.id);if(expandedSet.value===set.id)expandedSet.value=cfg.value.rule_sets[0]?.id||''}
  deletion.value=undefined
}
function ruleSummary(rule:Rule) {
  const name=(field:string)=>nfoFields.value.find(f=>f.value===field)?.label||field
  const conditions=rule.category==='nfo' ? rule.conditions.map(c=>{
    if(c.op==='empty')return name(c.field)+'为空'
    if(c.op==='min_length')return name(c.field)+'少于 '+c.value+' 字'
    if(c.op==='regex')return name(c.field)+'匹配 '+c.value
    if(c.op.startsWith('language_'))return name(c.field)+'：'+(ops.value.find(o=>o.value===c.op)?.text||c.op)
    return ops.value.find(o=>o.value===c.op)?.text||c.op
  }) : rule.images.map(i=>{
    const checks=[i.missing?'缺失':'',i.damaged?'损坏':'',i.min_width?'宽度不足 '+i.min_width+' px':'',i.min_height?'高度不足 '+i.min_height+' px':''].filter(Boolean)
    return (labels.value[i.type]||i.type)+'（'+(checks.join('／')||'未设置检查项')+'）'
  })
  return (conditions.join(rule.match==='all'?' 且 ':' 或 ')||'尚未配置条件')+' → '+(actions.value.find(a=>a.value===rule.action)?.text||rule.action)
}
function exclusions(set:RuleSet) {return [set.excludes.length?'排除 '+set.excludes.length+' 个目录':'',set.exclude_regex?'路径正则：'+set.exclude_regex:'',set.exclude_season_zero?'排除 Season 0':''].filter(Boolean).join(' · ')}
</script>
<template>
  <section v-if="cfg" aria-label="规则配置">
    <div class="section-heading"><h3>规则集</h3><div class="row"><button :disabled="live.busy||saving" :aria-expanded="showTemplates" @click="showTemplates=!showTemplates">＋ 从模板添加</button><button class="primary" :disabled="live.busy||saving" @click="createSet()">＋ 新建规则集</button></div></div>
    <div v-if="showTemplates" class="template-picker">
      <p class="hint">选择一个起点，填写检查目录后即可试运行。所有条件和动作都可以继续调整。</p>
      <div class="template-options"><button :disabled="live.busy||saving" @click="createSet('nfo')"><strong>NFO 基础完整性</strong><span>检查缺失、损坏、标题与简介 → 更新 NFO</span></button><button :disabled="live.busy||saving" @click="createSet('image')"><strong>图片缺失或损坏</strong><span>从海报开始检查 → 更新命中图片</span></button><button :disabled="live.busy||saving" @click="createSet()"><strong>自定义规则集</strong><span>自行选择检查范围与规则</span></button></div>
    </div>
    <fieldset v-for="set in cfg.rule_sets" :key="set.id" :disabled="live.busy||saving" class="ruleset">
      <div class="ruleset-heading">
        <button class="disclosure" :aria-expanded="expandedSet===set.id" @click="expandedSet=expandedSet===set.id?'':set.id"><span class="disclosure-marker" aria-hidden="true"></span><strong>{{set.name||'未命名规则集'}}</strong></button>
        <span class="badge" :class="{'success':set.enabled}">{{set.enabled?'已启用':'已停用'}}</span>
        <label class="switch-label"><input type="checkbox" role="switch" v-model="set.enabled" :aria-label="'启用规则集 '+set.name"></label>
        <details class="more-menu"><summary>更多 ⋯</summary><div class="menu-actions" @click="($event.currentTarget as HTMLElement).parentElement?.removeAttribute('open')"><button @click="duplicate(set)">复制规则集</button><button class="danger" @click="deletion={set}">删除规则集</button></div></details>
      </div>
      <div class="scope-summary"><span class="scope-path">{{set.roots.join(' · ')||'尚未设置检查目录'}}</span><span v-for="kind in set.kinds" :key="kind" class="badge">{{labels[kind]}}</span><span class="hint">{{set.rules.length}} 条规则</span><button class="text-button" :aria-expanded="rangeSet===set.id" @click="expandedSet=set.id;rangeSet=rangeSet===set.id?'':set.id">{{rangeSet===set.id?'收起检查范围':'编辑检查范围'}}</button></div>
      <div class="scope-summary hint"><span>Emby：{{embyLabels[set.emby]}}</span><span v-if="exclusions(set)" class="scope-path">{{exclusions(set)}}</span></div>
      <div v-if="deletion?.set.id===set.id" role="alertdialog" aria-label="删除规则配置" class="confirm-panel"><p>删除「{{deletion.rule?.name||set.name}}」{{deletion.rule?'这条规则':'及其中所有规则'}}？保存配置后生效。</p><div class="row"><button @click="deletion=undefined">取消</button><button class="danger" @click="remove">确认删除</button></div></div>
      <template v-if="expandedSet===set.id">
        <div v-if="rangeSet===set.id" class="scope-editor">
          <div class="grid"><label>规则集名称<input v-model="set.name"></label><label>Emby 联动<select v-model="set.emby"><option value="off">关闭</option><option value="changed">本地修改后刷新</option><option value="compare">修改后刷新，并检查 Emby 显示缺失</option></select></label></div>
          <label class="field-label">检查目录（每行一个）<textarea :value="set.roots.join('\n')" @input="setLines(set,'roots',$event)" placeholder="/media/115/电影"/></label>
          <p v-if="!set.roots.length" class="warning">请填写至少一个检查目录。</p>
          <div class="row condition"><span class="field-caption">媒体类型</span><label v-for="kind in ['movie','tv','season','episode']" :key="kind"><input type="checkbox" :value="kind" v-model="set.kinds">{{labels[kind]}}</label></div>
          <details class="advanced-options"><summary>高级范围选项 <span class="hint">{{exclusions(set)||'未设置排除项'}}</span></summary><div class="grid"><label>排除目录（每行一个）<textarea :value="set.excludes.join('\n')" @input="setLines(set,'excludes',$event)"/></label><label>排除路径正则<input v-model="set.exclude_regex" placeholder="留空不排除"></label></div><label><input type="checkbox" v-model="set.exclude_season_zero">排除 Season 0</label></details>
        </div>
        <article v-for="rule in set.rules" :key="rule.id" class="rule-card">
          <div class="rule-heading">
            <button class="disclosure" :aria-expanded="expandedRule===rule.id" @click="expandedRule=expandedRule===rule.id?'':rule.id"><span class="disclosure-marker" aria-hidden="true"></span><span class="rule-type">{{rule.category==='nfo'?'NFO':'图片'}}</span><strong>{{rule.name||'未命名规则'}}</strong></button>
            <span class="rule-summary" :title="ruleSummary(rule)">{{ruleSummary(rule)}}</span>
            <label class="switch-label"><input type="checkbox" role="switch" v-model="rule.enabled" :aria-label="'启用规则 '+rule.name"></label>
            <details class="more-menu"><summary aria-label="规则操作">⋯</summary><div class="menu-actions" @click="($event.currentTarget as HTMLElement).parentElement?.removeAttribute('open')"><button @click="expandedRule=rule.id">编辑规则</button><button class="danger" @click="deletion={set,rule}">删除规则</button></div></details>
          </div>
          <RuleEditor v-if="expandedRule===rule.id" :rule="rule" :set="set" @close="expandedRule=''"/>
        </article>
        <div v-if="!set.rules.length" class="empty compact"><p>检查范围已准备好后，添加 NFO 或图片规则。</p></div>
        <div class="row rule-add"><button class="text-button" @click="createRule(set,'nfo')">＋ 添加 NFO 规则</button><button class="text-button" @click="createRule(set,'image')">＋ 添加图片规则</button></div>
      </template>
    </fieldset>
    <div v-if="!cfg.rule_sets.length" class="empty"><h3>从一个检查目录开始</h3><p>选择常用模板，填写目录，再试运行查看结果。</p><button class="primary" :disabled="live.busy||saving" @click="showTemplates=true">从模板创建规则集</button></div>
    <details class="help-details"><summary>规则如何执行？</summary><p class="hint">所有启用规则独立判断，命中动作合并。试运行不会写入媒体文件或刷新 Emby。规则集中的联动方式与设置页选择的 Emby 服务共同生效。</p></details>
  </section>
</template>
