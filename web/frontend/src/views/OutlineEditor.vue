<template>
  <div class="outline-editor">
    <!-- Page header -->
    <div class="page-header">
      <h1 class="page-title">
        <el-icon class="title-icon"><Document /></el-icon>
        大纲
      </h1>
    </div>

    <div class="outline-layout">
      <!-- Left: tree panel -->
      <div class="tree-panel">
        <div class="tree-card">
          <div class="tree-header">
            <span class="tree-title">大纲结构</span>
            <el-button size="small" type="primary" plain @click="generateSynopsis" :loading="generating">
              <el-icon><MagicStick /></el-icon> 生成梗概
            </el-button>
          </div>
          <div class="tree-body">
            <el-tree
              :data="treeData"
              :props="{ label: 'label', children: 'children' }"
              default-expand-all
              highlight-current
              @node-click="onNodeClick"
            />
          </div>
          <div class="tree-actions">
            <el-button size="small" @click="addVolume" :loading="generating">
              <el-icon><Plus /></el-icon> 新卷
            </el-button>
            <el-button size="small" @click="addChapter" :loading="generating">
              <el-icon><Plus /></el-icon> 新章节
            </el-button>
          </div>
        </div>
      </div>

      <!-- Right: editor panel -->
      <div class="editor-panel">
        <!-- Synopsis editor -->
        <div v-if="editing === 'synopsis'" class="editor-card">
          <div class="editor-header">
            <h2 class="editor-title">
              <el-icon class="editor-title-icon"><Notebook /></el-icon>
              全书梗概
            </h2>
          </div>
          <div class="editor-body">
            <el-input v-model="synopsisText" type="textarea" :rows="16" placeholder="输入或生成全书梗概…" class="synopsis-input" />
            <div class="editor-footer">
              <el-button type="primary" @click="saveSynopsis">
                <el-icon><Check /></el-icon> 保存
              </el-button>
            </div>
          </div>
        </div>

        <!-- Volume editor -->
        <div v-else-if="editing === 'volume' && editingVolume" class="editor-card">
          <div class="editor-header">
            <h2 class="editor-title">
              <el-icon class="editor-title-icon"><Folder /></el-icon>
              第{{ editingVolume.number }}卷《{{ editingVolume.title }}》
            </h2>
          </div>
          <div class="editor-body">
            <el-form :model="volumeForm" label-width="60px">
              <el-form-item label="标题"><el-input v-model="volumeForm.title" /></el-form-item>
              <el-form-item label="大纲">
                <el-input v-model="volumeForm.arc" type="textarea" :rows="12" />
              </el-form-item>
              <el-form-item label="结局"><el-input v-model="volumeForm.ending" type="textarea" :rows="4" /></el-form-item>
            </el-form>
            <div class="editor-footer">
              <el-button type="primary" @click="saveVolume">
                <el-icon><Check /></el-icon> 保存
              </el-button>
            </div>
          </div>
        </div>

        <!-- Chapter beat editor -->
        <div v-else-if="editing === 'chapter' && editingChapter" class="editor-card">
          <div class="editor-header">
            <h2 class="editor-title">
              <el-icon class="editor-title-icon"><EditPen /></el-icon>
              第{{ editingChapter.number }}章《{{ editingChapter.title }}》
            </h2>
            <el-button size="small" @click="generateBeat" :loading="generating">
              <el-icon><MagicStick /></el-icon> LLM 生成 Beat
            </el-button>
          </div>
          <div class="editor-body">
            <el-form label-width="60px">
              <el-form-item label="标题"><el-input v-model="chapterForm.title" /></el-form-item>
              <el-form-item label="卷"><el-input-number v-model="chapterForm.volume" :min="0" /></el-form-item>
              <el-form-item label="实体">
                <el-select v-model="chapterForm.entities" multiple filterable allow-create default-first-option />
              </el-form-item>
              <el-form-item label="标签">
                <el-select v-model="chapterForm.tags" multiple filterable allow-create default-first-option />
              </el-form-item>
            </el-form>

            <div class="beats-section">
              <h3 class="beats-heading">场景 Beat</h3>
              <div v-for="(beat, i) in chapterForm.beats" :key="i" class="beat-item">
                <div class="beat-card">
                  <div class="beat-header">
                    <span class="beat-number">场景 {{ i + 1 }}</span>
                    <el-button type="danger" size="small" text @click="chapterForm.beats.splice(i, 1)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                  <el-form label-width="50px" size="small" class="beat-form">
                    <el-form-item label="目标"><el-input v-model="beat.goal" /></el-form-item>
                    <el-form-item label="冲突"><el-input v-model="beat.conflict" /></el-form-item>
                    <el-form-item label="结果"><el-input v-model="beat.outcome" /></el-form-item>
                    <el-form-item label="实体"><el-select v-model="beat.entities" multiple filterable allow-create default-first-option /></el-form-item>
                  </el-form>
                </div>
              </div>
              <el-button size="small" @click="chapterForm.beats.push({ goal: '', conflict: '', outcome: '', entities: [] })">
                <el-icon><Plus /></el-icon> 添加场景
              </el-button>
            </div>

            <el-form label-width="60px" style="margin-top:20px">
              <el-form-item label="附注"><el-input v-model="chapterForm.notes" type="textarea" :rows="4" /></el-form-item>
            </el-form>
            <div class="editor-footer">
              <el-button type="primary" @click="saveChapter">
                <el-icon><Check /></el-icon> 保存
              </el-button>
            </div>
          </div>
        </div>

        <div v-else class="editor-empty">
          <el-icon :size="48" class="empty-icon-big"><Document /></el-icon>
          <p class="empty-main-text">选择大纲节点进行编辑</p>
          <span class="empty-sub-text">点击左侧树形结构中的任意节点</span>
        </div>
      </div>
    </div>

    <!-- Synopsis generate dialog -->
    <el-dialog v-model="showSynopsisDialog" title="生成全书梗概" width="500px">
      <el-input v-model="premiseText" type="textarea" :rows="6" placeholder="输入小说创意/核心设定…" />
      <template #footer>
        <el-button @click="showSynopsisDialog = false">取消</el-button>
        <el-button type="primary" @click="doGenerateSynopsis" :loading="generating">
          <el-icon><MagicStick /></el-icon> 生成
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useProjectStore } from '../stores/project'
import {
  getSynopsis, updateSynopsis, generateSynopsis as apiGenerateSynopsis,
  listVolumes, planVolume, updateVolume,
  listChapters, planChapter, updateChapter, regenerateChapter,
  type VolumeOutline, type ChapterOutline, type SceneBeat,
} from '../api'
import { ElMessage } from 'element-plus'

