<template>
  <div class="network-graph">
    <div class="graph-toolbar">
      <div class="toolbar-left">
        <el-select
          v-model="visibleTypes"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="类型过滤"
          class="type-filter"
        >
          <el-option
            v-for="option in typeOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <el-switch v-model="includeImplicitWorld" active-text="隐式世界观边" />
        <el-switch v-model="focusMode" active-text="聚焦所选" />
        <el-input-number
          v-model="focusDepth"
          :min="0"
          :max="3"
          :disabled="!focusMode || !focusId"
          controls-position="right"
          class="depth-input"
        />
        <span class="hint">聚焦深度</span>
      </div>
      <div class="toolbar-right">
        <el-tag size="small" effect="plain">{{ nodes.length }} 节点</el-tag>
        <el-tag size="small" effect="plain">{{ edges.length }} 边</el-tag>
        <el-button size="small" :loading="loading" @click="reload">刷新</el-button>
        <el-button size="small" :loading="layouting" @click="runForceLayout">重新布局</el-button>
        <el-button size="small" :loading="savingLayout" @click="persistLayout">保存布局</el-button>
      </div>
    </div>

    <div class="type-legend">
      <span v-for="option in typeOptions" :key="option.value" class="legend-item">
        <i :style="{ background: TYPE_THEME[option.value].fill, boxShadow: `0 0 0 2px ${TYPE_THEME[option.value].stroke}` }" />
        {{ option.label }}
      </span>
    </div>

    <div v-if="error" class="graph-error">{{ error }}</div>
    <div v-else-if="!loading && !nodes.length" class="graph-empty">
      暂无可视化节点。可先生成基础设定，或新建条目与关系。
    </div>
    <div v-show="!error && (loading || nodes.length)" ref="canvasRef" class="graph-canvas" />
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Graph, type GraphData, type NodeData, type EdgeData } from '@antv/g6'
import {
  getPlanningGraph,
  getPlanningGraphLayout,
  savePlanningGraphLayout,
  type PlanningGraphEdge,
  type PlanningGraphNode,
} from '../api'

/** High-contrast type palette for dark canvas: vivid fills + white in-node labels. */
const TYPE_THEME: Record<string, { fill: string; stroke: string; label: string }> = {
  character: { fill: '#6366f1', stroke: '#c7d2fe', label: '角色' },
  worldbuilding: { fill: '#14b8a6', stroke: '#99f6e4', label: '世界观' },
  location: { fill: '#f59e0b', stroke: '#fde68a', label: '地点' },
  faction: { fill: '#f43f5e', stroke: '#fecdd3', label: '势力' },
  item: { fill: '#a855f7', stroke: '#e9d5ff', label: '物品' },
  timeline: { fill: '#0ea5e9', stroke: '#bae6fd', label: '时间线' },
}

const typeOptions = Object.entries(TYPE_THEME).map(([value, meta]) => ({
  value,
  label: meta.label,
}))

const props = defineProps<{
  projectId: string
  focusId?: string
}>()

const emit = defineEmits<{
  'select-node': [id: string]
  'select-edge': [id: string]
  'pane-click': []
}>()

const canvasRef = ref<HTMLDivElement | null>(null)
const visibleTypes = ref(typeOptions.map(item => item.value))
const includeImplicitWorld = ref(false)
const focusMode = ref(false)
const focusDepth = ref(1)
const loading = ref(false)
const layouting = ref(false)
const savingLayout = ref(false)
const error = ref('')
const nodes = ref<PlanningGraphNode[]>([])
const edges = ref<PlanningGraphEdge[]>([])
const savedPositions = ref<Record<string, { x: number; y: number }>>({})

const focusId = computed(() => props.focusId || '')

let graph: Graph | null = null
let resizeObserver: ResizeObserver | null = null
/** Ignore the next focusId watch tick after canvas clear (parent may still hold selection). */
let highlightSuppressed = false
let pointerDownOnCanvas = false
let pointerDownPos: { x: number; y: number } | null = null

function themeOf(type: string) {
  return TYPE_THEME[type] || TYPE_THEME.item
}

function nodeSize(degree: number) {
  return Math.min(92, Math.max(64, 56 + degree * 5))
}

