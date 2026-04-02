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
        <el-tag :type="statusTypeMap[displayStatus]" size="large">
          {{ statusLabelMap[displayStatus] }}
        </el-tag>
        <template v-if="task.status === 'completed'">
          <el-button
            :icon="Download"
            :loading="exportingFormat === 'xlsx'"
            :disabled="isExporting"
            @click="exportResult('xlsx')"
          >
            导出 Excel
          </el-button>
          <el-button
            :icon="Download"
            type="primary"
            :loading="exportingFormat === 'json'"
            :disabled="isExporting"
            @click="exportResult('json')"
          >
            导出 JSON
          </el-button>
        </template>
      </div>
    </section>

    <!-- 运行中进度条 -->
    <el-card v-if="showProgressCard" shadow="never" class="progress-card">
      <div class="progress-center">
        <el-progress type="circle" :percentage="smoothProgress" :width="120" :format="formatPercentage" />
        <div class="progress-desc">
          <p class="progress-status">{{ statusLabelMap[displayStatus] }}</p>
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
        <el-card shadow="never" v-if="task.status === 'completed' || fieldResults.length > 0">
          <template #header>
            <div style="display:flex;align-items:center;gap:12px">
              <span>{{ task.status === 'completed' ? '提取结果' : '分块结果预览' }}</span>
              <el-tag size="small" type="info">{{ matrixColumns.length }} 个字段</el-tag>
              <el-tag size="small" type="success">{{ matrixRows.length }} 条记录</el-tag>
              <el-tag size="small" type="warning" v-if="pagination.totalRows > pagination.pageSize">
                已分页展示
              </el-tag>
              <el-tag v-if="task.status !== 'completed'" size="small" type="warning">处理中</el-tag>
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

          <div v-if="pagination.totalRows > 0" style="margin-top:12px;display:flex;justify-content:flex-end;">
            <el-pagination
              background
              layout="total, sizes, prev, pager, next"
              :total="pagination.totalRows"
              :current-page="pagination.page"
              :page-size="pagination.pageSize"
              :page-sizes="[10, 25, 50, 100]"
              @current-change="handlePageChange"
              @size-change="handlePageSizeChange"
            />
          </div>
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
import { formatDateToUTC8 } from '@/utils/datetime'

const router = useRouter()
const route = useRoute()
const loading = ref(false)
const task = ref({})
const fieldResults = ref([])
const smoothProgress = ref(0)
const shouldShowCompletionTransition = ref(false)
const pagination = ref({
  page: 1,
  pageSize: 10,
  totalRows: 0,
  totalPages: 1,
})
let pollTimer = null
let smoothTimer = null
let completedEmptyPollCount = 0
const exportingFormat = ref('')
const isExporting = computed(() => Boolean(exportingFormat.value))
let exportingNotice = null
const ACTIVE_STATUSES = ['pending', 'queued', 'running', 'processing', 'retrying']

const targetProgress = computed(() => normalizeProgress(task.value.progress ?? 0))

const isFinishingToCompleted = computed(() => {
  return task.value.status === 'completed' && shouldShowCompletionTransition.value && smoothProgress.value + 0.2 < targetProgress.value
})

const showProgressCard = computed(() => {
  return ACTIVE_STATUSES.includes(task.value.status) || isFinishingToCompleted.value
})

const displayStatus = computed(() => {
  if (isFinishingToCompleted.value) {
    return 'processing'
  }
  return task.value.status
})

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
  pending: 'info', queued: 'info', running: 'warning', processing: 'warning', retrying: 'warning',
  completed: 'success', failed: 'danger', cancelled: 'info',
}
const statusLabelMap = {
  pending: '待处理', queued: '排队中', running: '运行中', processing: '处理中', retrying: '重试中',
  completed: '已完成', failed: '失败', cancelled: '已取消',
}

function formatDate(str) {
  return formatDateToUTC8(str)
}

