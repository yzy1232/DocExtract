<template>
  <div class="dashboard">
    <h2 class="page-title">工作台</h2>

    <!-- 统计卡片 -->
    <el-row :gutter="20" class="stat-cards">
      <el-col :span="6" v-for="card in statCards" :key="card.label">
        <el-card class="stat-card" shadow="hover">
          <div class="stat-content">
            <div class="stat-icon" :style="{ background: card.color }">
              <el-icon :size="28" style="color: white"><component :is="card.icon" /></el-icon>
            </div>
            <div class="stat-info">
              <div class="stat-value">{{ stats[card.key] ?? '--' }}</div>
              <div class="stat-label">{{ card.label }}</div>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 快捷操作 -->
    <el-row :gutter="20" class="quick-actions">
      <el-col :span="12">
        <el-card header="快捷操作" shadow="never">
          <div class="action-grid">
            <div
              v-for="action in quickActions"
              :key="action.label"
              class="action-item"
              @click="router.push(action.to)"
            >
              <el-icon :size="32" :style="{ color: action.color }">
                <component :is="action.icon" />
              </el-icon>
              <span>{{ action.label }}</span>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="12">
        <el-card header="系统状态" shadow="never">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="API服务">
              <el-tag type="success" size="small">正常</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="数据库">
              <el-tag :type="health.database === 'ok' ? 'success' : 'danger'" size="small">
                {{ health.database === 'ok' ? '正常' : '异常' }}
              </el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="缓存服务">
              <el-tag :type="health.cache === 'ok' ? 'success' : 'danger'" size="small">
                {{ health.cache === 'ok' ? '正常' : '异常' }}
              </el-tag>
            </el-descriptions-item>
          </el-descriptions>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { systemApi } from '@/api/index'

const router = useRouter()
const stats = ref({})
const health = ref({ database: 'unknown', cache: 'unknown' })

const statCards = [
  { key: 'total_documents', label: '文档总数', icon: 'Document', color: '#60a5fa' },
  { key: 'total_templates', label: '模板总数', icon: 'Collection', color: '#34d399' },
  { key: 'total_tasks', label: '任务总数', icon: 'MagicStick', color: '#a78bfa' },
  { key: 'pending_tasks', label: '待处理任务', icon: 'Clock', color: '#fb923c' },
]

const quickActions = [
  { label: '上传文档', icon: 'Upload', color: '#60a5fa', to: '/documents/upload' },
  { label: '创建模板', icon: 'Plus', color: '#34d399', to: '/templates/create' },
  { label: '新建提取', icon: 'MagicStick', color: '#a78bfa', to: '/extractions/create' },
  { label: '查看结果', icon: 'DataAnalysis', color: '#fb923c', to: '/extractions' },
]

onMounted(async () => {
  try {
    const [statsRes, healthRes] = await Promise.all([
      systemApi.stats(),
      systemApi.health(),
    ])
    stats.value = statsRes.data
    health.value = healthRes.data
  } catch {
    // 忽略
  }
})
</script>

<style scoped>
.page-title {
  font-size: 22px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 24px;
}

.stat-cards {
  margin-bottom: 20px;
}

.stat-card {
  border-radius: 12px;
}

.stat-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.stat-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #1e293b;
  line-height: 1;
}

.stat-label {
  font-size: 13px;
  color: #64748b;
  margin-top: 4px;
}

.quick-actions {
  margin-top: 20px;
}

.action-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 16px;
}

.action-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 20px;
  border-radius: 10px;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.2s;
  font-size: 13px;
  color: #475569;
}

.action-item:hover {
  background: #e0f2fe;
  transform: translateY(-2px);
}
</style>
