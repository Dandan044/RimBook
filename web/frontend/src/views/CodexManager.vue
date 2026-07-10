<template>
  <div class="codex-manager">
    <!-- Page header -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon class="title-icon"><Collection /></el-icon>
        设定集
      </h1>
    </div>

    <div class="codex-layout">
      <!-- Left panel -->
      <div class="left-panel">
        <!-- Type tabs -->
        <div class="type-tabs">
          <div
            v-for="t in entityTypes"
            :key="t.value"
            class="type-tab"
            :class="{ active: activeType === t.value }"
            @click="activeType = t.value; fetchEntries()"
          >
            <span class="type-icon">{{ t.icon }}</span>
            <span class="type-label">{{ t.label }}</span>
          </div>
        </div>

        <!-- Entry list -->
        <div class="entry-list">
          <div
            v-for="entry in entries"
            :key="entry.id"
            class="entry-item"
            :class="{ active: selected?.id === entry.id }"
            @click="selectEntry(entry)"
          >
            <div class="entry-info">
              <span class="entry-name">{{ entry.name }}</span>
              <span class="entry-id">{{ entry.id }}</span>
            </div>
          </div>
          <div v-if="entries.length === 0" class="empty-list">
            <el-icon :size="24" class="empty-icon"><Document /></el-icon>
            <span>暂无条目</span>
          </div>
        </div>

        <!-- Add button -->
        <div class="add-section">
          <el-button type="primary" @click="openAdd" style="width: 100%">
            <el-icon><Plus /></el-icon> 添加条目
          </el-button>
        </div>
      </div>

      <!-- Right: detail / editor -->
      <div class="right-panel">
        <template v-if="selected">
          <div class="detail-card">
            <div class="detail-header">
              <div class="detail-title-area">
                <h2 class="detail-title">{{ selected.name }}</h2>
                <el-tag size="small" :type="typeTagColor(selected.type)" effect="plain">
                  {{ entityTypeLabel(selected.type) }}
                </el-tag>
              </div>
              <div class="detail-actions">
                <el-button @click="doEdit" :disabled="!selected">
                  <el-icon><Edit /></el-icon> 编辑
                </el-button>
                <el-button type="danger" plain @click="doDelete" :disabled="!selected">
                  <el-icon><Delete /></el-icon> 删除
                </el-button>
              </div>
            </div>

            <div class="detail-body">
              <!-- Meta grid -->
              <div class="meta-grid">
                <div class="meta-item">
                  <span class="meta-label">ID</span>
                  <code class="meta-code">{{ selected.id }}</code>
                </div>
                <div class="meta-item">
                  <span class="meta-label">别名</span>
                  <div class="meta-tags">
                    <el-tag v-for="a in selected.aliases" :key="a" size="small" effect="plain">{{ a }}</el-tag>
                    <span v-if="!selected.aliases?.length" class="meta-empty">-</span>
                  </div>
                </div>
                <div class="meta-item">
                  <span class="meta-label">标签</span>
                  <div class="meta-tags">
                    <el-tag v-for="tag in selected.tags" :key="tag" size="small" type="info" effect="plain">{{ tag }}</el-tag>
                    <span v-if="!selected.tags?.length" class="meta-empty">-</span>
                  </div>
                </div>
                <div class="meta-item">
                  <span class="meta-label">关联</span>
                  <div class="meta-tags">
                    <el-tag v-for="r in selected.related" :key="r" size="small" type="warning" effect="plain">{{ r }}</el-tag>
                    <span v-if="!selected.related?.length" class="meta-empty">-</span>
                  </div>
                </div>
              </div>

              <!-- Body content -->
              <div class="body-section">
                <h3 class="body-heading">正文</h3>
                <div class="body-text">{{ selected.body || '(空)' }}</div>
              </div>
            </div>
          </div>
        </template>

        <div v-else class="detail-empty">
          <el-icon :size="40" class="empty-big-icon"><Collection /></el-icon>
          <p class="empty-text">选择左侧条目查看详情</p>
          <span class="empty-sub">或点击"添加条目"创建新的设定</span>
        </div>
      </div>
    </div>

    <!-- Add / Edit dialog -->
    <el-dialog v-model="showDialog" :title="isEdit ? '编辑条目' : '添加条目'" width="560px" destroy-on-close>
      <el-form :model="form" label-width="60px">
        <el-form-item v-if="!isEdit" label="ID"><el-input v-model="form.id" placeholder="唯一 slug，如 lin_yuxuan" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width:100%">
            <el-option v-for="t in entityTypes" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="别名">
          <el-select v-model="form.aliases" multiple filterable allow-create default-first-option style="width:100%" />
        </el-form-item>
        <el-form-item label="标签">
          <el-select v-model="form.tags" multiple filterable allow-create default-first-option style="width:100%" />
        </el-form-item>
        <el-form-item label="关联">
          <el-select v-model="form.related" multiple filterable allow-create default-first-option style="width:100%" />
        </el-form-item>
        <el-form-item label="正文">
          <el-input v-model="form.body" type="textarea" :rows="8" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" @click="doSave" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useProjectStore } from '../stores/project'
