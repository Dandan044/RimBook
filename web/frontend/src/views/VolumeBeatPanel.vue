<template>
  <div class="beat-panel">
    <!-- Step Indicator -->
    <div class="step-indicator">
      <div
        v-for="s in steps"
        :key="s.num"
        class="step-item"
        :class="{ active: currentStep === s.num, done: currentStep > s.num || (currentStep === s.num && stepStatus === 'done') }"
      >
        <div class="step-dot">
          <el-icon v-if="currentStep === s.num && stepStatus === 'running'" class="is-loading"><Loading /></el-icon>
          <el-icon v-else-if="currentStep > s.num || (currentStep === s.num && stepStatus === 'done')"><Check /></el-icon>
          <span v-else>{{ s.num }}</span>
        </div>
        <span class="step-label">{{ s.label }}</span>
        <div v-if="s.num < 3" class="step-line" :class="{ filled: currentStep > s.num }" />
      </div>
      <span v-if="phaseLabel" class="phase-label">{{ phaseLabel }}</span>
    </div>

    <!-- Running overlay -->
    <div v-if="running" class="running-overlay">
      <el-icon class="is-loading" :size="20"><Loading /></el-icon>
      <span>{{ progressMsg || '正在处理…' }}</span>
    </div>

    <!-- Beat Chain -->
    <div v-if="beats.length" class="beat-chain-section">
      <div class="beat-chain-header">
        <span class="beat-chain-title">Beat 链（{{ beats.length }} 个）</span>
        <div class="beat-chain-actions">
          <el-button size="small" @click="showAddBeat = true">
            <el-icon><Plus /></el-icon> 添加
          </el-button>
          <el-button
            size="small"
            type="primary"
            :loading="running"
            :disabled="!canAssemble"
            @click="doAssemble"
          >
            <el-icon><MagicStick /></el-icon> 重新组装
          </el-button>
        </div>
      </div>

      <div class="beat-chain-scroll">
        <div
          v-for="(beat, idx) in beats"
          :key="beat.id"
          class="beat-node"
          :class="{ selected: selectedBeatId === beat.id, editing: editingBeatId === beat.id }"
          @click="selectBeat(beat)"
        >
          <div class="beat-node-id">{{ beat.id }}</div>
          <div class="beat-node-goal">{{ beat.goal || '(未填写)' }}</div>
          <div class="beat-node-momentum" v-if="beat.momentum">{{ beat.momentum }}</div>
          <div class="beat-node-connector" v-if="idx < beats.length - 1">→</div>
        </div>
      </div>
    </div>

    <!-- Empty state -->
    <div v-else-if="!running && loaded" class="beat-empty">
      <span>暂无 beat 数据</span>
    </div>

    <!-- Beat Detail Editor -->
    <div v-if="selectedBeat" class="beat-detail">
      <div class="beat-detail-header">
        <span class="beat-detail-title">编辑 {{ selectedBeat.id }}</span>
        <div class="beat-detail-actions">
          <el-button size="small" type="danger" plain @click="doDeleteBeat(selectedBeat.id)">
            <el-icon><Delete /></el-icon> 删除
          </el-button>
          <el-button size="small" @click="selectedBeatId = null">关闭</el-button>
        </div>
      </div>
      <el-form label-width="60px" size="small" class="beat-detail-form">
        <el-form-item label="目标">
          <el-input v-model="editForm.goal" @change="markDirty" />
        </el-form-item>
        <el-form-item label="冲突">
          <el-input v-model="editForm.conflict" @change="markDirty" />
        </el-form-item>
        <el-form-item label="结果">
          <el-input v-model="editForm.outcome" @change="markDirty" />
        </el-form-item>
        <el-form-item label="动量">
          <el-input v-model="editForm.momentum" placeholder="把故事从什么状态推向什么状态" @change="markDirty" />
        </el-form-item>
        <el-form-item label="实体">
          <el-select v-model="editForm.entities" multiple filterable allow-create default-first-option @change="markDirty" />
        </el-form-item>
      </el-form>
      <div v-if="dirty" class="beat-detail-save">
        <el-button size="small" type="primary" @click="saveBeatEdit">
          <el-icon><Check /></el-icon> 保存修改
        </el-button>
      </div>
    </div>

    <!-- Add Beat Dialog -->
    <el-dialog v-model="showAddBeat" title="添加 Beat" width="480px" append-to-body>
      <el-form label-width="60px" size="small">
        <el-form-item label="目标"><el-input v-model="newBeat.goal" /></el-form-item>
        <el-form-item label="冲突"><el-input v-model="newBeat.conflict" /></el-form-item>
        <el-form-item label="结果"><el-input v-model="newBeat.outcome" /></el-form-item>
        <el-form-item label="动量"><el-input v-model="newBeat.momentum" /></el-form-item>
        <el-form-item label="实体">
          <el-select v-model="newBeat.entities" multiple filterable allow-create default-first-option />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddBeat = false">取消</el-button>
        <el-button type="primary" @click="doAddBeat">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getVolumeBeats, updateVolumeBeats, addVolumeBeat, deleteVolumeBeat,
  assembleVolumeSSE,
  type RawBeat, type VolumeBeatData, type PlanSSEHandle,
} from '../api'
import { useProjectStore } from '../stores/project'