const store = useProjectStore()
const generating = ref(false)
const editing = ref<'none' | 'synopsis' | 'volume' | 'chapter'>('none')
const synopsisText = ref('')
const volumes = ref<VolumeOutline[]>([])
const chapters = ref<ChapterOutline[]>([])
const editingVolume = ref<VolumeOutline | null>(null)
const editingChapter = ref<ChapterOutline | null>(null)

const showSynopsisDialog = ref(false)
const premiseText = ref('')

const volumeForm = reactive({ title: '', arc: '', ending: '' })
const chapterForm = reactive({
  title: '', volume: null as number | null, entities: [] as string[],
  tags: [] as string[], beats: [] as SceneBeat[], notes: '',
})

const treeData = computed(() => {
  const children: any[] = []
  children.push({ label: '📖 全书梗概', nodeType: 'synopsis' })
  for (const v of volumes.value) {
    const vChapters = chapters.value.filter(c => c.volume === v.number)
    children.push({
      label: `📚 第${v.number}卷 ${v.title || '(未命名)'}`,
      nodeType: 'volume',
      volume: v,
      children: vChapters.map(c => ({
        label: `📝 第${c.number}章 ${c.title || '(未命名)'}`,
        nodeType: 'chapter',
        chapter: c,
      })),
    })
  }
  // Chapters without a volume
  const orphanChapters = chapters.value.filter(c => !c.volume || !volumes.value.find(v => v.number === c.volume))
  if (orphanChapters.length) {
    children.push({
      label: '📝 未分卷章节',
      children: orphanChapters.map(c => ({
        label: `第${c.number}章 ${c.title || '(未命名)'}`,
        nodeType: 'chapter',
        chapter: c,
      })),
    })
  }
  return children
})

