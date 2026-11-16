<script setup lang="ts">
import {computed, inject, ref, toRefs} from 'vue'
import {NFO_KEY} from './nfoState'
import type {Rule, RuleSet} from './types'
import NfoFieldSelect from './NfoFieldSelect.vue'
const props=defineProps<{rule:Rule;set:RuleSet}>()
defineEmits<{(e:'close'):void}>()
const {nfoFields,translation,languageOps,usesTranslation,policyFields,labels,ops,actions,assetOptions,toggleImage}=toRefs(inject(NFO_KEY)!)
const addingField=ref(false), field=ref('plot')
const emptyFields=computed(()=>[...new Set(['title','plot',...props.rule.conditions.filter(c=>c.op==='empty').map(c=>c.field)])])
const advanced=computed(()=>props.rule.conditions.map((condition,index)=>({condition,index})).filter(({condition})=>!['missing','invalid','empty'].includes(condition.op)))
const assets=computed(()=>[...new Set([...assetOptions.value(props.set),...props.rule.images.map(i=>i.type),...props.rule.selected_images])])
const mixedFields=computed(()=>props.rule.conditions.filter(c=>c.op==='empty').map(c=>nfoFields.value.find(f=>f.value===c.field)).filter(f=>f && props.set.kinds.some(k=>!f.kinds.includes(k))))
function toggleCondition(op:string,field:string,checked:boolean) {
  if(checked){if(!props.rule.conditions.some(c=>c.op===op && (op!=='empty'||c.field===field)))props.rule.conditions.push({op,field:field||'plot',value:''})}
  else props.rule.conditions=props.rule.conditions.filter(c=>!(c.op===op && (op!=='empty'||c.field===field)))
}
function addField() {if(!field.value.trim())return;toggleCondition('empty',field.value.trim(),true);addingField.value=false}
</script>
<template>
  <div class="rule-editor">
    <label class="field-label">规则名称<input v-model="rule.name" aria-label="规则名称"></label>
    <div class="editor-columns">
      <div class="condition-editor">
        <div class="row"><strong>触发条件</strong><div class="segmented" aria-label="条件关系">
          <button :class="{'is-selected':rule.match==='any'}" :aria-pressed="rule.match==='any'" @click="rule.match='any'">任一满足</button>
          <button :class="{'is-selected':rule.match==='all'}" :aria-pressed="rule.match==='all'" @click="rule.match='all'">全部满足</button>
        </div></div>
        <template v-if="rule.category==='nfo'">
          <div class="row condition"><label v-for="op in [{value:'missing',text:'NFO 不存在'},{value:'invalid',text:'XML 损坏或根元素错误'}]" :key="op.value"><input type="checkbox" :checked="rule.conditions.some(c=>c.op===op.value)" @change="toggleCondition(op.value,'',($event.target as HTMLInputElement).checked)">{{op.text}}</label></div>
          <p class="field-caption">检查必填字段</p>
          <div class="row field-chips"><label v-for="name in emptyFields" :key="name" class="field-chip"><input type="checkbox" :checked="rule.conditions.some(c=>c.op==='empty'&&c.field===name)" @change="toggleCondition('empty',name,($event.target as HTMLInputElement).checked)">{{nfoFields.find(f=>f.value===name)?.label||name}}</label><button class="text-button" @click="addingField=!addingField">＋ 添加字段</button></div>
          <div v-if="addingField" class="row condition"><NfoFieldSelect v-model="field" :fields="nfoFields" :kinds="set.kinds"/><button :disabled="!field.trim()" @click="addField">添加</button><button class="text-button" @click="addingField=false">取消</button></div>
          <p v-if="mixedFields.length" class="warning">部分字段不适用于所有选定层级：{{mixedFields.map(f=>f!.label).join('、')}}。建议放入单独的规则集。</p>
          <div v-for="{condition:cond,index} in advanced" :key="index" class="advanced-condition">
            <select aria-label="NFO 判定条件" v-model="cond.op"><option v-for="op in ops" :key="op.value" :value="op.value">{{op.text}}</option></select>
            <select v-if="languageOps.includes(cond.op)" v-model="cond.field" aria-label="翻译条件字段"><option v-for="(name,key) in translation.fields" :key="key" :value="key">{{name}}</option></select>
            <NfoFieldSelect v-if="['regex','min_length'].includes(cond.op)" v-model="cond.field" :fields="nfoFields" :kinds="set.kinds"/>
            <input v-if="['regex','min_length'].includes(cond.op)" aria-label="条件值" v-model="cond.value" :placeholder="cond.op==='regex'?'正则表达式':'最小字符数'">
            <button class="text-button danger" @click="rule.conditions.splice(index,1)">移除条件</button>
          </div>
          <button class="text-button" @click="rule.conditions.push({op:'min_length',field:'plot',value:'20'})">＋ 添加高级条件</button>
          <details class="help-details"><summary>条件说明</summary><p class="hint">未找到字段、空标签或内容仅有空白均视为空；重复字段至少一项非空即通过，0 和 false 不算空。所有条件按上方“任一／全部满足”判断。</p></details>
          <p v-if="!rule.conditions.length" class="warning">请至少选择一个条件。</p>
        </template>
        <template v-else>
          <div class="row condition"><label v-for="asset in assets" :key="asset"><input type="checkbox" :checked="rule.images.some(i=>i.type===asset)" @change="toggleImage(rule,asset,($event.target as HTMLInputElement).checked)">{{labels[asset]||asset}}</label></div>
          <div v-for="check in rule.images" :key="check.type" class="image-check"><strong>{{labels[check.type]}}</strong><div class="row"><label><input type="checkbox" v-model="check.missing">缺失</label><label><input type="checkbox" v-model="check.damaged">损坏</label><label>宽度 ≥<input aria-label="最小宽度" type="number" min="0" v-model.number="check.min_width">px</label><label>高度 ≥<input aria-label="最小高度" type="number" min="0" v-model.number="check.min_height">px</label></div></div>
          <p class="hint">尺寸为 0 表示不限；同一图片类型任一文件合格即通过。</p>
          <p v-if="!rule.images.length" class="warning">请至少选择一种图片。</p>
        </template>
      </div>
      <div class="action-editor">
        <label class="field-label">命中动作<select v-model="rule.action"><option v-for="a in actions.filter(a=>rule.category==='image'?!['translate','nfo_translate'].includes(a.value):a.value!=='matched_images')" :value="a.value" :key="a.value">{{a.text}}</option></select></label>
        <p class="hint">{{rule.action==='report'?'仅记录命中结果，不执行修复。':'覆盖前按备份设置保存原文件。试运行不会写入媒体文件或刷新 Emby。'}}</p>
        <div v-if="['selected_images','both'].includes(rule.action)"><p class="field-caption">另行指定更新</p><div class="row"><label v-for="asset in assets" :key="asset"><input type="checkbox" :value="asset" v-model="rule.selected_images">{{labels[asset]}}</label></div></div>
      </div>
    </div>
    <div v-if="rule.category==='nfo' && usesTranslation(rule)" class="translation-editor">
      <h4>翻译联动</h4><p v-if="!translation.enabled" class="warning">元数据翻译插件未启用或不可用，请先在独立插件中配置服务和策略。</p>
      <label class="field-label">翻译策略<select v-model="rule.translation_policy"><option v-if="!translation.policies.some(p=>p.id===rule.translation_policy)" :value="rule.translation_policy">{{rule.translation_policy}}（未找到）</option><option v-for="p in translation.policies" :key="p.id" :value="p.id">{{p.name}} · {{p.target_language}}</option></select></label>
      <div class="row condition"><label v-for="(name,key) in translation.fields" :key="key"><input type="checkbox" :value="key" v-model="rule.translation_fields" :disabled="!policyFields(rule).includes(key)&&!rule.translation_fields.includes(key)">{{name}}</label></div>
      <p class="hint">条件字段也须勾选。仅补齐文字会保留其他 NFO 节点；重建采用官方候选。不同策略命中同一 NFO 时转人工处理。摘要仅写入本地。</p>
    </div>
    <div class="editor-footer"><span class="hint">修改后统一保存配置</span><button class="text-button" @click="$emit('close')">收起编辑</button></div>
  </div>
</template>
