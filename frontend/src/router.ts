import { createRouter, createWebHistory } from 'vue-router'

import BatchCreate from './pages/batches/BatchCreate.vue'
import BatchDetail from './pages/batches/BatchDetail.vue'
import BatchList from './pages/batches/BatchList.vue'
import ProjectConfig from './pages/projects/ProjectConfig.vue'
import ProjectCreate from './pages/projects/ProjectCreate.vue'
import ProjectShell from './pages/projects/ProjectShell.vue'
import ProjectList from './pages/projects/ProjectList.vue'
import SystemSettings from './pages/settings/SystemSettings.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: ProjectList },
    { path: '/batches', component: BatchList },
    { path: '/batches/new', component: BatchCreate },
    { path: '/batches/:id', component: BatchDetail },
    { path: '/projects/new', component: ProjectCreate },
    { path: '/projects/:id', component: ProjectShell },
    { path: '/projects/:id/config', component: ProjectConfig },
    { path: '/settings', component: SystemSettings },
  ],
})

export default router
