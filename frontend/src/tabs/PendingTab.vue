<script setup lang="ts">
import {inject, toRefs} from 'vue'
import {NFO_KEY} from '../nfoState'
const nfo = toRefs(inject(NFO_KEY)!)
let {cfg, pendingCount, pendingPage, pendingLoading, tab, live, page, total, labels, guard, start, loadPending, stamp} = nfo
</script>
<template>
  <section v-if="tab==='pending'">
    <div class="toolbar"><button :disabled="live.busy||!cfg?.enabled||!pendingCount" @click="guard(()=>start('refresh_pending',{run_id:null}))">重试待同步队列</button><button :disabled="pendingLoading" @click="guard(()=>loadPending(pendingPage?.page||1))">刷新列表</button><span>共 {{pendingCount}} 项</span></div>
    <p class="hint">待同步任务独立保存，删除运行记录后仍可重试。重试会生成新的运行记录；同一已提交版本先复查 Emby，不重复补刮本地文件。</p>
    <p v-if="pendingLoading" role="status">正在读取待同步任务…</p>
    <div v-for="entry in pendingPage?.items" :key="entry.key" class="card path"><strong>{{entry.target?.path||'旧记录目标待确认'}}</strong><p>{{entry.server||'尚未配置 Emby 服务'}} · {{labels[entry.status]||entry.status}}</p><p>{{entry.message}}</p><small v-if="entry.updated">{{stamp(entry.updated)}}</small></div>
    <p v-if="pendingPage && !pendingPage.total && !pendingLoading" class="empty">没有待同步任务。</p>
    <div v-if="pendingPage?.total" class="toolbar"><button :disabled="pendingLoading||pendingPage.page<=1" @click="guard(()=>loadPending((pendingPage?.page||1)-1))">上一页</button><span>第 {{pendingPage.page}} 页 · {{pendingPage.total}} 项</span><button :disabled="pendingLoading||pendingPage.page*pendingPage.page_size>=pendingPage.total" @click="guard(()=>loadPending((pendingPage?.page||1)+1))">下一页</button></div>
  </section>
</template>
