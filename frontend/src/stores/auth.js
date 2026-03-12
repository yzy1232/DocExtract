import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import request from '@/utils/request'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('access_token') || '')
  const user = ref(JSON.parse(localStorage.getItem('user_info') || 'null'))

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.is_superuser === true)

  async function login(username, password) {
    const res = await request.post('/auth/login', { username, password })
    token.value = res.data.access_token
    localStorage.setItem('access_token', token.value)
    await fetchMe()
    return res.data
  }

  async function fetchMe() {
    const res = await request.get('/auth/me')
    user.value = res.data
    localStorage.setItem('user_info', JSON.stringify(res.data))
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('user_info')
  }

  return { token, user, isLoggedIn, isAdmin, login, fetchMe, logout }
})
