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

export const useProjectStore = defineStore('project', () => {
  const projects = ref<ProjectInfo[]>([])
  const currentId = ref<string>('')
  const status = ref<ProjectStatus | null>(null)
  const loading = ref(false)

  // Track active write tasks (survives page navigation within the SPA).
  const writeTasks = ref<Record<number, WriteTaskState>>({})
  const writeTaskTimer = ref<ReturnType<typeof setInterval> | null>(null)

  const currentProject = computed(() =>
    projects.value.find(p => p.id === currentId.value)
  )

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
    fetchProjects, createNew, removeProject, fetchStatus, selectProject,
    startWriteTracking, stopWriteTracking, updateWriteStream, checkPendingTasks,
  }
})
