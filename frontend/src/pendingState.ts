import {computed, ref, shallowRef} from 'vue'
import type {HostProps, PendingEntry, PendingPage} from './types'

// 队列选择、删除与分页刷新共用请求序号，避免旧轮询覆盖删除结果。
export function createPendingState(api: HostProps['api'], url: (path:string)=>string, active: ()=>boolean) {
  const pendingCount = ref(0), pendingPage = shallowRef<PendingPage>(), pendingLoading = ref(false)
  const pendingSelected = ref<string[]>([]), pendingDelete = ref<PendingEntry[]>([]), pendingDeleting = ref(false)
  const pendingRevision = ref(0)
  const pendingAllSelected = computed(()=>!!pendingPage.value?.items.length && pendingPage.value.items.every(e=>pendingSelected.value.includes(e.key)))
  let request = 0

  function cancelPendingLoad() {request++;pendingLoading.value=false}
  function selectPendingPage(checked:boolean) {pendingSelected.value=checked ? pendingPage.value?.items.map(e=>e.key)||[] : []}
  function confirmPendingDelete(entry?:PendingEntry) {
    pendingDelete.value=entry ? [entry] : (pendingPage.value?.items||[]).filter(e=>pendingSelected.value.includes(e.key))
  }
  async function loadPending(page:number) {
    if(pendingDeleting.value)return
    const current=++request
    pendingLoading.value=true
    try {
      const data=await api.get<PendingPage>(url('pending'),{params:{page,page_size:100}})
      if(current!==request || !active())return
      pendingPage.value=data;pendingCount.value=data.total
      pendingSelected.value=pendingSelected.value.filter(key=>data.items.some(e=>e.key===key))
    } finally {if(current===request)pendingLoading.value=false}
  }
  async function deletePending() {
    if(pendingDeleting.value || !pendingDelete.value.length)return 0
    pendingDeleting.value=true;pendingRevision.value++;cancelPendingLoad()
    try {
      const keys=pendingDelete.value.map(e=>e.key)
      const data=await api.post<{deleted:string[];pending_count:number}>(url('delete_pending'),{keys})
      pendingCount.value=data.pending_count;pendingSelected.value=[];pendingDelete.value=[]
      if(pendingPage.value)pendingPage.value={...pendingPage.value,total:data.pending_count,items:pendingPage.value.items.filter(e=>!keys.includes(e.key))}
      return data.deleted.length
    } finally {pendingDeleting.value=false;pendingRevision.value++}
  }
  return {pendingCount,pendingPage,pendingLoading,pendingSelected,pendingDelete,pendingDeleting,pendingRevision,
    pendingAllSelected,loadPending,deletePending,cancelPendingLoad,selectPendingPage,confirmPendingDelete}
}
