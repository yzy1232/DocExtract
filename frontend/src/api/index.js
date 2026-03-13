import request from '@/utils/request'

export const templateApi = {
  // 创建模板
  create: (data) => request.post('/templates', data),

  // 更新模板
  update: (id, data) => request.put(`/templates/${id}`, data),

  // 获取模板列表
  list: (params) => request.get('/templates', { params }),

  // 获取模板详情
  get: (id) => request.get(`/templates/${id}`),

  // 删除模板
  delete: (id) => request.delete(`/templates/${id}`),

  // 添加字段
  addField: (templateId, data) => request.post(`/templates/${templateId}/fields`, data),

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

  // 获取提取结果
  getResults: (id) => request.get(`/extractions/${id}/results`),

  // 验证结果
  validate: (id, data) => request.put(`/extractions/${id}/validation`, data),

  // 导出结果
  export: (data) => request.post('/extractions/export', data),
}

export const systemApi = {
  health: () => request.get('/system/health'),
  stats: () => request.get('/system/stats'),

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
}
