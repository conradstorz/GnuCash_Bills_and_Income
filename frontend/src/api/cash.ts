import api from './client'

export interface CashEntryRow { account_guid: string; memo: string; amount: number }
export interface CashSubmitIn {
  entry_date: string
  entries: CashEntryRow[]
  deposit_account_guid?: string
  deposit_amount?: number
  deposit_date?: string
}

export const submitCash = (body: CashSubmitIn) => api.post('/cash/submit', body).then(r => r.data)
