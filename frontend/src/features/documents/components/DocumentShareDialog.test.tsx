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
import DocumentShareDialog from './DocumentShareDialog'

describe('DocumentShareDialog', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    it('loads existing shares and saves updated tenant access', async () => {
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

        vi.mocked(apiClient.get).mockResolvedValue({
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

        vi.mocked(apiClient.put).mockResolvedValue({
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
                    {
                        tenant_id: 'engineering',
                        tenant_name: 'Engineering',
                        share_mode: 'read',
                        created_at: '2026-03-27T00:00:00Z',
                    },
                ],
            },
        })

        const onSaved = vi.fn()
        const onOpenChange = vi.fn()

        render(
            <DocumentShareDialog
                open={true}
                onOpenChange={onOpenChange}
                documentId="doc-1"
                documentTitle="Carbonio Guide"
                onSaved={onSaved}
            />
        )

        expect(await screen.findByText('Engineering')).toBeInTheDocument()
        expect(screen.getByLabelText('Sales')).toBeChecked()

        fireEvent.click(screen.getByLabelText('Engineering'))
        fireEvent.click(screen.getByRole('button', { name: /save access/i }))

        await waitFor(() => {
            expect(apiClient.put).toHaveBeenCalledWith('/documents/doc-1/shares', {
                tenant_ids: ['sales', 'engineering'],
            })
        })

        expect(onSaved).toHaveBeenCalled()
        expect(onOpenChange).toHaveBeenCalledWith(false)
    })
})
