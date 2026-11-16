<script setup lang="ts">
import {inject, toRefs} from 'vue'
import {NFO_KEY} from '../nfoState'
const nfo = toRefs(inject(NFO_KEY)!)
let {tab, live, runs, historySelected, deleteIds, deleting, historyPage, historySize, historyRuns, labels, guard, open, deleteRuns, stamp} = nfo
</script>
<template>
  <section v-if="tab==='history'">
    <div class="toolbar"><button :disabled="live.busy||deleting||!historyRuns.length" @click="historySelected=historyRuns.map(r=>r.id)">选择本页记录</button><button :disabled="!historySelected.length||deleting" @click="historySelected=[]">清空选择</button><button :disabled="live.busy||deleting||!historySelected.length" @click="deleteIds=[...historySelected]">删除选中记录（{{historySelected.length}}）</button></div>
    <div v-if="deleteIds.length" role="alertdialog" aria-label="删除运行记录" class="card">
      <p>确定删除这 {{deleteIds.length}} 条运行记录及巡检结果？删除后无法在运行记录中查看；媒体文件、备份、规则和待同步任务保留。</p>
      <div class="row"><button :disabled="live.busy||deleting" @click="guard(deleteRuns)">确认删除</button><button :disabled="deleting" @click="deleteIds=[]">取消删除</button></div>
    </div>
    <p v-if="live.busy" class="hint">任务运行期间暂不可删除记录。</p>
    <div v-for="run in historyRuns" :key="run.id" class="card row">
      <input type="checkbox" :value="run.id" v-model="historySelected" :disabled="live.busy||deleting" :aria-label="'选择运行记录 '+stamp(run.created)">
      <div class="grow"><strong>{{stamp(run.created)}} · {{labels[run.status]||run.status}}</strong><p>{{run.summary}}</p></div>
      <button @click="guard(()=>open(run.id))">查看结果</button><button :disabled="live.busy||deleting" @click="deleteIds=[run.id]">删除记录</button>
    </div>
    <div v-if="runs.length" class="toolbar"><button :disabled="historyPage<=1" @click="historyPage--">上一页记录</button><span>第 {{historyPage}} 页 · {{runs.length}} 条记录</span><button :disabled="historyPage*historySize>=runs.length" @click="historyPage++">下一页记录</button></div>
    <p v-else class="empty">暂无运行记录。</p>
  </section>
</template>
