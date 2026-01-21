/**
 * Admin API Client
 * =================
 * 
 * API functions for admin endpoints: jobs, config, curation, maintenance.
 */

import { apiClient } from './api-client'

// =============================================================================
// Types
// =============================================================================

export interface JobInfo {
    task_id: string
    task_name: string | null
    status: string
    progress: number | null
    progress_message: string | null
    result: Record<string, unknown> | null
    error: string | null
    started_at: string | null
    completed_at: string | null
    runtime_seconds: number | null
    retries: number
}

export interface JobListResponse {
    jobs: JobInfo[]
    total: number
    active_count: number
    reserved_count: number
}

export interface QueueInfo {
    queue_name: string
    message_count: number
    consumer_count: number
}

export interface WorkerInfo {
    hostname: string
    status: string
    active_tasks: number
    processed_total: number
    concurrency: number
    queues: string[]
}

export interface QueuesResponse {
    queues: QueueInfo[]
    workers: WorkerInfo[]
    total_active_tasks: number
}

export interface TenantConfig {
    tenant_id: string
    config: Record<string, unknown>
    top_k: number
    expansion_depth: number
    similarity_threshold: number
    reranking_enabled: boolean
    hyde_enabled: boolean
    graph_expansion_enabled: boolean
    embedding_model: string
    generation_model: string
    system_prompt_override: string | null
    hybrid_ocr_enabled: boolean
    ocr_text_density_threshold: number
    weights?: {
        vector_weight: number
        graph_weight: number
        rerank_weight: number
    }
}

export interface ConfigSchemaField {
    name: string
    type: 'number' | 'boolean' | 'string' | 'select'
    label: string
    description: string
    default: unknown
    min?: number
    max?: number
    step?: number
    options?: string[]
    group: string
    read_only?: boolean
}

export interface ConfigSchema {
    fields: ConfigSchemaField[]
    groups: string[]
}

export interface FlagSummary {
    id: string
    tenant_id: string
    type: string
    status: string
    reported_by: string
    target_type: string
    target_id: string
    comment: string | null
    snippet_preview: string | null
    created_at: string
    resolved_at: string | null
    resolved_by: string | null
}

export interface FlagDetail extends FlagSummary {
    context: {
        query_text?: string
        chunk_text?: string
        chunk_id?: string
        entity_id?: string
        entity_name?: string
        document_id?: string
        document_title?: string
        request_id?: string
        retrieval_trace?: Record<string, unknown>
    }
    resolution_notes: string | null
    merge_target_id: string | null
}

export interface FlagListResponse {
    flags: FlagSummary[]
    total: number
    pending_count: number
    resolved_count: number
}

export interface CurationStats {
    total_flags: number
    pending_count: number
    accepted_count: number
    rejected_count: number
    merged_count: number
    avg_resolution_time_hours: number | null
    flags_by_type: Record<string, number>
}

export interface DatabaseStats {
    documents_total: number
    documents_ready: number
    documents_processing: number
    documents_failed: number
    chunks_total: number
    entities_total: number
    relationships_total: number
    communities_total: number
}

export interface CacheStats {
    memory_used_bytes: number
    memory_max_bytes: number
    memory_usage_percent: number
    keys_total: number
    hit_rate: number | null
    miss_rate: number | null
    evictions: number
}

export interface SystemStats {
    database: DatabaseStats
    cache: CacheStats
    vector_store: {
        collections_count: number
        vectors_total: number
        index_size_bytes: number
    }
    timestamp: string
}

export interface MaintenanceResult {
    operation: string
    status: string
    message: string
    items_affected: number
    duration_seconds: number
}

export interface VectorCollectionInfo {
    name: string
    count: number
    dimensions: number | null
    index_type: string | null
    memory_mb: number
}

export interface VectorCollectionsResponse {
    collections: VectorCollectionInfo[]
}

export interface ChatHistoryItem {
    request_id: string
    tenant_id: string
    query_text: string | null
    response_preview: string | null
    model: string
    provider: string
    total_tokens: number
    cost: number
    has_feedback: boolean
    feedback_score: number | null
    created_at: string
}

export interface ChatHistoryResponse {
    conversations: ChatHistoryItem[]
    total: number
    limit: number
    offset: number
}

