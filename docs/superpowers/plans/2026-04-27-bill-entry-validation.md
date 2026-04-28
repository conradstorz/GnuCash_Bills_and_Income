# Bill Entry Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the user clicks Add/Save in the bill entry row with a missing vendor or invalid amount, highlight the invalid fields with red borders and error labels, and move focus to the first invalid field.

**Architecture:** All changes are in a single file (`BillsQueue.tsx`). `VendorInput` is converted to a `forwardRef` component so a ref can be passed to its inner `<Input>` for focus control. `EditableRow` gains an `errors` state object, two refs, validation logic in `handleSave`, per-field error labels, and per-field error-clearing on `onChange`.

**Tech Stack:** React 19, TypeScript, Tailwind CSS v4, shadcn `<Input>` (already uses `forwardRef`)

---

## File Map

| Action | File | Change |
|---|---|---|
| Modify | `frontend/src/pages/BillsQueue.tsx` | `forwardRef` on `VendorInput`; errors/refs/validation in `EditableRow` |

---

### Task 1: Convert VendorInput to forwardRef and add inputClassName prop

**Files:**
- Modify: `frontend/src/pages/BillsQueue.tsx:1` (import) and `:18-129` (VendorInput)

No frontend test framework exists — TypeScript compilation (`tsc -b --noEmit`) is the verification gate.

- [ ] **Step 1: Add `forwardRef` to the React import on line 1**

Change:
```tsx
import { useState, useRef, useEffect } from 'react'
```
To:
```tsx
import { useState, useRef, useEffect, forwardRef } from 'react'
```

- [ ] **Step 2: Replace the `VendorInput` function declaration with a `forwardRef` version**

The current signature is:
```tsx
function VendorInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
```

Replace the entire `VendorInput` function (lines 18–129) with the following. The internal `ref` (renamed `wrapperRef`) still points to the wrapper `<div>` for click-outside detection. The forwarded `inputRef` goes to the inner `<Input>`. A new `inputClassName` prop is passed through to the `<Input>`:

```tsx
const VendorInput = forwardRef<HTMLInputElement, {
  value: string
  onChange: (v: string) => void
  inputClassName?: string
}>(function VendorInput({ value, onChange, inputClassName }, inputRef) {
  const [suggestions, setSuggestions] = useState<VendorMatch[]>([])
  const [open, setOpen] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [modalInitialName, setModalInitialName] = useState('')
  const [dropdownPos, setDropdownPos] = useState<{ top: number; left: number; width: number } | null>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)
  const dropdownRef = useRef<HTMLUListElement>(null)
  const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const searchAbortRef = useRef<AbortController | null>(null)

  const computePos = () => {
    if (wrapperRef.current) {
      const r = wrapperRef.current.getBoundingClientRect()
      setDropdownPos({ top: r.bottom, left: r.left, width: r.width })
    }
  }

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      const t = e.target as Node
      if (
        wrapperRef.current && !wrapperRef.current.contains(t) &&
        (!dropdownRef.current || !dropdownRef.current.contains(t))
      ) setOpen(false)
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
        computePos()
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
      <div ref={wrapperRef}>
        <Input
          ref={inputRef}
          className={`h-7 text-sm${inputClassName ? ' ' + inputClassName : ''}`}
          value={value}
          placeholder="Vendor"
          autoFocus
          onChange={e => handleChange(e.target.value)}
          onFocus={() => {
            if (suggestions.length > 0 || showAddNew) { computePos(); setOpen(true) }
          }}
        />
      </div>
      {open && dropdownPos && (suggestions.length > 0 || showAddNew) && createPortal(
        <ul
          ref={dropdownRef}
          style={{ position: 'fixed', top: dropdownPos.top, left: dropdownPos.left, width: dropdownPos.width }}
          className="z-[9999] bg-white border border-slate-200 rounded shadow-lg max-h-48 overflow-y-auto text-sm"
        >
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
        </ul>,
        document.body
      )}
      {showModal && (
        <CreateVendorModal
          initialName={modalInitialName}
          onCreated={displayName => { onChange(displayName); setShowModal(false) }}
          onClose={() => setShowModal(false)}
        />
      )}
    </>
  )
})
```

- [ ] **Step 3: Run TypeScript check**

```bash
cd frontend && npx tsc -b --noEmit
```

