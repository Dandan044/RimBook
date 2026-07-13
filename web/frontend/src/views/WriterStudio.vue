<template>
  <div class="writer-studio">
    <!-- Top toolbar -->
    <div class="writer-topbar">
      <div class="topbar-left">
        <h1 class="page-title-inline">
          <el-icon class="title-icon"><EditPen /></el-icon>
          写作
        </h1>
        <el-select v-model="chapterNum" placeholder="选择章节" class="chapter-select" @change="loadChapter">
          <el-option v-for="c in chapterList" :key="c.number" :label="`第${c.number}章 ${c.title}`" :value="c.number" />
        </el-select>
      </div>
      <div class="topbar-right">
        <div class="action-group">
          <el-button type="primary" @click="doWrite" :loading="writing" :disabled="!chapterNum">
            <el-icon><VideoPlay /></el-icon> 生成正文
          </el-button>
          <el-button @click="doCheck" :loading="checking" :disabled="!draftText">
            <el-icon><CircleCheck /></el-icon> 校验
          </el-button>
          <el-button @click="showRevise = true" :disabled="!draftText">
            <el-icon><EditPen /></el-icon> 修订
          </el-button>
          <el-button @click="doSummary" :loading="summarizing" :disabled="!draftText">
            <el-icon><Refresh /></el-icon> 摘要
          </el-button>
          <el-button @click="saveDraft" :disabled="!draftText">
            <el-icon><DocumentChecked /></el-icon> 保存
          </el-button>
        </div>
        <transition name="progress-fade">
          <el-tag v-if="progressMsg" type="info" effect="plain" class="progress-tag">
            <el-icon class="is-loading"><Loading /></el-icon>
            {{ progressMsg }}
          </el-tag>
        </transition>
      </div>
    </div>

    <!-- Mobile/Tablet context collapsible -->
    <el-collapse v-model="contextCollapsed" class="context-collapse-mobile">
      <el-collapse-item title="上下文" name="context">
        <div class="context-collapse-actions">
          <el-button size="small" @click="loadContext" :disabled="!chapterNum">预览</el-button>
        </div>
        <div v-if="contextText" class="context-text">{{ contextText }}</div>
        <div v-else class="empty-hint">点击「预览」查看投喂给 LLM 的上下文</div>
      </el-collapse-item>
    </el-collapse>

    <div class="writer-body" :class="bodyExpandClass">
      <!-- Left: context panel -->
      <div class="panel-context" :class="{ 'is-expanded': expandedPanel === 'context' }">
        <div class="panel-card context-card">
          <div class="panel-header">
            <span class="panel-title">
              <el-icon><View /></el-icon> 上下文
            </span>
            <div class="panel-header-actions">
              <el-button size="small" text @click="loadContext" :disabled="!chapterNum">
                <el-icon><Refresh /></el-icon> 预览
              </el-button>
              <el-button size="small" text @click="contextViewMode = contextViewMode === 'structured' ? 'raw' : 'structured'" :disabled="!contextText">
                {{ contextViewMode === 'structured' ? '原始' : '结构化' }}
              </el-button>
              <button class="expand-btn" @click="toggleExpand('context')" :title="expandedPanel === 'context' ? '收起' : '展开'">
                <svg v-if="expandedPanel === 'context'" viewBox="0 0 16 16" fill="none" class="expand-icon"><path d="M4 1h11v11M1 4l11-3M12 15H1V4M15 12L4 15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
                <svg v-else viewBox="0 0 16 16" fill="none" class="expand-icon"><path d="M1 5V1h4M15 11v4h-4M1 1l5 5M15 15l-5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </button>
            </div>
          </div>
          <div class="panel-content">
            <div v-if="contextText && contextViewMode === 'structured'" class="context-structured">
              <div v-for="(sec, i) in structuredSections" :key="i" class="context-section" :class="{ collapsed: collapsedSections.has(i) }">
                <div class="context-section-header" @click="toggleSection(i)">
                  <span class="section-label">{{ sec.label }}</span>
                  <span class="section-tokens">~{{ sec.tokens }} tokens</span>
                </div>
                <div v-if="!collapsedSections.has(i)" class="context-section-body">
                  <!-- Codex: entity cards with full info -->
                  <template v-if="sec.key === 'codex' && sec.entities?.length">
                    <div v-for="ent in sec.entities" :key="ent.id" class="entity-card" :class="{ placeholder: ent.is_placeholder }">
                      <div class="entity-card-header">
                        <el-tag size="small" effect="dark" :type="ent.is_placeholder ? 'warning' : 'primary'">{{ ent.type_label }}</el-tag>
                        <span class="entity-card-name">{{ ent.name }}</span>
                        <code class="entity-card-id">{{ ent.id }}</code>
                        <el-tag v-if="ent.is_placeholder" size="small" type="warning" effect="plain">占位符</el-tag>
                      </div>
                      <div v-if="ent.aliases?.length" class="entity-card-aliases">
                        别名：<el-tag v-for="a in ent.aliases" :key="a" size="small" effect="plain">{{ a }}</el-tag>
                      </div>
                      <div v-if="ent.body" class="entity-card-body" v-html="renderMarkdown(ent.body)"></div>
                      <div v-else class="entity-card-empty">（档案待补：此实体由系统自动创建，暂无静态档案。）</div>
                      <div v-if="ent.revelations?.length" class="entity-card-revelations">
                        <div class="entity-sub-header">📖 章节发现</div>
                        <div v-for="r in ent.revelations" :key="r.chapter" class="entity-sub-item rev-item">
                          <span class="rev-chapter">第{{ r.chapter }}章</span>
                          <span class="rev-content">{{ r.content }}</span>
                        </div>
                      </div>
                      <div v-if="ent.contradictions?.length" class="entity-card-contradictions">
                        <div class="entity-sub-header">⚠️ 待审核矛盾</div>
                        <div v-for="c in ent.contradictions" :key="c.chapter" class="entity-sub-item con-item" :class="{ resolved: c.resolved }">
                          <el-tag size="small" :type="c.resolved ? 'success' : 'danger'" effect="plain">{{ c.resolved ? '已解决' : '未解决' }}</el-tag>
                          <span class="con-chapter">第{{ c.chapter }}章</span>
                          <span class="con-desc">{{ c.description }}</span>
                          <div v-if="c.evidence" class="con-evidence">证据：{{ c.evidence }}</div>
                        </div>
                      </div>
                    </div>
                  </template>

                  <!-- Entity state: state cards -->
                  <template v-else-if="sec.key === 'entity_state' && sec.sub_items?.length">
                    <div v-for="st in sec.sub_items" :key="st.entity_id" class="state-card">
                      <div class="state-card-header">
                        <code>{{ st.entity_id }}</code>
                        <span v-if="st.status" class="state-status">{{ st.status }}</span>
                        <span v-if="st.location" class="state-location">📍 {{ st.location }}</span>
                      </div>
                      <div v-if="st.last_seen_chapter" class="state-meta">
                        最后出现：第{{ st.last_seen_chapter }}章
                      </div>
                      <div v-if="st.knowledge?.length" class="state-list">
                        <div class="state-list-label">已知信息：</div>
                        <ul>
                          <li v-for="(k, ki) in st.knowledge" :key="ki">{{ k }}</li>
                        </ul>
                      </div>
                      <div v-if="st.possessions?.length" class="state-list">
                        <div class="state-list-label">随身物品：</div>
                        <ul>
                          <li v-for="(p, pi) in st.possessions" :key="pi">{{ p }}</li>
                        </ul>
                      </div>
                      <div v-if="st.relationships && Object.keys(st.relationships).length" class="state-list">
                        <div class="state-list-label">人际关系：</div>
                        <ul>
                          <li v-for="(v, k) in st.relationships" :key="k">{{ k }}（{{ v }}）</li>
                        </ul>
                      </div>
                    </div>
                  </template>

                  <!-- Summaries: chapter summary cards -->
                  <template v-else-if="sec.key === 'summaries' && sec.sub_items?.length">
                    <div v-for="s in sec.sub_items" :key="s.chapter" class="summary-card">
                      <span class="summary-chapter">第{{ s.chapter }}章</span>
                      <span class="summary-text">{{ s.text }}</span>
                    </div>
                  </template>

                  <!-- Beat: formatted beat info -->
                  <template v-else-if="sec.key === 'beat'">
                    <div class="section-preview">{{ sec.text }}</div>
                  </template>

                  <!-- Other sections: full text -->
                  <template v-else>
                    <div class="section-preview">{{ sec.text }}</div>
                  </template>
                </div>
              </div>
            </div>
            <div v-else-if="contextText" class="context-text">{{ contextText }}</div>
            <div v-else class="panel-empty">
              <el-icon :size="28" class="panel-empty-icon"><View /></el-icon>
              <span>点击「预览」查看上下文</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Center: draft editor -->
      <div class="panel-draft" :class="{ 'is-expanded': expandedPanel === 'draft' }">
        <div class="panel-card draft-card">
          <div class="panel-header">
            <span class="panel-title">
              <el-icon><EditPen /></el-icon> 第{{ chapterNum || '?' }}章正文
            </span>
            <div class="panel-header-actions draft-header-controls">
              <div class="font-size-control">
                <button class="fs-btn" @click="setDraftFontSize(13)" :class="{ active: draftFontSize === 13 }" title="小字号">A<small>-</small></button>
                <button class="fs-btn" @click="setDraftFontSize(16)" :class="{ active: draftFontSize === 16 }" title="标准字号">A</button>
                <button class="fs-btn" @click="setDraftFontSize(19)" :class="{ active: draftFontSize === 19 }" title="大字号">A<small>+</small></button>
                <button class="fs-btn" @click="setDraftFontSize(22)" :class="{ active: draftFontSize === 22 }" title="超大字号">A<small>++</small></button>
              </div>
              <span class="word-count" v-if="draftText">{{ draftText.length }} 字</span>
              <button class="expand-btn" @click="toggleExpand('draft')" :title="expandedPanel === 'draft' ? '收起' : '展开'">
                <svg v-if="expandedPanel === 'draft'" viewBox="0 0 16 16" fill="none" class="expand-icon"><path d="M4 1h11v11M1 4l11-3M12 15H1V4M15 12L4 15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
                <svg v-else viewBox="0 0 16 16" fill="none" class="expand-icon"><path d="M1 5V1h4M15 11v4h-4M1 1l5 5M15 15l-5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </button>
            </div>
          </div>
          <div class="panel-content draft-content" :style="{ '--draft-font-size': draftFontSize + 'px' }">
            <el-input
              v-model="draftText"
              type="textarea"
              :rows="28"
              placeholder="章节正文将显示在这里…"
              class="draft-editor"
            />
          </div>
        </div>
      </div>

      <!-- Right: check + beat -->
      <div class="panel-check" :class="{ 'is-expanded': expandedPanel === 'check' }">
        <!-- Check report -->
        <div class="panel-card check-card">
          <div class="panel-header">
            <span class="panel-title">
              <el-icon><CircleCheck /></el-icon> 校验报告
            </span>
            <button class="expand-btn" @click="toggleExpand('check')" :title="expandedPanel === 'check' ? '收起' : '展开'">
              <svg v-if="expandedPanel === 'check'" viewBox="0 0 16 16" fill="none" class="expand-icon"><path d="M4 1h11v11M1 4l11-3M12 15H1V4M15 12L4 15" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              <svg v-else viewBox="0 0 16 16" fill="none" class="expand-icon"><path d="M1 5V1h4M15 11v4h-4M1 1l5 5M15 15l-5-5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </button>
          </div>
          <div class="panel-content">
            <template v-if="checkReport">
              <div class="check-summary">
                <el-tag
                  :type="checkReport.overall === '通过' ? 'success' : checkReport.overall === '严重问题' ? 'danger' : 'warning'"
                  size="large"
                  effect="dark"
                >
                  {{ checkReport.overall }}
                </el-tag>
                <span class="check-summary-text">{{ checkReport.summary }}</span>
              </div>
              <div v-if="checkReport.issues?.length" class="issues-list">
                <div v-for="(iss, i) in checkReport.issues" :key="i" class="issue-item">
                  <div class="issue-row">
                    <el-tag :type="sevColor(iss.severity)" size="small" effect="plain">{{ iss.severity }}</el-tag>
                    <el-tag size="small" type="info" effect="plain">{{ iss.category }}</el-tag>
                  </div>
                  <p class="issue-desc">{{ iss.description }}</p>
                  <div v-if="iss.suggestion" class="issue-suggestion">
                    <el-icon><Sunny /></el-icon>
                    {{ iss.suggestion }}
                  </div>
                </div>
              </div>
              <div v-else class="panel-empty" style="padding: 20px 0;">
                <el-icon :size="24" style="color: #10b981;"><CircleCheckFilled /></el-icon>
                <span style="color: #10b981; font-weight: 500;">无问题，一切正常！</span>
              </div>
            </template>
            <div v-else class="panel-empty">
              <el-icon :size="28" class="panel-empty-icon"><CircleCheck /></el-icon>
              <span>点击「校验」查看一致性报告</span>
            </div>
          </div>
        </div>

        <!-- Enrichment result -->
        <div class="panel-card enrich-card" v-if="enrichmentResult">
          <div class="panel-header">
            <span class="panel-title">
              <el-icon><MagicStick /></el-icon> 设定集扩充
            </span>
          </div>
          <div class="panel-content">
            <p class="enrich-summary">{{ enrichmentResult.summary }}</p>
            <div v-if="enrichmentResult.created?.length" class="enrich-group">
              <span class="enrich-label enrich-label--new">新增实体</span>
              <div v-for="c in enrichmentResult.created" :key="c.id" class="enrich-item">
                <el-tag size="small" type="success" effect="plain">{{ c.id }}</el-tag>
                <span class="enrich-detail">{{ c.detail }}</span>
              </div>
            </div>
            <div v-if="enrichmentResult.updated?.length" class="enrich-group">
              <span class="enrich-label enrich-label--update">更新档案</span>
              <div v-for="c in enrichmentResult.updated" :key="c.id" class="enrich-item">
                <el-tag size="small" type="primary" effect="plain">{{ c.id }}</el-tag>
                <span class="enrich-detail">{{ c.detail }}</span>
              </div>
            </div>
            <div v-if="enrichmentResult.contradictions?.length" class="enrich-group">
              <span class="enrich-label enrich-label--warn">待审核矛盾</span>
              <div v-for="c in enrichmentResult.contradictions" :key="c.id" class="enrich-item">
                <el-tag size="small" type="danger" effect="plain">{{ c.id }}</el-tag>
                <span class="enrich-detail">{{ c.detail }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Chapter beat summary -->
        <div class="panel-card beat-card" v-if="expandedPanel !== 'check'">
          <div class="panel-header">
            <span class="panel-title">
              <el-icon><List /></el-icon> 本章 Beat
            </span>
          </div>
          <div class="panel-content">
            <template v-if="currentBeat">
              <div v-for="(b, i) in currentBeat.beats" :key="i" class="beat-summary-item">
                <div class="beat-scene-tag">场景{{ i + 1 }}</div>
                <div class="beat-scene-body">
                  <strong>{{ b.goal }}</strong>
                  <span v-if="b.conflict" class="beat-conflict">（冲突：{{ b.conflict }}）</span>
                </div>
              </div>
              <div v-if="currentBeat.summary" class="beat-summary">
                <div class="beat-summary-label">摘要</div>
                <p>{{ currentBeat.summary }}</p>
              </div>
            </template>
            <div v-else class="panel-empty">
              <el-icon :size="28" class="panel-empty-icon"><List /></el-icon>
              <span>选择章节查看 Beat</span>
            </div>
          </div>
        </div>

        <!-- Expanded check: beat becomes a section inside the expanded panel -->
        <div class="panel-card beat-card beat-expanded" v-if="expandedPanel === 'check'">
          <div class="panel-header">
            <span class="panel-title">
              <el-icon><List /></el-icon> 本章 Beat
            </span>
          </div>
          <div class="panel-content">
            <template v-if="currentBeat">
              <div v-for="(b, i) in currentBeat.beats" :key="i" class="beat-summary-item">
                <div class="beat-scene-tag">场景{{ i + 1 }}</div>
                <div class="beat-scene-body">
                  <strong>{{ b.goal }}</strong>
                  <span v-if="b.conflict" class="beat-conflict">（冲突：{{ b.conflict }}）</span>
                </div>
              </div>
              <div v-if="currentBeat.summary" class="beat-summary">
                <div class="beat-summary-label">摘要</div>
                <p>{{ currentBeat.summary }}</p>
              </div>
            </template>
            <div v-else class="panel-empty">
              <el-icon :size="28" class="panel-empty-icon"><List /></el-icon>
              <span>选择章节查看 Beat</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Revise dialog -->
    <el-dialog v-model="showRevise" title="修订章节" width="500px">
      <el-input v-model="reviseInstructions" type="textarea" :rows="5" placeholder="输入修订要求…" />
      <template #footer>
        <el-button @click="showRevise = false">取消</el-button>
        <el-button type="primary" @click="doRevise" :loading="revising">修订</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useProjectStore } from '../stores/project'
