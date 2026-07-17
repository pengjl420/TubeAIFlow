import { createRouter, createWebHistory } from 'vue-router'

import BatchCreate from './pages/batches/BatchCreate.vue'
import BatchDetail from './pages/batches/BatchDetail.vue'
import BatchList from './pages/batches/BatchList.vue'
import ProjectConfig from './pages/projects/ProjectConfig.vue'
import ProjectCreate from './pages/projects/ProjectCreate.vue'
import ProjectShell from './pages/projects/ProjectShell.vue'
import ProjectStoryboardWorkspace from './pages/projects/ProjectStoryboardWorkspace.vue'
import StoryboardLab from './pages/projects/ProjectStoryboard.vue'
import ProjectList from './pages/projects/ProjectList.vue'
import SystemSettings from './pages/settings/SystemSettings.vue'
import VoiceProfiles from './pages/settings/VoiceProfiles.vue'

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior: () => ({ top: 0 }),
  routes: [
    { path: '/', component: ProjectList },
    { path: '/batches', component: BatchList },
    { path: '/batches/new', component: BatchCreate },
    { path: '/batches/:id', component: BatchDetail },
    { path: '/projects/new', component: ProjectCreate },
    { path: '/projects/:id', component: ProjectShell },
    { path: '/projects/:id/storyboard', component: ProjectStoryboardWorkspace },
    { path: '/storyboard-lab', component: StoryboardLab },
    { path: '/projects/:id/config', component: ProjectConfig },
    { path: '/voices', component: VoiceProfiles },
    { path: '/settings', component: SystemSettings },
  ],
})

router.afterEach((to) => {
  const section = to.path.startsWith('/voices')
    ? '参考音频'
    : to.path.startsWith('/batches')
      ? '批量生产'
      : to.path.startsWith('/storyboard-lab')
        ? '分镜测试台'
      : to.path.startsWith('/settings')
        ? '系统设置'
        : to.path.startsWith('/projects/new')
          ? '创建项目'
          : to.path.startsWith('/projects/')
            ? '项目工作台'
            : '项目总览'
  document.title = `${section} · TubeAIFlow`
})

export default router
