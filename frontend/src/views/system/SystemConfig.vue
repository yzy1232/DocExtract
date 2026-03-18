<template>
  <div class="system-config page-shell">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">SYSTEM SETTINGS</span>
        <h2 class="page-title">系统配置</h2>
        <p class="page-subtitle">维护模型接入、默认策略与系统运行参数，把底层能力与前台业务使用衔接起来。</p>
      </div>
    </section>

    <el-tabs v-model="activeTab" type="border-card">
      <!-- LLM 配置 -->
      <el-tab-pane label="LLM 模型配置" name="llm">
        <div class="tab-header">
          <el-button type="primary" :icon="Plus" @click="openLLMDialog()">添加LLM配置</el-button>
        </div>

        <el-table :data="llmConfigs" v-loading="llmLoading" stripe>
          <el-table-column prop="name" label="配置名称" min-width="140" />
          <!-- 提供商字段已移除 -->
          <el-table-column prop="model_name" label="模型名称" width="160" />
          <el-table-column prop="base_url" label="API地址" min-width="200" show-overflow-tooltip />
          <el-table-column label="默认" width="70" align="center">
            <template #default="{ row }">
              <el-icon v-if="row.is_default" color="#22c55e"><Check /></el-icon>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '启用' : '禁用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="200" align="center">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click="testLLM(row)">
                连接测试
              </el-button>
              <el-button size="small" text type="primary" @click="openLLMDialog(row)">
                编辑
              </el-button>
              <el-button size="small" text type="danger" @click="deleteLLM(row)">
                删除
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <!-- 系统参数 -->
      <el-tab-pane label="系统参数" name="system">
        <el-form :model="sysConfig" label-width="160px" style="max-width:600px;margin-top:20px">
          <el-form-item label="最大上传大小(MB)">
            <el-input-number v-model="sysConfig.max_upload_mb" :min="1" :max="500" />
          </el-form-item>
          <el-form-item label="每分钟限速请求数">
            <el-input-number v-model="sysConfig.rate_limit_per_minute" :min="10" :max="10000" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveSysConfig" :loading="sysConfigSaving">
              保存配置
            </el-button>
          </el-form-item>
        </el-form>
      </el-tab-pane>

      <!-- 账号权限 -->
      <el-tab-pane label="账号权限" name="accounts">
        <div class="tab-header account-actions">
          <el-input
            v-model="userQuery.keyword"
            placeholder="搜索用户名/邮箱/姓名"
            clearable
            style="width: 260px"
            @keyup.enter="loadUsers"
          />
          <el-button @click="loadUsers">查询</el-button>
          <el-button type="primary" :icon="Plus" @click="openUserDialog()">新增账号</el-button>
        </div>

        <el-table :data="users" v-loading="usersLoading" stripe>
          <el-table-column prop="username" label="用户名" min-width="120" />
          <el-table-column prop="email" label="邮箱" min-width="180" show-overflow-tooltip />
          <el-table-column prop="full_name" label="姓名" min-width="120" />
          <el-table-column label="角色" min-width="180">
            <template #default="{ row }">
              <el-tag
                v-for="role in row.roles"
                :key="role.id"
                size="small"
                style="margin-right: 6px; margin-bottom: 4px"
              >
                {{ role.display_name || role.name }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'active' ? 'success' : 'info'" size="small">
                {{ row.status === 'active' ? '启用' : '停用' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="管理员" width="90" align="center">
            <template #default="{ row }">
              <el-icon v-if="row.is_superuser" color="#22c55e"><Check /></el-icon>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="220" align="center">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click="openUserDialog(row)">编辑</el-button>
              <el-button size="small" text type="danger" @click="deleteUser(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pagination-wrap">
          <el-pagination
            background
            layout="total, prev, pager, next"
            :current-page="userQuery.page"
            :page-size="userQuery.page_size"
            :total="userTotal"
            @current-change="handleUserPageChange"
          />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- LLM 配置对话框 -->
    <el-dialog
      v-model="llmDialogVisible"
      :title="editingLLM ? '编辑LLM配置' : '新增LLM配置'"
      width="600px"
    >
      <el-form :model="llmForm" label-width="110px" :rules="llmRules" ref="llmFormRef">
        <el-form-item label="配置名称" prop="name">
          <el-input v-model="llmForm.name" placeholder="如：生产环境GPT-4o" />
        </el-form-item>
        <!-- 提供商选择已移除，配置仅需 API 地址 和 模型 名称 -->
        <el-form-item label="API 地址" prop="base_url" :rules="[{ required: true, message: '请输入 API 地址', trigger: 'blur' }]">
          <el-input v-model="llmForm.base_url" placeholder="https://api.openai.com/v1" />
        </el-form-item>
        <el-form-item label="API Key" prop="api_key" :rules="[{ required: true, message: '请输入 API Key', trigger: 'blur' }]">
          <el-input v-model="llmForm.api_key" type="password" show-password placeholder="sk-..." />
        </el-form-item>
        <el-form-item label="模型名称" prop="model_name">
          <el-input v-model="llmForm.model_name" placeholder="gpt-4o" />
        </el-form-item>
        <el-form-item label="设为默认">
          <el-switch v-model="llmForm.is_default" />
        </el-form-item>
        <el-form-item label="启用">
          <el-switch v-model="llmForm.is_active" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="llmDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveLLM" :loading="llmSaving">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="userDialogVisible"
      :title="editingUser ? '编辑账号' : '新增账号'"
      width="640px"
    >
      <el-form :model="userForm" :rules="userRules" ref="userFormRef" label-width="110px">
        <el-form-item label="用户名" prop="username">
          <el-input v-model="userForm.username" :disabled="!!editingUser" placeholder="如：alice" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="userForm.email" placeholder="name@example.com" />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input v-model="userForm.full_name" placeholder="可选" />
        </el-form-item>
        <el-form-item :label="editingUser ? '重置密码' : '密码'" prop="password">
          <el-input
            v-model="userForm.password"
            type="password"
            show-password
            :placeholder="editingUser ? '留空则不修改' : '至少8位，含大小写和数字'"
          />
        </el-form-item>
        <el-form-item label="超级管理员">
          <el-switch v-model="userForm.is_superuser" />
        </el-form-item>
        <el-form-item label="账号状态">
          <el-radio-group v-model="userForm.status">
            <el-radio-button label="active">启用</el-radio-button>
            <el-radio-button label="inactive">停用</el-radio-button>
            <el-radio-button label="locked">锁定</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="角色分配">
          <el-select v-model="userForm.role_ids" multiple collapse-tags placeholder="选择角色" style="width: 100%">
            <el-option
              v-for="role in roles"
              :key="role.id"
              :label="role.display_name || role.name"
              :value="role.id"
            />
          </el-select>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="userDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="userSaving" @click="saveUser">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Check } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { systemApi } from '@/api/index'

const authStore = useAuthStore()
const activeTab = ref('llm')
const llmLoading = ref(false)
const llmConfigs = ref([])
const llmDialogVisible = ref(false)
const llmSaving = ref(false)
const llmFormRef = ref(null)
const editingLLM = ref(null)
const sysConfigSaving = ref(false)

const usersLoading = ref(false)
const users = ref([])
const userTotal = ref(0)
const roles = ref([])
const userDialogVisible = ref(false)
const userFormRef = ref(null)
const userSaving = ref(false)
const editingUser = ref(null)

const userQuery = reactive({
  page: 1,
  page_size: 10,
  keyword: '',
})

const userForm = reactive({
  username: '',
  email: '',
  full_name: '',
  password: '',
  is_superuser: false,
  status: 'active',
  role_ids: [],
})

const userRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    {
      pattern: /^[a-zA-Z0-9_-]+$/,
      message: '用户名只能包含字母、数字、下划线和连字符',
      trigger: 'blur',
    },
  ],
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }],
  password: [
    {
      validator: (_, value, callback) => {
        if (editingUser.value && !value) {
          callback()
          return
        }
        if (!value) {
          callback(new Error('请输入密码'))
          return
        }
        if (value.length < 8) {
          callback(new Error('密码至少8位'))
          return
        }
        if (!/[A-Z]/.test(value)) {
          callback(new Error('密码必须包含至少一个大写字母'))
          return
        }
        if (!/[a-z]/.test(value)) {
          callback(new Error('密码必须包含至少一个小写字母'))
          return
        }
        if (!/\d/.test(value)) {
          callback(new Error('密码必须包含至少一个数字'))
          return
        }
        callback()
      },
      trigger: 'blur',
    },
  ],
}

