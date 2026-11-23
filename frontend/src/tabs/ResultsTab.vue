<script setup lang="ts">
import {inject, toRefs} from 'vue'
import ManualRepair from '../manual/ManualRepair.vue'
import type {AssetResult, Item} from '../types'
import {NFO_KEY, VIEWER_KEY} from '../nfoState'
const nfo = toRefs(inject(NFO_KEY)!)
let {cfg, translation, translationMode, tab, error, live, report, recordLoading, selected, query, statusFilter, kindFilter, ruleFilter, page, visible, total, labels, exitLabels, actions, guard, changePage, selectAllResults, start, applyTranslation, stamp} = nfo
const viewer = inject(VIEWER_KEY)!
const expandMoreByDefault = typeof window !== 'undefined' && window.matchMedia('(min-width: 761px)').matches

function canHandle(item: Item, asset: string, result: AssetResult) {
  if (item.conflicts.length || item.needs_recheck || (asset === 'nfo' && item.translation_conflict) ||
      ['ignored','excluded','unstable'].includes(item.status)) return false
  if (['translation_conflict','needs_recheck','identity_unknown','network','file_conflict','io','internal'].includes(result.error_code || '')) return false
  return ['unimproved','manual','cooldown'].includes(result.status) ||
    ['source_empty','candidate_rejected','manual_nfo'].includes(result.error_code || '') ||
    !!result.translation_pending_fields?.length ||
    (result.manual === true && !!item.remaining_assets?.includes(asset))
}