import {
  listChapters, getDraft, updateDraft, previewContext,
  checkChapter, reviseChapter, regenerateSummary,
  writeChapterSSE, getWriteStatus,
  type ChapterOutline, type CheckIssue,
} from '../api'
import { ElMessage } from 'element-plus'
import { marked } from 'marked'

const store = useProjectStore()
const chapterNum = ref<number | null>(null)
const chapterList = ref<ChapterOutline[]>([])
const draftText = ref('')
const contextText = ref('')
const contextViewMode = ref<'raw' | 'structured'>('structured')
const collapsedSections = ref(new Set<number>())
// Structured sections from API (data-driven, not parsed)
interface EntitySubInfo {
  id: string; name: string; type: string; type_label: string
  aliases: string[]; body: string
  revelations: { chapter: number; content: string; source: string }[]
  contradictions: { chapter: number; description: string; evidence: string; resolved: boolean }[]
  is_placeholder: boolean
}
interface SectionData {
  key: string; label: string; text: string; tokens: number
  entities?: EntitySubInfo[]
  sub_items?: Record<string, any>[]
}
const contextSections = ref<SectionData[]>([])
const currentBeat = ref<ChapterOutline | null>(null)
const checkReport = ref<{ overall: string; summary: string; issues: CheckIssue[] } | null>(null)
const enrichmentResult = ref<{ created: { id: string; detail: string }[]; updated: { id: string; detail: string }[]; contradictions: { id: string; detail: string }[]; summary: string } | null>(null)

