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

export interface MicroScene {
  intent: string
  sensory: string
  action: string
  dialogue: string
  event: string
  technique: string
  pacing: string
  words: number
}

export interface SceneBeat {
  goal: string
  conflict: string
  outcome: string
  entities: string[]
  scenes?: MicroScene[]
}

export interface ChapterOutline {
  number: number
  title: string
  volume: number | null
  entities: string[]
  tags: string[]
  beats: SceneBeat[]
  notes: string
  keynote?: string[]
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

// ---------- Author-side planning entities ----------
export interface EntityArc {
  start: string
  current: string
  destination: string
}

export interface PlanningCodexEntry {
  id: string
  name: string
  type: string
  aliases: string[]
  tags: string[]
  relationship_refs: string[]
  revealed_ref: string
  surface_summary: string
  secret_truth: string
  narrative_role: string
  reveal_strategy: string
  detail: string
  volume_roles: Record<string, string>
  field_locks: string[]
  source: string
  updated_at: string
  details: Record<string, unknown>
  body: string
}

export interface PlanningEntity {
  id: string
  name: string
  kind: string
  aliases: string[]
  tags: string[]
  story_role: string
  surface_goal: string
  inner_need: string
  fear: string
  values: string
  flaw: string
  secret: string
  capabilities: string
  limitations: string
  voice: string
  action_style: string
  arc: EntityArc
  volume_roles: Record<string, string>
  codex_ref: string
  field_locks: string[]
  source: string
  updated_at: string
}

export interface RelationshipArc {
  start: string
  current: string
  destination: string
}

export interface EntityRelationship {
  id: string
  source_id?: string
  target_id?: string
  source_entity_id: string
  target_entity_id: string
  relationship_type: string
  tags: string[]
  status: string
  source_goal: string
  target_goal: string
  stakes: string
  conflict: string
  secret: string
  arc: RelationshipArc
  field_locks: string[]
  source: string
  updated_at: string
}

export interface EntityNetwork {
  version: number
  entries?: PlanningCodexEntry[]
  entities: PlanningEntity[]
  relationships: EntityRelationship[]
  updated_at: string
}

export interface PlanningGraphNode {
  id: string
  name: string
  type: string
  summary: string
  narrative_role: string
  tags: string[]
  planned: boolean
  expansion_depth: number
  expansion_run_id: string
  degree: number
}

export interface PlanningGraphEdge {
  id: string
  source: string
  target: string
  relationship_type: string
  kind: 'explicit' | 'implicit_world'
  label: string
  conflict?: string
  stakes?: string
  status?: string
  tags?: string[]
}

export interface PlanningGraph {
  nodes: PlanningGraphNode[]
  edges: PlanningGraphEdge[]
}

export const getPlanningEntityNetwork = (projectId: string) =>
  http.get<EntityNetwork>(`/projects/${projectId}/planning-entities`).then(r => r.data)

export const getPlanningGraph = (
  projectId: string,
  params?: {
    types?: string[]
    focus?: string
    depth?: number
    includeImplicitWorld?: boolean
  },
) => http.get<PlanningGraph>(`/projects/${projectId}/planning-entities/graph`, {
  params: {
    types: params?.types?.join(',') || '',
    focus: params?.focus || undefined,
    depth: params?.depth ?? 1,
    include_implicit_world: params?.includeImplicitWorld ?? false,
  },
}).then(r => r.data)

export interface PlanningGraphLayout {
  nodes: Record<string, { x: number; y: number }>
  viewport: Record<string, number>
}

export const getPlanningGraphLayout = (projectId: string) =>
  http.get<PlanningGraphLayout>(`/projects/${projectId}/planning-entities/graph-layout`).then(r => r.data)

export const savePlanningGraphLayout = (projectId: string, layout: PlanningGraphLayout) =>
  http.put<{ ok: boolean }>(`/projects/${projectId}/planning-entities/graph-layout`, layout).then(r => r.data)

export const listPlanningEntries = (projectId: string, type?: string) =>
  http.get<PlanningCodexEntry[]>(`/projects/${projectId}/planning-entities/entries`, {
    params: type ? { type } : undefined,
  }).then(r => r.data)

export const addPlanningEntry = (projectId: string, entry: PlanningCodexEntry) =>
  http.post<PlanningCodexEntry>(`/projects/${projectId}/planning-entities/entries`, entry).then(r => r.data)

export const updatePlanningEntry = (projectId: string, entry: PlanningCodexEntry) =>
  http.put<PlanningCodexEntry>(`/projects/${projectId}/planning-entities/entries/${entry.id}`, entry).then(r => r.data)

export const deletePlanningEntry = (projectId: string, entryId: string) =>
  http.delete<{ ok: boolean }>(`/projects/${projectId}/planning-entities/entries/${entryId}`).then(r => r.data)

export const addPlanningEntity = (projectId: string, entity: PlanningEntity) =>
  http.post<PlanningEntity>(`/projects/${projectId}/planning-entities/entities`, entity).then(r => r.data)

export const updatePlanningEntity = (projectId: string, entity: PlanningEntity) =>
  http.put<PlanningEntity>(`/projects/${projectId}/planning-entities/entities/${entity.id}`, entity).then(r => r.data)

export const deletePlanningEntity = (projectId: string, entityId: string) =>
  http.delete<{ ok: boolean }>(`/projects/${projectId}/planning-entities/entities/${entityId}`).then(r => r.data)

export const addEntityRelationship = (projectId: string, relationship: EntityRelationship) =>
  http.post<EntityRelationship>(`/projects/${projectId}/planning-entities/relationships`, relationship).then(r => r.data)

export const updateEntityRelationship = (projectId: string, relationship: EntityRelationship) =>
  http.put<EntityRelationship>(`/projects/${projectId}/planning-entities/relationships/${relationship.id}`, relationship).then(r => r.data)

export const deleteEntityRelationship = (projectId: string, relationshipId: string) =>
  http.delete<{ ok: boolean }>(`/projects/${projectId}/planning-entities/relationships/${relationshipId}`).then(r => r.data)

export const setPlanningEntityFieldLock = (
  projectId: string,
  itemId: string,
  itemType: 'entity' | 'entry' | 'relationship',
  fieldName: string,
  locked: boolean,
) => http.put<{ ok: boolean }>(`/projects/${projectId}/planning-entities/locks/${itemId}`, {
  item_type: itemType,
  field_name: fieldName,
  locked,
}).then(r => r.data)

export const syncPlanningEntityNetwork = (projectId: string, volume?: number) =>
  http.post<Record<string, unknown>>(`/projects/${projectId}/planning-entities/sync`, { volume: volume ?? null }).then(r => r.data)

// ---------- Outline ----------

export const getSynopsis = (projectId: string) =>
  http.get<{ text: string }>(`/projects/${projectId}/outline/synopsis`).then(r => r.data)

export const updateSynopsis = (projectId: string, text: string) =>
  http.put(`/projects/${projectId}/outline/synopsis`, { text }).then(r => r.data)

export const generateSynopsis = (projectId: string, premise: string) =>
  http.post<{ text: string }>(`/projects/${projectId}/outline/synopsis`, { text: premise }).then(r => r.data)

export const listVolumes = (projectId: string) =>
  http.get<VolumeOutline[]>(`/projects/${projectId}/outline/volumes`).then(r => r.data)

export const updateVolume = (projectId: string, number: number, data: Partial<VolumeOutline>) =>
  http.put<VolumeOutline>(`/projects/${projectId}/outline/volumes/${number}`, data).then(r => r.data)

export const deleteVolume = (projectId: string, number: number) =>
  http.delete<{ ok: boolean; volume: number; deleted_chapters: number[] }>(
    `/projects/${projectId}/outline/volumes/${number}`,
  ).then(r => r.data)

export const listChapters = (projectId: string) =>
  http.get<ChapterOutline[]>(`/projects/${projectId}/outline/chapters`).then(r => r.data)

export const planChapter = (projectId: string, data: { volume: number; title?: string; hint?: string }) =>
  http.post<ChapterOutline>(`/projects/${projectId}/outline/chapters`, data).then(r => r.data)

export const getChapter = (projectId: string, number: number) =>
  http.get<ChapterOutline>(`/projects/${projectId}/outline/chapters/${number}`).then(r => r.data)

export const updateChapter = (projectId: string, number: number, data: Partial<ChapterOutline>) =>
  http.put<ChapterOutline>(`/projects/${projectId}/outline/chapters/${number}`, data).then(r => r.data)

export const regenerateChapter = (projectId: string, number: number, data: { volume: number; title?: string; hint?: string }) =>
  http.post<ChapterOutline>(`/projects/${projectId}/outline/chapters/${number}/regenerate`, data).then(r => r.data)

export const deleteChapter = (projectId: string, number: number) =>
  http.delete<{ ok: boolean; chapter: number }>(
    `/projects/${projectId}/outline/chapters/${number}`,
  ).then(r => r.data)

// ---------- Volume Planning v2 (beat chain → refine → assemble) ----------

export interface RawBeat {
  id: string
  goal: string
  conflict: string
  outcome: string
  entities: string[]
  momentum: string
}

export interface RefinedBeat extends RawBeat {
  technique: string
  plot_detail: string
  thematic_expr: string
  pacing_note: string
  is_bridge: boolean
}

export interface ChapterAssignment {
  chapter: number
  title: string
  beat_ids: string[]
  purpose: string
  value_shift: string
  tension: number
  hook: string
  story_date: string
  elapsed: string
}

export interface VolumeBeatData {
  volume: number
  step: number  // 0=none, 2=raw beats, 3=refined+grouped
  raw_beats: RawBeat[]
  refined_beats: RefinedBeat[]
  chapter_map: ChapterAssignment[]
}

export const getVolumeBeats = (projectId: string, volumeNumber: number) =>
  http.get<VolumeBeatData>(`/projects/${projectId}/outline/volumes/${volumeNumber}/beats`).then(r => r.data)

export const updateVolumeBeats = (projectId: string, volumeNumber: number, beats: RawBeat[]) =>
  http.put<{ ok: boolean; beat_count: number }>(
    `/projects/${projectId}/outline/volumes/${volumeNumber}/beats`, { beats },
  ).then(r => r.data)

export const addVolumeBeat = (projectId: string, volumeNumber: number, beat: Partial<RawBeat>) =>
  http.post<{ ok: boolean; id: string }>(
    `/projects/${projectId}/outline/volumes/${volumeNumber}/beats`, beat,
  ).then(r => r.data)

export const deleteVolumeBeat = (projectId: string, volumeNumber: number, beatId: string) =>
  http.delete<{ ok: boolean }>(
    `/projects/${projectId}/outline/volumes/${volumeNumber}/beats/${beatId}`,
  ).then(r => r.data)

export const reorderVolumeBeats = (projectId: string, volumeNumber: number, orderedIds: string[]) =>
  http.put<{ ok: boolean }>(
    `/projects/${projectId}/outline/volumes/${volumeNumber}/beats/reorder`, { ordered_ids: orderedIds },
  ).then(r => r.data)

export interface PlanSSEHandlers {
  onProgress?: (msg: string) => void
  onStep?: (data: { step: number; status: string; phase?: string; [key: string]: unknown }) => void
  onError?: (msg: string) => void
  onDone?: (data: unknown) => void
}

export interface PlanSSEHandle {
  close: () => void
}

export function generatePlanningEntryDetailSSE(
  projectId: string,
  entryId: string,
  handlers: PlanSSEHandlers,
): PlanSSEHandle {
  return _planningDetailSSE(
    `/api/projects/${projectId}/planning-entities/entries/${encodeURIComponent(entryId)}/detail`,
    {},
    handlers,
  )
}

export function generateMissingPlanningDetailsSSE(
  projectId: string,
  handlers: PlanSSEHandlers,
  onlyMissing = true,
): PlanSSEHandle {
  return _planningDetailSSE(
    `/api/projects/${projectId}/planning-entities/details`,
    { only_missing: onlyMissing },
    handlers,
  )
}

export function expandPlanningWorldSSE(
  projectId: string,
  coefficient: number,
  handlers: PlanSSEHandlers,
  seedIds: string[] = [],
): PlanSSEHandle {
  return _planningDetailSSE(
    `/api/projects/${projectId}/planning-entities/expand`,
    { coefficient, seed_ids: seedIds },
    handlers,
  )
}

function _planningDetailSSE(
  url: string,
  body: Record<string, unknown>,
  handlers: PlanSSEHandlers,
): PlanSSEHandle {
  const ctrl = new AbortController()
  ;(async () => {
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(body),
        signal: ctrl.signal,
        cache: 'no-store',
      })
      if (!res.ok || !res.body) {
        handlers.onError?.(`连接失败（HTTP ${res.status}）`)
        return
      }
      await _readSSEStream(res, handlers)
    } catch (e: any) {
      if (e?.name === 'AbortError') return
      handlers.onError?.(e?.message || '连接中断')
    }
  })()
  return { close: () => ctrl.abort() }
}

