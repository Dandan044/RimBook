<template>
  <section class="entity-workbench">
    <header class="page-header">
      <div>
        <p class="eyebrow">AUTHOR ROOM · PRIVATE</p>
        <h1>幕后实体网络</h1>
        <p class="subtitle">在卷规划之前管理动机、弧线与关系张力；这里的秘密不会进入读者向设定集。</p>
      </div>
      <div class="header-actions">
        <el-button :loading="syncing" @click="syncNetwork"><el-icon><Refresh /></el-icon>从剧情同步</el-button>
        <el-button type="primary" @click="createEntity"><el-icon><Plus /></el-icon>新建实体</el-button>
      </div>
    </header>

    <div class="workbench-grid">
      <aside class="entity-roster">
        <div class="roster-head">
          <span>出场实体</span>
          <el-tag size="small" effect="plain">{{ entities.length }}</el-tag>
        </div>
        <el-input v-model="search" placeholder="筛选名称、ID、标签" clearable class="entity-search">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <div class="roster-list">
          <button
            v-for="entity in filteredEntities"
            :key="entity.id"
            class="roster-item"
            :class="{ active: selectedId === entity.id }"
            @click="selectEntity(entity)"
          >
            <span class="entity-mark">{{ entity.name.slice(0, 1) }}</span>
            <span class="roster-copy">
              <strong>{{ entity.name }}</strong>
              <small>{{ entity.story_role || entity.kind || '待定义职责' }}</small>
            </span>
            <span v-if="entity.field_locks.length" class="lock-count"><el-icon><Lock /></el-icon>{{ entity.field_locks.length }}</span>
          </button>
          <div v-if="!filteredEntities.length" class="empty-roster">尚无实体。可先同步已有剧情，或手动建立第一张幕后卡。</div>
        </div>
      </aside>

      <main v-if="draft" class="entity-dossier">
        <div class="dossier-top">
          <div>
            <p class="dossier-kicker">{{ draft.id || 'NEW ENTITY' }}</p>
            <el-input v-model="draft.name" class="name-input" placeholder="实体名称" />
          </div>
          <div class="dossier-actions">
            <el-tag effect="plain">{{ draft.source }}</el-tag>
            <el-button text type="danger" :disabled="isNew" @click="removeEntity"><el-icon><Delete /></el-icon>删除</el-button>
            <el-button type="primary" :loading="saving" @click="saveEntity">保存档案</el-button>
          </div>
        </div>

        <el-form label-position="top" class="dossier-form">
          <div class="identity-row">
            <el-form-item label="稳定 ID" required><el-input v-model="draft.id" :disabled="!isNew" placeholder="如：hero_linmo" /></el-form-item>
            <el-form-item label="实体类型"><el-input v-model="draft.kind" placeholder="人类、AI、精怪、非人叙事主体…" /></el-form-item>
            <el-form-item label="关联 Codex ID"><el-input v-model="draft.codex_ref" placeholder="可留空；仅作对齐桥接" /></el-form-item>
          </div>

          <section class="dossier-section">
            <div class="section-title"><span>驱动力</span><small>这些字段将约束后续 beat 的行为因果</small></div>
            <div class="field-grid">
              <LockableField label="剧情职责" field="story_role" :locked="isLocked('story_role')" @toggle="toggleEntityLock"><el-input v-model="draft.story_role" type="textarea" :rows="2" /></LockableField>
              <LockableField label="表层目标" field="surface_goal" :locked="isLocked('surface_goal')" @toggle="toggleEntityLock"><el-input v-model="draft.surface_goal" type="textarea" :rows="2" /></LockableField>
              <LockableField label="深层需求" field="inner_need" :locked="isLocked('inner_need')" @toggle="toggleEntityLock"><el-input v-model="draft.inner_need" type="textarea" :rows="2" /></LockableField>
              <LockableField label="恐惧 / 代价" field="fear" :locked="isLocked('fear')" @toggle="toggleEntityLock"><el-input v-model="draft.fear" type="textarea" :rows="2" /></LockableField>
              <LockableField label="价值观" field="values" :locked="isLocked('values')" @toggle="toggleEntityLock"><el-input v-model="draft.values" type="textarea" :rows="2" /></LockableField>
              <LockableField label="致命缺陷" field="flaw" :locked="isLocked('flaw')" @toggle="toggleEntityLock"><el-input v-model="draft.flaw" type="textarea" :rows="2" /></LockableField>
            </div>
          </section>

          <section class="dossier-section">
            <div class="section-title"><span>演出与弧线</span><small>字段锁定后，自动同步只能读取，不能改写</small></div>
            <div class="field-grid">
              <LockableField label="能力 / 资源" field="capabilities" :locked="isLocked('capabilities')" @toggle="toggleEntityLock"><el-input v-model="draft.capabilities" type="textarea" :rows="2" /></LockableField>
              <LockableField label="限制 / 盲区" field="limitations" :locked="isLocked('limitations')" @toggle="toggleEntityLock"><el-input v-model="draft.limitations" type="textarea" :rows="2" /></LockableField>
              <LockableField label="声音与语言" field="voice" :locked="isLocked('voice')" @toggle="toggleEntityLock"><el-input v-model="draft.voice" type="textarea" :rows="2" /></LockableField>
              <LockableField label="行动方式" field="action_style" :locked="isLocked('action_style')" @toggle="toggleEntityLock"><el-input v-model="draft.action_style" type="textarea" :rows="2" /></LockableField>
            </div>
            <div class="arc-strip">
              <LockableField label="弧线起点" field="arc" :locked="isLocked('arc')" @toggle="toggleEntityLock"><el-input v-model="draft.arc.start" /></LockableField>
              <el-icon class="arc-arrow"><Right /></el-icon>
              <LockableField label="当前阶段" field="arc" :locked="isLocked('arc')" @toggle="toggleEntityLock"><el-input v-model="draft.arc.current" /></LockableField>
              <el-icon class="arc-arrow"><Right /></el-icon>
              <LockableField label="预期终点" field="arc" :locked="isLocked('arc')" @toggle="toggleEntityLock"><el-input v-model="draft.arc.destination" /></LockableField>
            </div>
          </section>

          <section class="dossier-section secret-section">
            <LockableField label="幕后秘密 / 误导意图" field="secret" :locked="isLocked('secret')" @toggle="toggleEntityLock">
              <el-input v-model="draft.secret" type="textarea" :rows="3" placeholder="仅供策划；不会自动注入正文写作上下文。" />
            </LockableField>
          </section>
        </el-form>
      </main>

      <main v-else class="empty-dossier">
        <el-icon><Connection /></el-icon>
        <h2>实体不是读者档案</h2>
        <p>它记录的是角色尚未说出口的欲望、恐惧与选择压力。</p>
        <el-button type="primary" @click="createEntity">建立第一张幕后卡</el-button>
      </main>
    </div>

    <section class="relationship-panel">
      <div class="relationship-head">
        <div><p class="eyebrow">TENSION MAP</p><h2>关系张力</h2></div>
        <el-button :disabled="entities.length < 2" @click="createRelationship"><el-icon><Plus /></el-icon>新增关系</el-button>
      </div>
      <div v-if="relationships.length" class="relationship-list">
        <article v-for="relationship in relationships" :key="relationship.id" class="relationship-card" @click="editRelationship(relationship)">
          <div class="relationship-path">
            <strong>{{ entityName(relationship.source_entity_id) }}</strong><el-icon><Right /></el-icon><strong>{{ entityName(relationship.target_entity_id) }}</strong>
          </div>
          <el-tag size="small" effect="plain">{{ relationship.relationship_type }}</el-tag>
          <p>{{ relationship.conflict || relationship.stakes || relationship.status || '待定义张力' }}</p>
          <small>{{ relationship.arc.current || '关系尚未标注阶段' }}</small>
        </article>
      </div>
      <div v-else class="relationship-empty">暂无关系。请为至少两名实体定义他们彼此想从对方身上得到什么。</div>
    </section>

    <el-dialog v-model="relationshipDialog" :title="relationshipDraft?.id ? '编辑关系' : '新建关系'" width="620px" destroy-on-close>
      <el-form v-if="relationshipDraft" label-position="top" class="relationship-form">
        <div class="identity-row"><el-form-item label="关系 ID"><el-input v-model="relationshipDraft.id" :disabled="relationshipEditing" /></el-form-item><el-form-item label="关系类型"><el-input v-model="relationshipDraft.relationship_type" placeholder="盟友、敌手、亲属、雇佣…" /></el-form-item></div>
        <div class="identity-row"><el-form-item label="起点实体"><el-select v-model="relationshipDraft.source_entity_id"><el-option v-for="e in entities" :key="e.id" :label="e.name" :value="e.id" /></el-select></el-form-item><el-form-item label="目标实体"><el-select v-model="relationshipDraft.target_entity_id"><el-option v-for="e in entities" :key="e.id" :label="e.name" :value="e.id" /></el-select></el-form-item></div>
        <el-form-item label="关系冲突 / 张力"><el-input v-model="relationshipDraft.conflict" type="textarea" :rows="2" /></el-form-item>
        <div class="identity-row"><el-form-item label="双方筹码"><el-input v-model="relationshipDraft.stakes" /></el-form-item><el-form-item label="当前状态"><el-input v-model="relationshipDraft.status" /></el-form-item></div>
        <div class="identity-row"><el-form-item label="起点"><el-input v-model="relationshipDraft.arc.start" /></el-form-item><el-form-item label="当前"><el-input v-model="relationshipDraft.arc.current" /></el-form-item><el-form-item label="终点"><el-input v-model="relationshipDraft.arc.destination" /></el-form-item></div>
        <el-form-item label="锁定字段"><el-select v-model="relationshipDraft.field_locks" multiple filterable allow-create default-first-option placeholder="锁定后自动同步不会覆盖"><el-option v-for="field in relationshipLockFields" :key="field" :label="field" :value="field" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button v-if="relationshipEditing" type="danger" text @click="removeRelationship">删除</el-button><el-button @click="relationshipDialog = false">取消</el-button><el-button type="primary" @click="saveRelationship">保存关系</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useProjectStore } from '../stores/project'
