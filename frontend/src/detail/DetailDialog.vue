<script setup lang="ts">
import {computed, nextTick, onMounted, onUnmounted, ref} from 'vue'
import PluginClose from '../PluginClose.vue'
import DetailReadout from './DetailReadout.vue'
import type {DetailSession} from './useDetail'

const props = withDefaults(defineProps<{session: DetailSession; modelValue?: boolean}>(), {modelValue: true})
const emit = defineEmits<{(event: 'close'): void}>()
const media = window.matchMedia('(max-width: 700px)')
const mobile = ref(media.matches)
const dirty = ref(false)
const busy = ref(false)
const confirmDiscard = ref(false)
const titleElement = ref<HTMLElement>()
const continueButton = ref<HTMLButtonElement>()
let lastControl: HTMLElement | null = null
function resize() { mobile.value = media.matches }
onMounted(() => media.addEventListener('change', resize))
onUnmounted(() => media.removeEventListener('change', resize))

const path = computed(() => {
  const data = props.session.data as {backup?: {path?: string}; path?: string} | undefined
  return props.session.subtitle || data?.backup?.path || data?.path || ''
})
const filename = computed(() => path.value.split(/[/\\]/).filter(Boolean).pop())
function requestClose() {
  if (busy.value || confirmDiscard.value) return
  if (dirty.value) {
    lastControl = document.activeElement instanceof HTMLElement ? document.activeElement : null
    confirmDiscard.value = true
    return
  }
  emit('close')
}
function continueEditing() {
  confirmDiscard.value = false
  void nextTick(() => { if (lastControl?.isConnected) lastControl.focus({preventScroll: true}) })
}
</script>
<template>
  <v-dialog
    :model-value="modelValue" :fullscreen="mobile" :width="mobile ? undefined : 920"
    :persistent="busy || dirty" :transition="false" :aria-label="session.title"
    @update:model-value="(visible: boolean) => { if (!visible) requestClose() }"
    @click:outside="dirty && requestClose()"
    @after-enter="titleElement?.focus({preventScroll:true})"
  >
    <article class="detail-frame" @keydown.esc.stop.prevent="confirmDiscard ? continueEditing() : requestClose()">
      <header class="detail-heading">
        <div>
          <h2 ref="titleElement" tabindex="-1">{{session.title}}</h2>
          <p v-if="filename" class="filename">{{filename}}</p>
        </div>
        <PluginClose :disabled="busy" @close="requestClose"/>
      </header>
      <div class="detail-body" :aria-busy="!!session.loading" :inert="confirmDiscard">
        <p v-if="session.loading" class="status" role="status">正在读取详情…</p>
        <p v-else-if="session.error" class="status error" role="alert">{{session.error}}</p>
        <component v-else-if="session.editor" :is="session.editor" v-bind="session.editorProps"
                   @dirty="dirty = $event" @busy="busy = $event" @close="requestClose"/>
        <DetailReadout v-else :data="session.data" :path="path"/>
      </div>
      <div v-if="confirmDiscard" class="discard" role="alert">
        <strong>放弃未保存的修改？</strong>
        <div>
          <button ref="continueButton" type="button" @vue:mounted="continueButton?.focus()" @click="continueEditing">继续编辑</button>
          <button type="button" @click="emit('close')">放弃修改</button>
        </div>
      </div>
    </article>
  </v-dialog>
</template>
<style scoped>
.detail-frame {
  --line: rgba(var(--v-theme-on-surface, 43, 48, 58), .17);
  --muted: rgba(var(--v-theme-on-surface, 43, 48, 58), .68);
  --tint: rgba(var(--v-theme-on-surface, 43, 48, 58), .05);
  --accent: rgb(var(--v-theme-primary, 82, 105, 205));
  display: flex; flex-direction: column; width: 100%; min-height: 0;
  max-height: min(88dvh, 900px); overflow: hidden; border-radius: 12px;
  color: rgb(var(--v-theme-on-surface, 43, 48, 58)); background: rgb(var(--v-theme-surface, 255, 255, 255));
  font: inherit; font-size: 15px; text-align: start;
}
.detail-heading {display: flex; flex: none; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 20px; border-bottom: 1px solid var(--line)}
.detail-heading > div {min-width: 0}
.detail-heading h2 {font-size: 19px; font-weight: 600; line-height: 1.4; margin: 0}
.detail-heading h2:focus {outline: none}
.filename {margin: 2px 0 0; font-size: 13px; color: var(--muted); overflow-wrap: anywhere}
.detail-body {min-height: 0; overflow: auto; overscroll-behavior: contain}
.status {padding: 20px; margin: 0}
.error {color: rgb(var(--v-theme-error, 169, 41, 49))}
.discard {padding: 12px 20px; padding-bottom: max(12px, env(safe-area-inset-bottom)); border-top: 1px solid var(--line); display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px}
.discard > div {display: flex; gap: 8px}
.discard button {color: inherit; font: inherit; border: 1px solid var(--line); padding: 8px 12px; border-radius: 6px; cursor: pointer}
@media(max-width: 700px) {
  .detail-frame {height: 100dvh; max-height: 100%; border-radius: 0}
  .detail-heading {padding: max(10px, env(safe-area-inset-top)) 12px 10px}
  .detail-body {flex: 1; padding-bottom: env(safe-area-inset-bottom)}
  .filename {display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden}
}
</style>
