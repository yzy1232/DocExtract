<template>
  <div class="template-detail page-shell" v-loading="loading">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">TEMPLATE DETAIL</span>
        <h2 class="page-title">{{ template.name || '模板详情' }}</h2>
        <p class="page-subtitle">查看模板版本、字段定义与系统提示词，并直接基于此模板发起新的提取任务。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="ArrowLeft" @click="router.push('/templates')">返回列表</el-button>
        <el-tag :type="statusTypeMap[template.status]" size="large">
          {{ statusLabelMap[template.status] }}
        </el-tag>
        <el-button type="primary" :icon="Edit" @click="router.push(`/templates/${template.id}/edit`)">
          编辑
        </el-button>
      </div>
    </section>

    <el-row :gutter="24" v-if="template.id">
      <el-col :span="16">
        <el-card header="基本信息" shadow="never">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="模板名称" :span="2">{{ template.name }}</el-descriptions-item>
            <el-descriptions-item label="描述" :span="2">{{ template.description || '-' }}</el-descriptions-item>
            <el-descriptions-item label="版本">v{{ template.version }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatDate(template.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="更新时间" :span="2">{{ formatDate(template.updated_at) }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 字段列表 -->
        <el-card class="mt-16" shadow="never">
          <template #header>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>字段定义（{{ template.fields?.length ?? 0 }} 个）</span>
            </div>
          </template>

          <el-table :data="template.fields" stripe size="small">
            <el-table-column type="index" width="50" label="#" />
            <el-table-column prop="name" label="标识" min-width="120">
              <template #default="{ row }">
                <el-text type="primary" class="mono">{{ row.name }}</el-text>
              </template>
            </el-table-column>
            <el-table-column prop="label" label="名称" min-width="120" />
            <el-table-column label="类型" width="90" align="center">
              <template #default="{ row }">
                <el-tag size="small" type="info">{{ row.field_type }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="必填" width="70" align="center">
              <template #default="{ row }">
                <el-icon v-if="row.required" color="#22c55e"><Check /></el-icon>
                <el-icon v-else color="#cbd5e1"><Close /></el-icon>
              </template>
            </el-table-column>
            <el-table-column label="多值" width="70" align="center">
              <template #default="{ row }">
                <el-icon v-if="row.is_array" color="#22c55e"><Check /></el-icon>
                <el-icon v-else color="#cbd5e1"><Close /></el-icon>
              </template>
            </el-table-column>
            <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card header="关联操作" shadow="never">
          <el-button
            type="primary"
            style="width:100%"
            :icon="MagicStick"
            @click="router.push({ path: '/extractions/create', query: { template_id: template.id } })"
          >
            基于此模板新建提取任务
          </el-button>
        </el-card>

        <el-card class="mt-16" header="系统提示词" shadow="never" v-if="template.system_prompt">
          <el-text type="info" class="prompt-text">{{ template.system_prompt }}</el-text>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Edit, MagicStick, Check, Close } from '@element-plus/icons-vue'
import { templateApi } from '@/api/index'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const template = ref({})

const statusTypeMap = { draft: 'info', active: 'success', deprecated: 'warning', archived: 'danger' }
const statusLabelMap = { draft: '草稿', active: '已发布', deprecated: '已废弃', archived: '已归档' }

function formatDate(str) {
  if (!str) return '-'
  return new Date(str).toLocaleString('zh-CN')
}

onMounted(async () => {
  loading.value = true
  try {
    const res = await templateApi.get(route.params.id)
    template.value = res.data
  } catch {
    ElMessage.error('加载模板详情失败')
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.mt-16 {
  margin-top: 16px;
}

.mono {
  font-family: 'JetBrains Mono', 'Courier New', monospace;
  font-size: 12px;
}

.prompt-text {
  font-size: 12px;
  white-space: pre-wrap;
  line-height: 1.7;
}

@media (max-width: 768px) {
  .header-actions {
    width: 100%;
  }
}
</style>
