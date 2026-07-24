<template>
  <div class="settings-page">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon class="title-icon"><Setting /></el-icon>
        设置
      </h1>
    </div>

    <div class="settings-layout">
      <!-- Left: project list -->
      <div class="project-list-panel">
        <div class="project-list-card">
          <div class="project-list-header">
            <span class="list-title">项目</span>
          </div>
          <div class="project-list-scroll">
            <div v-for="p in projects" :key="p.id"
              class="project-item"
              :class="{ active: selectedId === p.id }"
              @click="selectProject(p.id)">
              <div class="project-item-info">
                <strong class="project-item-title">{{ p.title || p.id }}</strong>
                <div class="project-meta">{{ p.author || '未设作者' }}</div>
              </div>
              <el-tag size="small" effect="plain">{{ p.language }}</el-tag>
            </div>
            <div v-if="!projects.length" class="empty-list">
              <el-icon :size="24" class="empty-icon"><Folder /></el-icon>
              <span>暂无项目</span>
              <span class="empty-sub">请先在仪表盘创建</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: config tabs -->
      <div class="config-panel">
        <el-tabs v-model="activeTab" class="config-tabs" @tab-change="onTabChange">
          <!-- Tab 1: Global model config (always available) -->
          <el-tab-pane label="全局模型配置" name="global">
            <template v-if="globalConfig">
              <!-- LLM config -->
              <div class="config-card">
                <div class="config-card-header">
                  <h2 class="config-title"><el-icon><Cpu /></el-icon> LLM 模型</h2>
                </div>
                <div class="config-card-body">
                  <el-alert type="info" :closable="false" class="config-alert">
                    此配置适配<strong>所有项目</strong>。支持 OpenAI 兼容协议端点（OpenAI、vLLM、Ollama 等）。
                    API Key 也可通过环境变量 <code>RIMBOOK_API_KEY</code> 设置（优先级更高）。
                  </el-alert>
                  <el-form label-width="100px">
                    <el-form-item label="Base URL">
                      <el-input v-model="globalConfig.llm.base_url" placeholder="https://api.openai.com/v1" />
                    </el-form-item>
                    <el-form-item label="API Key">
                      <el-input v-model="globalConfig.llm.api_key" type="password" show-password placeholder="sk-... 或留空用环境变量" />
                    </el-form-item>
                    <el-form-item label="写作模型">
                      <el-input v-model="globalConfig.llm.model" placeholder="gpt-4o" />
                    </el-form-item>
                    <el-form-item label="校验模型">
                      <el-input v-model="globalConfig.llm.check_model" placeholder="gpt-4o-mini（留空则同写作模型）" />
                    </el-form-item>
                    <el-form-item label="推理模式">
                      <el-select v-model="globalConfig.llm.reasoning_effort" placeholder="关闭" clearable style="width: 200px">
                        <el-option label="关闭" value="" />
                        <el-option label="低" value="low" />
                        <el-option label="中" value="medium" />
                        <el-option label="高" value="high" />
                      </el-select>
                      <span class="form-hint">开启后模型进行深度推理，适用于复杂创作任务；不支持该参数的模型将自动忽略</span>
                    </el-form-item>
                  </el-form>
                  <div class="test-bar">
                    <el-button @click="doTestLLM" :loading="testLLMLoading">
                      <el-icon><Connection /></el-icon> 测试连通性
                    </el-button>
                    <el-tag v-if="testLLMResult !== null" :type="testLLMResult.ok ? 'success' : 'danger'" effect="plain">
                      {{ testLLMResult.ok ? `连通成功 (${testLLMResult.model})` : testLLMResult.error }}
                    </el-tag>
                  </div>
                </div>
              </div>

              <!-- Embedding config -->
              <div class="config-card">
                <div class="config-card-header">
                  <h2 class="config-title"><el-icon><Coin /></el-icon> 嵌入模型</h2>
                </div>
                <div class="config-card-body">
                  <el-alert type="info" :closable="false" class="config-alert">
                    用于向量检索（RAG 补充上下文）。留空则复用上方 LLM 配置。
                  </el-alert>
                  <el-form label-width="100px">
                    <el-form-item label="Base URL">
                      <el-input v-model="globalConfig.llm.embedding.base_url" placeholder="留空则复用 LLM Base URL" />
                    </el-form-item>
                    <el-form-item label="API Key">
                      <el-input v-model="globalConfig.llm.embedding.api_key" type="password" show-password placeholder="留空则复用 LLM API Key" />
                    </el-form-item>
                    <el-form-item label="模型">
                      <el-input v-model="globalConfig.llm.embedding.model" placeholder="text-embedding-3-small" />
                    </el-form-item>
                  </el-form>
                  <div class="test-bar">
                    <el-button @click="doTestEmbedding" :loading="testEmbeddingLoading">
                      <el-icon><Connection /></el-icon> 测试连通性
                    </el-button>
                    <el-tag v-if="testEmbeddingResult !== null" :type="testEmbeddingResult.ok ? 'success' : 'danger'" effect="plain">
                      {{ testEmbeddingResult.ok ? `连通成功 (${testEmbeddingResult.model})` : testEmbeddingResult.error }}
                    </el-tag>
                  </div>
                </div>
              </div>

              <div class="save-section">
                <el-button type="primary" size="large" @click="saveGlobalConfig" :loading="savingGlobal">
                  <el-icon><Check /></el-icon> 保存全局配置
                </el-button>
              </div>
            </template>
          </el-tab-pane>

          <!-- Tab 2: Per-project config -->
          <el-tab-pane label="项目配置" name="project" :disabled="!selectedId">
            <template v-if="projectConfig">
              <!-- Project info -->
              <div class="config-card">
                <div class="config-card-header">
                  <h2 class="config-title"><el-icon><Document /></el-icon> 项目信息</h2>
                </div>
                <div class="config-card-body">
                  <el-form :model="projectConfig" label-width="80px">
                    <el-form-item label="标题">
                      <el-input v-model="projectConfig.title" />
                    </el-form-item>
                    <el-form-item label="作者">
                      <el-input v-model="projectConfig.author" />
                    </el-form-item>
                    <el-form-item label="语言">
                      <el-select v-model="projectConfig.language">
                        <el-option label="中文" value="zh" />
                        <el-option label="English" value="en" />
                        <el-option label="日本語" value="ja" />
                      </el-select>
                    </el-form-item>
                  </el-form>
                </div>
              </div>

              <!-- Generation config -->
              <div class="config-card">
                <div class="config-card-header">
                  <h2 class="config-title"><el-icon><SetUp /></el-icon> 生成参数</h2>
                </div>
                <div class="config-card-body">
                  <el-form label-width="140px">
                    <el-form-item label="Temperature">
                      <el-slider v-model="projectConfig.generation.temperature" :min="0" :max="2" :step="0.05" show-input />
                    </el-form-item>
                    <el-form-item label="Max Tokens">
                      <el-input-number v-model="projectConfig.generation.max_tokens" :min="500" :max="100000" :step="500" />
                    </el-form-item>
                    <el-form-item label="Top P">
                      <el-slider v-model="projectConfig.generation.top_p" :min="0" :max="1" :step="0.05" show-input />
                    </el-form-item>
                    <el-form-item label="滑动窗口章数">
                      <el-input-number v-model="projectConfig.generation.recent_window_chapters" :min="0" :max="5" />
                      <span class="form-hint">最近 N 章原文直接传入上下文</span>
                    </el-form-item>
                    <el-form-item label="摘要历史章数">
                      <el-input-number v-model="projectConfig.generation.summary_history" :min="0" :max="20" />
                      <span class="form-hint">携带的章节摘要数量</span>
                    </el-form-item>
                    <el-form-item label="自动一致性校验">
                      <el-switch v-model="projectConfig.generation.auto_consistency_check" />
                    </el-form-item>
                    <el-form-item label="自动修复">
                      <el-switch v-model="projectConfig.generation.auto_fix" />
                      <span class="form-hint">校验发现问题时自动修订</span>
                    </el-form-item>
                    <el-form-item label="最大修复轮数">
                      <el-input-number v-model="projectConfig.generation.max_fix_rounds" :min="1" :max="5" />
                    </el-form-item>
                    <el-divider content-position="left">版本管理</el-divider>
                    <el-form-item label="自动检查点">
                      <el-switch v-model="projectConfig.generation.auto_checkpoint" />
                      <span class="form-hint">写章/改章前自动创建增量快照</span>
                    </el-form-item>
                    <el-form-item label="最大检查点数">
                      <el-input-number v-model="projectConfig.generation.max_checkpoints" :min="5" :max="200" :step="5" />
                      <span class="form-hint">超出时自动清理最旧的检查点</span>
                    </el-form-item>
                  </el-form>
                </div>
              </div>

              <div class="save-section">
                <el-button type="primary" size="large" @click="saveProjectConfig" :loading="savingProject">
                  <el-icon><Check /></el-icon> 保存项目配置
                </el-button>
              </div>
            </template>
            <div v-else-if="selectedId" class="loading-state">
              <el-icon class="is-loading" :size="24"><Loading /></el-icon>
              <span>加载中…</span>
            </div>
            <div v-else class="config-empty">
              <el-icon :size="40" class="empty-icon-big"><Folder /></el-icon>
              <p class="empty-main-text">选择左侧项目查看项目配置</p>
            </div>
          </el-tab-pane>

          <!-- Tab 3: Version management -->
          <el-tab-pane label="版本管理" name="versioning" :disabled="!selectedId">
            <div class="versioning-layout" v-if="selectedId">
              <!-- Left: Branch list -->
              <div class="branch-panel">
                <div class="branch-card">
                  <div class="branch-header">
                    <span class="branch-title">分支</span>
                    <el-button size="small" @click="showNewBranchDialog = true">
                      <el-icon><Plus /></el-icon>
                    </el-button>
                  </div>
                  <div class="branch-list">
                    <div v-for="b in branches" :key="b.name"
                      class="branch-item"
                      :class="{ active: b.is_current }"
                      @click="selectBranch(b.name)">
                      <div class="branch-item-info">
                        <strong class="branch-name">
                          <el-icon v-if="b.is_current" class="branch-head-icon"><CircleCheckFilled /></el-icon>
                          {{ b.name }}
                        </strong>
                        <span class="branch-meta">{{ b.checkpoint_count }} 个检查点</span>
                      </div>
                      <div class="branch-actions" v-if="!b.is_current">
                        <el-button size="small" text type="primary" @click.stop="doSwitchBranch(b.name)">切换</el-button>
                        <el-button size="small" text type="danger" @click.stop="doDeleteBranch(b.name)">删除</el-button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Right: Timeline -->
              <div class="timeline-panel">
                <div class="timeline-card">
                  <div class="timeline-header">
                    <span class="timeline-title">时间线 — {{ currentBranch }}</span>
                    <el-button size="small" type="primary" @click="doCreateCheckpoint">
                      <el-icon><Camera /></el-icon> 手动快照
                    </el-button>
                  </div>
                  <div class="timeline-body" v-if="checkpoints.length">
                    <div v-for="cp in checkpoints" :key="cp.name"
                      class="timeline-item"
                      :class="{ 'is-head': cp.name === currentBranchHead }">
                      <div class="timeline-dot"></div>
                      <div class="timeline-content">
                        <div class="timeline-top">
                          <span class="timeline-label">{{ cp.label }}</span>
                          <el-tag v-if="cp.name === currentBranchHead" size="small" type="success" effect="dark">HEAD</el-tag>
                          <el-tag v-if="forkPoints[cp.name]" size="small" type="warning" effect="plain">
                            分叉 → {{ forkPoints[cp.name].join(', ') }}
                          </el-tag>
                        </div>
                        <span class="timeline-ts">{{ cp.timestamp }}</span>
                        <span class="timeline-files">{{ cp.file_count }} 文件</span>
                        <div class="timeline-actions">
                          <el-button size="small" text type="primary" @click="doRestore(cp.name)">回滚到此</el-button>
                          <el-button size="small" text @click="openBranchDialog(cp.name)">从此处分叉</el-button>
                          <el-button size="small" text type="danger" @click="doDeleteCheckpoint(cp.name)">删除</el-button>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div v-else class="timeline-empty">
                    <el-icon :size="32"><Clock /></el-icon>
                    <span>暂无检查点</span>
                    <span class="empty-sub">写章时自动创建，或点击上方按钮手动创建</span>
                  </div>
                </div>
              </div>
            </div>
            <div v-else class="config-empty">
              <p class="empty-main-text">选择左侧项目查看版本管理</p>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </div>
