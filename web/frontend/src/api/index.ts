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
  // v2 structured fields
  revelations: { chapter: number; content: string; source: string }[]
  contradictions: { chapter: number; description: string; evidence: string; resolved: boolean }[]
  relationships: { target: string; type: string; since_chapter: number; notes: string }[]
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
  purpose: string
  value_shift: string
  tension: number
  hook: string
  story_date: string
  elapsed: string
  has_draft?: boolean
}

export interface VolumeOutline {
  number: number
  title: string
  arc: string
  chapters: number[]
  ending: string
  recap: string
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
  http.get<{ llm: { base_url: string; api_key: string; model: string; check_model: string | null; reasoning_effort: string | null; embedding: { base_url: string | null; api_key: string; model: string } } }>('/config').then(r => r.data)

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

export const regenerateChapter = (projectId: string, number: number, data: { volume?: number; title?: string; hint?: string }) =>
  http.post<ChapterOutline>(`/projects/${projectId}/outline/chapters/${number}/regenerate`, data).then(r => r.data)

// ---------- Narrative: style bible / threads / recap / review ----------

export interface PlotThread {
  id: string
  description: string
  type: string          // foreshadow | suspense | promise
  status: string        // open | progressed | resolved
  planted_chapter: number
  expected_resolve_chapter: number | null
  resolved_chapter: number | null
  updates: { chapter: number; note: string }[]
}

export const getStyle = (projectId: string) =>
  http.get<{ text: string }>(`/projects/${projectId}/style`).then(r => r.data)

export const updateStyle = (projectId: string, text: string) =>
  http.put<{ ok: boolean }>(`/projects/${projectId}/style`, { text }).then(r => r.data)

export const generateStyle = (projectId: string, chapters: number = 3) =>
  http.post<{ text: string }>(`/projects/${projectId}/style/generate`, { chapters }).then(r => r.data)

export const listThreads = (projectId: string, includeResolved: boolean = true) =>
  http.get<{ threads: PlotThread[] }>(`/projects/${projectId}/threads`, {
    params: { include_resolved: includeResolved },
  }).then(r => r.data)

export const updateThread = (
  projectId: string, threadId: string,
  data: Partial<Pick<PlotThread, 'description' | 'type' | 'status' | 'expected_resolve_chapter'>>,
) =>
  http.put<{ ok: boolean }>(`/projects/${projectId}/threads/${encodeURIComponent(threadId)}`, data).then(r => r.data)

export const deleteThread = (projectId: string, threadId: string) =>
  http.delete<{ ok: boolean }>(`/projects/${projectId}/threads/${encodeURIComponent(threadId)}`).then(r => r.data)

export const getStorySoFar = (projectId: string) =>
  http.get<{ text: string; upto_chapter: number }>(`/projects/${projectId}/recap/story`).then(r => r.data)

export const refreshStorySoFar = (projectId: string) =>
  http.post<{ text: string; upto_chapter: number }>(`/projects/${projectId}/recap/story`).then(r => r.data)

export const refreshVolumeRecap = (projectId: string, number: number) =>
  http.post<{ recap: string }>(`/projects/${projectId}/recap/volume/${number}`).then(r => r.data)

export const runMacroReview = (
  projectId: string,
  data: { volume?: number; from_chapter?: number; to_chapter?: number },
) =>
  http.post<{ scope: string; report: string; saved_as: string; chapters: number }>(
    `/projects/${projectId}/review`, data,
  ).then(r => r.data)

export const listReviews = (projectId: string) =>
  http.get<{ reviews: { name: string }[] }>(`/projects/${projectId}/reviews`).then(r => r.data)

export const getReview = (projectId: string, name: string) =>
  http.get<{ name: string; text: string }>(`/projects/${projectId}/reviews/${encodeURIComponent(name)}`).then(r => r.data)

// ---------- Writer ----------

export const getDraft = (projectId: string, number: number) =>
  http.get<{ text: string; exists: boolean }>(`/projects/${projectId}/drafts/${number}`).then(r => r.data)

export const updateDraft = (projectId: string, number: number, text: string) =>
  http.put(`/projects/${projectId}/drafts/${number}`, { text }).then(r => r.data)

export const previewContext = (projectId: string, number: number, live: boolean = false) =>
  http.get(`/projects/${projectId}/context/${number}`, { params: { live } }).then(r => r.data)

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
    onEnrichment?: (data: unknown) => void
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
  es.addEventListener('enrichment', (e: MessageEvent) => {
    handlers.onEnrichment?.(JSON.parse(e.data))
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

// ---------- Checkpoints / Branches (version management) ----------

export interface CheckpointInfo {
  name: string
  label: string
  timestamp: string
  branch: string
  parent: string | null
  file_count: number
}

export interface BranchInfo {
  name: string
  head: string
  is_current: boolean
  checkpoint_count: number
}

export const listCheckpoints = (projectId: string, branch?: string) =>
  http.get<{ checkpoints: CheckpointInfo[]; current_branch: string; fork_points: Record<string, string[]> }>(
    `/projects/${projectId}/checkpoints`, { params: branch ? { branch } : {} }
  ).then(r => r.data)

export const createCheckpoint = (projectId: string, data: { label?: string; files?: string[] } = {}) =>
  http.post<{ checkpoint: string; files: number; branch: string }>(`/projects/${projectId}/checkpoints`, data).then(r => r.data)

export const restoreCheckpoint = (projectId: string, name: string, files: string[] | null = null) =>
  http.post<{ restored: number; skipped: number }>(`/projects/${projectId}/checkpoints/${name}/restore`, { files }).then(r => r.data)

export const diffCheckpoint = (projectId: string, name: string) =>
  http.get<{ changed: { file: string; status: string }[]; added: string[] }>(`/projects/${projectId}/checkpoints/${name}/diff`).then(r => r.data)

export const deleteCheckpoint = (projectId: string, name: string) =>
  http.delete<{ ok: boolean }>(`/projects/${projectId}/checkpoints/${name}`).then(r => r.data)

// Branches
export const listBranches = (projectId: string) =>
  http.get<{ branches: BranchInfo[]; current: string; fork_points: Record<string, string[]> }>(
    `/projects/${projectId}/branches`
  ).then(r => r.data)

export const createBranch = (projectId: string, data: { name: string; from_checkpoint?: string | null }) =>
  http.post<{ ok: boolean; branch: string }>(`/projects/${projectId}/branches`, data).then(r => r.data)

export const switchBranch = (projectId: string, name: string) =>
  http.post<{ ok: boolean; branch: string; saved_checkpoint: string | null }>(`/projects/${projectId}/branches/${name}/switch`).then(r => r.data)

export const deleteBranch = (projectId: string, name: string) =>
  http.delete<{ ok: boolean }>(`/projects/${projectId}/branches/${name}`).then(r => r.data)

export const getBranchHistory = (projectId: string, name: string) =>
  http.get<{ branch: string; history: CheckpointInfo[]; fork_points: Record<string, string[]> }>(
    `/projects/${projectId}/branches/${name}/history`
  ).then(r => r.data)

/** Fork a new branch from the last pre-write checkpoint of chapter *number* and switch to it. */
export const forkForRegen = (projectId: string, number: number, branchName?: string) =>
  http.post<{
    ok: boolean; branch: string; from_checkpoint: string; from_checkpoint_label: string
    previous_branch: string; saved_checkpoint: string | null; hint: string
  }>(`/projects/${projectId}/chapters/${number}/fork-for-regen`, { branch_name: branchName || '' }).then(r => r.data)

// ---------- Server management ----------

export interface ServerStatus {
  running: boolean
  pid: number | null
  port: number | null
  url: string | null
}

export interface ServerResult {
  running: boolean
  pid?: number
  port?: number
  url?: string
  action?: string
  error?: string
}

export const getServerStatus = () =>
  http.get<ServerStatus>('/server/status').then(r => r.data)

export const startServer = (data?: { workspace?: string; port?: number }) =>
  http.post<ServerResult>('/server/start', data || {}).then(r => r.data)

export const stopServer = () =>
  http.post<ServerResult>('/server/stop').then(r => r.data)

export const restartServer = (data?: { workspace?: string; port?: number }) =>
  http.post<ServerResult>('/server/restart', data || {}).then(r => r.data)

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

// ---------- Write status (poll when SSE disconnects) ----------

export const getWriteStatus = (projectId: string, number: number) =>
  http.get<{ active: boolean; progress: string; started_at: string; draft_exists?: boolean; op?: string }>(
    `/projects/${projectId}/write-status/${number}`
  ).then(r => r.data)

export const getTasks = (projectId: string) =>
  http.get<{ tasks: { op: string; chapter: number | null; started_at: string; progress: string }[] }>(
    `/projects/${projectId}/tasks`
  ).then(r => r.data)

// ---------- Prompts / Workflow ----------

export interface PromptPlaceholder {
  name: string
  desc: string
  source: string
}

export interface PromptEntry {
  key: string
  stage: string
  role: string
  zh_name: string
  zh_module: string
  description: string
  placeholders: PromptPlaceholder[]
  in_use: boolean
  default_value: string
  value: string
  overridden: boolean
}

export const getPrompts = () =>
  http.get<{ prompts: PromptEntry[]; stages: string[] }>('/prompts').then(r => {
    // Guard against a stale backend serving the SPA HTML for /api/prompts
    // (would otherwise surface as "undefined has no property length").
    if (typeof r.data !== 'object' || r.data == null || !Array.isArray(r.data.prompts)) {
      throw new Error('后端返回格式异常：请重启后端以加载新的 /api/prompts 路由。')
    }
    return r.data
  })

export const updatePrompt = (key: string, value: string) =>
  http.put<PromptEntry>(`/prompts/${encodeURIComponent(key)}`, { value }).then(r => r.data)

export const resetPrompt = (key: string) =>
  http.delete<PromptEntry>(`/prompts/${encodeURIComponent(key)}`).then(r => r.data)

export const resetAllPrompts = () =>
  http.post<{ ok: boolean }>('/prompts/reset').then(r => r.data)

export const previewPrompt = (
  projectId: string,
  key: string,
  params: { number?: number; premise?: string; instructions?: string } = {},
) =>
  http.get<{ rendered: string }>(`/projects/${projectId}/prompts/${encodeURIComponent(key)}/preview`, {
    params: { number: params.number ?? 1, premise: params.premise ?? '', instructions: params.instructions ?? '' },
  }).then(r => r.data)
