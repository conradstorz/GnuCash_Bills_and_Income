# Shutdown Button Design

**Date:** 2026-04-27  
**Status:** Approved

## Summary

Add a styled "Shut Down" button to the sidebar that stops the uvicorn server and attempts to close the browser tab, gated by a React confirmation modal.

## Scope

- Frontend only: `frontend/src/components/Sidebar.tsx`
- Backend: no changes — `/api/shutdown` already exists (app.py:690)

## UI Placement

Bottom of the sidebar, below the `flex-1` nav block. Styled in muted red (`text-red-400 hover:bg-red-900/40`) to signal danger without being alarming.

## State

Two boolean states local to `Sidebar.tsx`:
- `showConfirm` — controls modal visibility
- `isShuttingDown` — disables the confirm button and shows loading text while the request is in flight

## Confirmation Modal

A fixed full-screen overlay (`bg-black/50`) containing a centered card (`bg-slate-800`, rounded, ~320px wide):

| Element | Detail |
|---|---|
| Title | "Shut down server?" |
| Description | "This will stop the server and close this tab." |
| Cancel button | Slate ghost style; sets `showConfirm = false` |
| Shut Down button | Solid red; triggers shutdown flow |

## Shutdown Flow

1. Set `isShuttingDown = true` (button shows "Shutting down…")
2. POST `/api/shutdown`
3. Call `window.close()`

`window.close()` only works on tabs opened by script. The `.bat` launcher opens the browser via `start`, so behavior is browser-dependent. If it fails, the server stops anyway and the tab shows a connection-refused page — acceptable, no fallback needed.

## Files Changed

- `frontend/src/components/Sidebar.tsx` — add state, shutdown button, modal overlay
