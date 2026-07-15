<template>
  <div class="narrative-page">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon class="title-icon"><Compass /></el-icon>
        叙事管理
      </h1>
    </div>

    <el-tabs v-model="activeTab" class="narrative-tabs">
      <!-- ============ 线索账本 ============ -->
      <el-tab-pane label="线索账本" name="threads">
        <div class="tab-card">
          <div class="tab-toolbar">
            <el-radio-group v-model="threadFilter" size="small">
              <el-radio-button value="open">未回收</el-radio-button>
              <el-radio-button value="all">全部</el-radio-button>
            </el-radio-group>
            <el-button size="small" @click="fetchThreads" :loading="loading.threads">
              <el-icon><Refresh /></el-icon> 刷新
            </el-button>
          </div>
          <el-table :data="visibleThreads" v-loading="loading.threads" class="threads-table" empty-text="暂无线索（写作时自动抽取，或在设置中开启 track_threads）">
            <el-table-column label="类型" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="threadTypeTag(row.type)">{{ threadTypeLabel(row.type) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag size="small" :type="threadStatusTag(row.status)" effect="plain">{{ threadStatusLabel(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="埋设" width="70" align="center">
              <template #default="{ row }">第{{ row.planted_chapter }}章</template>
            </el-table-column>
            <el-table-column label="预期回收" width="90" align="center">
              <template #default="{ row }">
                <span v-if="row.expected_resolve_chapter">第{{ row.expected_resolve_chapter }}章</span>
                <span v-else class="dim-text">—</span>
              </template>
            </el-table-column>
            <el-table-column label="回收于" width="80" align="center">
              <template #default="{ row }">
                <span v-if="row.resolved_chapter">第{{ row.resolved_chapter }}章</span>
                <span v-else class="dim-text">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="130" align="center">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="openThreadEditor(row)">编辑</el-button>
                <el-popconfirm title="确定删除该线索？" @confirm="removeThread(row)">
                  <template #reference>
                    <el-button size="small" text type="danger">删除</el-button>
                  </template>
                </el-popconfirm>
              </template>
            </el-table-column>
            <el-table-column type="expand">
              <template #default="{ row }">
                <div class="thread-updates">
                  <div v-if="!row.updates.length" class="dim-text">暂无进展记录</div>
                  <div v-for="(u, i) in row.updates" :key="i" class="thread-update-item">
                    <el-tag size="small" effect="plain">第{{ u.chapter }}章</el-tag>
                    <span>{{ u.note }}</span>
                  </div>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- ============ 风格指南 ============ -->
      <el-tab-pane label="风格指南" name="style">
        <div class="tab-card">
          <div class="tab-toolbar">
            <span class="toolbar-hint">写作与修订时自动注入到提示词最前部</span>
            <div class="toolbar-actions">
              <el-button size="small" @click="doGenerateStyle" :loading="loading.styleGen">
                <el-icon><MagicStick /></el-icon> 从已写章节反推
              </el-button>
              <el-button size="small" type="primary" @click="saveStyle" :loading="loading.styleSave">
                <el-icon><Check /></el-icon> 保存
              </el-button>
            </div>
          </div>
          <el-input
            v-model="styleText" type="textarea" :rows="22" class="style-input"
            placeholder="风格圣经：叙事视角、语言风格、禁用词、对白习惯等。留空则不注入。"
          />
        </div>
      </el-tab-pane>

      <!-- ============ 故事线 ============ -->
      <el-tab-pane label="故事线" name="recap">
        <div class="tab-card">
          <div class="tab-toolbar">
            <span class="toolbar-hint">
              全书至今故事线
              <el-tag v-if="storyUpto > 0" size="small" effect="plain" style="margin-left:8px">已覆盖至第 {{ storyUpto }} 章</el-tag>
            </span>
            <el-button size="small" type="primary" @click="doRefreshStory" :loading="loading.story">
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
              <el-button size="small" text type="primary" @click="doVolumeRecap(v.number)" :loading="loading.volumeRecap === v.number">
                {{ v.recap ? '重新生成' : '生成回顾' }}
              </el-button>
            </div>
            <div v-if="v.recap" class="volume-recap-text">{{ v.recap }}</div>
            <div v-else class="dim-text">尚无回顾（需要该卷章节已有摘要）</div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ============ 宏观审阅 ============ -->
      <el-tab-pane label="宏观审阅" name="review">
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
            <el-button size="small" type="primary" @click="doReview" :loading="loading.review">
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
              <div v-if="loading.review" class="review-running">
                <el-icon class="is-loading"><Loading /></el-icon> 正在审阅，可能需要一到两分钟…
              </div>
              <div v-else-if="reviewText" class="md-body" v-html="renderMarkdown(reviewText)"></div>
              <el-empty v-else description="选择左侧报告或发起新的审阅" :image-size="80" />
            </div>
          </div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 线索编辑对话框 -->
    <el-dialog v-model="threadDialog" title="编辑线索" width="520px">
      <el-form label-width="80px" v-if="threadForm">
        <el-form-item label="描述">
          <el-input v-model="threadForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="threadForm.type" style="width:200px">
            <el-option value="foreshadow" label="伏笔" />
            <el-option value="suspense" label="悬念" />
            <el-option value="promise" label="承诺" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="threadForm.status" style="width:200px">
            <el-option value="open" label="未回收" />
            <el-option value="progressed" label="推进中" />
            <el-option value="resolved" label="已回收" />
          </el-select>
        </el-form-item>
        <el-form-item label="预期回收">
          <el-input-number v-model="threadForm.expected_resolve_chapter" :min="1" controls-position="right" />
          <span class="dim-text" style="margin-left:8px">章（可留空）</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="threadDialog = false">取消</el-button>
        <el-button type="primary" @click="saveThread" :loading="loading.threadSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { marked } from 'marked'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import {
  listThreads, updateThread, deleteThread,
  getStyle, updateStyle, generateStyle,
  getStorySoFar, refreshStorySoFar, refreshVolumeRecap,
  runMacroReview, listReviews, getReview, listVolumes,
  type PlotThread, type VolumeOutline,
} from '../api'

const store = useProjectStore()
const activeTab = ref('threads')

const loading = reactive({
  threads: false, styleGen: false, styleSave: false,
  story: false, volumeRecap: 0, review: false, threadSave: false,
})

function renderMarkdown(text: string): string {
  try { return marked.parse(text) as string } catch { return text }
}

// ===== 线索账本 =====
const threads = ref<PlotThread[]>([])
const threadFilter = ref<'open' | 'all'>('open')
const visibleThreads = computed(() =>
  threadFilter.value === 'all' ? threads.value : threads.value.filter(t => t.status !== 'resolved'))

const threadTypeLabel = (t: string) => ({ foreshadow: '伏笔', suspense: '悬念', promise: '承诺' } as Record<string, string>)[t] || t
const threadTypeTag = (t: string) => ({ foreshadow: 'warning', suspense: 'danger', promise: 'success' } as Record<string, string>)[t] || 'info'
const threadStatusLabel = (s: string) => ({ open: '未回收', progressed: '推进中', resolved: '已回收' } as Record<string, string>)[s] || s
const threadStatusTag = (s: string) => ({ open: 'warning', progressed: 'primary', resolved: 'success' } as Record<string, string>)[s] || 'info'

async function fetchThreads() {
  if (!store.currentId) return
  loading.threads = true
  try { threads.value = (await listThreads(store.currentId)).threads }
  catch (e: any) { ElMessage.error(e?.response?.data?.detail || '加载线索失败') }
  finally { loading.threads = false }
}

const threadDialog = ref(false)
const threadForm = ref<{ id: string; description: string; type: string; status: string; expected_resolve_chapter: number | null } | null>(null)

function openThreadEditor(row: PlotThread) {
  threadForm.value = {
    id: row.id, description: row.description, type: row.type,
    status: row.status, expected_resolve_chapter: row.expected_resolve_chapter,
  }
  threadDialog.value = true
}

async function saveThread() {
  if (!store.currentId || !threadForm.value) return
  loading.threadSave = true
  try {
    const f = threadForm.value
    await updateThread(store.currentId, f.id, {
      description: f.description, type: f.type, status: f.status,
      expected_resolve_chapter: f.expected_resolve_chapter,
    })
    threadDialog.value = false
    ElMessage.success('线索已更新')
    await fetchThreads()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
  finally { loading.threadSave = false }
}

async function removeThread(row: PlotThread) {
  if (!store.currentId) return
  try {
    await deleteThread(store.currentId, row.id)
    ElMessage.success('已删除')
    await fetchThreads()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '删除失败') }
}

// ===== 风格指南 =====
const styleText = ref('')

async function fetchStyle() {
  if (!store.currentId) return
  try { styleText.value = (await getStyle(store.currentId)).text } catch {}
}

async function saveStyle() {
  if (!store.currentId) return
  loading.styleSave = true
  try {
    await updateStyle(store.currentId, styleText.value)
    ElMessage.success('风格指南已保存')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
  finally { loading.styleSave = false }
}

async function doGenerateStyle() {
  if (!store.currentId) return
  loading.styleGen = true
  try {
    const r = await generateStyle(store.currentId)
    styleText.value = r.text
    ElMessage.success('已根据近期章节反推风格指南（已自动保存，可继续修改）')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '生成失败') }
  finally { loading.styleGen = false }
}

// ===== 故事线 =====
const storyText = ref('')
const storyUpto = ref(0)
const volumes = ref<VolumeOutline[]>([])

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
  loading.story = true
  try {
    const r = await refreshStorySoFar(store.currentId)
    storyText.value = r.text
    storyUpto.value = r.upto_chapter
    ElMessage.success('故事线已更新')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '更新失败') }
  finally { loading.story = false }
}

async function fetchVolumes() {
  if (!store.currentId) return
  try { volumes.value = await listVolumes(store.currentId) } catch {}
}

async function doVolumeRecap(number: number) {
  if (!store.currentId) return
  loading.volumeRecap = number
  try {
    await refreshVolumeRecap(store.currentId, number)
    ElMessage.success(`第 ${number} 卷回顾已生成`)
    await fetchVolumes()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '生成失败') }
  finally { loading.volumeRecap = 0 }
}

// ===== 宏观审阅 =====
const reviewScope = ref<'volume' | 'range'>('volume')
const reviewVolume = ref<number | null>(null)
const reviewFrom = ref(1)
const reviewTo = ref(1)
const reviews = ref<{ name: string }[]>([])
const reviewText = ref('')
const currentReviewName = ref('')

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
  loading.review = true
  reviewText.value = ''
  try {
    const r = await runMacroReview(store.currentId, payload)
    reviewText.value = `# 宏观审阅报告 · ${r.scope}\n\n${r.report}`
    currentReviewName.value = r.saved_as
    ElMessage.success(`审阅完成（覆盖 ${r.chapters} 章）`)
    await fetchReviews()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '审阅失败') }
  finally { loading.review = false }
}

