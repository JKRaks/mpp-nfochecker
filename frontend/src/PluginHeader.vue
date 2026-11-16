<script setup lang="ts">
import PluginClose from './PluginClose.vue'
defineProps<{ title: string }>()
const emit = defineEmits(['close'])
</script>
<template>
  <header class="plugin-header">
    <h2 class="plugin-header-title">{{ title }}</h2>
    <PluginClose @close="emit('close')" />
  </header>
</template>
<style scoped>
.plugin-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: nowrap;
  gap: 16px;
  margin: 0;
  padding: 16px 16px 16px 24px;
  min-height: 64px;
  background: transparent;
  color: rgb(var(--v-theme-on-surface, 40, 44, 52));
  border-bottom: 1px solid rgba(var(--v-border-color, 128, 128, 128), var(--v-border-opacity, 0.16));
  box-sizing: border-box;
}
.plugin-header .plugin-header-title {
  margin: 0;
  padding: 0;
  min-width: 0;
  font-size: 20px;
  line-height: 1.5;
  font-weight: 500;
  overflow-wrap: anywhere;
}
</style>
