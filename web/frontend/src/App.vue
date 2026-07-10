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
        <el-menu-item index="/codex">
          <el-icon><Collection /></el-icon>
          <template #title>设定集</template>
        </el-menu-item>
        <el-menu-item index="/outline">
          <el-icon><Document /></el-icon>
          <template #title>大纲</template>
        </el-menu-item>
        <el-menu-item index="/writer">
          <el-icon><EditPen /></el-icon>
          <template #title>写作</template>
        </el-menu-item>
        <el-menu-item index="/settings">
          <el-icon><Setting /></el-icon>
          <template #title>设置</template>
        </el-menu-item>
      </el-menu>
      <div class="sidebar-footer">
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
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
})
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
  width: 4px;
}
.app-menu::-webkit-scrollbar-track {
  background: transparent;
}
.app-menu::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
}

/* ===== Collapsed menu adjustments ===== */
.el-menu--collapse .el-menu-item {
  padding: 0 !important;
  text-align: center;
}
</style>