function editAsset(item: Item, asset: string) {
  const runId = report.value?.id
  if (!runId) return
  const assetLabel = labels.value[asset] || asset
  viewer.edit('手动处理 · ' + assetLabel, ManualRepair, {
    api: nfo.api.value,
    endpoint: nfo.url.value,
    runId, itemId: item.id, asset, assetLabel,
    lastMessage: item.results[asset]?.message || '',
    labels: labels.value,
    onSaved: () => {
      if (nfo.viewRunId.value === runId) void guard.value(() => nfo.open.value(runId, false))
    },
  }, item.target.path)
}
</script>
<template>
  <section v-if="tab==='results'">
    <p v-if="recordLoading" role="status">正在加载运行记录…</p>
    <div v-if="!report && !recordLoading" class="empty">选择试运行，或在运行记录中打开一次巡检。</div>
    <template v-if="report">
      <div class="card"><strong>{{report.dry_run?'试运行':'正式运行'}} · {{stamp(report.created)}} · {{labels[report.status]||report.status}}</strong><p>{{report.summary}}</p><p v-if="report.exit_reason">{{exitLabels[report.exit_reason]||report.exit_reason}}<span v-if="report.batches"> · 本次执行 {{report.batches}} 批</span></p><p v-if="report.emby_enabled===false" class="hint">规则已关闭 Emby 联动。</p><p v-for="(e,i) in report.errors" :key="i" class="error">{{e}}</p><p v-if="report.error_count>report.errors.length">共 {{report.error_count}} 条运行错误，显示前 {{report.errors.length}} 条。</p></div>
      <div class="result-controls">
        <section class="result-filters" aria-label="筛选结果">
          <h3>
            <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"><path d="M3 4h18l-7 8v8l-4-2v-6z"/></svg>
            筛选结果
          </h3>
          <div class="result-filter-fields">
            <label class="field-label filter-path">路径
              <input v-model="query" placeholder="搜索路径" aria-label="搜索路径">
            </label>
            <label class="field-label">状态
              <select v-model="statusFilter" aria-label="状态筛选">
                <option value="">全部状态</option>
                <option v-for="s in report.statuses" :key="s" :value="s">{{labels[s] || s}}</option>
              </select>
            </label>
            <label class="field-label">媒体层级
              <select v-model="kindFilter" aria-label="层级筛选">
                <option value="">全部层级</option>
                <option v-for="k in ['movie','tv','season','episode']" :key="k" :value="k">{{labels[k]}}</option>
              </select>
            </label>
            <label class="field-label filter-ruleset">规则集
              <select v-model="ruleFilter" aria-label="规则集筛选">
                <option value="">全部规则集</option>
                <option v-for="s in cfg?.rule_sets" :key="s.id" :value="s.id">{{s.name}}</option>
              </select>
            </label>
          </div>
        </section>

        <section class="result-group" aria-label="选中条目">
          <div class="result-selection">
            <div class="result-selection-title">
              <h3>选中条目</h3>
              <span class="hint" role="status">已选 {{selected.length}} 项</span>
            </div>
            <fieldset class="result-actions selection-links" aria-label="选择条目" :disabled="recordLoading">
              <button class="text-button" @click="selected=[...new Set([...selected,...visible.map(i=>i.id)])]">选择本页</button>
              <button class="text-button" @click="guard(selectAllResults)">选择全部筛选结果</button>
              <button class="text-button" @click="selected=[]">清空选择</button>
            </fieldset>
            <button class="primary repair-selected" :disabled="recordLoading || live.busy || !selected.length || !cfg?.enabled"
                    @click="guard(()=>start('repair',{ids:selected,sync:true}))">修复选中</button>
          </div>

          <details class="result-more" :open="expandMoreByDefault">
            <summary>更多选中操作</summary>
            <fieldset class="result-actions" aria-label="重试与忽略" :disabled="recordLoading || live.busy || !selected.length">
              <button :disabled="!cfg?.enabled" @click="guard(()=>start('repair',{ids:selected,retry:true}))">清除冷却并重试</button>
              <button @click="guard(()=>start('ignore',{ids:selected}))">忽略选中</button>
              <button @click="guard(()=>start('ignore',{ids:selected,undo:true}))">取消忽略</button>
            </fieldset>
            <fieldset class="result-actions result-translation" aria-label="翻译处理" :disabled="recordLoading || live.busy || !selected.length || !cfg?.enabled">
              <label>翻译处理
                <select v-model="translationMode">
                  <option value="normal">补齐未完成字段</option>
                  <option value="force">重新翻译插件生成的字段（绕过译文缓存）</option>
                  <option value="overwrite">允许替换来源不明或已手工修改的文字</option>
                </select>
              </label>
              <button @click="guard(applyTranslation)">应用到选中条目</button>
              <p v-if="translationMode==='overwrite'" class="hint">本次将按命中的翻译规则替换选中字段，备份遵循当前 NFO 备份设置。</p>
            </fieldset>
          </details>
        </section>

        <section class="result-group result-run" aria-label="本次巡检">
          <h3>本次巡检</h3>
          <fieldset class="result-actions" aria-label="本次巡检操作" :disabled="recordLoading">
            <button :disabled="live.busy || report.dry_run || !cfg?.enabled" @click="guard(()=>start('resume'))">继续剩余任务（一批）</button>
            <button :disabled="live.busy || report.dry_run || !cfg?.enabled" @click="guard(()=>start('refresh'))">仅重试 Emby 同步</button>
            <button :disabled="live.busy" @click="guard(()=>start('inspect',{set_ids:report?.set_ids}))">重新巡检</button>
          </fieldset>
        </section>
      </div>
      <div class="table-wrap" :aria-busy="recordLoading"><table><thead><tr><th>选择</th><th>媒体／状态</th><th>命中与动作</th><th>修复与同步结果</th></tr></thead><tbody><tr v-for="item in visible" :key="item.id"><td><input type="checkbox" :value="item.id" v-model="selected" :disabled="recordLoading" :aria-label="'选择 '+item.target.path"></td><td class="path"><span class="badge">{{labels[item.target.kind]}}</span> {{item.target.path}}<p>{{labels[item.status]||item.status}}</p></td><td><p class="hint">巡检时命中</p><p v-for="hit in item.hits" :key="hit.set+hit.rule"><strong>{{hit.name}}</strong><br>{{hit.reasons.join('；')}}</p><p v-if="item.conflicts.length" class="error">{{item.conflicts.join('；')}}</p><p v-if="item.translation_conflict" class="error">{{item.translation_conflict}}</p><p>动作：{{item.actions.map(a=>labels[a]).join('、')||'仅报告'}}</p><details v-if="item.remaining_hits?.length"><summary>复查后仍命中 {{item.remaining_hits.length}} 条规则</summary><p v-for="hit in item.remaining_hits" :key="hit.set+hit.rule">{{hit.name}}：{{hit.reasons.join('；')}}</p></details><p>剩余资产：{{item.remaining_assets?.map(a=>labels[a]||a).join('、')||'无'}}</p></td><td><div v-for="(res,asset) in item.results" :key="asset"><p>{{labels[asset]}}：{{labels[res.status]||res.status}} {{res.message}}</p><p v-if="res.error_code" class="hint">类型：{{labels[res.error_code]||res.error_code}}</p><p v-if="res.translation_pending_fields?.length">待处理字段：{{res.translation_pending_fields.map(f=>translation.fields[f]||f).join('、')}}</p><p v-if="res.attempts">连续未改善 {{res.attempts}} 次</p><p v-if="res.next_retry_at" class="hint">下次可重试 {{stamp(res.next_retry_at)}}</p><div class="row">
              <button v-if="res.message || res.error_code || (res.details && Object.keys(res.details).length)" @click="viewer.show((labels[asset]||asset)+'处理详情',res,item.target.path)">查看处理详情</button>
              <button v-if="canHandle(item,String(asset),res)" :disabled="recordLoading || live.busy || !cfg?.enabled" @click="editAsset(item,String(asset))">手动处理</button>
            </div></div><p v-if="item.emby_mode==='off' && !item.sync.length" class="hint">Emby 联动已关闭</p><p v-for="(sync,si) in item.sync" :key="si">{{sync.server}}：{{labels[sync.status]||sync.status}} {{sync.message}}</p></td></tr></tbody></table><div class="toolbar"><button :disabled="recordLoading||page<=1" @click="guard(()=>changePage(page-1))">上一页</button><span>第 {{page}} 页 · {{total}} 项</span><button :disabled="recordLoading||page*100>=total" @click="guard(()=>changePage(page+1))">下一页</button></div><p v-if="!total && !recordLoading" class="empty">没有匹配的结果。</p></div>
    </template>
  </section>
</template>
