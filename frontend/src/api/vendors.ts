import api from './client'

export interface Vendor {
  key: string
  display_name: string
  gnucash_guid: string
  synced: boolean
  aliases: string[]
  addr_line1: string
  addr_city: string
  addr_state: string
  addr_zip: string
}

export interface VendorUpdate {
  display_name?: string
  addr_line1?: string
  addr_city?: string
  addr_state?: string
  addr_zip?: string
  aliases?: string[]
}

export const getVendors = () => api.get<Vendor[]>('/vendors').then(r => r.data)
export const updateVendor = (key: string, body: VendorUpdate) => api.put(`/vendors/${key}`, body).then(r => r.data)
export const syncAllVendors = () => api.post('/vendors/sync-all').then(r => r.data)
export const syncVendor = (key: string) => api.post(`/vendors/${key}/sync`).then(r => r.data)
export const lookupAddress = (body: object) => api.post('/vendors/lookup-address', body).then(r => r.data)