import {
  listCodex, addCodex, getCodex, updateCodex, deleteCodex,
  type CodexEntry,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const store = useProjectStore()

const entityTypes = [
  { value: 'character', label: '实体', icon: '🧩' },
  { value: 'worldbuilding', label: '世界观', icon: '🌍' },
  { value: 'location', label: '地点', icon: '📍' },
  { value: 'faction', label: '势力', icon: '⚔️' },
  { value: 'item', label: '物品', icon: '🔑' },
  { value: 'timeline', label: '时间线', icon: '📅' },
]

const activeType = ref('character')
const entries = ref<CodexEntry[]>([])
const selected = ref<CodexEntry | null>(null)

const showDialog = ref(false)
const isEdit = ref(false)
const saving = ref(false)

const form = reactive({
  id: '',
  name: '',
  type: 'character',
  aliases: [] as string[],
  tags: [] as string[],
  related: [] as string[],
  body: '',
})

function entityTypeLabel(type: string) {
  return entityTypes.find(t => t.value === type)?.label || type
}

function typeTagColor(type: string) {
  const map: Record<string, string> = {
    character: '',
    worldbuilding: 'success',
    location: 'warning',
    faction: 'danger',
    item: 'info',
    timeline: '',
  }
  return (map[type] || '') as any
}

async function fetchEntries() {
  if (!store.currentId) return
  selected.value = null
  try {
    entries.value = await listCodex(store.currentId, activeType.value)
  } catch {
    entries.value = []
  }
}

function selectEntry(entry: CodexEntry) {
  selected.value = entry
}

function openAdd() {
  isEdit.value = false
  Object.assign(form, {
    id: '',
    name: '',
    type: activeType.value,
    aliases: [],
    tags: [],
    related: [],
    body: '',
  })
  showDialog.value = true
}

function doEdit() {
  if (!selected.value) return
  isEdit.value = true
  Object.assign(form, {
    name: selected.value.name,
    type: selected.value.type,
    aliases: [...(selected.value.aliases || [])],
    tags: [...(selected.value.tags || [])],
    related: [...(selected.value.related || [])],
    body: selected.value.body,
  })
  showDialog.value = true
}

async function doSave() {
  if (!store.currentId) return
  saving.value = true
  try {
    if (isEdit.value && selected.value) {
      await updateCodex(store.currentId, selected.value.id, { ...form })
      ElMessage.success('已更新')
    } else {
      await addCodex(store.currentId, { ...form })
      ElMessage.success('已添加')
    }
    showDialog.value = false
    await fetchEntries()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function doDelete() {
  if (!store.currentId || !selected.value) return
  try {
    await ElMessageBox.confirm(
      '确定删除「' + selected.value.name + '」？',
      '删除确认',
      { type: 'warning' },
    )
    await deleteCodex(store.currentId, selected.value.id)
    ElMessage.success('已删除')
    selected.value = null
    await fetchEntries()
  } catch {
    // cancelled or failed
  }
}

onMounted(fetchEntries)
</script>

<style scoped>
.codex-manager {
  height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
}

.page-header {
  margin-bottom: 20px;
  flex-shrink: 0;
}

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

.title-icon {
  color: var(--rb-primary);
  font-size: 22px;
}

.codex-layout {
  flex: 1;
  display: flex;
  gap: 20px;
  min-height: 0;
}

/* ===== Left Panel ===== */
.left-panel {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.type-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 12px;
  border-bottom: 1px solid var(--rb-border-light);
  background: var(--rb-bg-subtle);
}

.type-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s ease;
  font-size: 13px;
  font-weight: 500;
  color: var(--rb-text-secondary);
  user-select: none;
}

.type-tab:hover {
  background: var(--rb-bg-surface);
  color: var(--rb-text-primary);
}

.type-tab.active {
  background: var(--rb-primary-bg);
  color: var(--rb-primary);
  font-weight: 600;
  box-shadow: 0 0 0 1px var(--rb-primary-bg-hover);
}

.type-icon {
  font-size: 15px;
  width: 20px;
  text-align: center;
  flex-shrink: 0;
}

.type-label {
  white-space: nowrap;
}

/* Entry list */
.entry-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  min-height: 0;
}

.entry-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.12s ease;
  margin-bottom: 2px;
}

