import { createRouter, createWebHistory } from 'vue-router'

import AssetLibrary from './pages/assets/AssetLibrary.vue'
import AssetSection from './pages/assets/AssetSection.vue'
import BatchCreate from './pages/batches/BatchCreate.vue'
import BatchDetail from './pages/batches/BatchDetail.vue'
import BatchList from './pages/batches/BatchList.vue'
import Dashboard from './pages/Dashboard.vue'
import ProjectConfig from './pages/projects/ProjectConfig.vue'
import ProjectCreate from './pages/projects/ProjectCreate.vue'
import ProjectDelivery from './pages/projects/ProjectDelivery.vue'
import ProjectList from './pages/projects/ProjectList.vue'
import ProjectMedia from './pages/projects/ProjectMedia.vue'
import ProjectOverview from './pages/projects/ProjectOverview.vue'
import ProjectRender from './pages/projects/ProjectRender.vue'
import ProjectShell from './pages/projects/ProjectShell.vue'
import ProjectStoryboardWorkspace from './pages/projects/ProjectStoryboardWorkspace.vue'
import ProjectSubtitles from './pages/projects/ProjectSubtitles.vue'
import ProjectWorkspace from './pages/projects/ProjectWorkspace.vue'
import SettingsLayout from './pages/settings/SettingsLayout.vue'
import SystemSettings from './pages/settings/SystemSettings.vue'
import VoiceProfiles from './pages/settings/VoiceProfiles.vue'
import TaskCenter from './pages/TaskCenter.vue'

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: '/', redirect: '/dashboard' },
    { path: '/dashboard', component: Dashboard },
    { path: '/projects', component: ProjectList },
    { path: '/projects/new', component: ProjectCreate },
    {
      path: '/projects/:id',
      component: ProjectWorkspace,
      children: [
        { path: '', redirect: (to) => `/projects/${String(to.params.id)}/overview` },
        { path: 'overview', component: ProjectOverview },
        { path: 'narration', component: ProjectShell },
        { path: 'subtitles', component: ProjectSubtitles },
        { path: 'storyboard', component: ProjectStoryboardWorkspace },
        { path: 'media-review', component: ProjectMedia },
        { path: 'media', redirect: (to) => `/projects/${String(to.params.id)}/media-review` },
        { path: 'render', component: ProjectRender },
        { path: 'delivery', component: ProjectDelivery },
        { path: 'settings', component: ProjectConfig },
        { path: 'config', redirect: (to) => `/projects/${String(to.params.id)}/settings` },
      ],
    },
    { path: '/batches', component: BatchList },
    { path: '/batches/new', component: BatchCreate },
    { path: '/batches/:id', component: BatchDetail },
    { path: '/tasks', component: TaskCenter },
    { path: '/assets', component: AssetLibrary },
    { path: '/assets/:section(import|indexing|storage)', component: AssetSection },
    { path: '/voices', component: VoiceProfiles },
    {
      path: '/settings',
      component: SettingsLayout,
      children: [
        { path: '', redirect: '/settings/general' },
        { path: ':section', component: SystemSettings },
      ],
    },
  ],
})

router.afterEach((to) => {
  const title = String(to.meta.title || '')
  const section = title || (to.path.startsWith('/dashboard') ? '工作台'
    : to.path.startsWith('/projects') ? '项目'
      : to.path.startsWith('/batches') ? '批量生产'
        : to.path.startsWith('/tasks') ? '任务中心'
          : to.path.startsWith('/assets') ? '素材中心'
            : to.path.startsWith('/voices') ? '音色中心' : '系统设置')
  document.title = `${section} · TubeAIFlow`
})

export default router
