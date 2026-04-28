# Bill Entry Validation Design

**Date:** 2026-04-27  
**Status:** Approved

## Summary

Add client-side validation to the `EditableRow` component in `BillsQueue.tsx` so that clicking Add/Save with missing or invalid required fields highlights the problem fields, shows a per-field error label, and moves focus to the first invalid field.

## Scope

- One file modified: `frontend/src/pages/BillsQueue.tsx`
- No backend changes

## Required Fields

| Field | Invalid when | Error message |
|---|---|---|
| Vendor | empty string after trim | "Vendor is required" |
| Amount | empty, NaN, or ≤ 0 | "Amount is required" / "Amount must be greater than 0" |

Memo, date (pre-filled with today), and check number are optional — no validation needed.

## State

Add to `EditableRow`:
```tsx
const [errors, setErrors] = useState<{ vendor?: string; amount?: string }>({})
```

Starts empty. Set on failed save attempt. Per-field error clears as the user edits that field.

## Validation Flow (on Add/Save click)

1. Compute `newErrors`:
   - If `vendor.trim()` is empty → `newErrors.vendor = "Vendor is required"`
   - If `amount` is empty or `isNaN(parseFloat(amount))` → `newErrors.amount = "Amount is required"`
   - Else if `parseFloat(amount) <= 0` → `newErrors.amount = "Amount must be greater than 0"`
2. If `newErrors` has any keys → `setErrors(newErrors)`, focus first invalid field, `return`
3. Otherwise → `setErrors({})`, call `onSave(...)`

## Focus on First Invalid

- Add `useRef<HTMLInputElement>(null)` for vendor and amount inputs
- After setting errors, `vendorRef.current?.focus()` if vendor invalid, else `amountRef.current?.focus()`
- `VendorInput` must accept a `ref` prop forwarded to its inner `<Input>` via `forwardRef`

## Visual Treatment

**Invalid input:** replace normal border with `border-red-500` (Tailwind class on the `<Input>`)

**Error label:** directly below the input inside the same `<td>`:
```tsx
{errors.vendor && <p className="text-xs text-red-500 mt-0.5">{errors.vendor}</p>}
```

**Clearing errors:** each field's `onChange` clears its own error key:
```tsx
onChange={v => { setVendor(v); if (errors.vendor) setErrors(e => ({ ...e, vendor: undefined })) }}
```

## Files Changed

- `frontend/src/pages/BillsQueue.tsx` — add `errors` state, validation in `handleSave`, refs, error labels, `forwardRef` on `VendorInput`
