<template>
  <div class="outline-editor">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon class="title-icon"><Document /></el-icon>
        写作规划
      </h1>
    </div>

    <el-tabs v-model="mainTab" class="planning-tabs">
      <el-tab-pane label="大纲" name="outline">
        <div class="outline-tab">
        <!-- Hero AI actions -->
        <div class="ai-hero">
          <div class="ai-hero-label">AI 创作</div>
          <div class="ai-hero-actions">
            <button
              type="button"
              class="ai-hero-card primary"
              :disabled="generating"
              @click="generateSynopsis"
            >
              <span class="ai-hero-icon"><el-icon :size="22"><MagicStick /></el-icon></span>
              <span class="ai-hero-body">
                <span class="ai-hero-title">生成梗概</span>
                <span class="ai-hero-desc">从创意出发，生成全书故事骨架</span>
              </span>
              <el-icon v-if="generating" class="is-loading ai-hero-loading"><Loading /></el-icon>
            </button>
            <button
              type="button"
              class="ai-hero-card"
              :disabled="generating"
              @click="confirmAddVolume"
            >
              <span class="ai-hero-icon"><el-icon :size="22"><FolderAdd /></el-icon></span>
              <span class="ai-hero-body">
                <span class="ai-hero-title">新卷</span>
                <span class="ai-hero-desc">规划卷大纲、结局，并生成卷内全部章 beat</span>
              </span>
              <el-icon v-if="generating" class="is-loading ai-hero-loading"><Loading /></el-icon>
            </button>
            <button
              type="button"
              class="ai-hero-card"
              :disabled="generating || !volumes.length"
              @click="confirmAddChapter"
            >
              <span class="ai-hero-icon"><el-icon :size="22"><DocumentAdd /></el-icon></span>
              <span class="ai-hero-body">
                <span class="ai-hero-title">新章节</span>
                <span class="ai-hero-desc">{{ volumes.length ? '在最新一卷下追加一章 beat' : '请先规划卷后再生成章节' }}</span>
              </span>
              <el-icon v-if="generating" class="is-loading ai-hero-loading"><Loading /></el-icon>
            </button>
          </div>
        </div>

        <div class="outline-layout">
          <div class="tree-panel">
            <div class="tree-card">
              <div class="tree-header">
                <span class="tree-title">大纲结构</span>
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
            </div>
          </div>

          <div class="editor-panel">
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

            <div v-else-if="editing === 'volume' && editingVolume" class="editor-card">
              <div class="editor-header">
                <h2 class="editor-title">
                  <el-icon class="editor-title-icon"><Folder /></el-icon>
                  第{{ editingVolume.number }}卷《{{ editingVolume.title }}》
                </h2>
                <el-button type="danger" size="small" plain :loading="deleting" @click="confirmDeleteVolume">
                  <el-icon><Delete /></el-icon> 删除卷
                </el-button>
              </div>
              <div class="editor-body">
                <el-form :model="volumeForm" label-width="60px">
                  <el-form-item label="标题"><el-input v-model="volumeForm.title" /></el-form-item>
                  <el-form-item label="大纲">
                    <el-input v-model="volumeForm.arc" type="textarea" :rows="12" />
                  </el-form-item>
                  <el-form-item label="结局"><el-input v-model="volumeForm.ending" type="textarea" :rows="4" /></el-form-item>
                  <el-form-item v-if="(editingVolume.chapters || []).length" label="章节">
                    <span class="muted-meta">第 {{ editingVolume.chapters.join('、') }} 章（由系统维护）</span>
                  </el-form-item>
                  <el-form-item v-if="editingVolume.recap" label="回顾">
                    <el-alert type="info" :closable="false" class="recap-alert">
                      <template #title>实际剧情回顾（由摘要自动生成，只读）</template>
                      <div class="recap-text">{{ editingVolume.recap }}</div>
                    </el-alert>
                  </el-form-item>
                </el-form>
                <div class="editor-footer">
                  <el-button type="primary" @click="saveVolume">
                    <el-icon><Check /></el-icon> 保存
                  </el-button>
                </div>
              </div>
            </div>

            <div v-else-if="editing === 'chapter' && editingChapter" class="editor-card">
              <div class="editor-header">
                <h2 class="editor-title">
                  <el-icon class="editor-title-icon"><EditPen /></el-icon>
                  第{{ editingChapter.number }}章《{{ editingChapter.title }}》
                </h2>
                <div class="editor-header-actions">
                  <el-button size="small" @click="generateBeat" :loading="generating">
                    <el-icon><MagicStick /></el-icon> LLM 生成 Beat
                  </el-button>
                  <el-button type="danger" size="small" plain :loading="deleting" @click="confirmDeleteChapter">
                    <el-icon><Delete /></el-icon> 删除章
                  </el-button>
                </div>
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

                <div class="pacing-section">
                  <h3 class="beats-heading">节奏与时间线</h3>
                  <el-form label-width="80px" size="small">
                    <el-form-item label="叙事功能">
                      <el-input v-model="chapterForm.purpose" placeholder="本章的叙事功能，如：推进主线 / 铺垫伏笔 / 情感缓冲" />
                    </el-form-item>
                    <el-form-item label="价值转变">
                      <el-input v-model="chapterForm.value_shift" placeholder="主角处境的变化，如：安全→危险、希望→绝望" />
                    </el-form-item>
                    <el-form-item label="张力">
                      <el-rate v-model="chapterForm.tension" :max="5" show-score score-template="{value}/5" clearable />
                    </el-form-item>
                    <el-form-item label="章末钩子">
                      <el-input v-model="chapterForm.hook" placeholder="章节结尾的悬念/钩子" />
                    </el-form-item>
                    <el-form-item label="故事日期">
                      <el-input v-model="chapterForm.story_date" placeholder="故事内时间，如：第三年春 / 王历1024年冬" style="max-width:300px" />
                    </el-form-item>
                    <el-form-item label="经过时长">
                      <el-input v-model="chapterForm.elapsed" placeholder="本章经过的时间，如：三天 / 半个时辰" style="max-width:300px" />
                    </el-form-item>
                  </el-form>
                </div>

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
        </div>
      </el-tab-pane>

      <el-tab-pane label="线索账本" name="threads" lazy>
        <NarrativePanel section="threads" />
      </el-tab-pane>
      <el-tab-pane label="风格指南" name="style" lazy>
        <NarrativePanel section="style" />
      </el-tab-pane>
      <el-tab-pane label="故事线" name="recap" lazy>
        <NarrativePanel section="recap" />
      </el-tab-pane>
      <el-tab-pane label="宏观审阅" name="review" lazy>
        <NarrativePanel section="review" />
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="showSynopsisDialog" :title="synopsisOverwrite ? '重新生成全书梗概' : '生成全书梗概'" width="500px">
      <el-alert
        v-if="synopsisOverwrite"
        type="warning"
        :closable="false"
        show-icon
        title="将覆盖当前已有梗概"
        style="margin-bottom: 12px"
      />
      <el-input v-model="premiseText" type="textarea" :rows="6" placeholder="输入小说创意/核心设定…" />
      <template #footer>
        <el-button @click="showSynopsisDialog = false">取消</el-button>
        <el-button type="primary" @click="doGenerateSynopsis" :loading="generating">
          <el-icon><MagicStick /></el-icon> {{ synopsisOverwrite ? '覆盖并生成' : '生成' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '../stores/project'
import {
  getSynopsis, updateSynopsis, generateSynopsis as apiGenerateSynopsis,
  listVolumes, planVolume, updateVolume, deleteVolume,
  listChapters, planChapter, updateChapter, regenerateChapter, deleteChapter,
  type VolumeOutline, type ChapterOutline, type SceneBeat,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import NarrativePanel from './Narrative.vue'

const store = useProjectStore()
const route = useRoute()
const router = useRouter()
const generating = ref(false)
const deleting = ref(false)
const mainTab = ref('outline')

const VALID_TABS = new Set(['outline', 'threads', 'style', 'recap', 'review'])

function syncTabFromRoute() {
  const q = String(route.query.tab || 'outline')
  mainTab.value = VALID_TABS.has(q) ? q : 'outline'
}

watch(mainTab, (tab) => {
  const current = String(route.query.tab || 'outline')
  if (current === tab) return
  const query = { ...route.query }
  if (tab === 'outline') delete query.tab
  else query.tab = tab
  router.replace({ query })
})

watch(() => route.query.tab, syncTabFromRoute, { immediate: true })
const editing = ref<'none' | 'synopsis' | 'volume' | 'chapter'>('none')
const synopsisText = ref('')
const volumes = ref<VolumeOutline[]>([])
const chapters = ref<ChapterOutline[]>([])
const editingVolume = ref<VolumeOutline | null>(null)
const editingChapter = ref<ChapterOutline | null>(null)

const showSynopsisDialog = ref(false)
const premiseText = ref('')
const synopsisOverwrite = ref(false)

const volumeForm = reactive({ title: '', arc: '', ending: '' })
const chapterForm = reactive({
  title: '', volume: null as number | null, entities: [] as string[],
  tags: [] as string[], beats: [] as SceneBeat[], notes: '',
  purpose: '', value_shift: '', tension: 0, hook: '', story_date: '', elapsed: '',
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
      purpose: node.chapter.purpose || '',
      value_shift: node.chapter.value_shift || '',
      tension: node.chapter.tension || 0,
      hook: node.chapter.hook || '',
      story_date: node.chapter.story_date || '',
      elapsed: node.chapter.elapsed || '',
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

async function generateSynopsis() {
  const existing = (synopsisText.value || '').trim()
  if (existing) {
    try {
      await ElMessageBox.confirm(
        '当前已有全书梗概。继续生成将用新内容覆盖现有梗概，此操作不可撤销。',
        '覆盖现有梗概？',
        {
          type: 'warning',
          confirmButtonText: '继续生成',
          cancelButtonText: '取消',
        },
      )
    } catch {
      return
    }
  } else {
    try {
      await ElMessageBox.confirm(
        '将根据你输入的创意，由 AI 生成全书梗概。是否继续？',
        '生成全书梗概',
        {
          type: 'info',
          confirmButtonText: '继续',
          cancelButtonText: '取消',
        },
      )
    } catch {
      return
    }
  }
  synopsisOverwrite.value = !!(synopsisText.value || '').trim()
  showSynopsisDialog.value = true
  premiseText.value = ''
}

async function doGenerateSynopsis() {
  if (!store.currentId) return
  generating.value = true
  try {
    const r = await apiGenerateSynopsis(store.currentId, premiseText.value)
    synopsisText.value = r.text
    showSynopsisDialog.value = false
    editing.value = 'synopsis'
    ElMessage.success('梗概已生成')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '生成失败') }
  finally { generating.value = false }
}

async function confirmAddVolume() {
  if (!store.currentId) return
  const nextNum = volumes.value.length
    ? Math.max(...volumes.value.map(v => v.number)) + 1
    : 1
  try {
    await ElMessageBox.confirm(
      `将由 AI 规划第 ${nextNum} 卷（大纲 + 结局），并一次性生成该卷全部章节 beat。已存在的卷不能重复规划。是否继续？`,
      '规划新卷',
      {
        type: 'info',
        confirmButtonText: '开始规划',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  await addVolume()
}

async function addVolume() {
  if (!store.currentId) return
  generating.value = true
  try {
    const result = await planVolume(store.currentId)
    await fetchData()
    editing.value = 'volume'
    editingVolume.value = result.volume
    Object.assign(volumeForm, {
      title: result.volume.title,
      arc: result.volume.arc,
      ending: result.volume.ending,
    })
    const n = result.chapters?.length || 0
    ElMessage.success(`第${result.volume.number}卷已规划，并生成 ${n} 章 beat`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '规划失败')
  } finally {
    generating.value = false
  }
}

async function confirmAddChapter() {
  if (!store.currentId) return
  if (!volumes.value.length) {
    ElMessage.warning('请先规划卷，才能生成章节')
    return
  }
  const nextNum = chapters.value.length
    ? Math.max(...chapters.value.map(c => c.number)) + 1
    : 1
  const lastVol = volumes.value[volumes.value.length - 1]
  try {
    await ElMessageBox.confirm(
      `将由 AI 规划第 ${nextNum} 章 beat，归属第 ${lastVol.number} 卷《${lastVol.title || '未命名'}》。是否继续？`,
      '规划新章节',
      {
        type: 'info',
        confirmButtonText: '开始规划',
        cancelButtonText: '取消',
      },
    )
  } catch {
    return
  }
  await addChapter()
}

async function addChapter() {
  if (!store.currentId) return
  if (!volumes.value.length) {
    ElMessage.warning('请先规划卷，才能生成章节')
    return
  }
  generating.value = true
  try {
    const lastVol = volumes.value[volumes.value.length - 1].number
    const c = await planChapter(store.currentId, { volume: lastVol })
    await fetchData()
    ElMessage.success(`第${c.number}章 beat 已规划`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '规划失败')
  } finally {
    generating.value = false
  }
}

async function generateBeat() {
  // Re-plan current chapter beat via LLM (preserves chapter number + summary)
  if (!store.currentId || !editingChapter.value) return
  const vol = editingChapter.value.volume ?? chapterForm.volume
  if (!vol) {
    ElMessage.warning('请先为本章指定所属卷并保存')
    return
  }
  generating.value = true
  try {
    const chNum = editingChapter.value.number
    const c = await regenerateChapter(store.currentId, chNum, {
      volume: vol,
      title: editingChapter.value.title,
    })
    const idx = chapters.value.findIndex(ch => ch.number === chNum)
    if (idx >= 0) chapters.value[idx] = c
    else chapters.value.push(c)
    Object.assign(chapterForm, {
      title: c.title, volume: c.volume, entities: [...c.entities], tags: [...c.tags],
      beats: c.beats.map(b => ({ ...b, entities: [...b.entities] })), notes: c.notes,
      purpose: c.purpose || '', value_shift: c.value_shift || '', tension: c.tension || 0,
      hook: c.hook || '', story_date: c.story_date || '', elapsed: c.elapsed || '',
    })
    editingChapter.value = c
    ElMessage.success('Beat 已重新生成')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '生成失败') }
  finally { generating.value = false }
}

async function confirmDeleteVolume() {
  if (!store.currentId || !editingVolume.value) return
  const vol = editingVolume.value
  const chCount = chapters.value.filter(c => c.volume === vol.number).length
  try {
    await ElMessageBox.confirm(
      `将删除第 ${vol.number} 卷《${vol.title || '未命名'}》及其下 ${chCount} 个章节大纲（含对应草稿/定稿，如有）。此操作不可撤销。`,
      '删除卷',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  deleting.value = true
  try {
    const r = await deleteVolume(store.currentId, vol.number)
    editing.value = 'none'
    editingVolume.value = null
    await fetchData()
    ElMessage.success(`已删除第 ${vol.number} 卷（含 ${r.deleted_chapters.length} 章）`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  } finally {
    deleting.value = false
  }
}

async function confirmDeleteChapter() {
  if (!store.currentId || !editingChapter.value) return
  const ch = editingChapter.value
  const draftHint = ch.has_draft ? '（该章已有正文草稿，将一并删除）' : ''
  try {
    await ElMessageBox.confirm(
      `将删除第 ${ch.number} 章《${ch.title || '未命名'}》大纲${draftHint}。此操作不可撤销。`,
      '删除章节',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  deleting.value = true
  try {
    await deleteChapter(store.currentId, ch.number)
    editing.value = 'none'
    editingChapter.value = null
    await fetchData()
    ElMessage.success(`已删除第 ${ch.number} 章`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  } finally {
    deleting.value = false
  }
}

async function saveVolume() {
  if (!store.currentId || !editingVolume.value) return
  await updateVolume(store.currentId, editingVolume.value.number, {
    title: volumeForm.title,
    arc: volumeForm.arc,
    ending: volumeForm.ending,
  } as any)
  ElMessage.success('已保存')
  await fetchData()
  const refreshed = volumes.value.find(v => v.number === editingVolume.value?.number)
  if (refreshed) {
    editingVolume.value = refreshed
    Object.assign(volumeForm, { title: refreshed.title, arc: refreshed.arc, ending: refreshed.ending })
  }
}

async function saveChapter() {
  if (!store.currentId || !editingChapter.value) return
  if (!chapterForm.volume) {
    ElMessage.warning('章节必须归属某一卷')
    return
  }
  await updateChapter(store.currentId, editingChapter.value.number, {
    title: chapterForm.title, volume: chapterForm.volume,
    entities: chapterForm.entities, tags: chapterForm.tags,
    beats: chapterForm.beats, notes: chapterForm.notes,
    purpose: chapterForm.purpose, value_shift: chapterForm.value_shift,
    tension: chapterForm.tension, hook: chapterForm.hook,
    story_date: chapterForm.story_date, elapsed: chapterForm.elapsed,
  } as any)
  ElMessage.success('已保存')
  await fetchData()
}

onMounted(fetchData)
</script>

<style scoped>
.outline-editor {
  /* Grow with content; single scroll lives on app-main */
  margin: -8px -8px 0;
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 48px);
}

.page-header {
  margin-bottom: 12px;
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

.planning-tabs {
  display: flex;
  flex-direction: column;
}

.planning-tabs :deep(.el-tabs__header) {
  flex-shrink: 0;
  margin-bottom: 16px;
}

.planning-tabs :deep(.el-tabs__content),
.planning-tabs :deep(.el-tab-pane) {
  height: auto;
  overflow: visible;
}

/* ===== AI Hero Actions ===== */
.outline-tab {
  display: flex;
  flex-direction: column;
}

.ai-hero {
  flex-shrink: 0;
  margin-bottom: 12px;
  padding: 12px 16px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.08) 0%, rgba(14, 165, 233, 0.06) 100%);
  border: 1px solid rgba(99, 102, 241, 0.18);
  border-radius: 16px;
}

.ai-hero-label {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--rb-primary);
  margin-bottom: 10px;
}

.ai-hero-actions {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.ai-hero-card {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px 16px;
  text-align: left;
  border: 1px solid var(--rb-border-light);
  border-radius: 12px;
  background: var(--rb-bg-surface);
  cursor: pointer;
  transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
  font: inherit;
  color: inherit;
  min-height: 76px;
  position: relative;
}

.ai-hero-card:hover:not(:disabled) {
  transform: translateY(-2px);
  border-color: var(--rb-primary);
  box-shadow: 0 8px 20px rgba(99, 102, 241, 0.12);
}

.ai-hero-card:disabled {
  opacity: 0.7;
  cursor: wait;
}

.ai-hero-card.primary {
  border-color: rgba(99, 102, 241, 0.35);
  background: linear-gradient(180deg, var(--rb-bg-surface) 0%, rgba(99, 102, 241, 0.06) 100%);
}

.ai-hero-icon {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--rb-primary);
  background: rgba(99, 102, 241, 0.12);
}

.ai-hero-card.primary .ai-hero-icon {
  background: var(--rb-primary);
  color: #fff;
}

.ai-hero-body {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.ai-hero-title {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--rb-text-primary);
}

.ai-hero-desc {
  font-size: 12px;
  line-height: 1.45;
  color: var(--rb-text-muted);
}

.ai-hero-loading {
  position: absolute;
  top: 12px;
  right: 12px;
  color: var(--rb-primary);
}

.outline-layout {
  display: flex;
  align-items: flex-start;
  gap: 20px;
  min-height: 640px;
}

/* ===== Tree Panel ===== */
.tree-panel {
  width: 300px;
  flex-shrink: 0;
  position: sticky;
  top: 0;
  align-self: flex-start;
}

.tree-card {
  background: var(--rb-bg-surface);
  border: 1px solid var(--rb-border-light);
  border-radius: 14px;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03);
  display: flex;
  flex-direction: column;
  min-height: 640px;
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
  padding: 12px 8px;
  /* No nested scroll — page scrolls as a whole */
  overflow: visible;
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
  overflow: visible;
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

.editor-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.muted-meta {
  color: var(--rb-text-secondary, #6b7280);
  font-size: 13px;
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

/* ===== Pacing Section ===== */
.pacing-section {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--rb-border-light);
}

.recap-alert {
  width: 100%;
}

.recap-text {
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.8;
  color: var(--rb-text-secondary);
  margin-top: 6px;
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
@media (max-width: 900px) {
  .ai-hero-actions {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .outline-layout {
    flex-direction: column;
    min-height: 0;
  }

  .tree-panel {
    width: 100%;
    position: static;
  }

  .tree-card {
    min-height: 0;
  }

  .tree-body {
    max-height: 320px;
    overflow-y: auto;
  }

  .editor-card {
    border-radius: 12px;
  }
}
</style>
