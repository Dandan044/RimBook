<template>
  <div class="tab-card">
    <div class="tab-toolbar">
      <span class="toolbar-hint">
        全书至今故事线
        <el-tag v-if="storyUpto > 0" size="small" effect="plain" style="margin-left:8px">已覆盖至第 {{ storyUpto }} 章</el-tag>
      </span>
      <el-button size="small" type="primary" @click="doRefreshStory" :loading="loadingStory">
        <el-icon><Refresh /></el-icon> 更新至最新章节
      </el-button>
    </div>
    <div v-if="storyText" class="md-body" v-html="renderMarkdown(storyText)"></div>
    <el-empty v-else description="尚未生成。写作过程中会按配置周期自动更新，也可手动触发。" :image-size="80" />

    <el-divider />

    <h3 class="section-heading">分卷回顾</h3>
    <div v-if="!volumes.length" class="dim-text">暂无分卷</div>
    <div v-for="v in volumes" :key="v.number" class="volume-recap-item">
      <div class="volume-recap-head">
        <span class="volume-recap-title">第 {{ v.number }} 卷《{{ v.title || '未命名' }}》</span>
        <el-button size="small" text type="primary" @click="doVolumeRecap(v.number)" :loading="loadingVolume === v.number">
          {{ v.recap ? '重新生成' : '生成回顾' }}
        </el-button>
      </div>
      <div v-if="v.recap" class="volume-recap-text">{{ v.recap }}</div>
      <div v-else class="dim-text">尚无回顾（需要该卷章节已有摘要）</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { marked } from 'marked'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../../stores/project'
import { getStorySoFar, refreshStorySoFar, refreshVolumeRecap, listVolumes, type VolumeOutline } from '../../api'
import './narrative.css'

const store = useProjectStore()
const storyText = ref('')
const storyUpto = ref(0)
const volumes = ref<VolumeOutline[]>([])
const loadingStory = ref(false)
const loadingVolume = ref(0)

function renderMarkdown(text: string): string {
  try { return marked.parse(text) as string } catch { return text }
}

async function fetchStory() {
  if (!store.currentId) return
  try {
    const r = await getStorySoFar(store.currentId)
    storyText.value = r.text
    storyUpto.value = r.upto_chapter
  } catch {}
}

async function doRefreshStory() {
  if (!store.currentId) return
  loadingStory.value = true
  try {
    const r = await refreshStorySoFar(store.currentId)
    storyText.value = r.text
    storyUpto.value = r.upto_chapter
    ElMessage.success('故事线已更新')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '更新失败') }
  finally { loadingStory.value = false }
}

async function fetchVolumes() {
  if (!store.currentId) return
  try { volumes.value = await listVolumes(store.currentId) } catch {}
}

async function doVolumeRecap(number: number) {
  if (!store.currentId) return
  loadingVolume.value = number
  try {
    await refreshVolumeRecap(store.currentId, number)
    ElMessage.success(`第 ${number} 卷回顾已生成`)
    await fetchVolumes()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '生成失败') }
  finally { loadingVolume.value = 0 }
}

onMounted(() => {
  fetchStory()
  fetchVolumes()
})
</script>

<style scoped>
.section-heading {
  font-size: 13px;
  font-weight: 600;
  color: var(--rb-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 0 0 12px;
}

.volume-recap-item {
  border: 1px solid var(--rb-border-light);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
  background: var(--rb-bg-subtle);
}

.volume-recap-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.volume-recap-title { font-size: 14px; font-weight: 600; color: var(--rb-text-primary); }

.volume-recap-text {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.8;
  color: var(--rb-text-secondary);
}
</style>
