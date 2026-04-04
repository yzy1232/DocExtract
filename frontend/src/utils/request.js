import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

const SERVICE_UNAVAILABLE_REDIRECT_COOLDOWN_MS = 8000
let serviceUnavailableRedirectInFlight = false
let lastServiceUnavailableRedirectAt = 0

function getUnavailableStateFromHealth(healthData) {
  const services = []
  let byCriticalFallback = false

  if (healthData?.database && healthData.database !== 'ok') {
    services.push('database')
  }
  if (healthData?.cache && healthData.cache !== 'ok') {
    services.push('redis')
  }

  // 在部分故障场景下（例如删库后连接仍可建立、Redis被改为从库），
  // health 的 database/cache 仍可能为 ok，但 disaster.has_critical 为 true。
  if (!services.length && healthData?.disaster?.has_critical) {
    services.push('database', 'redis')
    byCriticalFallback = true
  }

  return {
    services: Array.from(new Set(services)),
    byCriticalFallback,
  }
}

function getUnavailableReasonText(services, byCriticalFallback = false) {
  if (byCriticalFallback) {
    return '检测到数据库或Redis异常'
  }

  const hasDb = services.includes('database')
  const hasRedis = services.includes('redis')

  if (hasDb && hasRedis) {
    return '数据库和Redis不可用'
  }
  if (hasDb) {
    return '数据库不可用'
  }
  if (hasRedis) {
    return 'Redis不可用'
  }
  return ''
}

async function fetchHealthDataWithoutInterceptor() {
  const res = await axios.get('/api/v1/system/health', {
    timeout: 6000,
    validateStatus: () => true,
  })

  if (res.status !== 200) {
    return null
  }

  return res.data?.data || null
}

async function handleServiceUnavailableRedirect() {
  const now = Date.now()
  if (serviceUnavailableRedirectInFlight) {
    return { handled: true, reasonText: null }
  }

  if (now - lastServiceUnavailableRedirectAt < SERVICE_UNAVAILABLE_REDIRECT_COOLDOWN_MS) {
    return { handled: true, reasonText: null }
  }

  serviceUnavailableRedirectInFlight = true
  try {
    const healthData = await fetchHealthDataWithoutInterceptor()
    const { services, byCriticalFallback } = getUnavailableStateFromHealth(healthData)

    if (!services.length) {
      return { handled: false, reasonText: null }
    }

    const reasonText = getUnavailableReasonText(services, byCriticalFallback)
    const unavailable = services.join(',')
    const currentRoute = router.currentRoute.value

    if (currentRoute.name !== 'Login' || currentRoute.query?.unavailable !== unavailable) {
      await router.push({
        name: 'Login',
        query: {
          redirect: currentRoute.fullPath || '/',
          unavailable,
        },
      })
    }

    lastServiceUnavailableRedirectAt = Date.now()
    return { handled: true, reasonText }
  } catch {
    return { handled: false, reasonText: null }
  } finally {
    serviceUnavailableRedirectInFlight = false
  }
}

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
  async (response) => {
    // 如果是二进制下载请求，直接返回原始 response，让调用方处理 blob
    if (response.config && response.config.responseType === 'blob') {
      return response
    }
    const data = response.data
    if (data.code && data.code !== 200) {
      if (Number(data.code) >= 500) {
        const unavailable = await handleServiceUnavailableRedirect()
        if (unavailable.handled) {
          ElMessage.error(unavailable.reasonText || '检测到系统异常，已自动跳转到登录页')
          return Promise.reject(new Error(unavailable.reasonText || data.message || '服务异常'))
        }
      }

      ElMessage.error(data.message || '请求失败')
      return Promise.reject(new Error(data.message))
    }
    return data
  },
  async (error) => {
    const status = error.response?.status
    const msg = error.response?.data?.message || error.message
    const requestUrl = String(error.config?.url || '')
    const isLoginRequest = /\/auth\/login(?:\?|$)/.test(requestUrl)
    const hasToken = Boolean(localStorage.getItem('access_token'))

    if (status === 401) {
      if (isLoginRequest) {
        ElMessage.error(msg || '用户名或密码错误')
        return Promise.reject(error)
      }

      localStorage.removeItem('access_token')
      localStorage.removeItem('user_info')

      if (router.currentRoute.value.name !== 'Login') {
        router.push({ name: 'Login' })
      }

      if (hasToken) {
        ElMessage.warning('登录已过期，请重新登录')
      } else {
        ElMessage.error(msg || '未登录或登录状态无效')
      }
    } else if (status === 403) {
      ElMessage.error('无权限访问')
    } else if (status === 404) {
      ElMessage.error('资源不存在')
    } else if (status >= 500) {
      const unavailable = await handleServiceUnavailableRedirect()
      if (unavailable.handled) {
        if (unavailable.reasonText) {
          ElMessage.error(`${unavailable.reasonText}，已自动跳转到登录页`)
        }
      } else {
        ElMessage.error('服务器错误，请稍后重试')
      }
    } else if (!status) {
      const unavailable = await handleServiceUnavailableRedirect()
      if (unavailable.handled) {
        if (unavailable.reasonText) {
          ElMessage.error(`${unavailable.reasonText}，已自动跳转到登录页`)
        }
      } else {
        ElMessage.error(msg || '网络错误')
      }
    } else {
      ElMessage.error(msg || '网络错误')
    }
    return Promise.reject(error)
  }
)

export default request