.entry-item:hover {
  background: var(--rb-bg-subtle);
}

.entry-item.active {
  background: var(--rb-primary-bg);
}

.entry-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.entry-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--rb-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.entry-item.active .entry-name {
  color: var(--rb-primary);
  font-weight: 600;
}

.entry-id {
  font-size: 11px;
  color: var(--rb-text-muted);
  font-family: 'SF Mono', ui-monospace, monospace;
}

.empty-list {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 40px 20px;
  color: var(--rb-text-muted);
  font-size: 13px;
}

.empty-icon {
  color: var(--rb-text-subtle);
}

/* Add section */
.add-section {
  padding: 12px;
  border-top: 1px solid var(--rb-border-light);
  flex-shrink: 0;
}

/* ===== Right Panel ===== */
.right-panel {
  flex: 1;
  min-width: 0;
}

.detail-card {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid var(--rb-border-light);
  gap: 16px;
  flex-wrap: wrap;
}

.detail-title-area {
  display: flex;
  align-items: center;
  gap: 10px;
}

.detail-title {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--rb-text-primary);
  margin: 0;
}

.detail-actions {
  display: flex;
  gap: 8px;
}

.detail-body {
  padding: 24px;
}

/* Meta grid */
.meta-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 24px;
  padding: 20px;
  background: var(--rb-bg-subtle);
  border-radius: 10px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.meta-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--rb-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

.meta-code {
  font-size: 13px;
  font-family: 'SF Mono', ui-monospace, monospace;
  color: var(--rb-text-secondary);
  background: var(--rb-bg-surface);
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid var(--rb-border);
  display: inline-block;
}

.meta-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.meta-empty {
  color: var(--rb-text-subtle);
  font-size: 13px;
}

/* Body section */
.body-section {
  margin-top: 4px;
}

.body-heading {
  font-size: 13px;
  font-weight: 600;
  color: var(--rb-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 0 0 12px;
}

.body-text {
  white-space: pre-wrap;
  line-height: 1.9;
  font-size: 15px;
  color: var(--rb-text-primary);
  background: var(--rb-bg-subtle);
  border-radius: 10px;
  padding: 20px 24px;
  max-height: calc(100vh - 480px);
  overflow-y: auto;
  border: 1px solid var(--rb-border-light);
}

/* ===== Empty Detail ===== */
.detail-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 14px;
  min-height: 400px;
}

.empty-big-icon {
  color: var(--rb-text-subtle);
  margin-bottom: 12px;
}

.empty-text {
  font-size: 16px;
  font-weight: 500;
  color: var(--rb-text-secondary);
  margin: 0 0 4px;
}

.empty-sub {
  font-size: 13px;
  color: var(--rb-text-muted);
}

/* ===== Responsive ===== */
@media (max-width: 768px) {
  .codex-layout {
    flex-direction: column;
  }

  .left-panel {
    width: 100%;
    max-height: 45vh;
  }

  .right-panel {
    min-height: 40vh;
  }

  .body-text {
    max-height: 40vh;
  }

  .type-tabs {
    flex-wrap: nowrap;
    overflow-x: auto;
  }

  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
