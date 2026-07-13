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

export const useProjectStore = defineStore('project', () => {
  const projects = ref<ProjectInfo[]>([])
  const currentId = ref<string>('')
  const status = ref<ProjectStatus | null>(null)
  const loading = ref(false)

  // Track active write tasks (survives page navigation).
  const writeTasks = ref<Record<number, { started_at: string; progress: string }>>({})
  const writeTaskTimer = ref<ReturnType<typeof setInterval> | null>(null)

  const currentProject = computed(() =>
    projects.value.find(p => p.id === currentId.value)
  )

  function startWriteTracking(chapterNum: number) {
    writeTasks.value = {
      ...writeTasks.value,
      [chapterNum]: { started_at: new Date().toISOString(), progress: '准备中…' },
    }
    // Poll for status every 3 seconds.
    if (!writeTaskTimer.value) {
      writeTaskTimer.value = setInterval(pollWriteStatus, 3000)
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
          writeTasks.value[num].progress = s.progress
        } else {
          stopWriteTracking(num)
          // Trigger a draft reload event.
          window.dispatchEvent(new CustomEvent('write-complete', { detail: { chapter: num, draft_exists: s.draft_exists } }))
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
          writeTasks.value = {
            ...writeTasks.value,
            [t.chapter]: { started_at: t.started_at, progress: t.progress },
          }
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
    startWriteTracking, stopWriteTracking, checkPendingTasks,
  }
})
