import { createRouter, createWebHistory } from 'vue-router'

const BatchCreate = () => import('./pages/batches/BatchCreate.vue')
const BatchDetail = () => import('./pages/batches/BatchDetail.vue')
const BatchList = () => import('./pages/batches/BatchList.vue')
const Dashboard = () => import('./pages/Dashboard.vue')
const LocalVideoMerge = () => import('./pages/LocalVideoMerge.vue')
const AvatarStudio = () => import('./pages/AvatarStudio.vue')
const ProjectCreate = () => import('./pages/projects/ProjectCreate.vue')
const ProjectDelivery = () => import('./pages/projects/ProjectDelivery.vue')
const ProjectList = () => import('./pages/projects/ProjectList.vue')
const ProjectOverview = () => import('./pages/projects/ProjectOverview.vue')
const ProjectRender = () => import('./pages/projects/ProjectRender.vue')
const ProjectShell = () => import('./pages/projects/ProjectShell.vue')
const ProjectWorkspace = () => import('./pages/projects/ProjectWorkspace.vue')
const SettingsLayout = () => import('./pages/settings/SettingsLayout.vue')
const SystemSettings = () => import('./pages/settings/SystemSettings.vue')
const VoiceProfiles = () => import('./pages/settings/VoiceProfiles.vue')
const TaskCenter = () => import('./pages/TaskCenter.vue')

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
        { path: 'subtitles', redirect: (to) => `/projects/${String(to.params.id)}/narration` },
        { path: 'media', redirect: (to) => `/projects/${String(to.params.id)}/render` },
        { path: 'render', component: ProjectRender },
        { path: 'delivery', component: ProjectDelivery },
        { path: 'settings', redirect: (to) => `/projects/${String(to.params.id)}/overview` },
        { path: 'config', redirect: (to) => `/projects/${String(to.params.id)}/overview` },
      ],
    },
    { path: '/batches', component: BatchList },
    { path: '/batches/new', component: BatchCreate },
    { path: '/batches/:id', component: BatchDetail },
    { path: '/local-video-merge', component: LocalVideoMerge, meta: { title: '本地素材拼接' } },
    { path: '/avatars', component: AvatarStudio, meta: { title: '数字人合成' } },
    { path: '/tasks', component: TaskCenter },
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
      : to.path.startsWith('/local-video-merge') ? '本地素材拼接'
        : to.path.startsWith('/avatars') ? '数字人合成'
        : to.path.startsWith('/tasks') ? '任务中心'
          : to.path.startsWith('/voices') ? '音色中心' : '系统设置')
  document.title = `${section} · TubeAIFlow`
})

export default router