const writing = ref(false)
const checking = ref(false)
const summarizing = ref(false)
const revising = ref(false)
const progressMsg = ref('')

const showRevise = ref(false)
const reviseInstructions = ref('')

const contextCollapsed = ref<string[]>([])

// ===== Panel expand/collapse =====
const expandedPanel = ref<'context' | 'draft' | 'check' | null>(null)

const bodyExpandClass = computed(() => {
  if (!expandedPanel.value) return ''
  return `expand-${expandedPanel.value}`
})

function toggleExpand(panel: 'context' | 'draft' | 'check') {
  expandedPanel.value = expandedPanel.value === panel ? null : panel
}

// ESC to collapse
function onKeyDown(e: KeyboardEvent) {
  if (e.key === 'Escape' && expandedPanel.value) {
    expandedPanel.value = null
  }
}
onMounted(() => {
  document.addEventListener('keydown', onKeyDown)
})
onUnmounted(() => {
  document.removeEventListener('keydown', onKeyDown)
})

// ===== Draft font size =====
const FONT_SIZE_KEY = 'rimbook-draft-font-size'
const draftFontSize = ref(16)

function setDraftFontSize(size: number) {
  draftFontSize.value = size
  try { localStorage.setItem(FONT_SIZE_KEY, String(size)) } catch {}
}

