<script setup lang="ts">
import App from './App.vue'
import type {HostProps} from './types'
defineProps<HostProps>()
const emit = defineEmits(['close'])
</script>
<template><App :api="api" :plugin-id="pluginId" /><div style="text-align:right;padding:12px"><v-btn @click="emit('close')">关闭</v-btn></div></template>
