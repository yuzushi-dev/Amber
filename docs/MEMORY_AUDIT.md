# Amber Frontend Memory Audit

Scope: `/home/daniele/Amber/frontend` (React 19 / TypeScript / Vite).
Method: static inspection of source files. Each finding below is a confirmed fact with file:line evidence. No recommendations.

Framework/dependency facts:
- `react` 19.2.0, `react-dom` 19.2.0 (frontend/package.json:44-45).
- `three` 0.149.0, `react-force-graph-2d` 1.22.0, `react-force-graph-3d` 1.22.0 (frontend/package.json:46-47,55).
- `react-pdf` 9.1.1 (frontend/package.json:50).
- `@tanstack/react-virtual` 3.13.13 is declared as a dependency (frontend/package.json:31). `grep` for `useVirtualizer` / `react-virtual` across `src` returns zero matches: the virtualization library is installed but not imported anywhere in `src`.

---

**FINDING-1**: [WebGL/Three.js resources not released]
- File: src/features/documents/components/Graph/ThreeGraph.tsx:237-328
- Code: `const nodeThreeObject = useCallback((node: ForceGraphNode) => { const group = new THREE.Group(); ... const geometry = new THREE.SphereGeometry(baseSize, 32, 32); ... const coreMaterial = new THREE.MeshStandardMaterial({...}); ... const innerGlowGeometry = new THREE.SphereGeometry(baseSize * 1.2, 24, 24); ... const outerGlowGeometry = new THREE.SphereGeometry(baseSize * 1.8, 16, 16); ... const texture = new THREE.CanvasTexture(canvas); const spriteMaterial = new THREE.SpriteMaterial({ map: texture, ... });`
- Fact: For every node, `nodeThreeObject` allocates one `THREE.Group`, three `THREE.SphereGeometry` instances, one `MeshStandardMaterial`, two `MeshBasicMaterial`, one HTMLCanvasElement, one `THREE.CanvasTexture`, and one `THREE.SpriteMaterial`. No call to `.dispose()` on any geometry, material, or texture exists in the file. The component has no unmount cleanup that disposes the `ForceGraph3D` WebGL renderer; the only `return` cleanup in the file is `resizeObserver.disconnect()` at line 208.

**FINDING-2**: [Unbounded state growth feeding Three.js allocations]
- File: src/features/graph/pages/GlobalGraphPage.tsx:227-241
- Code: `setGraphData(prev => { const nodeMap = new Map(prev.nodes.map(n => [n.id, n])); ... neighborhood.nodes.forEach(n => nodeMap.set(n.id, n)); ... return { nodes: Array.from(nodeMap.values()), edges: [...prev.edges, ...newEdges] }; });`
- Fact: In view mode, `handleNodeClick` merges fetched neighborhood nodes/edges into the existing `graphData` state Map and array. There is no cap on `graphData.nodes` or `graphData.edges`. The merged `graphData` is passed to `ThreeGraph` (lines 321-327); each growth causes `ThreeGraph`'s `graphData` `useMemo` to recompute (ThreeGraph.tsx:126-159) and `nodeThreeObject` to allocate new Three.js objects per node (see FINDING-1).

**FINDING-3**: [No virtualization — large list rendered to DOM]
- File: src/features/documents/components/DocumentLibrary.tsx:111 and 420
- Code: `const response = await apiClient.get<Document[]>('/documents', { params: { limit: 10000 } })` ... `{filteredDocuments.map((doc, idx) => {`
- Fact: The document list query requests up to 10000 documents. `filteredDocuments` is rendered via `.map()` at line 420 with no virtualization. All returned document rows are mounted into the DOM simultaneously.

**FINDING-4**: [Fuse.js index rebuilt every render]
- File: src/features/documents/components/DocumentLibrary.tsx:128-131
- Code: `const filteredDocuments = useFuzzySearch(documents || [], searchQuery, { keys: ['title', 'filename', 'source_type'], threshold: 0.4, })`
- Fact: `documents || []` produces a new array identity on every render when `documents` is undefined, and the options object containing `keys: [...]` is a new array/object literal on every render. `useFuzzySearch` memoizes the `Fuse` instance with `useMemo(..., [items, keys, threshold, minMatchCharLength])` (src/hooks/useFuzzySearch.ts:29-41). Because `keys` (and `items` when undefined) change identity each render, `new Fuse(items, fuseOptions)` is reconstructed every render over the items array (up to 10000 documents per FINDING-3).

**FINDING-5**: [No virtualization — unbounded chat message list]
- File: src/features/chat/components/MessageList.tsx:72-89
- Code: `messages.map((msg, index) => { ... return ( <MessageItem key={msg.id} message={msg} ... /> ); })`
- Fact: `MessageList` renders the entire `messages` array via `.map()` with no virtualization. The backing store `useChatStore` (src/features/chat/store.ts:53-68) holds `messages: Message[]`; `addMessage` appends with `messages: [...state.messages, message]` and there is no size cap. `clearMessages` exists but is only invoked explicitly (e.g. ChatContainer.tsx:167,236).

