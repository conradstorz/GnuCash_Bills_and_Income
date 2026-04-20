import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getSettings, updateSettings, type SettingsUpdate } from '../api/settings'
import { getAllAccounts, type Account } from '../api/accounts'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import api from '../api/client'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-lg border border-slate-200 p-5 mb-4">
      <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-4">{title}</h3>
      {children}
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-3">
      <label className="block text-sm text-slate-600 mb-1">{label}</label>
      {children}
    </div>
  )
}

export default function Settings() {
  const qc = useQueryClient()
  const { data: settings, isLoading } = useQuery({ queryKey: ['settings'], queryFn: getSettings })
  const { data: allAccounts = [] } = useQuery({ queryKey: ['allAccounts'], queryFn: getAllAccounts })
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (body: SettingsUpdate) => updateSettings(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['settings'] })
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    },
    onError: (e: unknown) => setSaveError(e instanceof Error ? e.message : 'Save failed'),
  })

  const browsePath = async () => {
    const res = await api.get<{ path: string }>('/db/browse')
    if (res.data.path) {
      mutation.mutate({ gnucash_db_path: res.data.path })
    }
  }

  if (isLoading || !settings) return <div className="text-slate-500 text-sm">Loading...</div>

  return (
    <div className="max-w-2xl">
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-semibold text-slate-800">Settings</h1>
        {saved && <span className="text-green-600 text-sm">Saved</span>}
        {saveError && <span className="text-red-600 text-sm">{saveError}</span>}
      </div>

      <Section title="Database">
        <Field label="GnuCash Database Path">
          <div className="flex gap-2">
            <Input className="h-8 text-sm flex-1" value={settings.gnucash_db_path} readOnly />
            <Button size="sm" variant="outline" onClick={browsePath}>Browse...</Button>
          </div>
        </Field>
      </Section>

      <Section title="Processing Accounts">
        <Field label="Accounts Payable Account">
          <select
            className="w-full h-8 text-sm border border-slate-200 rounded px-2 bg-white"
            value={settings.ap_account_guid ?? ''}
            onChange={e => mutation.mutate({ ap_account_guid: e.target.value || undefined })}
          >
            <option value="">— not set —</option>
            {allAccounts.map((a: Account) => (
              <option key={a.guid} value={a.guid}>{a.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Checking Account">
          <select
            className="w-full h-8 text-sm border border-slate-200 rounded px-2 bg-white"
            value={settings.checking_account_guid ?? ''}
            onChange={e => mutation.mutate({ checking_account_guid: e.target.value || undefined })}
          >
            <option value="">— not set —</option>
            {allAccounts.map((a: Account) => (
              <option key={a.guid} value={a.guid}>{a.name}</option>
            ))}
          </select>
        </Field>
        <Field label="Default Expense Account">
          <select
            className="w-full h-8 text-sm border border-slate-200 rounded px-2 bg-white"
            value={settings.expense_account_guid ?? ''}
            onChange={e => mutation.mutate({ expense_account_guid: e.target.value || undefined })}
          >
            <option value="">— not set —</option>
            {allAccounts.map((a: Account) => (
              <option key={a.guid} value={a.guid}>{a.name}</option>
            ))}
          </select>
        </Field>
      </Section>

      <Section title="Cash Entry">
        <Field label="Cash-on-Hand Account Name">
          <Input
            className="h-8 text-sm"
            defaultValue={settings.cash_on_hand_account_name}
            onBlur={e => mutation.mutate({ cash_on_hand_account_name: e.target.value })}
          />
        </Field>
        <Field label="Income / Asset Accounts Available for Cash Deposits">
          {allAccounts.length === 0 ? (
            <p className="text-xs text-slate-400 italic">No accounts found — is the database connected?</p>
          ) : (
            <div className="border border-slate-200 rounded p-2 max-h-48 overflow-y-auto space-y-1">
              {allAccounts.map((a: Account) => {
                const checked = settings.enabled_cash_account_guids.includes(a.guid)
                return (
                  <label key={a.guid} className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer hover:bg-slate-50 px-1 rounded">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-blue-600"
                      checked={checked}
                      onChange={e => {
                        const next = e.target.checked
                          ? [...settings.enabled_cash_account_guids, a.guid]
                          : settings.enabled_cash_account_guids.filter(g => g !== a.guid)
                        mutation.mutate({ enabled_cash_account_guids: next })
                      }}
                    />
                    {a.name}
                  </label>
                )
              })}
            </div>
          )}
        </Field>
      </Section>

      <Section title="Locality">
        <div className="flex gap-3">
          <Field label="City">
            <Input className="h-8 text-sm" defaultValue={settings.locality_city}
              onBlur={e => mutation.mutate({ locality_city: e.target.value })} />
          </Field>
          <Field label="State">
            <Input className="h-8 text-sm w-16" defaultValue={settings.locality_state}
              onBlur={e => mutation.mutate({ locality_state: e.target.value })} />
          </Field>
        </div>
        <div className="flex gap-3">
          <Field label="Latitude">
            <Input className="h-8 text-sm" defaultValue={settings.home_latitude}
              onBlur={e => mutation.mutate({ home_latitude: parseFloat(e.target.value) || undefined })} />
          </Field>
          <Field label="Longitude">
            <Input className="h-8 text-sm" defaultValue={settings.home_longitude}
              onBlur={e => mutation.mutate({ home_longitude: parseFloat(e.target.value) || undefined })} />
          </Field>
          <Field label="Search Radius (miles)">
            <Input className="h-8 text-sm w-24" defaultValue={settings.search_radius_miles}
              onBlur={e => mutation.mutate({ search_radius_miles: parseFloat(e.target.value) || undefined })} />
          </Field>
        </div>
      </Section>

      <Section title="Fuzzy Matching">
        <div className="flex gap-3">
          <Field label="Match Threshold">
            <Input className="h-8 text-sm w-20" defaultValue={settings.fuzzy_match_threshold}
              onBlur={e => mutation.mutate({ fuzzy_match_threshold: parseInt(e.target.value) || undefined })} />
          </Field>
          <Field label="Ambiguous Threshold">
            <Input className="h-8 text-sm w-20" defaultValue={settings.fuzzy_ambiguous_threshold}
              onBlur={e => mutation.mutate({ fuzzy_ambiguous_threshold: parseInt(e.target.value) || undefined })} />
          </Field>
        </div>
      </Section>
    </div>
  )
}