// Restore saved font size
try {
  const saved = localStorage.getItem(FONT_SIZE_KEY)
  if (saved) draftFontSize.value = Number(saved) || 16
} catch {}

function sevColor(s: string) {
  return s === 'high' ? 'danger' : s === 'medium' ? 'warning' : 'info'
}

// Structured context view — data-driven from API section_list
interface ContextSection { label: string; text: string; tokens: number; sub?: ContextSection[]; entities?: EntitySubInfo[]; sub_items?: Record<string, any>[]; key: string }

const structuredSections = computed<ContextSection[]>(() => {
  if (!contextSections.value.length) return []
  return contextSections.value.map(sec => ({
    key: sec.key,
    label: sec.label,
    text: sec.text,
    tokens: sec.tokens,
    entities: sec.entities,
    sub_items: sec.sub_items,
    sub: (sec.entities || sec.sub_items) ? [] : undefined,
  }))
})
function renderMarkdown(text: string): string {
  if (!text) return ''
  try { return marked.parse(text) as string } catch { return text }
}
function toggleSection(i: number) { collapsedSections.value.has(i) ? collapsedSections.value.delete(i) : collapsedSections.value.add(i) }

async function fetchChapterList() {
  if (!store.currentId) return
  chapterList.value = await listChapters(store.currentId)
  // Auto-select the latest chapter on load
  if (chapterList.value.length > 0 && !chapterNum.value) {
    const latest = chapterList.value.reduce((a, b) => a.number > b.number ? a : b)
    chapterNum.value = latest.number
    loadChapter()
  }
}

