<template>
  <div class="template-list page-shell">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">TEMPLATE LIBRARY</span>
        <h2 class="page-title">模板管理</h2>
        <p class="page-subtitle">维护抽取模板、字段结构和发布状态，保证不同文档场景下的输出一致性。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="Upload" :loading="importing" @click="triggerImport">
          上传模板
        </el-button>
        <el-button type="primary" :icon="Plus" @click="router.push('/templates/create')">
          新建模板
        </el-button>
        <input
          ref="importInputRef"
          class="hidden-file-input"
          type="file"
          accept=".xlsx,.csv"
          @change="handleImportFileChange"
        />
      </div>
    </section>

    <el-card shadow="never" class="search-card">
      <div class="ops-toolbar">
        <div class="ops-toolbar__filters">
          <el-input
            v-model="query.keyword"
            placeholder="搜索模板名称/描述"
            :prefix-icon="Search"
            clearable
            @keyup.enter="loadTemplates"
          />
          <el-select v-model="query.status" placeholder="状态筛选" clearable>
            <el-option label="草稿" value="draft" />
            <el-option label="已发布" value="active" />
            <el-option label="已废弃" value="deprecated" />
          </el-select>
        </div>
        <div class="ops-toolbar__actions">
          <el-button type="primary" :icon="Search" @click="loadTemplates">搜索</el-button>
          <el-button @click="resetQuery">重置</el-button>
        </div>
        <div class="ops-toolbar__batch">
          <el-button
            type="danger"
            plain
            :disabled="selectedIds.length === 0"
            @click="handleBatchDelete"
          >
            批量删除（{{ selectedIds.length }}）
          </el-button>
        </div>
      </div>
    </el-card>

    <el-card shadow="never">
      <el-table :data="templates" v-loading="loading" stripe row-key="id" style="width:100%" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="42" />
        <el-table-column prop="name" label="模板名称" min-width="180">
          <template #default="{ row }">
            <el-link type="primary" @click="router.push(`/templates/${row.id}`)">
              {{ row.name }}
            </el-link>
          </template>
        </el-table-column>
        <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
        <el-table-column label="字段数" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" type="info" round>{{ row.field_count ?? 0 }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTypeMap[row.status]" size="small">
              {{ statusLabelMap[row.status] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" width="170">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="320" align="center">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button size="small" text type="primary" @click="router.push(`/templates/${row.id}`)">
                详情
              </el-button>
              <el-button size="small" text type="primary" @click="router.push(`/templates/${row.id}/edit`)">
                编辑
              </el-button>
              <el-dropdown @command="(cmd) => handleDownloadCommand(row, cmd)">
                <el-button size="small" text type="primary">
                  下载
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="xlsx">下载Excel</el-dropdown-item>
                    <el-dropdown-item command="csv">下载CSV</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
              <el-button
                size="small"
                text
                type="primary"
                @click="router.push({ path: '/extractions/create', query: { template_id: row.id } })"
              >
                新建提取
              </el-button>
              <el-button size="small" text type="danger" @click="handleDelete(row)">
                删除
              </el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrap">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          background
          @change="loadTemplates"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search, Upload } from '@element-plus/icons-vue'
import { templateApi } from '@/api/index'
import { formatDateToUTC8 } from '@/utils/datetime'

const router = useRouter()
const loading = ref(false)
const importing = ref(false)
const importInputRef = ref(null)
const templates = ref([])
const total = ref(0)
const selectedRows = ref([])

const query = reactive({ keyword: '', status: '', page: 1, page_size: 10 })

const statusTypeMap = { draft: 'info', active: 'success', deprecated: 'warning', archived: 'danger' }
const statusLabelMap = { draft: '草稿', active: '已发布', deprecated: '已废弃', archived: '已归档' }
const selectedIds = computed(() => selectedRows.value.map(item => item.id))

function formatDate(str) {
  return formatDateToUTC8(str)
}

function triggerImport() {
  if (importing.value) return
  importInputRef.value?.click()
}

async function handleImportFileChange(event) {
  const file = event?.target?.files?.[0]
  if (!file) return

  const lowerName = String(file.name || '').toLowerCase()
  if (!lowerName.endsWith('.xlsx') && !lowerName.endsWith('.csv')) {
    ElMessage.warning('仅支持上传 .xlsx 或 .csv 模板文件')
    event.target.value = ''
    return
  }

  importing.value = true
  try {
    const formData = new FormData()
    formData.append('file', file)
    const res = await templateApi.importFile(formData)
    ElMessage.success(`模板上传成功：${res.data?.name || file.name}`)
    query.page = 1
    await loadTemplates()
  } catch {
    ElMessage.error('模板上传失败')
  } finally {
    importing.value = false
    event.target.value = ''
  }
}

async function loadTemplates() {
  loading.value = true
  try {
    const res = await templateApi.list({
      keyword: query.keyword,
      status: query.status,
      page: query.page,
      page_size: query.page_size,
    })
    templates.value = res.data.items
    total.value = res.data.pagination.total
  } catch {
    ElMessage.error('加载模板列表失败')
  } finally {
    loading.value = false
  }
}

function handleSelectionChange(rows) {
  selectedRows.value = rows
}

function resetQuery() {
  query.keyword = ''
  query.status = ''
  query.page = 1
  loadTemplates()
}

async function handleDelete(row) {
  await ElMessageBox.confirm(`确认删除模板「${row.name}」？`, '删除确认', { type: 'warning' })
  try {
    await templateApi.delete(row.id)
    ElMessage.success('删除成功')
    loadTemplates()
  } catch {
    ElMessage.error('删除失败')
  }
}

function resolveDownloadFilename(headers, fallbackName) {
  const contentDisposition = headers?.['content-disposition'] || ''
  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1])
    } catch {
      // ignore decode error and continue fallback
    }
  }

  const plainMatch = contentDisposition.match(/filename="?([^";]+)"?/i)
  if (plainMatch?.[1]) {
    return plainMatch[1]
  }
  return fallbackName
}

async function downloadTemplateFile(row, format = 'xlsx') {
  try {
    const res = await templateApi.download(row.id, format)
    const contentType = res.headers?.['content-type'] || (format === 'csv'
      ? 'text/csv'
      : 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    const blob = res.data instanceof Blob ? res.data : new Blob([res.data], { type: contentType })
    if (!blob || blob.size === 0) {
      ElMessage.error('下载失败：文件为空')
      return
    }

    const fallbackName = `${row.name || 'template'}.${format}`
    const filename = resolveDownloadFilename(res.headers, fallbackName)

    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('下载模板失败')
  }
}

function handleDownloadCommand(row, command) {
  const format = command === 'csv' ? 'csv' : 'xlsx'
  downloadTemplateFile(row, format)
}

async function handleBatchDelete() {
  if (selectedIds.value.length === 0) return
  await ElMessageBox.confirm(`确认删除选中的 ${selectedIds.value.length} 个模板？`, '批量删除确认', { type: 'warning' })

  const results = await Promise.allSettled(selectedIds.value.map(id => templateApi.delete(id)))
  const successCount = results.filter(item => item.status === 'fulfilled').length

  if (successCount > 0) {
    ElMessage.success(`已删除 ${successCount} 个模板`)
    loadTemplates()
  }
  if (successCount < selectedIds.value.length) {
    ElMessage.warning(`有 ${selectedIds.value.length - successCount} 个模板删除失败`)
  }
}

onMounted(loadTemplates)
</script>

<style scoped>
.search-card {
  margin-bottom: 16px;
}

.hidden-file-input {
  display: none;
}

.pagination-wrap {
  margin-top: 16px;
}
</style>
