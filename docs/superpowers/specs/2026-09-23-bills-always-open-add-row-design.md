# Bills Queue: Always-Open Add Row

**Date:** 2026-09-23
**Scope:** `frontend/src/pages/BillsQueue.tsx` only. No backend or API changes.

## Problem

The Bills Queue page requires clicking "+ Add Bill" to open one editable row, and
pressing "Add" saves the bill and closes the row. Entering several bills means
alternating between the button and the row. The Cash Entry page, by contrast,
always shows a blank row and keeps adding rows as they are filled. Bills should
feel the same.

## Decision

Keep the existing queue-per-row model (each "Add" writes one bill to
`data/bills_to_process.txt` via `POST /bills`). Change only the page's editing
behavior so a blank add row is always present.

## Behavior

1. **Blank add row always visible.** An `EditableRow` in add mode renders as
   the last body row of the table at all times, including when the queue is
   empty. The "+ Add Bill" header button and the "No bills in queue" empty-state
   row are removed.
2. **Add resets instead of closing.** After `addBill` succeeds, the add row
   resets to blank: vendor, amount, memo, check number, and bill type clear;
   date resets to today. Focus moves to the Vendor input.
3. **Cancel clears.** The add row's "Cancel" button becomes "Clear" and resets
   the fields the same way, without closing the row.
4. **Enter adds.** Pressing Enter in any input of the add row triggers the same
   validation and save as clicking "Add". Vendor autocomplete: Enter submits
   the text as typed, and the suggestion dropdown closes.
5. **Editing an existing bill is unchanged.** Clicking "Edit" swaps that bill's
   row for an `EditableRow` in edit mode with Save/Cancel. The blank add row
   stays visible below the list while editing.
6. **Validation is unchanged.** Vendor required, amount required and > 0, with
   the existing inline error messages and focus behavior. On validation failure
   nothing is saved and the row keeps its values.
7. **Add failure.** If `POST /bills` fails, the row keeps its values and the
   error surfaces in the existing `rowErrors` banner area under the table
   header (a new entry keyed to index `-1`, rendered above the add row). Cash
   Entry's error banner style is the reference.

## Implementation notes

- `EditingRow` state drops the `'add'` variant; it becomes
  `{ index: number } | null` for edit mode only.
- `EditableRow` gains an `onKeyDown` handler on its `<tr>` (or each input) that
  calls `handleSave` on Enter. `VendorInput` closes its dropdown on Enter.
- For the add row, `EditableRow` needs a way to reset after a successful save.
  Simplest: the parent remounts the add row by changing its `key` (an
  incrementing counter bumped in `addMutation.onSuccess`). `autoFocus` on the
  vendor input then gives focus to the fresh row for free.
- Clear button: same remount via the key counter.

## Testing

The frontend has no test suite. Verification is:

- `npm run build` in `frontend/` passes (type check + bundle).
- Browser check: load page with empty queue, see blank row; fill vendor and
  amount, press Enter; bill appears above, row is blank with focus on Vendor;
  repeat; Edit an existing bill while the add row remains visible; Clear resets.
- Backend tests unaffected: `uv run pytest tests/test_web_app.py` still passes.
