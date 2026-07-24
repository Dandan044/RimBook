<template>
  <section class="entity-workbench">
    <header class="page-header">
      <div>
        <p class="eyebrow">AUTHOR ROOM · FULL CODEX</p>
        <h1>完整设定集</h1>
        <p class="subtitle">作者侧六类设定与跨类关系；幕后真相不会进入已揭示设定集或 Writer 上下文。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="generatingDetails" @click="generateMissingDetails">
          <el-icon><MagicStick /></el-icon>补齐未细化详情
        </el-button>
        <el-button :loading="expanding" @click="openExpandDialog">
          <el-icon><Connection /></el-icon>继续扩展世界
        </el-button>
        <el-button :loading="syncing" @click="syncNetwork"><el-icon><Refresh /></el-icon>从剧情同步</el-button>
        <el-button type="primary" @click="createEntry"><el-icon><Plus /></el-icon>新建条目</el-button>
      </div>
    </header>

    <el-alert
      v-if="detailProgress"
      class="detail-progress"
      type="info"
      :closable="false"
      show-icon
      :title="detailProgress"
    />

    <el-tabs v-model="activeType" class="type-tabs" @tab-change="onTypeChange">
      <el-tab-pane v-for="t in typeTabs" :key="t.value" :label="t.label" :name="t.value" />
    </el-tabs>

    <div class="workbench-grid">
      <aside class="entity-roster">
        <div class="roster-head">
          <span>{{ typeLabel(activeType) }}</span>
          <el-tag size="small" effect="plain">{{ filteredEntries.length }}</el-tag>
        </div>
        <el-input v-model="search" placeholder="筛选名称、ID、标签" clearable class="entity-search">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <div class="roster-list">
          <button
            v-for="entry in filteredEntries"
            :key="entry.id"
            class="roster-item"
            :class="{ active: selectedId === entry.id }"
            @click="selectEntry(entry)"
          >
            <span class="entity-mark">{{ entry.name.slice(0, 1) }}</span>
            <span class="roster-copy">
              <strong>{{ entry.name }}</strong>
              <small>{{ entry.narrative_role || entry.surface_summary || entry.type }}</small>
            </span>
            <span v-if="entry.field_locks.length" class="lock-count"><el-icon><Lock /></el-icon>{{ entry.field_locks.length }}</span>
          </button>
          <div v-if="!filteredEntries.length" class="empty-roster">尚无条目。可先生成项目基础设定，或手动新建。</div>
        </div>
      </aside>

      <main v-if="draft" class="entity-dossier">
        <div class="dossier-top">
          <div>
            <p class="dossier-kicker">{{ draft.id || 'NEW ENTRY' }}</p>
            <el-input v-model="draft.name" class="name-input" placeholder="条目名称" />
          </div>
          <div class="dossier-actions">
            <el-tag effect="plain">{{ draft.source }}</el-tag>
            <el-button
              :disabled="isNew"
              :loading="generatingDetails"
              @click="regenerateDetail"
            >
              <el-icon><MagicStick /></el-icon>重新生成详情
            </el-button>
            <el-button text type="danger" :disabled="isNew" @click="removeEntry"><el-icon><Delete /></el-icon>删除</el-button>
            <el-button type="primary" :loading="saving" @click="saveEntry">保存</el-button>
          </div>
        </div>

        <el-form label-position="top" class="dossier-form">
          <div class="identity-row">
            <el-form-item label="稳定 ID" required><el-input v-model="draft.id" :disabled="!isNew" placeholder="如：char_linmo" /></el-form-item>
            <el-form-item label="类型">
              <el-select v-model="draft.type" :disabled="!isNew">
                <el-option v-for="t in typeTabs" :key="t.value" :label="t.label" :value="t.value" />
              </el-select>
            </el-form-item>
            <el-form-item label="已揭示关联 ID"><el-input v-model="draft.revealed_ref" placeholder="可留空；仅对齐桥接" /></el-form-item>
          </div>

          <section class="dossier-section">
            <div class="section-title"><span>通用字段</span><small>锁定后 AI 不可覆盖</small></div>
            <div class="field-grid">
              <LockableField label="叙事职责" field="narrative_role" :locked="isLocked('narrative_role')" @toggle="toggleLock"><el-input v-model="draft.narrative_role" type="textarea" :rows="2" /></LockableField>
              <LockableField label="公开面摘要" field="surface_summary" :locked="isLocked('surface_summary')" @toggle="toggleLock"><el-input v-model="draft.surface_summary" type="textarea" :rows="2" /></LockableField>
              <LockableField label="首次登场方式" field="reveal_strategy" :locked="isLocked('reveal_strategy')" @toggle="toggleLock">
                <el-input
                  v-model="draft.reveal_strategy"
                  type="textarea"
                  :rows="2"
                  placeholder="描述触发其第一次进入正文的钩子与呈现途径，不是秘密揭底。"
                />
              </LockableField>
            </div>
          </section>

          <section v-if="draft.type === 'character'" class="dossier-section">
            <div class="section-title"><span>角色结构化细节</span><small>由传记详情提炼，供规划稳定复用</small></div>
            <div class="field-grid">
              <LockableField label="深层需求" field="inner_need" :locked="isLocked('inner_need')" @toggle="toggleLock"><el-input v-model="charDetails.inner_need" type="textarea" :rows="2" /></LockableField>
              <LockableField label="恐惧" field="fear" :locked="isLocked('fear')" @toggle="toggleLock"><el-input v-model="charDetails.fear" type="textarea" :rows="2" /></LockableField>
              <LockableField label="缺陷" field="flaw" :locked="isLocked('flaw')" @toggle="toggleLock"><el-input v-model="charDetails.flaw" type="textarea" :rows="2" /></LockableField>
              <LockableField label="能力" field="capabilities" :locked="isLocked('capabilities')" @toggle="toggleLock"><el-input v-model="charDetails.capabilities" type="textarea" :rows="2" /></LockableField>
              <LockableField label="价值观" field="values" :locked="isLocked('values')" @toggle="toggleLock"><el-input v-model="charDetails.values" type="textarea" :rows="2" /></LockableField>
              <LockableField label="限制 / 盲区" field="limitations" :locked="isLocked('limitations')" @toggle="toggleLock"><el-input v-model="charDetails.limitations" type="textarea" :rows="2" /></LockableField>
              <LockableField label="声音与语言" field="voice" :locked="isLocked('voice')" @toggle="toggleLock"><el-input v-model="charDetails.voice" type="textarea" :rows="2" /></LockableField>
              <LockableField label="行动方式" field="action_style" :locked="isLocked('action_style')" @toggle="toggleLock"><el-input v-model="charDetails.action_style" type="textarea" :rows="2" /></LockableField>
            </div>
          </section>

          <section v-else class="dossier-section">
            <div class="section-title">
              <span>{{ typeLabel(draft.type) }}结构化细节</span>
              <small>JSON 对象；详情生成会自动补齐</small>
            </div>
            <el-input
              v-model="detailsJson"
              type="textarea"
              :rows="8"
              class="structured-json"
              placeholder="{ }"
            />
          </section>

          <section class="dossier-section detail-section">
            <LockableField label="详情 · 历史与底蕴" field="detail" :locked="isLocked('detail')" @toggle="toggleLock">
              <el-input
                v-model="draft.detail"
                type="textarea"
                :rows="18"
                placeholder="从起源、经历与因果写起，让设定成为有时间厚度的真实存在。支持 Markdown。"
              />
            </LockableField>
            <p class="field-help">详情可以很长；世界观默认作为所有设定的上游背景，显式关系会参与生成上下文。</p>
          </section>

          <section class="dossier-section secret-section">
            <LockableField label="幕后真相" field="secret_truth" :locked="isLocked('secret_truth')" @toggle="toggleLock">
              <el-input v-model="draft.secret_truth" type="textarea" :rows="3" placeholder="仅供策划；不会注入 Writer 上下文。" />
            </LockableField>
          </section>
        </el-form>
      </main>

      <main v-else class="empty-dossier">
        <el-icon><Connection /></el-icon>
        <h2>完整设定集 ≠ 已揭示设定集</h2>
        <p>这里记录已真实存在但尚未进入正文的设定、秘密与历史底蕴。</p>
        <el-button type="primary" @click="createEntry">新建第一条设定</el-button>
      </main>
    </div>

    <section class="relationship-panel">
      <div class="relationship-head">
        <div>
          <p class="eyebrow">CROSS-TYPE GRAPH</p>
          <h2>跨类关系网</h2>
        </div>
        <div class="relationship-actions">
          <el-radio-group v-model="relationView" size="small">
            <el-radio-button value="graph">网状图</el-radio-button>
            <el-radio-button value="list">关系列表</el-radio-button>
          </el-radio-group>
          <el-button :disabled="entries.length < 2" @click="createRelationship">
            <el-icon><Plus /></el-icon>新增关系
          </el-button>
        </div>
      </div>

      <EntityNetworkGraph
        v-if="relationView === 'graph' && store.currentId"
        ref="graphRef"
        :project-id="store.currentId"
        :focus-id="graphFocusId || undefined"
        @select-node="onGraphSelectNode"
        @select-edge="onGraphSelectEdge"
        @pane-click="onGraphPaneClick"
      />

      <div v-else-if="relationships.length" class="relationship-list">
        <article
          v-for="relationship in relationships"
          :key="relationship.id"
          class="relationship-card"
          @click="editRelationship(relationship)"
        >
          <div class="relationship-path">
            <strong>{{ entryName(relSource(relationship)) }}</strong>
            <el-icon><Right /></el-icon>
            <strong>{{ entryName(relTarget(relationship)) }}</strong>
          </div>
          <el-tag size="small" effect="plain">{{ relationship.relationship_type }}</el-tag>
          <p>{{ relationship.conflict || relationship.stakes || relationship.status || '待定义张力' }}</p>
        </article>
      </div>
      <div v-else class="relationship-empty">暂无关系。可跨角色/地点/势力/物品等类别关联。</div>
    </section>

    <el-dialog v-model="expandDialog" title="继续扩展真实世界" width="560px" destroy-on-close>
      <p class="expand-hint">
        从已完成详情中挖掘隐含相关存在，自动建档、写详情并补关系。系数 1 不扩展；系数越高，递归越深、预算越大。
      </p>
      <el-radio-group v-model="expandCoefficient" class="expand-options">
        <el-radio-button :value="2">2 · 邻域（约 +12）</el-radio-button>
        <el-radio-button :value="3">3 · 区域（约 +28）</el-radio-button>
        <el-radio-button :value="4">4 · 宏大（约 +55）</el-radio-button>
      </el-radio-group>
      <el-alert
        v-if="expandCoefficient === 4"
        type="warning"
        :closable="false"
        title="宏大世界会显著增加模型调用与时间。"
        style="margin-top: 12px"
      />
      <template #footer>
        <el-button @click="expandDialog = false" :disabled="expanding">取消</el-button>
        <el-button type="primary" :loading="expanding" @click="runExpand">开始扩展</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="relationshipDialog" :title="relationshipEditing ? '编辑关系' : '新建关系'" width="620px" destroy-on-close>
      <el-form v-if="relationshipDraft" label-position="top">
        <div class="identity-row">
          <el-form-item label="关系 ID"><el-input v-model="relationshipDraft.id" :disabled="relationshipEditing" /></el-form-item>
          <el-form-item label="关系类型"><el-input v-model="relationshipDraft.relationship_type" /></el-form-item>
        </div>
        <div class="identity-row">
          <el-form-item label="起点">
            <el-select v-model="relationshipDraft.source_entity_id" filterable>
              <el-option v-for="e in entries" :key="e.id" :label="`${e.name} [${e.type}]`" :value="e.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标">
            <el-select v-model="relationshipDraft.target_entity_id" filterable>
              <el-option v-for="e in entries" :key="e.id" :label="`${e.name} [${e.type}]`" :value="e.id" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="冲突 / 张力"><el-input v-model="relationshipDraft.conflict" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="relationshipEditing" type="danger" text @click="removeRelationship">删除</el-button>
        <el-button @click="relationshipDialog = false">取消</el-button>
        <el-button type="primary" @click="saveRelationship">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { ElIcon, ElMessage, ElMessageBox } from 'element-plus'
