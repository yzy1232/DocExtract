<template>
  <div class="dashboard page-shell">
    <section class="page-hero dashboard-hero">
      <div class="page-heading">
        <span class="page-kicker">CONTROL CENTER</span>
        <h2 class="page-title">把文档流转压缩到一个工作台里</h2>
        <p class="page-subtitle">
          这里集中展示模板、文档和任务的当前节奏，你可以从总览直接跳转到上传、建模和结果追踪。
        </p>
        <div class="inline-metrics">
          <span class="metric-chip"><strong>{{ stats.total_documents ?? '--' }}</strong> 文档库存</span>
          <span class="metric-chip"><strong>{{ stats.total_templates ?? '--' }}</strong> 活跃模板</span>
          <span class="metric-chip"><strong>{{ stats.pending_tasks ?? '--' }}</strong> 待处理任务</span>
        </div>
      </div>

      <div class="hero-status-card">
        <div class="status-label">系统状态</div>
        <div class="status-main">{{ overallHealthLabel }}</div>
        <div class="status-grid">
          <div>
            <span>数据库</span>
            <strong>{{ health.database === 'ok' ? '在线' : '异常' }}</strong>
          </div>
          <div>
            <span>缓存服务</span>
            <strong>{{ health.cache === 'ok' ? '在线' : '异常' }}</strong>
          </div>
        </div>
      </div>
    </section>

    <section class="dashboard-stats">
      <article v-for="card in statCards" :key="card.label" class="stat-panel">
        <div class="stat-panel-icon" :style="{ background: card.tint }">
          <el-icon :size="26" :style="{ color: card.color }"><component :is="card.icon" /></el-icon>
        </div>
        <div>
          <div class="stat-panel-value">{{ stats[card.key] ?? '--' }}</div>
          <div class="stat-panel-label">{{ card.label }}</div>
        </div>
      </article>
    </section>

    <el-row :gutter="18">
      <el-col :lg="14" :md="24">
        <el-card shadow="never">
          <template #header>
            <div class="card-header-row">
              <div>
                <strong>快捷操作</strong>
                <p>从这里直接进入最高频动作。</p>
              </div>
            </div>
          </template>

          <div class="action-grid">
            <button
              v-for="action in quickActions"
              :key="action.label"
              type="button"
              class="action-item"
              @click="router.push(action.to)"
            >
              <span class="action-icon" :style="{ background: action.tint }">
                <el-icon :size="24" :style="{ color: action.color }">
                  <component :is="action.icon" />
                </el-icon>
              </span>
              <strong>{{ action.label }}</strong>
              <span>{{ action.description }}</span>
            </button>
          </div>
        </el-card>
      </el-col>

      <el-col :lg="10" :md="24">
        <el-card shadow="never">
          <template #header>
            <div class="card-header-row">
              <div>
                <strong>运行诊断</strong>
                <p>基础依赖可用性与处理链路状态。</p>
              </div>
            </div>
          </template>

          <div class="health-list">
            <div class="health-item">
              <span>API 服务</span>
              <el-tag type="success">正常</el-tag>
            </div>
            <div class="health-item">
              <span>数据库</span>
              <el-tag :type="health.database === 'ok' ? 'success' : 'danger'">
                {{ health.database === 'ok' ? '正常' : '异常' }}
              </el-tag>
            </div>
            <div class="health-item">
              <span>缓存服务</span>
              <el-tag :type="health.cache === 'ok' ? 'success' : 'danger'">
                {{ health.cache === 'ok' ? '正常' : '异常' }}
              </el-tag>
            </div>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { systemApi } from '@/api/index'

const router = useRouter()
const stats = ref({})
const health = ref({ database: 'unknown', cache: 'unknown' })

const statCards = [
  { key: 'total_documents', label: '文档总数', icon: 'Document', color: '#1f6f5f', tint: 'rgba(31, 111, 95, 0.12)' },
  { key: 'total_templates', label: '模板总数', icon: 'Collection', color: '#d1893f', tint: 'rgba(209, 137, 63, 0.14)' },
  { key: 'total_tasks', label: '任务总数', icon: 'MagicStick', color: '#46796c', tint: 'rgba(70, 121, 108, 0.14)' },
  { key: 'pending_tasks', label: '待处理任务', icon: 'Clock', color: '#b86a3b', tint: 'rgba(184, 106, 59, 0.16)' },
]

