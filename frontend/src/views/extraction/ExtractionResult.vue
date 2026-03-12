<template>
  <div class="extraction-result" v-loading="loading">
    <div class="page-header">
      <el-button :icon="ArrowLeft" text @click="router.push('/extractions')">返回列表</el-button>
      <div style="display:flex;align-items:center;gap:12px">
        <h2 class="page-title">提取结果</h2>
        <el-tag :type="statusTypeMap[task.status]" size="large">
          {{ statusLabelMap[task.status] }}
        </el-tag>
      </div>
      <div class="header-actions" v-if="task.status === 'completed'">
        <el-button :icon="Download" @click="exportResult('xlsx')">导出 Excel</el-button>
        <el-button :icon="Download" type="primary" @click="exportResult('json')">导出 JSON</el-button>
      </div>
    </div>

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
              <el-tag size="small" type="info">{{ fieldResults.length }} 个字段</el-tag>
            </div>
          </template>

          <el-table :data="fieldResults" stripe size="small">
            <el-table-column prop="field_name" label="字段" min-width="140">
              <template #default="{ row }">
                <div style="display:flex;flex-direction:column">
                  <span style="font-size:13px;font-weight:500">{{ row.field_label ?? row.field_name }}</span>
                  <span class="mono" style="font-size:11px;color:#94a3b8">{{ row.field_name }}</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="提取值" min-width="200">
              <template #default="{ row }">
                <div class="value-cell">
                  <span v-if="!editingField || editingField !== row.field_name">
                    {{ formatValue(row.value) }}
                  </span>
                  <el-input
                    v-else
                    v-model="editValues[row.field_name]"
                    size="small"
                    @keyup.enter="saveEdit(row)"
                  />
                </div>
              </template>
            </el-table-column>
            <el-table-column label="置信度" width="130">
              <template #default="{ row }">
                <el-progress
                  v-if="row.confidence != null"
                  :percentage="Math.round(row.confidence * 100)"
                  :stroke-width="8"
                  :color="confidenceColor(row.confidence)"
                  :show-text="true"
                  :format="(p) => p + '%'"
                />
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="验证" width="70" align="center">
              <template #default="{ row }">
                <el-icon v-if="row.is_valid === true" color="#22c55e"><Check /></el-icon>
                <el-icon v-else-if="row.is_valid === false" color="#ef4444"><Close /></el-icon>
                <span v-else>-</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="80" align="center">
              <template #default="{ row }">
                <el-button
                  v-if="editingField !== row.field_name"
                  size="small"
                  text
                  type="primary"
                  @click="startEdit(row)"
                >
                  编辑
                </el-button>
                <el-button
                  v-else
                  size="small"
                  text
                  type="success"
                  @click="saveEdit(row)"
                >
                  保存
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Download, Check, Close } from '@element-plus/icons-vue'
import { extractionApi } from '@/api/index'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const task = ref({})
const fieldResults = ref([])
const editingField = ref(null)
const editValues = ref({})
let pollTimer = null

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

function confidenceColor(conf) {
  if (conf >= 0.9) return '#22c55e'
  if (conf >= 0.7) return '#f59e0b'
  return '#ef4444'
}

async function loadTask() {
  try {
    const res = await extractionApi.get(route.params.id)
    task.value = res.data
    if (task.value.status === 'completed') {
      const rRes = await extractionApi.getResults(route.params.id)
      fieldResults.value = rRes.data
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

function startEdit(row) {
  editingField.value = row.field_name
  editValues.value[row.field_name] = formatValue(row.value)
}

async function saveEdit(row) {
  // 更新本地
  row.value = editValues.value[row.field_name]
  editingField.value = null
  ElMessage.success('已更新（仅本地预览，导出时生效）')
}

async function exportResult(format) {
  try {
    const res = await extractionApi.export({ task_ids: [task.value.id], format })
    if (res.data.url) {
      window.open(res.data.url, '_blank')
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
.page-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.page-title {
  font-size: 22px;
  font-weight: 600;
  color: #1e293b;
  margin: 0;
}

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
  color: #1e293b;
  margin: 0;
}

.progress-hint {
  font-size: 13px;
  color: #64748b;
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
</style>
