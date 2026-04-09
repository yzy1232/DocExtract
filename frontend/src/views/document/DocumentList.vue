<template>
  <div class="document-list page-shell">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">DOCUMENT PIPELINE</span>
        <h2 class="page-title">文档管理</h2>
        <p class="page-subtitle">集中查看文件格式、处理状态和下载动作，把原始文档输入源维护得更干净。</p>
      </div>
      <div class="page-actions">
        <el-button type="primary" :icon="Upload" @click="router.push('/documents/upload')">
          上传文档
        </el-button>
      </div>
    </section>

    <el-card shadow="never" class="search-card">
      <div class="ops-toolbar">
        <div class="ops-toolbar__filters">
          <el-input
            v-model="query.keyword"
            placeholder="搜索文档名称"
            :prefix-icon="Search"
            clearable
            @keyup.enter="loadDocuments"
          />
          <el-select v-model="query.status" placeholder="处理状态" clearable>
            <el-option label="已上传" value="uploaded" />
            <el-option label="处理中" value="processing" />
            <el-option label="已完成" value="processed" />
            <el-option label="解析失败" value="failed" />
          </el-select>
        </div>
        <div class="ops-toolbar__actions">
          <el-button type="primary" :icon="Search" @click="loadDocuments">搜索</el-button>
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
      <el-table :data="documents" v-loading="loading" stripe row-key="id" @selection-change="handleSelectionChange">
        <el-table-column type="selection" width="42" />
        <el-table-column prop="name" label="文件名" min-width="200">
          <template #default="{ row }">
            <div class="filename-cell">
              <el-icon class="file-icon"><component :is="fileIcon(row.format)" /></el-icon>
              <span>{{ row.display_name || row.name }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="格式" width="90" align="center">
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.format?.toUpperCase() }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="大小" width="100" align="center">
          <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
        </el-table-column>
        <el-table-column label="页数" width="70" align="center">
          <template #default="{ row }">{{ row.page_count ?? '-' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="statusTypeMap[row.status]" size="small">
              {{ statusLabelMap[row.status] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="上传时间" width="170">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="300" align="center">
          <template #default="{ row }">
            <div class="table-actions">
              <el-button
                size="small"
                text
                type="primary"
                @click="createExtraction(row.id)"
              >
                提取
              </el-button>
              <el-button
                size="small"
                text
                type="primary"
                :disabled="row.status !== 'processed'"
                @click="createTemplateFromDoc(row)"
              >
                提取模板
              </el-button>
              <el-button size="small" text type="primary" @click="previewDoc(row)">
                在线查看
              </el-button>
              <el-button size="small" text type="primary" @click="downloadDoc(row)">
                下载
              </el-button>
              <el-button size="small" text type="danger" @click="handleDelete(row)">
                删除
              </el-button>
            </div>
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
          @change="loadDocuments"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Upload, Search, Document, Film, Picture } from '@element-plus/icons-vue'
import { documentApi } from '@/api/index'
import { formatDateToUTC8 } from '@/utils/datetime'

const router = useRouter()
const loading = ref(false)
const documents = ref([])
const total = ref(0)
const selectedRows = ref([])

const query = reactive({ keyword: '', status: '', page: 1, page_size: 10 })

const statusTypeMap = {
  uploading: 'info', uploaded: 'info', processing: 'warning',
  processed: 'success', failed: 'danger', deleted: 'info',
}
const statusLabelMap = {
  uploading: '上传中', uploaded: '已上传', processing: '处理中',
  processed: '已完成', failed: '失败', deleted: '已删除',
}

const selectedIds = computed(() => selectedRows.value.map(item => item.id))

function fileIcon(fileType) {
  if (!fileType) return 'Document'
  if (fileType.includes('image')) return 'Picture'
  if (fileType.includes('video')) return 'Film'
  return 'Document'
}

function formatSize(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

function formatDate(str) {
  return formatDateToUTC8(str)
}

async function loadDocuments() {
  loading.value = true
  try {
    const res = await documentApi.list(query)
    documents.value = res.data.items
    total.value = res.data.pagination.total
  } catch {
    ElMessage.error('加载文档列表失败')
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
  loadDocuments()
}

function createExtraction(docId) {
  router.push({ path: '/extractions/create', query: { document_id: docId } })
}

function createTemplateFromDoc(row) {
  if (row.status !== 'processed') {
    ElMessage.warning('请先等待文档解析完成')
    return
  }
  router.push({ path: '/templates/create', query: { document_id: row.id } })
}

function previewDoc(row) {
  router.push(`/documents/${row.id}/preview`)
}

async function downloadDoc(row) {
  try {
    const res = await documentApi.download(row.id)
    const blob = res.data
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = row.display_name || row.name || 'download'
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('下载失败')
  }
}

async function handleDelete(row) {
  const filename = row.display_name || row.name || row.original_filename || '该文档'
  await ElMessageBox.confirm(`确认删除文档「${filename}」？`, '删除确认', { type: 'warning' })
  try {
    await documentApi.delete(row.id)
    ElMessage.success('删除成功')
    loadDocuments()
  } catch {
    ElMessage.error('删除失败')
  }
}

async function handleBatchDelete() {
  if (selectedIds.value.length === 0) return
  await ElMessageBox.confirm(`确认删除选中的 ${selectedIds.value.length} 个文档？`, '批量删除确认', { type: 'warning' })

  const results = await Promise.allSettled(selectedIds.value.map(id => documentApi.delete(id)))
  const successCount = results.filter(item => item.status === 'fulfilled').length

  if (successCount > 0) {
    ElMessage.success(`已删除 ${successCount} 个文档`)
    loadDocuments()
  }
  if (successCount < selectedIds.value.length) {
    ElMessage.warning(`有 ${selectedIds.value.length - successCount} 个文档删除失败`)
  }
}

onMounted(loadDocuments)
</script>

<style scoped>
.search-card {
  margin-bottom: 16px;
}

.filename-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-icon {
  color: #1f6f5f;
  font-size: 18px;
}

.pagination-wrap {
  margin-top: 16px;
}
</style>