function formatReviewName(name: string): string {
  // 20260715-103000-vol1.md → 2026-07-15 10:30 · 第1卷
  const m = name.match(/^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})\d{2}-(.+)\.md$/)
  if (!m) return name
  const scope = m[6].startsWith('vol')
    ? `第${m[6].slice(3)}卷`
    : m[6].startsWith('ch') ? `第${m[6].slice(2).replace('-', '–')}章` : m[6]
  return `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]} · ${scope}`
}

onMounted(() => {
  fetchThreads()
  fetchStyle()
  fetchStory()
  fetchVolumes()
  fetchReviews()
})
</script>

<style scoped>
.narrative-page {
  min-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
}

.page-header { margin-bottom: 16px; flex-shrink: 0; }

.page-title {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--rb-text-primary);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.title-icon { color: var(--rb-primary); font-size: 22px; }

.narrative-tabs { flex: 1; }

.tab-card {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 14px;
  padding: 20px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.tab-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.toolbar-hint { font-size: 13px; color: var(--rb-text-muted); }
.toolbar-actions { display: flex; gap: 8px; }

.dim-text { color: var(--rb-text-muted); font-size: 13px; }

/* threads */
.thread-updates { padding: 8px 16px; }
.thread-update-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 13px;
  color: var(--rb-text-secondary);
  margin-bottom: 6px;
}

/* style */
.style-input :deep(textarea) {
  font-size: 14px;
  line-height: 1.8;
  font-family: var(--rb-font);
}

/* recap */
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

/* review */
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

/* markdown body */
.md-body {
  font-size: 14px;
  line-height: 1.9;
  color: var(--rb-text-primary);
}

.md-body :deep(h1) { font-size: 18px; }
.md-body :deep(h2) { font-size: 16px; }
.md-body :deep(h3) { font-size: 15px; }
.md-body :deep(p) { margin: 8px 0; }
.md-body :deep(ul), .md-body :deep(ol) { padding-left: 22px; }

@media (max-width: 768px) {
  .review-layout { flex-direction: column; }
  .review-list { width: 100%; max-height: 200px; }
}
</style>
