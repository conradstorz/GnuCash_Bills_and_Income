import { useState, useEffect, useRef } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  createVendor,
  searchVendorCandidates,
  type VendorCandidate,
} from '../api/vendors'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface Props {
  initialName: string
  onCreated: (displayName: string) => void
  onClose: () => void
}

export default function CreateVendorModal({ initialName, onCreated, onClose }: Props) {
  const qc = useQueryClient()
  const [displayName, setDisplayName] = useState(initialName)
  const [addrLine1, setAddrLine1] = useState('')
  const [city, setCity] = useState('')
  const [addrState, setAddrState] = useState('')
  const [zip, setZip] = useState('')
  const [candidates, setCandidates] = useState<VendorCandidate[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Debounced, non-blocking live search — watches name/city/zip only
  useEffect(() => {
    const timer = setTimeout(async () => {
      if (!displayName.trim() && !city.trim() && !zip.trim()) {
        setCandidates([])
        return
      }
      if (abortRef.current) abortRef.current.abort()
      const controller = new AbortController()
      abortRef.current = controller
      setIsSearching(true)
      setSearchError(false)
      try {
        const results = await searchVendorCandidates(
          { name: displayName, city, zip },
          controller.signal,
        )
        setCandidates(results)
        setIsSearching(false)
      } catch (e: unknown) {
        // ERR_CANCELED means the request was aborted by a newer keystroke — ignore
        if ((e as { code?: string })?.code !== 'ERR_CANCELED') {
          setSearchError(true)
          setIsSearching(false)
        }
      }
    }, 600)
    return () => clearTimeout(timer)
  }, [displayName, city, zip])

  const fillFromCandidate = (c: VendorCandidate) => {
    setDisplayName(c.display_name)
    setAddrLine1(c.addr_line1)
    setCity(c.addr_city)
    setAddrState(c.addr_state)
    setZip(c.addr_zip)
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createVendor({
        vendor_name: displayName,
        display_name: displayName,
        addr_line1: addrLine1,
        addr_city: city,
        addr_state: addrState,
        addr_zip: zip,
      }),
    onSuccess: data => {
      if (data.ok) {
        qc.invalidateQueries({ queryKey: ['vendors'] })
        onCreated(displayName)
        onClose()
      } else {
        setCreateError(data.error ?? 'Failed to create vendor')
      }
    },
    onError: (e: unknown) => {
      setCreateError(e instanceof Error ? e.message : 'Failed to create vendor')
    },
  })

  // Close on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200">
          <h2 className="text-base font-semibold text-slate-800">New Vendor</h2>
          <span className="text-xs text-slate-400">Esc to cancel</span>
        </div>

        {/* Body */}
        <div className="flex min-h-64">
          {/* Left: form fields */}
          <div className="flex-1 p-6 border-r border-slate-100">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-4">
              Details
            </p>
            <div className="space-y-3">
              <div>
                <label className="text-xs text-slate-500 block mb-1">Display Name *</label>
                <Input
                  className="h-8 text-sm"
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                  autoFocus
                />
              </div>
              <div>
                <label className="text-xs text-slate-500 block mb-1">Address</label>
                <Input
                  className="h-8 text-sm"
                  value={addrLine1}
                  onChange={e => setAddrLine1(e.target.value)}
                  placeholder="123 Main St"
                />
              </div>
              <div className="flex gap-2">
                <div className="flex-1">
                  <label className="text-xs text-slate-500 block mb-1">City</label>
                  <Input
                    className="h-8 text-sm"
                    value={city}
                    onChange={e => setCity(e.target.value)}
                  />
                </div>
                <div className="w-16">
                  <label className="text-xs text-slate-500 block mb-1">State</label>
                  <Input
                    className="h-8 text-sm"
                    value={addrState}
                    onChange={e => setAddrState(e.target.value)}
                  />
                </div>
                <div className="w-24">
                  <label className="text-xs text-slate-500 block mb-1">ZIP</label>
                  <Input
                    className="h-8 text-sm"
                    value={zip}
                    onChange={e => setZip(e.target.value)}
                  />
                </div>
              </div>
            </div>
            {createError && (
              <div className="mt-3 p-2 bg-red-50 border border-red-200 rounded text-red-600 text-xs">
                {createError}
              </div>
            )}
          </div>

          {/* Right: live candidates panel */}
          <div className="w-56 p-6 flex-shrink-0">
            <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              Internet Results
              {isSearching && (
                <span className="ml-2 text-blue-400 font-normal normal-case">searching…</span>
              )}
            </p>
            {searchError ? (
              <p className="text-xs text-slate-400 italic">Search unavailable</p>
            ) : candidates.length === 0 && !isSearching ? (
              <p className="text-xs text-slate-400 italic">No matches found</p>
            ) : (
              <div className="space-y-2">
                {candidates.map((c, i) => (
                  <button
                    key={i}
                    onClick={() => fillFromCandidate(c)}
                    className="w-full text-left p-2 border border-slate-200 rounded hover:border-blue-400 hover:bg-blue-50 transition-colors"
                  >
                    <div className="text-xs font-medium text-slate-800 truncate">
                      {c.display_name}
                    </div>
                    <div className="text-xs text-slate-500 truncate">{c.addr_line1}</div>
                    <div className="text-xs text-slate-500 truncate">
                      {[c.addr_city, c.addr_state, c.addr_zip].filter(Boolean).join(', ')}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-slate-200">
          <Button size="sm" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={() => createMutation.mutate()}
            disabled={!displayName.trim() || createMutation.isPending}
          >
            {createMutation.isPending ? 'Creating…' : 'Finish'}
          </Button>
        </div>
      </div>
    </div>
  )
}
