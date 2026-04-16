import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { getVendors, updateVendor, syncAllVendors, type Vendor, type VendorUpdate } from '../api/vendors'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import CreateVendorModal from '../components/CreateVendorModal'

function VendorDetail({
  vendor,
  onSaved,
}: {
  vendor: Vendor
  onSaved: () => void
}) {
  const qc = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<VendorUpdate>({
    display_name: vendor.display_name,
    addr_line1: vendor.addr_line1,
    addr_city: vendor.addr_city,
    addr_state: vendor.addr_state,
    addr_zip: vendor.addr_zip,
    aliases: [...vendor.aliases],
  })
  const [newAlias, setNewAlias] = useState('')
  const [saveError, setSaveError] = useState<string | null>(null)

  const updateMutation = useMutation({
    mutationFn: (body: VendorUpdate) => updateVendor(vendor.key, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['vendors'] })
      setEditing(false)
      onSaved()
    },
    onError: (e: unknown) => setSaveError(e instanceof Error ? e.message : 'Save failed'),
  })

  const syncMutation = useMutation({
    mutationFn: () => syncAllVendors(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vendors'] }),
  })

  const field = (label: string, key: keyof VendorUpdate, placeholder?: string) => (
    <div className="mb-3">
      <label className="text-xs text-slate-500 uppercase block mb-1">{label}</label>
      {editing ? (
        <Input
          className="h-7 text-sm"
          value={(form[key] as string) ?? ''}
          placeholder={placeholder}
          onChange={e => setForm(prev => ({ ...prev, [key]: e.target.value }))}
        />
      ) : (
        <div className="text-sm text-slate-800">{(vendor as unknown as Record<string, unknown>)[key] as string || <span className="text-slate-400">—</span>}</div>
      )}
    </div>
  )

  return (
    <div className="p-5">
      <div className="flex items-center justify-between mb-5">
        <h2 className="text-base font-semibold text-slate-800">{vendor.display_name}</h2>
        <div className="flex gap-2">
          {editing ? (
            <>
              <Button size="sm" onClick={() => updateMutation.mutate(form)} disabled={updateMutation.isPending}>Save</Button>
              <Button size="sm" variant="outline" onClick={() => { setEditing(false); setSaveError(null) }}>Cancel</Button>
            </>
          ) : (
            <>
              <Button size="sm" variant="outline" onClick={() => setEditing(true)}>Edit</Button>
              <Button size="sm" onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending}>
                {syncMutation.isPending ? 'Syncing...' : 'Sync'}
              </Button>
            </>
          )}
        </div>
      </div>

      {saveError && <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-red-600 text-xs">{saveError}</div>}

      {field('Display Name', 'display_name')}
      <div className="mb-3">
        <label className="text-xs text-slate-500 uppercase block mb-1">Vendor Key</label>
        <div className="text-sm text-slate-500 font-mono">{vendor.key}</div>
      </div>
      <div className="mb-3">
        <label className="text-xs text-slate-500 uppercase block mb-1">GnuCash GUID</label>
        <div className="text-xs text-slate-400 font-mono truncate">{vendor.gnucash_guid || '—'}</div>
      </div>
      {field('Address', 'addr_line1', '123 Main St')}
      <div className="flex gap-2">
        <div className="flex-1">{field('City', 'addr_city')}</div>
        <div className="w-16">{field('State', 'addr_state')}</div>
        <div className="w-24">{field('ZIP', 'addr_zip')}</div>
      </div>

      <div className="mt-4">
        <label className="text-xs text-slate-500 uppercase block mb-1">Aliases</label>
        <div className="flex flex-wrap gap-1 mb-2">
          {(form.aliases ?? []).map(a => (
            <Badge key={a} variant="secondary" className="text-xs gap-1">
              {a}
              {editing && (
                <button
                  className="ml-1 text-slate-400 hover:text-red-500"
                  onClick={() => setForm(prev => ({ ...prev, aliases: prev.aliases?.filter(x => x !== a) }))}
                >
                  ✕
                </button>
              )}
            </Badge>
          ))}
          {(form.aliases ?? []).length === 0 && <span className="text-sm text-slate-400">None</span>}
        </div>
        {editing && (
          <div className="flex gap-2">
            <Input
              className="h-7 text-sm w-40"
              placeholder="New alias"
              value={newAlias}
              onChange={e => setNewAlias(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && newAlias.trim()) {
                  setForm(prev => ({ ...prev, aliases: [...(prev.aliases ?? []), newAlias.trim()] }))
                  setNewAlias('')
                }
              }}
            />
            <Button size="sm" variant="outline" onClick={() => {
              if (newAlias.trim()) {
                setForm(prev => ({ ...prev, aliases: [...(prev.aliases ?? []), newAlias.trim()] }))
                setNewAlias('')
              }
            }}>Add</Button>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Vendors() {
  const qc = useQueryClient()
  const { data: vendors = [], isLoading } = useQuery({ queryKey: ['vendors'], queryFn: getVendors })
  const [selected, setSelected] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [showCreateModal, setShowCreateModal] = useState(false)

  const syncMutation = useMutation({
    mutationFn: syncAllVendors,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vendors'] }),
  })

  const filtered = vendors.filter(v =>
    v.display_name.toLowerCase().includes(search.toLowerCase()) ||
    v.key.toLowerCase().includes(search.toLowerCase())
  )

  const selectedVendor = vendors.find(v => v.key === selected) ?? null

  if (isLoading) return <div className="text-slate-500 text-sm">Loading...</div>

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold text-slate-800">Vendors</h1>
        <div className="flex gap-2">
          <Button size="sm" onClick={() => setShowCreateModal(true)}>+ New Vendor</Button>
          <Button size="sm" variant="outline" onClick={() => syncMutation.mutate()} disabled={syncMutation.isPending}>
            {syncMutation.isPending ? 'Syncing...' : 'Sync All'}
          </Button>
        </div>
      </div>

      <div className="flex gap-0 bg-white rounded-lg border border-slate-200 overflow-hidden" style={{ minHeight: 500 }}>
        {/* Master panel */}
        <div className="w-56 border-r border-slate-200 flex flex-col flex-shrink-0">
          <div className="p-2 border-b border-slate-100">
            <Input className="h-7 text-sm" placeholder="Search vendors..." value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <div className="flex-1 overflow-y-auto">
            {filtered.map(v => (
              <button
                key={v.key}
                onClick={() => setSelected(v.key)}
                className={`w-full text-left px-3 py-2 border-l-2 transition-colors ${
                  selected === v.key
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-transparent hover:bg-slate-50'
                }`}
              >
                <div className="text-sm font-medium text-slate-800 truncate">{v.display_name}</div>
                <div className="flex items-center gap-1 mt-0.5">
                  <span className="text-xs text-slate-400 truncate">{v.key}</span>
                  {!v.synced && <Badge variant="outline" className="text-xs py-0 h-4 text-amber-600 border-amber-300">unsynced</Badge>}
                </div>
              </button>
            ))}
            {filtered.length === 0 && (
              <div className="p-4 text-sm text-slate-400 text-center">No vendors found</div>
            )}
          </div>
        </div>

        {/* Detail panel */}
        <div className="flex-1">
          {selectedVendor ? (
            <VendorDetail vendor={selectedVendor} onSaved={() => {}} />
          ) : (
            <div className="flex items-center justify-center h-full text-slate-400 text-sm">
              Select a vendor to view details
            </div>
          )}
        </div>
      </div>

      {showCreateModal && (
        <CreateVendorModal
          initialName=""
          onCreated={() => setShowCreateModal(false)}
          onClose={() => setShowCreateModal(false)}
        />
      )}
    </div>
  )
}