<!-- New branch dialog -->
    <el-dialog v-model="showNewBranchDialog" title="新建分支" width="400px">
      <el-form>
        <el-form-item label="分支名">
          <el-input v-model="newBranchName" placeholder="如：experimental-ending" />
        </el-form-item>
        <el-form-item label="从检查点分叉" v-if="newBranchFromCp">
          <span class="form-hint">{{ newBranchFromCp }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showNewBranchDialog = false">取消</el-button>
        <el-button type="primary" @click="doCreateBranch">创建分支</el-button>
      </template>
    </el-dialog>

    <!-- Restore confirmation dialog -->
    <el-dialog v-model="showRestoreDialog" title="确认回滚" width="450px">
      <el-alert type="warning" :closable="false" show-icon>
        <p>将项目恢复到检查点 <strong>{{ restoreTargetName }}</strong> 的状态。</p>
        <p style="margin-top:8px">当前所有文件将被覆盖，此操作不可撤销。</p>
      </el-alert>
      <template #footer>
        <el-button @click="showRestoreDialog = false">取消</el-button>
        <el-button type="danger" @click="confirmRestore">确认回滚</el-button>
      </template>
    </el-dialog>

    <!-- Switch branch confirmation dialog -->
    <el-dialog v-model="showSwitchDialog" title="切换分支" width="450px">
      <el-alert type="info" :closable="false" show-icon>
        <p>当前状态将自动保存为检查点，然后切换到分支 <strong>{{ switchTargetBranch }}</strong>。</p>
      </el-alert>
      <template #footer>
        <el-button @click="showSwitchDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmSwitchBranch">确认切换</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  listProjects,
  getProjectConfig,
  updateProjectConfig,
  getGlobalConfig,
  updateGlobalConfig,
  testLLM,
  testEmbedding,
  type ProjectInfo,
  listBranches, createBranch, switchBranch, deleteBranch, getBranchHistory,
  listCheckpoints, createCheckpoint, restoreCheckpoint, deleteCheckpoint,
  type BranchInfo, type CheckpointInfo,
} from '../api'
import { ElMessage, ElMessageBox } from 'element-plus'