/**
 * Fit a CJK-heavy name inside the circle by shrinking font and wrapping up to
 * 3 lines. Avoid G6 word-wrap/ellipsis (it under-measures CJK and truncates early).
 */
function layoutNodeLabel(name: string, size: number) {
  const trimmed = name.trim()
  if (!trimmed) return { text: '', fontSize: 12, lineHeight: 15 }

  const maxWidth = size * 0.78
  const maxHeight = size * 0.72
  const maxLines = 3
  const minFont = 8
  const maxFont = 13

  for (let fontSize = maxFont; fontSize >= minFont; fontSize--) {
    // Bold CJK glyphs are ~1em wide; keep a small safety margin.
    const charW = fontSize * 1.05
    const perLine = Math.max(1, Math.floor(maxWidth / charW))
    const linesNeeded = Math.ceil(trimmed.length / perLine)
    const lineHeight = Math.round(fontSize * 1.2)
    if (linesNeeded > maxLines || linesNeeded * lineHeight > maxHeight) continue

    const lines: string[] = []
    for (let i = 0; i < trimmed.length; i += perLine) {
      lines.push(trimmed.slice(i, i + perLine))
    }
    return { text: lines.join('\n'), fontSize, lineHeight }
  }

  // Last resort: min font, 3 lines, then ellipsis.
  const fontSize = minFont
  const charW = fontSize * 1.05
  const perLine = Math.max(1, Math.floor(maxWidth / charW))
  const maxChars = perLine * maxLines
  const clipped = trimmed.length > maxChars
    ? `${trimmed.slice(0, Math.max(1, maxChars - 1))}…`
    : trimmed
  const lines: string[] = []
  for (let i = 0; i < clipped.length; i += perLine) {
    lines.push(clipped.slice(i, i + perLine))
  }
  return { text: lines.join('\n'), fontSize, lineHeight: Math.round(fontSize * 1.2) }
}

function toG6Data(
  sourceNodes: PlanningGraphNode[],
  sourceEdges: PlanningGraphEdge[],
  positions: Record<string, { x: number; y: number }>,
): GraphData {
  const g6Nodes: NodeData[] = sourceNodes.map((node, index) => {
    const theme = themeOf(node.type)
    const saved = positions[node.id]
    const size = nodeSize(node.degree || 0)
    const label = layoutNodeLabel(node.name, size)
    return {
      id: node.id,
      data: {
        name: node.name,
        type: node.type,
        summary: node.summary,
        narrative_role: node.narrative_role,
        planned: node.planned,
        expansion_depth: node.expansion_depth,
        degree: node.degree,
      },
      style: {
        x: saved?.x ?? (index % 6) * 170 + 90,
        y: saved?.y ?? Math.floor(index / 6) * 140 + 90,
        size,
        fill: theme.fill,
        stroke: theme.stroke,
        lineWidth: node.id === focusId.value ? 3 : 2,
        lineDash: node.planned ? [6, 4] : undefined,
        shadowColor: 'rgba(0, 0, 0, 0.45)',
        shadowBlur: 14,
        shadowOffsetY: 3,
        labelText: label.text,
        labelPlacement: 'center',
        labelFill: '#ffffff',
        labelFontSize: label.fontSize,
        labelFontWeight: 700,
        labelFontFamily: '"Microsoft YaHei", "PingFang SC", "Noto Sans SC", system-ui, sans-serif',
        labelBackground: false,
        // Manual wrapping above; G6 word-wrap + maxWidth truncates CJK too early.
        labelWordWrap: false,
        labelLineHeight: label.lineHeight,
        labelTextAlign: 'center',
        labelTextBaseline: 'middle',
        ports: [],
      },
    }
  })

  const g6Edges: EdgeData[] = sourceEdges.map(edge => {
    const implicit = edge.kind === 'implicit_world'
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      data: {
        relationship_type: edge.relationship_type,
        kind: edge.kind,
        label: edge.label,
      },
      style: {
        stroke: implicit ? '#64748b' : '#818cf8',
        lineWidth: implicit ? 1 : 1.8,
        lineDash: implicit ? [6, 4] : undefined,
        opacity: implicit ? 0.45 : 0.88,
        endArrow: !implicit,
        endArrowSize: 8,
        labelText: implicit ? '' : (edge.label || edge.relationship_type || ''),
        labelFill: '#e2e8f0',
        labelFontSize: 10,
        labelFontWeight: 500,
        labelFontFamily: 'Inter, system-ui, sans-serif',
        labelBackground: true,
        labelBackgroundFill: 'rgba(12, 18, 34, 0.88)',
        labelBackgroundRadius: 3,
        labelPadding: [2, 6],
        labelAutoRotate: false,
      },
    }
  })

  return { nodes: g6Nodes, edges: g6Edges }
}

