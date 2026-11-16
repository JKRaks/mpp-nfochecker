import {computed, onMounted, onUnmounted, ref, shallowRef, watch} from 'vue'
import type {InjectionKey, UnwrapNestedRefs} from 'vue'
import type {Config, HostProps, NfoField, Report, RunSummary, Rule, RuleSet, TranslationInfo} from './types'
import {createPendingState} from './pendingState'
import type {useDetail} from './detail/useDetail'

// 元数据巡检的页面状态与操作。App.vue 创建一次，并通过 provide 交给各页签组件。
export function createNfoState(props: HostProps, viewer: ReturnType<typeof useDetail>) {
const cfg = ref<Config>()
const servers = ref<string[]>([])
const channels = ref<{title: string; value: string}[]>([])
const supported = ref<Record<string, string[]>>({})
const nfoFields = ref<NfoField[]>([])
const translation = ref<TranslationInfo>({enabled:false,policies:[],fields:{title:'标题(title)',plot:'剧情简介(plot)',outline:'简短摘要(outline)',tagline:'宣传语(tagline)'}})
const translationMode = ref('normal')
const languageOps = ['language_missing','language_mismatch','language_unknown']
const usesTranslation = (rule:Rule) => ['translate','nfo_translate'].includes(rule.action) || rule.conditions.some(c=>languageOps.includes(c.op))
const policyFields = (rule:Rule) => translation.value.policies.find(p=>p.id===rule.translation_policy)?.fields || Object.keys(translation.value.fields)
const tab = ref('rules'), error = ref(''), notice = ref(''), saving = ref(false)
const url = (path: string) => `plugin/${props.pluginId}/${path}`
const pending = createPendingState(props.api,url,()=>tab.value==='pending')
const {pendingCount,pendingPage,pendingLoading,pendingDeleting,pendingRevision,loadPending,cancelPendingLoad} = pending
const savedConfig = ref('')
const dirty = computed(()=>!!cfg.value && JSON.stringify(cfg.value)!==savedConfig.value)
const live = ref({busy: false, run_id: '', error: ''})
const runs = shallowRef<RunSummary[]>([]), report = shallowRef<Report>()
const viewRunId = ref(''), recordLoading = ref(false), historySelected = ref<string[]>([]), deleteIds = ref<string[]>([]), deleting = ref(false)
const historyPage = ref(1), historySize = 20
const historyRuns = computed(()=>runs.value.slice((historyPage.value-1)*historySize,historyPage.value*historySize))
let reportRequest = 0, filterTimer:ReturnType<typeof setTimeout> | undefined, resettingFilters = false, followNewRun = false
const backups = ref<{id: string; path: string; created: number; committed: boolean; asset: string}[]>([])
const selected = ref<string[]>([]), query = ref(''), statusFilter = ref(''), kindFilter = ref(''), ruleFilter = ref('')
const labels: Record<string,string> = {movie:'电影',tv:'整部剧',season:'季',episode:'单集',nfo:'NFO',poster:'主图／海报',backdrop:'背景图',logo:'徽标',banner:'横幅',landscape:'横版图',thumb:'缩略图／单集主图',clearart:'透明艺术图',disc:'光盘图',
  pending:'待处理',complete:'完整',report:'仅报告',unstable:'等待文件稳定',ignored:'已忽略',cooldown:'冷却中',manual:'待人工处理',failed:'失败',unimproved:'未改善',partial:'部分完成',repaired:'已修复',unchanged:'内容未变化',verified:'同步已验证',unconfirmed:'图片更新未确认',locked:'字段已锁定',submitted:'刷新已提交',scanning:'扫描中',inspected:'已巡检',repairing:'修复中',finished:'已完成',cancelled:'已停止',excluded:'已排除',restored:'已恢复',batch_limited:'达到批次上限',interrupted:'运行被中断',sync_pending:'等待 Emby 同步',syncing:'同步中',paused:'已暂停',needs_recheck:'需要重新确认',discovering:'发现媒体中',unknown:'未确认层级',source_empty:'来源为空',candidate_rejected:'候选不符合规则',network:'网络失败',io:'文件读写失败',file_conflict:'文件冲突',internal:'内部错误'}
const exitLabels: Record<string,string> = {batch_limit:'达到修复批次上限，可继续剩余任务',stop:'已按请求停止',interrupted:'上次运行中断，等待手动继续',error:'运行出错',inspected:'巡检结束',completed:'本轮处理结束'}
const ops = [{value:'missing',text:'NFO 不存在'},{value:'invalid',text:'XML 损坏或根元素错误'},{value:'empty',text:'字段缺失或为空'},{value:'min_length',text:'字段长度小于'},{value:'regex',text:'字段匹配正则'},{value:'identity_missing',text:'媒体来源 ID 缺失'},{value:'conflict',text:'身份／季集号冲突（仅报告）'}]
const actions = [{value:'report',text:'仅报告'},{value:'nfo',text:'只更新 NFO'},{value:'matched_images',text:'只更新命中图片'},{value:'selected_images',text:'更新指定图片'},{value:'both',text:'更新 NFO 和图片'}]
ops.push({value:'language_missing',text:'缺少目标语言内容'},{value:'language_mismatch',text:'现有内容不是目标语言'},{value:'language_unknown',text:'语言或内容来源无法确认'})
actions.push({value:'translate',text:'仅补齐所选文字字段'},{value:'nfo_translate',text:'重新生成 NFO 并翻译'})
const page = ref(1)
const visible = computed(() => report.value?.items || [])
const total = computed(() => report.value?.total || 0)
const enabledSetCount = computed(() => cfg.value?.rule_sets.filter(s => s.enabled).length || 0)
const ruleCount = computed(() => cfg.value?.rule_sets.reduce((n, s) => n + s.rules.length, 0) || 0)
const lastRun = computed(() => runs.value[0])
const configurationIssue = computed(()=>{
  const sets=cfg.value?.rule_sets.filter(s=>s.enabled)||[]
  if(!sets.length)return '请先新建或启用一个规则集'
  for(const set of sets){
    if(!set.roots.length)return `请为「${set.name}」填写检查目录`
    if(!set.kinds.length)return `请为「${set.name}」选择媒体类型`
    if(!set.rules.some(r=>r.enabled))return `请为「${set.name}」添加或启用规则`
    for(const rule of set.rules.filter(r=>r.enabled)){
      if(rule.category==='nfo'&&!rule.conditions.length)return `请为「${rule.name}」选择至少一个条件`
      if(rule.category==='image'&&!rule.images.length)return `请为「${rule.name}」选择至少一种图片`
    }
  }
  return ''
})
const statusText = computed(() => {
  if (!cfg.value) return '正在读取设置'
  if (live.value.busy) return '任务运行中，可在巡检结果中查看进度'
  if (configurationIssue.value) return configurationIssue.value
  if (!cfg.value.enabled) return '配置已就绪，可先试运行；开启修复后可按规则运行'
  return '配置已就绪，建议先试运行查看命中结果'
})
const filters = () => ({query:query.value,status:statusFilter.value,kind:kindFilter.value,rule_set:ruleFilter.value})
watch([query,statusFilter,kindFilter,ruleFilter],()=>{
  if(resettingFilters || !viewRunId.value)return
  selected.value=[];page.value=1;reportRequest++;recordLoading.value=true
  clearTimeout(filterTimer)
  filterTimer=setTimeout(()=>{if(tab.value==='results')guard(()=>open(viewRunId.value,false))},250)
},{flush:'sync'})
watch(tab, value=>{
  if(value!=='results'){reportRequest++;recordLoading.value=false;clearTimeout(filterTimer)}
  if(value==='settings')guard(poll)
  if(value==='pending')guard(()=>loadPending(1))
  else cancelPendingLoad()
  if(value==='results' && viewRunId.value && !recordLoading.value)guard(()=>open(viewRunId.value,false))
})
const assetOptions = (set: RuleSet) => [...new Set(set.kinds.flatMap(k=>supported.value[k] || []))]
function message(e: unknown) {const v=e as {response?:{data?:{detail?:unknown}};message?:string}; return typeof v.response?.data?.detail === 'string' ? v.response.data.detail : JSON.stringify(v.response?.data?.detail || v.message || '请求失败')}
async function guard(work:()=>Promise<void>) {error.value=''; try {await work()} catch(e) {error.value=message(e)}}
async function load() {const data=await props.api.get<{config:Config;servers:string[];channels:{title:string;value:string}[];assets:Record<string,string[]>;nfo_fields:NfoField[];translation:TranslationInfo}>(url('settings'));cfg.value=data.config;savedConfig.value=JSON.stringify(data.config);servers.value=data.servers;channels.value=data.channels;supported.value=data.assets;nfoFields.value=data.nfo_fields||[];if(data.translation)translation.value=data.translation}
async function poll() {
  const revision=pendingRevision.value
  const data=await props.api.get<{live:typeof live.value;runs:RunSummary[];pending_count:number;backups?:typeof backups.value}>(url('status'),{params:{include_backups:tab.value==='settings'}})
  live.value=data.live;runs.value=data.runs
  if(revision===pendingRevision.value && !pendingDeleting.value)pendingCount.value=data.pending_count||0
  if(tab.value==='pending' && !pendingLoading.value && !pendingDeleting.value)await loadPending(pendingPage.value?.page||1)
  if(data.backups)backups.value=data.backups
  historyPage.value=Math.min(historyPage.value,Math.max(1,Math.ceil(runs.value.length/historySize)))
  historySelected.value=historySelected.value.filter(id=>runs.value.some(r=>r.id===id))
  if(data.live.error)error.value=data.live.error
  if(followNewRun && data.live.run_id){followNewRun=false;await open(data.live.run_id);return}
  const summary=runs.value.find(r=>r.id===viewRunId.value)
  if(viewRunId.value && !summary && !recordLoading.value){viewRunId.value='';report.value=undefined;selected.value=[];return}
  if(tab.value==='results' && report.value && summary && summary.updated!==report.value.updated && !recordLoading.value)await open(report.value.id,false)
}
async function open(id:string, switchTab=true) {
  clearTimeout(filterTimer)
  const request=++reportRequest
  viewRunId.value=id;recordLoading.value=true
  if(switchTab){
    resettingFilters=true;query.value='';statusFilter.value='';kindFilter.value='';ruleFilter.value='';resettingFilters=false
    selected.value=[];page.value=1;report.value=undefined;tab.value='results'
  }
  try {
    const data=await props.api.get<Report>(url('report'),{params:{run_id:id,page:page.value,page_size:100,...filters()}})
    if(request===reportRequest && tab.value==='results'){report.value=data;page.value=data.page}
  } finally {if(request===reportRequest)recordLoading.value=false}
}
async function changePage(value:number) {page.value=value;await open(viewRunId.value,false)}
async function selectAllResults() {
  const id=viewRunId.value, request=reportRequest
  const data=await props.api.get<{ids:string[]}>(url('report'),{params:{run_id:id,ids_only:true,...filters()}})
  if(id===viewRunId.value && request===reportRequest)selected.value=data.ids
}
async function deleteRuns() {
  deleting.value=true
  try {
    const ids=[...deleteIds.value]
    const data=await props.api.post<{deleted:string[]}>(url('delete_runs'),{ids})
    if(ids.includes(viewRunId.value)){reportRequest++;viewRunId.value='';report.value=undefined;selected.value=[];recordLoading.value=false}
    deleteIds.value=[];historySelected.value=historySelected.value.filter(id=>!ids.includes(id))
    notice.value=`已删除 ${data.deleted.length} 条运行记录`
    await poll()
  } finally {deleting.value=false}
}
async function save() {if(!cfg.value||saving.value)return;saving.value=true;try{const snapshot=JSON.stringify(cfg.value);await props.api.post(url('settings'),JSON.parse(snapshot));savedConfig.value=snapshot;notice.value='配置已保存'}finally{saving.value=false}}
async function start(operation:string, extra:Record<string,unknown>={}) {await props.api.post(url('start'),{operation,run_id:['run','inspect','restore','refresh_pending'].includes(operation)?null:report.value?.id,...extra});selected.value=[];if(['run','inspect','restore','refresh_pending'].includes(operation)){followNewRun=true;viewRunId.value='';report.value=undefined}tab.value='results';await poll()}
async function removePending() {
  const count=await pending.deletePending()
  notice.value=`已移出 ${count} 项待同步任务`
  if(tab.value==='pending')await loadPending(pendingPage.value?.page||1)
}
function showBackup(id:string) {return viewer.show('NFO 备份详情',()=>props.api.get(url('backup_detail'),{params:{id}}))}
async function launch(dry:boolean) {if(configurationIssue.value)throw new Error(configurationIssue.value);await save();await start('run',{dry_run:dry,run_id:null})}
async function applyTranslation() {const mode=translationMode.value;await start('repair',{ids:[...selected.value],retry:true,translation_overwrite:mode==='overwrite',translation_force:mode==='force'});translationMode.value='normal'}
function lines(value:string) {return value.split('\n').map(v=>v.trim()).filter(Boolean)}
function setLines(object:RuleSet, key:'roots'|'excludes', event:Event) {object[key]=lines((event.target as HTMLTextAreaElement).value)}
function addSet() {cfg.value?.rule_sets.push({id:crypto.randomUUID(),name:'新规则集',enabled:true,roots:[],kinds:['movie','tv','episode'],excludes:[],exclude_regex:'',exclude_season_zero:false,emby:'off',rules:[]})}
function copySet(set:RuleSet) {const copied=JSON.parse(JSON.stringify(set)) as RuleSet;copied.id=crypto.randomUUID();copied.name+=' 副本';cfg.value?.rule_sets.push(copied)}
function addRule(set:RuleSet, category:string) {set.rules.push({id:crypto.randomUUID(),name:category==='nfo'?'NFO 完整性':'图片完整性',enabled:true,category,match:'any',conditions:category==='nfo'?[{op:'empty',field:'plot',value:''}]:[],images:category==='image'?[{type:assetOptions(set)[0]||'poster',missing:true,damaged:true,min_width:0,min_height:0}]:[],action:'report',selected_images:[],translation_policy:'default',translation_fields:['plot','outline']})}
function toggleImage(rule:Rule, asset:string, checked:boolean) {if(checked)rule.images.push({type:asset,missing:true,damaged:true,min_width:0,min_height:0});else rule.images=rule.images.filter(i=>i.type!==asset)}
function toggleServer(name:string, checked:boolean) {if(!cfg.value)return;if(checked)cfg.value.emby_servers.push({name,libraries:[],mappings:[]});else cfg.value.emby_servers=cfg.value.emby_servers.filter(s=>s.name!==name)}
function stamp(time:number) {return new Date(time*1000).toLocaleString()}
let timer:ReturnType<typeof setInterval>
let polling=false
onMounted(()=>{guard(async()=>{await load();await poll()});timer=setInterval(async()=>{if(polling)return;polling=true;try{await guard(poll)}finally{polling=false}},4000)})
onUnmounted(()=>{clearInterval(timer);clearTimeout(filterTimer);reportRequest++;cancelPendingLoad()})
  return {
    cfg, servers, channels, supported, nfoFields, translation, translationMode, languageOps, usesTranslation, policyFields,
    ...pending, removePending, dirty, configurationIssue, tab, error, notice, saving, live, runs, report, viewRunId, recordLoading,
    historySelected, deleteIds, deleting, historyPage, historySize, historyRuns, backups, selected, query, statusFilter,
    kindFilter, ruleFilter, page, visible, total, labels, exitLabels, ops, actions, assetOptions, url, guard, load, poll,
    open, changePage, selectAllResults, deleteRuns, save, start, loadPending, showBackup, launch, applyTranslation, lines,
    setLines, addSet, copySet, addRule, toggleImage, toggleServer, stamp, enabledSetCount, ruleCount, lastRun, statusText,
    api: props.api,
  }
}

export type NfoState = UnwrapNestedRefs<ReturnType<typeof createNfoState>>
export const NFO_KEY: InjectionKey<NfoState> = Symbol('nfocheck-state')
export const VIEWER_KEY: InjectionKey<ReturnType<typeof useDetail>> = Symbol('nfocheck-viewer')