/** Stream the full v2 volume planning pipeline (Step 1–4) via SSE. */
export function planVolumeSSE(
  projectId: string,
  handlers: PlanSSEHandlers,
  title?: string,
  opts?: { resume?: boolean },
): PlanSSEHandle {
  const ctrl = new AbortController()
  const qs = opts?.resume ? '?resume=1' : ''
  const url = `/api/projects/${projectId}/outline/volumes/plan${qs}`

  ;(async () => {
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify({ title: title || '' }),
        signal: ctrl.signal,
        cache: 'no-store',
      })
      if (!res.ok || !res.body) {
        handlers.onError?.(`连接失败（HTTP ${res.status}）`)
        return
      }
      await _readSSEStream(res, handlers)
    } catch (e: any) {
      if (e?.name === 'AbortError') return
      handlers.onError?.(e?.message || '连接中断')
    }
  })()

  return { close: () => ctrl.abort() }
}

/** Foundation pipeline: synopsis + codex + detail layers (reconnectable SSE). */
export function generateFoundationSSE(
  projectId: string,
  premise: string,
  handlers: PlanSSEHandlers,
  expansionCoefficient = 1,
  opts?: { resume?: boolean },
): PlanSSEHandle {
  const ctrl = new AbortController()
  const qs = opts?.resume ? '?resume=1' : ''
  const url = `/api/projects/${projectId}/outline/foundation${qs}`

  ;(async () => {
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify({
          text: premise,
          expansion_coefficient: expansionCoefficient,
        }),
        signal: ctrl.signal,
        cache: 'no-store',
      })
      if (!res.ok || !res.body) {
        handlers.onError?.(`连接失败（HTTP ${res.status}）`)
        return
      }
      await _readSSEStream(res, handlers)
    } catch (e: any) {
      if (e?.name === 'AbortError') return
      handlers.onError?.(e?.message || '连接中断')
    }
  })()

  return { close: () => ctrl.abort() }
}

