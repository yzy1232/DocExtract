<template>
  <div class="template-create page-shell">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">TEMPLATE EDITOR</span>
        <h2 class="page-title">{{ isEdit ? '编辑模板' : '新建模板' }}</h2>
        <p class="page-subtitle">定义字段标识、显示名称和提取描述，让模型能稳定理解你的目标结构。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="ArrowLeft" @click="router.back()">返回</el-button>
      </div>
    </section>

    <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
      <el-row :gutter="24">
        <!-- 基本信息 -->
        <el-col :span="16">
          <el-card header="基本信息" shadow="never">
            <el-form-item label="模板名称" prop="name">
              <el-input v-model="form.name" placeholder="请输入模板名称" maxlength="100" show-word-limit />
            </el-form-item>
            <el-form-item label="描述" prop="description">
              <el-input
                v-model="form.description"
                type="textarea"
                :rows="3"
                placeholder="模板用途描述（可选）"
                maxlength="500"
                show-word-limit
              />
            </el-form-item>
            <el-form-item label="状态" prop="status">
              <el-radio-group v-model="form.status">
                <el-radio value="draft">草稿</el-radio>
                <el-radio value="active">立即发布</el-radio>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="系统提示词" prop="system_prompt">
              <el-input
                v-model="form.system_prompt"
                type="textarea"
                :rows="4"
                placeholder="自定义系统提示词（可选，留空使用默认）"
                maxlength="2000"
                show-word-limit
              />
            </el-form-item>
          </el-card>

          <!-- 字段定义 -->
          <el-card class="field-card" shadow="never">
            <template #header>
              <div style="display:flex;justify-content:space-between;align-items:center">
                <span>提取字段</span>
                <el-button type="primary" :icon="Plus" size="small" @click="addField">
                  添加字段
                </el-button>
              </div>
            </template>

            <div v-if="form.fields.length === 0" class="empty-fields">
              <el-text type="info">暂未添加字段，点击右上角按钮添加</el-text>
            </div>

            <div v-else class="field-list">
              <el-card
                v-for="(field, idx) in form.fields"
                :key="idx"
                class="field-item"
                shadow="hover"
              >
                <template #header>
                  <div style="display:flex;justify-content:space-between;align-items:center">
                    <span style="font-size:13px;color:#64748b">字段 {{ idx + 1 }}</span>
                    <el-button
                      :icon="Delete"
                      size="small"
                      type="danger"
                      text
                      @click="removeField(idx)"
                    />
                  </div>
                </template>

                <el-row :gutter="16">
                  <el-col :span="12">
                    <el-form-item
                      :prop="`fields.${idx}.name`"
                        label="字段标识"
                        :rules="[{ required: true, message: '请输入字段标识' }, { pattern: /^[\u4e00-\u9fff_a-zA-Z][\u4e00-\u9fff_a-zA-Z0-9_]*$/u, message: '字段标识只能以中文/字母/下划线开头，仅允许中文/字母/数字/下划线' }]"
                    >
                      <el-input v-model="field.name" placeholder="如: invoice_no" />
                    </el-form-item>
                  </el-col>
                    <el-col :span="12">
                      <el-form-item label="显示名称" :prop="`fields.${idx}.display_name`" :rules="[{ required: true, message: '请输入显示名称' }]">
                        <el-input v-model="field.display_name" placeholder="如: 发票号码" />
                      </el-form-item>
                    </el-col>
                  <el-col :span="8">
                    <el-form-item label="字段类型">
                      <el-select v-model="field.field_type" style="width:100%">
                        <el-option v-for="t in fieldTypes" :key="t.value" :label="t.label" :value="t.value" />
                      </el-select>
                    </el-form-item>
                  </el-col>
                  <el-col :span="8">
                    <el-form-item label="是否必填">
                      <el-switch v-model="field.required" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="8">
                    <el-form-item label="是否多值">
                      <el-switch v-model="field.is_array" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="24">
                    <el-form-item label="提取描述">
                      <el-input
                        v-model="field.description"
                        placeholder="帮助LLM理解该字段含义的描述（可选）"
                      />
                    </el-form-item>
                  </el-col>
                </el-row>
              </el-card>
            </div>
          </el-card>
        </el-col>

        <!-- 右侧操作栏 -->
        <el-col :span="8">
          <el-card header="从文档自动生成" shadow="never" class="auto-card">
            <el-form-item label="选择文档" label-width="80px" style="margin-bottom: 12px">
              <el-select
                v-model="inferForm.document_id"
                placeholder="请选择已解析文档"
                filterable
                style="width:100%"
              >
                <el-option
                  v-for="doc in documentOptions"
                  :key="doc.id"
                  :label="doc.display_name || doc.name"
                  :value="doc.id"
                />
              </el-select>
            </el-form-item>
            <el-form-item label="字段上限" label-width="80px" style="margin-bottom: 12px">
              <el-input-number v-model="inferForm.max_fields" :min="1" :max="200" style="width:100%" />
            </el-form-item>
            <el-button type="success" style="width:100%" :loading="inferring" @click="generateFromDocument()">
              自动生成字段
            </el-button>
            <div v-if="inferProgress.visible" class="infer-progress">
              <div class="infer-progress-head">
                <span>{{ inferProgress.text }}</span>
                <span>{{ inferProgress.chunkIndex }}/{{ inferProgress.chunkTotal }}</span>
              </div>
              <el-progress :percentage="inferProgress.percent" :stroke-width="8" />
            </div>
            <div class="auto-hint">生成后可继续修改字段名称、类型与描述。</div>
          </el-card>

          <el-card header="操作" shadow="never">
            <div style="display:flex;flex-direction:column;gap:12px">
              <el-button type="primary" style="width:100%" :loading="saving" @click="submit">
                {{ isEdit ? '保存修改' : '创建模板' }}
              </el-button>
              <el-button style="width:100%;margin-left:0" @click="router.back()">取消</el-button>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </el-form>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Plus, Delete } from '@element-plus/icons-vue'