// provider 相关常量已移除，配置仅包含 API 地址、API Key 与模型名称

const llmForm = reactive({
  name: '', base_url: 'https://api.openai.com/v1',
  api_key: '', model_name: 'gpt-4o', is_default: false, is_active: true,
})

const llmRules = {
  name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
  model_name: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
}

const sysConfig = reactive({
  max_upload_mb: 100,
  rate_limit_per_minute: 60,
  default_llm_config_id: '',
})

// provider 逻辑已移除

async function loadLLMConfigs() {
  llmLoading.value = true
  try {
    const res = await systemApi.listLLMConfigs()
    llmConfigs.value = (res.data || []).map((item) => ({
      ...item,
      // 兼容后端不同字段命名，确保编辑弹窗可回填 API Key
      api_key: item.api_key ?? item.api_key_encrypted ?? '',
    }))
  } catch {
    ElMessage.error('加载LLM配置失败')
  } finally {
    llmLoading.value = false
  }
}

function openLLMDialog(row = null) {
  editingLLM.value = row
  if (row) {
    Object.assign(llmForm, {
      ...row,
      api_key: row.api_key ?? row.api_key_encrypted ?? '',
    })
  } else {
    Object.assign(llmForm, {
      name: '', base_url: 'https://api.openai.com/v1',
      api_key: '', model_name: 'gpt-4o', is_default: false, is_active: true,
    })
  }
  llmDialogVisible.value = true
}

