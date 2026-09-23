# Bills Queue Always-Open Add Row Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Bills Queue page keep a blank editable add row permanently visible, reset it after each successful add, and accept Enter as "Add", matching the Cash Entry workflow.

**Architecture:** Frontend-only change in `frontend/src/pages/BillsQueue.tsx`. The parent `BillsQueue` component renders one `EditableRow` in add mode as the last table row, keyed by an incrementing counter so a bump remounts (resets) it. `EditableRow` gains Enter-key handling. `VendorInput` closes its dropdown on Enter. Backend `POST /bills` is unchanged.

**Tech Stack:** React 19, TypeScript, TanStack Query, Vite. No frontend test runner exists; verification is `npm run build` and a manual browser check.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-23-bills-always-open-add-row-design.md`
- No backend, API, or `frontend/src/api/*` changes.
- Validation rules unchanged: vendor required; amount required, numeric, > 0.
- Do not chain shell commands with `&&`; run each command as a separate call.
- Build check: `npm run build` in `frontend/` (runs `tsc -b` then `vite build`). Must exit 0.
- Do not commit `frontend/dist` (not tracked).
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

---

### Task 1: Enter-to-add in `EditableRow` and dropdown close in `VendorInput`

**Files:**
- Modify: `frontend/src/pages/BillsQueue.tsx` (functions `VendorInput` and `EditableRow`)

**Interfaces:**
- Consumes: existing `EditableRow` props `{ initial?, onSave, onCancel, isNew }`.
- Produces: `EditableRow` submits on Enter from any of its inputs; `VendorInput` closes its suggestion list on Enter. Prop signatures unchanged.

- [ ] **Step 1: Add Enter handling to `VendorInput`**

In `VendorInput`, add an `onKeyDown` prop to the `<Input>` so Enter closes the dropdown. Keep the event propagating so the row-level handler (Step 2) still fires.

```tsx
        <Input
          ref={inputRef}
          className={cn('h-7 text-sm', inputClassName)}
          value={value}
          placeholder="Vendor"
          autoFocus
          onChange={e => handleChange(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') setOpen(false) }}
          onFocus={() => {
            if (suggestions.length > 0 || showAddNew) { computePos(); setOpen(true) }
          }}
        />
```

- [ ] **Step 2: Add a row-level Enter handler to `EditableRow`**

Change the returned `<tr>` in `EditableRow` to:

```tsx
    <tr
      className="border-b-2 border-blue-400 bg-blue-50"
      onKeyDown={e => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault()
          handleSave()
        }
      }}
    >
```

`handleSave` is already defined above the JSX in `EditableRow`; no other change.

- [ ] **Step 3: Build**

Run (from `frontend/`): `npm run build`
Expected: exits 0, ends with `built in ...`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/BillsQueue.tsx
git commit -m "feat(bills): Enter submits the editable bill row"
```

---

### Task 2: Always-visible add row with reset-on-add and Clear

**Files:**
- Modify: `frontend/src/pages/BillsQueue.tsx` (type `EditingRow`, function `EditableRow`, function `BillsQueue`)

**Interfaces:**
- Consumes: `EditableRow` from Task 1; `addBill` from `../api/bills` (`(b: BillIn) => Promise<unknown>`).
- Produces: `BillsQueue` renders a permanent add row; state `editingIndex: number | null` replaces `editing: EditingRow | null`; `addRowKey: number` counter; constant `ADD_ROW_INDEX = -1`.

- [ ] **Step 1: Replace the `EditingRow` type**

Delete this line:

```tsx
type EditingRow = { mode: 'add' } | { mode: 'edit'; index: number }
```

Add this constant directly under `interface RowError { index: number; message: string }`:

```tsx
const ADD_ROW_INDEX = -1
```

- [ ] **Step 2: Rename the cancel button label for new rows**

In `EditableRow`, change the Cancel button to read "Clear" when `isNew`:

```tsx
          <Button size="sm" variant="ghost" className="text-xs h-7" onClick={onCancel}>{isNew ? 'Clear' : 'Cancel'}</Button>
```

- [ ] **Step 3: Update `BillsQueue` state**

Replace:

```tsx
  const [editing, setEditing] = useState<EditingRow | null>(null)
```

with:

```tsx
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [addRowKey, setAddRowKey] = useState(0)
  const resetAddRow = () => setAddRowKey(k => k + 1)
```

- [ ] **Step 4: Update the mutations**

Replace `addMutation` and `updateMutation` with:

```tsx
  const addMutation = useMutation({
    mutationFn: addBill,
    onSuccess: () => {
      invalidateBills()
      setRowErrors(prev => prev.filter(e => e.index !== ADD_ROW_INDEX))
      resetAddRow()
    },
    onError: (e: unknown) => {
      const axiosDetail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      const msg = axiosDetail ?? (e instanceof Error ? e.message : 'Could not add bill')
      setRowErrors(prev => [...prev.filter(r => r.index !== ADD_ROW_INDEX), { index: ADD_ROW_INDEX, message: msg }])
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ index, bill }: { index: number; bill: BillIn }) => updateBill(index, bill),
    onSuccess: () => { invalidateBills(); setEditingIndex(null) },
  })
```

- [ ] **Step 5: Remove the "+ Add Bill" header button**

Change the header button group to contain only Post All:

```tsx
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handlePostAll}
            disabled={postingAll || bills.length === 0 || !canPost}
            title={!canPost ? 'Configure AP, checking, and expense accounts in Settings before posting' : undefined}
          >
            {postingAll ? 'Processing...' : 'Post All'}
          </Button>
        </div>
```

- [ ] **Step 6: Rewrite the `<tbody>`**

Replace the whole `<tbody>...</tbody>` block with:

```tsx
          <tbody>
            {bills.map(bill =>
              editingIndex === bill.index ? (
                <EditableRow
                  key={bill.index}
                  initial={bill}
                  isNew={false}
                  onSave={b => updateMutation.mutate({ index: bill.index, bill: b })}
                  onCancel={() => setEditingIndex(null)}
                />
              ) : (
                <BillRow
                  key={bill.index}
                  bill={bill}
                  canPost={canPost}
                  onEdit={() => setEditingIndex(bill.index)}
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
            {rowErrors.find(e => e.index === ADD_ROW_INDEX) && (
              <tr>
                <td colSpan={7} className="px-3 py-1 text-xs text-red-600 bg-red-50">
                  {rowErrors.find(e => e.index === ADD_ROW_INDEX)?.message}
                </td>
              </tr>
            )}
            <EditableRow
              key={`add-${addRowKey}`}
              isNew
              onSave={bill => addMutation.mutate(bill)}
              onCancel={resetAddRow}
            />
          </tbody>
```

The empty-state "No bills in queue" row is intentionally gone. The add row is always the last row, and `autoFocus` on its vendor input focuses the fresh row after each remount.

- [ ] **Step 7: Build and lint**

Run (from `frontend/`): `npm run build`
Expected: exits 0. If `tsc` reports `editing` or `EditingRow` unused/undefined, a reference from the old code was missed; grep for `editing` and fix.

Run (from `frontend/`): `npm run lint`
Expected: no errors in `src/pages/BillsQueue.tsx`.

- [ ] **Step 8: Backend regression check**

Run (from repo root): `uv run pytest tests/test_web_app.py -q`
Expected: all pass (no backend files changed).

- [ ] **Step 9: Commit**

```bash
git add frontend/src/pages/BillsQueue.tsx
git commit -m "feat(bills): keep a blank add row always open, reset after add"
```

---

### Task 3: Browser verification

**Files:** none modified.

- [ ] **Step 1: Start the app**

From repo root: `uv run uvicorn bill_processor.web.app:app --port 7432`
Open `http://localhost:7432` (Bills Queue is the default page). The server serves `frontend/dist`, so Task 2's `npm run build` must have run first.

- [ ] **Step 2: Check each spec behavior**

- Page loads with a blank blue editable row at the bottom of the table and the Vendor input focused. No "+ Add Bill" button.
- Type a vendor and an amount, press Enter. The bill appears above; the add row is blank again with Vendor focused.
- Press Enter on the blank row: "Vendor is required" appears, nothing is added.
- Type into the row, click Clear: fields reset to blank, date is today.
- Click Edit on an existing bill: that row becomes editable with Save/Cancel; the blank add row remains below.

- [ ] **Step 3: Record the result**

Report which checks passed. Any failure goes back to Task 2.
