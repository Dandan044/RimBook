<template>
  <el-container class="app-container">
    <el-aside :width="asideWidth" class="app-aside">
      <div class="logo" @click="toggleCollapse">
        <svg class="logo-svg" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M8 7h8M8 11h5" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
        <transition name="logo-text">
          <span v-if="!collapsed" class="logo-text">RimBook</span>
        </transition>
      </div>
      <el-menu
        :default-active="currentRoute"
        router
        class="app-menu"
        :collapse="collapsed"
        :collapse-transition="true"
      >
        <el-menu-item index="/dashboard">
          <el-icon><DataAnalysis /></el-icon>
          <template #title>仪表盘</template>
        </el-menu-item>
        <el-menu-item index="/outline">
          <el-icon><Document /></el-icon>
          <template #title>写作规划</template>
        </el-menu-item>
        <el-menu-item index="/writer">
          <el-icon><EditPen /></el-icon>
          <template #title>写作</template>
        </el-menu-item>
        <el-menu-item index="/codex">
          <el-icon><Collection /></el-icon>
          <template #title>设定集</template>
        </el-menu-item>
        <el-menu-item index="/workflow">
          <el-icon><Connection /></el-icon>
          <template #title>工作流</template>
        </el-menu-item>
        <el-menu-item index="/llm-logs">
          <el-icon><Tickets /></el-icon>
          <template #title>LLM 日志</template>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <template #title>设置</template>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer">
        <!-- ---- Server management ---- -->
        <div class="server-status-area">
          <div class="server-status-row" :class="{ collapsed: collapsed }">
            <el-tooltip :content="serverTooltip" placement="right" :disabled="!collapsed">
              <span class="server-dot" :class="serverDotClass"></span>
            </el-tooltip>
            <transition name="logo-text">
              <div v-if="!collapsed" class="server-info">
                <span class="server-label">{{ serverLabel }}</span>
              </div>
            </transition>
          </div>
          <transition name="logo-text">
            <div v-if="!collapsed && serverStatus?.running" class="server-actions">
              <el-button size="small" text @click="doRestartServer" :loading="serverActionLoading === 'restart'" class="server-action-btn">
                <el-icon :size="12"><Refresh /></el-icon> 重启
              </el-button>
              <el-button size="small" text @click="doStopServer" :loading="serverActionLoading === 'stop'" class="server-action-btn server-stop-btn">
                <el-icon :size="12"><Close /></el-icon> 停止
              </el-button>
            </div>
          </transition>
          <transition name="logo-text">
            <div v-if="!collapsed && !serverStatus?.running" class="server-actions">
              <el-button size="small" text @click="doStartServer" :loading="serverActionLoading === 'start'" class="server-action-btn">
                <el-icon :size="12"><VideoPlay /></el-icon> 启动
              </el-button>
            </div>
          </transition>
        </div>
        <div class="sidebar-separator"></div>
        <!-- ---- Theme toggle ---- -->
        <div class="theme-toggle" @click="toggleTheme">
          <el-icon :size="16">
            <Moon v-if="!isDark" />
            <Sunny v-else />
          </el-icon>
          <transition name="logo-text">
            <span v-if="!collapsed" class="theme-label">{{ isDark ? '浅色模式' : '深色模式' }}</span>
          </transition>
        </div>
        <div class="collapse-toggle" @click="toggleCollapse">
          <el-icon :size="16">
            <Fold v-if="!collapsed" />
            <Expand v-else />
          </el-icon>
          <transition name="logo-text">
            <span v-if="!collapsed" class="collapse-label">收起菜单</span>
          </transition>
        </div>
      </div>
    </el-aside>
    <el-main class="app-main">
      <router-view v-slot="{ Component }">
        <transition name="fade-slide" mode="out-in">
          <component :is="Component" />
        </transition>
      </router-view>
    </el-main>
  </el-container>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  getServerStatus,
  startServer,
  stopServer,
  restartServer,
  type ServerStatus,
} from './api'

const route = useRoute()
const currentRoute = computed(() => route.path)

const collapsed = ref(false)
const asideWidth = computed(() => collapsed.value ? '64px' : '220px')

function toggleCollapse() {
  collapsed.value = !collapsed.value
}

// ===== Theme management =====
const THEME_KEY = 'rimbook-theme'
const isDark = ref(false)

function applyTheme(dark: boolean, animate = true) {
  const html = document.documentElement
  if (animate) {
    html.classList.add('theme-transitioning')
    setTimeout(() => html.classList.remove('theme-transitioning'), 400)
  }
  html.setAttribute('data-theme', dark ? 'dark' : 'light')
  isDark.value = dark
  try { localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light') } catch {}
}

function toggleTheme() {
  applyTheme(!isDark.value)
}

// Auto-collapse on narrow screens
function onResize() {
  collapsed.value = window.innerWidth < 768
}
onMounted(() => {
  onResize()
  window.addEventListener('resize', onResize)
  // Restore theme preference
  try {
    const saved = localStorage.getItem(THEME_KEY)
    if (saved === 'dark') {
      applyTheme(true, false)
    } else if (saved === 'light') {
      applyTheme(false, false)
    } else if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
      applyTheme(true, false)
    }
  } catch {}
  // Start server status polling
  startServerPolling()
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  stopServerPolling()
})