async function loadChapter() {
  if (!store.currentId || !chapterNum.value) return
  checkReport.value = null
  contextText.value = ''
  const [draft, ch] = await Promise.all([
    getDraft(store.currentId, chapterNum.value),
    listChapters(store.currentId),
  ])
  draftText.value = draft.text || ''
  currentBeat.value = ch.find(c => c.number === chapterNum.value) || null
}

async function loadContext() {
  if (!store.currentId || !chapterNum.value) return
  try {
    const r = await previewContext(store.currentId, chapterNum.value) as any
    contextText.value = r.text
    contextSections.value = r.section_list || []
  } catch (e: any) { ElMessage.error('预览失败') }
}

async function doWrite() {
  if (!store.currentId || !chapterNum.value) return
  writing.value = true
  progressMsg.value = '连接中…'
  checkReport.value = null

  // Register in store so navigation away doesn't lose track.
  store.startWriteTracking(chapterNum.value)

  // Use SSE for streaming progress
  const es = writeChapterSSE(store.currentId, chapterNum.value, {
    onProgress: (msg) => {
      progressMsg.value = msg
      store.writeTasks[chapterNum.value!] = {
        ...store.writeTasks[chapterNum.value!],
        progress: msg,
      }
    },
    onContext: (data) => { contextText.value = (data as any).preview || '' },
    onDraft: async (data) => {
      const d = data as any
      draftText.value = '' // will reload below
      progressMsg.value = '草稿已生成'
    },
    onCheck: (data) => {
      checkReport.value = data as any
    },
    onEnrichment: (data) => {
      enrichmentResult.value = data as any
    },
    onError: (msg) => {
      ElMessage.error(msg)
      store.stopWriteTracking(chapterNum.value!)
    },
    onDone: async () => {
      writing.value = false
      progressMsg.value = ''
      store.stopWriteTracking(chapterNum.value!)
      await loadChapter()
      ElMessage.success('生成完成')
    },
  })
}

async function doCheck() {
  if (!store.currentId || !chapterNum.value) return
  checking.value = true
  try {
    checkReport.value = await checkChapter(store.currentId, chapterNum.value, false)
    ElMessage.success('校验完成')
  } catch (e: any) { ElMessage.error('校验失败') }
  finally { checking.value = false }
}

async function doRevise() {
  if (!store.currentId || !chapterNum.value) return
  revising.value = true
  try {
    await reviseChapter(store.currentId, chapterNum.value, reviseInstructions.value)
    ElMessage.success('修订完成')
    showRevise.value = false
    await loadChapter()
  } catch (e: any) { ElMessage.error('修订失败') }
  finally { revising.value = false }
}

async function doSummary() {
  if (!store.currentId || !chapterNum.value) return
  summarizing.value = true
  try {
    const r = await regenerateSummary(store.currentId, chapterNum.value)
    ElMessage.success('摘要已更新')
  } catch (e: any) { ElMessage.error('生成摘要失败') }
  finally { summarizing.value = false }
}

async function saveDraft() {
  if (!store.currentId || !chapterNum.value) return
  await updateDraft(store.currentId, chapterNum.value, draftText.value)
  ElMessage.success('草稿已保存')
}

onMounted(fetchChapterList)

