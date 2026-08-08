import { createRouter, createWebHistory } from 'vue-router'

const LocalVideoMerge = () => import('./pages/LocalVideoMerge.vue')
const VoiceGeneration = () => import('./pages/VoiceGeneration.vue')
const AvatarStudio = () => import('./pages/AvatarStudio.vue')
const SettingsLayout = () => import('./pages/settings/SettingsLayout.vue')
const SystemSettings = () => import('./pages/settings/SystemSettings.vue')
const VoiceProfiles = () => import('./pages/settings/VoiceProfiles.vue')

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: '/', redirect: '/voice-generation' },
    { path: '/voice-generation', component: VoiceGeneration, meta: { title: '配音生成' } },
    { path: '/local-video-merge', component: LocalVideoMerge, meta: { title: '本地素材拼接' } },
    { path: '/avatars', component: AvatarStudio, meta: { title: '数字人合成' } },
    { path: '/voices', component: VoiceProfiles, meta: { title: '音色中心' } },
    {
      path: '/settings',
      component: SettingsLayout,
      children: [
        { path: '', redirect: '/settings/general' },
        { path: ':section', component: SystemSettings },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/voice-generation' },
  ],
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title || '系统设置')} · TubeAIFlow`
})

export default router