import { Lock, Unlock } from '@element-plus/icons-vue'
import { useProjectStore } from '../stores/project'
import EntityNetworkGraph from '../components/EntityNetworkGraph.vue'
import {
  addEntityRelationship, addPlanningEntry, deleteEntityRelationship, deletePlanningEntry,
  expandPlanningWorldSSE, generateMissingPlanningDetailsSSE, generatePlanningEntryDetailSSE,
  getPlanningEntityNetwork, listPlanningEntries, setPlanningEntityFieldLock,
  syncPlanningEntityNetwork, updateEntityRelationship, updatePlanningEntry,
  type EntityRelationship, type PlanningCodexEntry, type PlanSSEHandle,
} from '../api'

const LockableField = defineComponent({
  props: { label: String, field: String, locked: Boolean },
  emits: ['toggle'],
  setup(props, { emit, slots }) {
    return () => h('div', { class: ['lockable-field', { 'is-locked': props.locked }] }, [
      h('div', { class: 'lockable-label' }, [
        h('span', { class: 'lockable-label-text' }, props.label),
        h('button', {
          class: { 'field-lock': true, active: props.locked },
          type: 'button',
          title: props.locked ? '已锁定，AI 不可覆盖 · 点击取消' : '锁定此字段，防止 AI 覆盖',
          'aria-label': props.locked ? '取消字段锁定' : '锁定字段',
          'aria-pressed': String(!!props.locked),
          onClick: () => emit('toggle', props.field),
        }, [
          h(ElIcon, { class: 'field-lock-icon', size: 13 }, () => h(props.locked ? Lock : Unlock)),
          h('span', { class: 'field-lock-text' }, props.locked ? '锁定' : '保护'),
        ]),
      ]),
      slots.default?.(),
    ])
  },
})

