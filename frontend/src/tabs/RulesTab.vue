<script setup lang="ts">
import {inject, toRefs} from 'vue'
import {NFO_KEY} from '../nfoState'
import NfoFieldSelect from '../NfoFieldSelect.vue'
const nfo = toRefs(inject(NFO_KEY)!)
let {cfg, nfoFields, translation, languageOps, usesTranslation, policyFields, tab, live, labels, ops, actions, assetOptions, setLines, addSet, copySet, addRule, toggleImage} = nfo
</script>
<template>
  <section v-if="cfg && tab==='rules'">
    <p class="hint">所有启用规则独立判断，命中动作合并。同一图片类型有任一合格文件即通过。试运行不会写入媒体文件或刷新 Emby。</p>
    <fieldset v-for="(set,si) in cfg.rule_sets" :key="set.id" :disabled="live.busy" class="card">
      <div class="row"><label><input type="checkbox" v-model="set.enabled">启用</label><input aria-label="规则集名称" v-model="set.name" class="grow"><button @click="copySet(set)">复制</button><button @click="cfg.rule_sets.splice(si,1)">删除规则集</button></div>
      <div class="grid"><label>检查目录（每行一个）<textarea :value="set.roots.join('\n')" @input="setLines(set,'roots',$event)" placeholder="/media/115/电影" /></label><label>排除目录（每行一个）<textarea :value="set.excludes.join('\n')" @input="setLines(set,'excludes',$event)" /></label></div>
      <div class="row"><label v-for="kind in ['movie','tv','season','episode']" :key="kind"><input type="checkbox" :value="kind" v-model="set.kinds">{{labels[kind]}}</label><label><input type="checkbox" v-model="set.exclude_season_zero">排除 Season 0</label></div>
      <div class="grid"><label>排除路径正则<input v-model="set.exclude_regex" placeholder="留空不排除" /></label><label>Emby 联动<select v-model="set.emby"><option value="off">关闭</option><option value="changed">本地修改后刷新</option><option value="compare">修改后刷新，并检查 Emby 显示缺失</option></select></label></div>
      <article v-for="(rule,ri) in set.rules" :key="rule.id" class="rule">
        <div class="row"><label><input type="checkbox" v-model="rule.enabled">启用</label><input v-model="rule.name" aria-label="规则名称" class="grow"><span>{{rule.category==='nfo'?'NFO':'图片'}}</span><button @click="set.rules.splice(ri,1)">删除</button></div>
        <div class="grid"><label>条件关系<select v-model="rule.match"><option value="any">任一满足</option><option value="all">全部满足</option></select></label><label>命中动作<select v-model="rule.action"><option v-for="a in actions.filter(a=>rule.category==='image'?!['translate','nfo_translate'].includes(a.value):a.value!=='matched_images')" :value="a.value" :key="a.value">{{a.text}}</option></select></label></div>
        <template v-if="rule.category==='nfo'">
          <div v-for="(cond,ci) in rule.conditions" :key="ci" class="row condition"><select aria-label="NFO 判定条件" v-model="cond.op"><option v-for="op in ops" :key="op.value" :value="op.value">{{op.text}}</option></select><select v-if="languageOps.includes(cond.op)" v-model="cond.field" aria-label="翻译条件字段"><option v-for="(name,field) in translation.fields" :key="field" :value="field">{{name}}</option></select><NfoFieldSelect v-if="['empty','regex','min_length'].includes(cond.op)" v-model="cond.field" :fields="nfoFields" :kinds="set.kinds"/><input v-if="['regex','min_length'].includes(cond.op)" aria-label="条件值" v-model="cond.value" :placeholder="cond.op==='regex'?'正则表达式':'最小字符数'"><button @click="rule.conditions.splice(ci,1)">移除条件</button></div>
          <p class="hint">未找到字段、空标签或内容仅有空白均视为空；重复字段至少有一项非空即通过，0 和 false 不算空。标准中的可选字段由你按需添加。</p>
          <div v-if="usesTranslation(rule)" class="card">
            <p v-if="!translation.enabled" class="hint">元数据翻译插件未启用或不可用。请在独立插件中配置服务和策略；图片任务可继续处理。</p>
            <label>翻译策略<select v-model="rule.translation_policy"><option v-if="!translation.policies.some(p=>p.id===rule.translation_policy)" :value="rule.translation_policy">{{rule.translation_policy}}（未找到）</option><option v-for="p in translation.policies" :key="p.id" :value="p.id">{{p.name}} · {{p.target_language}}</option></select></label>
            <div class="row"><label v-for="(name,field) in translation.fields" :key="field"><input type="checkbox" :value="field" v-model="rule.translation_fields" :disabled="!policyFields(rule).includes(field)&&!rule.translation_fields.includes(field)">{{name}}</label></div>
            <p class="hint">条件字段也须勾选。仅补齐文字会保留其他 NFO 节点；重建操作采用官方候选。不同策略同时命中同一 NFO 时转人工处理。摘要(outline)仅写入本地。</p>
          </div>
          <button @click="rule.conditions.push({op:'empty',field:'plot',value:''})">添加 NFO 条件</button>
        </template>
        <template v-else>
          <div class="row"><label v-for="asset in assetOptions(set)" :key="asset"><input type="checkbox" :checked="rule.images.some(i=>i.type===asset)" @change="toggleImage(rule,asset,($event.target as HTMLInputElement).checked)">{{labels[asset]}}</label></div>
          <div v-for="check in rule.images" :key="check.type" class="row condition"><strong>{{labels[check.type]}}</strong><label><input type="checkbox" v-model="check.missing">缺失</label><label><input type="checkbox" v-model="check.damaged">损坏</label><label>最小宽<input type="number" min="0" v-model.number="check.min_width"></label><label>最小高<input type="number" min="0" v-model.number="check.min_height"></label></div>
        </template>
        <div v-if="['selected_images','both'].includes(rule.action)" class="row"><span>另行指定更新：</span><label v-for="asset in assetOptions(set)" :key="asset"><input type="checkbox" :value="asset" v-model="rule.selected_images">{{labels[asset]}}</label></div>
      </article>
      <div class="row"><button @click="addRule(set,'nfo')">添加 NFO 规则</button><button @click="addRule(set,'image')">添加图片规则</button></div>
    </fieldset>
    <div v-if="!cfg.rule_sets.length" class="empty"><p>还没有规则集。规则集指定要检查的目录和媒体类型，规则决定哪些内容需要修复。</p><p class="hint">建议先添加一个规则集，设置检查目录后再添加 NFO 或图片规则，并先试运行。</p></div>
    <button @click="addSet" :disabled="live.busy">添加规则集</button>
  </section>
</template>
