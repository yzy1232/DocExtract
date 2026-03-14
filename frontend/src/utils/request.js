import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

const request = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截器 - 注入 JWT Token，并清理空值查询参数
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    // 过滤掉值为空字符串、null、undefined 的查询参数，避免后端枚举校验 422
    if (config.params) {
      const cleaned = {}
      for (const [k, v] of Object.entries(config.params)) {
        if (v !== '' && v !== null && v !== undefined) {
          cleaned[k] = v
        }
      }
      config.params = cleaned
    }
    // 如果请求数据是 FormData，删除默认 Content-Type，让浏览器/axios 自动设置 boundary
    if (config.data && typeof FormData !== 'undefined' && config.data instanceof FormData) {
      if (config.headers) {
        delete config.headers['Content-Type']
        delete config.headers['content-type']
      }
    }
    return config
  },
  (error) => Promise.reject(error)
)

// 响应拦截器 - 统一错误处理
request.interceptors.response.use(
  (response) => {
    // 如果是二进制下载请求，直接返回原始 response，让调用方处理 blob
    if (response.config && response.config.responseType === 'blob') {
      return response
    }
    const data = response.data
    if (data.code && data.code !== 200) {
      ElMessage.error(data.message || '请求失败')
      return Promise.reject(new Error(data.message))
    }
    return data
  },
  (error) => {
    const status = error.response?.status
    const msg = error.response?.data?.message || error.message

    if (status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('user_info')
      router.push({ name: 'Login' })
      ElMessage.warning('登录已过期，请重新登录')
    } else if (status === 403) {
      ElMessage.error('无权限访问')
    } else if (status === 404) {
      ElMessage.error('资源不存在')
    } else if (status >= 500) {
      ElMessage.error('服务器错误，请稍后重试')
    } else {
      ElMessage.error(msg || '网络错误')
    }
    return Promise.reject(error)
  }
)

export default request
