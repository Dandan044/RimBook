<template>
  <div class="tab-card">
    <div class="tab-toolbar review-toolbar">
      <el-radio-group v-model="reviewScope" size="small">
        <el-radio-button value="volume">按卷</el-radio-button>
        <el-radio-button value="range">按章节范围</el-radio-button>
      </el-radio-group>
      <template v-if="reviewScope === 'volume'">
        <el-select v-model="reviewVolume" size="small" placeholder="选择卷" style="width:160px">
          <el-option v-for="v in volumes" :key="v.number" :value="v.number" :label="`第 ${v.number} 卷 ${v.title || ''}`" />
        </el-select>
      </template>
      <template v-else>
        <el-input-number v-model="reviewFrom" size="small" :min="1" controls-position="right" style="width:100px" />
        <span class="dim-text">至</span>
        <el-input-number v-model="reviewTo" size="small" :min="1" controls-position="right" style="width:100px" />
      </template>
      <el-button size="small" type="primary" @click="doReview" :loading="loading">
        <el-icon><View /></el-icon> 开始审阅
      </el-button>
    </div>

    <div class="review-layout">
      <div class="review-list">
        <div class="review-list-header">历史报告</div>
        <div
          v-for="r in reviews" :key="r.name"
          class="review-list-item" :class="{ active: r.name === currentReviewName }"
          @click="openReview(r.name)"
        >
          {{ formatReviewName(r.name) }}
        </div>
        <div v-if="!reviews.length" class="dim-text" style="padding:12px">暂无报告</div>
      </div>
      <div class="review-detail">
        <div v-if="loading" class="review-running">
          <el-icon class="is-loading"><Loading /></el-icon> 正在审阅，可能需要一到两分钟…
        </div>
        <div v-else-if="reviewText" class="md-body" v-html="renderMarkdown(reviewText)"></div>
        <el-empty v-else description="选择左侧报告或发起新的审阅" :image-size="80" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { marked } from 'marked'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../../stores/project'
import { runMacroReview, listReviews, getReview, listVolumes, type VolumeOutline } from '../../api'
import './narrative.css'

const store = useProjectStore()
const reviewScope = ref<'volume' | 'range'>('volume')
const reviewVolume = ref<number | null>(null)
const reviewFrom = ref(1)
const reviewTo = ref(1)
const reviews = ref<{ name: string }[]>([])
const reviewText = ref('')
const currentReviewName = ref('')
const volumes = ref<VolumeOutline[]>([])
const loading = ref(false)

function renderMarkdown(text: string): string {
  try { return marked.parse(text) as string } catch { return text }
}

async function fetchVolumes() {
  if (!store.currentId) return
  try { volumes.value = await listVolumes(store.currentId) } catch {}
}

async function fetchReviews() {
  if (!store.currentId) return
  try { reviews.value = (await listReviews(store.currentId)).reviews } catch {}
}

async function openReview(name: string) {
  if (!store.currentId) return
  try {
    const r = await getReview(store.currentId, name)
    reviewText.value = r.text
    currentReviewName.value = name
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '读取失败') }
}

async function doReview() {
  if (!store.currentId) return
  const payload: { volume?: number; from_chapter?: number; to_chapter?: number } = {}
  if (reviewScope.value === 'volume') {
    if (!reviewVolume.value) { ElMessage.warning('请选择要审阅的卷'); return }
    payload.volume = reviewVolume.value
  } else {
    payload.from_chapter = reviewFrom.value
    payload.to_chapter = reviewTo.value
  }
  loading.value = true
  reviewText.value = ''
  try {
    const r = await runMacroReview(store.currentId, payload)
    reviewText.value = `# 宏观审阅报告 · ${r.scope}\n\n${r.report}`
    currentReviewName.value = r.saved_as
    ElMessage.success(`审阅完成（覆盖 ${r.chapters} 章）`)
    await fetchReviews()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '审阅失败') }
  finally { loading.value = false }
}

function formatReviewName(name: string): string {
  const m = name.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})\d{2}-(.+)\.md$/)
  if (!m) return name
  const scope = m[6].startsWith('vol')
    ? `第${m[6].slice(3)}卷`
    : m[6].startsWith('ch') ? `第${m[6].slice(2).replace('-', '–')}章` : m[6]
  return `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]} · ${scope}`
}

onMounted(() => {
  fetchVolumes()
  fetchReviews()
})
</script>

<style scoped>
.review-toolbar { justify-content: flex-start; }

.review-layout {
  display: flex;
  gap: 16px;
  min-height: 320px;
}

.review-list {
  width: 240px;
  flex-shrink: 0;
  border: 1px solid var(--rb-border-light);
  border-radius: 10px;
  overflow-y: auto;
  max-height: 480px;
  background: var(--rb-bg-subtle);
}

.review-list-header {
  padding: 10px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--rb-text-muted);
  border-bottom: 1px solid var(--rb-border-light);
}

.review-list-item {
  padding: 10px 14px;
  font-size: 13px;
  color: var(--rb-text-secondary);
  cursor: pointer;
  border-bottom: 1px solid var(--rb-border-light);
  transition: background 0.15s ease;
}

.review-list-item:hover { background: var(--rb-bg-surface); }
.review-list-item.active { background: var(--rb-primary); color: #fff; }

.review-detail {
  flex: 1;
  min-width: 0;
  border: 1px solid var(--rb-border-light);
  border-radius: 10px;
  padding: 16px 20px;
  overflow-y: auto;
  max-height: 480px;
}

.review-running {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--rb-text-muted);
  font-size: 14px;
  padding: 24px;
}

@media (max-width: 768px) {
  .review-layout { flex-direction: column; }
  .review-list { width: 100%; max-height: 200px; }
}
</style>