interface GlobalConfigData {
  llm: {
    base_url: string
    api_key: string
    model: string
    check_model: string | null
    /** '' = off; Element Plus cannot reliably bind null as option value */
    reasoning_effort: string
    embedding: { base_url: string | null; api_key: string; model: string }
  }
}

interface ProjectConfigData {
  title: string
  author: string
  language: string
  generation: {
    temperature: number; max_tokens: number; top_p: number
    recent_window_chapters: number; summary_history: number
    auto_consistency_check: boolean; auto_fix: boolean; max_fix_rounds: number
    auto_checkpoint: boolean; max_checkpoints: number
  }
}

const activeTab = ref('global')
const projects = ref<ProjectInfo[]>([])
const selectedId = ref('')

const globalConfig = ref<GlobalConfigData | null>(null)
const projectConfig = ref<ProjectConfigData | null>(null)

const savingGlobal = ref(false)
const savingProject = ref(false)

const testLLMLoading = ref(false)
const testLLMResult = ref<{ ok: boolean; model?: string; error?: string } | null>(null)
const testEmbeddingLoading = ref(false)
const testEmbeddingResult = ref<{ ok: boolean; model?: string; error?: string } | null>(null)

// Version management state
const branches = ref<BranchInfo[]>([])
const currentBranch = ref('main')
const checkpoints = ref<CheckpointInfo[]>([])
const forkPoints = ref<Record<string, string[]>>({})
const currentBranchHead = ref('')
const showNewBranchDialog = ref(false)
const newBranchName = ref('')
const newBranchFromCp = ref<string | null>(null)
const showRestoreDialog = ref(false)
const restoreTargetName = ref('')
const showSwitchDialog = ref(false)
const switchTargetBranch = ref('')