export interface ConversationDetail {
    request_id: string
    tenant_id: string
    trace_id: string | null
    query_text: string | null
    response_text: string | null
    model: string
    provider: string
    input_tokens: number
    output_tokens: number
    total_tokens: number
    cost: number
    feedback: {
        score: number
        is_positive: boolean
        comment: string | null
        correction: string | null
        created_at: string | null
    } | null
    metadata: Record<string, unknown>
    created_at: string
}

// =============================================================================
// Jobs API
// =============================================================================

export const jobsApi = {
    list: async (params?: { status?: string; task_type?: string; limit?: number }) => {
        const response = await apiClient.get<JobListResponse>('/admin/jobs', { params })
        return response.data
    },

    get: async (taskId: string) => {
        const response = await apiClient.get<JobInfo>(`/admin/jobs/${taskId}`)
        return response.data
    },

    cancel: async (taskId: string, terminate = false) => {
        const response = await apiClient.post<{ task_id: string; status: string; message: string }>(
            `/admin/jobs/${taskId}/cancel`,
            null,
            { params: { terminate } }
        )
        return response.data
    },

    getQueues: async () => {
        const response = await apiClient.get<QueuesResponse>('/admin/jobs/queues/status')
        return response.data
    },
}

// =============================================================================
// Config API
// =============================================================================

export const configApi = {
    getSchema: async () => {
        const response = await apiClient.get<ConfigSchema>('/admin/config/schema')
        return response.data
    },

    getTenant: async (tenantId: string) => {
        const response = await apiClient.get<TenantConfig>(`/admin/config/tenants/${tenantId}`)
        return response.data
    },

    updateTenant: async (tenantId: string, config: Partial<TenantConfig>) => {
        const response = await apiClient.put<TenantConfig>(`/admin/config/tenants/${tenantId}`, config)
        return response.data
    },

    resetTenant: async (tenantId: string) => {
        const response = await apiClient.post<{ status: string; message: string }>(
            `/admin/config/tenants/${tenantId}/reset`
        )
        return response.data
    },
}

// =============================================================================
// Curation API
// =============================================================================

export const curationApi = {
    listFlags: async (params?: { status?: string; flag_type?: string; limit?: number; offset?: number }) => {
        const response = await apiClient.get<FlagListResponse>('/admin/curation/flags', { params })
        return response.data
    },

    getFlag: async (flagId: string) => {
        const response = await apiClient.get<FlagDetail>(`/admin/curation/flags/${flagId}`)
        return response.data
    },

    resolveFlag: async (flagId: string, resolution: { action: string; notes?: string; merge_target_id?: string }) => {
        const response = await apiClient.put<FlagDetail>(`/admin/curation/flags/${flagId}`, resolution)
        return response.data
    },

    getStats: async () => {
        const response = await apiClient.get<CurationStats>('/admin/curation/stats')
        return response.data
    },
}

// =============================================================================
// Maintenance API
// =============================================================================

export const maintenanceApi = {
    getStats: async () => {
        const response = await apiClient.get<SystemStats>('/admin/maintenance/stats')
        return response.data
    },

    clearCache: async (pattern?: string) => {
        const response = await apiClient.post<MaintenanceResult>(
            '/admin/maintenance/cache/clear',
            null,
            { params: pattern ? { pattern } : undefined }
        )
        return response.data
    },

    pruneOrphans: async () => {
        const response = await apiClient.post<MaintenanceResult>('/admin/maintenance/prune/orphans')
        return response.data
    },

    getReconciliation: async () => {
        const response = await apiClient.get<{
            sync_status: string
            last_sync_at: string | null
            sync_lag_seconds: number
            pending_writes: number
            failed_writes: number
            retry_queue_depth: number
            errors: string[]
        }>('/admin/maintenance/reconciliation')
        return response.data
    },

    triggerReindex: async (collection?: string) => {
        const response = await apiClient.post<MaintenanceResult>(
            '/admin/maintenance/reindex',
            null,
            { params: collection ? { collection } : undefined }
        )
        return response.data
    },

    getQueryMetrics: async (limit = 100, tenantId?: string) => {
        const response = await apiClient.get<QueryMetrics[]>('/admin/maintenance/metrics/queries', {
            params: { limit, tenant_id: tenantId }
        })
        return response.data
    },
}

