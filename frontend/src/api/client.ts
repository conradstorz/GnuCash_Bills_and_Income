import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export default api

export async function apiFetch<T>(url: string): Promise<T> {
  const res = await api.get<T>(url)
  return res.data
}