/** Re-run Step 4 (refine + assemble) via SSE. */
export function assembleVolumeSSE(
  projectId: string,
  volumeNumber: number,
  handlers: PlanSSEHandlers,
  opts?: { resume?: boolean },
): PlanSSEHandle {
  const ctrl = new AbortController()
  const qs = opts?.resume ? '?resume=1' : ''
  const url = `/api/projects/${projectId}/outline/volumes/${volumeNumber}/assemble${qs}`

  ;(async () => {
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        signal: ctrl.signal,
        cache: 'no-store',
      })
      if (!res.ok || !res.body) {
        handlers.onError?.(`连接失败（HTTP ${res.status}）`)
        return
      }
      await _readSSEStream(res, handlers)
    } catch (e: any) {
      if (e?.name === 'AbortError') return
      handlers.onError?.(e?.message || '连接中断')
    }
  })()

  return { close: () => ctrl.abort() }
}

export interface VolumePlanStatus {
  active: boolean
  finished: boolean
  op: string
  volume: number | null
  progress: string
  step: { step?: number; status?: string; phase?: string; message?: string; volume?: number } | null
  error: string | null
  started_at?: string
}

export const getVolumePlanStatus = (projectId: string) =>
  http.get<VolumePlanStatus>(`/projects/${projectId}/outline/volumes/plan-status`).then(r => r.data)