function formatValue(val) {
  if (val === null || val === undefined) return '-'
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

function normalizeProgress(progress) {
  if (Number.isNaN(Number(progress))) return 0
  return Math.max(0, Math.min(100, Number(progress)))
}

function round2(num) {
  return Math.round(num * 100) / 100
}

function formatPercentage(percentage) {
  return `${round2(Number(percentage) || 0).toFixed(2)}%`
}

function syncSmoothProgress() {
  const latestTarget = normalizeProgress(task.value.progress ?? 0)
  const status = task.value.status
  const isCompletionTransition = status === 'completed' && shouldShowCompletionTransition.value

  if ((status === 'failed' || status === 'cancelled') || (status === 'completed' && !isCompletionTransition)) {
    smoothProgress.value = round2(latestTarget)
    if (smoothTimer) {
      clearInterval(smoothTimer)
      smoothTimer = null
    }
    return
  }

  if (!smoothTimer) {
    smoothTimer = setInterval(() => {
      const latestTarget = normalizeProgress(task.value.progress ?? 0)
      const isDone = ['completed', 'failed', 'cancelled'].includes(task.value.status)
      const delta = latestTarget - smoothProgress.value

      if (Math.abs(delta) < 0.2) {
        smoothProgress.value = round2(latestTarget)
        if (task.value.status === 'completed') {
          shouldShowCompletionTransition.value = false
        }
        if (isDone) {
          clearInterval(smoothTimer)
          smoothTimer = null
        }
        return
      }

      const step = isDone
        ? Math.max(1.2, Math.abs(delta) * 0.28)
        : Math.max(0.4, Math.abs(delta) * 0.2)
      const next = smoothProgress.value + Math.sign(delta) * step

      if ((delta > 0 && next > latestTarget) || (delta < 0 && next < latestTarget)) {
        smoothProgress.value = round2(latestTarget)
      } else {
        smoothProgress.value = round2(next)
      }
    }, 120)
  }
}

async function loadTask() {
  try {
    const previousStatus = task.value.status
    const res = await extractionApi.get(route.params.id)
    task.value = res.data || {}

    if (task.value.status === 'completed' && ACTIVE_STATUSES.includes(previousStatus)) {
      shouldShowCompletionTransition.value = true
    }
    if (ACTIVE_STATUSES.includes(task.value.status)) {
      shouldShowCompletionTransition.value = true
    }

    syncSmoothProgress()

    const taskFieldResults = Array.isArray(task.value.field_results)
      ? task.value.field_results.map((item) => ({
          field_name: item.field_name,
          field_label: item.field_name,
          value: item.normalized_value ?? item.raw_value,
          confidence: item.confidence,
          is_valid: item.is_valid,
        }))
      : []

    let previewRows = []
    
    // 【新增】优先从raw_result.partial_chunks中构建即时结果（流式显示已完成chunks）
    const rawResult = task.value.raw_result || {}
    const partialChunks = Array.isArray(rawResult.partial_chunks) ? rawResult.partial_chunks : []
    
    if (partialChunks.length > 0) {
      // 聚合所有已完成chunks的字段，用最后一个chunk的结果作为预览
      const latestChunk = partialChunks[partialChunks.length - 1]
      if (latestChunk && typeof latestChunk === 'object') {
        const fieldsMap = latestChunk.fields || {}
        const records = latestChunk.records || []
        
        if (typeof fieldsMap === 'object' && Object.keys(fieldsMap).length > 0) {
          previewRows = Object.entries(fieldsMap).map(([fieldName, fieldValue]) => ({
            field_name: fieldName,
            field_label: fieldName,
            value: records.length > 0 
              ? records.map(r => r && r[fieldName] ? r[fieldName] : null)
              : [fieldValue],
            confidence: null,
            is_valid: null,
          }))
        }
      }
    }
    
    // 【原有逻辑】最终结果API降为备选方案
    if (previewRows.length === 0) {
      try {
        const rRes = await extractionApi.getResults(route.params.id, {
          paged: true,
          page: pagination.value.page,
          page_size: pagination.value.pageSize,
        })
        const resultData = rRes.data || {}
        const structured = resultData.structured_result || {}
        if (Array.isArray(structured.columns) && Array.isArray(structured.rows)) {
          const p = structured.pagination || {}
          pagination.value = {
            page: Number(p.page) || pagination.value.page,
            pageSize: Number(p.page_size) || pagination.value.pageSize,
            totalRows: Number(p.total_rows) || 0,
            totalPages: Number(p.total_pages) || 1,
          }

          previewRows = (structured.columns || []).map((col) => {
            const key = col.field_name || col.field_label
            return {
              field_name: key,
              field_label: col.field_label || key,
              value: (structured.rows || []).map((r) => (r ? r[key] : null)),
              confidence: null,
              is_valid: null,
            }
          })
        } else {
          // 兼容旧版结构
          previewRows = structured && typeof structured === 'object'
            ? Object.entries(structured).map(([key, value]) => ({
                field_name: key,
                field_label: key,
                value,
                confidence: null,
                is_valid: null,
              }))
            : []
        }
      } catch {
        previewRows = []
      }
    }

    if (task.value.status === 'completed') {
      fieldResults.value = previewRows.length > 0 ? previewRows : taskFieldResults
      if (fieldResults.value.length === 0) {
        completedEmptyPollCount += 1
      } else {
        completedEmptyPollCount = 0
      }
    } else {
      // 【改进】即使任务还在processing，如果有partial chunks就立即展示
      fieldResults.value = previewRows.length > 0 ? previewRows : []
      completedEmptyPollCount = 0
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

async function handlePageChange(page) {
  pagination.value.page = page
  await refreshTask()
}

async function handlePageSizeChange(size) {
  pagination.value.pageSize = size
  pagination.value.page = 1
  await refreshTask()
}

async function exportResult(format) {
  if (isExporting.value) {
    ElMessage.info('导出任务正在进行中，请稍候')
    return
  }

  exportingFormat.value = format
  exportingNotice = ElMessage({
    type: 'info',
    duration: 0,
    showClose: true,
    message: '下载任务已提交，请等待文件生成与下载完成...',
  })

  try {
    console.log(`[导出] 开始导出${format}格式，任务ID:${task.value.id}`)
    const res = await extractionApi.export({ task_ids: [task.value.id], format })
    console.log(`[导出] 导出API响应:`, res?.data)
    const objectKey = res?.data?.object_key
    if (!objectKey) {
      throw new Error('导出文件标识缺失')
    }
    console.log(`[导出] 获得对象键:${objectKey}，开始通过代理下载...`)
    ElMessage.info('文件已生成，正在下载，请勿关闭页面...')

    const downloadRes = await extractionApi.downloadExport(objectKey)
    const contentType = downloadRes.headers?.['content-type'] || 'application/octet-stream'
    const blob = downloadRes.data instanceof Blob
      ? downloadRes.data
      : new Blob([downloadRes.data], { type: contentType })
    console.log(`[导出] 下载完成，大小:${blob.size || 0}字节`)

    if (!blob || blob.size === 0) {
      throw new Error('下载内容为空')
    }

    let filename = `extraction_export_${new Date().getTime()}.${format}`
    const contentDisposition = downloadRes.headers?.['content-disposition'] || ''
    const utf8FilenameMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
    const plainFilenameMatch = contentDisposition.match(/filename="?([^";]+)"?/i)
    if (utf8FilenameMatch && utf8FilenameMatch[1]) {
      filename = decodeURIComponent(utf8FilenameMatch[1])
    } else if (plainFilenameMatch && plainFilenameMatch[1]) {
      filename = decodeURIComponent(plainFilenameMatch[1])
    }
    console.log(`[导出] 文件名:${filename}`)

    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    window.URL.revokeObjectURL(url)
    console.log(`[导出] ${format}导出完成`)
    ElMessage.success(`${format === 'json' ? 'JSON' : 'Excel'}导出成功`)
  } catch (err) {
    console.error(`[导出] ${format}导出失败:`, err)
    ElMessage.error(`${format === 'json' ? 'JSON' : 'Excel'}导出失败: ${err.message || '未知错误'}`)
  } finally {
    if (exportingNotice) {
      exportingNotice.close()
      exportingNotice = null
    }
    exportingFormat.value = ''
  }
}

function shouldPollTask() {
  // 任务还在处理中时，频繁轮询以获取partial chunks
  if (ACTIVE_STATUSES.includes(task.value.status)) {
    return true
  }
  // 任务完成但结果为空时，继续轮询作为备选
  if (task.value.status === 'completed' && fieldResults.value.length === 0 && completedEmptyPollCount < 12) {
    return true
  }
  return false
}

onMounted(async () => {
  loading.value = true
  await loadTask()
  loading.value = false

  if (shouldPollTask()) {
    // 【改进】处理中时用1秒快速轮询（获取partial chunks），完成后改为5秒
    const startPolling = () => {
      pollTimer = setInterval(async () => {
        await loadTask()
        const isProcessing = ['pending', 'queued', 'running', 'processing', 'retrying'].includes(task.value.status)
        
        if (!shouldPollTask()) {
          clearInterval(pollTimer)
          if (task.value.status === 'completed' && fieldResults.value.length === 0) {
            ElMessage.warning('任务已完成，但结果暂不可见，请稍后刷新')
          }
        } else if (isProcessing) {
          // 继续快速轮询，保持检测新的partial chunks
        }
      }, 1000)  // 改为1秒快速轮询
    }
    startPolling()
  }
})

onBeforeUnmount(() => {
  clearInterval(pollTimer)
  clearInterval(smoothTimer)
})
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
