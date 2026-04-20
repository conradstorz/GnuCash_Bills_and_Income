import { useState, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getCashAccounts, getMemos, type Account } from '../api/accounts'
import { submitCash, type CashEntryRow } from '../api/cash'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

const today = () => new Date().toISOString().slice(0, 10)

interface Row { id: number; account_guid: string; memo: string; amount: string }
let nextId = 1

function newRow(): Row {
  return { id: nextId++, account_guid: '', memo: '', amount: '' }
}

function AutocompleteInput({
  value, onChange, suggestions, placeholder, className,
}: {
  value: string
  onChange: (v: string) => void
  suggestions: string[]
  placeholder?: string
  className?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <Input
        className={className}
        value={value}
        placeholder={placeholder}
        onChange={e => { onChange(e.target.value); setOpen(true) }}
        onFocus={() => setOpen(true)}
      />
      {open && suggestions.length > 0 && (
        <ul className="absolute z-10 w-full bg-white border border-slate-200 rounded shadow-lg max-h-48 overflow-y-auto text-sm">
          {suggestions.map(s => (
            <li
              key={s}
              className="px-3 py-1.5 cursor-pointer hover:bg-blue-50"
              onMouseDown={() => { onChange(s); setOpen(false) }}
            >
              {s}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const STORAGE_KEY = 'cashEntry_draft'

function loadDraft(): { entryDate: string; rows: Row[] } | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : null
  } catch { return null }
}

function saveDraft(entryDate: string, rows: Row[]) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify({ entryDate, rows })) } catch {}
}

function clearDraft() {
  try { localStorage.removeItem(STORAGE_KEY) } catch {}
}

export default function CashEntry() {
  const draft = loadDraft()
  const [entryDate, setEntryDate] = useState(draft?.entryDate ?? today())
  const [rows, setRows] = useState<Row[]>(draft?.rows ?? [newRow()])
  const [memoSuggestions, setMemoSuggestions] = useState<string[]>([])
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const { data: accounts = [] } = useQuery({ queryKey: ['cashAccounts'], queryFn: getCashAccounts })

  const updateRow = (id: number, field: keyof Row, value: string) =>
    setRows(prev => {
      const next = prev.map(r => r.id === id ? { ...r, [field]: value } : r)
      saveDraft(entryDate, next)
      return next
    })

  const removeRow = (id: number) =>
    setRows(prev => {
      const next = prev.filter(r => r.id !== id)
      saveDraft(entryDate, next)
      return next
    })

  const addRow = () => setRows(prev => {
    const next = [...prev, newRow()]
    saveDraft(entryDate, next)
    return next
  })

  const fetchMemos = async (q: string) => {
    const data = await getMemos(q)
    setMemoSuggestions(data.suggestions)
  }

  const samuse = rows.reduce((sum, r) => sum + (parseFloat(r.amount) || 0), 0)

  const handleSubmit = async () => {
    const entries: CashEntryRow[] = rows
      .filter(r => r.account_guid && parseFloat(r.amount) > 0)
      .map(r => ({ account_guid: r.account_guid, memo: r.memo, amount: parseFloat(r.amount) }))

    if (!entries.length) { setError('Add at least one entry with an account and amount.'); return }

    setSubmitting(true)
    setError(null)
    try {
      const res = await submitCash({ entry_date: entryDate, entries })
      if (res.batch?.ok) {
        setResult(`Posted $${res.batch.total.toFixed(2)} to GnuCash.`)
        clearDraft()
        setRows([newRow()])
      } else {
        setError(res.batch?.error || 'Unknown error')
      }
    } catch (e: unknown) {
      // Prefer the server's error detail over the generic axios message
      const axiosDetail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      const msg = axiosDetail ?? (e instanceof Error ? e.message : 'Server error')
      setError(msg)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-slate-800">Cash Entry</h1>
        <div className="flex items-center gap-3">
          <label className="text-sm text-slate-500">Date</label>
          <Input type="date" className="h-8 w-36 text-sm" value={entryDate} onChange={e => { setEntryDate(e.target.value); saveDraft(e.target.value, rows) }} />
          <Button onClick={handleSubmit} disabled={submitting} className="bg-green-600 hover:bg-green-700">
            {submitting ? 'Posting...' : 'Post to GnuCash'}
          </Button>
        </div>
      </div>

      {result && <div className="mb-3 p-3 bg-green-50 border border-green-200 rounded text-green-700 text-sm">{result}</div>}
      {error && <div className="mb-3 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

      <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase w-5/12">Memo</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase w-4/12">Account</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-slate-500 uppercase w-2/12">Amount</th>
              <th className="px-3 py-2 w-1/12"></th>
            </tr>
          </thead>
          <tbody>
            {rows.map(row => (
              <tr key={row.id} className="border-b border-slate-100">
                <td className="px-2 py-1">
                  <AutocompleteInput
                    className="h-7 text-sm"
                    value={row.memo}
                    placeholder="Client / memo"
                    suggestions={memoSuggestions}
                    onChange={v => { updateRow(row.id, 'memo', v); fetchMemos(v) }}
                  />
                </td>
                <td className="px-2 py-1">
                  <select
                    className="h-7 text-sm w-full border border-slate-200 rounded px-2 bg-white"
                    value={row.account_guid}
                    onChange={e => updateRow(row.id, 'account_guid', e.target.value)}
                  >
                    <option value="">Select account...</option>
                    {accounts.map((a: Account) => (
                      <option key={a.guid} value={a.guid}>{a.name}</option>
                    ))}
                  </select>
                </td>
                <td className="px-2 py-1">
                  <Input
                    className="h-7 text-sm text-right"
                    value={row.amount}
                    placeholder="0.00"
                    onChange={e => updateRow(row.id, 'amount', e.target.value)}
                  />
                </td>
                <td className="px-2 py-1 text-center">
                  <button className="text-red-400 hover:text-red-600 text-sm" onClick={() => removeRow(row.id)}>✕</button>
                </td>
              </tr>
            ))}
            <tr className="border-b border-slate-200">
              <td colSpan={4} className="px-3 py-1">
                <button className="text-blue-600 text-sm hover:underline" onClick={addRow}>+ Add row</button>
              </td>
            </tr>
            <tr className="bg-green-50">
              <td className="px-3 py-2 text-sm text-slate-500 italic">SAMUSE (auto)</td>
              <td className="px-3 py-2 text-sm text-slate-500">Cash on Hand</td>
              <td className="px-3 py-2 text-sm font-semibold text-green-700 text-right">${samuse.toFixed(2)}</td>
              <td></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  )
}