const props = defineProps<{
  projectId: string
  volumeNumber: number
}>()

const emit = defineEmits<{
  (e: 'assembled'): void
  (e: 'step', data: { step: number; status: string; phase?: string }): void
}>()

const store = useProjectStore()

const steps = [
  { num: 1, label: '卷规划' },
  { num: 2, label: 'Beat 链' },
  { num: 3, label: '细化组装' },
]

const loaded = ref(false)
const running = ref(false)
const progressMsg = ref('')
const currentStep = ref(0)
const stepStatus = ref<'idle' | 'running' | 'done'>('idle')
const phase = ref('')
const beats = ref<RawBeat[]>([])
const beatData = ref<VolumeBeatData | null>(null)
const selectedBeatId = ref<string | null>(null)
const editingBeatId = ref<string | null>(null)
const dirty = ref(false)
const showAddBeat = ref(false)
let sseHandle: PlanSSEHandle | null = null

const editForm = reactive({ goal: '', conflict: '', outcome: '', momentum: '', entities: [] as string[] })
const newBeat = reactive({ goal: '', conflict: '', outcome: '', momentum: '', entities: [] as string[] })

const selectedBeat = computed(() => beats.value.find(b => b.id === selectedBeatId.value) || null)
const canAssemble = computed(() => beats.value.length >= 3 && !running.value && !store.volumePlan.active)
const phaseLabel = computed(() => {
  if (phase.value === 'refining') return '细化中…'
  if (phase.value === 'grouping') return '分组中…'
  return ''
})

// Mirror store pipeline state when this volume is the active job target.
watch(
  () => store.volumePlan,
  (vp) => {
    if (!vp.active && vp.status !== 'running') {
      if (running.value && vp.volume === props.volumeNumber) {
        running.value = false
      }
      return
    }
    if (vp.volume !== null && vp.volume !== props.volumeNumber) return
    running.value = vp.active
    currentStep.value = vp.step || currentStep.value
    stepStatus.value = vp.status
    phase.value = vp.phase || ''
    if (vp.message) progressMsg.value = vp.message
  },
  { deep: true, immediate: true },
)

// Load beat data when volume changes
watch(() => props.volumeNumber, loadBeats, { immediate: true })

async function loadBeats() {
  if (!props.projectId || !props.volumeNumber) return
  loaded.value = false
  try {
    const data = await getVolumeBeats(props.projectId, props.volumeNumber)
    beatData.value = data
    beats.value = data.raw_beats || []
    // Don't clobber an in-flight pipeline indicator.
    if (!store.volumePlan.active || store.volumePlan.volume !== props.volumeNumber) {
      currentStep.value = data.step || 0
      stepStatus.value = data.step >= 3 ? 'done' : (data.step > 0 ? 'done' : 'idle')
    }
  } catch {
    beats.value = []
    if (!store.volumePlan.active) currentStep.value = 0
  }
  loaded.value = true
}