function _isMasked(value: string): boolean {
  return value.includes('***') || value.includes('\u2026')
}

async function fetchProjects() {
  projects.value = await listProjects()
  if (!selectedId.value && projects.value.length) {
    selectedId.value = projects.value[0].id
    await loadProjectConfig()
  }
}

async function selectProject(id: string) {
  selectedId.value = id
  activeTab.value = 'project'
  await loadProjectConfig()
}

function onTabChange(tab: string) {
  if (tab === 'versioning') loadVersionData()
}

// ---- Global config ----
async function loadGlobalConfig() {
  try {
    const data = await getGlobalConfig()
    globalConfig.value = {
      llm: {
        base_url: data.llm?.base_url || '',
        api_key: data.llm?.api_key || '',
        model: data.llm?.model || '',
        check_model: data.llm?.check_model || null,
        // Normalize null → '' so el-select can bind (null option values are broken in Element Plus)
        reasoning_effort: data.llm?.reasoning_effort || '',
        embedding: {
          base_url: data.llm?.embedding?.base_url || null,
          api_key: data.llm?.embedding?.api_key || '',
          model: data.llm?.embedding?.model || '',
        },
      },
    }
  } catch {
    globalConfig.value = null
  }
}

async function saveGlobalConfig() {
  if (!globalConfig.value) return
  savingGlobal.value = true
  try {
    const c = globalConfig.value
    const payload: Record<string, any> = {
      base_url: c.llm.base_url,
      model: c.llm.model,
      check_model: c.llm.check_model,
      // Always send the field: '' means explicitly turn off (backend maps to null)
      reasoning_effort: c.llm.reasoning_effort || null,
      embed_base_url: c.llm.embedding.base_url,
      embed_model: c.llm.embedding.model,
    }
    // Only send API key if not masked (user actually changed it).
    if (!_isMasked(c.llm.api_key) && c.llm.api_key) {
      payload.api_key = c.llm.api_key
    }
    if (!_isMasked(c.llm.embedding.api_key) && c.llm.embedding.api_key) {
      payload.embed_api_key = c.llm.embedding.api_key
    }
    await updateGlobalConfig(payload)
    await loadGlobalConfig()
    ElMessage.success('全局配置已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    savingGlobal.value = false
  }
}

// ---- Project config ----
async function loadProjectConfig() {
  if (!selectedId.value) return
  try {
    const data = await getProjectConfig(selectedId.value)
    projectConfig.value = {
      title: data.title || '',
      author: data.author || '',
      language: data.language || 'zh',
      generation: data.generation || {
        temperature: 1.0, max_tokens: 50000, top_p: 1.0,
        recent_window_chapters: 1, summary_history: 6,
        auto_consistency_check: true, auto_fix: false, max_fix_rounds: 2,
        auto_checkpoint: true, max_checkpoints: 50,
      },
    }
  } catch {
    projectConfig.value = null
  }
}

async function saveProjectConfig() {
  if (!selectedId.value || !projectConfig.value) return
  savingProject.value = true
  try {
    const c = projectConfig.value
    await updateProjectConfig(selectedId.value, {
      title: c.title,
      author: c.author,
      language: c.language,
      temperature: c.generation.temperature,
      max_tokens: c.generation.max_tokens,
      top_p: c.generation.top_p,
      recent_window_chapters: c.generation.recent_window_chapters,
      summary_history: c.generation.summary_history,
      auto_consistency_check: c.generation.auto_consistency_check,
      auto_fix: c.generation.auto_fix,
      max_fix_rounds: c.generation.max_fix_rounds,
      auto_checkpoint: c.generation.auto_checkpoint,
      max_checkpoints: c.generation.max_checkpoints,
    })
    ElMessage.success('项目配置已保存')
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '保存失败')
  } finally {
    savingProject.value = false
  }
}

