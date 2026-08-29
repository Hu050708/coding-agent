import { createRouter, createWebHistory } from 'vue-router'

import HomeView from './views/HomeView.vue'
import EvaluationView from './views/EvaluationView.vue'
import WorkbenchView from './views/WorkbenchView.vue'
import WorkspaceView from './views/WorkspaceView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/evaluations', name: 'evaluations', component: EvaluationView },
    { path: '/w/:workspaceId', name: 'workspace', component: WorkspaceView },
    {
      path: '/w/:workspaceId/c/:conversationId',
      name: 'conversation',
      component: WorkbenchView,
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