const typeTabs = [
  { value: 'character', label: '角色' },
  { value: 'worldbuilding', label: '世界观' },
  { value: 'location', label: '地点' },
  { value: 'faction', label: '势力' },
  { value: 'item', label: '物品' },
  { value: 'timeline', label: '时间线' },
]

const store = useProjectStore()
const entries = ref<PlanningCodexEntry[]>([])
const relationships = ref<EntityRelationship[]>([])
const activeType = ref('character')
const selectedId = ref('')
/** Graph neighborhood focus; cleared on blank-canvas click without wiping dossier selection. */
const graphFocusId = ref('')
const draft = ref<PlanningCodexEntry | null>(null)
const charDetails = reactive({
  inner_need: '',
  fear: '',
  flaw: '',
  capabilities: '',
  values: '',
  limitations: '',
  voice: '',
  action_style: '',
})
const detailsJson = ref('{}')
const search = ref('')
const saving = ref(false)
const syncing = ref(false)
const generatingDetails = ref(false)
const expanding = ref(false)
const expandDialog = ref(false)
const expandCoefficient = ref(2)
const detailProgress = ref('')
let detailSse: PlanSSEHandle | null = null
const relationshipDialog = ref(false)
const relationshipEditing = ref(false)
const relationshipDraft = ref<EntityRelationship | null>(null)
const relationView = ref<'graph' | 'list'>('graph')
const graphRef = ref<{ reload: () => Promise<void> } | null>(null)

