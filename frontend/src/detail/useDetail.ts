import {onUnmounted, ref, shallowRef} from 'vue'
export function useDetail(){
  const opened=ref(false), title=ref('详情'), loading=ref(false), error=ref(''), data=shallowRef<unknown>(null)
  let sequence=0
  function close(){opened.value=false;loading.value=false;sequence++}
  async function show(name:string, value:unknown|(()=>Promise<unknown>)){
    const id=++sequence;title.value=name;data.value=null;error.value='';opened.value=true;loading.value=typeof value==='function'
    try{const result=typeof value==='function'?await (value as ()=>Promise<unknown>)():value;if(id===sequence)data.value=result}
    catch(e:any){if(id===sequence)error.value=typeof e?.response?.data?.detail==='string'?e.response.data.detail:e?.message||'详情读取失败'}
    finally{if(id===sequence)loading.value=false}
  }
  onUnmounted(close)
  return {opened,title,loading,error,data,close,show}
}
