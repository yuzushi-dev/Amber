# Multi-File Upload (Persistent Queue) — Design
Date: 2026-01-28

## Goal
Enable multi-file uploads with per-file progress, background continuity across modal close and page reload, and a global indicator. Concurrency is limited to 1 file at a time. Failed items do not block others; users can retry.

## Scope
- Frontend-only changes. Backend already accepts single-file POST `/documents` and processes in parallel.
- Persist queue state and file blobs across reloads.
- Global progress indicator and title/notification behavior moved outside the modal.

## Non-Goals
- True resumable uploads (no chunking/tus/S3 multipart). Mid-upload reload becomes “interrupted” and requires re-upload.

## Architecture Overview
Create a global Zustand store `useUploadStore` responsible for queue state and background worker. Store metadata in localStorage, and file blobs in IndexedDB. Runtime resources (AbortController, SSEManager, polling timers) are maintained in module-level maps and never persisted.

### State Model (per item)
- `id`, `fileMeta` (name, size, type, lastModified), `fileKey` (IDB key)
- `status`: queued | uploading | processing | ready | completed | failed | interrupted | missingFile
- `uploadProgress` (0–100), `stageProgress` (0–100)
- `documentId`, `eventsUrl`, `error`, `attempts`, `createdAt`

### Persistence
- Zustand `persist` stores queue metadata only.
- File blobs stored in IndexedDB (prefer a small library like `idb-keyval` or `localforage` to avoid hand-rolled IDB).
- On rehydrate, attempt to restore blobs; if missing, mark item `missingFile` and `interrupted`.

### Upload Worker (Concurrency = 1)
- Background queue worker selects the next queued item.
- Uses `AbortController` for cancellation.
- On success: store `documentId` and start SSE + polling.
- On terminal state: cleanup runtime resources, advance queue.

### SSE + Polling
- Reuse existing SSEManager; per item connection is created after upload.
- Polling fallback (3s) remains; SSE retry (3 attempts).
- Cleanup on success/fail/remove/retry.

### Progress Aggregation
- Per-file progress is upload-based while uploading, then stage-based.
- Global progress is size-weighted across non-failed items only.
- Failed items are excluded from the denominator.

## UI/UX
### UploadWizard
- Dropzone accepts multiple files.
- List of items with per-file progress, status, retry/remove/cancel.
- Summary header: “Uploading 1/5” + total progress bar.

### Global Indicator
- Always visible (e.g., MainLayout). Shows active count, failed count, and a small progress ring.
- Click to open UploadWizard via store.

### Notifications + Title
- New `UploadGlobalEffects` component (always mounted) handles:
  - Browser notifications on terminal states (hidden tab only).
  - Title progress set to aggregate percent and label (`Uploading 1/5` / `Processing 2/5`).
- Request notification permission once per session or after first enqueue.

## Error Handling
- If one file fails, others continue.
- Retry resets state, closes old SSE/polling, re-queues item.
- If reload occurs mid-upload, mark as `interrupted` and allow one-click retry if blob exists.

## Testing
- Unit: queue actions, persistence/rehydration, retry logic, progress aggregation.
- Integration: multi-file upload, modal close/reopen, reload mid-upload, retry failed item.

## Rollout
- Replace modal-local state with store.
- Render UploadWizard once at layout level; update existing open/close triggers to use store.
- No backend changes required.
