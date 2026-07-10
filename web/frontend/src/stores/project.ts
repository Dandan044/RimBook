import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  listProjects,
  createProject,
  deleteProject,
  getProjectStatus,
  type ProjectInfo,
  type ProjectStatus,
} from '../api'

export const useProjectStore = defineStore('project', () => {
  const projects = ref<ProjectInfo[]>([])
  const currentId = ref<string>('')
  const status = ref<ProjectStatus | null>(null)
  const loading = ref(false)

  const currentProject = computed(() =>
    projects.value.find(p => p.id === currentId.value)
  )

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
    projects,
    currentId,
    status,
    loading,
    currentProject,
    fetchProjects,
    createNew,
    removeProject,
    fetchStatus,
    selectProject,
  }
})
