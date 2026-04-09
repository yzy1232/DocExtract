import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/',
    component: () => import('@/components/Layout/AppLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        redirect: '/dashboard',
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/Dashboard.vue'),
        meta: { title: '工作台', icon: 'House' },
      },
      // 模板管理
      {
        path: 'templates',
        name: 'TemplateList',
        component: () => import('@/views/template/TemplateList.vue'),
        meta: { title: '模板管理', icon: 'Collection' },
      },
      {
        path: 'templates/create',
        name: 'TemplateCreate',
        component: () => import('@/views/template/TemplateCreate.vue'),
        meta: { title: '创建模板', parent: 'TemplateList' },
      },
      {
        path: 'templates/:id/edit',
        name: 'TemplateEdit',
        component: () => import('@/views/template/TemplateCreate.vue'),
        meta: { title: '编辑模板', parent: 'TemplateList' },
      },
      {
        path: 'templates/:id',
        name: 'TemplateDetail',
        component: () => import('@/views/template/TemplateDetail.vue'),
        meta: { title: '模板详情', parent: 'TemplateList' },
      },
      // 文档管理
      {
        path: 'documents',
        name: 'DocumentList',
        component: () => import('@/views/document/DocumentList.vue'),
        meta: { title: '文档管理', icon: 'Document' },
      },
      {
        path: 'documents/upload',
        name: 'DocumentUpload',
        component: () => import('@/views/document/DocumentUpload.vue'),
        meta: { title: '上传文档', parent: 'DocumentList' },
      },
      {
        path: 'documents/:id/preview',
        name: 'DocumentPreview',
        component: () => import('@/views/document/DocumentPreview.vue'),
        meta: { title: '在线预览', parent: 'DocumentList' },
      },
      // 提取任务
      {
        path: 'extractions',
        name: 'ExtractionList',
        component: () => import('@/views/extraction/ExtractionList.vue'),
        meta: { title: '提取任务', icon: 'MagicStick' },
      },
      {
        path: 'extractions/create',
        name: 'ExtractionCreate',
        component: () => import('@/views/extraction/ExtractionCreate.vue'),
        meta: { title: '创建提取任务', parent: 'ExtractionList' },
      },
      {
        path: 'extractions/:id',
        name: 'ExtractionResult',
        alias: 'extractions/:id/result',
        component: () => import('@/views/extraction/ExtractionResult.vue'),
        meta: { title: '提取结果', parent: 'ExtractionList' },
      },
      {
        path: 'guide',
        name: 'UsageGuide',
        component: () => import('@/views/guide/UsageGuide.vue'),
        meta: { title: '使用文档', icon: 'Reading' },
      },
      // 系统管理
      {
        path: 'system',
        name: 'SystemConfig',
        component: () => import('@/views/system/SystemConfig.vue'),
        meta: { title: '系统配置', icon: 'Setting', adminOnly: true },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 全局路由守卫
router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  // 设置页面标题
  document.title = to.meta.title ? `${to.meta.title} - DocExtract` : 'DocExtract'

  if (to.meta.public) {
    next()
    return
  }

  if (!authStore.isLoggedIn) {
    next({ name: 'Login', query: { redirect: to.fullPath } })
    return
  }

  // 检查管理员权限
  if (to.meta.adminOnly && !authStore.isAdmin) {
    next({ name: 'Dashboard' })
    return
  }

  next()
})

export default router