const filteredEntries = computed(() => {
  const ofType = entries.value.filter(e => e.type === activeType.value)
  const keyword = search.value.trim().toLowerCase()
  return keyword
    ? ofType.filter(e => `${e.id} ${e.name} ${e.tags.join(' ')}`.toLowerCase().includes(keyword))
    : ofType
})
const isNew = computed(() => !selectedId.value)

function typeLabel(t: string) {
  return typeTabs.find(x => x.value === t)?.label || t
}
function blankEntry(): PlanningCodexEntry {
  return {
    id: '', name: '', type: activeType.value, aliases: [], tags: [], relationship_refs: [],
    revealed_ref: '', surface_summary: '', secret_truth: '', narrative_role: '',
    reveal_strategy: '', detail: '', volume_roles: {},
    field_locks: [], source: 'manual', updated_at: '', details: {}, body: '',
  }
}
function blankRelationship(): EntityRelationship {
  return {
    id: '', source_entity_id: entries.value[0]?.id || '', target_entity_id: entries.value[1]?.id || '',
    relationship_type: 'related', tags: [], status: '', source_goal: '', target_goal: '',
    stakes: '', conflict: '', secret: '', arc: { start: '', current: '', destination: '' },
    field_locks: [], source: 'manual', updated_at: '',
  }
}
function copy<T>(v: T): T { return JSON.parse(JSON.stringify(v)) }
function entryName(id: string) { return entries.value.find(e => e.id === id)?.name || id }
function relSource(r: EntityRelationship) { return r.source_id || r.source_entity_id }
function relTarget(r: EntityRelationship) { return r.target_id || r.target_entity_id }
function isLocked(field: string) { return !!draft.value?.field_locks.includes(field) }

