<script setup lang="ts">
import {inject, toRefs} from 'vue'
import {NFO_KEY} from '../nfoState'
const {cfg,servers,channels,live,saving,backups,guard,start,showBackup,lines,toggleServer,stamp}=toRefs(inject(NFO_KEY)!)
const notifyLabels:Record<string,string>={off:'关闭',always:'每轮汇总',issues:'仅有问题时通知'}
</script>
<template>
  <section v-if="cfg" aria-label="插件设置">
    <div class="section-heading"><h3>插件设置</h3><span class="hint">展开分组调整，修改后统一保存</span></div>
    <details class="settings-section" open>
      <summary><strong>执行策略</strong><span>每批 {{cfg.batch_limit}} 项 · {{cfg.auto_continue?'自动继续，最多 '+cfg.max_batches_per_run+' 批':'手动继续'}}</span></summary>
      <fieldset :disabled="live.busy||saving" class="settings-body">
        <div class="grid settings-grid">
          <label>每批修复媒体上限<input type="number" min="1" max="10000" v-model.number="cfg.batch_limit"></label>
          <label class="inline-label"><input type="checkbox" role="switch" v-model="cfg.auto_continue">达到每批上限后自动继续</label>
          <label v-if="cfg.auto_continue">每次运行最多批数（含首批）<input type="number" min="1" max="100" v-model.number="cfg.max_batches_per_run"></label>
          <label>任务间隔（秒）<input type="number" min="0" step="any" v-model.number="cfg.interval"></label>
        </div>
        <details class="advanced-options"><summary>高级执行选项 <span class="hint">文件稳定 {{cfg.stable_seconds}} 秒 · 未改善冷却 {{cfg.cooldown_days}} 天 · 记录保留 {{cfg.history_days}} 天</span></summary>
          <div class="grid"><label>文件稳定时间（秒）<input type="number" min="0" v-model.number="cfg.stable_seconds"></label><label>未改善冷却（天）<input type="number" min="0" step="any" v-model.number="cfg.cooldown_days"></label><label>连续未改善上限<input type="number" min="1" v-model.number="cfg.max_no_improvement"></label><label>运行记录保留（天）<input type="number" min="1" v-model.number="cfg.history_days"></label></div>
        </details>
        <p class="hint">“继续剩余任务”每次执行一批；冷却、忽略及等待稳定的对象不占修复名额。定时运行在 MoviePilot 工作流配置。</p>
      </fieldset>
    </details>
    <details class="settings-section">
      <summary><strong>备份</strong><span>NFO {{cfg.backup.nfo?'已开启':'已关闭'}} · 图片 {{cfg.backup.images?'已开启':'已关闭'}} · {{cfg.backup.cleanup?'自动清理':'不自动清理'}}</span></summary>
      <fieldset :disabled="live.busy||saving" class="settings-body">
        <div class="row"><label><input type="checkbox" v-model="cfg.backup.nfo">覆盖 NFO 前备份</label><label><input type="checkbox" v-model="cfg.backup.images">覆盖图片前备份</label><label><input type="checkbox" v-model="cfg.backup.cleanup">自动清理备份</label></div>
        <div class="grid" v-if="cfg.backup.cleanup"><label>保留天数（0 不限）<input type="number" min="0" v-model.number="cfg.backup.days"></label><label>每文件版本数（0 不限）<input type="number" min="0" v-model.number="cfg.backup.versions"></label></div>
        <label class="field-label">备份目录<input v-model="cfg.backup.directory" placeholder="留空使用插件数据目录"></label>
        <p class="hint">启用备份但备份失败时，该文件不覆盖。重建 NFO 会更新整份文件。</p>
      </fieldset>
    </details>
    <details class="settings-section">
      <summary><strong>Emby 联动</strong><span>已选择 {{cfg.emby_servers.length}} 个服务 · 刷新方式在规则集中配置</span></summary>
      <fieldset :disabled="live.busy||saving" class="settings-body">
        <p class="hint">仅发送定向刷新请求。请同时在规则集中开启 Emby 联动。</p>
        <div class="row"><label v-for="name in [...new Set([...servers,...cfg.emby_servers.map(s=>s.name)])]" :key="name"><input type="checkbox" :checked="cfg.emby_servers.some(s=>s.name===name)" @change="toggleServer(name,($event.target as HTMLInputElement).checked)">{{name}}<span v-if="!servers.includes(name)" class="warning">（服务不可用）</span></label></div>
        <p v-if="!servers.length" class="warning">未发现已启用的 Emby 服务，请先在 MoviePilot 配置。</p>
        <div v-for="server in cfg.emby_servers" :key="server.name" class="server-settings">
          <h4>{{server.name}}</h4>
          <details class="advanced-options"><summary>媒体库与路径映射 <span class="hint">{{server.libraries.length?server.libraries.length+' 个媒体库':'全部媒体库'}} · {{server.mappings.length}} 条映射</span></summary>
            <label class="field-label">Emby 媒体库 ID（每行一个，留空为全部）<textarea :value="server.libraries.join('\n')" @input="server.libraries=lines(($event.target as HTMLTextAreaElement).value)"/></label>
            <div class="row condition" v-for="(mapping,mi) in server.mappings" :key="mi"><input class="grow" v-model="mapping.local" aria-label="MP 本地路径" placeholder="MP：/media/115"><span>→</span><input class="grow" v-model="mapping.remote" aria-label="Emby 路径" placeholder="Emby：/media/115"><button class="text-button danger" @click="server.mappings.splice(mi,1)">移除</button></div>
            <button class="text-button" @click="server.mappings.push({local:'',remote:''})">＋ 添加路径映射</button>
          </details>
        </div>
        <div v-if="cfg.emby_servers.length" class="grid"><label>复查间隔（秒）<input type="number" min="1" step="any" v-model.number="cfg.emby_poll"></label><label>每条目最长等待（秒，0 仅提交）<input type="number" min="0" max="3600" step="any" v-model.number="cfg.emby_timeout"></label></div>
      </fieldset>
    </details>
    <details class="settings-section">
      <summary><strong>运行通知</strong><span>{{notifyLabels[cfg.notify]}} · {{cfg.notify_channels.length?cfg.notify_channels.length+' 个渠道':'使用默认渠道'}}</span></summary>
      <fieldset :disabled="live.busy||saving" class="settings-body">
        <label class="field-label">手动运行通知<select v-model="cfg.notify"><option value="off">关闭</option><option value="always">每轮汇总</option><option value="issues">仅有问题时通知</option></select></label>
        <div v-if="cfg.notify!=='off'" class="row condition"><label v-for="channel in channels" :key="channel.value"><input type="checkbox" :value="channel.value" v-model="cfg.notify_channels">{{channel.title}}</label></div>
        <p class="hint">渠道留空沿用 MP 默认通知路由。工作流运行使用末尾的官方通知节点。</p>
      </fieldset>
    </details>
    <details class="settings-section">
      <summary><strong>备份恢复</strong><span>{{backups.length}} 份备份</span></summary>
      <div class="settings-body"><p v-if="!backups.length" class="hint">暂无可恢复的备份。</p>
        <div v-for="b in backups" :key="b.id" class="backup-row"><div class="grow path">{{b.path}}<p class="hint">{{stamp(b.created)}}</p></div><div class="row"><button v-if="b.asset==='nfo'" @click="showBackup(b.id)">查看 NFO 备份</button><button :disabled="live.busy||!cfg.enabled||!b.committed" @click="guard(()=>start('restore',{backup_id:b.id,sync:false}))">恢复文件</button><button :disabled="live.busy||!cfg.enabled||!b.committed" @click="guard(()=>start('restore',{backup_id:b.id,sync:true}))">恢复并刷新 Emby</button></div></div>
      </div>
    </details>
  </section>
</template>
