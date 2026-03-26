const SHANGHAI_TIMEZONE = 'Asia/Shanghai'

function normalizeDateInput(value) {
  if (!value) return null
  if (value instanceof Date) return value

  const str = String(value).trim()
  if (!str) return null

  // 后端若返回无时区的 ISO 时间，按 UTC 解释，避免浏览器按本地时区误判
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$/.test(str)) {
    return new Date(`${str}Z`)
  }

  return new Date(str)
}

export function formatDateToUTC8(value, fallback = '-') {
  const date = normalizeDateInput(value)
  if (!date || Number.isNaN(date.getTime())) return fallback

  return date.toLocaleString('zh-CN', {
    timeZone: SHANGHAI_TIMEZONE,
    hour12: false,
  })
}