export interface QueryMetrics {
    query_id: string
    tenant_id: string
    query: string
    timestamp: string

    // Operation type
    operation: string
    // Response text
    response: string | null

    // Latency
    embedding_latency_ms: number
    retrieval_latency_ms: number
    reranking_latency_ms: number
    generation_latency_ms: number
    total_latency_ms: number

    // Retrieval
    chunks_retrieved: number
    chunks_used: number
    cache_hit: boolean

    // Generation
    tokens_used: number
    input_tokens: number
    output_tokens: number
    cost_estimate: number
    model: string | null
    provider: string | null
    success: boolean
    error_message: string | null
    conversation_id: string | null

    // Quality
    sources_cited: number
    answer_length: number
}

// =============================================================================
// Vector Store API
// =============================================================================

export const vectorStoreApi = {
    getCollections: async () => {
        const response = await apiClient.get<VectorCollectionsResponse>('/admin/maintenance/vectors/collections')
        return response.data
    },

    deleteCollection: async (collectionName: string) => {
        const response = await apiClient.delete<MaintenanceResult>(`/admin/maintenance/vectors/collections/${collectionName}`)
        return response.data
    },
}

// =============================================================================
// Chat History API
// =============================================================================

export const chatHistoryApi = {
    list: async (params?: { limit?: number; offset?: number; tenant_id?: string }) => {
        const response = await apiClient.get<ChatHistoryResponse>('/admin/chat/history', { params })
        return response.data
    },

    getDetail: async (requestId: string) => {
        const response = await apiClient.get<ConversationDetail>(`/admin/chat/history/${requestId}`)
        return response.data
    },

    delete: async (requestId: string) => {
        await apiClient.delete(`/admin/chat/history/${requestId}`)
    },
}

// =============================================================================
// Ragas Benchmark API
// =============================================================================

export interface RagasStats {
    total_runs: number
    completed_runs: number
    failed_runs: number
    avg_faithfulness: number | null
    avg_relevancy: number | null
}

export interface RagasDataset {
    name: string
    sample_count: number
    path: string
}

export interface BenchmarkRunSummary {
    id: string
    tenant_id: string
    dataset_name: string
    status: string
    metrics: Record<string, number> | null
    error_message: string | null
    started_at: string | null
    completed_at: string | null
    created_at: string
}

export interface BenchmarkRunDetail extends BenchmarkRunSummary {
    details: Array<Record<string, unknown>> | null
    config: Record<string, unknown> | null
    error_message: string | null
}

export interface RunBenchmarkResponse {
    benchmark_run_id: string
    task_id: string
    status: string
    message: string
}

export const ragasApi = {
    getStats: async () => {
        const response = await apiClient.get<RagasStats>('/admin/ragas/stats')
        return response.data
    },

    getDatasets: async () => {
        const response = await apiClient.get<RagasDataset[]>('/admin/ragas/datasets')
        return response.data
    },

    uploadDataset: async (file: File) => {
        const formData = new FormData()
        formData.append('file', file)
        const response = await apiClient.post<{ filename: string; samples: number; path: string; message: string }>(
            '/admin/ragas/datasets',
            formData,
            { headers: { 'Content-Type': 'multipart/form-data' } }
        )
        return response.data
    },

    deleteRun: async (runId: string) => {
        const response = await apiClient.delete<{ message: string }>(`/admin/ragas/runs/${runId}`)
        return response.data
    },

    deleteDataset: async (filename: string) => {
        const response = await apiClient.delete<{ message: string }>(`/admin/ragas/datasets/${filename}`)
        return response.data
    },

    runBenchmark: async (params: { dataset_name: string; metrics?: string[] }) => {
        const response = await apiClient.post<RunBenchmarkResponse>('/admin/ragas/run-benchmark', params)
        return response.data
    },

    getJobStatus: async (jobId: string) => {
        const response = await apiClient.get<BenchmarkRunDetail>(`/admin/ragas/job/${jobId}`)
        return response.data
    },

    listRuns: async (params?: { limit?: number; offset?: number; status_filter?: string }) => {
        const response = await apiClient.get<BenchmarkRunSummary[]>('/admin/ragas/runs', { params })
        return response.data
    },

    getComparison: async (runIds: string[]) => {
        const response = await apiClient.get<{ runs: BenchmarkRunSummary[]; count: number }>(
            '/admin/ragas/comparison',
            { params: { run_ids: runIds.join(',') } }
        )
        return response.data
    },
}

