<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getPrompts, updatePrompt, resetPrompt, resetAllPrompts, previewPrompt,
  type PromptEntry,
} from '../api'
import { useProjectStore } from '../stores/project'

interface StageMeta { key: string; label: string }

const STORE: Record<string, StageMeta> = {
  planning: { key: 'planning', label: '规划' },
  writing: { key: 'writing', label: '写作' },
  summarization: { key: 'summarization', label: '摘要与状态' },
  checking: { key: 'checking', label: '校验' },
  enrichment: { key: 'enrichment', label: '设定扩充' },
}

const stageLabel = (s: string) => STORE[s]?.label ?? s

interface PromptModule {
  name: string
  stage: string
  keys: string[]
  systemKey: string | null
  userKeys: string[]
  hasBoth: boolean
}

const projectStore = useProjectStore()

const prompts = ref<PromptEntry[]>([])
const selectedModule = ref<string | null>(null)

// per-key editing state maps
const valueByKey = reactive<Record<string, string>>({})      // current edits
const savedByKey = reactive<Record<string, string>>({})       // last saved (or loaded) value

const saving = ref(false)
const reseting = ref(false)
const previewing = ref(false)
const previewKey = ref<string | null>(null)
const previewText = ref('')
const showPreview = ref(false)
const keyword = ref('')

const previewNumber = ref(1)
const previewPremise = ref('')
const previewInstructions = ref('')

const byKey = computed<Record<string, PromptEntry>>(() => {
  const m: Record<string, PromptEntry> = {}
  for (const p of prompts.value) m[p.key] = p
  return m
})

const modules = computed<PromptModule[]>(() => {
  const list = Array.isArray(prompts.value) ? prompts.value : []
  const kw = keyword.value.trim().toLowerCase()
  const filtered = list.filter(p => {
    if (!kw) return true
    return (
      p.key.toLowerCase().includes(kw) ||
      (p.zh_module || '').toLowerCase().includes(kw) ||
      (p.zh_name || '').toLowerCase().includes(kw) ||
      (p.description || '').toLowerCase().includes(kw) ||
      (p.value || '').toLowerCase().includes(kw)
    )
  })
  // group by zh_module, preserving declaration order
  const order: string[] = []
  const group: Record<string, { stage: string; entries: PromptEntry[] }> = {}
  for (const p of filtered) {
    const name = p.zh_module || p.key
    if (!group[name]) { group[name] = { stage: p.stage, entries: [] }; order.push(name) }
    group[name].entries.push(p)
  }
  return order.map(name => {
    const entries = group[name].entries
    const stage = group[name].stage
    const keys = entries.map(e => e.key)
    const systemKey = entries.find(e => e.role === 'system')?.key ?? null
    const userKeys = entries.filter(e => e.role === 'user').map(e => e.key)
    return { name, stage, keys, systemKey, userKeys, hasBoth: !!systemKey && userKeys.length > 0 }
  })
})

const stageModules = computed(() => {
  const grouped: Record<string, PromptModule[]> = {}
  for (const mod of modules.value) {
    if (!grouped[mod.stage]) grouped[mod.stage] = []
    grouped[mod.stage].push(mod)
  }
  return grouped
})

const stageOrder = computed(() => {
  const order = ['planning', 'writing', 'summarization', 'checking', 'enrichment']
  const seen = Object.keys(stageModules.value)
  return [
    ...order.filter(s => seen.includes(s)),
    ...seen.filter(s => !order.includes(s)),
  ]
})

const selectedMod = computed<PromptModule | null>(() =>
  modules.value.find(m => m.name === selectedModule.value) ?? null,
)

const selectedEntries = computed<PromptEntry[]>(() =>
  selectedMod.value ? selectedMod.value.keys.map(k => byKey.value[k]).filter(Boolean) : [],
)

function isDirtyKey(key: string): boolean {
  return valueByKey[key] !== savedByKey[key]
}

const isDirty = computed(() =>
  selectedMod.value ? selectedMod.value.keys.some(k => isDirtyKey(k)) : false,
)
const overriddenCount = computed(() => prompts.value.filter(p => p.overridden).length)

function chips(key: string) {
  const p = byKey.value[key]
  if (!p) return []
  return p.placeholders.map(ph => ({
    name: ph.name,
    tip: `${ph.desc}（来源：${ph.source}）`,
    labelHtml: `{${ph.name}}`
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;'),
  }))
}

