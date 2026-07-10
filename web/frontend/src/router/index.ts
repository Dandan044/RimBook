import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', name: 'dashboard', component: () => import('../views/Dashboard.vue') },
    { path: '/codex', name: 'codex', component: () => import('../views/CodexManager.vue') },
    { path: '/outline', name: 'outline', component: () => import('../views/OutlineEditor.vue') },
    { path: '/writer', name: 'writer', component: () => import('../views/WriterStudio.vue') },
    { path: '/settings', name: 'settings', component: () => import('../views/Settings.vue') },
  ],
})

export default router
