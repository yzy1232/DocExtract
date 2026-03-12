<template>
  <div class="document-upload page-shell">
    <section class="page-hero">
      <div class="page-heading">
        <span class="page-kicker">UPLOAD STATION</span>
        <h2 class="page-title">上传文档</h2>
        <p class="page-subtitle">支持拖拽上传和多文件队列管理，上传后可以直接接入解析和抽取流程。</p>
      </div>
      <div class="page-actions">
        <el-button :icon="ArrowLeft" @click="router.push('/documents')">返回列表</el-button>
      </div>
    </section>

    <el-row :gutter="24">
      <el-col :span="16">
        <el-card header="选择文件" shadow="never">
          <el-upload
            ref="uploadRef"
            drag
            multiple
            :auto-upload="false"
            :file-list="fileList"
            :accept="acceptTypes"
            :before-upload="beforeUpload"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">
              拖拽文件到此处，或<em>点击选择文件</em>
            </div>
            <template #tip>
              <div class="upload-tip">
                支持格式：PDF、Word(.docx)、Excel(.xlsx)、文本(.txt)，单文件不超过 100MB
              </div>
            </template>
          </el-upload>
        </el-card>

        <!-- 上传进度 -->
        <el-card class="mt-16" header="上传进度" shadow="never" v-if="uploadList.length > 0">
          <div class="upload-progress-list">
            <div
              v-for="item in uploadList"
              :key="item.uid"
              class="progress-item"
            >
              <div class="progress-info">
                <el-icon><Document /></el-icon>
                <span class="filename">{{ item.name }}</span>
                <el-tag
                  :type="item.status === 'success' ? 'success' : item.status === 'error' ? 'danger' : 'warning'"
                  size="small"
                >
                  {{ item.status === 'success' ? '上传成功' : item.status === 'error' ? '上传失败' : '上传中' }}
                </el-tag>
              </div>
              <el-progress
                :percentage="item.percent"
                :status="item.status === 'success' ? 'success' : item.status === 'error' ? 'exception' : ''"
                :stroke-width="6"
                style="margin-top:6px"
              />
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :span="8">
        <el-card header="上传配置" shadow="never">
          <el-form label-width="90px">
            <el-form-item label="解析方式">
              <el-radio-group v-model="uploadConfig.parse_immediately">
                <el-radio :value="true">立即解析</el-radio>
                <el-radio :value="false">仅上传</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-form>

          <el-divider />

          <div style="display:flex;flex-direction:column;gap:12px">
            <el-button
              type="primary"
              style="width:100%"
              :loading="uploading"
              :disabled="fileList.length === 0"
              @click="startUpload"
            >
              开始上传（{{ fileList.length }} 个文件）
            </el-button>
            <el-button style="width:100%;margin-left:0" @click="router.push('/documents')">
              取消
            </el-button>
          </div>
        </el-card>

        <el-card class="mt-16" header="注意事项" shadow="never">
          <ul class="tips-list">
            <li>文件名请避免特殊字符</li>
            <li>PDF 文件支持文字版和扫描版</li>
            <li>扫描版 PDF 将自动 OCR 识别</li>
            <li>上传中请勿关闭页面</li>
          </ul>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, UploadFilled, Document } from '@element-plus/icons-vue'
import { documentApi } from '@/api/index'

const router = useRouter()
const uploadRef = ref(null)
const fileList = ref([])
const uploadList = ref([])
const uploading = ref(false)

const uploadConfig = reactive({
  parse_immediately: true,
})

const acceptTypes = '.pdf,.docx,.xlsx,.txt,.jpg,.jpeg,.png'

function beforeUpload(file) {
  const maxSize = 100 * 1024 * 1024
  if (file.size > maxSize) {
    ElMessage.warning(`文件 ${file.name} 超过 100MB 限制`)
    return false
  }
  return true
}

function handleFileChange(file, files) {
  fileList.value = files
}

function handleFileRemove(file, files) {
  fileList.value = files
}

async function startUpload() {
  if (fileList.value.length === 0) return

  uploading.value = true
  uploadList.value = fileList.value.map(f => ({
    uid: f.uid,
    name: f.name,
    percent: 0,
    status: 'uploading',
  }))

  const results = []
  for (const file of fileList.value) {
    const progressItem = uploadList.value.find(u => u.uid === file.uid)
    try {
      await documentApi.upload(file.raw, (p) => {
        if (progressItem) progressItem.percent = p
      })
      if (progressItem) {
        progressItem.percent = 100
        progressItem.status = 'success'
      }
      results.push({ name: file.name, success: true })
    } catch (e) {
      if (progressItem) progressItem.status = 'error'
      results.push({ name: file.name, success: false })
    }
  }

  uploading.value = false
  const successCount = results.filter(r => r.success).length
  if (successCount > 0) {
    ElMessage.success(`成功上传 ${successCount} / ${results.length} 个文件`)
  }
  if (successCount === results.length) {
    setTimeout(() => router.push('/documents'), 1500)
  }
}
</script>

<style scoped>
.upload-tip {
  font-size: 12px;
  color: #94a3b8;
  margin-top: 8px;
  text-align: center;
}

.mt-16 {
  margin-top: 16px;
}

.upload-progress-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.progress-item {
  padding: 10px;
  background: rgba(255, 255, 255, 0.56);
  border-radius: 14px;
}

.progress-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filename {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tips-list {
  padding-left: 18px;
  margin: 0;
  font-size: 13px;
  color: #64746c;
  line-height: 2;
}
</style>