function selectBeat(beat: RawBeat) {
  selectedBeatId.value = beat.id
  editingBeatId.value = beat.id
  dirty.value = false
  Object.assign(editForm, {
    goal: beat.goal,
    conflict: beat.conflict,
    outcome: beat.outcome,
    momentum: beat.momentum,
    entities: [...beat.entities],
  })
}

function markDirty() {
  dirty.value = true
}

async function saveBeatEdit() {
  if (!selectedBeat.value) return
  const updated = beats.value.map(b =>
    b.id === selectedBeat.value!.id
      ? { ...b, goal: editForm.goal, conflict: editForm.conflict, outcome: editForm.outcome, momentum: editForm.momentum, entities: [...editForm.entities] }
      : b
  )
  try {
    await updateVolumeBeats(props.projectId, props.volumeNumber, updated)
    beats.value = updated
    dirty.value = false
    ElMessage.success('Beat 已更新')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  }
}

async function doAddBeat() {
  try {
    const r = await addVolumeBeat(props.projectId, props.volumeNumber, { ...newBeat })
    beats.value.push({
      id: r.id,
      goal: newBeat.goal,
      conflict: newBeat.conflict,
      outcome: newBeat.outcome,
      momentum: newBeat.momentum,
      entities: [...newBeat.entities],
    })
    showAddBeat.value = false
    Object.assign(newBeat, { goal: '', conflict: '', outcome: '', momentum: '', entities: [] })
    ElMessage.success(`已添加 ${r.id}`)
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '添加失败')
  }
}

