<template>
  <div class="app-shell">
    <aside
      class="app-sidebar"
      :class="{ collapsed: sidebarCollapsed && !isMobile, mobile: isMobile, open: mobileMenuOpen }"
    >
      <div class="sidebar-brand">
        <div class="brand-badge">
          <img src="/favicon.svg" alt="logo" />
        </div>
        <div v-show="!sidebarCollapsed || isMobile" class="brand-copy">
          <div class="brand-title">DocExtract</div>
          <div class="brand-subtitle">让模板、文档和抽取结果在同一套工作流中协同运行</div>
        </div>
      </div>

      <div v-show="!sidebarCollapsed || isMobile" class="sidebar-caption">WORKSPACE</div>

      <el-menu
        :default-active="String(activeMenuName)"
        :collapse="sidebarCollapsed && !isMobile"
        class="nav-menu"
        router
      >
        <el-menu-item
          v-for="item in visibleNavItems"
          :key="item.name"
          :index="item.name"
          :route="{ name: item.name }"
          @click="mobileMenuOpen = false"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <template #title>
            <div class="nav-label">
              <span class="nav-title">{{ item.label }}</span>
              <span class="nav-hint">{{ item.description }}</span>
            </div>
          </template>
        </el-menu-item>
      </el-menu>

      <div v-if="!sidebarCollapsed || isMobile" class="sidebar-footer-card">
        <strong>当前会话</strong>
        <p>文档解析、模板维护与抽取任务都汇聚在这一套控制台中。</p>
        <el-tag size="small" effect="plain">{{ authStore.isAdmin ? '管理员视图' : '业务视图' }}</el-tag>
        <el-tag size="small" effect="plain" type="success">实时任务追踪</el-tag>
      </div>

      <div class="sidebar-toggle">
        <el-button :icon="toggleIcon" @click="toggleSidebar">
          {{ isMobile ? '收起导航' : sidebarCollapsed ? '展开导航' : '折叠导航' }}
        </el-button>
      </div>
    </aside>

    <div v-if="isMobile && mobileMenuOpen" class="app-mask" @click="mobileMenuOpen = false" />

    <div class="app-stage">
      <header class="app-topbar">
        <div class="topbar-left">
          <el-button class="menu-trigger" :icon="Menu" circle @click="mobileMenuOpen = true" />

          <div class="topbar-title-block">
            <div class="topbar-title">{{ currentTitle }}</div>
            <div class="topbar-subtitle">{{ currentDescription }}</div>
          </div>
        </div>

        <div class="topbar-right">
          <div class="topbar-pills">
            <span class="topbar-pill">
              <el-icon><Compass /></el-icon>
              {{ breadcrumbLabel }}
            </span>
            <span class="topbar-pill accent">
              <el-icon><Timer /></el-icon>
              {{ authStore.isAdmin ? '管理员模式' : '标准工作区' }}
            </span>
          </div>

          <el-dropdown @command="handleUserCommand">
            <span class="topbar-user">
              <el-avatar :size="34" style="background: linear-gradient(135deg, #1f6f5f, #d1893f); color: #fff;">
                {{ authStore.user?.username?.[0]?.toUpperCase() }}
              </el-avatar>
              <span class="username">{{ authStore.user?.username || '未命名用户' }}</span>
              <span class="user-role">{{ authStore.isAdmin ? '管理员' : '成员' }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="dashboard">返回工作台</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="app-content">
        <div class="app-content-inner">
          <router-view v-slot="{ Component }">
            <transition name="page" mode="out-in">
              <component :is="Component" />
            </transition>
          </router-view>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Menu, Fold, Expand, House, Collection, Document, MagicStick, Setting, Compass, Timer } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const sidebarCollapsed = ref(false)
const isMobile = ref(window.innerWidth <= 992)
const mobileMenuOpen = ref(false)

const navItems = [
  { name: 'Dashboard', label: '工作台', description: '总览核心指标与系统状态', icon: House },
  { name: 'TemplateList', label: '模板管理', description: '维护字段结构与模板版本', icon: Collection },
  { name: 'DocumentList', label: '文档管理', description: '上传、追踪并管理原始文档', icon: Document },
  { name: 'ExtractionList', label: '提取任务', description: '查看任务进度与结果产出', icon: MagicStick },
  { name: 'SystemConfig', label: '系统配置', description: '配置模型连接与运行参数', icon: Setting, adminOnly: true },
]

const pageDescriptions = {
  Dashboard: '把文档、模板与任务的关键变化集中在一个高密度工作台中。',
  TemplateList: '统一管理模板结构、发布状态与字段设计。',
  TemplateCreate: '在结构化表单中定义字段规则，让提取结果更稳定。',
  TemplateEdit: '调整字段配置与提示词，持续迭代提取精度。',
  TemplateDetail: '查看模板信息、字段结构以及关联提取动作。',
  DocumentList: '跟踪文档格式、状态和可下载资源，保持输入源整洁。',
  DocumentUpload: '批量上传并立即进入解析流程，减少人工切换。',
  ExtractionList: '关注任务运行、优先级、完成率与结果状态。',
  ExtractionCreate: '为指定文档和模板快速发起新的抽取任务。',
  ExtractionResult: '集中查看字段结果、置信度与导出动作。',
  SystemConfig: '维护模型接入参数、默认策略和系统限额。',
}

const visibleNavItems = computed(() => navItems.filter((item) => !item.adminOnly || authStore.isAdmin))

const activeMenuName = computed(() => {
  const routeName = String(route.name || '')
  const matchedItem = navItems.find((item) => item.name === routeName)
  if (matchedItem) return routeName
  return route.meta?.parent ? String(route.meta.parent) : 'Dashboard'
})

const currentTitle = computed(() => String(route.meta?.title || 'DocExtract'))
const currentDescription = computed(() => pageDescriptions[String(route.name || '')] || '统一处理智能文档抽取流程。')
const breadcrumbLabel = computed(() => {
  const current = visibleNavItems.value.find((item) => item.name === activeMenuName.value)
  return current ? current.label : '工作区'
})
const toggleIcon = computed(() => (isMobile.value ? Fold : sidebarCollapsed.value ? Expand : Fold))

function handleResize() {
  isMobile.value = window.innerWidth <= 992
  if (!isMobile.value) {
    mobileMenuOpen.value = false
  }
}

function toggleSidebar() {
  if (isMobile.value) {
    mobileMenuOpen.value = false
    return
  }
  sidebarCollapsed.value = !sidebarCollapsed.value
}

function handleUserCommand(cmd) {
  if (cmd === 'dashboard') {
    router.push({ name: 'Dashboard' })
    return
  }

  if (cmd === 'logout') {
    authStore.logout()
    router.push({ name: 'Login' })
  }
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
})
</script>

<style scoped>
.page-enter-active,
.page-leave-active {
  transition: all 0.2s ease;
}

.page-enter-from,
.page-leave-to {
  opacity: 0;
  transform: translateY(10px);
}
</style>