function onNodeClick(node: any) {
  if (node.nodeType === 'synopsis') {
    editing.value = 'synopsis'
  } else if (node.nodeType === 'volume') {
    editing.value = 'volume'
    editingVolume.value = node.volume
    Object.assign(volumeForm, { title: node.volume.title, arc: node.volume.arc, ending: node.volume.ending })
  } else if (node.nodeType === 'chapter') {
    editing.value = 'chapter'
    editingChapter.value = node.chapter
    Object.assign(chapterForm, {
      title: node.chapter.title,
      volume: node.chapter.volume,
      entities: [...node.chapter.entities],
      tags: [...node.chapter.tags],
      beats: node.chapter.beats.map((b: SceneBeat) => ({ ...b, entities: [...b.entities] })),
      notes: node.chapter.notes,
    })
  }
}

async function fetchData() {
  if (!store.currentId) return
  const [syn, vols, chs] = await Promise.all([
    getSynopsis(store.currentId),
    listVolumes(store.currentId),
    listChapters(store.currentId),
  ])
  synopsisText.value = syn.text
  volumes.value = vols
  chapters.value = chs
}

async function saveSynopsis() {
  if (!store.currentId) return
  await updateSynopsis(store.currentId, synopsisText.value)
  ElMessage.success('梗概已保存')
}

function generateSynopsis() { showSynopsisDialog.value = true; premiseText.value = '' }

async function doGenerateSynopsis() {
  if (!store.currentId) return
  generating.value = true
  try {
    const r = await apiGenerateSynopsis(store.currentId, premiseText.value)
    synopsisText.value = r.text
    showSynopsisDialog.value = false
    ElMessage.success('梗概已生成')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '生成失败') }
  finally { generating.value = false }
}

async function addVolume() {
  if (!store.currentId) return
  generating.value = true
  try {
    const v = await planVolume(store.currentId)
    volumes.value.push(v)
    ElMessage.success(`第${v.number}卷已规划`)
  } catch (e: any) { ElMessage.error('规划失败') }
  finally { generating.value = false }
}

async function addChapter() {
  if (!store.currentId) return
  generating.value = true
  try {
    const lastVol = volumes.value.length ? volumes.value[volumes.value.length - 1].number : undefined
    const c = await planChapter(store.currentId, { volume: lastVol })
    chapters.value.push(c)
    ElMessage.success(`第${c.number}章 beat 已规划`)
  } catch (e: any) { ElMessage.error('规划失败') }
  finally { generating.value = false }
}

async function generateBeat() {
  // Re-plan current chapter beat via LLM (preserves chapter number + summary)
  if (!store.currentId || !editingChapter.value) return
  generating.value = true
  try {
    const chNum = editingChapter.value.number
    const c = await regenerateChapter(store.currentId, chNum, {
      volume: editingChapter.value.volume || undefined,
      title: editingChapter.value.title,
    })
    // Replace the chapter in our list (same number, so findIndex should match)
    const idx = chapters.value.findIndex(ch => ch.number === chNum)
    if (idx >= 0) chapters.value[idx] = c
    else chapters.value.push(c)
    Object.assign(chapterForm, {
      title: c.title, volume: c.volume, entities: [...c.entities], tags: [...c.tags],
      beats: c.beats.map(b => ({ ...b, entities: [...b.entities] })), notes: c.notes,
    })
    editingChapter.value = c
    ElMessage.success('Beat 已重新生成')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '生成失败') }
  finally { generating.value = false }
}

