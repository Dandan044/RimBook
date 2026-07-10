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
        <el-tabs v-model="activeTab" class="config-tabs">
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
                      <el-input-number v-model="projectConfig.generation.max_tokens" :min="500" :max="16000" :step="500" />
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
        </el-tabs>
      </div>
    </div>
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
} from '../api'
import { ElMessage } from 'element-plus'

interface GlobalConfigData {
  llm: {
    base_url: string
    api_key: string
    model: string
    check_model: string | null
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
        temperature: 0.85, max_tokens: 4000, top_p: 1.0,
        recent_window_chapters: 1, summary_history: 6,
        auto_consistency_check: true, auto_fix: false, max_fix_rounds: 2,
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

onMounted(async () => {
  await loadGlobalConfig()
  await fetchProjects()
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
</style>
