import { useState, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getBills, addBill, updateBill, deleteBill, postBill, postAllBills, type Bill, type BillIn } from '../api/bills'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import api from '@/api/client'
import CreateVendorModal from '../components/CreateVendorModal'

interface RowError { index: number; message: string }

type EditingRow = { mode: 'add' } | { mode: 'edit'; index: number }

const today = () => new Date().toISOString().slice(0, 10)

interface VendorMatch { key: string; display_name: string }

function VendorInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [suggestions, setSuggestions] = useState<VendorMatch[]>([])
  const [open, setOpen] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [modalInitialName, setModalInitialName] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const searchAbortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [])

  const handleChange = (v: string) => {
    onChange(v)
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current)
    if (v.trim().length < 2) { setSuggestions([]); setOpen(false); return }
    searchTimerRef.current = setTimeout(async () => {
      if (searchAbortRef.current) searchAbortRef.current.abort()
      const controller = new AbortController()
      searchAbortRef.current = controller
      try {
        const res = await api.get<{ results: VendorMatch[] }>(
          `/vendors/search?q=${encodeURIComponent(v)}`,
          { signal: controller.signal },
        )
        setSuggestions(res.data.results)
        setOpen(true)
      } catch (e: unknown) {
        if ((e as { code?: string })?.code !== 'ERR_CANCELED') {
          setSuggestions([])
        }
      }
    }, 300)
  }

  const showAddNew =
    value.trim().length >= 2 &&
    !suggestions.some(s => s.display_name.toLowerCase() === value.trim().toLowerCase())

  return (
    <>
      <div className="relative" ref={ref}>
        <Input
          className="h-7 text-sm"
          value={value}
          placeholder="Vendor"
          autoFocus
          onChange={e => handleChange(e.target.value)}
          onFocus={() => (suggestions.length > 0 || showAddNew) && setOpen(true)}
        />
        {open && (suggestions.length > 0 || showAddNew) && (
          <ul className="absolute z-20 w-full bg-white border border-slate-200 rounded shadow-lg max-h-48 overflow-y-auto text-sm">
            {suggestions.map(s => (
              <li
                key={s.key}
                className="px-3 py-1.5 cursor-pointer hover:bg-blue-50"
                onMouseDown={() => { onChange(s.display_name); setSuggestions([]); setOpen(false) }}
              >
                {s.display_name}
              </li>
            ))}
            {showAddNew && (
              <li
                className="px-3 py-1.5 cursor-pointer hover:bg-green-50 text-green-700 font-medium border-t border-slate-100"
                onMouseDown={() => {
                  setModalInitialName(value.trim())
                  setShowModal(true)
                  setOpen(false)
                }}
              >
                ＋ Add "{value.trim()}"
              </li>
            )}
          </ul>
        )}
      </div>
      {showModal && (
        <CreateVendorModal
          initialName={modalInitialName}
          onCreated={displayName => { onChange(displayName); setShowModal(false) }}
          onClose={() => setShowModal(false)}
        />
      )}
    </>
  )
}

function BillRow({
  bill,
  onEdit,
  onDelete,
  onPost,
  error,
}: {
  bill: Bill
  onEdit: () => void
  onDelete: () => void
  onPost: () => void
  error?: string
}) {
  return (
    <>
      <tr className="border-b border-slate-100 hover:bg-slate-50">
        <td className="px-3 py-2 text-sm text-slate-800">{bill.vendor_name}</td>
        <td className="px-3 py-2 text-sm text-slate-800 text-right">${bill.amount.toFixed(2)}</td>
        <td className="px-3 py-2 text-sm text-slate-500">{bill.memo}</td>
        <td className="px-3 py-2 text-sm text-slate-500">{bill.date}</td>
        <td className="px-3 py-2 text-sm text-slate-500">{bill.check_number}</td>
        <td className="px-3 py-2">
          <div className="flex gap-1">
            <Button size="sm" variant="default" className="bg-green-600 hover:bg-green-700 text-xs h-7" onClick={onPost}>
              Post
            </Button>
            <Button size="sm" variant="outline" className="text-xs h-7" onClick={onEdit}>
              Edit
            </Button>
            <Button size="sm" variant="ghost" className="text-red-500 text-xs h-7" onClick={onDelete}>
              ✕
            </Button>
          </div>
        </td>
      </tr>
      {error && (
        <tr>
          <td colSpan={6} className="px-3 py-1 text-xs text-red-600 bg-red-50">{error}</td>
        </tr>
      )}
    </>
  )
}