function syncCharDetailsFromDraft() {
  const d = (draft.value?.details || {}) as Record<string, string>
  charDetails.inner_need = d.inner_need || ''
  charDetails.fear = d.fear || ''
  charDetails.flaw = d.flaw || ''
  charDetails.capabilities = d.capabilities || ''
  charDetails.values = d.values || ''
  charDetails.limitations = d.limitations || ''
  charDetails.voice = d.voice || ''
  charDetails.action_style = d.action_style || ''
  detailsJson.value = JSON.stringify(draft.value?.details || {}, null, 2)
}

watch(charDetails, () => {
  if (!draft.value || draft.value.type !== 'character') return
  draft.value.details = {
    ...draft.value.details,
    inner_need: charDetails.inner_need,
    fear: charDetails.fear,
    flaw: charDetails.flaw,
    capabilities: charDetails.capabilities,
    values: charDetails.values,
    limitations: charDetails.limitations,
    voice: charDetails.voice,
    action_style: charDetails.action_style,
  }
}, { deep: true })

async function loadNetwork() {
  if (!store.currentId) return
  try {
    const [list, network] = await Promise.all([
      listPlanningEntries(store.currentId),
      getPlanningEntityNetwork(store.currentId),
    ])
    entries.value = list.length ? list : (network.entries || [])
    relationships.value = network.relationships.map(r => ({
      ...r,
      source_entity_id: r.source_id || r.source_entity_id,
      target_entity_id: r.target_id || r.target_entity_id,
    }))
    const selected = entries.value.find(e => e.id === selectedId.value)
    if (selected) { draft.value = copy(selected); syncCharDetailsFromDraft() }
    await nextTick()
    await graphRef.value?.reload()
  } catch { ElMessage.error('无法读取完整设定集') }
}

function onGraphSelectNode(id: string) {
  const entry = entries.value.find(item => item.id === id)
  if (!entry) return
  activeType.value = entry.type
  graphFocusId.value = id
  selectEntry(entry)
}

function onGraphSelectEdge(id: string) {
  const relationship = relationships.value.find(item => item.id === id)
  if (relationship) editRelationship(relationship)
}

/** Clear graph focus only; keep left-panel dossier selection for editing. */
function onGraphPaneClick() {
  graphFocusId.value = ''
}

function openExpandDialog() {
  expandDialog.value = true
}

async function runExpand() {
  if (!store.currentId || expanding.value || generatingDetails.value) return
  expandDialog.value = false
  expanding.value = true
  detailProgress.value = '准备扩展真实世界…'
  try {
    await new Promise<void>((resolve, reject) => {
      detailSse?.close()
      detailSse = expandPlanningWorldSSE(store.currentId, expandCoefficient.value, {
        onProgress: (message: string) => { detailProgress.value = message },
        onStep: (data) => {
          detailProgress.value = String(data.message || detailProgress.value)
        },
        onError: (message: string) => reject(new Error(message)),
        onDone: () => resolve(),
      })
    })
    await loadNetwork()
    ElMessage.success(`世界扩展完成（系数 ${expandCoefficient.value}）`)
  } catch (error: any) {
    ElMessage.error(error?.message || '世界扩展失败')
  } finally {
    expanding.value = false
    detailProgress.value = ''
    detailSse = null
  }
}

