import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  listProjects,
  createProject,
  deleteProject,
  getProjectStatus,
  getWriteStatus,
  getTasks,
  type ProjectInfo,
  type ProjectStatus,
} from '../api'

export interface WriteTaskState {
  started_at: string
  progress: string
  stream_text: string
  active: boolean
}

export interface VolumePlanState {
  active: boolean
  op: 'plan_volume' | 'assemble_volume' | ''
  volume: number | null
  step: number
  status: 'idle' | 'running' | 'done'
  phase: string
  message: string
  error: string | null
}

export interface FoundationPlanState {
  active: boolean
  step: number
  status: 'idle' | 'running' | 'done'
  phase: string
  message: string
  error: string | null
  expansionCoefficient: number
  entryType: string
  current: number | null
  total: number | null
}

export const useProjectStore = defineStore('project', () => {
  const projects = ref<ProjectInfo[]>([])
  const currentId = ref<string>('')
  const status = ref<ProjectStatus | null>(null)
  const loading = ref(false)

  // Track active write tasks (survives page navigation within the SPA).
  const writeTasks = ref<Record<number, WriteTaskState>>({})
  const writeTaskTimer = ref<ReturnType<typeof setInterval> | null>(null)

  // Volume plan / assemble pipeline (survives tab switches & remounts).
  const volumePlan = ref<VolumePlanState>({
    active: false,
    op: '',
    volume: null,
    step: 0,
    status: 'idle',
    phase: '',
    message: '',
    error: null,
  })
  let volumePlanSse: { close: () => void } | null = null

  // Foundation pipeline (survives tab switches & remounts).
  const foundationPlan = ref<FoundationPlanState>({
    active: false,
    step: 0,
    status: 'idle',
    phase: '',
    message: '',
    error: null,
    expansionCoefficient: 1,
    entryType: '',
    current: null,
    total: null,
  })
  let foundationPlanSse: { close: () => void } | null = null

  const currentProject = computed(() =>
    projects.value.find(p => p.id === currentId.value)
  )

  function patchVolumePlan(patch: Partial<VolumePlanState>) {
    volumePlan.value = { ...volumePlan.value, ...patch }
  }

  function resetVolumePlan() {
    volumePlanSse?.close()
    volumePlanSse = null
    volumePlan.value = {
      active: false,
      op: '',
      volume: null,
      step: 0,
      status: 'idle',
      phase: '',
      message: '',
      error: null,
    }
  }

  function applyVolumePlanStep(data: {
    step?: number
    status?: string
    phase?: string
    message?: string
    volume?: number
    beat_count?: number
  }) {
    patchVolumePlan({
      active: true,
      step: data.step ?? volumePlan.value.step,
      status: (data.status as VolumePlanState['status']) || volumePlan.value.status,
      phase: data.phase ?? volumePlan.value.phase,
      message: data.message || volumePlan.value.message,
      volume: data.volume ?? volumePlan.value.volume,
    })
  }

  function bindVolumePlanSse(handle: { close: () => void }, handlers?: {
    onDone?: (data: unknown) => void
    onError?: (msg: string) => void
  }) {
    volumePlanSse?.close()
    volumePlanSse = {
      close: () => {
        handle.close()
        volumePlanSse = null
      },
    }
    // The actual SSE callbacks are wired by the caller via the handle's
    // construction; this just owns the AbortController for teardown.
    void handlers
  }

  function startVolumePlanTracking(opts: {
    op: 'plan_volume' | 'assemble_volume'
    volume: number
    message?: string
  }) {
    patchVolumePlan({
      active: true,
      op: opts.op,
      volume: opts.volume,
      step: opts.op === 'assemble_volume' ? 3 : 1,
      status: 'running',
      phase: opts.op === 'assemble_volume' ? 'refining' : '',
      message: opts.message || '准备中…',
      error: null,
    })
  }

  function finishVolumePlan(opts?: { error?: string }) {
    volumePlanSse?.close()
    volumePlanSse = null
    if (opts?.error) {
      patchVolumePlan({
        active: false,
        status: 'idle',
        phase: '',
        error: opts.error,
        message: opts.error,
      })
    } else {
      patchVolumePlan({
        active: false,
        status: 'done',
        phase: '',
        error: null,
        message: '完成',
      })
    }
  }

  function patchFoundationPlan(patch: Partial<FoundationPlanState>) {
    foundationPlan.value = { ...foundationPlan.value, ...patch }
  }

  function resetFoundationPlan() {
    foundationPlanSse?.close()
    foundationPlanSse = null
    foundationPlan.value = {
      active: false,
      step: 0,
      status: 'idle',
      phase: '',
      message: '',
      error: null,
      expansionCoefficient: 1,
      entryType: '',
      current: null,
      total: null,
    }
  }

  function applyFoundationPlanStep(data: {
    step?: number
    status?: string
    phase?: string
    message?: string
    entry_type?: string
    current?: number
    total?: number
    expansion_coefficient?: number
  }) {
    patchFoundationPlan({
      active: true,
      step: data.step ?? foundationPlan.value.step,
      status: (data.status as FoundationPlanState['status']) || foundationPlan.value.status,
      phase: data.phase ?? foundationPlan.value.phase,
      message: data.message || foundationPlan.value.message,
      entryType: data.entry_type ?? foundationPlan.value.entryType,
      current: data.current ?? foundationPlan.value.current,
      total: data.total ?? foundationPlan.value.total,
      expansionCoefficient:
        data.expansion_coefficient
        ?? foundationPlan.value.expansionCoefficient,
    })
  }

  function bindFoundationPlanSse(handle: { close: () => void }) {
    foundationPlanSse?.close()
    foundationPlanSse = {
      close: () => {
        handle.close()
        foundationPlanSse = null
      },
    }
  }

  function startFoundationPlanTracking(opts: {
    message?: string
    expansionCoefficient?: number
  }) {
    patchFoundationPlan({
      active: true,
      step: 1,
      status: 'running',
      phase: '',
      message: opts.message || '准备中…',
      error: null,
      expansionCoefficient: opts.expansionCoefficient ?? 1,
      entryType: '',
      current: null,
      total: null,
    })
  }

  function finishFoundationPlan(opts?: { error?: string }) {
    foundationPlanSse?.close()
    foundationPlanSse = null
    if (opts?.error) {
      patchFoundationPlan({
        active: false,
        status: 'idle',
        phase: '',
        error: opts.error,
        message: opts.error,
      })
    } else {
      patchFoundationPlan({
        active: false,
        status: 'done',
        phase: '',
        error: null,
        message: '完成',
      })
    }
  }

  function startWriteTracking(chapterNum: number, seed?: Partial<WriteTaskState>) {
    const prev = writeTasks.value[chapterNum]
    writeTasks.value = {
      ...writeTasks.value,
      [chapterNum]: {
        started_at: seed?.started_at || prev?.started_at || new Date().toISOString(),
        progress: seed?.progress || prev?.progress || '准备中…',
        stream_text: seed?.stream_text ?? prev?.stream_text ?? '',
        active: seed?.active ?? true,
      },
    }
    if (!writeTaskTimer.value) {
      writeTaskTimer.value = setInterval(pollWriteStatus, 2000)
    }
  }

  function updateWriteStream(chapterNum: number, text: string, opts?: { replace?: boolean; progress?: string }) {
    const prev = writeTasks.value[chapterNum]
    if (!prev) return
    const stream_text = opts?.replace ? text : (prev.stream_text + text)
    writeTasks.value = {
      ...writeTasks.value,
      [chapterNum]: {
        ...prev,
        stream_text,
        progress: opts?.progress || prev.progress,
        active: true,
      },
    }
  }

  function stopWriteTracking(chapterNum: number) {
    const { [chapterNum]: _, ...rest } = writeTasks.value
    writeTasks.value = rest
    if (Object.keys(writeTasks.value).length === 0 && writeTaskTimer.value) {
      clearInterval(writeTaskTimer.value)
      writeTaskTimer.value = null
    }
  }

  async function pollWriteStatus() {
    if (!currentId.value) return
    for (const num of Object.keys(writeTasks.value).map(Number)) {
      try {
        const s = await getWriteStatus(currentId.value, num)
        if (s.active) {
          const prev = writeTasks.value[num]
          writeTasks.value = {
            ...writeTasks.value,
            [num]: {
              started_at: prev?.started_at || s.started_at || new Date().toISOString(),
              progress: s.progress || prev?.progress || '',
              stream_text: s.stream_text || prev?.stream_text || '',
              active: true,
            },
          }
        } else {
          stopWriteTracking(num)
          window.dispatchEvent(new CustomEvent('write-complete', {
            detail: { chapter: num, draft_exists: s.draft_exists, error: s.error },
          }))
        }
      } catch {
        // backend may be restarting; keep polling
      }
    }
  }

  // Check backend on page load if there are active tasks for this project.
  async function checkPendingTasks() {
    if (!currentId.value) return
    try {
      const s = await getTasks(currentId.value)
      for (const t of s.tasks) {
        if (t.chapter !== null && (t.op === 'write' || t.op === 'revise' || t.op === 'check')) {
          // Prefer write-status for stream_text when available.
          let stream_text = writeTasks.value[t.chapter]?.stream_text || ''
          try {
            const st = await getWriteStatus(currentId.value, t.chapter)
            if (st.stream_text) stream_text = st.stream_text
            if (!st.active) continue
          } catch { /* use task list info */ }
          startWriteTracking(t.chapter, {
            started_at: t.started_at,
            progress: t.progress,
            stream_text,
            active: true,
          })
        }
        if ((t.op === 'plan_volume' || t.op === 'assemble_volume') && t.chapter !== null) {
          startVolumePlanTracking({
            op: t.op as 'plan_volume' | 'assemble_volume',
            volume: t.chapter,
            message: t.progress,
          })
          // Notify OutlineEditor to re-attach SSE (avoids circular import).
          window.dispatchEvent(new CustomEvent('volume-plan-resume', {
            detail: { op: t.op, volume: t.chapter },
          }))
        }
        if (t.op === 'foundation') {
          startFoundationPlanTracking({
            message: t.progress || '恢复进度…',
          })
          window.dispatchEvent(new CustomEvent('foundation-plan-resume'))
        }
      }
    } catch { /* no-op */ }
  }

  async function fetchProjects() {
    projects.value = await listProjects()
    if (!currentId.value && projects.value.length > 0) {
      currentId.value = projects.value[0].id
    }
  }

  async function createNew(data: { name: string; title?: string; author?: string }) {
    const p = await createProject(data)
    projects.value.push(p)
    currentId.value = p.id
    return p
  }

  async function removeProject(id: string) {
    await deleteProject(id)
    projects.value = projects.value.filter(p => p.id !== id)
    if (currentId.value === id) {
      currentId.value = projects.value.length > 0 ? projects.value[0].id : ''
      status.value = null
    }
  }

  async function fetchStatus() {
    if (!currentId.value) return
    loading.value = true
    try {
      status.value = await getProjectStatus(currentId.value)
    } finally {
      loading.value = false
    }
  }

  function selectProject(id: string) {
    currentId.value = id
    status.value = null
  }

  return {
    projects, currentId, status, loading, currentProject, writeTasks,
    volumePlan,
    foundationPlan,
    fetchProjects, createNew, removeProject, fetchStatus, selectProject,
    startWriteTracking, stopWriteTracking, updateWriteStream, checkPendingTasks,
    patchVolumePlan, resetVolumePlan, applyVolumePlanStep,
    startVolumePlanTracking, finishVolumePlan, bindVolumePlanSse,
    patchFoundationPlan, resetFoundationPlan, applyFoundationPlanStep,
    startFoundationPlanTracking, finishFoundationPlan, bindFoundationPlanSse,
  }
})
