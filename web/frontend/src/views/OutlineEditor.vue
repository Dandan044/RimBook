<template>
  <div class="outline-editor">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon class="title-icon"><Document /></el-icon>
        写作规划
      </h1>
    </div>

    <!-- Persistent foundation progress (survives tab switches) -->
    <div
      v-if="foundationPlan.active || (foundationPlan.step > 0 && foundationPlan.status === 'running')"
      class="plan-banner foundation-banner"
    >
      <div class="plan-banner-steps">
        <div
          v-for="s in foundationBannerSteps"
          :key="s.num"
          class="plan-banner-step"
          :class="{
            active: foundationBannerStep === s.num && foundationPlan.active,
            done: foundationBannerStep > s.num,
          }"
        >
          <span class="plan-banner-dot">
            <el-icon v-if="foundationBannerStep === s.num && foundationPlan.active" class="is-loading"><Loading /></el-icon>
            <el-icon v-else-if="foundationBannerStep > s.num"><Check /></el-icon>
            <template v-else>{{ s.num }}</template>
          </span>
          <span>{{ s.label }}</span>
        </div>
      </div>
      <div class="plan-banner-msg">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>{{ foundationPlan.message || '正在生成项目基础设定…' }}</span>
        <span class="plan-banner-vol">基础设定</span>
      </div>
    </div>

    <!-- Persistent volume-plan progress (survives tab switches) -->
    <div v-if="volumePlan.active || (volumePlan.step > 0 && volumePlan.status === 'running')" class="plan-banner">
      <div class="plan-banner-steps">
        <div
          v-for="s in planSteps"
          :key="s.num"
          class="plan-banner-step"
          :class="{
            active: volumePlan.step === s.num && volumePlan.status === 'running',
            done: volumePlan.step > s.num || (volumePlan.step === s.num && volumePlan.status === 'done'),
          }"
        >
          <span class="plan-banner-dot">
            <el-icon v-if="volumePlan.step === s.num && volumePlan.status === 'running'" class="is-loading"><Loading /></el-icon>
            <el-icon v-else-if="volumePlan.step > s.num || (volumePlan.step === s.num && volumePlan.status === 'done')"><Check /></el-icon>
            <template v-else>{{ s.num }}</template>
          </span>
          <span>{{ s.label }}</span>
        </div>
      </div>
      <div class="plan-banner-msg">
        <el-icon class="is-loading"><Loading /></el-icon>
        <span>{{ volumePlan.message || '正在规划…' }}</span>
        <span v-if="volumePlan.volume" class="plan-banner-vol">第 {{ volumePlan.volume }} 卷</span>
      </div>
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
                <span class="ai-hero-title">生成项目基础设定</span>
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
                <span class="ai-hero-desc">规划卷大纲 → 生成连续 beat 链 → 细化并组装为章节</span>
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
                  <el-button type="danger" plain :loading="deleting" @click="confirmDeleteVolume">
                    <el-icon><Delete /></el-icon> 删除卷
                  </el-button>
                </div>

                <!-- Volume Beat Pipeline Panel -->
                <VolumeBeatPanel
                  v-if="store.currentId && editingVolume"
                  ref="beatPanelRef"
                  :project-id="store.currentId"
                  :volume-number="editingVolume.number"
                  @assembled="fetchData"
                />
              </div>
            </div>

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
                  <el-form-item label="卷"><el-input-number v-model="chapterForm.volume" :min="1" /></el-form-item>
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

                <div class="keynote-section">
                  <h3 class="beats-heading">章基调</h3>
                  <p class="keynote-hint">2–5 条本章特有约束，勿套公式前缀；必须渗透进剧情，禁止在正文中明说或总结。</p>
                  <div v-for="(_k, ki) in chapterForm.keynote" :key="'kn'+ki" class="keynote-row">
                    <el-input v-model="chapterForm.keynote[ki]" size="small" placeholder="如：近距离跟林默，吊坠只当遗物，章末停在门缝的光" />
                    <el-button type="danger" size="small" text @click="chapterForm.keynote.splice(ki, 1)">
                      <el-icon><Delete /></el-icon>
                    </el-button>
                  </div>
                  <el-button size="small" @click="chapterForm.keynote.push('')">
                    <el-icon><Plus /></el-icon> 添加基调
                  </el-button>
                </div>

                <div class="beats-section">
                  <h3 class="beats-heading">场景 Beat / 细场景</h3>
                  <div v-for="(beat, i) in chapterForm.beats" :key="i" class="beat-item">
                    <div class="beat-card">
                      <div class="beat-header">
                        <span class="beat-number">Beat {{ i + 1 }}</span>
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

                      <div class="micro-scenes">
                        <div class="micro-scenes-title">细场景（{{ (beat.scenes || []).length }}）</div>
                        <div v-for="(sc, si) in (beat.scenes || [])" :key="si" class="micro-card">
                          <div class="beat-header">
                            <span class="beat-number">细场景 {{ si + 1 }}</span>
                            <el-button type="danger" size="small" text @click="beat.scenes!.splice(si, 1)">
                              <el-icon><Delete /></el-icon>
                            </el-button>
                          </div>
                          <el-form label-width="80px" size="small">
                            <el-form-item label="创作意图"><el-input v-model="sc.intent" type="textarea" :rows="2" placeholder="本段要让读者感到什么（环境/沉默/物件/人物均可）" /></el-form-item>
                            <el-form-item label="感官/氛围"><el-input v-model="sc.sensory" type="textarea" :rows="2" placeholder="可空；环境与感官方向" /></el-form-item>
                            <el-form-item label="动作"><el-input v-model="sc.action" type="textarea" :rows="2" placeholder="可空；无人场景请留空" /></el-form-item>
                            <el-form-item label="对白方向"><el-input v-model="sc.dialogue" placeholder="可空；无对白请留空" /></el-form-item>
                            <el-form-item label="事件"><el-input v-model="sc.event" placeholder="可空；有剧情转折才填" /></el-form-item>
                            <el-form-item label="手法"><el-input v-model="sc.technique" /></el-form-item>
                            <el-form-item label="节奏"><el-input v-model="sc.pacing" placeholder="缓起/加速/留白/爆发…" /></el-form-item>
                            <el-form-item label="篇幅">
                              <el-input-number v-model="sc.words" :min="0" :step="50" controls-position="right" />
                            </el-form-item>
                          </el-form>
                        </div>
                        <el-button size="small" @click="addMicroScene(beat)">
                          <el-icon><Plus /></el-icon> 添加细场景
                        </el-button>
                      </div>
                    </div>
                  </div>
                  <el-button size="small" @click="chapterForm.beats.push({ goal: '', conflict: '', outcome: '', entities: [], scenes: [] })">
                    <el-icon><Plus /></el-icon> 添加 Beat
                  </el-button>
                </div>

                <el-form label-width="60px" style="margin-top:20px">
                  <el-form-item label="附注">
                    <el-input v-model="chapterForm.notes" type="textarea" :rows="3" placeholder="作者备忘（可选，不再承载手法/剧情）" />
                  </el-form-item>
                </el-form>
                <div class="editor-footer">
                  <el-button type="primary" @click="saveChapter">
                    <el-icon><Check /></el-icon> 保存
                  </el-button>
                  <el-button type="danger" plain :loading="deleting" @click="confirmDeleteChapter">
                    <el-icon><Delete /></el-icon> 删除章
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

      <el-tab-pane label="完整设定集" name="entities" lazy>
        <PlanningEntities />
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

    <el-dialog v-model="showSynopsisDialog" :title="synopsisOverwrite ? '重新生成项目基础设定' : '生成项目基础设定'" width="560px">
      <el-alert
        v-if="synopsisOverwrite"
        type="warning"
        :closable="false"
        show-icon
        title="将覆盖当前宏观梗概，并增量补充完整设定集"
        style="margin-bottom: 12px"
      />
      <p class="foundation-hint">
        将先生成宏观梗概与粗略设定，再按世界观 → 时间线 → 势力 → 地点 → 角色 → 物品逐层细化详情。
        每层即时保存，单条失败不会丢失已完成内容。
      </p>
      <div class="world-budget">
        <div class="world-budget-title">
          <span>世界规模</span>
          <el-tag size="small" effect="plain">{{ expansionBudgetInfo.cost }}</el-tag>
        </div>
        <el-radio-group v-model="expansionCoefficient" class="world-budget-options">
          <el-radio-button :value="1">1 · 核心世界</el-radio-button>
          <el-radio-button :value="2">2 · 邻域扩展</el-radio-button>
          <el-radio-button :value="3">3 · 区域世界</el-radio-button>
          <el-radio-button :value="4">4 · 宏大世界</el-radio-button>
        </el-radio-group>
        <p>{{ expansionBudgetInfo.description }}</p>
        <el-alert
          v-if="expansionCoefficient === 4"
          type="warning"
          :closable="false"
          title="宏大世界最多递归三层，模型调用与生成时间会显著增加。"
        />
      </div>
      <el-input v-model="premiseText" type="textarea" :rows="6" placeholder="输入小说创意/核心设定…" />
      <template #footer>
        <el-button @click="showSynopsisDialog = false" :disabled="generating">取消</el-button>
        <el-button type="primary" @click="doGenerateSynopsis" :loading="generating">
          <el-icon><MagicStick /></el-icon> {{ synopsisOverwrite ? '覆盖并生成' : '生成项目基础设定' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectStore } from '../stores/project'
import {
  getSynopsis, updateSynopsis, generateFoundationSSE, getFoundationStatus,
  listVolumes, planVolume, updateVolume, deleteVolume,
  listChapters, planChapter, updateChapter, regenerateChapter, deleteChapter,
  planVolumeSSE, assembleVolumeSSE, getVolumePlanStatus,
  type VolumeOutline, type ChapterOutline, type SceneBeat, type MicroScene,
  type PlanSSEHandle,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'
import NarrativePanel from './Narrative.vue'
import PlanningEntities from './PlanningEntities.vue'
import VolumeBeatPanel from './VolumeBeatPanel.vue'

const store = useProjectStore()
const route = useRoute()
const router = useRouter()
const localBusy = ref(false)
const generating = computed(() =>
  localBusy.value || store.volumePlan.active || store.foundationPlan.active,
)
const volumePlan = computed(() => store.volumePlan)
const foundationPlan = computed(() => store.foundationPlan)
const planSteps = [
  { num: 1, label: '卷大纲' },
  { num: 2, label: '设定扩充' },
  { num: 3, label: 'Beat 链' },
  { num: 4, label: '细化组装' },
]

function bannerStepFromRaw(step: number, coefficient: number): number {
  if (step <= 0) return 1
  if (step === 1) return 1
  if (step === 2) return 2
  if (step >= 9 && coefficient > 1) return 4
  return 3
}

const foundationBannerSteps = computed(() => {
  const steps = [
    { num: 1, label: '宏观梗概' },
    { num: 2, label: '设定集初始化' },
    { num: 3, label: '分层详情' },
  ]
  if (foundationPlan.value.expansionCoefficient > 1) {
    steps.push({ num: 4, label: '世界扩展' })
  }
  return steps
})

const foundationBannerStep = computed(() =>
  bannerStepFromRaw(foundationPlan.value.step, foundationPlan.value.expansionCoefficient),
)
const deleting = ref(false)
const mainTab = ref('outline')

const VALID_TABS = new Set(['outline', 'entities', 'threads', 'style', 'recap', 'review'])

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
const expansionCoefficient = ref(1)
let foundationSseHandle: PlanSSEHandle | null = null
const expansionBudgetInfo = computed(() => {
  const presets: Record<number, { cost: string; description: string }> = {
    1: { cost: '当前成本', description: '保持当前流程，不递归扩展隐含人物与地点。' },
    2: { cost: '最多 +12 条', description: '从核心设定向外扩展一层，优先关键人物与关系节点。' },
    3: { cost: '最多 +28 条', description: '递归两层，形成较完整的区域社会、历史与人物网络。' },
    4: { cost: '最多 +55 条', description: '递归三层，生成高密度世界网络，适合长篇大型项目。' },
  }
  return presets[expansionCoefficient.value] || presets[1]
})

const beatPanelRef = ref<InstanceType<typeof VolumeBeatPanel> | null>(null)
let planSseHandle: PlanSSEHandle | null = null

function wireVolumePlanHandlers(opts?: { onDoneExtra?: () => void | Promise<void> }) {
  return {
    onProgress: (msg: string) => {
      store.patchVolumePlan({ message: msg, active: true, status: 'running' })
      beatPanelRef.value?.setRunning(true, msg)
    },
    onStep: (data: { step: number; status: string; phase?: string; message?: string; beats?: unknown[]; volume?: number | { number?: number } }) => {
      const volNum = typeof data.volume === 'number'
        ? data.volume
        : (data.volume && typeof data.volume === 'object' ? data.volume.number : undefined)
      store.applyVolumePlanStep({
        ...data,
        volume: volNum,
        message: data.message || (data.status === 'running' ? `步骤 ${data.step} 进行中…` : data.status === 'done' ? `步骤 ${data.step} 完成` : ''),
      })
      if (volNum) store.patchVolumePlan({ volume: volNum })
      // Default progress messages when backend omits them on done events.
      if (!data.message) {
        if (data.status === 'running') {
          const defaults: Record<number, string> = {
            1: '正在生成卷大纲与结局…',
            2: '正在扩充本卷出场设定…',
            3: '正在生成连续 beat 链…',
            4: '正在细化并组装章节…',
          }
          store.patchVolumePlan({ message: defaults[data.step] || store.volumePlan.message })
        } else if (data.status === 'done') {
          const defaults: Record<number, string> = {
            1: '卷大纲已生成',
            2: '本卷设定扩充完成',
            3: 'Beat 链已生成',
            4: '章节组装完成',
          }
          store.patchVolumePlan({ message: defaults[data.step] || store.volumePlan.message })
        }
      }
      beatPanelRef.value?.handlePipelineStep(data as any)
    },
    onError: (msg: string) => {
      store.finishVolumePlan({ error: msg })
      beatPanelRef.value?.setRunning(false)
      ElMessage.error(msg)
    },
    onDone: async () => {
      const volNum = store.volumePlan.volume
      store.finishVolumePlan()
      beatPanelRef.value?.setRunning(false)
      await fetchData()
      if (volNum && volumes.value.length) {
        const vol = volumes.value.find(v => v.number === volNum) || volumes.value[volumes.value.length - 1]
        editing.value = 'volume'
        editingVolume.value = vol
        Object.assign(volumeForm, { title: vol.title, arc: vol.arc, ending: vol.ending })
        beatPanelRef.value?.loadBeats()
      }
      await opts?.onDoneExtra?.()
      ElMessage.success('卷规划完成（含 beat 细化与章节组装）')
    },
  }
}

function attachVolumePlanSse(opts?: { resume?: boolean; title?: string; volume?: number; op?: string }) {
  if (!store.currentId) return
  planSseHandle?.close()
  const handlers = wireVolumePlanHandlers()
  const resume = !!opts?.resume
  if (opts?.op === 'assemble_volume' && opts.volume) {
    planSseHandle = assembleVolumeSSE(store.currentId, opts.volume, handlers, { resume })
  } else {
    planSseHandle = planVolumeSSE(store.currentId, handlers, opts?.title || '', { resume })
  }
  store.bindVolumePlanSse(planSseHandle)
}

async function resumeVolumePlanIfNeeded() {
  if (!store.currentId) return
  try {
    const st = await getVolumePlanStatus(store.currentId)
    if (!st.active || !st.volume) return
    store.startVolumePlanTracking({
      op: (st.op as 'plan_volume' | 'assemble_volume') || 'plan_volume',
      volume: st.volume,
      message: st.progress || '恢复进度…',
    })
    if (st.step) store.applyVolumePlanStep(st.step)
    attachVolumePlanSse({
      resume: true,
      volume: st.volume,
      op: st.op,
    })
  } catch { /* ignore */ }
}

function onVolumePlanResume(ev: Event) {
  const detail = (ev as CustomEvent).detail || {}
  attachVolumePlanSse({ resume: true, volume: detail.volume, op: detail.op })
}

const volumeForm = reactive({ title: '', arc: '', ending: '' })
const chapterForm = reactive({
  title: '', volume: null as number | null, entities: [] as string[],
  tags: [] as string[], beats: [] as SceneBeat[], notes: '',
  keynote: [] as string[],
  purpose: '', value_shift: '', tension: 0, hook: '', story_date: '', elapsed: '',
})

function addMicroScene(beat: SceneBeat) {
  if (!beat.scenes) beat.scenes = []
  beat.scenes.push({
    intent: '', sensory: '', action: '', dialogue: '', event: '',
    technique: '', pacing: '', words: 300,
  })
}

function cloneBeat(b: SceneBeat): SceneBeat {
  return {
    goal: b.goal,
    conflict: b.conflict,
    outcome: b.outcome,
    entities: [...(b.entities || [])],
    scenes: (b.scenes || []).map((s: MicroScene) => ({
      intent: s.intent || s.event || s.action || '',
      sensory: s.sensory || '',
      action: s.action || '',
      dialogue: s.dialogue || '',
      event: s.event || '',
      technique: s.technique || '',
      pacing: s.pacing || '',
      words: s.words || 0,
    })),
  }
}

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
      beats: node.chapter.beats.map((b: SceneBeat) => cloneBeat(b)),
      notes: node.chapter.notes,
      keynote: [...(node.chapter.keynote || [])],
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
        '当前已有宏观梗概。继续将覆盖梗概，并增量补充完整设定集。',
        '覆盖并生成项目基础设定？',
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
        '将根据创意生成宏观梗概、完整设定集与详情；世界规模高于 1 时会继续自动扩展关系网络。是否继续？',
        '生成项目基础设定',
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

function wireFoundationPlanHandlers() {
  return {
    onProgress: (msg: string) => {
      store.patchFoundationPlan({ message: msg, active: true, status: 'running' })
    },
    onStep: (data: {
      step: number
      status: string
      phase?: string
      message?: string
      entry_type?: string
      current?: number
      total?: number
      expansion_coefficient?: number
    }) => {
      store.applyFoundationPlanStep({
        ...data,
        message: data.message
          || (data.status === 'running'
            ? `步骤 ${data.step} 进行中…`
            : data.status === 'done'
              ? `步骤 ${data.step} 完成`
              : ''),
      })
      if (data.step === 1 && data.status === 'done' && store.currentId) {
        getSynopsis(store.currentId).then(r => { synopsisText.value = r.text }).catch(() => {})
      }
    },
    onError: (msg: string) => {
      store.finishFoundationPlan({ error: msg })
      ElMessage.error(msg)
    },
    onDone: async () => {
      store.finishFoundationPlan()
      if (store.currentId) {
        try {
          const r = await getSynopsis(store.currentId)
          synopsisText.value = r.text
        } catch { /* ignore */ }
      }
      editing.value = 'synopsis'
      ElMessage.success({
        message: '项目基础设定已生成。可前往「完整设定集」查看条目。',
        duration: 4000,
      })
      mainTab.value = 'entities'
    },
  }
}

function attachFoundationPlanSse(opts?: { resume?: boolean; premise?: string; coefficient?: number }) {
  if (!store.currentId) return
  foundationSseHandle?.close()
  const handlers = wireFoundationPlanHandlers()
  const resume = !!opts?.resume
  foundationSseHandle = generateFoundationSSE(
    store.currentId,
    opts?.premise || '',
    handlers,
    opts?.coefficient ?? store.foundationPlan.expansionCoefficient,
    { resume },
  )
  store.bindFoundationPlanSse(foundationSseHandle)
}

async function resumeFoundationPlanIfNeeded() {
  if (!store.currentId) return
  try {
    const st = await getFoundationStatus(store.currentId)
    if (!st.active) return
    const coefficient = st.expansion_coefficient
      ?? st.step?.expansion_coefficient
      ?? store.foundationPlan.expansionCoefficient
      ?? 1
    store.startFoundationPlanTracking({
      message: st.progress || '恢复进度…',
      expansionCoefficient: coefficient,
    })
    if (st.step) store.applyFoundationPlanStep(st.step)
    attachFoundationPlanSse({ resume: true, coefficient })
  } catch { /* ignore */ }
}

function onFoundationPlanResume() {
  void resumeFoundationPlanIfNeeded()
}

async function doGenerateSynopsis() {
  if (!store.currentId) return
  const premise = premiseText.value
  const coefficient = expansionCoefficient.value
  store.startFoundationPlanTracking({
    message: '准备中…',
    expansionCoefficient: coefficient,
  })
  showSynopsisDialog.value = false
  attachFoundationPlanSse({
    premise,
    coefficient,
  })
}

async function confirmAddVolume() {
  if (!store.currentId) return
  const nextNum = volumes.value.length
    ? Math.max(...volumes.value.map(v => v.number)) + 1
    : 1
  try {
    await ElMessageBox.confirm(
      `将由 AI 规划第 ${nextNum} 卷：\n① 卷大纲\n② 本卷设定扩充\n③ 连续 Beat 链\n④ 章节细化组装\n\n全流程约需 1-2 分钟，完成后你可以编辑 beat 再重新组装。是否继续？`,
      '规划新卷（四步管线）',
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
  const nextNum = volumes.value.length
    ? Math.max(...volumes.value.map(v => v.number)) + 1
    : 1
  store.startVolumePlanTracking({
    op: 'plan_volume',
    volume: nextNum,
    message: `正在规划第 ${nextNum} 卷…`,
  })
  beatPanelRef.value?.setRunning(true, `正在规划第 ${nextNum} 卷…`)
  attachVolumePlanSse({ title: '' })
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
  localBusy.value = true
  try {
    const lastVol = volumes.value[volumes.value.length - 1].number
    const c = await planChapter(store.currentId, { volume: lastVol })
    await fetchData()
    ElMessage.success(`第${c.number}章 beat 已规划`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '规划失败')
  } finally {
    localBusy.value = false
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
  localBusy.value = true
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
      beats: c.beats.map(b => cloneBeat(b)), notes: c.notes,
      keynote: [...(c.keynote || [])],
      purpose: c.purpose || '', value_shift: c.value_shift || '', tension: c.tension || 0,
      hook: c.hook || '', story_date: c.story_date || '', elapsed: c.elapsed || '',
    })
    editingChapter.value = c
    ElMessage.success('Beat 已重新生成')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '生成失败') }
  finally { localBusy.value = false }
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
    keynote: chapterForm.keynote.filter(k => k.trim()),
    purpose: chapterForm.purpose, value_shift: chapterForm.value_shift,
    tension: chapterForm.tension, hook: chapterForm.hook,
    story_date: chapterForm.story_date, elapsed: chapterForm.elapsed,
  } as any)
  ElMessage.success('已保存')
  await fetchData()
}

