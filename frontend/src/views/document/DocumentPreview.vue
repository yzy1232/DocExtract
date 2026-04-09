<template>
  <div class="document-preview page-shell" v-loading="loading">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">ONLINE PREVIEW</span>
        <h2 class="page-title">文档在线查看</h2>
        <p class="page-subtitle">{{ displayName }}</p>
      </div>
      <div class="page-actions">
        <el-button :icon="ArrowLeft" @click="router.push('/documents')">返回列表</el-button>
        <el-button :icon="Download" type="primary" :loading="downloading" @click="downloadCurrent">
          下载原文
        </el-button>
      </div>
    </section>

    <el-card shadow="never" class="preview-card">
      <template #header>
        <div class="preview-header">
          <span>预览区域</span>
          <el-tag size="small" type="info">{{ contentType || 'unknown' }}</el-tag>
        </div>
      </template>

      <div v-if="previewMode === 'pdf'" class="preview-frame-wrap">
        <iframe :src="previewUrl" class="preview-frame" title="PDF 预览" />
      </div>

      <div v-else-if="previewMode === 'html'" class="preview-frame-wrap">
        <iframe :src="previewUrl" class="preview-frame" title="HTML 预览" sandbox="" />
      </div>

      <div v-else-if="previewMode === 'image'" class="preview-image-wrap">
        <img :src="previewUrl" class="preview-image" alt="文档预览" />
      </div>

      <pre v-else-if="previewMode === 'text'" class="preview-text">{{ previewText }}</pre>

      <div v-else class="unsupported-wrap">
        <el-empty description="当前格式暂不支持浏览器直接预览" />
        <p class="unsupported-tip">你仍可以下载原文，或查看下方解析文本预览。</p>
      </div>

      <div v-if="parsedPreview" class="parsed-preview-wrap">
        <h4>解析文本预览</h4>
        <pre class="parsed-preview-text">{{ parsedPreview }}</pre>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Download } from '@element-plus/icons-vue'
import { documentApi } from '@/api/index'

const router = useRouter()
const route = useRoute()

const loading = ref(false)
const downloading = ref(false)
const documentInfo = ref({})
const contentType = ref('')
const previewMode = ref('unsupported')
const previewUrl = ref('')
const previewText = ref('')

const displayName = computed(() => {
  return documentInfo.value.display_name || documentInfo.value.name || '文档预览'
})

const parsedPreview = computed(() => {
  return documentInfo.value.parsed_text_preview || ''
})

function resolvePreviewMode(type) {
  const mime = String(type || '').toLowerCase()
  if (mime.includes('text/html') || mime.includes('application/xhtml+xml')) return 'html'
  if (mime.includes('application/pdf')) return 'pdf'
  if (mime.startsWith('image/')) return 'image'
  if (
    mime.startsWith('text/') ||
    mime.includes('json') ||
    mime.includes('xml') ||
    mime.includes('markdown')
  ) {
    return 'text'
  }
  return 'unsupported'
}

function cleanupPreviewUrl() {
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = ''
  }
}

async function loadDocumentInfo() {
  const res = await documentApi.get(route.params.id)
  documentInfo.value = res.data || {}
}

async function loadPreviewBlob() {
  const res = await documentApi.preview(route.params.id)
  const mime = (res.headers?.['content-type'] || '').toLowerCase()
  const blob = res.data instanceof Blob
    ? res.data
    : new Blob([res.data], { type: mime || 'application/octet-stream' })

  contentType.value = mime || blob.type || String(documentInfo.value.mime_type || '').toLowerCase()
  previewMode.value = resolvePreviewMode(contentType.value)

  cleanupPreviewUrl()
  previewUrl.value = URL.createObjectURL(blob)

  if (previewMode.value === 'text') {
    previewText.value = await blob.text()
  } else {
    previewText.value = ''
  }
}

async function loadPreview() {
  loading.value = true
  try {
    await loadDocumentInfo()
    await loadPreviewBlob()
  } catch {
    previewMode.value = 'unsupported'
    previewText.value = ''
    ElMessage.error('加载在线预览失败')
  } finally {
    loading.value = false
  }
}

async function downloadCurrent() {
  downloading.value = true
  try {
    const res = await documentApi.download(route.params.id)
    const blob = res.data
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = displayName.value || 'download'
    document.body.appendChild(a)
    a.click()
    a.remove()
    window.URL.revokeObjectURL(url)
  } catch {
    ElMessage.error('下载失败')
  } finally {
    downloading.value = false
  }
}

onMounted(loadPreview)

onBeforeUnmount(() => {
  cleanupPreviewUrl()
})
</script>

<style scoped>
.preview-card {
  min-height: 520px;
}

.preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.preview-frame-wrap {
  width: 100%;
  height: calc(100vh - 280px);
  min-height: 480px;
}

.preview-frame {
  width: 100%;
  height: 100%;
  border: none;
  border-radius: 14px;
  background: #fff;
}

.preview-image-wrap {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 420px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 14px;
}

.preview-image {
  max-width: 100%;
  max-height: calc(100vh - 320px);
  border-radius: 10px;
  box-shadow: 0 10px 28px rgba(31, 42, 36, 0.15);
}

.preview-text {
  margin: 0;
  padding: 14px;
  min-height: 420px;
  max-height: calc(100vh - 320px);
  overflow: auto;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(37, 64, 52, 0.12);
  border-radius: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.unsupported-wrap {
  padding: 24px 0 6px;
  text-align: center;
}

.unsupported-tip {
  margin: 0;
  color: #64746c;
  font-size: 13px;
}

.parsed-preview-wrap {
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px dashed rgba(37, 64, 52, 0.2);
}

.parsed-preview-wrap h4 {
  margin: 0 0 10px;
  color: #1f2a24;
}

.parsed-preview-text {
  margin: 0;
  padding: 12px;
  max-height: 280px;
  overflow: auto;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(37, 64, 52, 0.1);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 960px) {
  .preview-frame-wrap {
    height: calc(100vh - 340px);
    min-height: 420px;
  }

  .preview-image {
    max-height: calc(100vh - 360px);
  }
}
</style>
