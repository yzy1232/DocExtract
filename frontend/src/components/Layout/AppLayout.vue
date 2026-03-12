<template>
  <el-container class="app-layout">
    <!-- 左侧导航栏 -->
    <el-aside :width="sidebarCollapsed ? '64px' : '220px'" class="sidebar">
      <div class="sidebar-logo">
        <img src="/favicon.svg" alt="logo" class="logo-icon" />
        <span v-show="!sidebarCollapsed" class="logo-text">DocExtract</span>
      </div>

      <el-menu
        :default-active="route.name"
        :collapse="sidebarCollapsed"
        background-color="#1e293b"
        text-color="#94a3b8"
        active-text-color="#60a5fa"
        router
      >
        <el-menu-item index="Dashboard" :route="{ name: 'Dashboard' }">
          <el-icon><House /></el-icon>
          <template #title>工作台</template>
        </el-menu-item>

        <el-menu-item index="TemplateList" :route="{ name: 'TemplateList' }">
          <el-icon><Collection /></el-icon>
          <template #title>模板管理</template>
        </el-menu-item>

        <el-menu-item index="DocumentList" :route="{ name: 'DocumentList' }">
          <el-icon><Document /></el-icon>
          <template #title>文档管理</template>
        </el-menu-item>

        <el-menu-item index="ExtractionList" :route="{ name: 'ExtractionList' }">
          <el-icon><MagicStick /></el-icon>
          <template #title>提取任务</template>
        </el-menu-item>

        <el-menu-item
          v-if="authStore.isAdmin"
          index="SystemConfig"
          :route="{ name: 'SystemConfig' }"
        >
          <el-icon><Setting /></el-icon>
          <template #title>系统配置</template>
        </el-menu-item>
      </el-menu>

      <div class="sidebar-footer">
        <el-button
          :icon="sidebarCollapsed ? 'Expand' : 'Fold'"
          text
          style="color: #94a3b8; width: 100%"
          @click="sidebarCollapsed = !sidebarCollapsed"
        />
      </div>
    </el-aside>

    <!-- 主内容区 -->
    <el-container>
      <!-- 顶部 Header -->
      <el-header class="app-header">
        <div class="breadcrumb-area">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>首页</el-breadcrumb-item>
            <el-breadcrumb-item>{{ route.meta?.title }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>

        <div class="header-right">
          <el-dropdown @command="handleUserCommand">
            <span class="user-info">
              <el-avatar :size="32" style="background:#60a5fa">
                {{ authStore.user?.username?.[0]?.toUpperCase() }}
              </el-avatar>
              <span class="username">{{ authStore.user?.username }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人信息</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <!-- 页面内容 -->
      <el-main class="app-main">
        <router-view v-slot="{ Component }">
          <transition name="fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const sidebarCollapsed = ref(false)

function handleUserCommand(cmd) {
  if (cmd === 'logout') {
    authStore.logout()
    router.push({ name: 'Login' })
  }
}
</script>

<style scoped>
.app-layout {
  height: 100vh;
  overflow: hidden;
}

.sidebar {
  background: #1e293b;
  transition: width 0.3s;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.sidebar-logo {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 20px;
  border-bottom: 1px solid #334155;
  gap: 10px;
  overflow: hidden;
}

.logo-icon {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
}

.logo-text {
  color: #f1f5f9;
  font-size: 18px;
  font-weight: 700;
  white-space: nowrap;
}

.sidebar-footer {
  margin-top: auto;
  padding: 8px;
  border-top: 1px solid #334155;
}

.app-header {
  background: white;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: #475569;
}

.username {
  font-size: 14px;
  font-weight: 500;
}

.app-main {
  background: #f8fafc;
  overflow-y: auto;
  padding: 24px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