Expected: no errors. If `forwardRef` is flagged as unused or the ref type is wrong, confirm the import includes `forwardRef` and the generic types match `HTMLInputElement`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/BillsQueue.tsx
git commit -m "refactor: convert VendorInput to forwardRef with inputClassName prop"
```

---

### Task 2: Add errors state, validation, refs, and error labels to EditableRow

**Files:**
- Modify: `frontend/src/pages/BillsQueue.tsx:175-213` (EditableRow)

- [ ] **Step 1: Replace the entire `EditableRow` function with the validated version**

The current `EditableRow` (lines 175–213) has no error state and `handleSave` silently returns on invalid input. Replace it entirely with:

```tsx
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
  const [errors, setErrors] = useState<{ vendor?: string; amount?: string }>({})
  const vendorRef = useRef<HTMLInputElement>(null)
  const amountRef = useRef<HTMLInputElement>(null)

  const handleSave = () => {
    const newErrors: { vendor?: string; amount?: string } = {}
    if (!vendor.trim()) {
      newErrors.vendor = 'Vendor is required'
    }
    const amt = parseFloat(amount)
    if (!amount.trim() || isNaN(amt)) {
      newErrors.amount = 'Amount is required'
    } else if (amt <= 0) {
      newErrors.amount = 'Amount must be greater than 0'
    }
    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors)
      if (newErrors.vendor) vendorRef.current?.focus()
      else amountRef.current?.focus()
      return
    }
    setErrors({})
    onSave({ vendor_name: vendor, amount: amt, memo, bill_date: date, check_number: check })
  }

  return (
    <tr className="border-b-2 border-blue-400 bg-blue-50">
      <td className="px-2 py-1">
        <VendorInput
          ref={vendorRef}
          value={vendor}
          onChange={v => { setVendor(v); if (errors.vendor) setErrors(prev => ({ ...prev, vendor: undefined })) }}
          inputClassName={errors.vendor ? 'border-red-500 focus-visible:ring-red-500' : ''}
        />
        {errors.vendor && <p className="text-xs text-red-500 mt-0.5">{errors.vendor}</p>}
      </td>
      <td className="px-2 py-1">
        <Input
          ref={amountRef}
          className={`h-7 text-sm text-right${errors.amount ? ' border-red-500 focus-visible:ring-red-500' : ''}`}
          value={amount}
          onChange={e => { setAmount(e.target.value); if (errors.amount) setErrors(prev => ({ ...prev, amount: undefined })) }}
          placeholder="0.00"
        />
        {errors.amount && <p className="text-xs text-red-500 mt-0.5">{errors.amount}</p>}
      </td>
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
```

- [ ] **Step 2: Run TypeScript check**

```bash
cd frontend && npx tsc -b --noEmit
```

Expected: no errors. Common issues to watch for:
- `amt` used before assignment: ensure `const amt = parseFloat(amount)` is inside the `else if` branch — it's actually declared before the `if` block, which is correct.
- If `Input` doesn't accept `ref`, check `frontend/src/components/ui/input.tsx` — shadcn `Input` uses `forwardRef` and accepts `ref` natively.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/BillsQueue.tsx
git commit -m "feat: add per-field validation to bill entry row with focus on first error"
```

---

### Task 3: Build frontend and smoke-test

**Files:**
- No file changes — build and verify only

- [ ] **Step 1: Build the production bundle**

```bash
cd frontend && npm run build
```

Expected: `✓ built in Xs` with no errors.

- [ ] **Step 2: Start the server**

```bash
uv run uvicorn bill_processor.web.app:app --reload --port 7432
```

Open `http://localhost:7432/bills`.

- [ ] **Step 3: Verify empty-submit shows errors**

Click **+ Add Bill** to open the editable row. Immediately click **Add** without filling in anything.

Expected:
- Vendor field turns red with label "Vendor is required" beneath it
- Amount field turns red with label "Amount is required" beneath it
- Focus moves to the Vendor input

- [ ] **Step 4: Verify partial-submit (vendor filled, amount empty)**

Type a vendor name (e.g. "Test"). Click **Add**.

Expected:
- Vendor field is normal (no error — vendor is now valid)
- Amount field is red with "Amount is required"
- Focus moves to the Amount input

- [ ] **Step 5: Verify invalid amount (zero or negative)**

Type a vendor name. Type `0` in Amount. Click **Add**.

Expected:
- Amount field turns red with label "Amount must be greater than 0"

- [ ] **Step 6: Verify error clears on edit**

With the amount error showing, start typing in the Amount field.

Expected: red border and error label disappear immediately on the first keystroke.

- [ ] **Step 7: Verify successful add still works**

Fill in a valid vendor and amount. Click **Add**.

Expected: row is added to the queue, edit row disappears, no errors.

- [ ] **Step 8: Commit the build**

The dist is gitignored — no commit needed for build artifacts. The source commits from Tasks 1 and 2 are sufficient.