async function doDeleteBeat(beatId: string) {
  try {
    await ElMessageBox.confirm(`确定删除 beat「${beatId}」？`, '删除 Beat', { type: 'warning' })
  } catch { return }
  try {
    await deleteVolumeBeat(props.projectId, props.volumeNumber, beatId)
    beats.value = beats.value.filter(b => b.id !== beatId)
    if (selectedBeatId.value === beatId) selectedBeatId.value = null
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

function doAssemble() {
  running.value = true
  progressMsg.value = '正在细化 beat 并组装章节…'
  currentStep.value = 3
  stepStatus.value = 'running'
  phase.value = 'refining'
  store.startVolumePlanTracking({
    op: 'assemble_volume',
    volume: props.volumeNumber,
    message: '正在细化 beat 并组装章节…',
  })

  sseHandle = assembleVolumeSSE(props.projectId, props.volumeNumber, {
    onProgress: (msg) => {
      progressMsg.value = msg
      store.patchVolumePlan({ message: msg, active: true, status: 'running' })
    },
    onStep: (data) => {
      currentStep.value = data.step
      stepStatus.value = data.status as any
      if (data.phase) phase.value = data.phase
      if (data.message) progressMsg.value = data.message as string
      store.applyVolumePlanStep(data)
      emit('step', data)
    },
    onError: (msg) => {
      running.value = false
      stepStatus.value = 'idle'
      store.finishVolumePlan({ error: msg })
      ElMessage.error(msg)
    },
    onDone: () => {
      running.value = false
      stepStatus.value = 'done'
      phase.value = ''
      store.finishVolumePlan()
      ElMessage.success('章节组装完成')
      emit('assembled')
      loadBeats()
    },
  })
  store.bindVolumePlanSse(sseHandle)
}

/** Called by parent when the full v2 pipeline SSE sends step events. */
function handlePipelineStep(data: { step: number; status: string; phase?: string; message?: string; beats?: RawBeat[] }) {
  currentStep.value = data.step
  stepStatus.value = data.status as any
  if (data.phase) phase.value = data.phase
  if (data.message) progressMsg.value = data.message
  if (data.status === 'running') running.value = true
  if (data.beats) beats.value = data.beats
  emit('step', data)
}

function setRunning(val: boolean, msg?: string) {
  running.value = val
  if (msg) progressMsg.value = msg
}

defineExpose({ handlePipelineStep, setRunning, loadBeats })
</script>

<style scoped>
.beat-panel {
  margin-top: 16px;
  padding: 16px;
  background: var(--rb-bg-subtle, #f9fafb);
  border: 1px solid var(--rb-border-light, #e5e7eb);
  border-radius: 12px;
  position: relative;
}

/* Step Indicator */
.step-indicator {
  display: flex;
  align-items: center;
  gap: 0;
  margin-bottom: 16px;
}

.step-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.step-dot {
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  border: 2px solid var(--rb-border, #d1d5db);
  color: var(--rb-text-muted, #9ca3af);
  background: var(--rb-bg-surface, #fff);
  transition: all 0.2s;
}

.step-item.active .step-dot {
  border-color: var(--rb-primary, #6366f1);
  color: var(--rb-primary, #6366f1);
  background: var(--rb-primary-bg);
}

.step-item.done .step-dot {
  border-color: var(--el-color-success, #67c23a);
  color: #fff;
  background: var(--el-color-success, #67c23a);
}

.step-label {
  font-size: 12px;
  color: var(--rb-text-muted, #9ca3af);
  font-weight: 500;
}

.step-item.active .step-label {
  color: var(--rb-primary, #6366f1);
  font-weight: 600;
}

.step-item.done .step-label {
  color: var(--el-color-success, #67c23a);
}

.step-line {
  width: 32px;
  height: 2px;
  background: var(--rb-border-light, #e5e7eb);
  margin: 0 8px;
}

.step-line.filled {
  background: var(--el-color-success, #67c23a);
}

.phase-label {
  margin-left: 12px;
  font-size: 12px;
  color: var(--rb-primary, #6366f1);
  font-weight: 500;
}

/* Running overlay */
.running-overlay {
  position: absolute;
  inset: 0;
  background: color-mix(in srgb, var(--rb-bg-base) 88%, transparent);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border-radius: 12px;
  z-index: 10;
  font-size: 14px;
  color: var(--rb-text-primary);
}

/* Beat Chain */
.beat-chain-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.beat-chain-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--rb-text-primary, #1f2937);
}

.beat-chain-actions {
  display: flex;
  gap: 8px;
}

.beat-chain-scroll {
  display: flex;
  gap: 4px;
  overflow-x: auto;
  padding: 8px 0;
  align-items: flex-start;
}

.beat-node {
  flex-shrink: 0;
  width: 140px;
  padding: 10px 12px;
  background: var(--rb-bg-surface, #fff);
  border: 1px solid var(--rb-border-light, #e5e7eb);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
  position: relative;
}

.beat-node:hover {
  border-color: var(--rb-primary, #6366f1);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.1);
}

.beat-node.selected {
  border-color: var(--rb-primary, #6366f1);
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.2);
}

.beat-node-id {
  font-size: 11px;
  font-weight: 700;
  color: var(--rb-primary, #6366f1);
  margin-bottom: 4px;
}

.beat-node-goal {
  font-size: 12px;
  line-height: 1.4;
  color: var(--rb-text-primary, #1f2937);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.beat-node-momentum {
  font-size: 11px;
  color: var(--rb-text-muted, #9ca3af);
  margin-top: 4px;
  font-style: italic;
}

.beat-node-connector {
  position: absolute;
  right: -12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--rb-text-muted, #9ca3af);
  font-size: 14px;
  z-index: 1;
}

/* Beat Detail */
.beat-detail {
  margin-top: 16px;
  padding: 16px;
  background: var(--rb-bg-surface, #fff);
  border: 1px solid var(--rb-border-light, #e5e7eb);
  border-radius: 10px;
}

.beat-detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.beat-detail-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--rb-text-primary, #1f2937);
}

.beat-detail-actions {
  display: flex;
  gap: 8px;
}

.beat-detail-form {
  margin: 0;
}

.beat-detail-save {
  margin-top: 12px;
  text-align: right;
}

/* Empty */
.beat-empty {
  text-align: center;
  padding: 24px;
  color: var(--rb-text-muted, #9ca3af);
  font-size: 13px;
}
</style>
