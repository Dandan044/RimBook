/**
 * RimBook API client — wraps all backend endpoints.
 */
import axios from 'axios'

const http = axios.create({ baseURL: '/api' })

// ---------- Types ----------

export interface ProjectInfo {
  id: string
  title: string
  author: string
  language: string
  path: string
}

export interface ProjectStatus {
  title: string
  author: string
  has_synopsis: boolean
  volume_count: number
  chapter_count: number
  draft_count: number
  codex_count: number
  chapters: ChapterProgress[]
}

export interface ChapterProgress {
  number: number
  title: string
  volume: number | null
  beat_count: number
  has_summary: boolean
  has_draft: boolean
}

export interface CodexEntry {
  id: string
  name: string
  type: string
  aliases: string[]
  tags: string[]
  related: string[]
  body: string
}

export interface SceneBeat {
  goal: string
  conflict: string
  outcome: string
  entities: string[]
}

export interface ChapterOutline {
  number: number
  title: string
  volume: number | null
  entities: string[]
  tags: string[]
  beats: SceneBeat[]
  notes: string
  summary: string
}

export interface VolumeOutline {
  number: number
  title: string
  arc: string
  chapters: number[]
  ending: string
}

export interface CheckIssue {
  severity: string
  category: string
  description: string
  evidence: string
  suggestion: string
}

// ---------- Global Config (workspace-level, shared by all projects) ----------

export const getGlobalConfig = () =>
  http.get<{ llm: { base_url: string; api_key: string; model: string; check_model: string | null; embedding: { base_url: string | null; api_key: string; model: string } } }>('/config').then(r => r.data)

export const updateGlobalConfig = (data: Record<string, unknown>) =>
  http.put<{ ok: boolean }>('/config', data).then(r => r.data)

// ---------- Project ----------

export const listProjects = () =>
  http.get<ProjectInfo[]>('/projects').then(r => r.data)

export const createProject = (data: {
  name: string; title?: string; author?: string; base_url?: string; model?: string
}) =>
  http.post<ProjectInfo>('/projects', data).then(r => r.data)

export const deleteProject = (projectId: string) =>
  http.delete<{ ok: boolean; deleted: string }>(`/projects/${projectId}`).then(r => r.data)

export const getProjectStatus = (projectId: string) =>
  http.get<ProjectStatus>(`/projects/${projectId}/status`).then(r => r.data)

export const getProjectConfig = (projectId: string) =>
  http.get(`/projects/${projectId}/config`).then(r => r.data)

export const updateProjectConfig = (projectId: string, data: Record<string, unknown>) =>
  http.put(`/projects/${projectId}/config`, data).then(r => r.data)

// ---------- Codex ----------

export const listCodex = (projectId: string, type?: string) =>
  http.get<CodexEntry[]>(`/projects/${projectId}/codex`, { params: { type } }).then(r => r.data)

export const addCodex = (projectId: string, entry: CodexEntry) =>
  http.post<CodexEntry>(`/projects/${projectId}/codex`, entry).then(r => r.data)

export const getCodex = (projectId: string, entryId: string) =>
  http.get<CodexEntry>(`/projects/${projectId}/codex/${entryId}`).then(r => r.data)

export const updateCodex = (projectId: string, entryId: string, data: Partial<CodexEntry>) =>
  http.put<CodexEntry>(`/projects/${projectId}/codex/${entryId}`, data).then(r => r.data)

export const deleteCodex = (projectId: string, entryId: string) =>
  http.delete(`/projects/${projectId}/codex/${entryId}`).then(r => r.data)

// ---------- Outline ----------

export const getSynopsis = (projectId: string) =>
  http.get<{ text: string }>(`/projects/${projectId}/outline/synopsis`).then(r => r.data)

export const updateSynopsis = (projectId: string, text: string) =>
  http.put(`/projects/${projectId}/outline/synopsis`, { text }).then(r => r.data)

export const generateSynopsis = (projectId: string, premise: string) =>
  http.post<{ text: string }>(`/projects/${projectId}/outline/synopsis`, { text: premise }).then(r => r.data)

export const listVolumes = (projectId: string) =>
  http.get<VolumeOutline[]>(`/projects/${projectId}/outline/volumes`).then(r => r.data)

export const planVolume = (projectId: string, title?: string) =>
  http.post<VolumeOutline>(`/projects/${projectId}/outline/volumes`, { title: title || '' }).then(r => r.data)

