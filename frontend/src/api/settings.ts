import api from './client'

export interface AppSettings {
  ap_account_guid: string | null
  ap_account_name: string | null
  checking_account_guid: string | null
  checking_account_name: string | null
  expense_account_guid: string | null
  expense_account_name: string | null
  cash_on_hand_account_name: string
  locality_city: string
  locality_state: string
  home_latitude: number
  home_longitude: number
  search_radius_miles: number
  fuzzy_match_threshold: number
  fuzzy_ambiguous_threshold: number
  enabled_cash_account_guids: string[]
  gnucash_db_path: string
  processing_accounts_configured: boolean
}

export interface SettingsUpdate {
  ap_account_guid?: string
  checking_account_guid?: string
  expense_account_guid?: string
  cash_on_hand_account_name?: string
  locality_city?: string
  locality_state?: string
  home_latitude?: number
  home_longitude?: number
  search_radius_miles?: number
  fuzzy_match_threshold?: number
  fuzzy_ambiguous_threshold?: number
  enabled_cash_account_guids?: string[]
  gnucash_db_path?: string
}

export const getSettings = () => api.get<AppSettings>('/settings').then(r => r.data)
export const updateSettings = (body: SettingsUpdate) => api.put('/settings', body).then(r => r.data)