// Check for active writes when entering this page (may have navigated away and back).
async function checkActiveWrite() {
  if (!store.currentId || !chapterNum.value) return
  const num = chapterNum.value
  try {
    const s = await getWriteStatus(store.currentId, num)
    if (s.active) {
      writing.value = true
      progressMsg.value = s.progress
      store.startWriteTracking(num)
      // Poll until done.
      const poll = setInterval(async () => {
        try {
          const st = await getWriteStatus(store.currentId!, num)
          if (st.active) {
            progressMsg.value = st.progress
          } else {
            clearInterval(poll)
            writing.value = false
            progressMsg.value = ''
            store.stopWriteTracking(num)
            await loadChapter()
            if (st.draft_exists) {
              ElMessage.success('生成完成（已在后台完成）')
            }
          }
        } catch { /* keep polling */ }
      }, 3000)
    }
  } catch { /* ignore */ }
}

// Run check when chapter changes.
watch(chapterNum, () => {
  if (chapterNum.value) checkActiveWrite()
})
// Also check on first mount.
onMounted(() => {
  if (chapterNum.value) checkActiveWrite()
})
</script>

<style scoped>
.writer-studio {
  height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
}

/* ===== Top Bar ===== */
.writer-topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.topbar-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.page-title-inline {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--rb-text-primary);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  white-space: nowrap;
}

.title-icon {
  color: var(--rb-primary);
  font-size: 22px;
}

.chapter-select {
  min-width: 180px;
}

.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.action-group {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.progress-tag {
  animation: pulse-opacity 1.5s ease-in-out infinite;
}

@keyframes pulse-opacity {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.progress-fade-enter-active,
.progress-fade-leave-active {
  transition: opacity 0.2s ease;
}
.progress-fade-enter-from,
.progress-fade-leave-to {
  opacity: 0;
}

/* ===== Mobile context collapsible ===== */
.context-collapse-mobile {
  display: none;
  margin-bottom: 12px;
  flex-shrink: 0;
}

.context-collapse-actions {
  margin-bottom: 8px;
}

/* ===== Three-column body ===== */
.writer-body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 14px;
}

/* ---- Normal (no expand) ---- */
.panel-context {
  flex: 0 0 25%;
  max-width: 25%;
  min-width: 0;
  transition: flex 0.35s cubic-bezier(0.4, 0, 0.2, 1),
              max-width 0.35s cubic-bezier(0.4, 0, 0.2, 1),
              opacity 0.25s ease;
  overflow: hidden;
}

.panel-draft {
  flex: 1;
  min-width: 0;
  transition: flex 0.35s cubic-bezier(0.4, 0, 0.2, 1),
              max-width 0.35s cubic-bezier(0.4, 0, 0.2, 1),
              opacity 0.25s ease;
  overflow: hidden;
}

.panel-check {
  flex: 0 0 27%;
  max-width: 27%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  overflow-y: auto;
  transition: flex 0.35s cubic-bezier(0.4, 0, 0.2, 1),
              max-width 0.35s cubic-bezier(0.4, 0, 0.2, 1),
              opacity 0.25s ease;
}

/* ---- Expand states ---- */
/* When a panel is expanded, siblings shrink to 0 */
.writer-body.expand-context .panel-draft,
.writer-body.expand-context .panel-check,
.writer-body.expand-draft .panel-context,
.writer-body.expand-draft .panel-check,
.writer-body.expand-check .panel-context,
.writer-body.expand-check .panel-draft {
  flex: 0 0 0%;
  max-width: 0;
  opacity: 0;
  overflow: hidden;
  pointer-events: none;
}

/* The expanded panel takes all space */
.writer-body.expand-context .panel-context,
.writer-body.expand-draft .panel-draft,
.writer-body.expand-check .panel-check {
  flex: 1 1 100%;
  max-width: 100%;
}

/* Expanded panel gets a subtle highlight border */
.panel-context.is-expanded .panel-card,
.panel-draft.is-expanded .panel-card,
.panel-check.is-expanded .panel-card:first-child {
  border-color: var(--rb-primary-bg-hover);
  box-shadow: 0 0 0 1px var(--rb-primary-bg-hover), 0 4px 20px rgba(99, 102, 241, 0.08);
}

/* ===== Expand Button ===== */
.expand-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--rb-text-muted);
  cursor: pointer;
  transition: all 0.15s ease;
  flex-shrink: 0;
  padding: 0;
}

.expand-btn:hover {
  background: var(--rb-bg-base);
  color: var(--rb-primary);
}

.expand-icon {
  width: 15px;
  height: 15px;
}

.panel-header-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

/* ===== Panel Cards ===== */
.panel-card {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  display: flex;
  flex-direction: column;
  transition: border-color 0.25s ease, box-shadow 0.25s ease;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 18px;
  border-bottom: 1px solid var(--rb-border-light);
  flex-shrink: 0;
  background: var(--rb-bg-subtle);
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--rb-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.panel-title .el-icon {
  font-size: 14px;
  color: var(--rb-primary);
}

.word-count {
  font-size: 12px;
  font-weight: 500;
  color: var(--rb-text-muted);
  background: var(--rb-bg-base);
  padding: 2px 8px;
  border-radius: 999px;
  font-variant-numeric: tabular-nums;
}

/* Font size control */
.draft-header-controls {
  display: flex;
  align-items: center;
  gap: 10px;
}

.font-size-control {
  display: flex;
  align-items: center;
  gap: 2px;
  background: var(--rb-bg-base);
  border-radius: 8px;
  padding: 2px;
}

.fs-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 26px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--rb-text-muted);
  cursor: pointer;
  font-family: var(--rb-font);
  font-weight: 600;
  font-size: 13px;
  transition: all 0.12s ease;
  position: relative;
}