import { templateApi, documentApi } from '@/api/index'

const router = useRouter()
const route = useRoute()
const formRef = ref(null)
const saving = ref(false)
const inferring = ref(false)
const documentOptions = ref([])

const isEdit = computed(() => !!route.params.id && route.path.includes('edit'))

const form = reactive({
  name: '',
  description: '',
  status: 'draft',
  system_prompt: '',
  fields: [],
})

const inferForm = reactive({
  document_id: '',
  max_fields: 50,
})

const inferProgress = reactive({
  visible: false,
  percent: 0,
  chunkIndex: 0,
  chunkTotal: 0,
  text: '等待开始...',
})

const rules = {
  name: [{ required: true, message: '请输入模板名称', trigger: 'blur' }],
}

const fieldTypes = [
  { label: '文本', value: 'text' },
  { label: '数字', value: 'number' },
  { label: '日期', value: 'date' },
  { label: '日期时间', value: 'datetime' },
  { label: '布尔', value: 'boolean' },
  { label: '列表', value: 'list' },
  { label: '表格', value: 'table' },
  { label: '地址', value: 'address' },
  { label: '电话', value: 'phone' },
  { label: '邮箱', value: 'email' },
  { label: '链接', value: 'url' },
  { label: '自定义', value: 'custom' },
]

function addField() {
  form.fields.push({
    name: '',
    display_name: '',
    field_type: 'text',
    required: false,
    is_array: false,
    description: '',
    sort_order: form.fields.length,
  })
}

function removeField(idx) {
  form.fields.splice(idx, 1)
}

async function loadProcessedDocuments() {
  try {
    const res = await documentApi.list({ status: 'processed', page_size: 100, page: 1 })
    documentOptions.value = res.data.items || []
  } catch {
    documentOptions.value = []
  }
}

