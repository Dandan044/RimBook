<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import mermaid from 'mermaid'
import { STAGES, NODE_MATCHERS, type StageMeta } from './pipelineData'

// ---- Mermaid definition ----
// Keep labels Mermaid-11-safe: no <hr/>, no classDef rx/ry, no bare *,
// ASCII hyphen only, always quote labels that contain special chars.

const DIAGRAM = `
flowchart TD
    classDef stage fill:#6366f1,stroke:#4f46e5,color:#fff,stroke-width:2px
    classDef store fill:#10b981,stroke:#059669,color:#fff,stroke-width:1.5px
    classDef input fill:#f59e0b,stroke:#d97706,color:#fff,stroke-width:1.5px
    classDef data fill:#6b7280,stroke:#4b5563,color:#fff,stroke-width:1px

    USER["用户输入<br/>premise / 想法"]:::input

    OUTLINE[("OutlineStore<br/>synopsis.md<br/>volumes · chapters")]:::store
    CODEX[("CodexStore<br/>characters · worldbuilding<br/>locations · factions")]:::store
    STATE[("EntityStateStore<br/>state/entities yaml<br/>location · status · knowledge")]:::store
    DRAFTS[("Drafts<br/>drafts/chN.md")]:::store
    LOGS[("LLM Logs<br/>.llm_logs jsonl")]:::store

    P1["1 Planner<br/>规划器<br/>生成 synopsis<br/>拆 volume 弧线<br/>规划 chapter beats"]:::stage
    P2["实体解析<br/>resolve_entity_ids<br/>规范化漂移 id"]:::data

    CA["2 Context Assembler<br/>6 层上下文组装<br/>codex · synopsis · volume<br/>近章摘要 · 滑窗 · 状态"]:::stage

    W["3 Writer<br/>写作器<br/>LLM 生成正文<br/>写入 drafts<br/>触发后处理"]:::stage

    PP["4 Post-Write Pipeline<br/>后处理管道<br/>摘要 · 实体状态增量<br/>LLM 设定集扩充"]:::stage

    CHK["5 Checker<br/>一致性校验<br/>LLM 审计<br/>auto-fix 循环"]:::stage

    TRACE["LLMTrace<br/>每阶段记录<br/>prompt · response · usage"]:::data

    USER -->|"故事 premise"| P1
    CODEX -.->|"读取实体清单"| P1
    OUTLINE -.->|"读取上文大纲"| P1
    P1 -->|"resolve entity ids"| P2
    P2 -.->|"更新 canonical id"| OUTLINE
    P1 --- TRACE

    OUTLINE -->|"chapter outline"| CA
    CODEX -->|"实体档案"| CA
    STATE -->|"实体状态"| CA
    DRAFTS -.->|"滑窗最近全文"| CA
    CA -->|"AssembledContext"| W

    W -->|"写入正文"| DRAFTS
    W -->|"触发后处理"| PP
    W --- TRACE

    DRAFTS -.->|"读取正文"| PP
    CODEX -.->|"读取已有档案"| PP
    STATE -.->|"读取当前状态"| PP
    PP -->|"写入 summary"| OUTLINE
    PP -->|"写入状态 delta"| STATE
    PP -->|"更新档案"| CODEX
    PP --- TRACE

    DRAFTS -.->|"读取正文"| CHK
    CHK -.->|"发现 issue 修订"| W
    CHK -.->|"写回修订稿"| DRAFTS
    CHK --- TRACE

    TRACE -->|"append JSONL"| LOGS
`

// ---- Component props & emits ----

const emit = defineEmits<{
  (e: 'select-stage', stage: StageMeta | null): void
}>()

// ---- Reactive state ----

const containerRef = ref<HTMLElement | null>(null)
const svgWrapperRef = ref<HTMLElement | null>(null)

// Pan & zoom state
const translateX = ref(0)
const translateY = ref(0)
const scale = ref(1)
let isDragging = false
let dragStartX = 0
let dragStartY = 0
let dragTranslateX = 0
let dragTranslateY = 0

// Theme
function isDark(): boolean {
  return document.documentElement.getAttribute('data-theme') === 'dark'
}

let mermaidReady = false
let renderSeq = 0

function ensureMermaid(dark: boolean) {
  const opts = {
    startOnLoad: false,
    suppressErrorRendering: true,
    theme: (dark ? 'dark' : 'default') as 'dark' | 'default',
    themeVariables: dark ? {
      primaryColor: '#6366f1',
      primaryTextColor: '#e5e7eb',
      primaryBorderColor: '#4f46e5',
      lineColor: '#4b5563',
      secondaryColor: '#1f2937',
      tertiaryColor: '#111827',
    } : {
      primaryColor: '#6366f1',
      primaryTextColor: '#1f2937',
      primaryBorderColor: '#4f46e5',
      lineColor: '#9ca3af',
      secondaryColor: '#f3f4f6',
      tertiaryColor: '#f9fafb',
    },
    flowchart: {
      htmlLabels: true,
      curve: 'basis' as const,
      padding: 20,
      nodeSpacing: 40,
      rankSpacing: 60,
    },
    securityLevel: 'loose' as const,
  }
  if (!mermaidReady) {
    mermaid.initialize(opts)
    mermaidReady = true
  } else {
    // Theme toggle: re-init is required for themeVariables to take effect.
    mermaid.initialize(opts)
  }
}

// ---- Mermaid render ----