import {
  addEntityRelationship, addPlanningEntity, deleteEntityRelationship, deletePlanningEntity,
  getPlanningEntityNetwork, setPlanningEntityFieldLock, syncPlanningEntityNetwork,
  updateEntityRelationship, updatePlanningEntity,
  type EntityRelationship, type PlanningEntity,
} from '../api'

const LockableField = defineComponent({
  props: { label: String, field: String, locked: Boolean },
  emits: ['toggle'],
  setup(props, { emit, slots }) {
    return () => h('div', { class: 'lockable-field' }, [
      h('div', { class: 'lockable-label' }, [
        h('span', props.label),
        h('button', { class: { 'field-lock': true, active: props.locked }, type: 'button', title: props.locked ? '解除字段锁定' : '锁定字段，阻止 AI 覆盖', onClick: () => emit('toggle', props.field) }, props.locked ? '已锁' : '锁定'),
      ]),
      slots.default?.(),
    ])
  },
})

const store = useProjectStore()
const entities = ref<PlanningEntity[]>([])
const relationships = ref<EntityRelationship[]>([])
const selectedId = ref('')
const draft = ref<PlanningEntity | null>(null)
const search = ref('')
const saving = ref(false)
const syncing = ref(false)
const relationshipDialog = ref(false)
const relationshipEditing = ref(false)
const relationshipDraft = ref<EntityRelationship | null>(null)
const relationshipLockFields = ['relationship_type', 'status', 'source_goal', 'target_goal', 'stakes', 'conflict', 'secret', 'arc']