.fs-btn small {
  font-size: 9px;
  font-weight: 700;
  margin-left: 1px;
  vertical-align: super;
}

.fs-btn:hover {
  background: var(--rb-border-light);
  color: var(--rb-text-primary);
}

.fs-btn.active {
  background: var(--rb-primary);
  color: #ffffff;
  box-shadow: 0 1px 3px rgba(99, 102, 241, 0.3);
}

.fs-btn.active small {
  color: #ffffff;
}

.panel-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px 18px;
  min-height: 0;
}

.panel-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 32px 16px;
  color: var(--rb-text-muted);
  font-size: 13px;
  text-align: center;
}

.panel-empty-icon {
  color: var(--rb-text-subtle);
}

/* Context panel */
.context-card {
  height: 100%;
}

.context-text {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.7;
  color: var(--rb-text-primary);
  letter-spacing: -0.005em;
}

/* Draft panel */
.draft-card {
  height: 100%;
}

.draft-content {
  padding: 0 !important;
}

.draft-editor :deep(textarea) {
  font-size: var(--draft-font-size, 16px);
  line-height: 1.9;
  font-family: var(--rb-font);
  border: none !important;
  box-shadow: none !important;
  border-radius: 0 !important;
  padding: 20px 24px;
  min-height: 100%;
  resize: none;
  background: transparent;
  color: var(--rb-text-primary);
  letter-spacing: 0.01em;
  transition: font-size 0.2s ease;
}

.draft-editor :deep(textarea:focus) {
  box-shadow: none !important;
}

/* Check panel */
.check-card {
  flex: 1;
  min-height: 0;
}

.check-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--rb-border-light);
}

.check-summary-text {
  font-size: 13px;
  font-weight: 500;
  color: var(--rb-text-secondary);
}

.issues-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.issue-item {
  padding: 12px;
  background: var(--rb-bg-subtle);
  border-radius: 8px;
  border: 1px solid var(--rb-border-light);
}

.issue-row {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}

.issue-desc {
  font-size: 13px;
  color: var(--rb-text-primary);
  margin: 0;
  line-height: 1.5;
}

.issue-suggestion {
  display: flex;
  align-items: flex-start;
  gap: 4px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--rb-border-light);
  color: var(--rb-primary);
  font-size: 12px;
  line-height: 1.5;
}

.issue-suggestion .el-icon {
  font-size: 14px;
  flex-shrink: 0;
  margin-top: 1px;
}

/* Beat panel */
.beat-card {
  flex-shrink: 0;
}

.beat-expanded {
  flex: 1;
  min-height: 0;
}

.beat-summary-item {
  padding: 10px 12px;
  margin-bottom: 8px;
  background: var(--rb-bg-subtle);
  border-radius: 8px;
  border: 1px solid var(--rb-border-light);
}

.beat-scene-tag {
  font-size: 11px;
  font-weight: 600;
  color: var(--rb-primary);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 4px;
}

.beat-scene-body {
  font-size: 13px;
  line-height: 1.5;
  color: var(--rb-text-primary);
}

.beat-scene-body strong {
  font-weight: 600;
}

.beat-conflict {
  color: var(--rb-text-secondary);
  font-size: 12px;
}

.beat-summary {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--rb-border-light);
}

.beat-summary-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--rb-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 6px;
}

.beat-summary p {
  font-size: 13px;
  color: var(--rb-text-secondary);
  line-height: 1.6;
  margin: 0;
}

/* ===== Responsive: Tablet ===== */
@media (max-width: 991px) {
  .panel-context {
    display: none;
  }
  .context-collapse-mobile {
    display: block;
  }
  .panel-draft {
    flex: 0 0 58%;
  }
  .panel-check {
    flex: 0 0 42%;
    max-width: 42%;
  }
  /* Allow expand to work even on tablet for the two visible panels */
  .writer-body.expand-draft .panel-check,
  .writer-body.expand-check .panel-draft {
    flex: 0 0 0%;
    max-width: 0;
    opacity: 0;
  }
  .writer-body.expand-draft .panel-draft,
  .writer-body.expand-check .panel-check {
    flex: 1 1 100%;
    max-width: 100%;
  }
}

/* ===== Responsive: Mobile ===== */
@media (max-width: 767px) {
  .writer-topbar {
    flex-direction: column;
    align-items: flex-start;
  }
  .topbar-right {
    width: 100%;
  }
  .action-group {
    width: 100%;
  }
  .action-group .el-button {
    flex: 1;
    min-width: 0;
    font-size: 12px;
  }
  .writer-body {
    flex-direction: column;
  }
  .panel-context {
    display: none;
  }
  .context-collapse-mobile {
    display: block;
  }
  .panel-draft {
    flex: none;
    max-width: 100%;
  }
  .panel-check {
    flex: none;
    max-width: 100%;
  }
  .draft-editor :deep(textarea) {
    min-height: 300px;
  }
}

