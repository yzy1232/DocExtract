<template>
  <div class="extraction-create page-shell">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">NEW EXTRACTION</span>
        <h2 class="page-title">新建提取任务</h2>
        <p class="page-subtitle">选择文档、模板和优先级后提交任务，系统会在后台异步处理并持续更新结果状态。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="ArrowLeft" @click="router.push('/extractions')">返回列表</el-button>
      </div>
    </section>

    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-row :gutter="24">
        <el-col :span="16">
          <el-card header="基本配置" shadow="never">
            <!-- 文档选择 -->
            <el-form-item label="选择文档" prop="document_ids">
              <el-select
                v-model="form.document_ids"
                placeholder="请选择要提取的文档"
                style="width:100%"
                filterable
                remote
                multiple
                :remote-method="searchDocuments"
                :loading="documentsLoading"
              >
                <el-option
                  v-for="doc in documentOptions"
                  :key="doc.id"
                  :label="docLabel(doc)"
                  :value="doc.id"
                >
                  <div style="display:flex;justify-content:space-between;align-items:center">
                    <span>{{ docLabel(doc) }}</span>
                    <el-tag
                      :type="doc.status === 'completed' ? 'success' : 'warning'"
                      size="small"
                    >
                      {{ statusLabelMap[doc.status] || doc.status }}
                    </el-tag>
                  </div>
                </el-option>
              </el-select>
            </el-form-item>

            <!-- 模板选择 -->
            <el-form-item label="选择模板" prop="template_id">
              <el-select
                v-model="form.template_id"
                placeholder="请选择提取模板"
                style="width:100%"
                filterable
                @change="handleTemplateChange"
              >
                <el-option
                  v-for="tpl in templateOptions"
                  :key="tpl.id"
                  :label="tpl.name"
                  :value="tpl.id"
                />
              </el-select>
            </el-form-item>

            <!-- 优先级 -->
            <el-form-item label="优先级" prop="priority">
              <el-radio-group v-model="form.priority">
                <el-radio-button value="low">低</el-radio-button>
                <el-radio-button value="normal">普通</el-radio-button>
                <el-radio-button value="high">高</el-radio-button>
                <el-radio-button value="urgent">紧急</el-radio-button>
              </el-radio-group>
            </el-form-item>

            <!-- LLM配置 -->
            <el-form-item label="LLM模型">
              <el-select v-model="form.llm_config_id" placeholder="从系统LLM配置中选择" style="width:360px" filterable>
                <el-option
                  v-for="cfg in llmOptions"
                  :key="cfg.id"
                  :label="`${cfg.name} (${cfg.model_name})`"
                  :value="cfg.id"
                />
              </el-select>
            </el-form-item>

            <el-form-item label="备注">
              <el-input v-model="form.remark" placeholder="任务描述（可选）" />
            </el-form-item>
          </el-card>

          <!-- 选中模板预览 -->
          <el-card class="mt-16" header="模板字段预览" shadow="never" v-if="selectedTemplate">
            <el-table :data="selectedTemplate.fields" size="small" stripe>
              <el-table-column prop="name" label="字段标识" width="160" />
              <el-table-column prop="label" label="显示名称" width="140" />
              <el-table-column label="类型" width="90">
                <template #default="{ row }">
                  <el-tag size="small" type="info">{{ row.field_type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="必填" width="70" align="center">
                <template #default="{ row }">
                  <el-icon v-if="row.required" color="#22c55e"><Check /></el-icon>
                </template>
              </el-table-column>
              <el-table-column prop="description" label="描述" show-overflow-tooltip />
            </el-table>
          </el-card>
        </el-col>

        <el-col :span="8">
          <el-card header="提交" shadow="never">
            <div style="display:flex;flex-direction:column;gap:12px">
              <el-button
                type="primary"
                style="width:100%"
                size="large"
                :loading="submitting"
                @click="submit"
              >
                提交提取任务
              </el-button>
              <el-button style="width:100%;margin-left:0" @click="router.push('/extractions')">
                取消
              </el-button>
            </div>

            <el-divider />

            <el-alert
              type="info"
              title="提示"
              description="提取任务提交后将异步执行，可在任务列表中查看进度。"
              :closable="false"
              show-icon
            />
          </el-card>
        </el-col>
      </el-row>
    </el-form>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Check } from '@element-plus/icons-vue'
import { documentApi, templateApi, extractionApi, systemApi } from '@/api/index'

const router = useRouter()
const route = useRoute()
const formRef = ref(null)
const submitting = ref(false)
const documentsLoading = ref(false)
const documentOptions = ref([])
const templateOptions = ref([])
const selectedTemplate = ref(null)
const llmOptions = ref([])

const statusLabelMap = {
  pending: '待解析', processing: '处理中', parsing: '解析中',
  completed: '已完成', failed: '失败', deleted: '已删除',
}

function docLabel(doc) {
  return doc.display_name || doc.name || doc.original_filename || '未命名文档'
}

const form = reactive({
  document_ids: [],
  template_id: null,
  priority: 'normal',
  remark: '',
  // store selected llm config id and a snapshot object
  llm_config_id: null,
  llm_config: { model: 'gpt-4o', temperature: 0.1, max_tokens: 4096 },
})

const rules = {
  document_ids: [{ required: true, message: '请选择文档', trigger: 'change' }],
  template_id: [{ required: true, message: '请选择模板', trigger: 'change' }],
}

async function searchDocuments(keyword) {
  documentsLoading.value = true
  try {
    const res = await documentApi.list({ keyword, page_size: 20 })
    documentOptions.value = res.data.items
  } finally {
    documentsLoading.value = false
  }
}

async function handleTemplateChange(id) {
  if (!id) { selectedTemplate.value = null; return }
  try {
    const res = await templateApi.get(id)
    selectedTemplate.value = res.data
  } catch {
    selectedTemplate.value = null
  }
}

async function submit() {
  await formRef.value.validate()
  submitting.value = true
  try {
    // map form to backend ExtractionCreate schema
    const selectedCfg = llmOptions.value.find((c) => c.id === form.llm_config_id)
    // 支持多选：若选择多个文档则调用批量接口
    if (form.document_ids && form.document_ids.length > 1) {
      const batchPayload = {
        document_ids: form.document_ids,
        template_id: form.template_id,
        priority: form.priority,
        llm_provider: null,
        llm_model: selectedCfg ? selectedCfg.model_name : form.llm_config.model,
      }
      const res = await extractionApi.batchCreate(batchPayload)
      ElMessage.success('批量提取任务已提交')
      if (res.data && res.data.length > 0) {
        router.push(`/extractions/${res.data[0].id}/result`)
      } else {
        router.push('/extractions')
      }
    } else {
      const payload = {
        document_id: form.document_ids && form.document_ids.length === 1 ? form.document_ids[0] : form.document_id,
        template_id: form.template_id,
        priority: form.priority,
        llm_provider: null,
        llm_model: selectedCfg ? selectedCfg.model_name : form.llm_config.model,
        extra_config: selectedCfg ? selectedCfg : form.llm_config,
      }
      const res = await extractionApi.create(payload)
      ElMessage.success('提取任务已提交')
      router.push(`/extractions/${res.data.id}/result`)
    }
  } catch {
    ElMessage.error('提交失败，请重试')
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  // 加载模板列表
  try {
    const res = await templateApi.list({ status: 'active', page_size: 100 })
    templateOptions.value = res.data.items
  } catch { /* ignore */ }

  // 加载系统 LLM 配置用于下拉
  try {
    const res = await systemApi.listLLMConfigs()
    // 仅展示已启用的配置，并按后端顺序展示
    llmOptions.value = (res.data || []).filter((c) => c.is_active)
    // 预选默认配置（若存在）否则选第一个
    const defaultCfg = llmOptions.value.find((c) => c.is_default) || llmOptions.value[0]
    if (defaultCfg) {
      form.llm_config_id = defaultCfg.id
      form.llm_config = {
        model: defaultCfg.model_name,
        base_url: defaultCfg.base_url,
        name: defaultCfg.name,
      }
    }
  } catch {
    // ignore
  }

  // 预填 query 参数（支持单个 document_id）
  if (route.query.document_id) {
    form.document_ids = [route.query.document_id]
    await searchDocuments('')
  }
  if (route.query.template_id) {
    form.template_id = route.query.template_id
    await handleTemplateChange(form.template_id)
  }
})
</script>

<style scoped>
.mt-16 {
  margin-top: 16px;
}
</style>
