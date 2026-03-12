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
                      :rules="[{ required: true, message: '请输入字段标识' }, { pattern: /^[a-zA-Z_][a-zA-Z0-9_]*$/, message: '只允许字母/数字/下划线' }]"
                    >
                      <el-input v-model="field.name" placeholder="如: invoice_no" />
                    </el-form-item>
                  </el-col>
                  <el-col :span="12">
                    <el-form-item label="显示名称" :prop="`fields.${idx}.label`" :rules="[{ required: true, message: '请输入显示名称' }]">
                      <el-input v-model="field.label" placeholder="如: 发票号码" />
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
          <el-card header="操作" shadow="never">
            <el-button type="primary" style="width:100%" :loading="saving" @click="submit">
              {{ isEdit ? '保存修改' : '创建模板' }}
            </el-button>
            <el-button style="width:100%;margin-top:12px" @click="router.back()">取消</el-button>
          </el-card>
        </el-col>
      </el-row>
    </el-form>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Plus, Delete } from '@element-plus/icons-vue'
import { templateApi } from '@/api/index'

const router = useRouter()
const route = useRoute()
const formRef = ref(null)
const saving = ref(false)

const isEdit = computed(() => !!route.params.id && route.path.includes('edit'))

const form = reactive({
  name: '',
  description: '',
  status: 'draft',
  system_prompt: '',
  fields: [],
})

const rules = {
  name: [{ required: true, message: '请输入模板名称', trigger: 'blur' }],
}

const fieldTypes = [
  { label: '文本', value: 'text' },
  { label: '数字', value: 'number' },
  { label: '日期', value: 'date' },
  { label: '金额', value: 'money' },
  { label: '布尔', value: 'boolean' },
  { label: '列表', value: 'list' },
  { label: '对象', value: 'object' },
]

function addField() {
  form.fields.push({
    name: '',
    label: '',
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
  if (isEdit.value) {
    try {
      const res = await templateApi.get(route.params.id)
      Object.assign(form, res.data)
    } catch {
      ElMessage.error('加载模板信息失败')
    }
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
</style>