// =============================================================================
// API Key Management API
// =============================================================================

export interface ApiKeyResponse {
    id: string
    name: string
    prefix: string
    is_active: boolean
    scopes: string[]
    tenants: Array<{ id: string; name: string }>
    last_chars: string
    created_at: string
    last_used_at: string | null
}

export interface CreatedKeyResponse extends ApiKeyResponse {
    key: string
}

export interface CreateKeyRequest {
    name: string
    scopes?: string[]
    prefix?: string
}

export interface MeResponse {
    name: string
    scopes: string[]
    tenant_id: string | null
}

export const keysApi = {
    list: async () => {
        const response = await apiClient.get<ApiKeyResponse[]>('/admin/keys')
        return response.data
    },

    create: async (data: CreateKeyRequest) => {
        const response = await apiClient.post<CreatedKeyResponse>('/admin/keys', data)
        return response.data
    },

    revoke: async (keyId: string) => {
        await apiClient.delete(`/admin/keys/${keyId}`)
    },

    me: async () => {
        const response = await apiClient.get<MeResponse>('/admin/keys/me')
        return response.data
    },

    update: async (keyId: string, data: { name?: string; scopes?: string[] }) => {
        const response = await apiClient.patch<ApiKeyResponse>(`/admin/keys/${keyId}`, data)
        return response.data
    },

    linkTenant: async (keyId: string, tenantId: string, role = 'user') => {
        await apiClient.post(`/admin/keys/${keyId}/tenants`, { tenant_id: tenantId, role })
    },

    unlinkTenant: async (keyId: string, tenantId: string) => {
        await apiClient.delete(`/admin/keys/${keyId}/tenants/${tenantId}`)
    },
}

// =============================================================================
// Tenant Management API
// =============================================================================

export interface Tenant {
    id: string
    name: string
    api_key_prefix: string | null
    is_active: boolean
    config: Record<string, unknown>
    created_at: string | null
    api_keys: Array<{
        id: string
        name: string
        prefix: string
        last_chars: string
        is_active: boolean
        scopes: string[]
    }>
    document_count: number
}

export interface TenantCreate {
    name: string
    api_key_prefix?: string
    config?: Record<string, unknown>
}

export const tenantsApi = {
    list: async (params?: { skip?: number; limit?: number }) => {
        const response = await apiClient.get<Tenant[]>('/admin/tenants', { params })
        return response.data
    },

    create: async (data: TenantCreate) => {
        const response = await apiClient.post<Tenant>('/admin/tenants', data)
        return response.data
    },

    get: async (tenantId: string) => {
        const response = await apiClient.get<Tenant>(`/admin/tenants/${tenantId}`)
        return response.data
    },

    update: async (tenantId: string, data: Partial<TenantCreate> & { is_active?: boolean }) => {
        const response = await apiClient.patch<Tenant>(`/admin/tenants/${tenantId}`, data)
        return response.data
    },

    delete: async (tenantId: string) => {
        await apiClient.delete(`/admin/tenants/${tenantId}`)
    },
}

// =============================================================================
// Feedback API
// =============================================================================

export interface FeedbackItem {
    id: string
    request_id: string
    comment: string | null
    created_at: string
    score: number
    golden_status?: string
    is_active?: boolean
    query?: string
    answer?: string
}

export const feedbackApi = {
    getPending: async (params?: { skip?: number; limit?: number }) => {
        const response = await apiClient.get<{ data: FeedbackItem[] }>('/admin/feedback/pending', { params })
        return response.data.data
    },

    getApproved: async (params?: { skip?: number; limit?: number }) => {
        const response = await apiClient.get<{ data: FeedbackItem[] }>('/admin/feedback/approved', { params })
        return response.data.data
    },

    verify: async (feedbackId: string) => {
        const response = await apiClient.post<{ message: string; data: boolean }>(`/admin/feedback/${feedbackId}/verify`)
        return response.data
    },

    reject: async (feedbackId: string) => {
        const response = await apiClient.post<{ message: string; data: boolean }>(`/admin/feedback/${feedbackId}/reject`)
        return response.data
    },

    toggleActive: async (feedbackId: string, isActive: boolean) => {
        const response = await apiClient.put<{ message: string; data: boolean }>(
            `/admin/feedback/${feedbackId}/toggle-active`,
            null,
            { params: { is_active: isActive } }
        )
        return response.data
    },

    delete: async (feedbackId: string) => {
        const response = await apiClient.delete<{ message: string; data: boolean }>(`/admin/feedback/${feedbackId}`)
        return response.data
    },
}

