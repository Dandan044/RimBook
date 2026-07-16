<template>
  <div class="llm-logs">
    <div class="page-header">
      <div class="page-header-left">
        <h1 class="page-title">LLM 日志</h1>
        <p class="page-subtitle">按工作流阶段查看模型请求与响应溯源</p>
      </div>
      <div class="page-header-right">
        <el-select
          v-model="store.currentId"
          placeholder="选择项目"
          class="project-select"
          @change="onProjectChange"
        >
          <el-option
            v-for="p in store.projects"
            :key="p.id"
            :label="p.title || p.id"
            :value="p.id"
          />
        </el-select>
        <el-select
          v-model="selectedDate"
          placeholder="选择日期"
          class="date-select"
          :disabled="!dates.length"
          @change="loadDay"
        >
          <el-option v-for="d in dates" :key="d" :label="d" :value="d" />
        </el-select>
        <el-button :loading="loading" :disabled="!store.currentId" @click="refresh">
          <el-icon><Refresh /></el-icon> 刷新
        </el-button>
      </div>
    </div>

    <div v-if="!store.currentId" class="empty-panel">
      <el-icon :size="36" class="empty-icon"><FolderOpened /></el-icon>
      <p>请先选择一个项目</p>
    </div>

    <template v-else>
      <!-- Project-level token usage -->
      <div class="token-section">
        <div class="token-section-header">
          <h2 class="token-section-title">项目 Token 用量</h2>
          <span class="token-section-meta" v-if="projectUsage">
            {{ projectUsage.calls_with_usage }} / {{ projectUsage.calls }} 次有用量
          </span>
        </div>
        <div class="token-grid">
          <div class="token-card" v-for="(card, idx) in projectTokenCards" :key="'p-' + idx">
            <div class="token-label">{{ card.label }}</div>
            <div class="token-value" :style="{ color: card.color }">{{ card.value }}</div>
            <div class="token-hint">{{ card.hint }}</div>
          </div>
        </div>
      </div>

      <div v-if="loading" class="loading-area">
        <el-skeleton :rows="6" animated />
      </div>

      <template v-else-if="!dates.length">
        <div class="empty-panel">
          <el-icon :size="36" class="empty-icon"><Document /></el-icon>
          <p>暂无 LLM 日志</p>
          <span class="empty-hint">完成写作 / 规划 / 审校等操作后，日志会出现在项目的 .llm_logs 目录</span>
        </div>
      </template>

      <template v-else-if="day">
        <div class="token-section day-token-section">
          <div class="token-section-header">
            <h2 class="token-section-title">当日 Token 用量</h2>
            <span class="token-section-meta">
              {{ day.date }} · {{ day.usage?.calls_with_usage ?? 0 }} / {{ day.usage?.calls ?? day.total }} 次有用量
            </span>
          </div>
          <div class="token-grid">
            <div class="token-card" v-for="(card, idx) in dayTokenCards" :key="'d-' + idx">
              <div class="token-label">{{ card.label }}</div>
              <div class="token-value" :style="{ color: card.color }">{{ card.value }}</div>
              <div class="token-hint">{{ card.hint }}</div>
            </div>
          </div>
        </div>

        <div class="summary-bar">
          <span class="summary-item">
            <strong>{{ day.total }}</strong> 条调用
          </span>
          <span class="summary-item">
            <strong>{{ day.groups.length }}</strong> 个阶段
          </span>
          <span class="summary-item muted">{{ day.date }}</span>
        </div>

        <div v-if="!day.groups.length" class="empty-panel compact">
          <p>该日无记录</p>
        </div>

        <el-collapse v-else v-model="openStages" class="stage-collapse">
          <el-collapse-item
            v-for="group in day.groups"
            :key="group.stage"
            :name="group.stage"
          >
            <template #title>
              <div class="stage-title">
                <span class="stage-name">{{ stageLabel(group.stage) }}</span>
                <code class="stage-key">{{ group.stage }}</code>
                <el-tag size="small" type="info" effect="plain" round>{{ group.count }}</el-tag>
              </div>
            </template>

            <div class="table-card">
              <el-table
                :data="group.entries"
                size="default"
                :header-cell-style="headerCellStyle"
                highlight-current-row
                @row-click="openEntry"
              >
                <el-table-column label="时间" width="168">
                  <template #default="{ row }">
                    <span class="mono">{{ formatTs(row.ts) }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="章" width="64" align="center">
                  <template #default="{ row }">
                    <span v-if="row.chapter != null" class="chapter-num">{{ row.chapter }}</span>
                    <span v-else class="muted">—</span>
                  </template>
                </el-table-column>
                <el-table-column label="模型" min-width="120" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span class="model-name">{{ row.model || '—' }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="Tokens" width="88" align="right">
                  <template #default="{ row }">
                    <span class="mono">{{ row.usage_total != null ? row.usage_total : '—' }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="状态" width="80" align="center">
                  <template #default="{ row }">
                    <el-tag v-if="row.has_error" size="small" type="danger" effect="light">错误</el-tag>
                    <el-tag v-else size="small" type="success" effect="light">OK</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="正文摘要" min-width="220" show-overflow-tooltip>
                  <template #default="{ row }">
                    <span class="preview">{{ row.response_preview || row.error || '（空）' }}</span>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </el-collapse-item>
        </el-collapse>
      </template>
    </template>

    <!-- Detail drawer -->
    <el-drawer
      v-model="drawerOpen"
      :title="drawerTitle"
      size="560px"
      destroy-on-close
      class="log-drawer"
    >
      <div v-if="entryLoading" class="drawer-loading">
        <el-skeleton :rows="8" animated />
      </div>
      <div v-else-if="entry" class="drawer-body">
        <div class="meta-grid">
          <div class="meta-item">
            <span class="meta-label">阶段</span>
            <span>{{ stageLabel(entry.stage) }} <code>{{ entry.stage }}</code></span>
          </div>
          <div class="meta-item">
            <span class="meta-label">时间</span>
            <span class="mono">{{ formatTs(entry.ts) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">章节</span>
            <span>{{ entry.chapter != null ? entry.chapter : '—' }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">模型</span>
            <span>{{ entry.model || '—' }}</span>
          </div>
          <div class="meta-item" v-if="entry.usage">
            <span class="meta-label">用量</span>
            <span class="mono">
              {{ entry.usage.prompt_tokens ?? '?' }}
              + {{ entry.usage.completion_tokens ?? '?' }}
              = {{ entry.usage.total_tokens ?? '?' }}
            </span>
          </div>
        </div>

        <el-alert
          v-if="entry.error"
          type="error"
          :title="entry.error"
          :closable="false"
          show-icon
          class="error-alert"
        />

        <div v-if="entry.warnings?.length" class="block">
          <h3 class="block-title">警告</h3>
          <ul class="warn-list">
            <li v-for="(w, i) in entry.warnings" :key="i">{{ w }}</li>
          </ul>
        </div>

        <div class="block body-block">
          <div class="block-title-row">
            <h3 class="block-title">正文</h3>
            <el-tag v-if="entry.response_is_json" size="small" type="info" effect="plain">
              {{ entry.body_kind === 'structured' ? '结构化提取' : 'JSON' }}
            </el-tag>
            <el-tag v-else size="small" type="success" effect="plain">散文</el-tag>
            <el-button
              v-if="entry.body"
              size="small"
              text
              class="copy-btn"
              @click="copyText(entry.body)"
            >
              复制
            </el-button>
          </div>
          <div
            v-if="entry.body"
            class="body-content"
            :class="entry.body_kind === 'prose' ? 'body-prose' : 'body-structured'"
          >{{ entry.body }}</div>
          <div v-else class="muted">（无正文）</div>
        </div>

        <el-collapse class="aux-collapse">
          <el-collapse-item title="Prompt" name="prompt">
            <div
              v-for="(m, i) in entry.prompt"
              :key="i"
              class="msg-card"
              :class="'role-' + (m.role || 'raw')"
            >
              <div class="msg-role">{{ m.role || 'raw' }}</div>
              <pre class="msg-content">{{ m.content }}</pre>
            </div>
            <div v-if="!entry.prompt.length" class="muted">（无 prompt）</div>
          </el-collapse-item>

          <el-collapse-item name="raw">
            <template #title>
              <span>原始 Response</span>
              <span class="collapse-hint">完整原始输出</span>
            </template>
            <pre class="response-block">{{ entry.response || '（空）' }}</pre>
          </el-collapse-item>

          <el-collapse-item
            v-if="Object.keys(entry.resolved_ids || {}).length"
            title="Resolved IDs"
            name="ids"
          >
            <pre class="meta-json">{{ JSON.stringify(entry.resolved_ids, null, 2) }}</pre>
          </el-collapse-item>

          <el-collapse-item
            v-if="Object.keys(entry.meta || {}).length"
            title="其它元数据"
            name="meta"
          >
            <pre class="meta-json">{{ JSON.stringify(entry.meta, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../stores/project'
import {
  getLlmLogEntry,
  getLlmLogs,
  getLlmUsage,
  listLlmLogDates,
  type LlmLogDay,
  type LlmLogEntry,
  type LlmLogSummary,
  type LlmUsageStats,
} from '../api'

const STAGE_LABELS: Record<string, string> = {
  synopsis: '全书梗概',
  volume: '分卷规划',
  planner: '章节规划',
  writer: '写作',
  revise: '改写',
  fix: '修复',
  checker: '审校',
  summarizer: '章节摘要',
  volume_recap: '分卷回顾',
  story_so_far: '故事迄今',
  entity_delta: '实体变更',
  threads: '情节线',
  enricher: '设定富化',
  style: '文风',
  macro_review: '宏观审阅',
}

const store = useProjectStore()
const dates = ref<string[]>([])
const selectedDate = ref('')
const day = ref<LlmLogDay | null>(null)
const loading = ref(false)
const openStages = ref<string[]>([])
const projectUsage = ref<LlmUsageStats | null>(null)

const drawerOpen = ref(false)
const entryLoading = ref(false)
const entry = ref<LlmLogEntry | null>(null)
const activeSummary = ref<LlmLogSummary | null>(null)

const headerCellStyle = {
  background: 'var(--rb-bg-subtle)',
  color: 'var(--rb-text-secondary)',
  fontWeight: '600',
  fontSize: '12px',
}

const drawerTitle = computed(() => {
  if (!activeSummary.value) return '日志详情'
  const s = activeSummary.value
  const label = stageLabel(s.stage)
  const ch = s.chapter != null ? ` · 第 ${s.chapter} 章` : ''
  return `${label}${ch}`
})

function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] || stage
}

function formatTokens(n: number | undefined | null): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`
  if (n >= 10_000) return `${(n / 1000).toFixed(1)}k`
  return n.toLocaleString('zh-CN')
}

function tokenCardsFrom(u: LlmUsageStats | null | undefined) {
  return [
    {
      label: '输入 Tokens',
      value: formatTokens(u?.prompt_tokens ?? 0),
      hint: 'prompt_tokens',
      color: '#0ea5e9',
    },
    {
      label: '输出 Tokens',
      value: formatTokens(u?.completion_tokens ?? 0),
      hint: 'completion_tokens',
      color: '#f59e0b',
    },
    {
      label: '汇总 Tokens',
      value: formatTokens(u?.total_tokens ?? 0),
      hint: 'total_tokens',
      color: '#6366f1',
    },
  ]
}

const projectTokenCards = computed(() => tokenCardsFrom(projectUsage.value))
const dayTokenCards = computed(() => tokenCardsFrom(day.value?.usage))

function formatTs(ts: string): string {
  if (!ts) return '—'
  // "2026-07-16T15:30:00" → "07-16 15:30:00"
  const m = ts.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}:\d{2}:\d{2})/)
  if (m) return `${m[2]}-${m[3]} ${m[4]}`
  return ts
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制正文')
  } catch {
    ElMessage.error('复制失败')
  }
}

async function onProjectChange() {
  dates.value = []
  selectedDate.value = ''
  day.value = null
  openStages.value = []
  projectUsage.value = null
  if (!store.currentId) return
  await Promise.all([loadProjectUsage(), loadDates()])
}

async function loadProjectUsage() {
  if (!store.currentId) return
  try {
    projectUsage.value = await getLlmUsage(store.currentId)
  } catch {
    projectUsage.value = null
  }
}

async function loadDates() {
  if (!store.currentId) return
  loading.value = true
  try {
    const r = await listLlmLogDates(store.currentId)
    dates.value = r.dates
    if (dates.value.length) {
      if (!selectedDate.value || !dates.value.includes(selectedDate.value)) {
        selectedDate.value = dates.value[0]
      }
      await loadDay()
    } else {
      day.value = null
    }
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '加载日志日期失败')
  } finally {
    loading.value = false
  }
}

async function loadDay() {
  if (!store.currentId || !selectedDate.value) return
  loading.value = true
  try {
    day.value = await getLlmLogs(store.currentId, selectedDate.value)
    openStages.value = day.value.groups.map((g) => g.stage)
  } catch (e: unknown) {
    day.value = null
    ElMessage.error(e instanceof Error ? e.message : '加载日志失败')
  } finally {
    loading.value = false
  }
}

async function refresh() {
  await Promise.all([loadProjectUsage(), loadDates()])
}

async function openEntry(row: LlmLogSummary) {
  if (!store.currentId || !selectedDate.value) return
  activeSummary.value = row
  drawerOpen.value = true
  entryLoading.value = true
  entry.value = null
  try {
    entry.value = await getLlmLogEntry(store.currentId, selectedDate.value, row.index)
  } catch (e: unknown) {
    ElMessage.error(e instanceof Error ? e.message : '加载详情失败')
    drawerOpen.value = false
  } finally {
    entryLoading.value = false
  }
}

onMounted(async () => {
  await store.fetchProjects()
  if (store.currentId) {
    await loadDates()
  }
})
</script>

<style scoped>
.llm-logs {
  max-width: 1200px;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: var(--rb-text-primary);
  letter-spacing: -0.02em;
}

.page-subtitle {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--rb-text-muted);
}

.page-header-right {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.project-select {
  width: 200px;
}

.date-select {
  width: 150px;
}

.token-section {
  margin-bottom: 20px;
}

.day-token-section {
  margin-bottom: 14px;
}

.token-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.token-section-title {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
  color: var(--rb-text-secondary);
}

.token-section-meta {
  font-size: 12px;
  color: var(--rb-text-muted);
}

.token-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.token-card {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 10px;
  padding: 14px 16px;
}

.token-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--rb-text-muted);
  margin-bottom: 4px;
}

.token-value {
  font-size: 22px;
  font-weight: 700;
  letter-spacing: -0.03em;
  font-variant-numeric: tabular-nums;
  line-height: 1.15;
}

.token-hint {
  margin-top: 3px;
  font-size: 11px;
  color: var(--rb-text-subtle);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.summary-bar {
  display: flex;
  gap: 20px;
  align-items: center;
  margin-bottom: 16px;
  padding: 12px 16px;
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 10px;
}

.summary-item {
  font-size: 13px;
  color: var(--rb-text-secondary);
}

.summary-item strong {
  color: var(--rb-text-primary);
  font-weight: 600;
  margin-right: 2px;
}

.summary-item.muted {
  color: var(--rb-text-muted);
  margin-left: auto;
}

.empty-panel {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 64px 24px;
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 12px;
  color: var(--rb-text-secondary);
  text-align: center;
}

.empty-panel.compact {
  padding: 32px;
}

.empty-panel p {
  margin: 0;
  font-size: 15px;
  font-weight: 500;
}

.empty-icon {
  color: var(--rb-text-subtle);
  margin-bottom: 4px;
}

.empty-hint {
  font-size: 13px;
  color: var(--rb-text-muted);
  max-width: 420px;
}

.loading-area {
  padding: 24px;
  background: var(--rb-bg-surface);
  border-radius: 12px;
  border: 1px solid var(--rb-border-light);
}

.stage-collapse {
  border: none;
  background: transparent;
}

.stage-collapse :deep(.el-collapse-item) {
  margin-bottom: 12px;
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 12px;
  overflow: hidden;
}

.stage-collapse :deep(.el-collapse-item__header) {
  height: auto;
  min-height: 48px;
  padding: 12px 16px;
  border: none;
  background: transparent;
  font-size: 14px;
}

.stage-collapse :deep(.el-collapse-item__wrap) {
  border: none;
}

.stage-collapse :deep(.el-collapse-item__content) {
  padding: 0 12px 12px;
}

.stage-title {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.stage-name {
  font-weight: 600;
  color: var(--rb-text-primary);
}

.stage-key {
  font-size: 12px;
  color: var(--rb-text-muted);
  background: var(--rb-bg-subtle);
  padding: 2px 6px;
  border-radius: 4px;
}

.table-card {
  border: 1px solid var(--rb-border-light);
  border-radius: 8px;
  overflow: hidden;
}

.table-card :deep(.el-table__row) {
  cursor: pointer;
}

.mono {
  font-variant-numeric: tabular-nums;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  color: var(--rb-text-secondary);
}

.chapter-num {
  font-weight: 600;
  font-size: 13px;
}

.model-name {
  font-size: 13px;
  color: var(--rb-text-secondary);
}

.preview {
  font-size: 13px;
  color: var(--rb-text-muted);
}

.muted {
  color: var(--rb-text-muted);
}

/* Drawer */
.drawer-loading {
  padding: 8px;
}

.drawer-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 16px;
  padding: 12px 14px;
  background: var(--rb-bg-subtle);
  border-radius: 8px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
  color: var(--rb-text-primary);
}

.meta-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--rb-text-muted);
}

.meta-item code {
  font-size: 11px;
  color: var(--rb-text-muted);
  margin-left: 4px;
}

.error-alert {
  margin: 0;
}

.block-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--rb-text-secondary);
}

.block-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.block-title-row .block-title {
  margin: 0;
}

.copy-btn {
  margin-left: auto;
}

.body-block {
  padding: 14px;
  background: var(--rb-bg-subtle);
  border: 1px solid var(--rb-border-light);
  border-radius: 10px;
}

.body-content {
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 560px;
  overflow: auto;
  color: var(--rb-text-primary);
}

.body-prose {
  font-size: 14px;
  line-height: 1.8;
  font-family: var(--rb-font);
  padding: 4px 2px;
}

.body-structured {
  font-size: 13px;
  line-height: 1.65;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 8px;
  padding: 12px;
}

.aux-collapse {
  border: none;
}

.aux-collapse :deep(.el-collapse-item__header) {
  font-size: 13px;
  font-weight: 600;
  color: var(--rb-text-secondary);
  height: 40px;
  border-bottom-color: var(--rb-border-light);
}

.aux-collapse :deep(.el-collapse-item__wrap) {
  border-bottom-color: var(--rb-border-light);
}

.collapse-hint {
  margin-left: 8px;
  font-size: 11px;
  font-weight: 400;
  color: var(--rb-text-muted);
}

.warn-list {
  margin: 0;
  padding-left: 18px;
  font-size: 13px;
  color: var(--rb-accent-amber);
}

.msg-card {
  border: 1px solid var(--rb-border-light);
  border-radius: 8px;
  margin-bottom: 8px;
  overflow: hidden;
}

.msg-role {
  padding: 4px 10px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  background: var(--rb-bg-subtle);
  color: var(--rb-text-muted);
  border-bottom: 1px solid var(--rb-border-light);
}

.msg-card.role-system .msg-role {
  color: var(--rb-accent-sky);
}

.msg-card.role-user .msg-role {
  color: var(--rb-primary);
}

.msg-card.role-assistant .msg-role {
  color: var(--rb-accent-emerald);
}

.msg-content,
.response-block,
.meta-json {
  margin: 0;
  padding: 12px;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  color: var(--rb-text-primary);
  max-height: 420px;
  overflow: auto;
  background: var(--rb-bg-surface);
}

.response-block {
  border: 1px solid var(--rb-border-light);
  border-radius: 8px;
  max-height: 520px;
}

.meta-json {
  border: 1px solid var(--rb-border-light);
  border-radius: 8px;
  background: var(--rb-bg-subtle);
  max-height: 240px;
}

@media (max-width: 640px) {
  .page-header {
    flex-direction: column;
  }
  .page-header-right {
    width: 100%;
  }
  .project-select,
  .date-select {
    width: 100%;
  }
  .token-grid {
    grid-template-columns: 1fr;
  }
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
