import { createRouter, createWebHistory } from 'vue-router'

import ProjectConfig from './pages/ProjectConfig.vue'
import ProjectCreate from './pages/ProjectCreate.vue'
import ProjectDetail from './pages/ProjectDetail.vue'
import ProjectList from './pages/ProjectList.vue'
import SystemSettings from './pages/SystemSettings.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: ProjectList },
    { path: '/projects/new', component: ProjectCreate },
    { path: '/projects/:id', component: ProjectDetail },
    { path: '/projects/:id/config', component: ProjectConfig },
    { path: '/settings', component: SystemSettings },
  ],
})

export default router