async function generateFromDocument(forceOverwrite = false) {
  if (!inferForm.document_id) {
    ElMessage.warning('请先选择文档')
    return
  }

  if (!forceOverwrite && form.fields.length > 0) {
    try {
      await ElMessageBox.confirm('自动生成会覆盖当前字段，是否继续？', '覆盖确认', { type: 'warning' })
    } catch {
      return
    }
  }

  inferring.value = true
  inferProgress.visible = true
  inferProgress.percent = 0
  inferProgress.chunkIndex = 0
  inferProgress.chunkTotal = 0
  inferProgress.text = '正在启动自动生成...'
  try {
    const payload = {
      document_id: inferForm.document_id,
      max_fields: inferForm.max_fields,
      template_name: form.name || undefined,
      description: form.description || undefined,
    }
    console.info('[TemplateInfer][request]', {
      payload,
      currentFieldCount: form.fields.length,
      forceOverwrite,
    })
    const res = await templateApi.inferFromDocumentStream(payload, {
      inactivityTimeoutMs: 45000,
      onProgress: (progress) => {
        const stage = progress?.stage
        const chunkIndex = progress?.chunk_index
        const chunkTotal = progress?.chunk_total
        const progressPercent = Number(progress?.progress_percent || 0)
        const progressFields = Array.isArray(progress?.aggregated_fields) ? progress.aggregated_fields : []

        console.info('[TemplateInfer][progress]', {
          stage,
          chunkIndex,
          chunkTotal,
          aggregatedFieldCount: progressFields.length,
        })

        if (!form.name && progress?.name) {
          form.name = progress.name
        }
        if (!form.description && progress?.description) {
          form.description = progress.description
        }

        if (chunkTotal) {
          inferProgress.chunkTotal = Number(chunkTotal) || 0
        }
        if (chunkIndex) {
          inferProgress.chunkIndex = Number(chunkIndex) || 0
        }
        inferProgress.percent = Math.max(0, Math.min(100, progressPercent || (inferProgress.chunkTotal > 0
          ? Math.round((inferProgress.chunkIndex / inferProgress.chunkTotal) * 100)
          : 0)))
        inferProgress.text = stage === 'chunk_done'
          ? `正在处理分片 ${inferProgress.chunkIndex}/${inferProgress.chunkTotal}，已回填 ${progressFields.length} 个候选字段`
          : '正在处理中...'

        if (progressFields.length > 0) {
          form.fields = progressFields.map((field, idx) => ({
            name: field.name || `field_${idx + 1}`,
            display_name: field.display_name || `字段${idx + 1}`,
            field_type: field.field_type || 'text',
            required: !!field.required,
            is_array: field.field_type === 'list',
            description: field.description || '',
            extraction_hints: field.extraction_hints || '',
            sort_order: field.sort_order ?? idx,
          }))
        }
      },
      onFinal: (finalData) => {
        const finalCount = Array.isArray(finalData?.fields) ? finalData.fields.length : 0
        inferProgress.percent = 100
        inferProgress.text = `处理完成，最终返回 ${finalCount} 个字段`
      },
      onTimeout: () => {
        inferProgress.text = '等待分片结果超时，已中止请求'
      },
    })
    console.info('[TemplateInfer][response]', {
      responseType: typeof res,
      hasData: !!res?.data,
      topLevelKeys: res && typeof res === 'object' ? Object.keys(res) : [],
    })

    // 兼容两种返回结构：
    // 1) 拦截器返回 ResponseBase => res.data 为业务数据
    // 2) 直接返回业务数据 => res 即业务数据
    const data = (res && typeof res === 'object' && res.data && typeof res.data === 'object') ? res.data : (res || {})
    const rawFields = data?.fields
    const fieldsArray = Array.isArray(rawFields) ? rawFields : []

    if (!Array.isArray(rawFields)) {
      console.warn('[TemplateInfer][unexpected-fields-shape]', {
        fieldsType: typeof rawFields,
        rawFields,
        data,
      })
    }

    if (!form.name && data.name) {
      form.name = data.name
    }
    if (!form.description && data.description) {
      form.description = data.description
    }

    form.fields = fieldsArray.map((field, idx) => ({
      name: field.name || `field_${idx + 1}`,
      display_name: field.display_name || `字段${idx + 1}`,
      field_type: field.field_type || 'text',
      required: !!field.required,
      is_array: field.field_type === 'list',
      description: field.description || '',
      extraction_hints: field.extraction_hints || '',
      sort_order: field.sort_order ?? idx,
    }))

    console.info('[TemplateInfer][mapped-fields]', {
      returnedFieldCount: fieldsArray.length,
      mappedFieldCount: form.fields.length,
      sample: form.fields.slice(0, 3),
    })

    ElMessage.success(`已生成 ${form.fields.length} 个字段，可继续编辑后保存`)
  } catch (err) {
    console.error('[TemplateInfer][failed]', {
      message: err?.message,
      code: err?.code,
      status: err?.response?.status,
      responseData: err?.response?.data,
      stack: err?.stack,
    })
    if (err?.code === 'ECONNABORTED' || err?.code === 'INFER_STREAM_TIMEOUT') {
      ElMessage.error('自动生成超时，请稍后重试（后端可能仍在处理中）')
    } else {
      ElMessage.error('自动生成失败')
    }
  } finally {
    inferring.value = false
    window.setTimeout(() => {
      if (!inferring.value) {
        inferProgress.visible = false
      }
    }, 1200)
  }
}

async function submit() {
  await formRef.value.validate()
  saving.value = true
  try {
    if (isEdit.value) {
      await templateApi.update(route.params.id, form)
      ElMessage.success('模板已更新')
    } else {
      const res = await templateApi.create(form)
      ElMessage.success('模板创建成功')
      router.push(`/templates/${res.data.id}`)
      return
    }
    router.push('/templates')
  } catch {
    ElMessage.error(isEdit.value ? '更新失败' : '创建失败')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await loadProcessedDocuments()

  if (isEdit.value) {
    try {
      const res = await templateApi.get(route.params.id)
      Object.assign(form, res.data)
    } catch {
      ElMessage.error('加载模板信息失败')
    }
    return
  }

  const queryDocId = String(route.query.document_id || '')
  if (queryDocId) {
    inferForm.document_id = queryDocId
    await generateFromDocument(true)
  }
})
</script>

<style scoped>
.field-card {
  margin-top: 16px;
}

.field-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.field-item :deep(.el-card__body) {
  padding: 12px 16px;
}

.field-item :deep(.el-card__header) {
  padding: 8px 16px;
  background: rgba(247, 241, 232, 0.7);
}

.empty-fields {
  text-align: center;
  padding: 40px 0;
}

.auto-card {
  margin-bottom: 16px;
}

.auto-hint {
  margin-top: 10px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}

.infer-progress {
  margin-top: 12px;
  padding: 10px;
  border-radius: 8px;
  background: rgba(16, 185, 129, 0.08);
}

.infer-progress-head {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #0f766e;
  margin-bottom: 8px;
}
</style>