/* Structured context */
.context-structured { display: flex; flex-direction: column; gap: 8px; }
.context-section { border: 1px solid var(--rb-border-light); border-radius: 8px; overflow: hidden; }
.context-section.collapsed { opacity: 0.5; }
.context-section-header { display: flex; justify-content: space-between; align-items: center; padding: 9px 14px; background: var(--rb-bg-subtle); cursor: pointer; user-select: none; font-size: 13px; font-weight: 600; }
.context-section-header:hover { background: var(--rb-primary-bg); }
.section-label { color: var(--rb-text-primary); font-size: 13px; }
.section-tokens { font-size: 11px; color: var(--rb-text-muted); background: var(--rb-bg-surface); padding: 2px 8px; border-radius: 10px; font-weight: 500; flex-shrink: 0; }
.context-section-body { padding: 10px 14px; font-size: 12px; line-height: 1.7; color: var(--rb-text-secondary); background: var(--rb-bg-surface); max-height: 400px; overflow-y: auto; }
.section-preview { white-space: pre-wrap; word-break: break-word; }

/* Entity cards (codex section) */
.entity-card { border: 1px solid var(--rb-border-light); border-radius: 8px; padding: 12px; margin-bottom: 10px; background: var(--rb-bg-subtle); }
.entity-card:last-child { margin-bottom: 0; }
.entity-card.placeholder { border-color: #e6a23c66; background: #fdf6ec; }
.entity-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; flex-wrap: wrap; }
.entity-card-name { font-weight: 700; font-size: 14px; color: var(--rb-text-primary); }
.entity-card-id { font-size: 11px; color: var(--rb-text-muted); background: var(--rb-bg-base); padding: 1px 6px; border-radius: 4px; font-family: monospace; }
.entity-card-aliases { display: flex; align-items: center; gap: 4px; margin-bottom: 8px; flex-wrap: wrap; font-size: 12px; color: var(--rb-text-muted); }
.entity-card-body { font-size: 12px; line-height: 1.7; color: var(--rb-text-primary); margin-bottom: 8px; }
.entity-card-body :deep(h3) { font-size: 13px; margin: 8px 0 4px; }
.entity-card-body :deep(h4) { font-size: 12px; margin: 6px 0 4px; }
.entity-card-body :deep(ul) { padding-left: 18px; margin: 4px 0; }
.entity-card-body :deep(li) { margin-bottom: 2px; }
.entity-card-empty { font-size: 12px; color: var(--rb-text-muted); font-style: italic; margin-bottom: 8px; }
.entity-sub-header { font-size: 11px; font-weight: 600; color: var(--rb-text-secondary); margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.03em; }
.entity-sub-item { font-size: 12px; padding: 4px 0; border-bottom: 1px solid #f0f0f0; }
.entity-sub-item:last-child { border-bottom: none; }
.entity-card-revelations, .entity-card-contradictions { margin-top: 8px; padding-top: 8px; border-top: 1px solid var(--rb-border-light); }
.rev-item { display: flex; gap: 6px; }
.rev-chapter { font-weight: 600; color: var(--rb-primary); white-space: nowrap; flex-shrink: 0; }
.rev-content { color: var(--rb-text-secondary); }
.con-item { display: flex; align-items: flex-start; gap: 6px; flex-wrap: wrap; }
.con-item.resolved { opacity: 0.6; }
.con-chapter { font-weight: 600; white-space: nowrap; flex-shrink: 0; }
.con-desc { color: var(--rb-text-primary); }
.con-evidence { font-size: 11px; color: var(--rb-text-muted); width: 100%; padding-left: 4px; margin-top: 2px; }

/* State cards */
.state-card { border: 1px solid var(--rb-border-light); border-radius: 8px; padding: 10px; margin-bottom: 8px; background: var(--rb-bg-subtle); }
.state-card:last-child { margin-bottom: 0; }
.state-card-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap; }
.state-card-header code { font-size: 12px; color: var(--rb-primary); background: var(--rb-primary-bg); padding: 2px 6px; border-radius: 4px; }
.state-status { font-size: 12px; font-weight: 500; color: var(--rb-text-primary); }
.state-location { font-size: 11px; color: var(--rb-text-muted); }
.state-meta { font-size: 11px; color: var(--rb-text-muted); margin-bottom: 4px; }
.state-list { margin-bottom: 4px; }
.state-list-label { font-size: 11px; font-weight: 600; color: var(--rb-text-secondary); }
.state-list ul { padding-left: 16px; margin: 2px 0; }
.state-list li { font-size: 12px; color: var(--rb-text-primary); line-height: 1.5; }

/* Summary cards */
.summary-card { display: flex; gap: 8px; padding: 6px 0; border-bottom: 1px solid #f5f5f5; }
.summary-card:last-child { border-bottom: none; }
.summary-chapter { font-weight: 600; color: var(--rb-primary); white-space: nowrap; flex-shrink: 0; font-size: 12px; }
.summary-text { font-size: 12px; color: var(--rb-text-secondary); line-height: 1.5; }
</style>