function EditableRow({
  initial,
  onSave,
  onCancel,
  isNew,
}: {
  initial?: Bill
  onSave: (b: BillIn) => void
  onCancel: () => void
  isNew: boolean
}) {
  const [vendor, setVendor] = useState(initial?.vendor_name ?? '')
  const [amount, setAmount] = useState(initial?.amount?.toString() ?? '')
  const [memo, setMemo] = useState(initial?.memo ?? '')
  const [date, setDate] = useState(initial?.date ?? today())
  const [check, setCheck] = useState(initial?.check_number ?? '')

  const handleSave = () => {
    const amt = parseFloat(amount)
    if (!vendor.trim() || isNaN(amt) || amt <= 0) return
    onSave({ vendor_name: vendor, amount: amt, memo, bill_date: date, check_number: check })
  }

  return (
    <tr className="border-b-2 border-blue-400 bg-blue-50">
      <td className="px-2 py-1"><VendorInput value={vendor} onChange={setVendor} /></td>
      <td className="px-2 py-1"><Input className="h-7 text-sm text-right" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" /></td>
      <td className="px-2 py-1"><Input className="h-7 text-sm" value={memo} onChange={e => setMemo(e.target.value)} placeholder="Memo" /></td>
      <td className="px-2 py-1"><Input className="h-7 text-sm" type="date" value={date} onChange={e => setDate(e.target.value)} /></td>
      <td className="px-2 py-1"><Input className="h-7 text-sm" value={check} onChange={e => setCheck(e.target.value)} placeholder="Check #" /></td>
      <td className="px-2 py-1">
        <div className="flex gap-1">
          <Button size="sm" className="text-xs h-7" onClick={handleSave}>{isNew ? 'Add' : 'Save'}</Button>
          <Button size="sm" variant="ghost" className="text-xs h-7" onClick={onCancel}>Cancel</Button>
        </div>
      </td>
    </tr>
  )
}

export default function BillsQueue() {
  const qc = useQueryClient()
  const { data: bills = [], isLoading } = useQuery({ queryKey: ['bills'], queryFn: getBills })
  const [editing, setEditing] = useState<EditingRow | null>(null)
  const [rowErrors, setRowErrors] = useState<RowError[]>([])
  const [postingAll, setPostingAll] = useState(false)

  const clearRowError = (index: number) =>
    setRowErrors(prev => prev.filter(e => e.index !== index))

  const addMutation = useMutation({
    mutationFn: addBill,
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['bills'] }); setEditing(null) },
  })

  const updateMutation = useMutation({
    mutationFn: ({ index, bill }: { index: number; bill: BillIn }) => updateBill(index, bill),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['bills'] }); setEditing(null) },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteBill,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['bills'] }),
  })

  const postMutation = useMutation({
    mutationFn: postBill,
    onSuccess: (data, index) => {
      if (data.ok) {
        qc.invalidateQueries({ queryKey: ['bills'] })
        clearRowError(index)
      } else {
        setRowErrors(prev => [...prev.filter(e => e.index !== index), { index, message: data.error }])
      }
    },
  })

  const handlePostAll = async () => {
    setPostingAll(true)
    try {
      const result = await postAllBills()
      qc.invalidateQueries({ queryKey: ['bills'] })
      if (result.failed?.length) {
        const errors: RowError[] = result.failed.map((f: { vendor_name: string; error: string }, i: number) => ({
          index: i,
          message: `${f.vendor_name}: ${f.error}`,
        }))
        setRowErrors(errors)
      } else {
        setRowErrors([])
      }
    } finally {
      setPostingAll(false)
    }
  }

  if (isLoading) return <div className="text-slate-500 text-sm">Loading...</div>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-slate-800">Bills Queue</h1>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" onClick={handlePostAll} disabled={postingAll || bills.length === 0}>
            {postingAll ? 'Processing...' : 'Post All'}
          </Button>
          <Button size="sm" onClick={() => setEditing({ mode: 'add' })}>+ Add Bill</Button>
        </div>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 overflow-hidden">
        <table className="w-full border-collapse">
          <thead>
            <tr className="bg-slate-50 border-b border-slate-200">
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Vendor</th>
              <th className="px-3 py-2 text-right text-xs font-medium text-slate-500 uppercase">Amount</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Memo</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Date</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 uppercase">Check #</th>
              <th className="px-3 py-2 text-xs font-medium text-slate-500 uppercase">Actions</th>
            </tr>
          </thead>
          <tbody>
            {editing?.mode === 'add' && (
              <EditableRow
                isNew
                onSave={bill => addMutation.mutate(bill)}
                onCancel={() => setEditing(null)}
              />
            )}
            {bills.map(bill =>
              editing?.mode === 'edit' && editing.index === bill.index ? (
                <EditableRow
                  key={bill.index}
                  initial={bill}
                  isNew={false}
                  onSave={b => updateMutation.mutate({ index: bill.index, bill: b })}
                  onCancel={() => setEditing(null)}
                />
              ) : (
                <BillRow
                  key={bill.index}
                  bill={bill}
                  onEdit={() => setEditing({ mode: 'edit', index: bill.index })}
                  onDelete={() => {
                    if (confirm(`Delete bill for ${bill.vendor_name}?`)) {
                      deleteMutation.mutate(bill.index)
                    }
                  }}
                  onPost={() => postMutation.mutate(bill.index)}
                  error={rowErrors.find(e => e.index === bill.index)?.message}
                />
              )
            )}
            {bills.length === 0 && !editing && (
              <tr>
                <td colSpan={6} className="px-3 py-8 text-center text-slate-400 text-sm">
                  No bills in queue. Click &quot;+ Add Bill&quot; to add one.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}
