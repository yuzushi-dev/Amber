import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api-client', () => ({
    apiClient: {
        get: vi.fn(),
        put: vi.fn(),
    },
}))

vi.mock('@/lib/api-admin', () => ({
    tenantsApi: {
        list: vi.fn(),
    },
}))

import { apiClient } from '@/lib/api-client'
import { tenantsApi } from '@/lib/api-admin'
import BulkDocumentShareDialog from './BulkDocumentShareDialog'

describe('BulkDocumentShareDialog', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('grants tenant access without overwriting existing shares on other selected documents', async () => {
        vi.mocked(tenantsApi.list).mockResolvedValue([
            {
                id: 'default',
                name: 'Global Admin',
                api_key_prefix: null,
                is_active: true,
                config: {},
                created_at: null,
                api_keys: [],
                document_count: 0,
            },
            {
                id: 'sales',
                name: 'Sales',
                api_key_prefix: null,
                is_active: true,
                config: {},
                created_at: null,
                api_keys: [],
                document_count: 0,
            },
            {
                id: 'engineering',
                name: 'Engineering',
                api_key_prefix: null,
                is_active: true,
                config: {},
                created_at: null,
                api_keys: [],
                document_count: 0,
            },
        ])

        vi.mocked(apiClient.get)
            .mockResolvedValueOnce({
                data: {
                    document_id: 'doc-1',
                    owner_tenant_id: 'default',
                    shares: [
                        {
                            tenant_id: 'sales',
                            tenant_name: 'Sales',
                            share_mode: 'read',
                            created_at: '2026-03-27T00:00:00Z',
                        },
                    ],
                },
            })
            .mockResolvedValueOnce({
                data: {
                    document_id: 'doc-2',
                    owner_tenant_id: 'default',
                    shares: [],
                },
            })

        vi.mocked(apiClient.put).mockResolvedValue({ data: {} })

        const onSaved = vi.fn()
        const onOpenChange = vi.fn()

        render(
            <BulkDocumentShareDialog
                open={true}
                onOpenChange={onOpenChange}
                documentIds={['doc-1', 'doc-2']}
                documentTitles={['Acme Mail Guide', 'Engineering Runbook']}
                onSaved={onSaved}
            />
        )

        expect(await screen.findByText(/2 documents selected/i)).toBeInTheDocument()

        fireEvent.click(screen.getByLabelText('Engineering'))
        fireEvent.click(screen.getByRole('button', { name: /grant access/i }))

        await waitFor(() => {
            expect(apiClient.put).toHaveBeenNthCalledWith(1, '/documents/doc-1/shares', {
                tenant_ids: ['sales', 'engineering'],
            })
        })

        expect(apiClient.put).toHaveBeenNthCalledWith(2, '/documents/doc-2/shares', {
            tenant_ids: ['engineering'],
        })
        expect(onSaved).toHaveBeenCalled()
        expect(onOpenChange).toHaveBeenCalledWith(false)
    })
})