function allPositionsSaved(sourceNodes: PlanningGraphNode[], positions: Record<string, { x: number; y: number }>) {
  return sourceNodes.length > 0 && sourceNodes.every(node => positions[node.id])
}

function createGraph(runLayout: boolean) {
  if (!canvasRef.value) return
  destroyGraph()
  const width = canvasRef.value.clientWidth || 960
  const height = canvasRef.value.clientHeight || 520

  graph = new Graph({
    container: canvasRef.value,
    width,
    height,
    autoFit: 'view',
    padding: 36,
    animation: true,
    data: { nodes: [], edges: [] },
    layout: runLayout
      ? {
          type: 'd3-force',
          preventOverlap: true,
          collide: { radius: 56 },
          link: { distance: 170, strength: 0.4 },
          manyBody: { strength: -520 },
          center: { x: width / 2, y: height / 2 },
        }
      : undefined,
    node: {
      type: 'circle',
      state: {
        active: {
          lineWidth: 3.5,
          stroke: '#ffffff',
          shadowColor: 'rgba(255, 255, 255, 0.55)',
          shadowBlur: 22,
          halo: true,
          haloStroke: '#ffffff',
          haloLineWidth: 12,
          haloStrokeOpacity: 0.35,
          opacity: 1,
          labelOpacity: 1,
          zIndex: 3,
        },
        neighborActive: {
          lineWidth: 3,
          stroke: '#fde68a',
          shadowColor: 'rgba(253, 230, 138, 0.45)',
          shadowBlur: 16,
          halo: true,
          haloStroke: '#fbbf24',
          haloLineWidth: 8,
          haloStrokeOpacity: 0.4,
          opacity: 1,
          labelOpacity: 1,
          zIndex: 2,
        },
        inactive: {
          opacity: 0.16,
          labelOpacity: 0.12,
          strokeOpacity: 0.25,
          shadowBlur: 0,
        },
      },
    },
    edge: {
      type: 'quadratic',
      state: {
        active: {
          stroke: '#f8fafc',
          lineWidth: 2.8,
          opacity: 1,
          labelFill: '#f8fafc',
          labelOpacity: 1,
          zIndex: 2,
        },
        inactive: {
          opacity: 0.08,
          labelOpacity: 0,
        },
      },
    },
    behaviors: [
      'drag-canvas',
      'zoom-canvas',
      {
        type: 'drag-element',
        enable: (event: any) => event.targetType === 'node',
      },
      // Highlight is owned manually below — click-select races async setElementState
      // and fights canvas clear when enable excludes canvas.
    ],
    plugins: [
      {
        type: 'minimap',
        key: 'minimap',
        size: [168, 112],
        position: 'right-bottom',
        padding: 8,
        containerStyle: {
          border: '1px solid rgba(148, 163, 184, 0.28)',
          borderRadius: '10px',
          boxShadow: '0 8px 24px rgba(0,0,0,0.35)',
          background: '#111827',
        },
      },
      {
        type: 'toolbar',
        key: 'toolbar',
        position: 'left-top',
        style: {
          backgroundColor: 'rgba(17, 24, 39, 0.92)',
          border: '1px solid rgba(148, 163, 184, 0.25)',
          borderRadius: '10px',
          color: '#e2e8f0',
        },
        onClick: (value: string) => {
          if (!graph) return
          if (value === 'zoom-in') graph.zoomBy(1.2)
          if (value === 'zoom-out') graph.zoomBy(0.8)
          if (value === 'auto-fit') graph.fitView()
          if (value === 'reset') void runForceLayout()
        },
        getItems: () => [
          { id: 'zoom-in', value: 'zoom-in' },
          { id: 'zoom-out', value: 'zoom-out' },
          { id: 'auto-fit', value: 'auto-fit' },
          { id: 'reset', value: 'reset' },
        ],
      },
    ],
  })

  graph.on('node:click', (event: any) => {
    const id = String(event.target?.id || event.itemId || '')
    if (!id) return
    highlightSuppressed = false
    applyNeighborhoodHighlight(id)
    emit('select-node', id)
  })
  graph.on('edge:click', (event: any) => {
    const id = String(event.target?.id || event.itemId || '')
    if (!id || id.startsWith('implicit_world_')) return
    emit('select-edge', id)
  })
  // drag-canvas often swallows canvas:click; also treat short pointerup on blank as clear.
  graph.on('canvas:pointerdown', (event: any) => {
    pointerDownOnCanvas = true
    pointerDownPos = { x: Number(event.canvas?.x ?? event.client?.x ?? 0), y: Number(event.canvas?.y ?? event.client?.y ?? 0) }
  })
  graph.on('node:pointerdown', () => { pointerDownOnCanvas = false; pointerDownPos = null })
  graph.on('edge:pointerdown', () => { pointerDownOnCanvas = false; pointerDownPos = null })
  graph.on('canvas:click', () => { clearCanvasHighlight() })
  graph.on('canvas:pointerup', (event: any) => {
    if (!pointerDownOnCanvas) return
    pointerDownOnCanvas = false
    const x = Number(event.canvas?.x ?? event.client?.x ?? 0)
    const y = Number(event.canvas?.y ?? event.client?.y ?? 0)
    const dx = pointerDownPos ? Math.abs(x - pointerDownPos.x) : 0
    const dy = pointerDownPos ? Math.abs(y - pointerDownPos.y) : 0
    pointerDownPos = null
    // Treat as click (not pan) when movement is tiny.
    if (dx <= 4 && dy <= 4) clearCanvasHighlight()
  })
  graph.on('node:dragend', () => { void persistLayout() })
}