async function load() {
  try {
    const r = await getPrompts()
    const items = Array.isArray(r?.prompts) ? r.prompts : []
    if (items.length === 0) {
      ElMessage.error('未获取到提示词列表。后端可能仍在运行旧版本——请重启后端进程以加载新的 /api/prompts 路由。')
    }
    prompts.value = items
    // reset per-key state
    for (const k of Object.keys(valueByKey)) delete valueByKey[k]
    for (const k of Object.keys(savedByKey)) delete savedByKey[k]
    for (const p of items) {
      valueByKey[p.key] = p.value
      savedByKey[p.key] = p.value
    }
    if (
      (!selectedModule.value ||
        !items.some(p => (p.zh_module || p.key) === selectedModule.value)) &&
      items.length > 0
    ) {
      selectedModule.value = items[0].zh_module || items[0].key
    }
  } catch (e: any) {
    prompts.value = []
    ElMessage.error('加载提示词失败：' + (e?.message || '未知错误') + '（请确认后端已重启以加载工作流路由）')
  }
}

function selectModule(name: string) {
  if (isDirty.value) {
    ElMessageBox.confirm('当前有未保存的修改，确定切换？未保存的编辑将丢失。', '提示', {
      type: 'warning', cancelButtonText: '取消', confirmButtonText: '切换',
    })
      .then(() => { selectedModule.value = name; afterSelect() })
      .catch(() => {})
    return
  }
  selectedModule.value = name
  afterSelect()
}

function afterSelect() {
  showPreview.value = false
  previewText.value = ''
  previewKey.value = null
}

watch(selectedModule, () => { afterSelect() })

function rollbackKey(key: string) {
  valueByKey[key] = savedByKey[key]
}

function rollbackAll() {
  if (!selectedMod.value) return
  for (const k of selectedMod.value.keys) rollbackKey(k)
}