const filteredEntities = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return keyword ? entities.value.filter(e => `${e.id} ${e.name} ${e.tags.join(' ')}`.toLowerCase().includes(keyword)) : entities.value
})
const isNew = computed(() => !selectedId.value)

function blankEntity(): PlanningEntity {
  return { id: '', name: '', kind: 'character', aliases: [], tags: [], story_role: '', surface_goal: '', inner_need: '', fear: '', values: '', flaw: '', secret: '', capabilities: '', limitations: '', voice: '', action_style: '', arc: { start: '', current: '', destination: '' }, volume_roles: {}, codex_ref: '', field_locks: [], source: 'manual', updated_at: '' }
}
function blankRelationship(): EntityRelationship {
  return { id: '', source_entity_id: entities.value[0]?.id || '', target_entity_id: entities.value[1]?.id || '', relationship_type: 'related', tags: [], status: '', source_goal: '', target_goal: '', stakes: '', conflict: '', secret: '', arc: { start: '', current: '', destination: '' }, field_locks: [], source: 'manual', updated_at: '' }
}
function copy<T>(value: T): T { return JSON.parse(JSON.stringify(value)) }
function entityName(id: string) { return entities.value.find(e => e.id === id)?.name || id }
function isLocked(field: string) { return !!draft.value?.field_locks.includes(field) }