async function saveLLM() {
  await llmFormRef.value.validate()
  llmSaving.value = true
  try {
    const payload = { ...llmForm }
    if (editingLLM.value) {
      await systemApi.updateLLMConfig(editingLLM.value.id, payload)
      ElMessage.success('更新成功')
    } else {
      await systemApi.createLLMConfig(payload)
      ElMessage.success('创建成功')
    }
    llmDialogVisible.value = false
    loadLLMConfigs()
  } catch {
    ElMessage.error('保存失败，请检查输入')
  } finally {
    llmSaving.value = false
  }
}

async function testLLM(row) {
  const loading = ElMessage({
    message: `正在测试连接「${row.name}」...`,
    type: 'info',
    duration: 0,
  })
  try {
    const res = await systemApi.testLLMConfig(row.id)
    loading.close()
    const latency = res.data?.latency_ms
    if (res.data?.success) {
      ElMessage.success(`连接成功，延迟 ${latency} ms`)
    } else {
      const err = res.data?.error_message
      ElMessage.error(err ? `连接失败: ${err}` : '连接失败，请检查 API Key 和地址')
    }
    loadLLMConfigs()
  } catch {
    loading.close()
    ElMessage.error('连接测试失败')
  }
}

async function deleteLLM(row) {
  await ElMessageBox.confirm(`确认删除LLM配置「${row.name}」？`, '删除确认', { type: 'warning' })
  try {
    await systemApi.deleteLLMConfig(row.id)
    ElMessage.success('已删除')
    loadLLMConfigs()
  } catch {
    ElMessage.error('删除失败')
  }
}

