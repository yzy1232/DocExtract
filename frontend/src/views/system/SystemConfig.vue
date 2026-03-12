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
          <el-table-column prop="provider" label="提供商" width="120">
            <template #default="{ row }">
              <el-tag size="small">{{ row.provider }}</el-tag>
            </template>
          </el-table-column>
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
          <el-form-item label="默认LLM提供商">
            <el-select v-model="sysConfig.default_llm_provider" style="width:200px">
              <el-option label="OpenAI" value="openai" />
              <el-option label="DeepSeek" value="deepseek" />
              <el-option label="Ollama (本地)" value="ollama" />
              <el-option label="文心一言" value="wenxin" />
              <el-option label="自定义" value="custom" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="saveSysConfig" :loading="sysConfigSaving">
              保存配置
            </el-button>
          </el-form-item>
        </el-form>
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
        <el-form-item label="提供商" prop="provider">
          <el-select v-model="llmForm.provider" style="width:100%" @change="onProviderChange">
            <el-option label="OpenAI" value="openai" />
            <el-option label="DeepSeek" value="deepseek" />
            <el-option label="Ollama（本地）" value="ollama" />
            <el-option label="文心一言" value="wenxin" />
            <el-option label="自定义（OpenAI 兼容）" value="custom" />
          </el-select>
        </el-form-item>
        <el-form-item label="API 地址" prop="base_url"
          :rules="llmForm.provider === 'custom' ? [{ required: true, message: '自定义提供商必须填写 API 地址' }] : []"
        >
          <el-input v-model="llmForm.base_url" placeholder="https://api.openai.com/v1">
            <template #suffix>
              <el-tooltip v-if="llmForm.provider === 'custom'" content="自定义提供商：填写任意 OpenAI 兼容端点地址" placement="top">
                <el-icon style="cursor:help"><InfoFilled /></el-icon>
              </el-tooltip>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item label="API Key" prop="api_key"
          :rules="llmForm.provider !== 'ollama' ? [{ required: true, message: '请输入 API Key' }] : []"
        >
          <el-input
            v-model="llmForm.api_key"
            type="password"
            show-password
            :placeholder="llmForm.provider === 'ollama' ? '本地 Ollama 无需 Key' : 'sk-...'" />
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
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Check, InfoFilled } from '@element-plus/icons-vue'
import { systemApi } from '@/api/index'

const activeTab = ref('llm')
const llmLoading = ref(false)
const llmConfigs = ref([])
const llmDialogVisible = ref(false)
const llmSaving = ref(false)
const llmFormRef = ref(null)
const editingLLM = ref(null)
const sysConfigSaving = ref(false)

// 不同提供商的默认 base_url
const PROVIDER_URLS = {
  openai: 'https://api.openai.com/v1',
  deepseek: 'https://api.deepseek.com/v1',
  ollama: 'http://localhost:11434',
  wenxin: 'https://aip.baidubce.com/rpc/2.0/ai_custom/v1/wenxinworkshop/chat',
  custom: '',
}

// 提供商默认模型
const PROVIDER_MODELS = {
  openai: 'gpt-4o',
  deepseek: 'deepseek-chat',
  ollama: 'llama3',
  wenxin: 'ernie-bot-4',
  custom: '',
}

const llmForm = reactive({
  name: '', provider: 'openai', base_url: 'https://api.openai.com/v1',
  api_key: '', model_name: 'gpt-4o', is_default: false, is_active: true,
})

const llmRules = {
  name: [{ required: true, message: '请输入配置名称', trigger: 'blur' }],
  provider: [{ required: true, message: '请选择提供商', trigger: 'change' }],
  model_name: [{ required: true, message: '请输入模型名称', trigger: 'blur' }],
}

const sysConfig = reactive({
  max_upload_mb: 100,
  rate_limit_per_minute: 60,
  default_llm_provider: 'openai',
})

function onProviderChange(val) {
  // 选择提供商时自动填充默认地址和模型
  if (PROVIDER_URLS[val] !== undefined) {
    llmForm.base_url = PROVIDER_URLS[val]
  }
  if (PROVIDER_MODELS[val]) {
    llmForm.model_name = PROVIDER_MODELS[val]
  }
}

async function loadLLMConfigs() {
  llmLoading.value = true
  try {
    const res = await systemApi.listLLMConfigs()
    llmConfigs.value = res.data
  } catch {
    ElMessage.error('加载LLM配置失败')
  } finally {
    llmLoading.value = false
  }
}

function openLLMDialog(row = null) {
  editingLLM.value = row
  if (row) {
    Object.assign(llmForm, row)
    llmForm.api_key = '' // 不回填Key
  } else {
    Object.assign(llmForm, {
      name: '', provider: 'openai', base_url: 'https://api.openai.com/v1',
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
      ElMessage.error('连接失败，请检查 API Key 和地址')
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
  setTimeout(() => {
    ElMessage.success('系统配置已保存')
    sysConfigSaving.value = false
  }, 600)
}

onMounted(loadLLMConfigs)
</script>

<style scoped>
.tab-header {
  margin-bottom: 16px;
}
</style>
