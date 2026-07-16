<template>
  <div class="narrative-panel" :class="{ embedded: !!section }">
    <!-- Standalone mode: own tab bar -->
    <el-tabs v-if="!section" v-model="activeTab" class="narrative-tabs">
      <el-tab-pane label="线索账本" name="threads">
        <ThreadsSection />
      </el-tab-pane>
      <el-tab-pane label="风格指南" name="style">
        <StyleSection />
      </el-tab-pane>
      <el-tab-pane label="故事线" name="recap">
        <RecapSection />
      </el-tab-pane>
      <el-tab-pane label="宏观审阅" name="review">
        <ReviewSection />
      </el-tab-pane>
    </el-tabs>

    <!-- Embedded mode: parent owns the tab bar -->
    <template v-else>
      <ThreadsSection v-if="section === 'threads'" />
      <StyleSection v-else-if="section === 'style'" />
      <RecapSection v-else-if="section === 'recap'" />
      <ReviewSection v-else-if="section === 'review'" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import ThreadsSection from '../components/narrative/ThreadsSection.vue'
import StyleSection from '../components/narrative/StyleSection.vue'
import RecapSection from '../components/narrative/RecapSection.vue'
import ReviewSection from '../components/narrative/ReviewSection.vue'

defineProps<{
  section?: 'threads' | 'style' | 'recap' | 'review'
}>()

const activeTab = ref('threads')
</script>

<style scoped>
.narrative-panel { min-height: 0; }
.narrative-panel.embedded { height: auto; }
.narrative-tabs { flex: 1; }
</style>