async function saveKey(key: string) {
  saving.value = true
  try {
    const updated = await updatePrompt(key, valueByKey[key])
    const idx = prompts.value.findIndex(p => p.key === key)
    if (idx >= 0) prompts.value[idx] = updated
    savedByKey[key] = updated.value
    valueByKey[key] = updated.value
    ElMessage.success(`已保存：${byKey.value[key]?.zh_name || key}`)
  } catch (e: any) {
    ElMessage.error(e?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function saveAll() {
  if (!selectedMod.value) return
  for (const k of selectedMod.value.keys) {
    if (!isDirtyKey(k)) continue
    await saveKey(k)
  }
}

async function resetKey(key: string) {
  try {
    await ElMessageBox.confirm(`将「${byKey.value[key]?.zh_name || key}」恢复为内建默认？`, '恢复默认', {
      type: 'warning', cancelButtonText: '取消', confirmButtonText: '恢复',
    })
  } catch { return }
  reseting.value = true
  try {
    const updated = await resetPrompt(key)
    const idx = prompts.value.findIndex(p => p.key === key)
    if (idx >= 0) prompts.value[idx] = updated
    savedByKey[key] = updated.value
    valueByKey[key] = updated.value
    ElMessage.success('已恢复为默认')
  } catch (e: any) {
    ElMessage.error(e?.message || '恢复失败')
  } finally {
    reseting.value = false
  }
}

async function resetAll() {
  try {
    await ElMessageBox.confirm('将清空工作区级别的全部提示词覆盖，所有提示词恢复为内建默认。确定继续？', '恢复全部默认', {
      type: 'warning', cancelButtonText: '取消', confirmButtonText: '全部恢复',
    })
  } catch { return }
  try {
    await resetAllPrompts()
    await load()
    ElMessage.success('已恢复全部默认')
  } catch (e: any) {
    ElMessage.error(e?.message || '恢复失败')
  }
}

const placeholderRegex = /(\{\{[^}]*\}\}|\{[^{}]+\})/g
function highlightHtml(s: string) {
  const esc = (s || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return esc.replace(placeholderRegex, '<span class="ph">$1</span>')
}

async function renderPreviewFor(key: string) {
  if (!projectStore.currentId) {
    ElMessage.warning('请先在「导航」切换到某个项目以使用真实数据预览')
    return
  }
  previewing.value = true
  previewKey.value = key
  showPreview.value = true
  try {
    const r = await previewPrompt(projectStore.currentId, key, {
      number: previewNumber.value,
      premise: previewPremise.value,
      instructions: previewInstructions.value,
    })
    previewText.value = r.rendered
  } catch (e: any) {
    ElMessage.error(e?.message || '预览失败')
    previewText.value = ''
  } finally {
    previewing.value = false
  }
}

function hasPlaceholder(key: string, name: string): boolean {
  return !!byKey.value[key]?.placeholders.some(p => p.name === name)
}

onMounted(async () => {
  if (projectStore.projects.length === 0) {
    try { await projectStore.fetchProjects() } catch {}
  }
  await load()
})
</script>

<template>
  <div class="workflow-page">
    <div class="workflow-header">
      <div>
        <h1>工作流 · 提示词</h1>
        <p class="muted">
          集中查看和即时编辑所有发给 LLM 的提示词模板。
          占位符 <code class="ph-inline">{xxx}</code> 在生成时会被真实数据填充。
          覆盖仅写入工作区级 <code>prompts.yaml</code>，不影响内建默认值。
        </p>
      </div>
      <div class="header-actions">
        <el-tag v-if="overriddenCount > 0" type="warning" size="small">
          已修改 {{ overriddenCount }} 项
        </el-tag>
        <el-button size="small" :disabled="reseting" @click="resetAll">
          恢复默认（全部）
        </el-button>
      </div>
    </div>

    <div class="workflow-body">
      <!-- Left column: modules grouped by stage -->
      <aside class="prompt-list">
        <el-input v-model="keyword" placeholder="搜索提示词或模块…" clearable size="small" class="search" />
        <div v-for="stage in stageOrder" :key="stage" class="stage-group">
          <div class="stage-title">{{ stageLabel(stage) }}</div>
          <div
            v-for="mod in stageModules[stage]"
            :key="mod.name"
            class="prompt-row"
            :class="{ active: mod.name === selectedModule }"
            @click="selectModule(mod.name)"
          >
            <div class="row-top">
              <span class="row-zh">{{ mod.name }}</span>
              <span class="row-tags">
                <el-tag v-if="mod.systemKey && byKey[mod.systemKey]?.overridden" type="warning" size="small" effect="plain">系统·改</el-tag>
                <el-tag v-for="uk in mod.userKeys" :key="uk" v-show="byKey[uk]?.overridden" type="warning" size="small" effect="plain">用户·改</el-tag>
                <el-tag v-if="mod.keys.some(k => !byKey[k]?.in_use)" type="info" size="small" effect="plain">未使用</el-tag>
              </span>
            </div>
            <div class="row-bottom">
              <span class="row-zh-name">
                {{ mod.systemKey ? (byKey[mod.systemKey]?.zh_name || '系统') : (mod.userKeys[0] ? byKey[mod.userKeys[0]]?.zh_name : mod.name) }}
              </span>
            </div>
            <div class="row-keys">
              <code class="key-chip" v-for="k in mod.keys" :key="k">{{ k }}</code>
            </div>
          </div>
        </div>
      </aside>

      <!-- Right column: detail / editor -->
      <section v-if="selectedMod" class="prompt-detail">
        <div class="detail-head">
          <div class="head-left">
            <h2>{{ selectedMod.name }}</h2>
            <div class="head-tags">
              <el-tag size="small">{{ stageLabel(selectedMod.stage) }}</el-tag>
              <el-tag v-if="selectedMod.hasBoth" size="small" type="primary">系统 + 用户</el-tag>
              <el-tag v-else-if="selectedMod.systemKey" size="small" type="primary">仅系统</el-tag>
              <el-tag v-else size="small" type="success">仅用户</el-tag>
              <el-tag v-if="selectedMod.keys.some(k => byKey[k]?.overridden)" type="warning" size="small">已修改</el-tag>
              <el-tag v-if="selectedMod.keys.some(k => !byKey[k]?.in_use)" type="info" size="small">未使用</el-tag>
            </div>
          </div>
          <div class="head-actions">
            <el-button size="small" :disabled="!isDirty || saving" type="primary" :loading="saving" @click="saveAll">
              全部保存
            </el-button>
            <el-button size="small" :disabled="!isDirty" @click="rollbackAll">撤销编辑</el-button>
          </div>
        </div>

        <p class="description">
          本模块包含 {{ selectedMod.keys.length }} 条提示词：
          <code v-for="(k, i) in selectedMod.keys" :key="k" class="key-inline">
            {{ k }}<span v-if="i < selectedMod.keys.length - 1">、</span>
          </code>
          。下方分别编辑，逐条可独立保存 / 恢复 / 预览。
        </p>

        <!-- One editor card per prompt key in this module -->
        <div v-for="k in selectedMod.keys" :key="k" class="key-card">
          <div class="card-head">
            <div class="card-title">
              <el-tag :type="byKey[k]?.role === 'system' ? 'primary' : 'success'" size="small">
                {{ byKey[k]?.role }}
              </el-tag>
              <span class="card-zh">{{ byKey[k]?.zh_name || k }}</span>
              <span class="card-key">({{ k }})</span>
              <el-tag v-if="byKey[k]?.overridden" type="warning" size="small" effect="plain">已修改</el-tag>
              <el-tag v-if="!byKey[k]?.in_use" type="info" size="small" effect="plain">未使用</el-tag>
              <span v-if="isDirtyKey(k)" class="dirty-mark">未保存</span>
            </div>
            <div class="card-actions">
              <el-button size="small" type="primary" :disabled="!isDirtyKey(k) || saving" :loading="saving" @click="saveKey(k)">
                保存
              </el-button>
              <el-button size="small" :disabled="!isDirtyKey(k)" @click="rollbackKey(k)">撤销</el-button>
              <el-button size="small" :disabled="!byKey[k]?.overridden" :loading="reseting" @click="resetKey(k)">
                恢复默认
              </el-button>
            </div>
          </div>

          <p v-if="byKey[k]?.description" class="card-desc muted">{{ byKey[k].description }}</p>

          <div v-if="byKey[k]?.placeholders?.length" class="placeholders">
            <span class="ph-caption">占位符（生成时由下列来源填充）：</span>
            <div class="ph-list">
              <el-tooltip
                v-for="ph in chips(k)"
                :key="ph.name"
                :content="ph.tip"
                placement="top"
              >
                <code class="ph-chip" v-html="ph.labelHtml"></code>
              </el-tooltip>
            </div>
          </div>

          <div class="editor-wrap">
            <textarea
              v-model="valueByKey[k]"
              class="prompt-editor"
              spellcheck="false"
              :rows="byKey[k]?.role === 'system' ? 10 : 14"
            />
            <div class="highlight-preview">
              <div class="hp-title muted">占位符高亮预览（只读）：</div>
              <pre class="hp-body" v-html="highlightHtml(valueByKey[k])"></pre>
            </div>
          </div>

          <div class="preview-area">
            <div class="preview-controls">
              <span class="caption">用真实数据填充预览</span>
              <el-input-number v-model="previewNumber" :min="1" :step="1" size="small" />
              <el-input
                v-if="hasPlaceholder(k, 'premise')"
                v-model="previewPremise"
                placeholder="premise（可选）"
                size="small"
                style="width: 240px"
              />
              <el-input
                v-if="hasPlaceholder(k, 'instructions')"
                v-model="previewInstructions"
                placeholder="instructions（可选）"
                size="small"
                style="width: 220px"
              />
              <el-button
                size="small" type="primary" :loading="previewing && previewKey === k"
                @click="renderPreviewFor(k)"
              >
                预览填充
              </el-button>
            </div>
            <div v-if="showPreview && previewKey === k" class="preview-output">
              <div class="po-title muted">最终将发给 LLM 的文本：</div>
              <pre class="po-body">{{ previewText || '（暂无数据）' }}</pre>
            </div>
          </div>
        </div>
      </section>

      <section v-else class="prompt-empty">
        <el-empty description="选择左侧某一模块以查看与编辑" />
      </section>
    </div>
  </div>
</template>

<style scoped>
.workflow-page {
  display: flex; flex-direction: column;
  height: 100%; min-height: 0;
}
.workflow-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 16px; padding: 18px 24px 12px;
  border-bottom: 1px solid var(--rb-border);
  background: var(--rb-bg-surface);
}
.workflow-header h1 { margin: 0; font-size: 20px; font-weight: 600; }
.workflow-header .muted { margin: 4px 0 0; color: var(--rb-text-secondary); font-size: 13px; max-width: 760px; }
.header-actions { display: flex; align-items: center; gap: 8px; }

.workflow-body {
  display: grid; grid-template-columns: 340px 1fr;
  flex: 1; min-height: 0; overflow: hidden;
}

.prompt-list {
  border-right: 1px solid var(--rb-border);
  background: var(--rb-bg-surface);
  overflow-y: auto; padding: 12px 8px;
}
.search { margin-bottom: 12px; }
.stage-group { margin-bottom: 14px; }
.stage-title {
  font-size: 11px; font-weight: 600; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--rb-text-muted);
  padding: 4px 8px; margin-bottom: 6px;
}
.prompt-row {
  padding: 12px 12px; border-radius: 10px; cursor: pointer;
  transition: background var(--rb-transition-fast);
  margin-bottom: 6px; border: 1px solid transparent;
}
.prompt-row:hover { background: var(--rb-bg-subtle); }
.prompt-row.active { background: var(--rb-primary-bg); border-color: var(--rb-primary-light); }
.row-top {
  display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px;
}
.row-zh { font-size: 14px; font-weight: 600; color: var(--rb-text-primary); }
.row-tags { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.row-bottom { margin-bottom: 6px; }
.row-zh-name { font-size: 12px; color: var(--rb-text-secondary); }
.row-keys { display: flex; flex-wrap: wrap; gap: 4px; }
.key-chip {
  background: var(--rb-bg-subtle); color: var(--rb-text-muted);
  padding: 1px 6px; border-radius: 5px; font-size: 10.5px;
}
.key-inline { font-family: 'SFMono-Regular', 'Cascadia Code', Consolas, monospace; font-size: 12px; color: var(--rb-text-secondary); }

.prompt-detail {
  overflow-y: auto; padding: 20px 28px; background: var(--rb-bg-base);
}
.detail-head {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin-bottom: 8px;
}
.detail-head h2 { margin: 0; font-size: 18px; font-weight: 600; }
.head-tags { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
.head-actions { display: flex; gap: 8px; }
.description { color: var(--rb-text-secondary); font-size: 13px; line-height: 1.7; margin: 10px 0 14px; }

.key-card {
  background: var(--rb-bg-surface); border: 1px solid var(--rb-border);
  border-radius: 14px; padding: 16px 18px; margin-bottom: 18px;
}
.card-head {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding-bottom: 10px; border-bottom: 1px solid var(--rb-border-light);
}
.card-title { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; min-width: 0; }
.card-zh { font-size: 15px; font-weight: 600; color: var(--rb-text-primary); }
.card-key { font-size: 12px; color: var(--rb-text-muted); font-family: 'SFMono-Regular', 'Cascadia Code', Consolas, monospace; }
.card-actions { display: flex; gap: 6px; flex-shrink: 0; }
.card-desc { font-size: 12.5px; line-height: 1.65; margin: 8px 0 10px; color: var(--rb-text-secondary); }

.placeholders { margin-bottom: 10px; }
.ph-caption { font-size: 12px; color: var(--rb-text-muted); }
.ph-list { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 6px; }
.ph-chip {
  background: var(--rb-primary-bg); color: var(--rb-primary-dark);
  padding: 2px 8px; border-radius: 6px; font-size: 12px; cursor: help;
}

.editor-wrap { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
.prompt-editor {
  width: 100%; resize: vertical; min-height: 200px;
  font-family: 'SFMono-Regular', 'Cascadia Code', Consolas, monospace;
  font-size: 12.5px; line-height: 1.6;
  background: var(--rb-bg-base); color: var(--rb-text-primary);
  border: 1px solid var(--rb-border); border-radius: 10px; padding: 12px 14px;
}
.prompt-editor:focus { outline: none; border-color: var(--rb-primary-light); }

.highlight-preview { margin-top: 8px; }
.hp-title { font-size: 12px; margin-bottom: 4px; }
.hp-body {
  background: var(--rb-bg-base); border: 1px solid var(--rb-border-light); border-radius: 8px;
  padding: 10px 12px; margin: 0;
  font-family: 'SFMono-Regular', 'Cascadia Code', Consolas, monospace;
  font-size: 12.5px; line-height: 1.6; white-space: pre-wrap;
  max-height: 220px; overflow: auto;
}
.hp-body :deep(.ph) { background: var(--rb-primary-bg); color: var(--rb-primary-dark); border-radius: 3px; padding: 0 2px; }
.dirty-mark { color: var(--rb-accent-amber); font-weight: 500; font-size: 12px; margin-left: 4px; }

.ph-inline { background: var(--rb-primary-bg); color: var(--rb-primary-dark); padding: 0 4px; border-radius: 4px; }

.preview-area {
  margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--rb-border);
}
.preview-controls { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.preview-controls .caption { font-size: 13px; color: var(--rb-text-secondary); }
.preview-output {
  margin-top: 8px; background: var(--rb-bg-surface); border: 1px solid var(--rb-border); border-radius: 10px;
}
.po-title { font-size: 12px; padding: 8px 12px 0; }
.po-body {
  margin: 0; padding: 8px 12px 12px;
  font-family: 'SFMono-Regular', 'Cascadia Code', Consolas, monospace;
  font-size: 12.5px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;
  color: var(--rb-text-primary); max-height: 480px; overflow: auto;
}

.prompt-empty { display: flex; align-items: center; justify-content: center; }
.muted { color: var(--rb-text-muted); }
code { font-family: 'SFMono-Regular', 'Cascadia Code', Consolas, monospace; font-size: 12px; }
</style>