async function saveSysConfig() {
  sysConfigSaving.value = true
  try {
    // 尝试调用后端保存（需要管理员权限），若失败则回退到 localStorage
    try {
      await systemApi.putSystemConfig('default_llm_config_id', { value: sysConfig.default_llm_config_id })
      ElMessage.success('系统配置已保存（后端）')
    } catch (e) {
      localStorage.setItem('sys.default_llm_config_id', sysConfig.default_llm_config_id)
      ElMessage.success('系统配置已保存（本地）')
    }
  } finally {
    sysConfigSaving.value = false
  }
}

async function loadSysConfigFromStorage() {
  // 优先从后端读取系统配置（需要超级管理员权限）
  try {
    const res = await systemApi.getSystemConfig('default_llm_config_id')
    if (res?.data?.value) {
      sysConfig.default_llm_config_id = res.data.value
      try { localStorage.setItem('sys.default_llm_config_id', res.data.value) } catch {}
      return
    }
  } catch (e) {
    // 后端可能未配置或权限限制，回退到 localStorage
  }

  try {
    const v = localStorage.getItem('sys.default_llm_config_id')
    if (v) {
      sysConfig.default_llm_config_id = v
    }
  } catch (e) {
    // ignore
  }
}

async function loadRoles() {
  try {
    const res = await systemApi.listRoles()
    roles.value = res.data || []
  } catch {
    roles.value = []
    ElMessage.error('加载角色列表失败')
  }
}

async function loadUsers() {
  usersLoading.value = true
  try {
    const res = await systemApi.listUsers(userQuery)
    users.value = res.data?.items || []
    userTotal.value = res.data?.total || 0
  } catch {
    ElMessage.error('加载账号列表失败')
  } finally {
    usersLoading.value = false
  }
}

function handleUserPageChange(page) {
  userQuery.page = page
  loadUsers()
}

function openUserDialog(row = null) {
  editingUser.value = row
  if (row) {
    Object.assign(userForm, {
      username: row.username,
      email: row.email,
      full_name: row.full_name || '',
      password: '',
      is_superuser: row.is_superuser,
      status: row.status,
      role_ids: (row.roles || []).map((r) => r.id),
    })
  } else {
    Object.assign(userForm, {
      username: '',
      email: '',
      full_name: '',
      password: '',
      is_superuser: false,
      status: 'active',
      role_ids: [],
    })
  }
  userDialogVisible.value = true
}

async function saveUser() {
  await userFormRef.value.validate()
  userSaving.value = true
  try {
    const payload = {
      email: userForm.email,
      full_name: userForm.full_name || null,
      is_superuser: userForm.is_superuser,
      status: userForm.status,
      role_ids: userForm.role_ids,
    }

    if (editingUser.value) {
      if (userForm.password) {
        payload.password = userForm.password
      }
      await systemApi.updateUser(editingUser.value.id, payload)
      ElMessage.success('账号更新成功')
      if (editingUser.value.id === authStore.user?.id) {
        await authStore.fetchMe()
      }
    } else {
      payload.username = userForm.username
      payload.password = userForm.password
      await systemApi.createUser(payload)
      ElMessage.success('账号创建成功')
    }
    userDialogVisible.value = false
    loadUsers()
  } catch (error) {
    const errorMsg = error?.response?.data?.detail || error?.message || '保存失败，请检查输入'
    ElMessage.error(errorMsg)
  } finally {
    userSaving.value = false
  }
}

async function deleteUser(row) {
  await ElMessageBox.confirm(`确认删除账号「${row.username}」？`, '删除确认', { type: 'warning' })
  try {
    await systemApi.deleteUser(row.id)
    ElMessage.success('删除成功')
    loadUsers()
  } catch {
    ElMessage.error('删除失败')
  }
}

onMounted(() => {
  loadLLMConfigs()
  loadSysConfigFromStorage()
  loadRoles()
  loadUsers()
})
</script>

<style scoped>
.tab-header {
  margin-bottom: 16px;
}

.account-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