// ---- Test connectivity (uses first project) ----
async function doTestLLM() {
  if (!selectedId.value) return
  testLLMLoading.value = true
  testLLMResult.value = null
  try {
    testLLMResult.value = await testLLM(selectedId.value)
  } catch (e: any) {
    testLLMResult.value = { ok: false, error: e?.message || '请求失败' }
  } finally {
    testLLMLoading.value = false
  }
}

async function doTestEmbedding() {
  if (!selectedId.value) return
  testEmbeddingLoading.value = true
  testEmbeddingResult.value = null
  try {
    testEmbeddingResult.value = await testEmbedding(selectedId.value)
  } catch (e: any) {
    testEmbeddingResult.value = { ok: false, error: e?.message || '请求失败' }
  } finally {
    testEmbeddingLoading.value = false
  }
}

// ---- Version management ----
async function loadVersionData() {
  if (!selectedId.value) return
  try {
    const [branchData, cpData] = await Promise.all([
      listBranches(selectedId.value),
      listCheckpoints(selectedId.value),
    ])
    branches.value = branchData.branches
    currentBranch.value = branchData.current
    forkPoints.value = cpData.fork_points
    // Load checkpoints only for current branch
    const cur = branches.value.find(b => b.is_current)
    if (cur) {
      const hist = await getBranchHistory(selectedId.value, cur.name)
      checkpoints.value = hist.history.reverse() // newest first
      currentBranchHead.value = cur.head
    }
  } catch { /* ignore */ }
}