function clearCanvasHighlight() {
  highlightSuppressed = true
  clearHighlight()
  emit('pane-click')
}

function clearHighlight() {
  if (!graph) return
  const nodeIds = graph.getNodeData().map(node => String(node.id))
  const edgeIds = graph.getEdgeData().map(edge => String(edge.id))
  const states: Record<string, string[]> = {}
  for (const id of [...nodeIds, ...edgeIds]) states[id] = []
  // Disable animation so a pending click-select/state tween cannot overwrite the clear.
  void graph.setElementState(states, false)
}

function applyNeighborhoodHighlight(nodeId: string) {
  if (!graph || !nodeId) return
  const nodeIds = graph.getNodeData().map(node => String(node.id))
  if (!nodeIds.includes(nodeId)) return

  const neighbors = new Set<string>()
  const activeEdges = new Set<string>()
  for (const edge of graph.getEdgeData()) {
    const source = String(edge.source)
    const target = String(edge.target)
    const edgeId = String(edge.id)
    if (source === nodeId || target === nodeId) {
      activeEdges.add(edgeId)
      if (source !== nodeId) neighbors.add(source)
      if (target !== nodeId) neighbors.add(target)
    }
  }

  const states: Record<string, string[]> = {}
  for (const id of nodeIds) {
    if (id === nodeId) states[id] = ['active']
    else if (neighbors.has(id)) states[id] = ['neighborActive']
    else states[id] = ['inactive']
  }
  for (const edge of graph.getEdgeData()) {
    const edgeId = String(edge.id)
    states[edgeId] = activeEdges.has(edgeId) ? ['active'] : ['inactive']
  }
  void graph.setElementState(states, false)
}

async function renderGraph(runLayout: boolean) {
  if (!canvasRef.value) return
  createGraph(runLayout)
  if (!graph) return

  const data = toG6Data(nodes.value, edges.value, savedPositions.value)
  graph.setData(data)

  if (runLayout) layouting.value = true
  try {
    await graph.render()
    await graph.fitView()
    if (runLayout) {
      collectPositionsFromGraph()
      await persistLayout()
    }
  } finally {
    layouting.value = false
  }

  if (focusId.value && !highlightSuppressed) applyNeighborhoodHighlight(focusId.value)
}

function collectPositionsFromGraph() {
  if (!graph) return
  const positions: Record<string, { x: number; y: number }> = {}
  for (const node of graph.getNodeData()) {
    const x = Number(node.style?.x ?? 0)
    const y = Number(node.style?.y ?? 0)
    positions[String(node.id)] = { x, y }
  }
  savedPositions.value = positions
}