// =============================================================================
// Export API
// =============================================================================

export interface ExportJobResponse {
    job_id: string
    status: 'pending' | 'running' | 'completed' | 'failed'
    progress?: number
    download_url?: string
    file_size?: number
    error?: string
    created_at?: string
    completed_at?: string
}

export interface StartExportResponse {
    job_id: string
    status: string
    message: string
}

export const exportApi = {
    /**
     * Download a single conversation as a ZIP file.
     * Returns a Blob that can be used to trigger download.
     */
    downloadConversation: async (conversationId: string): Promise<Blob> => {
        const response = await apiClient.get(`/export/conversation/${conversationId}`, {
            responseType: 'blob',
        })
        return response.data
    },

    /**
     * Start an async export job for all conversations.
     * Returns a job ID that can be polled for status.
     */
    startExportAll: async (): Promise<StartExportResponse> => {
        const response = await apiClient.post<StartExportResponse>('/export/all')
        return response.data
    },

    /**
     * Get the status of an export job.
     */
    getJobStatus: async (jobId: string): Promise<ExportJobResponse> => {
        const response = await apiClient.get<ExportJobResponse>(`/export/job/${jobId}`)
        return response.data
    },

    /**
     * Download the completed export ZIP.
     * Returns a Blob that can be used to trigger download.
     */
    downloadExport: async (jobId: string): Promise<Blob> => {
        const response = await apiClient.get(`/export/job/${jobId}/download`, {
            responseType: 'blob',
        })
        return response.data
    },

    /**
     * Cancel or delete an export job.
     */
    cancelExport: async (jobId: string): Promise<void> => {
        await apiClient.delete(`/export/job/${jobId}`)
    },
}

// =============================================================================
// Global Rules API
// =============================================================================

export interface GlobalRule {
    id: string
    content: string
    category: string | null
    priority: number
    is_active: boolean
    source: string
    updated_at: string
}

// =============================================================================
// Embeddings API
// =============================================================================

export interface EmbeddingStatus {
    tenant_id: string
    tenant_name: string
    is_compatible: boolean
    stored_config: {
        provider: string | null
        model: string | null
        dimensions: number | null
    }
    system_config: {
        provider: string
        model: string
        dimensions: number
    }
    details: string
}

export interface MigrationResult {
    status: string
    chunks_deleted: number
    docs_queued: number
    new_model: string
}

export interface MigrationStatusResponse {
    status: 'idle' | 'running' | 'complete' | 'failed' | 'cancelled'
    phase: string
    progress: number
    message: string
    total_docs?: number
    completed_docs?: number
    current_document?: string
}

export const embeddingsApi = {
    checkCompatibility: async (): Promise<EmbeddingStatus[]> => {
        const response = await apiClient.get<{ data: EmbeddingStatus[], message: string }>('/admin/embeddings/check')
        return response.data.data
    },

    migrateTenant: async (tenantId: string): Promise<MigrationResult> => {
        const response = await apiClient.post<{ data: MigrationResult, message: string }>(
            `/admin/embeddings/migrate`,
            null,
            { params: { tenant_id: tenantId } }
        )
        return response.data.data
    },

    getMigrationStatus: async (tenantId: string): Promise<MigrationStatusResponse> => {
        const response = await apiClient.get<{ data: MigrationStatusResponse, message: string }>(
            `/admin/embeddings/migration-status`,
            { params: { tenant_id: tenantId } }
        )
        return response.data.data
    },

    cancelMigration: async (tenantId: string): Promise<{ cancelled: boolean }> => {
        const response = await apiClient.post<{ data: { cancelled: boolean }, message: string }>(
            `/admin/embeddings/cancel-migration`,
            null,
            { params: { tenant_id: tenantId } }
        )
        return response.data.data
    }
}

