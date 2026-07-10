<template>
  <div class="dashboard">
    <!-- Page header -->
    <div class="page-header">
      <div class="page-header-left">
        <h1 class="page-title">仪表盘</h1>
        <p class="page-subtitle" v-if="store.currentProject">
          {{ store.currentProject.title || store.currentProject.id }}
        </p>
      </div>
      <div class="page-header-right">
        <el-select v-model="store.currentId" placeholder="选择项目" class="project-select" @change="onProjectChange">
          <el-option v-for="p in store.projects" :key="p.id" :label="p.title || p.id" :value="p.id" />
        </el-select>
        <el-button type="primary" @click="showCreate = true">
          <el-icon><Plus /></el-icon> 新建项目
        </el-button>
        <el-button type="danger" plain :disabled="!store.currentId" :loading="deleting" @click="doDeleteProject">
          <el-icon><Delete /></el-icon> 删除项目
        </el-button>
      </div>
    </div>

    <!-- Create dialog -->
    <el-dialog v-model="showCreate" title="新建小说项目" width="480px">
      <el-form :model="createForm" label-width="80px">
        <el-form-item label="目录名"><el-input v-model="createForm.name" /></el-form-item>
        <el-form-item label="标题"><el-input v-model="createForm.title" /></el-form-item>
        <el-form-item label="作者"><el-input v-model="createForm.author" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" @click="doCreate">创建</el-button>
      </template>
    </el-dialog>

    <template v-if="store.status">
      <!-- Stats cards -->
      <div class="stat-grid">
        <div class="stat-card" v-for="(card, idx) in statCardsMeta" :key="idx">
          <div class="stat-icon-wrap" :style="{ background: card.bgColor }">
            <el-icon :size="22" :style="{ color: card.iconColor }">
              <component :is="card.icon" />
            </el-icon>
          </div>
          <div class="stat-info">
            <div class="stat-value" :style="{ color: card.iconColor }">{{ card.value }}</div>
            <div class="stat-label">{{ card.label }}</div>
          </div>
        </div>
      </div>

      <!-- Synopsis -->
      <div class="section">
        <div class="section-header">
          <h2 class="section-title">
            <el-icon class="section-icon"><Notebook /></el-icon>
            全书梗概
          </h2>
        </div>
        <div class="synopsis-card">
          <div v-if="synopsis" class="synopsis-text">{{ synopsis }}</div>
          <div v-else class="empty-state">
            <el-icon :size="32" class="empty-icon"><Document /></el-icon>
            <p>尚未生成梗概</p>
            <span class="empty-hint-text">前往「大纲」页面，点击"生成梗概"开始创作之旅</span>
          </div>
        </div>
      </div>

      <!-- Chapter progress -->
      <div class="section">
        <div class="section-header">
          <h2 class="section-title">
            <el-icon class="section-icon"><TrendCharts /></el-icon>
            章节进度
          </h2>
          <span class="chapter-count">{{ store.status.chapters.length }} 章</span>
        </div>
        <div class="table-card">
          <el-table :data="store.status.chapters" size="default" :header-cell-style="headerCellStyle">
            <el-table-column prop="number" label="章" width="64" align="center">
              <template #default="{ row }">
                <span class="chapter-num">{{ row.number }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="title" label="标题" min-width="160">
              <template #default="{ row }">
                <span class="chapter-title">{{ row.title || '(未命名)' }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="volume" label="卷" width="64" align="center" />
            <el-table-column prop="beat_count" label="Beat" width="72" align="center" />
            <el-table-column label="摘要" width="80" align="center">
              <template #default="{ row }">
                <span :class="['status-dot', row.has_summary ? 'dot-success' : 'dot-muted']"></span>
                <span :class="row.has_summary ? 'status-ok' : 'status-na'">{{ row.has_summary ? '有' : '无' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="草稿" width="80" align="center">
              <template #default="{ row }">
                <span :class="['status-dot', row.has_draft ? 'dot-success' : 'dot-muted']"></span>
                <span :class="row.has_draft ? 'status-ok' : 'status-na'">{{ row.has_draft ? '已写' : '未写' }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" align="center">
              <template #default="{ row }">
                <el-button size="small" text type="primary" @click="$router.push('/writer')">
                  <el-icon><EditPen /></el-icon> 写作
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
    </template>

    <div v-else-if="store.loading" class="loading-area">
      <div class="skeleton-grid">
        <div v-for="i in 4" :key="i" class="skeleton-card">
          <el-skeleton :rows="2" animated />
        </div>
      </div>
      <div class="skeleton-block">
        <el-skeleton :rows="6" animated />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useProjectStore } from '../stores/project'
import { getSynopsis } from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

const store = useProjectStore()
const showCreate = ref(false)
const synopsis = ref('')
const createForm = ref({ name: '', title: '', author: '' })
const deleting = ref(false)

const headerCellStyle = {
  fontWeight: '600',
  fontSize: '12px',
  color: 'var(--rb-text-secondary)',
  textTransform: 'uppercase' as const,
  letterSpacing: '0.06em',
}

const statCardsMeta = computed(() => {
  const s = store.status
  if (!s) return []
  return [
    {
      label: '设定集',
      value: s.codex_count,
      icon: 'Collection',
      iconColor: '#f59e0b',
      bgColor: 'rgba(245, 158, 11, 0.10)',
    },
    {
      label: '卷',
      value: s.volume_count,
      icon: 'Folder',
      iconColor: '#6366f1',
      bgColor: 'rgba(99, 102, 241, 0.10)',
    },
    {
      label: '章节 Beat',
      value: s.chapter_count,
      icon: 'Document',
      iconColor: '#0ea5e9',
      bgColor: 'rgba(14, 165, 233, 0.10)',
    },
    {
      label: '已写草稿',
      value: s.draft_count,
      icon: 'Finished',
      iconColor: '#10b981',
      bgColor: 'rgba(16, 185, 129, 0.10)',
    },
  ]
})

async function onProjectChange() {
  await store.fetchStatus()
  if (store.currentId) {
    const r = await getSynopsis(store.currentId)
    synopsis.value = r.text
  }
}

async function doCreate() {
  try {
    await store.createNew(createForm.value)
    showCreate.value = false
    ElMessage.success('项目已创建')
    await onProjectChange()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '创建失败')
  }
}

async function doDeleteProject() {
  if (!store.currentId || !store.currentProject) return
  const name = store.currentProject.title || store.currentProject.id
  try {
    await ElMessageBox.confirm(
      `确定删除项目「${name}」？此操作不可撤销，所有设定集、大纲、草稿将被永久删除。`,
      '删除项目',
      { type: 'warning', confirmButtonText: '确认删除', confirmButtonClass: 'el-button--danger' },
    )
  } catch {
    return // cancelled
  }
  deleting.value = true
  try {
    await store.removeProject(store.currentId)
    ElMessage.success('项目已删除')
    await onProjectChange()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  } finally {
    deleting.value = false
  }
}

onMounted(async () => {
  await store.fetchProjects()
  await onProjectChange()
})
</script>

<style scoped>
.dashboard {
  max-width: 1100px;
  margin: 0 auto;
}

/* ===== Page Header ===== */
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 32px;
}

.page-header-left {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.page-title {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--rb-text-primary);
  margin: 0;
}

.page-subtitle {
  font-size: 14px;
  color: var(--rb-text-muted);
  margin: 0;
  font-weight: 500;
}

.page-header-right {
  display: flex;
  gap: 10px;
  align-items: center;
}

.project-select {
  min-width: 200px;
}

/* ===== Stat Cards ===== */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 32px;
}

.stat-card {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 12px;
  padding: 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  transition: all 0.2s ease;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.stat-card:hover {
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.06);
  transform: translateY(-2px);
}

.stat-icon-wrap {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.stat-label {
  font-size: 13px;
  font-weight: 500;
  color: var(--rb-text-muted);
  letter-spacing: -0.01em;
}

/* ===== Section ===== */
.section {
  margin-bottom: 28px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 14px;
}

.section-title {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--rb-text-primary);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.section-icon {
  color: var(--rb-primary);
  font-size: 18px;
}

.chapter-count {
  font-size: 13px;
  font-weight: 500;
  color: var(--rb-text-muted);
  background: var(--rb-bg-subtle);
  padding: 4px 10px;
  border-radius: 999px;
}

/* ===== Synopsis ===== */
.synopsis-card {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.synopsis-text {
  white-space: pre-wrap;
  line-height: 1.9;
  font-size: 15px;
  color: var(--rb-text-primary);
  max-height: 320px;
  overflow-y: auto;
  letter-spacing: -0.005em;
}

/* ===== Empty State ===== */
.empty-state {
  text-align: center;
  padding: 32px 20px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.empty-state p {
  margin: 0;
  font-size: 15px;
  font-weight: 500;
  color: var(--rb-text-secondary);
}

.empty-icon {
  color: var(--rb-text-subtle);
  margin-bottom: 4px;
}

.empty-hint-text {
  font-size: 13px;
  color: var(--rb-text-muted);
}

/* ===== Table ===== */
.table-card {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.table-card :deep(.el-table) {
  border-radius: 0 !important;
}

.chapter-num {
  font-weight: 600;
  color: var(--rb-text-secondary);
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.chapter-title {
  font-weight: 500;
  color: var(--rb-text-primary);
}

.status-dot {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: middle;
}

.dot-success {
  background: #10b981;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.15);
}

.dot-muted {
  background: #d1d5db;
}

.status-ok {
  font-size: 13px;
  font-weight: 500;
  color: var(--rb-text-primary);
}

.status-na {
  font-size: 13px;
  font-weight: 500;
  color: var(--rb-text-muted);
}

/* ===== Loading ===== */
.loading-area {
  padding: 0;
}

.skeleton-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 28px;
}

.skeleton-card {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 12px;
  padding: 20px;
}

.skeleton-block {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 12px;
  padding: 24px;
}

/* ===== Responsive ===== */
@media (max-width: 992px) {
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .skeleton-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .page-header {
    flex-direction: column;
  }
  .page-header-right {
    width: 100%;
    flex-direction: column;
  }
  .project-select {
    width: 100%;
  }
  .stat-grid {
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .stat-card {
    padding: 14px;
    gap: 10px;
  }
  .stat-icon-wrap {
    width: 40px;
    height: 40px;
    border-radius: 10px;
  }
  .stat-value {
    font-size: 22px;
  }
  .skeleton-grid {
    grid-template-columns: 1fr 1fr;
  }
}
</style>