function onTypeChange() {
  selectedId.value = ''
  graphFocusId.value = ''
  draft.value = null
}
function selectEntry(entry: PlanningCodexEntry) {
  selectedId.value = entry.id
  graphFocusId.value = entry.id
  draft.value = copy(entry)
  syncCharDetailsFromDraft()
}
function createEntry() {
  selectedId.value = ''
  graphFocusId.value = ''
  draft.value = blankEntry()
  syncCharDetailsFromDraft()
}
async function saveEntry() {
  if (!store.currentId || !draft.value?.id || !draft.value.name.trim()) {
    ElMessage.warning('请填写稳定 ID 和名称'); return
  }
  saving.value = true
  try {
    if (draft.value.type !== 'character') {
      const parsed = JSON.parse(detailsJson.value || '{}')
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
        throw new Error('结构化细节必须是 JSON 对象')
      }
      draft.value.details = parsed
    }
    const saved = isNew.value
      ? await addPlanningEntry(store.currentId, draft.value)
      : await updatePlanningEntry(store.currentId, draft.value)
    const index = entries.value.findIndex(e => e.id === saved.id)
    if (index >= 0) entries.value[index] = saved; else entries.value.push(saved)
    selectedId.value = saved.id
    graphFocusId.value = saved.id
    draft.value = copy(saved)
    syncCharDetailsFromDraft()
    ElMessage.success('设定条目已保存')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || error?.message || '保存失败')
  } finally { saving.value = false }
}
async function removeEntry() {
  if (!store.currentId || !draft.value || isNew.value) return
  try {
    await ElMessageBox.confirm(`删除「${draft.value.name}」也会删除关联关系，是否继续？`, '删除条目', { type: 'warning' })
    await deletePlanningEntry(store.currentId, draft.value.id)
    selectedId.value = ''
    graphFocusId.value = ''
    draft.value = null
    await loadNetwork()
    ElMessage.success('已删除')
  } catch { /* cancelled */ }
}
async function toggleLock(field: string) {
  if (!store.currentId || !draft.value || isNew.value) {
    ElMessage.info('请先保存条目，再锁定字段'); return
  }
  const locked = !isLocked(field)
  try {
    await setPlanningEntityFieldLock(store.currentId, draft.value.id, 'entry', field, locked)
    draft.value.field_locks = locked
      ? [...draft.value.field_locks, field]
      : draft.value.field_locks.filter(x => x !== field)
  } catch { ElMessage.error('字段锁更新失败') }
}
async function syncNetwork() {
  if (!store.currentId) return
  syncing.value = true
  try {
    const result = await syncPlanningEntityNetwork(store.currentId)
    await loadNetwork()
    ElMessage.success(`同步完成：${result.change_count || 0} 项变更`)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '同步失败')
  } finally { syncing.value = false }
}

function runDetailStream(start: (handlers: any) => PlanSSEHandle) {
  if (generatingDetails.value) return
  generatingDetails.value = true
  detailProgress.value = '准备细化详情…'
  return new Promise<void>((resolve, reject) => {
    detailSse?.close()
    detailSse = start({
      onProgress: (message: string) => {
        detailProgress.value = message
      },
      onStep: (data: { message?: string; entry_type?: string; completed?: number; total?: number }) => {
        detailProgress.value = data.message || detailProgress.value
      },
      onError: (message: string) => reject(new Error(message)),
      onDone: () => resolve(),
    })
  }).finally(() => {
    generatingDetails.value = false
    detailProgress.value = ''
    detailSse = null
  })
}

async function regenerateDetail() {
  if (!store.currentId || !draft.value || isNew.value) return
  const entryId = draft.value.id
  try {
    await runDetailStream(handlers =>
      generatePlanningEntryDetailSSE(store.currentId, entryId, handlers),
    )
    await loadNetwork()
    const refreshed = entries.value.find(entry => entry.id === entryId)
    if (refreshed) selectEntry(refreshed)
    ElMessage.success('详情已重新生成并保存')
  } catch (error: any) {
    ElMessage.error(error?.message || '详情生成失败')
  }
}