export const updateVolume = (projectId: string, number: number, data: Partial<VolumeOutline>) =>
  http.put<VolumeOutline>(`/projects/${projectId}/outline/volumes/${number}`, data).then(r => r.data)

export const listChapters = (projectId: string) =>
  http.get<ChapterOutline[]>(`/projects/${projectId}/outline/chapters`).then(r => r.data)

export const planChapter = (projectId: string, data: { volume?: number; title?: string; hint?: string }) =>
  http.post<ChapterOutline>(`/projects/${projectId}/outline/chapters`, data).then(r => r.data)

export const getChapter = (projectId: string, number: number) =>
  http.get<ChapterOutline>(`/projects/${projectId}/outline/chapters/${number}`).then(r => r.data)

export const updateChapter = (projectId: string, number: number, data: Partial<ChapterOutline>) =>
  http.put<ChapterOutline>(`/projects/${projectId}/outline/chapters/${number}`, data).then(r => r.data)

// ---------- Writer ----------

export const getDraft = (projectId: string, number: number) =>
  http.get<{ text: string; exists: boolean }>(`/projects/${projectId}/drafts/${number}`).then(r => r.data)

export const updateDraft = (projectId: string, number: number, text: string) =>
  http.put(`/projects/${projectId}/drafts/${number}`, { text }).then(r => r.data)

export const previewContext = (projectId: string, number: number) =>
  http.get(`/projects/${projectId}/context/${number}`).then(r => r.data)

export const checkChapter = (projectId: string, number: number, fix: boolean = false) =>
  http.post(`/projects/${projectId}/check/${number}`, { fix }).then(r => r.data)

export const reviseChapter = (projectId: string, number: number, instructions: string) =>
  http.post(`/projects/${projectId}/revise/${number}`, { instructions }).then(r => r.data)

export const regenerateSummary = (projectId: string, number: number) =>
  http.post<{ summary: string }>(`/projects/${projectId}/summary/${number}`).then(r => r.data)

// ---------- SSE write ----------

/** Open an SSE connection for chapter generation. Returns an EventSource. */
export function writeChapterSSE(
  projectId: string,
  number: number,
  handlers: {
    onProgress?: (msg: string) => void
    onContext?: (data: unknown) => void
    onDraft?: (data: unknown) => void
    onCheck?: (data: unknown) => void
    onError?: (msg: string) => void
    onDone?: (data: unknown) => void
  },
): EventSource {
  // We use POST with SSE via fetch-event-source pattern.
  // For simplicity, use native fetch + EventSource workaround:
  // FastAPI's sse-starlette supports GET; for POST we use fetch.
  // Simpler approach: just use fetch with streaming.
  const es = new EventSource(`/api/projects/${projectId}/write/${number}`)
  es.addEventListener('progress', (e: MessageEvent) => {
    const d = JSON.parse(e.data)
    handlers.onProgress?.(d.message || d)
  })
  es.addEventListener('context', (e: MessageEvent) => {
    handlers.onContext?.(JSON.parse(e.data))
  })
  es.addEventListener('draft', (e: MessageEvent) => {
    handlers.onDraft?.(JSON.parse(e.data))
  })
  es.addEventListener('check', (e: MessageEvent) => {
    handlers.onCheck?.(JSON.parse(e.data))
  })
  es.addEventListener('error', (e: MessageEvent) => {
    try {
      const d = JSON.parse((e as MessageEvent).data)
      handlers.onError?.(d.message || 'Unknown error')
    } catch {
      handlers.onError?.('Connection error')
    }
  })
  es.addEventListener('done', (e: MessageEvent) => {
    const d = e.data ? JSON.parse(e.data) : null
    handlers.onDone?.(d)
    es.close()
  })
  return es
}

// ---------- Snapshots ----------

export const listSnapshots = (projectId: string) =>
  http.get<{ snapshots: string[] }>(`/projects/${projectId}/snapshots`).then(r => r.data)

export const createSnapshot = (projectId: string) =>
  http.post<{ snapshot: string }>(`/projects/${projectId}/snapshots`).then(r => r.data)

// ---------- Connectivity tests ----------

export const testLLM = (projectId: string) =>
  http.post<{ ok: boolean; model?: string; reply?: string; usage?: Record<string, number>; error?: string }>(`/projects/${projectId}/test-llm`).then(r => r.data)

export const testEmbedding = (projectId: string) =>
  http.post<{ ok: boolean; model?: string; dimensions?: number; error?: string }>(`/projects/${projectId}/test-embedding`).then(r => r.data)