async function persistLayout() {
  if (!props.projectId || !graph) return
  savingLayout.value = true
  try {
    collectPositionsFromGraph()
    await savePlanningGraphLayout(props.projectId, {
      nodes: savedPositions.value,
      viewport: {},
    })
  } finally {
    savingLayout.value = false
  }
}

async function runForceLayout() {
  if (!nodes.value.length) return
  await renderGraph(true)
}

async function reload() {
  if (!props.projectId) return
  loading.value = true
  error.value = ''
  try {
    const [graphPayload, layout] = await Promise.all([
      getPlanningGraph(props.projectId, {
        types: visibleTypes.value,
        focus: focusMode.value ? (focusId.value || undefined) : undefined,
        depth: focusDepth.value,
        includeImplicitWorld: includeImplicitWorld.value,
      }),
      getPlanningGraphLayout(props.projectId).catch(() => ({ nodes: {}, viewport: {} })),
    ])
    nodes.value = graphPayload.nodes
    edges.value = graphPayload.edges
    savedPositions.value = layout.nodes || {}
    await nextTick()
    if (!nodes.value.length) {
      destroyGraph()
      return
    }
    const needLayout = !allPositionsSaved(nodes.value, savedPositions.value)
    await renderGraph(needLayout)
  } catch (err: any) {
    error.value = err?.response?.data?.detail || err?.message || '关系图加载失败'
    destroyGraph()
  } finally {
    loading.value = false
  }
}

function destroyGraph() {
  if (graph) {
    graph.destroy()
    graph = null
  }
}

function resizeGraph() {
  if (!graph || !canvasRef.value) return
  const width = canvasRef.value.clientWidth
  const height = canvasRef.value.clientHeight
  if (width > 0 && height > 0) {
    graph.setSize(width, height)
    graph.fitView()
  }
}

onMounted(() => {
  if (canvasRef.value) {
    resizeObserver = new ResizeObserver(() => resizeGraph())
    resizeObserver.observe(canvasRef.value)
  }
})

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  destroyGraph()
})

watch(
  () => [props.projectId, focusMode.value, visibleTypes.value, includeImplicitWorld.value, focusDepth.value],
  () => { void reload() },
  { deep: true, immediate: true },
)

// Changing the selected entry should highlight neighbors, not remount the whole graph.
watch(
  () => props.focusId,
  (nextFocusId) => {
    if (!graph) return
    if (focusMode.value) {
      highlightSuppressed = false
      void reload()
      return
    }
    if (nextFocusId) {
      highlightSuppressed = false
      applyNeighborhoodHighlight(nextFocusId)
    } else {
      clearHighlight()
    }
  },
)

defineExpose({ reload })
</script>

<style scoped>
.network-graph {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 560px;
}
.graph-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}
.toolbar-left,
.toolbar-right {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}
.type-filter { width: 240px; }
.depth-input { width: 110px; }
.hint { color: var(--rb-text-muted); font-size: 12px; }
.type-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 16px;
  padding: 2px 2px 0;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--rb-text-secondary);
  font-size: 12px;
}
.legend-item i {
  width: 12px;
  height: 12px;
  border-radius: 999px;
  display: inline-block;
}
.graph-error,
.graph-empty {
  min-height: 460px;
  display: grid;
  place-items: center;
  color: #94a3b8;
  border: 1px dashed rgba(148, 163, 184, 0.35);
  border-radius: 14px;
  background: #0c1222;
}
.graph-canvas {
  height: 560px;
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 14px;
  background:
    radial-gradient(circle at 16% 10%, rgba(99, 102, 241, 0.22), transparent 38%),
    radial-gradient(circle at 84% 82%, rgba(14, 165, 233, 0.14), transparent 34%),
    radial-gradient(circle at 50% 50%, rgba(244, 63, 94, 0.06), transparent 50%),
    linear-gradient(165deg, #0b1220 0%, #111827 48%, #0c1222 100%);
  overflow: hidden;
  position: relative;
}
@media (max-width: 900px) {
  .graph-canvas { height: 440px; }
  .type-filter { width: 180px; }
}
</style>