const quickActions = [
  { label: '上传文档', icon: 'Upload', color: '#1f6f5f', tint: 'rgba(31, 111, 95, 0.12)', to: '/documents/upload', description: '新增文件并进入解析流程' },
  { label: '创建模板', icon: 'Plus', color: '#d1893f', tint: 'rgba(209, 137, 63, 0.14)', to: '/templates/create', description: '配置字段结构和提示词' },
  { label: '新建提取', icon: 'MagicStick', color: '#46796c', tint: 'rgba(70, 121, 108, 0.14)', to: '/extractions/create', description: '为文档发起新的抽取任务' },
  { label: '查看结果', icon: 'DataAnalysis', color: '#b86a3b', tint: 'rgba(184, 106, 59, 0.16)', to: '/extractions', description: '检查任务进度和结果产出' },
  { label: '使用文档', icon: 'Reading', color: '#28596d', tint: 'rgba(40, 89, 109, 0.14)', to: '/guide', description: '查看功能说明与操作指南' },
]

const overallHealthLabel = computed(() => {
  if (health.value.database === 'ok' && health.value.cache === 'ok') {
    return '稳定运行'
  }
  return '需要检查'
})

onMounted(async () => {
  try {
    const [statsRes, healthRes] = await Promise.all([systemApi.stats(), systemApi.health()])
    stats.value = statsRes.data
    health.value = healthRes.data
  } catch (error) {
    console.debug('Dashboard 数据加载失败', error?.message)
  }
})
</script>

<style scoped>
.dashboard-hero {
  align-items: stretch;
}

.hero-status-card {
  width: min(320px, 100%);
  padding: 22px;
  border-radius: 24px;
  background: linear-gradient(180deg, rgba(21, 63, 54, 0.96), rgba(14, 39, 34, 0.94));
  color: #f9f3e7;
  box-shadow: 0 18px 40px rgba(20, 43, 38, 0.22);
}

.status-label {
  font-size: 12px;
  letter-spacing: 0.12em;
  color: rgba(249, 243, 231, 0.6);
}

.status-main {
  margin-top: 8px;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.04em;
}

.status-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
  margin-top: 22px;
}

.status-grid div {
  padding: 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.08);
}

.status-grid span {
  display: block;
  margin-bottom: 8px;
  font-size: 12px;
  color: rgba(249, 243, 231, 0.64);
}

.status-grid strong {
  font-size: 16px;
}

.dashboard-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 18px;
}

.stat-panel {
  display: flex;
  gap: 16px;
  align-items: center;
  padding: 22px;
  border-radius: 24px;
  background: rgba(255, 252, 247, 0.84);
  border: 1px solid rgba(37, 64, 52, 0.12);
  box-shadow: 0 14px 36px rgba(62, 53, 39, 0.08);
}

.stat-panel-icon {
  width: 56px;
  height: 56px;
  display: grid;
  place-items: center;
  border-radius: 18px;
}

.stat-panel-value {
  font-size: 30px;
  font-weight: 700;
  color: #14201b;
  line-height: 1;
}

.stat-panel-label {
  margin-top: 6px;
  font-size: 13px;
  color: #6a756f;
}

.card-header-row {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.card-header-row strong {
  display: block;
  font-size: 16px;
  color: #14201b;
}

.card-header-row p {
  margin: 6px 0 0;
  color: #6a756f;
  font-size: 13px;
}

.action-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.action-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
  padding: 20px;
  border-radius: 22px;
  border: 1px solid rgba(37, 64, 52, 0.08);
  background: rgba(255, 255, 255, 0.58);
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
  text-align: left;
}

.action-item:hover {
  transform: translateY(-4px);
  box-shadow: 0 16px 34px rgba(62, 53, 39, 0.1);
  border-color: rgba(31, 111, 95, 0.18);
}

.action-item strong {
  font-size: 15px;
  color: #14201b;
}

.action-item span {
  font-size: 13px;
  line-height: 1.7;
  color: #68746d;
}

.action-icon {
  width: 48px;
  height: 48px;
  display: grid;
  place-items: center;
  border-radius: 16px;
}

.health-list {
  display: grid;
  gap: 14px;
}

.health-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.52);
}

@media (max-width: 1080px) {
  .dashboard-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .dashboard-stats,
  .action-grid,
  .status-grid {
    grid-template-columns: 1fr;
  }
}
</style>