async function generateMissingDetails() {
  if (!store.currentId) return
  try {
    await runDetailStream(handlers =>
      generateMissingPlanningDetailsSSE(store.currentId, handlers, true),
    )
    await loadNetwork()
    ElMessage.success('未细化条目已按世界观到物品的顺序补齐')
  } catch (error: any) {
    ElMessage.error(error?.message || '详情生成失败')
  }
}
function createRelationship() {
  relationshipEditing.value = false
  relationshipDraft.value = blankRelationship()
  relationshipDialog.value = true
}
function editRelationship(value: EntityRelationship) {
  relationshipEditing.value = true
  relationshipDraft.value = copy({
    ...value,
    source_entity_id: relSource(value),
    target_entity_id: relTarget(value),
  })
  relationshipDialog.value = true
}
async function saveRelationship() {
  if (!store.currentId || !relationshipDraft.value?.id) {
    ElMessage.warning('请填写关系 ID'); return
  }
  const payload = {
    ...relationshipDraft.value,
    source_id: relationshipDraft.value.source_entity_id,
    target_id: relationshipDraft.value.target_entity_id,
  }
  try {
    const saved = relationshipEditing.value
      ? await updateEntityRelationship(store.currentId, payload)
      : await addEntityRelationship(store.currentId, payload)
    await loadNetwork()
    relationshipDialog.value = false
    ElMessage.success('关系已保存')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail || '关系保存失败')
  }
}
async function removeRelationship() {
  if (!store.currentId || !relationshipDraft.value) return
  try {
    await deleteEntityRelationship(store.currentId, relationshipDraft.value.id)
    relationshipDialog.value = false
    await loadNetwork()
    ElMessage.success('关系已删除')
  } catch { ElMessage.error('删除失败') }
}
onMounted(loadNetwork)
onUnmounted(() => detailSse?.close())
</script>