**FINDING-6**: [Infinite-scroll list accumulates without cap or virtualization]
- File: src/components/layout/ContextSidebar.tsx:190-193 and 342
- Code: `setRecentConversations(prev => { ... return [...prev, ...uniqueNewItems] })` ... `recentConversations.map((conversation) => {`
- Fact: `loadMore` appends fetched conversations to `recentConversations` with `[...prev, ...uniqueNewItems]` (lines 190-193). There is no upper bound on the array. The full array is rendered via `.map()` at line 342 with no virtualization.

**FINDING-7**: [Infinite-scroll list accumulates without cap or virtualization, plus per-page query cache]
- File: src/features/chat/components/ChatHistoryPanel.tsx:48 and 54-57
- Code: `useQuery({ queryKey: ['chat-history-client', offset], queryFn: () => chatApi.list({ limit: PAGE_SIZE, offset }), })` ... `setAllConversations(prev => offset === 0 ? data.conversations : [...prev, ...data.conversations.filter(c => !prev.some(p => p.request_id === c.request_id))])`
- Fact: `allConversations` accumulates appended page results with no upper bound and is rendered without virtualization. Separately, the React Query key includes `offset` (line 48), so each scrolled page (offset value) creates a distinct cache entry. The global query client sets `gcTime: 5 * 60_000` (src/lib/query-client.ts:7), so each page response is retained in the query cache for 5 minutes after becoming unused, in addition to being held in `allConversations`.

**FINDING-8**: [Map state grows by messageId, freed only on reset]
- File: src/features/chat/store/citationStore.ts:49-54
- Code: `registerCitations: (messageId, newCitations) => set((state) => { const next = new Map(state.citations); next.set(messageId, newCitations); return { citations: next }; }),`
- Fact: `citations` is a `Map<string, Citation[]>`. `registerCitations` adds an entry per `messageId` and never deletes individual entries. The only code path that clears the Map is `reset()` (lines 64-70), which replaces it with `new Map()`. There is no per-message or size-based eviction.

**FINDING-9**: [Blob object URL not revoked on unmount]
- File: src/features/documents/components/DocumentViewer.tsx:28,59-61,70-78
- Code: `const url = URL.createObjectURL(blob); setBlobUrl(url)` ... `const handleClose = () => { setOpen(false); if (blobUrl) { URL.revokeObjectURL(blobUrl); setBlobUrl(null); } setTextContent(null); setState('idle') }`
- Fact: `blobUrl` (from `URL.createObjectURL(blob)`) and `textContent` (full file text via `blob.text()`) are stored in component state. They are released only inside `handleClose`, which runs from the dialog `onOpenChange` handler (line 171). There is no `useEffect` cleanup returning a function that revokes `blobUrl` or clears `textContent` on component unmount. The file (PDF/HTML blob or full text string) referenced by the object URL / state remains held if the component unmounts without `handleClose` running.

**FINDING-10**: [pdf.js document proxy never destroyed]
- File: src/features/documents/components/PDFViewer.tsx:23,32,38
- Code: `const pdfDocumentRef = useRef<PDFDocumentProxy | null>(null);` ... `pdfDocumentRef.current = null;` (inside useEffect at line 32) ... `function onDocumentLoadSuccess(pdf: PDFDocumentProxy) { ... pdfDocumentRef.current = pdf; ... }`
- Fact: `onDocumentLoadSuccess` stores the `PDFDocumentProxy` in `pdfDocumentRef`. On file change, the `useEffect` at lines 26-34 sets `pdfDocumentRef.current = null` without calling `.destroy()`. No `useEffect` cleanup or unmount handler calls `pdfDocumentRef.current?.destroy()`. The pdf.js document proxy (and its worker transport / parsed page resources) is dereferenced but `destroy()` is never invoked.

**FINDING-11**: [EventSource hook has no unmount cleanup; consumers do not call stop]
- File: src/features/admin/hooks/useInstallProgress.ts:42-48,64-65
- Code: `const stop = useCallback(() => { if (eventSourceRef.current) { eventSourceRef.current.close(); eventSourceRef.current = null; } setIsInstalling(false); }, []);` ... `const eventSource = new EventSource(url); eventSourceRef.current = eventSource;`
- Fact: `startInstall` opens an `EventSource`. `stop()` (which closes it) is invoked only on the SSE `complete` event (line 97), the SSE `error` event (line 113), the `onerror` handler (line 121), or by an external caller. There is no `useEffect` with a cleanup function in this hook. The two consumers destructure `{ startInstall, progress, isInstalling, error: installError }` only and do not destructure or call `stop`: src/features/setup/components/FeatureSetup.tsx:54 and src/features/admin/components/OptionalFeaturesManager.tsx:83. If a consumer unmounts while installation is in progress, the `EventSource` is not closed.

