import api from './client'

export interface Account { name: string; guid: string }
export interface MemoSuggestions { suggestions: string[] }

export const getCashAccounts = () => api.get<Account[]>('/accounts/cash').then(r => r.data)
export const getAllAccounts = () => api.get<Account[]>('/accounts').then(r => r.data)
export const getMemos = (q: string) => api.get<MemoSuggestions>(`/memos?q=${encodeURIComponent(q)}`).then(r => r.data)