<style scoped>
.entity-workbench { max-width: 1480px; margin: 0 auto; padding-bottom: 28px; color: var(--rb-text-primary); }
.page-header, .relationship-head, .dossier-top { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; }
.page-header { margin-bottom: 12px; }.eyebrow, .dossier-kicker { margin: 0 0 6px; color: var(--rb-primary); font: 700 11px/1.2 ui-monospace, monospace; letter-spacing: .12em; }.page-header h1 { margin: 0; font-size: 30px; letter-spacing: -.04em; }.subtitle { margin: 8px 0 0; color: var(--rb-text-secondary); }.header-actions, .dossier-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.detail-progress { margin-bottom: 12px; }
.type-tabs { margin-bottom: 12px; }
.workbench-grid { display: grid; grid-template-columns: 286px minmax(0, 1fr); min-height: 620px; gap: 16px; }.entity-roster, .entity-dossier, .empty-dossier, .relationship-panel { border: 1px solid var(--rb-border-light); border-radius: 14px; background: var(--rb-bg-surface); box-shadow: 0 1px 2px rgba(0,0,0,.04); }.entity-roster { display: flex; flex-direction: column; overflow: hidden; }.roster-head { display: flex; justify-content: space-between; padding: 17px 16px 10px; font-weight: 700; }.entity-search { padding: 0 12px 12px; box-sizing: border-box; }.roster-list { padding: 6px; overflow: auto; flex: 1; }.roster-item { border: 0; width: 100%; background: transparent; text-align: left; display: flex; align-items: center; padding: 10px; gap: 10px; border-radius: 10px; cursor: pointer; color: inherit; }.roster-item:hover { background: var(--rb-bg-subtle); }.roster-item.active { background: var(--rb-primary-bg); }.entity-mark { width: 31px; height: 31px; display: grid; place-items: center; border-radius: 9px; background: var(--rb-bg-subtle); color: var(--rb-primary); font-weight: 700; }.active .entity-mark { background: var(--rb-primary); color: #fff; }.roster-copy { min-width: 0; flex: 1; display: grid; gap: 3px; }.roster-copy strong, .roster-copy small { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }.roster-copy small, .lock-count { color: var(--rb-text-muted); font-size: 12px; }.lock-count { display: flex; align-items: center; gap: 3px; }.empty-roster, .relationship-empty { padding: 28px 18px; color: var(--rb-text-muted); font-size: 13px; line-height: 1.7; text-align: center; }
.entity-dossier { padding: 22px 26px; overflow: auto; }.dossier-top { border-bottom: 1px solid var(--rb-border-light); padding-bottom: 18px; }.name-input :deep(input) { padding: 0; height: 38px; border: 0; background: transparent; font-size: 28px; font-weight: 700; letter-spacing: -.04em; box-shadow: none; }.dossier-form { padding-top: 18px; }.identity-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }.dossier-section { padding: 18px 0; border-top: 1px solid var(--rb-border-light); }.section-title { display: flex; align-items: baseline; gap: 10px; margin-bottom: 14px; font-weight: 700; }.section-title small { color: var(--rb-text-muted); font-size: 12px; font-weight: 400; }.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }:deep(.lockable-label) {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  color: var(--rb-text-secondary);
  margin-bottom: 7px;
}
:deep(.lockable-label-text) { min-width: 0; }
:deep(.field-lock) {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  flex-shrink: 0;
  height: 26px;
  margin: -3px 0;
  padding: 0 12px 0 9px;
  border: 1px solid var(--rb-border);
  border-radius: 999px;
  background: var(--rb-bg-surface);
  color: var(--rb-text-secondary);
  font: 600 11px/1 var(--rb-font);
  letter-spacing: .03em;
  cursor: pointer;
  box-shadow: 0 1px 0 rgba(0, 0, 0, .04);
  transition:
    color var(--rb-transition-fast),
    background var(--rb-transition-fast),
    border-color var(--rb-transition-fast),
    box-shadow var(--rb-transition-fast),
    transform var(--rb-transition-fast);
}
:deep(.field-lock:hover) {
  border-color: var(--rb-border-strong, var(--rb-border));
  background: var(--rb-bg-subtle);
  color: var(--rb-text);
}
:deep(.field-lock:focus-visible) {
  outline: 2px solid color-mix(in srgb, var(--rb-primary) 45%, transparent);
  outline-offset: 1px;
}
:deep(.field-lock:active) { transform: scale(.97); }
:deep(.field-lock.active) {
  border-color: color-mix(in srgb, var(--rb-primary) 35%, transparent);
  background: var(--rb-primary);
  color: #fff;
  box-shadow: 0 1px 2px color-mix(in srgb, var(--rb-primary) 35%, transparent);
}
:deep(.field-lock.active:hover),
:deep(.lockable-field.is-locked:hover .field-lock.active) {
  background: var(--rb-primary-dark, var(--rb-primary));
  border-color: transparent;
}
:deep(.field-lock-icon) { display: flex; }
:deep(.field-lock-text) { user-select: none; }
:deep(.lockable-field.is-locked .el-textarea__inner),
:deep(.lockable-field.is-locked .el-input__wrapper) {
  background: color-mix(in srgb, var(--rb-primary-bg) 55%, var(--rb-bg-surface));
  box-shadow: inset 2px 0 0 var(--rb-primary-light);
}.detail-section { position: relative; }.detail-section :deep(textarea) { line-height: 1.8; font-family: var(--rb-font); }.field-help { margin: 9px 0 0; color: var(--rb-text-muted); font-size: 12px; line-height: 1.6; }.structured-json :deep(textarea) { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; line-height: 1.55; }.secret-section { background: color-mix(in srgb, var(--rb-primary-bg) 35%, transparent); margin: 0 -10px; padding: 16px 10px; border-radius: 10px; }.empty-dossier { display: grid; place-content: center; text-align: center; padding: 40px; }.empty-dossier :deep(.el-icon) { font-size: 42px; color: var(--rb-primary); margin: auto; }.empty-dossier h2 { margin: 15px 0 7px; }.empty-dossier p { color: var(--rb-text-secondary); margin: 0 0 18px; }
.relationship-panel { margin-top: 16px; padding: 20px; }.relationship-head h2 { margin: 0; font-size: 20px; }.relationship-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }.relationship-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 10px; margin-top: 15px; }.relationship-card { border: 1px solid var(--rb-border-light); border-radius: 10px; padding: 14px; cursor: pointer; transition: .15s ease; }.relationship-card:hover { border-color: var(--rb-primary); transform: translateY(-1px); }.relationship-path { display: flex; align-items: center; gap: 7px; margin-bottom: 9px; }.relationship-card p { min-height: 40px; margin: 10px 0; line-height: 1.5; color: var(--rb-text-secondary); font-size: 13px; }.expand-hint { margin: 0 0 14px; color: var(--rb-text-secondary); line-height: 1.6; }.expand-options { display: flex; flex-wrap: wrap; gap: 8px; }
@media (max-width: 900px) { .workbench-grid { grid-template-columns: 1fr; }.entity-roster { max-height: 260px; }.identity-row, .field-grid { grid-template-columns: 1fr; }.page-header, .dossier-top { flex-direction: column; }.entity-dossier { padding: 18px; } }
</style>
