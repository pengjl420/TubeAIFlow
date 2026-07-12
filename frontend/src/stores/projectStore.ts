import { defineStore } from 'pinia'

import type { Project } from '../types/project'

export const useProjectStore = defineStore('projects', {
  state: () => ({
    currentProject: null as Project | null,
  }),
  actions: {
    setCurrent(project: Project) {
      this.currentProject = project
    },
  },
})
