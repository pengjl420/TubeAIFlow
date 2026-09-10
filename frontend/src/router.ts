import { createRouter, createWebHistory } from 'vue-router'

const LocalVideoMerge = () => import('./pages/LocalVideoMerge.vue')
const VoiceGeneration = () => import('./pages/VoiceGeneration.vue')
const AvatarStudio = () => import('./pages/AvatarStudio.vue')
const SettingsLayout = () => import('./pages/settings/SettingsLayout.vue')
const SystemSettings = () => import('./pages/settings/SystemSettings.vue')
const VoiceProfiles = () => import('./pages/settings/VoiceProfiles.vue')
const ProjectList = () => import('./pages/projects/ProjectList.vue')
const ProjectWorkspace = () => import('./pages/projects/ProjectWorkspace.vue')
const BatchProduction = () => import('./pages/projects/BatchProduction.vue')

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: '/', redirect: '/projects' },
    { path: '/projects', component: ProjectList, meta: { title: '项目' } },
    { path: '/projects/:projectId', component: ProjectWorkspace, meta: { title: '项目工作区' } },
    { path: '/batches', component: BatchProduction, meta: { title: '批量生产' } },
    { path: '/voice-generation', component: VoiceGeneration, meta: { title: '配音生成' } },
    { path: '/local-video-merge', component: LocalVideoMerge, meta: { title: '本地素材拼接' } },
    { path: '/avatars', component: AvatarStudio, meta: { title: '数字人合成' } },
    { path: '/voices', component: VoiceProfiles, meta: { title: '音色中心' } },
    {
      path: '/settings',
      component: SettingsLayout,
      meta: { title: '系统设置' },
      children: [
        { path: '', redirect: '/settings/general' },
        { path: ':section', component: SystemSettings },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/projects' },
  ],
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title || '系统设置')} · TubeAiFolw`
})

export default router
