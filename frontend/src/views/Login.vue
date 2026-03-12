<template>
  <div class="login-page">
    <div class="login-grid">
      <section class="login-showcase">
        <div class="showcase-brand">
          <div class="showcase-logo">
            <img src="/favicon.svg" alt="logo" class="logo" />
          </div>
          <div>
            <div class="showcase-kicker">INTELLIGENT EXTRACTION CONSOLE</div>
            <h1>DocExtract</h1>
          </div>
        </div>

        <p class="showcase-copy">
          用更现代的工作流管理文档、模板和抽取任务，把零散操作压缩成一条清晰链路。
        </p>

        <div class="showcase-stats">
          <div class="showcase-stat">
            <strong>模板驱动</strong>
            <span>统一字段定义和提示词策略</span>
          </div>
          <div class="showcase-stat">
            <strong>任务可追踪</strong>
            <span>实时查看抽取状态与结果质量</span>
          </div>
          <div class="showcase-stat">
            <strong>配置可运营</strong>
            <span>在同一界面中管理模型接入和系统参数</span>
          </div>
        </div>
      </section>

      <section class="login-panel">
        <div class="panel-header">
          <span class="panel-kicker">SIGN IN</span>
          <h2>进入你的文档工作台</h2>
          <p>继续处理上传、模板维护和抽取结果校验。</p>
        </div>

        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          size="large"
          @submit.prevent="handleLogin"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="form.username"
              placeholder="请输入用户名或邮箱"
              prefix-icon="User"
              autofocus
            />
          </el-form-item>

          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              prefix-icon="Lock"
              show-password
              @keyup.enter="handleLogin"
            />
          </el-form-item>

          <el-button
            type="primary"
            class="login-submit"
            :loading="loading"
            @click="handleLogin"
          >
            登录并进入控制台
          </el-button>
        </el-form>

        <div class="login-footer">
          <span>建议使用桌面浏览器以获得最佳编辑和表格体验。</span>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  await formRef.value?.validate()
  loading.value = true
  try {
    await authStore.login(form.username, form.password)
    const redirect = route.query.redirect || '/dashboard'
    router.push(redirect)
    ElMessage.success('登录成功')
  } catch {
    // 错误已由拦截器处理
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(209, 137, 63, 0.2), transparent 28%),
    radial-gradient(circle at 80% 20%, rgba(31, 111, 95, 0.2), transparent 24%),
    linear-gradient(135deg, #f8f1e7 0%, #efe5d7 45%, #e8e0d2 100%);
}

.login-grid {
  width: min(1120px, 100%);
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  border-radius: 32px;
  overflow: hidden;
  border: 1px solid rgba(31, 111, 95, 0.12);
  box-shadow: 0 28px 80px rgba(62, 53, 39, 0.14);
  background: rgba(255, 252, 247, 0.7);
  backdrop-filter: blur(14px);
}

.login-showcase {
  position: relative;
  padding: 56px;
  background: linear-gradient(160deg, rgba(25, 79, 72, 0.98), rgba(14, 42, 37, 0.94));
  color: #f7efe2;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 28px;
}

.login-showcase::after {
  content: '';
  position: absolute;
  right: -48px;
  top: -48px;
  width: 220px;
  height: 220px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(209, 137, 63, 0.42), transparent 65%);
}

.showcase-brand,
.login-panel {
  position: relative;
  z-index: 1;
}

.showcase-brand {
  display: flex;
  align-items: center;
  gap: 18px;
}

.showcase-logo {
  width: 72px;
  height: 72px;
  display: grid;
  place-items: center;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.12);
}

.logo {
  width: 38px;
  height: 38px;
}

.showcase-kicker,
.panel-kicker {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
}

.showcase-brand h1 {
  margin: 8px 0 0;
  font-size: clamp(34px, 4vw, 54px);
  line-height: 1;
  letter-spacing: -0.04em;
}

.showcase-copy {
  max-width: 520px;
  margin: 0;
  font-size: 17px;
  line-height: 1.9;
  color: rgba(247, 239, 226, 0.82);
}

.showcase-stats {
  display: grid;
  gap: 14px;
}

.showcase-stat {
  padding: 18px 20px;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.showcase-stat strong {
  display: block;
  margin-bottom: 6px;
  font-size: 16px;
}

.showcase-stat span {
  color: rgba(247, 239, 226, 0.72);
  font-size: 13px;
  line-height: 1.7;
}

.login-panel {
  padding: 48px 42px;
  background: linear-gradient(180deg, rgba(255, 252, 247, 0.95), rgba(248, 243, 235, 0.92));
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.panel-header {
  margin-bottom: 28px;
}

.panel-header h2 {
  margin: 10px 0 10px;
  font-size: 32px;
  line-height: 1.1;
  letter-spacing: -0.04em;
  color: #14201b;
}

.panel-header p {
  margin: 0;
  font-size: 14px;
  line-height: 1.8;
  color: #66756d;
}

.login-submit {
  width: 100%;
  margin-top: 8px;
  min-height: 50px;
}

.login-footer {
  margin-top: 18px;
  color: #7a837e;
  font-size: 12px;
}

@media (max-width: 900px) {
  .login-grid {
    grid-template-columns: 1fr;
  }

  .login-showcase,
  .login-panel {
    padding: 32px 24px;
  }
}
</style>
