<template>
  <div class="extraction-result page-shell" v-loading="loading">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">RESULT REVIEW</span>
        <h2 class="page-title">提取结果</h2>
        <p class="page-subtitle">查看字段值、置信度和验证情况，并在需要时导出为结构化结果。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="ArrowLeft" @click="router.push('/extractions')">返回列表</el-button>
        <el-tag :type="statusTypeMap[task.status]" size="large">
          {{ statusLabelMap[task.status] }}
        </el-tag>
        <template v-if="task.status === 'completed'">
          <el-button :icon="Download" @click="exportResult('xlsx')">导出 Excel</el-button>
          <el-button :icon="Download" type="primary" @click="exportResult('json')">导出 JSON</el-button>
        </template>
      </div>
    </section>

    <!-- 运行中进度条 -->
    <el-card v-if="['pending', 'running', 'queued', 'processing'].includes(task.status)" shadow="never" class="progress-card">
      <div class="progress-center">
        <el-progress type="circle" :percentage="task.progress ?? 0" :width="120" />
        <div class="progress-desc">
          <p class="progress-status">{{ statusLabelMap[task.status] }}</p>
          <p class="progress-hint">提取任务正在后台处理，请稍候…</p>
          <el-button text type="primary" @click="refreshTask">刷新状态</el-button>
        </div>
      </div>
    </el-card>

    <!-- 失败信息 -->
    <el-alert
      v-if="task.status === 'failed'"
      type="error"
      :title="task.error_message || '提取任务失败'"
      show-icon
      style="margin-bottom:16px"
    />

    <el-row :gutter="24" v-if="task.id">
      <!-- 基本信息 -->
      <el-col :span="8">
        <el-card header="任务信息" shadow="never">
          <el-descriptions :column="1" size="small" border>
            <el-descriptions-item label="任务ID">#{{ task.id }}</el-descriptions-item>
            <el-descriptions-item label="文档">{{ task.document?.original_filename ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="模板">{{ task.template?.name ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="模型">{{ task.llm_model ?? '-' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatDate(task.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="完成时间">{{ formatDate(task.completed_at) }}</el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>

      <!-- 提取字段结果 -->
      <el-col :span="16">
        <el-card shadow="never" v-if="task.status === 'completed'">
          <template #header>
            <div style="display:flex;align-items:center;gap:12px">
              <span>提取结果</span>
              <el-tag size="small" type="info">{{ matrixColumns.length }} 个字段</el-tag>
              <el-tag size="small" type="success">{{ matrixRows.length }} 条记录</el-tag>
            </div>
          </template>

          <el-table v-if="matrixColumns.length > 0" :data="matrixRows" stripe size="small">
            <el-table-column type="index" label="#" width="56" />
            <el-table-column
              v-for="col in matrixColumns"
              :key="col.prop"
              :label="col.label"
              min-width="160"
            >
              <template #default="{ row }">
                <div class="value-cell">{{ formatValue(row[col.prop]) }}</div>
              </template>
            </el-table-column>
          </el-table>

          <el-empty v-else description="暂无可展示的结构化字段" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Download } from '@element-plus/icons-vue'
import { extractionApi } from '@/api/index'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const task = ref({})
const fieldResults = ref([])
let pollTimer = null

const matrixColumns = computed(() => {
  if (!Array.isArray(fieldResults.value)) return []
  return fieldResults.value.map((item) => ({
    prop: item.field_name,
    label: item.field_label ?? item.field_name,
  }))
})

const matrixRows = computed(() => {
  if (!Array.isArray(fieldResults.value) || fieldResults.value.length === 0) return []

  const normalized = fieldResults.value.map((item) => {
    const values = Array.isArray(item.value) ? item.value : [item.value]
    return {
      key: item.field_name,
      values,
    }
  })

  const rowCount = Math.max(1, ...normalized.map((x) => x.values.length))
  return Array.from({ length: rowCount }, (_, rowIndex) => {
    const row = {}
    normalized.forEach((item) => {
      row[item.key] = rowIndex < item.values.length ? item.values[rowIndex] : null
    })
    return row
  })
})

const statusTypeMap = {
  pending: 'info', queued: 'info', running: 'warning', processing: 'warning',
  completed: 'success', failed: 'danger', cancelled: 'info',
}
const statusLabelMap = {
  pending: '待处理', queued: '排队中', running: '运行中', processing: '处理中',
  completed: '已完成', failed: '失败', cancelled: '已取消',
}

function formatDate(str) {
  if (!str) return '-'
  return new Date(str).toLocaleString('zh-CN')
}

function formatValue(val) {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

async function loadTask() {
  try {
    const res = await extractionApi.get(route.params.id)
    task.value = res.data || {}

    const taskFieldResults = Array.isArray(task.value.field_results)
      ? task.value.field_results.map((item) => ({
          field_name: item.field_name,
          field_label: item.field_name,
          value: item.normalized_value ?? item.raw_value,
          confidence: item.confidence,
          is_valid: item.is_valid,
        }))
      : []

    if (task.value.status === 'completed') {
      const rRes = await extractionApi.getResults(route.params.id)
      const resultData = rRes.data || {}
      const structuredRows = resultData.structured_result && typeof resultData.structured_result === 'object'
        ? Object.entries(resultData.structured_result).map(([key, value]) => ({
            field_name: key,
            field_label: key,
            value,
            confidence: null,
            is_valid: null,
          }))
        : []

      fieldResults.value = structuredRows.length > 0 ? structuredRows : taskFieldResults
    } else {
      fieldResults.value = []
    }
  } catch {
    ElMessage.error('加载任务失败')
  }
}

async function refreshTask() {
  loading.value = true
  try {
    await loadTask()
  } finally {
    loading.value = false
  }
}

async function exportResult(format) {
  try {
    const res = await extractionApi.export({ task_ids: [task.value.id], format })
    if (res.data.download_url) {
      window.open(res.data.download_url, '_blank')
    }
    ElMessage.success('导出成功')
  } catch {
    ElMessage.error('导出失败')
  }
}

onMounted(async () => {
  loading.value = true
  await loadTask()
  loading.value = false

  // 如果任务未完成，轮询状态
  if (['pending', 'queued', 'running', 'processing'].includes(task.value.status)) {
    pollTimer = setInterval(async () => {
      await loadTask()
      if (['completed', 'failed', 'cancelled'].includes(task.value.status)) {
        clearInterval(pollTimer)
      }
    }, 5000)
  }
})

onBeforeUnmount(() => clearInterval(pollTimer))
</script>

<style scoped>
.header-actions {
  margin-left: auto;
  display: flex;
  gap: 8px;
}

.progress-card {
  margin-bottom: 16px;
}

.progress-center {
  display: flex;
  align-items: center;
  gap: 32px;
  padding: 24px;
}

.progress-desc {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.progress-status {
  font-size: 20px;
  font-weight: 600;
  color: #14201b;
  margin: 0;
}

.progress-hint {
  font-size: 13px;
  color: #64746c;
  margin: 0;
}

.value-cell {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mono {
  font-family: 'JetBrains Mono', monospace;
}

@media (max-width: 768px) {
  .progress-center {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
