import api from './client'

export interface Bill {
  index: number
  vendor_name: string
  amount: number
  memo: string
  date: string
  check_number: string
}

export interface BillIn {
  vendor_name: string
  amount: number
  memo?: string
  bill_date?: string
  check_number?: string
}

export const getBills = () => api.get<Bill[]>('/bills').then(r => r.data)
export const addBill = (b: BillIn) => api.post('/bills', b).then(r => r.data)
export const updateBill = (index: number, b: BillIn) => api.put(`/bills/${index}`, b).then(r => r.data)
export const deleteBill = (index: number) => api.delete(`/bills/${index}`).then(r => r.data)
export const postBill = (index: number) => api.post(`/bills/${index}/post`).then(r => r.data)
export const postAllBills = () => api.post('/bills/post-all').then(r => r.data)
