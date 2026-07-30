import type { CashEntryRow } from '../api/cash'

/** A single editable row from the Cash Entry table (amount is the raw string
 *  the user typed, before parsing). */
export interface DraftRow {
  account_guid: string
  memo: string
  amount: string
}

export interface BuildResult {
  /** Rows that passed validation, ready to POST. */
  entries: CashEntryRow[]
  /** Human-readable problems. Non-empty => do NOT submit; show these to the user. */
  errors: string[]
}

/**
 * Turn the raw table rows into the entries to submit — WITHOUT ever silently
 * discarding a row the user filled in.
 *
 * Rules:
 *  - A completely untouched row (no account AND blank amount) is ignored. This
 *    is the ONLY silent skip, and it only drops rows that carry no data.
 *  - Any row the user touched must be valid, or it becomes an error:
 *      * an account must be selected, and
 *      * the amount must be a finite, NON-ZERO number.
 *  - Negative amounts are valid and preserved. A negative moves cash OUT of
 *    Cash-on-hand into the selected account (e.g. reloading the dollar-bill
 *    changer from the drawer). The backend supports this; the old UI silently
 *    dropped it via `parseFloat(amount) > 0`, losing the entry with no warning.
 */
export function buildCashEntries(rows: DraftRow[]): BuildResult {
  const entries: CashEntryRow[] = []
  const errors: string[] = []

  rows.forEach((r, i) => {
    const label = `Row ${i + 1}`
    const hasAccount = r.account_guid.trim() !== ''
    // Allow thousands separators; reject anything else non-numeric below.
    const rawAmount = r.amount.replace(/,/g, '').trim()
    const hasAmount = rawAmount !== ''

    // Untouched row — the only silent skip.
    if (!hasAccount && !hasAmount) return

    if (!hasAccount) {
      errors.push(`${label}: select an account (or clear the amount to remove the row).`)
      return
    }
    if (!hasAmount) {
      errors.push(`${label}: enter an amount (or remove the row).`)
      return
    }
    const amount = Number(rawAmount)
    if (!Number.isFinite(amount)) {
      errors.push(`${label}: "${r.amount}" is not a valid amount.`)
      return
    }
    if (amount === 0) {
      errors.push(`${label}: amount cannot be zero.`)
      return
    }

    entries.push({ account_guid: r.account_guid, memo: r.memo, amount })
  })

  if (errors.length === 0 && entries.length === 0) {
    errors.push('Add at least one entry with an account and amount.')
  }

  return { entries, errors }
}