async function saveVolume() {
  if (!store.currentId || !editingVolume.value) return
  await updateVolume(store.currentId, editingVolume.value.number, { ...volumeForm, number: editingVolume.value.number, chapters: editingVolume.value.chapters } as any)
  ElMessage.success('已保存')
  await fetchData()
}

async function saveChapter() {
  if (!store.currentId || !editingChapter.value) return
  await updateChapter(store.currentId, editingChapter.value.number, {
    title: chapterForm.title, volume: chapterForm.volume,
    entities: chapterForm.entities, tags: chapterForm.tags,
    beats: chapterForm.beats, notes: chapterForm.notes,
  } as any)
  ElMessage.success('已保存')
  await fetchData()
}

onMounted(fetchData)
</script>

<style scoped>
.outline-editor {
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

.outline-layout {
  flex: 1;
  display: flex;
  gap: 20px;
  min-height: 0;
}

/* ===== Tree Panel ===== */
.tree-panel {
  width: 300px;
  flex-shrink: 0;
}

.tree-card {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  display: flex;
  flex-direction: column;
  height: 100%;
}

.tree-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--rb-border-light);
  flex-shrink: 0;
}

.tree-title {
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
  color: var(--rb-text-primary);
}

.tree-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 8px;
}

.tree-actions {
  padding: 12px 16px;
  display: flex;
  gap: 8px;
  border-top: 1px solid var(--rb-border-light);
  flex-shrink: 0;
  background: var(--rb-bg-subtle);
}

/* ===== Editor Panel ===== */
.editor-panel {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}

.editor-card {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid var(--rb-border-light);
  gap: 16px;
  flex-wrap: wrap;
}

.editor-title {
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--rb-text-primary);
  margin: 0;
  display: flex;
  align-items: center;
  gap: 10px;
}

.editor-title-icon {
  color: var(--rb-primary);
  font-size: 20px;
}

.editor-body {
  padding: 24px;
}

.editor-footer {
  margin-top: 20px;
  display: flex;
  gap: 8px;
}

.synopsis-input :deep(textarea) {
  font-size: 15px;
  line-height: 1.9;
  font-family: var(--rb-font);
}

/* ===== Beat Section ===== */
.beats-section {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--rb-border-light);
}

.beats-heading {
  font-size: 13px;
  font-weight: 600;
  color: var(--rb-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 0 0 14px;
}

.beat-item {
  margin-bottom: 12px;
}

.beat-card {
  background: var(--rb-bg-subtle);
  border: 1px solid var(--rb-border-light);
  border-radius: 10px;
  padding: 16px;
  transition: border-color 0.15s ease;
}

.beat-card:hover {
  border-color: var(--rb-border);
}

.beat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.beat-number {
  font-size: 14px;
  font-weight: 600;
  color: var(--rb-text-primary);
}

.beat-form {
  margin: 0;
}

/* ===== Empty Editor ===== */
.editor-empty {
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

.empty-icon-big {
  color: var(--rb-text-subtle);
  margin-bottom: 16px;
}

.empty-main-text {
  font-size: 16px;
  font-weight: 500;
  color: var(--rb-text-secondary);
  margin: 0 0 4px;
}

.empty-sub-text {
  font-size: 13px;
  color: var(--rb-text-muted);
}

/* ===== Mobile ===== */
@media (max-width: 768px) {
  .outline-layout {
    flex-direction: column;
  }

  .tree-panel {
    width: 100%;
  }

  .tree-card {
    height: auto;
    max-height: 350px;
  }

  .editor-card {
    border-radius: 12px;
  }
}
</style>
