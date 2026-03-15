<template>
  <div class="template-list page-shell">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">TEMPLATE LIBRARY</span>
        <h2 class="page-title">模板管理</h2>
        <p class="page-subtitle">维护抽取模板、字段结构和发布状态，保证不同文档场景下的输出一致性。</p>
      </div>
      <div class="page-actions">
        <el-button type="primary" :icon="Plus" @click="router.push('/templates/create')">
          新建模板
        </el-button>
      </div>
    </section>

    <el-card shadow="never" class="search-card">
      <el-row :gutter="16" align="middle">
        <el-col :span="8">
          <el-input
            v-model="query.keyword"
            placeholder="搜索模板名称/描述"
            :prefix-icon="Search"
            clearable
            @keyup.enter="loadTemplates"
          />
        </el-col>
        <el-col :span="5">
          <el-select v-model="query.status" placeholder="状态筛选" clearable style="width:100%">
            <el-option label="草稿" value="draft" />
            <el-option label="已发布" value="active" />
            <el-option label="已废弃" value="deprecated" />
          </el-select>
        </el-col>
        <el-col :span="4">
          <el-button type="primary" :icon="Search" @click="loadTemplates">搜索</el-button>
          <el-button @click="resetQuery">重置</el-button>
        </el-col>
        <el-col :span="7" style="text-align:right">
          <el-button
            type="danger"
            plain
            :disabled="selectedIds.length === 0"
            @click="handleBatchDelete"
          >
            批量删除（{{ selectedIds.length }}）
          </el-button>
        </el-col>
      </el-row>
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
        <el-table-column label="版本" width="80" align="center">
          <template #default="{ row }">v{{ row.version }}</template>
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
        <el-table-column label="操作" width="180" align="center">
          <template #default="{ row }">
            <el-button size="small" text type="primary" @click="router.push(`/templates/${row.id}`)">
              详情
            </el-button>
            <el-button size="small" text type="primary" @click="router.push(`/templates/${row.id}/edit`)">
              编辑
            </el-button>
            <el-button size="small" text type="danger" @click="handleDelete(row)">
              删除
            </el-button>
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
import { Plus, Search } from '@element-plus/icons-vue'
import { templateApi } from '@/api/index'

const router = useRouter()
const loading = ref(false)
const templates = ref([])
const total = ref(0)
const selectedRows = ref([])

const query = reactive({ keyword: '', status: '', page: 1, page_size: 10 })

const statusTypeMap = { draft: 'info', active: 'success', deprecated: 'warning', archived: 'danger' }
const statusLabelMap = { draft: '草稿', active: '已发布', deprecated: '已废弃', archived: '已归档' }
const selectedIds = computed(() => selectedRows.value.map(item => item.id))

function formatDate(str) {
  if (!str) return '-'
  return new Date(str).toLocaleString('zh-CN')
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

.pagination-wrap {
  margin-top: 16px;
}
</style>
