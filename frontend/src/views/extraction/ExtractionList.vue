<template>
  <div class="extraction-list page-shell">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">TASK MONITOR</span>
        <h2 class="page-title">提取任务</h2>
        <p class="page-subtitle">按状态、优先级和进度跟踪任务运行，把结果导出和问题排查都收敛到一个视图中。</p>
      </div>
      <div class="page-actions">
        <el-button type="primary" :icon="Plus" @click="router.push('/extractions/create')">
          新建任务
        </el-button>
      </div>
    </section>

    <el-card shadow="never" class="search-card">
      <el-row :gutter="16" align="middle">
        <el-col :span="5">
          <el-select v-model="query.status" placeholder="任务状态" clearable style="width:100%">
            <el-option label="待处理" value="pending" />
            <el-option label="运行中" value="running" />
            <el-option label="已完成" value="completed" />
            <el-option label="失败" value="failed" />
            <el-option label="已取消" value="cancelled" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-button type="primary" :icon="Search" @click="loadTasks">搜索</el-button>
          <el-button @click="resetQuery">重置</el-button>
        </el-col>
        <el-col :span="4" :offset="11" style="text-align:right">
          <el-button :icon="Refresh" circle @click="loadTasks" :loading="loading" />
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="never">
      <el-table :data="tasks" v-loading="loading" stripe row-key="id" table-layout="fixed">
        <el-table-column prop="id" label="任务ID" width="90">
          <template #default="{ row }">
            <el-text class="mono" size="small">#{{ shortId(row.id) }}</el-text>
          </template>
        </el-table-column>
        <el-table-column label="文档" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.document_name ?? row.document_id }}</template>
        </el-table-column>
        <el-table-column label="模板" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.template_name ?? row.template_id ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="进度" width="140">
          <template #default="{ row }">
            <el-progress
              v-if="['running', 'processing'].includes(row.status)"
              :percentage="getSmoothProgress(row)"
              :stroke-width="8"
              :format="formatPercentage"
            />
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTypeMap[row.status]" size="small">
              {{ statusLabelMap[row.status] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="优先级" width="80" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="priorityTypeMap[row.priority]" round>
              {{ priorityLabelMap[row.priority] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="140" align="center" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'completed'"
              size="small"
              text
              type="success"
              @click="router.push(`/extractions/${row.id}/result`)"
            >
              查看结果
            </el-button>
            <el-button
              v-else-if="['pending', 'queued', 'running', 'processing'].includes(row.status)"
              size="small"
              text
              type="warning"
              @click="router.push(`/extractions/${row.id}`)"
            >
              进度
            </el-button>
            <el-button
              v-if="row.status === 'failed'"
              size="small"
              text
              type="danger"
            >
              查看错误
            </el-button>
            <el-text v-if="!['completed', 'pending', 'queued', 'running', 'processing', 'failed'].includes(row.status)" type="info" size="small">
              -
            </el-text>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="query.page"
          :total="total"
          :page-sizes="[10, 20, 50]"
          v-model:page-size="query.page_size"
          layout="total, sizes, prev, pager, next"
          background
          @change="loadTasks"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Plus, Search, Refresh } from '@element-plus/icons-vue'
import { extractionApi } from '@/api/index'

const router = useRouter()
const loading = ref(false)
const tasks = ref([])
const total = ref(0)
const smoothProgressMap = ref({})
let timer = null
let smoothTimer = null

const query = reactive({ status: '', page: 1, page_size: 10 })

const statusTypeMap = {
  pending: 'info', queued: 'info', running: 'warning', processing: 'warning',
  completed: 'success', failed: 'danger', cancelled: 'info',
}
const statusLabelMap = {
  pending: '待处理', queued: '排队中', running: '运行中', processing: '处理中',
  completed: '已完成', failed: '失败', cancelled: '已取消',
}
const priorityTypeMap = { low: 'info', normal: '', high: 'warning', urgent: 'danger' }
const priorityLabelMap = { low: '低', normal: '普通', high: '高', urgent: '紧急' }

function formatDate(str) {
  if (!str) return '-'
  return new Date(str).toLocaleString('zh-CN')
}

function shortId(id) {
  if (!id) return '-'
  return String(id).slice(0, 8)
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

function getSmoothProgress(row) {
  const cached = smoothProgressMap.value[row.id]
  if (typeof cached === 'number') {
    return round2(cached)
  }
  return round2(normalizeProgress(row.progress ?? 0))
}

function syncProgressTargets() {
  const aliveIds = new Set(tasks.value.map(item => item.id))
  tasks.value.forEach((item) => {
    const current = smoothProgressMap.value[item.id]
    const target = normalizeProgress(item.progress ?? 0)
    if (typeof current !== 'number') {
      smoothProgressMap.value[item.id] = target
    }
  })

  Object.keys(smoothProgressMap.value).forEach((id) => {
    if (!aliveIds.has(id)) {
      delete smoothProgressMap.value[id]
    }
  })
}

function startSmoothTicker() {
  if (smoothTimer) return
  smoothTimer = setInterval(() => {
    tasks.value.forEach((item) => {
      const id = item.id
      const target = normalizeProgress(item.progress ?? 0)
      const current = normalizeProgress(smoothProgressMap.value[id] ?? target)
      const delta = target - current
      if (Math.abs(delta) < 0.2) {
        smoothProgressMap.value[id] = round2(target)
        return
      }

      // 任务进行中使用较平滑的步进，完成态直接对齐到终值
      if (['completed', 'failed', 'cancelled'].includes(item.status)) {
        smoothProgressMap.value[id] = round2(target)
        return
      }

      const step = Math.max(0.3, Math.abs(delta) * 0.18)
      smoothProgressMap.value[id] = round2(current + Math.sign(delta) * step)
    })
  }, 120)
}

async function loadTasks() {
  loading.value = true
  try {
    const res = await extractionApi.list(query)
    tasks.value = res.data.items
    syncProgressTargets()
    total.value = res.data.pagination.total
  } catch {
    ElMessage.error('加载任务列表失败')
  } finally {
    loading.value = false
  }
}

function resetQuery() {
  query.status = ''
  query.page = 1
  loadTasks()
}

onMounted(() => {
  loadTasks()
  startSmoothTicker()
  // 每 10s 自动刷新正在运行的任务
  timer = setInterval(() => {
    if (tasks.value.some(t => ['pending', 'running', 'processing', 'queued'].includes(t.status))) {
      loadTasks()
    }
  }, 10000)
})

onBeforeUnmount(() => {
  clearInterval(timer)
  clearInterval(smoothTimer)
})
</script>

<style scoped>
.search-card {
  margin-bottom: 16px;
}

.mono {
  font-family: 'JetBrains Mono', monospace;
}

.pagination-wrap {
  margin-top: 16px;
}
</style>