export interface CreateRuleRequest {
    content: string
    category?: string
    priority?: number
    is_active?: boolean
}

export interface UpdateRuleRequest {
    content?: string
    category?: string
    priority?: number
    is_active?: boolean
}

export const rulesApi = {
    list: async (includeInactive = false) => {
        const response = await apiClient.get<{ data: GlobalRule[] }>(
            '/admin/rules/',
            { params: { include_inactive: includeInactive } }
        )
        return response.data.data
    },

    create: async (data: CreateRuleRequest) => {
        const response = await apiClient.post<{ data: GlobalRule }>('/admin/rules/', data)
        return response.data.data
    },

    update: async (ruleId: string, data: UpdateRuleRequest) => {
        const response = await apiClient.put<{ data: GlobalRule }>(`/admin/rules/${ruleId}`, data)
        return response.data.data
    },

    delete: async (ruleId: string) => {
        await apiClient.delete(`/admin/rules/${ruleId}`)
    },

    uploadFile: async (file: File, replaceExisting = false) => {
        const formData = new FormData()
        formData.append('file', file)
        const response = await apiClient.post<{ data: { created: number; source: string } }>(
            '/admin/rules/upload',
            formData,
            {
                params: { replace_existing: replaceExisting },
                headers: { 'Content-Type': 'multipart/form-data' }
            }
        )
        return response.data.data
    },
}

// =============================================================================
// Context Graph API
// =============================================================================

export interface ContextGraphStats {
    total_conversations: number
    total_turns: number
    total_feedback: number
    positive_feedback: number
    negative_feedback: number
}

export interface GraphFeedbackItem {
    feedback_id: string
    is_positive: boolean
    comment: string | null
    created_at: string
    turn_query: string | null
    turn_answer: string | null
    turn_id: string | null
    chunks_affected: Array<{ chunk_id: string; score: number }>
}

export interface ConversationGraphItem {
    conversation_id: string
    created_at: string
    turn_count: number
    last_query: string | null
    last_active: string | null
}

export const contextGraphApi = {
    getStats: async () => {
        const response = await apiClient.get<ContextGraphStats>('/admin/context-graph/stats')
        return response.data
    },

    listConversations: async (limit = 50) => {
        const response = await apiClient.get<ConversationGraphItem[]>('/admin/context-graph/conversations', {
            params: { limit }
        })
        return response.data
    },

    listFeedback: async (limit = 50) => {
        const response = await apiClient.get<GraphFeedbackItem[]>('/admin/context-graph/feedback', {
            params: { limit }
        })
        return response.data
    },

    deleteFeedback: async (feedbackId: string) => {
        const response = await apiClient.delete<{ message: string; deleted: string }>(
            `/admin/context-graph/feedback/${feedbackId}`
        )
        return response.data
    },

    getChunkImpact: async (chunkId: string) => {
        const response = await apiClient.get<{
            chunk_id: string
            positive_count: number
            negative_count: number
            net_score: number
            feedback_ids: string[]
        }>(`/admin/context-graph/chunk/${chunkId}/impact`)
        return response.data
    },
}

// =============================================================================
// Retention API
// =============================================================================

export interface UserFact {
    id: string
    user_id: string
    content: string
    importance: number
    created_at: string
    metadata: Record<string, unknown>
}

export interface ConversationSummary {
    id: string
    user_id: string
    title: string
    summary: string
    created_at: string
    metadata: Record<string, unknown>
}

export interface PaginationResponse<T> {
    total: number
    page: number
    size: number
    data: T[]
}

export const retentionApi = {
    listFacts: async (params?: { page?: number; size?: number; user_id?: string }) => {
        const response = await apiClient.get<PaginationResponse<UserFact>>('/admin/retention/facts', { params })
        return response.data
    },

    deleteFact: async (factId: string) => {
        await apiClient.delete<{ status: string; message: string }>(`/admin/retention/facts/${factId}`)
    },

    listSummaries: async (params?: { page?: number; size?: number; user_id?: string }) => {
        const response = await apiClient.get<PaginationResponse<ConversationSummary>>('/admin/retention/summaries', { params })
        return response.data
    },

    deleteSummary: async (summaryId: string) => {
        await apiClient.delete<{ status: string; message: string }>(`/admin/retention/summaries/${summaryId}`)
    },
}