**FINDING-12**: [Streaming fetch reader and AbortController not aborted on unmount]
- File: src/features/chat/hooks/useChatStream.ts:160-209,237 and src/features/chat/components/ChatContainer.tsx:67
- Code: `const reader = response.body.getReader() ... while (true) { const { done, value } = await reader.read(); if (done) { ... break } ... }` ... hook return `}, [])` (startStream useCallback) ... ChatContainer: `const { startStream, isStreaming, resetConversation, setConversationId } = useChatStream()`
- Fact: `startStream` runs a `while (true)` loop reading from `response.body.getReader()` and calls `updateLastMessage` (zustand store mutation) on each parsed event. `useChatStream` exposes `stopStream` (which calls `abortControllerRef.current.abort()`, lines 54-60) but contains no `useEffect` cleanup. `ChatContainer` (the consumer) destructures `useChatStream()` without `stopStream` (line 67) and has no unmount handler that aborts the stream. On unmount during an active stream, `abortController.abort()` is not called, the reader loop continues, and `updateLastMessage` continues writing to `useChatStore`.

**FINDING-13**: [Forced per-chunk console logging during streaming]
- File: src/features/chat/hooks/useChatStream.ts:20,34-38,175
- Code: `const debugEnabledRef = useRef(true) // Force debug for troubleshooting` ... `const debugLog = (...args: unknown[]) => { if (debugEnabledRef.current) { console.log('[ChatStream]', ...args) } }` ... `debugLog(\`Received chunk: len=${chunk.length}, preview=${chunk.substring(0, 50).replace(/\n/g, '\\n')}\`)`
- Fact: `debugEnabledRef` is initialized to `true` unconditionally. `debugLog` is called for every received stream chunk (line 175) and for every processed event (line 203). Each call invokes `console.log` with string arguments. Browser DevTools retain logged argument values for the lifetime of the console session.

**FINDING-14**: [EventSource torn down and recreated on every status change]
- File: src/features/documents/components/LiveStatusBadge.tsx:30,55,101,109-115
- Code: `useEffect(() => { ... manager = new SSEManager(monitorUrl, ...); manager.connect(); ... return () => { mounted = false; if (manager) { manager.disconnect() } } }, [documentId, status, onComplete])`
- Fact: The `useEffect` that creates and connects the `SSEManager` lists `status` in its dependency array (line 115). `status` is updated inside the SSE message handler via `setStatus(data.status)` (line 61). Each status update triggers the effect cleanup (`manager.disconnect()`, closing the EventSource) and a re-run that creates a new `SSEManager` and a new `EventSource`. Cleanup is present, but the EventSource is destroyed and re-created on every status transition.

**FINDING-15**: [setTimeout without clearTimeout]
- File: src/features/chat/components/CitationExplorer.tsx:54-64
- Code: `useEffect(() => { if (selectedCitationId) { ... const targetCitation = activeCitations.find(...); if (targetCitation) { setTimeout(() => scrollToCard(targetCitation.id), 100) } } }, [selectedCitationId, rawCitations, activeCitations, scrollToCard])`
- Fact: `setTimeout(() => scrollToCard(targetCitation.id), 100)` is called inside a `useEffect`. The timeout id is not stored and the effect returns no cleanup function. No `clearTimeout` is called. The scheduled callback executes 100ms later regardless of whether `selectedCitationId`/dependencies changed or the component unmounted in that window.

---

Patterns verified and found to have correct cleanup (no finding):
- src/components/ui/constellation-loader.tsx: `requestAnimationFrame` loop and all canvas `addEventListener` calls are cancelled / removed in the effect cleanup (lines 203-212).
- src/components/layout/CommandDock.tsx:54-55,70-71: `resize` and `keydown` listeners removed in cleanup.
- src/features/admin/components/EmbeddingMigration.tsx:45-72,104-128: `setInterval` timers cleared on unmount and on status change.
- Admin polling pages with `setInterval` (ConnectorsList.tsx, MetricsDashboard.tsx, RagasSubPanel.tsx, JobsPage.tsx, QueuesPage.tsx, JobsAndQueuesPage.tsx, DataRetentionPage.tsx, BackupPage.tsx, FeatureSetup.tsx): each returns `clearInterval` in the effect cleanup.
- src/features/documents/stores/useUploadStore.ts: file blobs are stored in IndexedDB (`idb-keyval`), not in memory state; `partialize` persists only metadata to localStorage; `globalPollingTimer` self-clears when no items are `processing` (lines 526-533).
- src/features/admin/components/Connectors/ConnectorContentBrowser.tsx: list state is replaced per page (page-based), not accumulated.