async function loadNetwork() {
  if (!store.currentId) return
  try {
    const network = await getPlanningEntityNetwork(store.currentId)
    entities.value = network.entities
    relationships.value = network.relationships
    const selected = entities.value.find(e => e.id === selectedId.value)
    if (selected) draft.value = copy(selected)
  } catch { ElMessage.error('无法读取幕后实体网络') }
}
function selectEntity(entity: PlanningEntity) { selectedId.value = entity.id; draft.value = copy(entity) }
function createEntity() { selectedId.value = ''; draft.value = blankEntity() }
async function saveEntity() {
  if (!store.currentId || !draft.value?.id || !draft.value.name.trim()) { ElMessage.warning('请填写稳定 ID 和名称'); return }
  saving.value = true
  try {
    const saved = isNew.value ? await addPlanningEntity(store.currentId, draft.value) : await updatePlanningEntity(store.currentId, draft.value)
    const index = entities.value.findIndex(e => e.id === saved.id)
    if (index >= 0) entities.value[index] = saved; else entities.value.push(saved)
    selectedId.value = saved.id; draft.value = copy(saved); ElMessage.success('幕后档案已保存')
  } catch (error: any) { ElMessage.error(error?.response?.data?.detail || '保存失败') } finally { saving.value = false }
}
async function removeEntity() {
  if (!store.currentId || !draft.value || isNew.value) return
  try {
    await ElMessageBox.confirm(`删除「${draft.value.name}」也会删除关联关系，是否继续？`, '删除实体', { type: 'warning' })
    await deletePlanningEntity(store.currentId, draft.value.id)
    selectedId.value = ''; draft.value = null; await loadNetwork(); ElMessage.success('已删除实体及关联关系')
  } catch { /* cancelled */ }
}
async function toggleEntityLock(field: string) {
  if (!store.currentId || !draft.value || isNew.value) { ElMessage.info('请先保存实体，再锁定字段'); return }
  const locked = !isLocked(field)
  try {
    await setPlanningEntityFieldLock(store.currentId, draft.value.id, 'entity', field, locked)
    draft.value.field_locks = locked ? [...draft.value.field_locks, field] : draft.value.field_locks.filter(x => x !== field)
    const item = entities.value.find(e => e.id === draft.value?.id)
    if (item) item.field_locks = [...draft.value.field_locks]
  } catch { ElMessage.error('字段锁更新失败') }
}
async function syncNetwork() {
  if (!store.currentId) return
  syncing.value = true
  try { const result = await syncPlanningEntityNetwork(store.currentId); await loadNetwork(); ElMessage.success(`同步完成：${result.change_count || 0} 项变更`) }
  catch (error: any) { ElMessage.error(error?.response?.data?.detail || '同步失败') } finally { syncing.value = false }
}
function createRelationship() { relationshipEditing.value = false; relationshipDraft.value = blankRelationship(); relationshipDialog.value = true }
function editRelationship(value: EntityRelationship) { relationshipEditing.value = true; relationshipDraft.value = copy(value); relationshipDialog.value = true }
async function saveRelationship() {
  if (!store.currentId || !relationshipDraft.value?.id || !relationshipDraft.value.source_entity_id || !relationshipDraft.value.target_entity_id) { ElMessage.warning('请填写关系 ID 与双方实体'); return }
  try {
    const saved = relationshipEditing.value ? await updateEntityRelationship(store.currentId, relationshipDraft.value) : await addEntityRelationship(store.currentId, relationshipDraft.value)
    const index = relationships.value.findIndex(r => r.id === saved.id)
    if (index >= 0) relationships.value[index] = saved; else relationships.value.push(saved)
    relationshipDialog.value = false; ElMessage.success('关系已保存')
  } catch (error: any) { ElMessage.error(error?.response?.data?.detail || '关系保存失败') }
}
async function removeRelationship() {
  if (!store.currentId || !relationshipDraft.value) return
  try { await deleteEntityRelationship(store.currentId, relationshipDraft.value.id); relationshipDialog.value = false; await loadNetwork(); ElMessage.success('关系已删除') } catch { ElMessage.error('删除失败') }
}
onMounted(loadNetwork)
</script>

