/**
 * DocumentDetailPage.tsx
 * ======================
 * 
 * Detailed dashboard view for a single document.
 * Features:
 * - Summary & Metadata
 * - Statistics Cards (opening detailed modals)
 * - Graph Visualization
 */

import { useState } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';
import { useAuth } from '@/features/auth';
import {
    ChevronLeft,
    ExternalLink,
    Layers,
    Share2,
    Database,
    Network,
    GitMerge,
    Trash2,
    VectorSquare,
    Info,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from '@/components/ui/accordion';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

import { DocumentViewer } from '../components/DocumentViewer'

// Import existing tabs to reuse as modal content
import ChunksTab from '../components/DocumentTabs/ChunksTab';
import EntitiesTab from '../components/DocumentTabs/EntitiesTab';
import RelationshipsTab from '../components/DocumentTabs/RelationshipsTab';
import CommunitiesTab from '../components/DocumentTabs/CommunitiesTab';
import SimilaritiesTab from '../components/DocumentTabs/SimilaritiesTab';
import DocumentSubgraph from '../components/DocumentTabs/DocumentSubgraph';
import LiveStatusBadge from '../components/LiveStatusBadge';
import DeleteDocumentModal from '../components/DeleteDocumentModal';
import DocumentShareDialog from '../components/DocumentShareDialog';

// Placeholder for missing tabs
// const SimilaritiesView = () => <div className="p-4 text-center text-muted-foreground">Similarities exploration coming soon.</div>;

interface DocumentDetail {
    id: string
    filename: string
    title?: string
    status: string
    tenant_id: string
    summary?: string
    keywords?: string[]
    metadata?: Record<string, unknown>
    is_shared?: boolean
    owner_tenant_id?: string | null
    visible_from_tenant_id?: string | null
    share_mode?: string | null
    stats?: {
        chunks: number
        entities: number
        relationships: number
        communities: number
        similarities: number
    }
}

export default function DocumentDetailPage() {
    const { documentId } = useParams({ strict: false });
    const navigate = useNavigate();
    const { tenantId, permissions } = useAuth();

    // React Query Client
    const queryClient = useQueryClient();

    const [activeTab, setActiveTab] = useState<string>('chunks');
    const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
    const [shareDialogOpen, setShareDialogOpen] = useState(false);

    // Fetch Document Metadata
    const { data: document, isLoading } = useQuery({
        queryKey: ['document', documentId],
        queryFn: async () => {
            const response = await apiClient.get<DocumentDetail>(`/documents/${documentId}`);
            return response.data;
        }
    });

    if (isLoading) {
        return (
            <div className="flex items-center justify-center h-full">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            </div>
        );
    }

    // ... (rest of render)



    if (!document) {
        return <div className="p-8 text-center">Document not found</div>;
    }

    const docId = documentId!;

    const canManageShares =
        permissions.includes('super_admin') || (tenantId === 'default' && permissions.includes('admin'));
    const isDefaultOwnedDocument = (document.owner_tenant_id ?? document.tenant_id) === 'default';
    const sourceUrl = document.metadata?.source_url as string | undefined;

    const tabs = [
        { id: 'chunks', label: 'Chunks', icon: Database, count: document.stats?.chunks || 0 },
        { id: 'entities', label: 'Entities', icon: Layers, count: document.stats?.entities || 0 },
        { id: 'relationships', label: 'Relationships', icon: Share2, count: document.stats?.relationships || 0 },
        { id: 'communities', label: 'Communities', icon: Network, count: document.stats?.communities || 0 },
        { id: 'similarities', label: 'Similarities', icon: GitMerge, count: document.stats?.similarities || 0 },
    ];

    return (
        <div className="flex flex-col h-full bg-background overflow-y-auto">
            {/* Header */}
            <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b bg-card/80 backdrop-blur-sm">
                <div className="flex items-center gap-4">
                    <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => navigate({ to: '/admin/data/documents' })}
                        aria-label="Back to documents"
                    >
                        <ChevronLeft className="h-5 w-5" />
                    </Button>
                    <div>
                        <div className="flex items-center gap-2">
                            <h1 className="text-xl font-semibold truncate max-w-md" title={document.title || document.filename}>
                                {document.title || document.filename}
                            </h1>
                            <LiveStatusBadge
                                documentId={docId}
                                initialStatus={document.status}
                                onComplete={() => {
                                    queryClient.invalidateQueries({ queryKey: ['document', docId] });
                                    queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] });
                                }}
                            />
                        </div>
                        <p className="text-xs text-muted-foreground font-mono mt-0.5">{docId}</p>
                    </div>
                </div>
                <div className="flex gap-2">
                    {sourceUrl && (
                        <Button
                            variant="outline"
                            size="sm"
                            asChild
                        >
                            <a href={sourceUrl} target="_blank" rel="noopener noreferrer">
                                <ExternalLink className="w-4 h-4 mr-2" />
                                View Source
                            </a>
                        </Button>
                    )}
                    <DocumentViewer
                        documentId={docId}
                        filename={document.title || document.filename}
                    />
                    {canManageShares && isDefaultOwnedDocument && (
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setShareDialogOpen(true)}
                        >
                            <Share2 className="w-4 h-4 mr-2" />
                            Manage Access
                        </Button>
                    )}
                    <Button
                        variant="destructive"
                        size="sm"
                        onClick={() => setDeleteConfirmOpen(true)}
                    >
                        <Trash2 className="w-4 h-4 mr-2" />
                        Delete
                    </Button>
                </div>
            </div>

            <div className="p-6 space-y-6 max-w-6xl mx-auto w-full">

                {/* 1. Summary — compact, at-a-glance */}
                <Card>
                    <CardHeader className="pb-3">
                        <CardTitle className="text-lg flex items-center gap-2">
                            <Info className="w-5 h-5 text-primary" />
                            Summary
                        </CardTitle>
                    </CardHeader>
                    <CardContent>
                        <p className="text-sm text-muted-foreground leading-relaxed">
                            {document.summary || "No summary available for this document yet."}
                        </p>
                        {document.keywords && document.keywords.length > 0 && (
                            <div className="flex flex-wrap gap-2 mt-4">
                                {document.keywords.map((keyword: string, i: number) => (
                                    <Badge key={i} variant="secondary" className="text-xs">
                                        {keyword}
                                    </Badge>
                                ))}
                            </div>
                        )}
                    </CardContent>
                </Card>

                {/* 2. Metadata — expanded by default for debugging */}
                <Accordion type="single" collapsible defaultValue="metadata">
                    <AccordionItem value="metadata">
                        <AccordionTrigger>Metadata</AccordionTrigger>
                        <AccordionContent>
                            <div className="bg-muted/50 p-4 rounded-md overflow-x-auto">
                                <pre className="text-xs font-mono">{JSON.stringify(document.metadata || {}, null, 2)}</pre>
                            </div>
                        </AccordionContent>
                    </AccordionItem>
                </Accordion>

                {/* 3. Document Subgraph — visual context */}
                <div>
                    <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
                        <VectorSquare className="w-5 h-5" />
                        Document Subgraph
                    </h2>
                    <div className="border rounded-xl h-[420px] bg-card overflow-hidden">
                        <DocumentSubgraph documentId={docId} />
                    </div>
                </div>

                {/* 4. Inline detail tabs (replace modal stats) */}
                <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-3">
                    <TabsList className="grid grid-cols-2 md:grid-cols-5 w-full h-auto bg-muted/40">
                        {tabs.map(t => (
                            <TabsTrigger
                                key={t.id}
                                value={t.id}
                                className="flex items-center gap-2 py-2 data-[state=active]:bg-background"
                            >
                                <t.icon className="w-3.5 h-3.5" />
                                <span>{t.label}</span>
                                <Badge variant="secondary" className="text-[10px] px-1.5 py-0 ml-auto">
                                    {t.count}
                                </Badge>
                            </TabsTrigger>
                        ))}
                    </TabsList>
                    <div className="border rounded-xl bg-card min-h-[400px] overflow-hidden">
                        <TabsContent value="chunks" className="m-0">
                            <ChunksTab documentId={docId} />
                        </TabsContent>
                        <TabsContent value="entities" className="m-0">
                            <EntitiesTab documentId={docId} />
                        </TabsContent>
                        <TabsContent value="relationships" className="m-0">
                            <RelationshipsTab documentId={docId} />
                        </TabsContent>
                        <TabsContent value="communities" className="m-0">
                            <CommunitiesTab documentId={docId} />
                        </TabsContent>
                        <TabsContent value="similarities" className="m-0">
                            <SimilaritiesTab documentId={docId} />
                        </TabsContent>
                    </div>
                </Tabs>

            </div>

            {/* Delete Confirmation Modal */}
            <DeleteDocumentModal
                open={deleteConfirmOpen}
                onOpenChange={setDeleteConfirmOpen}
                documentTitle={document.title || document.filename}
                onConfirm={async () => {
                    await apiClient.delete(`/documents/${docId}`);
                    // Invalidate queries to refresh lists
                    await queryClient.invalidateQueries({ queryKey: ['documents'] });
                    await queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] });
                    await queryClient.invalidateQueries({ queryKey: ['graph-top-nodes'] });
                    // Navigate back to library
                    navigate({ to: '/admin/data/documents' });
                }}
            />

            <DocumentShareDialog
                open={shareDialogOpen}
                onOpenChange={setShareDialogOpen}
                documentId={docId}
                documentTitle={document.title || document.filename}
                onSaved={() => {
                    queryClient.invalidateQueries({ queryKey: ['document', documentId] });
                    queryClient.invalidateQueries({ queryKey: ['documents'] });
                }}
            />

        </div>
    );
}
