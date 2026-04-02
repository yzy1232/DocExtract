<template>
  <div class="usage-guide page-shell">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">PRODUCT GUIDE</span>
        <h2 class="page-title">五步完成一次文档抽取流程</h2>
        <p class="page-subtitle">
          这份页面面向业务同学和管理员，覆盖登录、模板维护、文档上传、任务提取、结果导出的标准操作路径。
        </p>
        <div class="inline-metrics">
          <span class="metric-chip"><strong>1</strong> 先建模板</span>
          <span class="metric-chip"><strong>2</strong> 再传文档</span>
          <span class="metric-chip"><strong>3</strong> 发起提取</span>
        </div>
      </div>
      <div class="guide-hero-side">
        <div class="guide-hero-title">常用入口</div>
        <div class="guide-link-list">
          <button
            v-for="link in quickLinks"
            :key="link.path"
            class="guide-link-btn"
            type="button"
            @click="router.push(link.path)"
          >
            <span>{{ link.label }}</span>
            <small>{{ link.tip }}</small>
          </button>
        </div>
      </div>
    </section>

    <el-row :gutter="18">
      <el-col :lg="15" :md="24">
        <el-card shadow="never">
          <template #header>
            <div class="card-header-row">
              <div>
                <strong>标准操作流程</strong>
                <p>推荐按顺序完成，减少重复返工。</p>
              </div>
            </div>
          </template>

          <div class="step-list">
            <article v-for="step in flowSteps" :key="step.title" class="step-item">
              <span class="step-no">{{ step.no }}</span>
              <div>
                <h4>{{ step.title }}</h4>
                <p>{{ step.desc }}</p>
              </div>
            </article>
          </div>
        </el-card>

        <el-card shadow="never">
          <template #header>
            <div class="card-header-row">
              <div>
                <strong>角色建议</strong>
                <p>按角色分工操作，提取流程会更稳定。</p>
              </div>
            </div>
          </template>

          <div class="role-grid">
            <article v-for="item in roleTips" :key="item.role" class="role-card">
              <h4>{{ item.role }}</h4>
              <p>{{ item.content }}</p>
            </article>
          </div>
        </el-card>
      </el-col>

      <el-col :lg="9" :md="24">
        <el-card shadow="never">
          <template #header>
            <div class="card-header-row">
              <div>
                <strong>排错清单</strong>
                <p>出现问题时优先检查这三项。</p>
              </div>
            </div>
          </template>

          <ul class="check-list">
            <li v-for="item in troubleshootList" :key="item">{{ item }}</li>
          </ul>
        </el-card>

        <el-card shadow="never">
          <template #header>
            <div class="card-header-row">
              <div>
                <strong>常见问题</strong>
                <p>高频问答汇总。</p>
              </div>
            </div>
          </template>

          <el-collapse>
            <el-collapse-item v-for="faq in faqList" :key="faq.q" :title="faq.q" :name="faq.q">
              <p class="faq-answer">{{ faq.a }}</p>
            </el-collapse-item>
          </el-collapse>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'

const router = useRouter()

const quickLinks = [
  { label: '模板管理', path: '/templates', tip: '维护字段结构与版本' },
  { label: '文档管理', path: '/documents', tip: '上传并检查文档状态' },
  { label: '提取任务', path: '/extractions', tip: '查看进度和提取结果' },
  { label: '系统配置', path: '/system', tip: '管理员配置模型与参数' },
]

const flowSteps = [
  { no: '01', title: '登录并确认权限', desc: '使用系统账号登录后，先确认当前账号是否具备模板管理或系统配置权限。' },
  { no: '02', title: '创建或复用模板', desc: '在模板管理中定义字段名称、类型、是否必填与说明，确认模板可用于实际文档。' },
  { no: '03', title: '上传待处理文档', desc: '进入文档管理上传 PDF、DOCX、XLSX 或 TXT，等待文档解析状态变为可用。' },
  { no: '04', title: '发起提取任务', desc: '在提取任务中选择文档和模板，提交后关注实时进度，必要时可重新执行。' },
  { no: '05', title: '查看并导出结果', desc: '在提取结果页核对字段值和置信度，确认无误后导出为 Excel、JSON 或 CSV。' },
]

const roleTips = [
  { role: '业务人员', content: '优先聚焦模板字段定义质量，字段描述越清晰，抽取结果通常越稳定。' },
  { role: '审核人员', content: '重点检查低置信度字段与空值字段，必要时回到模板优化字段说明。' },
  { role: '管理员', content: '定期检查系统配置、模型连通性和任务队列积压情况，避免高峰时段失败重试。' },
]

const troubleshootList = [
  '任务长时间处于排队中：检查 Redis、Celery Worker 与任务队列是否在线。',
  '提取结果为空或异常：确认模板字段描述完整，且文档解析状态为可用。',
  '登录后无系统配置菜单：确认当前账号为管理员角色。',
]

const faqList = [
  {
    q: '上传后为什么不能立刻发起提取？',
    a: '文档会先进入异步解析流程，只有解析完成后才能保证提取质量。建议在文档列表中先确认状态。',
  },
  {
    q: '同一文档可以用多个模板提取吗？',
    a: '可以。你可以基于同一文档创建多个提取任务，对比不同模板下的字段产出效果。',
  },
  {
    q: '如何提高提取准确率？',
    a: '优先优化模板字段说明，避免模糊描述；对低置信度字段进行人工复核并持续迭代模板。',
  },
]
</script>

<style scoped>
.guide-hero-side {
  position: relative;
  z-index: 1;
  width: min(320px, 100%);
  padding: 20px;
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.64);
  border: 1px solid rgba(37, 64, 52, 0.1);
}

.guide-hero-title {
  font-size: 13px;
  letter-spacing: 0.08em;
  color: #1f6f5f;
  font-weight: 700;
}

.guide-link-list {
  margin-top: 12px;
  display: grid;
  gap: 10px;
}

.guide-link-btn {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(37, 64, 52, 0.08);
  background: rgba(255, 255, 255, 0.8);
  color: #1f2a24;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.guide-link-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 26px rgba(62, 53, 39, 0.08);
}

.guide-link-btn span {
  font-size: 14px;
  font-weight: 700;
}

.guide-link-btn small {
  font-size: 12px;
  color: #5f6d65;
}

.step-list {
  display: grid;
  gap: 14px;
}

.step-item {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.62);
  border: 1px solid rgba(37, 64, 52, 0.08);
}

.step-no {
  min-width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
  color: #1f6f5f;
  background: rgba(31, 111, 95, 0.12);
}

.step-item h4 {
  margin: 2px 0 4px;
  font-size: 15px;
  color: #16231d;
}

.step-item p {
  margin: 0;
  font-size: 13px;
  line-height: 1.75;
  color: #606e66;
}

.role-grid {
  display: grid;
  gap: 12px;
}

.role-card {
  padding: 14px;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.58);
  border: 1px solid rgba(37, 64, 52, 0.08);
}

.role-card h4 {
  margin: 0;
  color: #16362d;
}

.role-card p {
  margin: 6px 0 0;
  font-size: 13px;
  line-height: 1.7;
  color: #5f6d65;
}

.check-list {
  margin: 0;
  padding-left: 18px;
  display: grid;
  gap: 10px;
  color: #55635b;
  font-size: 13px;
  line-height: 1.7;
}

.faq-answer {
  margin: 0;
  color: #55635b;
  font-size: 13px;
  line-height: 1.7;
}

@media (max-width: 992px) {
  .guide-hero-side {
    width: 100%;
  }
}
</style>