async function selectBranch(name: string) {
  try {
    const hist = await getBranchHistory(selectedId.value, name)
    checkpoints.value = hist.history.reverse()
    currentBranchHead.value = branches.value.find(b => b.name === name)?.head || ''
    forkPoints.value = hist.fork_points
  } catch { /* ignore */ }
}

async function doCreateCheckpoint() {
  if (!selectedId.value) return
  try {
    await createCheckpoint(selectedId.value, { label: `manual-${new Date().toISOString().slice(0, 10)}` })
    ElMessage.success('手动快照已创建')
    await loadVersionData()
  } catch (e: any) { ElMessage.error('创建失败') }
}

async function doCreateBranch() {
  if (!selectedId.value || !newBranchName.value.trim()) return
  const name = newBranchName.value.trim()
  try {
    await createBranch(selectedId.value, { name, from_checkpoint: newBranchFromCp.value })
    showNewBranchDialog.value = false
    newBranchName.value = ''
    newBranchFromCp.value = null
    ElMessage.success(`分支 '${name}' 已创建`)
    await loadVersionData()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '创建失败') }
}

function openBranchDialog(fromCp: string) {
  newBranchFromCp.value = fromCp
  newBranchName.value = ''
  showNewBranchDialog.value = true
}

function doSwitchBranch(name: string) {
  switchTargetBranch.value = name
  showSwitchDialog.value = true
}

async function confirmSwitchBranch() {
  if (!selectedId.value || !switchTargetBranch.value) return
  try {
    await switchBranch(selectedId.value, switchTargetBranch.value)
    showSwitchDialog.value = false
    ElMessage.success(`已切换到分支 '${switchTargetBranch.value}'`)
    await loadVersionData()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '切换失败') }
}

async function doDeleteBranch(name: string) {
  if (!selectedId.value) return
  try {
    await ElMessageBox.confirm(`确定要删除分支 '${name}' 吗？检查点不会被删除。`, '删除分支', { type: 'warning' })
    await deleteBranch(selectedId.value, name)
    ElMessage.success('分支已删除')
    await loadVersionData()
  } catch { /* cancelled */ }
}