// ===== Server management =====
const serverStatus = ref<ServerStatus | null>(null)
const serverActionLoading = ref<string | null>(null)
let _serverPollTimer: ReturnType<typeof setInterval> | null = null

const serverDotClass = computed(() => {
  if (serverActionLoading.value) return 'server-dot-busy'
  if (serverStatus.value?.running) return 'server-dot-online'
  return 'server-dot-offline'
})

const serverLabel = computed(() => {
  if (serverActionLoading.value === 'start') return '正在启动…'
  if (serverActionLoading.value === 'stop') return '正在停止…'
  if (serverActionLoading.value === 'restart') return '完整重启中…'
  if (serverStatus.value?.running) {
    const port = serverStatus.value.port
    return port ? `服务运行中 :${port}` : '服务运行中'
  }
  return '服务已停止'
})

const serverTooltip = computed(() => {
  if (serverStatus.value?.running) {
    const port = serverStatus.value.port
    return port ? `运行中 — 端口 ${port}` : '运行中'
  }
  return '服务已停止'
})

async function fetchServerStatus() {
  try {
    serverStatus.value = await getServerStatus()
  } catch {
    // If the server is down the request itself will fail — that's expected.
    serverStatus.value = { running: false, pid: null, port: null, url: null }
  }
}

function startServerPolling() {
  stopServerPolling()
  fetchServerStatus()
  _serverPollTimer = setInterval(fetchServerStatus, 5000)
}

function stopServerPolling() {
  if (_serverPollTimer !== null) {
    clearInterval(_serverPollTimer)
    _serverPollTimer = null
  }
}

async function doStartServer() {
  serverActionLoading.value = 'start'
  try {
    const result = await startServer()
    if (result.url) {
      window.open(result.url, '_blank')
    }
    await fetchServerStatus()
  } catch (e: any) {
    console.error('Failed to start server:', e)
  } finally {
    serverActionLoading.value = null
  }
}

async function doStopServer() {
  serverActionLoading.value = 'stop'
  try {
    await stopServer()
    await fetchServerStatus()
  } catch (e: any) {
    console.error('Failed to stop server:', e)
  } finally {
    serverActionLoading.value = null
  }
}

async function sleep(ms: number) {
  await new Promise((r) => setTimeout(r, ms))
}

async function doRestartServer() {
  serverActionLoading.value = 'restart'
  ElMessage.info('完整重启：清理进程 → 重建前端 → 重新启动（约 1 分钟）')
  let expectedUrl: string | undefined
  try {
    try {
      const result = await restartServer()
      expectedUrl = result.url
    } catch (e: any) {
      // Server may die before the response arrives — supervisor still runs.
      console.warn('restart request ended early (expected during full restart):', e)
    }

    // Poll until the new server is up, then open the UI.
    const deadline = Date.now() + 180_000
    while (Date.now() < deadline) {
      await sleep(2000)
      try {
        const s = await getServerStatus()
        if (s.running && s.url) {
          serverStatus.value = s
          window.open(s.url, '_blank')
          ElMessage.success('重启完成，已打开前端')
          return
        }
      } catch {
        // still down — keep waiting
      }
    }
    if (expectedUrl) {
      window.open(expectedUrl, '_blank')
    }
    ElMessage.warning('重启耗时较长，请手动刷新或查看 ~/.rimbook/full_restart.log')
    await fetchServerStatus()
  } finally {
    serverActionLoading.value = null
  }
}

</script>

<style>
html, body, #app { margin: 0; padding: 0; height: 100%; }

.app-container {
  height: 100vh;
}

/* ===== Sidebar ===== */
.app-aside {
  background: var(--rb-sidebar-bg);
  display: flex;
  flex-direction: column;
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
  border-right: 1px solid rgba(255, 255, 255, 0.06);
  position: relative;
}

/* Subtle gradient overlay on sidebar */
.app-aside::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(99, 102, 241, 0.08) 0%, transparent 40%);
  pointer-events: none;
  z-index: 0;
}