<style scoped>
.entity-workbench { max-width: 1480px; margin: 0 auto; padding-bottom: 28px; color: var(--rb-text-primary); }
.page-header, .relationship-head, .dossier-top { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; }
.page-header { margin-bottom: 20px; }.eyebrow, .dossier-kicker { margin: 0 0 6px; color: var(--rb-primary); font: 700 11px/1.2 ui-monospace, monospace; letter-spacing: .12em; }.page-header h1 { margin: 0; font-size: 30px; letter-spacing: -.04em; }.subtitle { margin: 8px 0 0; color: var(--rb-text-secondary); }.header-actions, .dossier-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.workbench-grid { display: grid; grid-template-columns: 286px minmax(0, 1fr); min-height: 620px; gap: 16px; }.entity-roster, .entity-dossier, .empty-dossier, .relationship-panel { border: 1px solid var(--rb-border-light); border-radius: 14px; background: var(--rb-bg-surface); box-shadow: 0 1px 2px rgba(0,0,0,.04); }.entity-roster { display: flex; flex-direction: column; overflow: hidden; }.roster-head { display: flex; justify-content: space-between; padding: 17px 16px 10px; font-weight: 700; }.entity-search { padding: 0 12px 12px; box-sizing: border-box; }.roster-list { padding: 6px; overflow: auto; flex: 1; }.roster-item { border: 0; width: 100%; background: transparent; text-align: left; display: flex; align-items: center; padding: 10px; gap: 10px; border-radius: 10px; cursor: pointer; color: inherit; }.roster-item:hover { background: var(--rb-bg-subtle); }.roster-item.active { background: var(--rb-primary-bg); }.entity-mark { width: 31px; height: 31px; display: grid; place-items: center; border-radius: 9px; background: var(--rb-bg-subtle); color: var(--rb-primary); font-weight: 700; }.active .entity-mark { background: var(--rb-primary); color: #fff; }.roster-copy { min-width: 0; flex: 1; display: grid; gap: 3px; }.roster-copy strong, .roster-copy small { overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }.roster-copy small, .lock-count { color: var(--rb-text-muted); font-size: 12px; }.lock-count { display: flex; align-items: center; gap: 3px; }.empty-roster, .relationship-empty { padding: 28px 18px; color: var(--rb-text-muted); font-size: 13px; line-height: 1.7; text-align: center; }
.entity-dossier { padding: 22px 26px; overflow: auto; }.dossier-top { border-bottom: 1px solid var(--rb-border-light); padding-bottom: 18px; }.name-input :deep(input) { padding: 0; height: 38px; border: 0; background: transparent; font-size: 28px; font-weight: 700; letter-spacing: -.04em; box-shadow: none; }.dossier-form { padding-top: 18px; }.identity-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; }.dossier-section { padding: 18px 0; border-top: 1px solid var(--rb-border-light); }.section-title { display: flex; align-items: baseline; gap: 10px; margin-bottom: 14px; font-weight: 700; }.section-title small { color: var(--rb-text-muted); font-size: 12px; font-weight: 400; }.field-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }.lockable-label { display: flex; justify-content: space-between; align-items: center; font-size: 13px; color: var(--rb-text-secondary); margin-bottom: 7px; }.field-lock { border: 0; background: transparent; color: var(--rb-text-muted); font-size: 11px; cursor: pointer; padding: 2px 5px; border-radius: 4px; }.field-lock:hover, .field-lock.active { color: var(--rb-primary); background: var(--rb-primary-bg); }.arc-strip { display: grid; grid-template-columns: 1fr auto 1fr auto 1fr; gap: 9px; align-items: end; margin-top: 15px; padding: 14px; background: var(--rb-bg-subtle); border-radius: 10px; }.arc-arrow { margin-bottom: 9px; color: var(--rb-text-muted); }.secret-section { background: color-mix(in srgb, var(--rb-primary-bg) 35%, transparent); margin: 0 -10px; padding: 16px 10px; border-radius: 10px; }.empty-dossier { display: grid; place-content: center; text-align: center; padding: 40px; }.empty-dossier :deep(.el-icon) { font-size: 42px; color: var(--rb-primary); margin: auto; }.empty-dossier h2 { margin: 15px 0 7px; }.empty-dossier p { color: var(--rb-text-secondary); margin: 0 0 18px; }
.relationship-panel { margin-top: 16px; padding: 20px; }.relationship-head h2 { margin: 0; font-size: 20px; }.relationship-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 10px; margin-top: 15px; }.relationship-card { border: 1px solid var(--rb-border-light); border-radius: 10px; padding: 14px; cursor: pointer; transition: .15s ease; }.relationship-card:hover { border-color: var(--rb-primary); transform: translateY(-1px); }.relationship-path { display: flex; align-items: center; gap: 7px; margin-bottom: 9px; }.relationship-card p { min-height: 40px; margin: 10px 0; line-height: 1.5; color: var(--rb-text-secondary); font-size: 13px; }.relationship-card small { color: var(--rb-text-muted); }
@media (max-width: 900px) { .workbench-grid { grid-template-columns: 1fr; }.entity-roster { max-height: 260px; }.identity-row, .field-grid { grid-template-columns: 1fr; }.arc-strip { grid-template-columns: 1fr; }.arc-arrow { display: none; }.page-header, .dossier-top { flex-direction: column; }.entity-dossier { padding: 18px; } }
</style>
