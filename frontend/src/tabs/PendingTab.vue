<script setup lang="ts">
import {inject, toRefs} from 'vue'
import {NFO_KEY} from '../nfoState'
const {cfg,pendingCount,pendingPage,pendingLoading,pendingSelected,pendingDelete,pendingDeleting,pendingAllSelected,
  live,labels,guard,start,loadPending,stamp,selectPendingPage,confirmPendingDelete,removePending}=toRefs(inject(NFO_KEY)!)
</script>
<template>
  <section aria-label="待同步管理">
    <div class="section-heading"><div class="row"><h3>待同步任务</h3><span class="hint">共 {{pendingCount}} 项</span></div><div class="row">
      <button :disabled="pendingLoading||pendingDeleting" @click="guard(()=>loadPending(pendingPage?.page||1))">刷新列表</button>
      <button class="primary" :disabled="live.busy||pendingDeleting||!cfg?.enabled||!pendingCount" @click="guard(()=>start('refresh_pending',{run_id:null}))">重试队列</button>
    </div></div>
    <div class="toolbar selection-bar">
      <label><input type="checkbox" :checked="pendingAllSelected" :indeterminate="!!pendingSelected.length&&!pendingAllSelected" :disabled="live.busy||pendingDeleting||!pendingPage?.items.length" @change="selectPendingPage(($event.target as HTMLInputElement).checked)">选择本页</label>
      <span class="hint">已选 {{pendingSelected.length}} 项</span>
      <button class="danger" :disabled="live.busy||pendingDeleting||!pendingSelected.length" @click="confirmPendingDelete()">移出选中任务</button>
    </div>
    <p v-if="live.busy" class="hint">任务运行期间暂不可移出队列，请等待任务结束或停止任务。</p>
    <p v-if="pendingLoading" role="status" class="hint">正在读取待同步任务…</p>
    <div v-if="pendingDelete.length" role="alertdialog" aria-labelledby="pending-delete-title" aria-describedby="pending-delete-description" class="confirm-panel">
      <strong id="pending-delete-title">移出选中的 {{pendingDelete.length}} 项任务？</strong>
      <p id="pending-delete-description">仅移出当前队列，保留媒体文件、备份和运行记录。已提交的 Emby 请求不会撤回；后续运行再次触发同步时，可重新入队。</p>
      <ul class="confirm-targets"><li v-for="entry in pendingDelete" :key="entry.key">{{entry.target?.path||'旧记录目标待确认'}} · {{entry.server||'未配置服务'}}</li></ul>
      <div class="row"><button :disabled="pendingDeleting" @click="pendingDelete=[]">取消</button><button class="danger" :disabled="live.busy||pendingDeleting" @click="guard(removePending)">{{pendingDeleting?'正在移出…':'确认移出'}}</button></div>
    </div>
    <div v-if="pendingPage?.items.length" class="pending-list">
      <article v-for="entry in pendingPage.items" :key="entry.key" class="pending-row">
        <input type="checkbox" :value="entry.key" v-model="pendingSelected" :disabled="live.busy||pendingDeleting" :aria-label="'选择 '+(entry.target?.path||entry.key)">
        <div class="pending-target"><strong>{{entry.target?.path?.split(/[\\/]/).filter(Boolean).pop()||'旧记录目标待确认'}}</strong><p class="hint path">{{entry.target?.path||entry.key}}</p><p v-if="entry.message" class="hint">{{entry.message}}</p><small v-if="entry.updated" class="hint">{{stamp(entry.updated)}}</small></div>
        <div class="pending-meta"><span class="badge">{{entry.server||'未配置 Emby 服务'}}</span><span class="badge" :class="{'error':entry.status==='failed','warning':entry.status==='unimproved'||entry.status==='unconfirmed'}">{{labels[entry.status]||entry.status}}</span></div>
        <button class="text-button danger" :disabled="live.busy||pendingDeleting" @click="confirmPendingDelete(entry)">移出</button>
      </article>
    </div>
    <p v-if="pendingPage && !pendingPage.total && !pendingLoading" class="empty">没有待同步任务。</p>
    <div v-if="pendingPage?.total" class="toolbar"><button :disabled="pendingLoading||pendingDeleting||pendingPage.page<=1" @click="guard(()=>loadPending((pendingPage?.page||1)-1))">上一页</button><span>第 {{pendingPage.page}} 页 · {{pendingPage.total}} 项</span><button :disabled="pendingLoading||pendingDeleting||pendingPage.page*pendingPage.page_size>=pendingPage.total" @click="guard(()=>loadPending((pendingPage?.page||1)+1))">下一页</button></div>
    <p class="hint">队列独立保存。重试会生成新的运行记录，已提交版本先复查 Emby，不重复补刮本地文件。</p>
  </section>
</template>