/* Logo area */
.logo {
  height: 56px;
  display: flex;
  align-items: center;
  padding: 0 18px;
  gap: 10px;
  cursor: pointer;
  flex-shrink: 0;
  white-space: nowrap;
  position: relative;
  z-index: 1;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.logo-svg {
  width: 24px;
  height: 24px;
  color: var(--rb-primary-light);
  flex-shrink: 0;
  transition: transform 0.3s ease;
}

.logo:hover .logo-svg {
  transform: scale(1.08);
}

.logo-text {
  font-size: 17px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: #ffffff;
  transition: opacity 0.2s ease;
}

.logo-text-enter-active,
.logo-text-leave-active {
  transition: opacity 0.2s ease;
}
.logo-text-enter-from,
.logo-text-leave-to {
  opacity: 0;
}

/* Menu */
.app-menu {
  border-right: none;
  background: transparent;
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  position: relative;
  z-index: 1;
}

.app-menu .el-menu-item {
  color: var(--rb-sidebar-text);
  font-weight: 500;
  font-size: 14px;
  letter-spacing: -0.01em;
  border-radius: 8px;
  margin-bottom: 2px;
  height: 40px;
  line-height: 40px;
  transition: all 0.15s ease;
}

.app-menu .el-menu-item:hover {
  color: var(--rb-sidebar-text-hover);
  background: var(--rb-sidebar-hover);
}

.app-menu .el-menu-item.is-active {
  color: var(--rb-sidebar-text-active);
  background: var(--rb-primary);
  box-shadow: 0 2px 8px rgba(99, 102, 241, 0.4);
}

.app-menu .el-menu-item.is-active .el-icon {
  color: var(--rb-sidebar-text-active);
}

.app-menu .el-menu-item .el-icon {
  font-size: 18px;
  color: inherit;
  margin-right: 8px;
}

/* Sidebar footer */
.sidebar-footer {
  flex-shrink: 0;
  padding: 8px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.theme-toggle {
  height: 40px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  color: var(--rb-sidebar-text);
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.15s ease;
  font-size: 13px;
  font-weight: 500;
}

.theme-toggle:hover {
  color: var(--rb-sidebar-text-hover);
  background: var(--rb-sidebar-hover);
}

.theme-label {
  white-space: nowrap;
  transition: opacity 0.2s ease;
}

.collapse-toggle {
  height: 40px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  color: var(--rb-sidebar-text);
  cursor: pointer;
  border-radius: 8px;
  transition: all 0.15s ease;
  font-size: 13px;
  font-weight: 500;
}

.collapse-toggle:hover {
  color: var(--rb-sidebar-text-hover);
  background: var(--rb-sidebar-hover);
}

.collapse-label {
  white-space: nowrap;
  transition: opacity 0.2s ease;
}

/* ===== Main Content ===== */
.app-main {
  background: var(--rb-bg-base);
  padding: 24px;
  overflow-y: auto;
  min-width: 0;
}

/* Page transition */
.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: opacity 0.25s ease, transform 0.25s ease;
}
.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(12px);
}
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

/* ===== Scrollbar in sidebar ===== */
.app-menu::-webkit-scrollbar {
  width: 6px;
}
.app-menu::-webkit-scrollbar-track {
  background: transparent;
}
.app-menu::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.22);
  border-radius: 3px;
}
.app-menu::-webkit-scrollbar-thumb:hover {
  background: rgba(255, 255, 255, 0.35);
}

/* ===== Server management in sidebar ===== */
.server-status-area {
  padding: 4px 8px;
  margin-bottom: 4px;
}

.server-status-row {
  display: flex;
  align-items: center;
  gap: 0;
  padding: 8px 4px;
  border-radius: 8px;
  transition: background var(--rb-transition-fast);
}

.server-status-row.collapsed {
  justify-content: center;
  padding: 6px 0;
}

.server-dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  transition: background-color 0.3s ease, box-shadow 0.3s ease;
}

.server-dot-online {
  background: #10b981;
  box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);
}

.server-dot-offline {
  background: #6e7681;
  box-shadow: none;
}

.server-dot-busy {
  background: #f59e0b;
  box-shadow: 0 0 6px rgba(245, 158, 11, 0.5);
  animation: dot-pulse 1s ease-in-out infinite;
}

@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.server-info {
  flex: 1;
  min-width: 0;
}

.server-label {
  font-size: 12px;
  font-weight: 500;
  color: var(--rb-sidebar-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  display: block;
}

.server-status-area:hover .server-label {
  color: var(--rb-sidebar-text-hover);
}

.server-actions {
  display: flex;
  gap: 2px;
  padding: 2px 0 4px 0;
}

.server-action-btn {
  --el-button-text-color: var(--rb-sidebar-text) !important;
  --el-button-hover-text-color: var(--rb-sidebar-text-hover) !important;
  font-size: 11px !important;
  padding: 2px 6px !important;
  height: auto !important;
  min-height: 24px !important;
}

.server-action-btn:hover {
  background: var(--rb-sidebar-hover) !important;
}

.server-stop-btn {
  --el-button-hover-text-color: #f87171 !important;
}

.sidebar-separator {
  height: 1px;
  background: rgba(255, 255, 255, 0.06);
  margin: 2px 8px;
}

/* ===== Collapsed menu adjustments ===== */
.el-menu--collapse .el-menu-item {
  padding: 0 !important;
  text-align: center;
}
</style>