function doRestore(name: string) {
  restoreTargetName.value = name
  showRestoreDialog.value = true
}

async function confirmRestore() {
  if (!selectedId.value || !restoreTargetName.value) return
  try {
    await restoreCheckpoint(selectedId.value, restoreTargetName.value)
    showRestoreDialog.value = false
    ElMessage.success('已回滚')
    await loadVersionData()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '回滚失败') }
}

async function doDeleteCheckpoint(name: string) {
  if (!selectedId.value) return
  try {
    await ElMessageBox.confirm(`确定要删除检查点 '${name}' 吗？`, '删除检查点', { type: 'warning' })
    await deleteCheckpoint(selectedId.value, name)
    ElMessage.success('检查点已删除')
    await loadVersionData()
  } catch { /* cancelled */ }
}

onMounted(async () => {
  await loadGlobalConfig()
  await fetchProjects()
  await loadVersionData()
})
</script>

<style scoped>
.settings-page { max-width: 1100px; margin: 0 auto; }
.page-header { margin-bottom: 24px; }
.page-title { font-size: 24px; font-weight: 700; letter-spacing: -0.03em; color: var(--rb-text-primary); margin: 0; display: flex; align-items: center; gap: 10px; }
.title-icon { color: var(--rb-primary); font-size: 22px; }
.settings-layout { display: flex; gap: 24px; align-items: flex-start; }
.project-list-panel { width: 260px; flex-shrink: 0; position: sticky; top: 24px; }
.project-list-card { background: var(--rb-bg-surface); border: 1px solid var(--rb-border-light); border-radius: 14px; overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }
.project-list-header { padding: 16px 20px; border-bottom: 1px solid var(--rb-border-light); background: var(--rb-bg-subtle); }
.list-title { font-size: 13px; font-weight: 600; color: var(--rb-text-secondary); text-transform: uppercase; letter-spacing: 0.06em; }
.project-list-scroll { max-height: calc(100vh - 200px); overflow-y: auto; padding: 8px; }
.project-item { padding: 12px 14px; border-radius: 10px; cursor: pointer; transition: all 0.15s ease; display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 2px; }
.project-item:hover { background: var(--rb-bg-subtle); }
.project-item.active { background: var(--rb-primary-bg); box-shadow: inset 0 0 0 1px var(--rb-primary-bg-hover); }
.project-item-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.project-item-title { font-size: 14px; font-weight: 600; color: var(--rb-text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.project-item.active .project-item-title { color: var(--rb-primary); }
.project-meta { font-size: 12px; color: var(--rb-text-muted); font-weight: 500; }
.empty-list { display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 40px 20px; color: var(--rb-text-muted); font-size: 13px; }
.empty-icon { color: var(--rb-text-subtle); margin-bottom: 4px; }
.empty-sub { font-size: 12px; color: var(--rb-text-subtle); }

.config-panel { flex: 1; min-width: 0; }
.config-tabs { margin-top: -8px; }
.config-card { background: var(--rb-bg-surface); border: 1px solid var(--rb-border-light); border-radius: 14px; overflow: hidden; box-shadow: 0 1px 2px rgba(0,0,0,0.03); margin-bottom: 20px; }
.config-card-header { padding: 18px 24px; border-bottom: 1px solid var(--rb-border-light); background: var(--rb-bg-subtle); }
.config-title { font-size: 15px; font-weight: 600; letter-spacing: -0.01em; color: var(--rb-text-primary); margin: 0; display: flex; align-items: center; gap: 8px; }
.config-title .el-icon { color: var(--rb-primary); font-size: 16px; }
.config-card-body { padding: 24px; }
.config-alert { margin-bottom: 20px; }
.config-alert :deep(code) { font-family: 'SF Mono', ui-monospace, monospace; font-size: 12px; background: var(--rb-bg-subtle); padding: 2px 6px; border-radius: 4px; }
.save-section { text-align: center; padding: 8px 0 24px; }
.test-bar { display: flex; align-items: center; gap: 12px; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--rb-border-light); }
.form-hint { margin-left: 12px; color: var(--rb-text-muted); font-size: 12px; font-weight: 500; }
.loading-state { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 60px 20px; color: var(--rb-text-muted); font-size: 14px; }
.config-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; background: var(--rb-bg-surface); border: 1px solid var(--rb-border-light); border-radius: 14px; min-height: 300px; }
.empty-icon-big { color: var(--rb-text-subtle); margin-bottom: 12px; }
.empty-main-text { font-size: 16px; font-weight: 500; color: var(--rb-text-secondary); margin: 0 0 4px; }