export interface FoundationStatus {
  active: boolean
  finished: boolean
  progress: string
  step: {
    step?: number
    status?: string
    phase?: string
    message?: string
    entry_type?: string
    current?: number
    total?: number
    expansion_coefficient?: number
  } | null
  error: string | null
  expansion_coefficient: number | null
  started_at?: string | null
}

export const getFoundationStatus = (projectId: string) =>
  http.get<FoundationStatus>(`/projects/${projectId}/outline/foundation-status`).then(r => r.data)

/** Shared SSE stream reader for plan/assemble endpoints. */
async function _readSSEStream(res: Response, handlers: PlanSSEHandlers) {
  const reader = res.body!.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''
  let currentEvent = 'message'
  let dataLines: string[] = []

  const dispatch = () => {
    if (!dataLines.length) { currentEvent = 'message'; return }
    const raw = dataLines.join('\n')
    dataLines = []
    const event = currentEvent
    currentEvent = 'message'
    if (raw === '' || raw === '[DONE]') return

    let parsed: any = raw
    try { parsed = JSON.parse(raw) } catch { /* keep string */ }

    switch (event) {
      case 'progress':
        handlers.onProgress?.(parsed?.message ?? String(parsed))
        break
      case 'step':
        handlers.onStep?.(parsed)
        break
      case 'error':
        handlers.onError?.(parsed?.message || String(parsed))
        break
      case 'done':
        handlers.onDone?.(parsed)
        break
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split(/\r?\n/)
    buffer = parts.pop() ?? ''
    for (const line of parts) {
      if (line === '') { dispatch(); continue }
      if (line.startsWith(':')) continue
      if (line.startsWith('event:')) { currentEvent = line.slice(6).trim(); continue }
      if (line.startsWith('data:')) { dataLines.push(line.slice(5).trimStart()) }
    }
  }
  dispatch()
}

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

export interface WriteSSEHandlers {
  onProgress?: (msg: string) => void
  onContext?: (data: unknown) => void
  /** *replay* is true when the server sends the full buffered text on reconnect. */
  onToken?: (text: string, meta?: { replay?: boolean }) => void
  onDraft?: (data: unknown) => void
  onCheck?: (data: unknown) => void
  onEnrichment?: (data: unknown) => void
  onError?: (msg: string) => void
  onDone?: (data: unknown) => void
}

export interface WriteSSEHandle {
  close: () => void
}

/**
 * Stream chapter generation via fetch + ReadableStream (more reliable than
 * EventSource through Vite proxy; supports named SSE events).
 *
 * Pass ``resume: true`` to attach to an in-flight write without starting a new one.
 */
export function writeChapterSSE(
  projectId: string,
  number: number,
  handlers: WriteSSEHandlers,
  opts?: { resume?: boolean },
): WriteSSEHandle {
  const ctrl = new AbortController()
  const qs = opts?.resume ? '?resume=1' : ''
  const url = `/api/projects/${projectId}/write/${number}${qs}`

  ;(async () => {
    try {
      const res = await fetch(url, {
        method: 'GET',
        headers: { Accept: 'text/event-stream' },
        signal: ctrl.signal,
        cache: 'no-store',
      })
      if (!res.ok || !res.body) {
        handlers.onError?.(`连接失败（HTTP ${res.status}）`)
        return
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      let currentEvent = 'message'
      let dataLines: string[] = []

      const dispatch = () => {
        if (!dataLines.length) {
          currentEvent = 'message'
          return
        }
        const raw = dataLines.join('\n')
        dataLines = []
        const event = currentEvent
        currentEvent = 'message'
        if (raw === '' || raw === '[DONE]') return

        let parsed: any = raw
        try { parsed = JSON.parse(raw) } catch { /* keep string */ }

        switch (event) {
          case 'progress':
            handlers.onProgress?.(parsed?.message ?? String(parsed))
            break
          case 'context':
            handlers.onContext?.(parsed)
            break
          case 'token':
            if (typeof parsed?.text === 'string' && parsed.text) {
              handlers.onToken?.(parsed.text, { replay: !!parsed.replay })
            }
            break
          case 'draft':
            handlers.onDraft?.(parsed)
            break
          case 'check':
            handlers.onCheck?.(parsed)
            break
          case 'enrichment':
            handlers.onEnrichment?.(parsed)
            break
          case 'error':
            handlers.onError?.(parsed?.message || String(parsed))
            break
          case 'done':
            handlers.onDone?.(parsed)
            break
          default:
            break
        }
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const parts = buffer.split(/\r?\n/)
        buffer = parts.pop() ?? ''
        for (const line of parts) {
          if (line === '') {
            dispatch()
            continue
          }
          if (line.startsWith(':')) continue // SSE comment / ping
          if (line.startsWith('event:')) {
            currentEvent = line.slice(6).trim()
            continue
          }
          if (line.startsWith('data:')) {
            dataLines.push(line.slice(5).trimStart())
          }
        }
      }
      dispatch()
    } catch (e: any) {
      if (e?.name === 'AbortError') return
      handlers.onError?.(e?.message || '连接中断')
    }
  })()

  return { close: () => ctrl.abort() }
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
  message?: string
  supervisor_pid?: number
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

export interface WriteStatus {
  active: boolean
  finished?: boolean
  progress: string
  stream_text?: string
  error?: string | null
  started_at?: string
  draft_exists?: boolean
  op?: string
}

export const getWriteStatus = (projectId: string, number: number) =>
  http.get<WriteStatus>(`/projects/${projectId}/write-status/${number}`).then(r => r.data)

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

// ---------- LLM Logs ----------

export interface LlmLogSummary {
  index: number
  ts: string
  stage: string
  chapter: number | null
  model: string
  usage_total: number | null
  has_error: boolean
  error: string | null
  prompt_preview: string
  response_preview: string
  prompt_chars: number
  response_chars: number
}

export interface LlmLogGroup {
  stage: string
  count: number
  entries: LlmLogSummary[]
}

export interface LlmUsageStats {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  calls: number
  calls_with_usage: number
  calls_missing_usage: number
  date?: string | null
  scope?: 'day' | 'project'
}

export interface LlmLogDay {
  date: string
  total: number
  groups: LlmLogGroup[]
  usage: LlmUsageStats
}

export interface LlmLogEntry {
  date: string
  index: number
  ts: string
  started_at: string
  stage: string
  project: string
  chapter: number | null
  model: string
  usage: Record<string, number> | null
  error: string | null
  warnings: string[]
  resolved_ids: Record<string, string>
  prompt: { role: string; content: string }[]
  /** Extracted main content (prose or stage-formatted structured text). */
  body: string
  body_kind: 'prose' | 'structured'
  response_is_json: boolean
  /** Raw model response (JSON string or plain text). */
  response: string
  meta: Record<string, unknown>
}

export const listLlmLogDates = (projectId: string) =>
  http.get<{ dates: string[] }>(`/projects/${projectId}/llm-logs/dates`).then(r => r.data)

export const getLlmLogs = (projectId: string, date: string) =>
  http.get<LlmLogDay>(`/projects/${projectId}/llm-logs`, { params: { date } }).then(r => r.data)

export const getLlmLogEntry = (projectId: string, date: string, index: number) =>
  http.get<LlmLogEntry>(`/projects/${projectId}/llm-logs/entry`, { params: { date, index } }).then(r => r.data)

export const getLlmUsage = (projectId: string, date?: string) =>
  http.get<LlmUsageStats>(`/projects/${projectId}/llm-logs/usage`, {
    params: date ? { date } : undefined,
  }).then(r => r.data)
