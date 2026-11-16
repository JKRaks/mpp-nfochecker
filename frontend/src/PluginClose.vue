<script setup lang="ts">
const emit = defineEmits<{(event:'close'):void}>()
</script>

<template>
  <v-btn class="plugin-close" color="default" icon variant="text" size="small" type="button" aria-label="关闭" title="关闭" @click="emit('close')">
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18" /></svg>
  </v-btn>
</template>

<style scoped>
.plugin-close{flex:0 0 40px;width:40px;height:40px;min-width:40px;padding:0;border:0;border-radius:50%;background:transparent;color:rgb(var(--v-theme-on-surface,40,44,52))!important}.plugin-close:focus-visible{outline:2px solid rgb(var(--v-theme-primary,82,105,205));outline-offset:2px}
</style>