@media (max-width: 768px) {
  .settings-layout { flex-direction: column; }
  .project-list-panel { width: 100%; position: static; }
  .project-list-scroll { max-height: 240px; }
}

/* ===== Version Management ===== */
.versioning-layout { display: flex; gap: 20px; min-height: 500px; }
.branch-panel { width: 200px; flex-shrink: 0; }
.branch-card { background: var(--rb-bg-surface); border: 1px solid var(--rb-border-light); border-radius: 14px; overflow: hidden; }
.branch-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 16px; border-bottom: 1px solid var(--rb-border-light); }
.branch-title { font-size: 13px; font-weight: 600; color: var(--rb-text-secondary); text-transform: uppercase; letter-spacing: 0.06em; }
.branch-list { padding: 8px; }
.branch-item { padding: 10px 12px; border-radius: 8px; cursor: pointer; transition: background 0.15s; margin-bottom: 4px; display: flex; justify-content: space-between; align-items: center; }
.branch-item:hover { background: var(--rb-bg-subtle); }
.branch-item.active { background: var(--rb-primary-bg); }
.branch-item-info { display: flex; flex-direction: column; gap: 2px; }
.branch-name { font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 4px; }
.branch-head-icon { color: var(--rb-primary); font-size: 14px; }
.branch-meta { font-size: 11px; color: var(--rb-text-muted); }
.branch-actions { display: flex; gap: 2px; }

.timeline-panel { flex: 1; min-width: 0; }
.timeline-card { background: var(--rb-bg-surface); border: 1px solid var(--rb-border-light); border-radius: 14px; overflow: hidden; }
.timeline-header { display: flex; justify-content: space-between; align-items: center; padding: 14px 20px; border-bottom: 1px solid var(--rb-border-light); }
.timeline-title { font-size: 15px; font-weight: 600; color: var(--rb-text-primary); }
.timeline-body { padding: 16px 20px; max-height: calc(100vh - 320px); overflow-y: auto; }
.timeline-item { display: flex; gap: 14px; padding-bottom: 20px; position: relative; }
.timeline-item:not(:last-child)::after { content: ''; position: absolute; left: 5px; top: 16px; bottom: 0; width: 2px; background: var(--rb-border-light); }
.timeline-dot { width: 12px; height: 12px; border-radius: 50%; background: var(--rb-border); flex-shrink: 0; margin-top: 4px; }
.timeline-item.is-head .timeline-dot { background: var(--rb-primary); box-shadow: 0 0 0 3px var(--rb-primary-bg); }
.timeline-content { flex: 1; }
.timeline-top { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; flex-wrap: wrap; }
.timeline-label { font-size: 14px; font-weight: 600; color: var(--rb-text-primary); }
.timeline-ts { font-size: 12px; color: var(--rb-text-muted); }
.timeline-files { font-size: 12px; color: var(--rb-text-muted); margin-left: 8px; }
.timeline-actions { margin-top: 8px; display: flex; gap: 4px; }
.timeline-empty { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 60px 20px; color: var(--rb-text-muted); font-size: 14px; }

@media (max-width: 768px) {
  .versioning-layout { flex-direction: column; }
  .branch-panel { width: 100%; }
}
</style>
