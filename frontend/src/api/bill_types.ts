import api from './client'

export interface AccountEntry {
  name: string
  guid: string
}

export interface Preset {
  expense_acct: AccountEntry
  checking_acct: AccountEntry
  payables_acct: AccountEntry
}

export interface BillTypesResponse {
  presets: Record<string, Preset>
  labels: Record<string, AccountEntry>
}

export const getBillTypes  = () => api.get<BillTypesResponse>('/bill-types').then(r => r.data)
export const syncBillTypes = () => api.get<{ updated: number; failed: { name: string; error: string }[] }>('/bill-types/sync').then(r => r.data)
