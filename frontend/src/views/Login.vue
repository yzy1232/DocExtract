<template>
  <div class="login-page">
    <div class="login-grid">
      <section class="login-showcase">
        <div class="showcase-brand">
          <div class="showcase-logo trigger-logo" @click="unlockEmergencyEntry">
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

        <el-alert
          v-if="unavailableReason"
          class="unavailable-alert"
          type="error"
          show-icon
          :closable="false"
          :title="unavailableReason"
        />

        <el-form
          v-if="!isEmergencyMode"
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

        <div v-else class="emergency-login-placeholder">
          当前处于应急修复模式，已隐藏账号和密码输入。请先执行应急修复，修复完成后会自动返回正常登录界面。
        </div>

        <div v-if="emergencyVisible" class="emergency-panel">
          <div class="emergency-head">
            <strong>应急容灾入口</strong>
          </div>

          <p class="emergency-desc">
            仅在数据库或 Redis 异常导致无法登录时使用。
          </p>

          <div class="emergency-notice">
            <p>
              由于某些原因（如黑客攻击、硬盘损坏、误操作、系统升级异常等），系统需要执行应急修复。
            </p>
            <p>
              修复过程中可能出现部分数据丢失或回滚，建议优先查看系统日志、容器日志和数据库告警，进一步确认根因后再进行业务恢复。
            </p>
          </div>

          <div class="emergency-actions">
            <el-button
              type="danger"
              :loading="repairingEmergency"
              :disabled="!canEmergencyRepair"
              @click="runEmergencyRepair"
            >
              执行修复
            </el-button>
          </div>
        </div>

        <div class="login-footer">
          <span>建议使用桌面浏览器以获得最佳编辑和表格体验。</span>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onBeforeUnmount, watch, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { systemApi } from '@/api'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref()
const loading = ref(false)
const form = reactive({ username: '', password: '' })
const emergencyVisible = ref(false)
const repairingEmergency = ref(false)
const unavailableReason = ref('')
const isEmergencyMode = computed(() => Boolean(unavailableReason.value))
const canEmergencyRepair = computed(() => Boolean(unavailableReason.value))

let logoTapCount = 0
let logoTapTimer = null

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

function toUnavailableReasonText(unavailableValue) {
  const raw = String(unavailableValue || '').toLowerCase()
  if (!raw) {
    return ''
  }

  const parts = raw
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)

  const hasDb = parts.includes('database')
  const hasRedis = parts.includes('redis') || parts.includes('cache')

  if (hasDb && hasRedis) {
    return '检测到数据库和Redis不可用，已自动跳转到登录页'
  }
  if (hasDb) {
    return '检测到数据库不可用，已自动跳转到登录页'
  }
  if (hasRedis) {
    return '检测到Redis不可用，已自动跳转到登录页'
  }
  return ''
}

function applyUnavailableReason(unavailableValue) {
  const message = toUnavailableReasonText(unavailableValue)
  unavailableReason.value = message

  if (message) {
    emergencyVisible.value = true
    ElMessage.error(message)
  }
}

watch(
  () => route.query.unavailable,
  (value) => {
    applyUnavailableReason(value)
  },
  { immediate: true }
)

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

function unlockEmergencyEntry() {
  if (emergencyVisible.value) {
    return
  }

  logoTapCount += 1
  if (logoTapTimer) {
    clearTimeout(logoTapTimer)
  }

  logoTapTimer = setTimeout(() => {
    logoTapCount = 0
  }, 1800)

  if (logoTapCount >= 6) {
    emergencyVisible.value = true
    logoTapCount = 0
    ElMessage.warning('已开启应急容灾入口')
  }
}

async function runEmergencyRepair() {
  if (!canEmergencyRepair.value) {
    ElMessage.warning('当前服务未检测到异常，无法执行应急修复')
    return
  }

  repairingEmergency.value = true
  try {
    const payload = {
      dry_run: false,
      confirm: 'REBUILD',
    }

    const res = await systemApi.publicDisasterRepair(payload)
    if (res.data?.success) {
      unavailableReason.value = ''
      emergencyVisible.value = false

      const redirect = route.query.redirect
      const query = redirect ? { redirect } : undefined
      await router.replace({ name: 'Login', query })

      ElMessage.success('修复流程执行完成，已返回正常登录界面')
    } else {
      ElMessage.warning('修复流程已执行，但系统仍有风险，请检查结果')
    }
  } catch (error) {
    const msg = error?.response?.data?.message || error?.message || '应急修复失败'
    ElMessage.error(msg)
  } finally {
    repairingEmergency.value = false
  }
}

onBeforeUnmount(() => {
  if (logoTapTimer) {
    clearTimeout(logoTapTimer)
    logoTapTimer = null
  }
})
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

.trigger-logo {
  cursor: pointer;
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

.emergency-login-placeholder {
  margin-top: 6px;
  padding: 12px;
  border-radius: 10px;
  background: rgba(255, 245, 235, 0.85);
  border: 1px solid rgba(184, 106, 59, 0.28);
  color: #7a4a2e;
  font-size: 13px;
  line-height: 1.7;
}

.login-footer {
  margin-top: 18px;
  color: #7a837e;
  font-size: 12px;
}

.unavailable-alert {
  margin-bottom: 14px;
}

.emergency-panel {
  margin-top: 16px;
  border: 1px dashed rgba(184, 106, 59, 0.5);
  border-radius: 12px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: rgba(255, 247, 237, 0.7);
}

.emergency-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.emergency-desc {
  margin: 0;
  font-size: 12px;
  color: #7a6151;
}

.emergency-notice {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  border-radius: 10px;
  background: rgba(255, 239, 224, 0.8);
  border: 1px solid rgba(184, 106, 59, 0.22);
}

.emergency-notice p {
  margin: 0;
  font-size: 12px;
  line-height: 1.7;
  color: #7a4a2e;
}

.emergency-actions {
  display: flex;
  gap: 8px;
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
