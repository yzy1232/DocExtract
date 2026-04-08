import request from '@/utils/request'

export const templateApi = {
  // 创建模板
  create: (data) => request.post('/templates', data),

  // 上传模板文件（Excel/CSV）
  importFile: (formData) =>
    request.post('/templates/import', formData, {
      timeout: 120000,
    }),

  // 更新模板
  update: (id, data) => request.put(`/templates/${id}`, data),

  // 获取模板列表
  list: (params) => request.get('/templates', { params }),

  // 获取模板详情
  get: (id) => request.get(`/templates/${id}`),

  // 下载模板文件（Excel/CSV）
  download: (id, format = 'xlsx') =>
    request.get(`/templates/${id}/download`, {
      params: { format },
      responseType: 'blob',
      timeout: 120000,
    }),

  // 删除模板
  delete: (id) => request.delete(`/templates/${id}`),

  // 添加字段
  addField: (templateId, data) => request.post(`/templates/${templateId}/fields`, data),

  // 从文档自动生成模板建议
  inferFromDocument: (data) => request.post('/templates/infer-from-document', data, { timeout: 300000 }),

  // 从文档自动生成模板建议（流式，逐chunk返回）
  inferFromDocumentStream: async (data, handlers = {}) => {
    const token = localStorage.getItem('access_token')
    const inactivityTimeoutMs = Number(handlers.inactivityTimeoutMs || 45000)
    const controller = new AbortController()
    let timeoutId = null

    const resetInactivityTimer = () => {
      if (timeoutId) {
        clearTimeout(timeoutId)
      }
      timeoutId = setTimeout(() => {
        controller.abort('stream-inactivity-timeout')
      }, inactivityTimeoutMs)
    }

    resetInactivityTimer()

    const response = await fetch('/api/v1/templates/infer-from-document/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify(data),
      signal: controller.signal,
    })

    try {
      if (!response.ok) {
        let errText = ''
        try {
          errText = await response.text()
        } catch {
          errText = ''
        }
        throw new Error(errText || `HTTP ${response.status}`)
      }

      if (!response.body) {
        throw new Error('流式响应为空')
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''
      let finalData = null

      while (true) {
        const { value, done } = await reader.read()
        if (done) break

        resetInactivityTimer()
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          const raw = line.trim()
          if (!raw) continue

          let event
          try {
            event = JSON.parse(raw)
          } catch {
            continue
          }

          // 每收到一条事件都重置无消息超时计时器。
          resetInactivityTimer()

          if (event.type === 'progress' && handlers.onProgress) {
            handlers.onProgress(event.data)
          } else if (event.type === 'final') {
            finalData = event.data
            if (handlers.onFinal) {
              handlers.onFinal(event.data)
            }
          } else if (event.type === 'error') {
            throw new Error(event.data?.message || '自动生成失败')
          }
        }
      }

      if (!finalData) {
        throw new Error('未收到最终结果')
      }

      return { data: finalData }
    } catch (error) {
      if (error?.name === 'AbortError') {
        const timeoutError = new Error(`流式超时：${inactivityTimeoutMs / 1000}秒内未收到新进度`)
        timeoutError.code = 'INFER_STREAM_TIMEOUT'
        if (handlers.onTimeout) {
          handlers.onTimeout(timeoutError)
        }
        throw timeoutError
      }
      throw error
    } finally {
      if (timeoutId) {
        clearTimeout(timeoutId)
      }
    }
  },

  // 获取分类列表
  listCategories: () => request.get('/templates/categories/list'),

  // 创建分类
  createCategory: (data) => request.post('/templates/categories', data),
}

export const documentApi = {
  // 上传文档
  upload: (formData, onProgress) =>
    request.post('/documents/upload', formData, {
      onUploadProgress: (e) => {
        if (onProgress && e.total) {
          onProgress(Math.round((e.loaded * 100) / e.total))
        }
      },
    }),

  // 批量上传
  batchUpload: (formData) =>
    request.post('/documents/batch-upload', formData),

  // 文档列表
  list: (params) => request.get('/documents', { params }),

  // 文档详情
  get: (id) => request.get(`/documents/${id}`),

  // 文档状态
  getStatus: (id) => request.get(`/documents/${id}/status`),

  // 获取下载URL
  getDownloadUrl: (id) => request.get(`/documents/${id}/download-url`),

  // 通过后端代理下载文件（返回 blob）
  download: (id) => request.get(`/documents/${id}/download`, { responseType: 'blob' }),

  // 删除文档
  delete: (id) => request.delete(`/documents/${id}`),
}

export const extractionApi = {
  // 创建提取任务
  create: (data) => request.post('/extractions', data),

  // 批量提取
  batchCreate: (data) => request.post('/extractions/batch', data),

  // 任务列表
  list: (params) => request.get('/extractions', { params }),

  // 任务详情
  get: (id) => request.get(`/extractions/${id}`),

  // 重启失败任务
  restart: (id) => request.post(`/extractions/${id}/restart`),

  // 删除任务（待处理/排队中会执行取消）
  delete: (id) => request.delete(`/extractions/${id}`),

  // 批量重启失败任务
  batchRestart: (taskIds) => request.post('/extractions/batch-restart', { task_ids: taskIds }),

  // 批量删除任务（待处理/排队中会执行取消）
  batchDelete: (taskIds) => request.post('/extractions/batch-delete', { task_ids: taskIds }),

  // 获取提取结果
  getResults: (id, params) => request.get(`/extractions/${id}/results`, { params }),

  // 验证结果
  validate: (id, data) => request.put(`/extractions/${id}/validation`, data),

  // 导出结果
  export: (data) => request.post('/extractions/export', data, { timeout: 180000 }),

  // 下载导出文件（通过后端代理，避免预签名URL跨主机签名问题）
  downloadExport: (objectKey) =>
    request.get('/extractions/exports/download', {
      params: { object_key: objectKey },
      responseType: 'blob',
      timeout: 180000,
    }),
}

export const systemApi = {
  health: () => request.get('/system/health'),
  stats: () => request.get('/system/stats'),
  disasterCheck: () => request.get('/system/disaster-check'),
  disasterRepair: (data) => request.post('/system/disaster-repair', data, { timeout: 180000 }),
  publicDisasterCheck: () => request.get('/system/public-disaster-check'),
  publicDisasterRepair: (data) =>
    request.post('/system/public-disaster-repair', data, {
      timeout: 180000,
    }),
  listLLMOptions: () => request.get('/system/llm-options'),

  // LLM 配置 CRUD
  listLLMConfigs: () => request.get('/system/llm-configs'),
  createLLMConfig: (data) => request.post('/system/llm-configs', data),
  updateLLMConfig: (id, data) => request.put(`/system/llm-configs/${id}`, data),
  deleteLLMConfig: (id) => request.delete(`/system/llm-configs/${id}`),
  testLLMConfig: (id) => request.post(`/system/llm-configs/${id}/test`),
  // 系统配置
  listSystemConfigs: () => request.get('/system/configs'),
  getSystemConfig: (key) => request.get(`/system/configs/${key}`),
  putSystemConfig: (key, data) => request.put(`/system/configs/${key}`, data),

  // 管理员账号与权限
  listRoles: () => request.get('/system/roles'),
  listUsers: (params) => request.get('/system/users', { params }),
  createUser: (data) => request.post('/system/users', data),
  updateUser: (id, data) => request.put(`/system/users/${id}`, data),
  deleteUser: (id) => request.delete(`/system/users/${id}`),
}