async function renderDiagram() {
  if (!containerRef.value) return
  const dark = isDark()
  ensureMermaid(dark)

  const renderId = `pipeline-diagram-${++renderSeq}`
  // Remove any leftover error/svg nodes Mermaid may have attached by id.
  document.getElementById(renderId)?.remove()

  try {
    const { svg } = await mermaid.render(renderId, DIAGRAM)
    containerRef.value.innerHTML = svg

    const svgEl = containerRef.value.querySelector('svg')
    if (svgEl) {
      svgEl.style.maxWidth = 'none'
      svgEl.style.width = 'auto'
      svgEl.style.height = 'auto'
      svgEl.style.cursor = 'grab'

      const nodes = svgEl.querySelectorAll('.node')
      nodes.forEach((node) => {
        const el = node as HTMLElement
        el.style.cursor = 'pointer'
        el.addEventListener('click', (e) => {
          e.stopPropagation()
          const text = el.textContent ?? ''
          for (const m of NODE_MATCHERS) {
            if (m.pattern.test(text)) {
              emit('select-stage', STAGES[m.id] ?? null)
              return
            }
          }
          emit('select-stage', null)
        })
      })
    }

    translateX.value = 0
    translateY.value = 0
    scale.value = 1
    applyTransform()
  } catch (e) {
    console.error('Mermaid render failed:', e)
    if (containerRef.value) {
      containerRef.value.innerHTML =
        '<p style="color:var(--rb-text-muted);padding:20px;text-align:center;">图表渲染失败，请刷新页面重试。</p>'
    }
  }
}

function applyTransform() {
  if (!containerRef.value) return
  const svg = containerRef.value.querySelector('svg') as SVGSVGElement | null
  if (!svg) return
  svg.style.transform = `translate(${translateX.value}px, ${translateY.value}px) scale(${scale.value})`
  svg.style.transformOrigin = '0 0'
}

// ---- Pan & Zoom handlers ----

function onMouseDown(e: MouseEvent) {
  // Only drag with left button, not on node clicks
  if (e.button !== 0) return
  const target = e.target as HTMLElement
  if (target.closest('.node')) return  // Don't drag when clicking on nodes
  isDragging = true
  dragStartX = e.clientX
  dragStartY = e.clientY
  dragTranslateX = translateX.value
  dragTranslateY = translateY.value
  if (containerRef.value) {
    const svg = containerRef.value.querySelector('svg') as SVGSVGElement | null
    if (svg) svg.style.cursor = 'grabbing'
  }
}

function onMouseMove(e: MouseEvent) {
  if (!isDragging) return
  const dx = e.clientX - dragStartX
  const dy = e.clientY - dragStartY
  translateX.value = dragTranslateX + dx
  translateY.value = dragTranslateY + dy
  applyTransform()
}

function onMouseUp(_e: MouseEvent) {
  if (!isDragging) return
  isDragging = false
  if (containerRef.value) {
    const svg = containerRef.value.querySelector('svg') as SVGSVGElement | null
    if (svg) svg.style.cursor = 'grab'
  }
}

function onWheel(e: WheelEvent) {
  e.preventDefault()
  const delta = e.deltaY > 0 ? 0.9 : 1.1
  const newScale = Math.max(0.3, Math.min(3, scale.value * delta))

  // Zoom towards mouse position
  if (containerRef.value) {
    const rect = containerRef.value.getBoundingClientRect()
    const mouseX = e.clientX - rect.left
    const mouseY = e.clientY - rect.top
    const scaleRatio = newScale / scale.value
    translateX.value = mouseX - scaleRatio * (mouseX - translateX.value)
    translateY.value = mouseY - scaleRatio * (mouseY - translateY.value)
  }
  scale.value = newScale
  applyTransform()
}

function resetView() {
  translateX.value = 0
  translateY.value = 0
  scale.value = 1
  applyTransform()
}

function onClickBlank(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.node')) {
    emit('select-stage', null)
  }
}

// ---- Lifecycle ----

let themeObserver: MutationObserver | null = null

onMounted(async () => {
  await nextTick()
  // Attach wheel listener with passive:false so preventDefault works
  containerRef.value?.addEventListener('wheel', onWheel, { passive: false })
  await renderDiagram()

  themeObserver = new MutationObserver(() => {
    renderDiagram()
  })
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  })
})

onUnmounted(() => {
  containerRef.value?.removeEventListener('wheel', onWheel)
  themeObserver?.disconnect()
})

// Expose for parent
defineExpose({ resetView, renderDiagram })
</script>

<template>
  <div
    ref="containerRef"
    class="pipeline-diagram"
    @mousedown="onMouseDown"
    @mousemove="onMouseMove"
    @mouseup="onMouseUp"
    @mouseleave="onMouseUp"
    @click="onClickBlank"
  >
    <!-- SVG inserted by Mermaid render -->
  </div>
</template>

<style scoped>
.pipeline-diagram {
  width: 100%;
  height: 100%;
  overflow: hidden;
  position: relative;
  background:
    radial-gradient(circle at 20% 30%, var(--rb-primary-bg) 0%, transparent 50%),
    radial-gradient(circle at 80% 70%, rgba(16, 185, 129, 0.04) 0%, transparent 50%),
    var(--rb-bg-base);
  border-radius: var(--rb-border-radius);
  border: 1px solid var(--rb-border-light);
  user-select: none;
}

.pipeline-diagram :deep(svg) {
  will-change: transform;
  transition: none;
}

.pipeline-diagram :deep(.node) {
  transition: filter 0.15s ease;
}

.pipeline-diagram :deep(.node:hover) {
  filter: brightness(1.15);
}

.pipeline-diagram :deep(.node rect),
.pipeline-diagram :deep(.node path),
.pipeline-diagram :deep(.node ellipse),
.pipeline-diagram :deep(.node polygon),
.pipeline-diagram :deep(.node circle) {
  transition: filter 0.15s ease;
}
</style>