onMounted(async () => {
  await fetchData()
  await resumeVolumePlanIfNeeded()
  await resumeFoundationPlanIfNeeded()
  window.addEventListener('volume-plan-resume', onVolumePlanResume)
  window.addEventListener('foundation-plan-resume', onFoundationPlanResume)
})
onUnmounted(() => {
  window.removeEventListener('volume-plan-resume', onVolumePlanResume)
  window.removeEventListener('foundation-plan-resume', onFoundationPlanResume)
  // Keep SSE alive in store across remounts — do not abort here.
})
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
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.plan-banner {
  margin-bottom: 14px;
  padding: 12px 16px;
  border: 1px solid var(--rb-border-light);
  border-radius: 12px;
  background: linear-gradient(180deg, var(--rb-primary-bg), var(--rb-bg-surface));
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.plan-banner-steps {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.plan-banner-step {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--rb-text-muted);
  font-weight: 500;
}

.plan-banner-step.active {
  color: var(--rb-primary);
  font-weight: 600;
}

.plan-banner-step.done {
  color: var(--el-color-success, #67c23a);
}

.plan-banner-dot {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 2px solid currentColor;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  background: var(--rb-bg-surface);
  color: inherit;
}

.plan-banner-step.active .plan-banner-dot {
  background: var(--rb-primary-bg);
  color: var(--rb-primary);
}

.plan-banner-msg {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--rb-text-primary);
}

.plan-banner-vol {
  margin-left: auto;
  font-size: 12px;
  color: var(--rb-primary);
  font-weight: 600;
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

.foundation-hint {
  margin: 0 0 12px;
  color: var(--rb-text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.world-budget {
  margin: 0 0 14px;
  padding: 13px;
  border: 1px solid var(--rb-border-light);
  border-radius: 10px;
  background: var(--rb-bg-subtle);
}
.world-budget-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  font-weight: 700;
}
.world-budget-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
  width: 100%;
}
.world-budget-options :deep(.el-radio-button__inner) {
  width: 100%;
  border: 1px solid var(--rb-border-light) !important;
  border-radius: 7px !important;
  box-shadow: none !important;
}
.world-budget p {
  margin: 10px 0 0;
  color: var(--rb-text-secondary);
  font-size: 12px;
  line-height: 1.6;
}
.world-budget .el-alert { margin-top: 10px; }

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

.keynote-section {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--rb-border-light);
}

.keynote-hint {
  margin: -6px 0 12px;
  font-size: 12px;
  color: var(--rb-text-muted);
}

.keynote-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
}

.micro-scenes {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--rb-border-light);
}

.micro-scenes-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--rb-text-secondary);
  margin-bottom: 8px;
}

.micro-card {
  background: var(--rb-bg-surface, #fff);
  border: 1px solid var(--rb-border-light);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 8px;
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
