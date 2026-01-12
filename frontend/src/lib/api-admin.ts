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
}
