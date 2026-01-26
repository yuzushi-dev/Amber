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

import React, { useState } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/lib/api-client';
import {
    ChevronLeft,
    FileText,
    Layers,
    Share2,
    Database,
    Network,
    GitMerge,
    Trash2,
    VectorSquare,
    Info
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogClose } from '@/components/ui/dialog';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Accordion, AccordionItem, AccordionTrigger, AccordionContent } from '@/components/ui/accordion';

// Import existing tabs to reuse as modal content
import ChunksTab from '../components/DocumentTabs/ChunksTab';
import EntitiesTab from '../components/DocumentTabs/EntitiesTab';
import RelationshipsTab from '../components/DocumentTabs/RelationshipsTab';
import CommunitiesTab from '../components/DocumentTabs/CommunitiesTab';
import SimilaritiesTab from '../components/DocumentTabs/SimilaritiesTab';
import LiveStatusBadge from '../components/LiveStatusBadge';
import DeleteDocumentModal from '../components/DeleteDocumentModal';

// Placeholder for missing tabs
// const SimilaritiesView = () => <div className="p-4 text-center text-muted-foreground">Similarities exploration coming soon.</div>;

interface DocumentDetail {
    id: string
    filename: string
    title?: string
    status: string
    summary?: string
    keywords?: string[]
    metadata?: Record<string, unknown>
    stats?: {
        chunks: number
        entities: number
        relationships: number
        communities: number
        similarities: number
    }
}

export default function DocumentDetailPage() {
    const { documentId } = useParams({ from: '/admin/data/documents/$documentId' });
    const navigate = useNavigate();

    // React Query Client
    const queryClient = useQueryClient();

    // State for Modals
    const [activeModal, setActiveModal] = useState<string | null>(null);
    const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);

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

    const statsCards = [
        { id: 'chunks', label: 'Chunks', icon: Database, count: document.stats?.chunks || 0, color: 'text-purple-500', bg: 'bg-purple-500/10' },
        { id: 'entities', label: 'Entities', icon: Layers, count: document.stats?.entities || 0, color: 'text-green-500', bg: 'bg-green-500/10' },
        { id: 'relationships', label: 'Relationships', icon: Share2, count: document.stats?.relationships || 0, color: 'text-orange-500', bg: 'bg-orange-500/10' },
        { id: 'communities', label: 'Communities', icon: Network, count: document.stats?.communities || 0, color: 'text-pink-500', bg: 'bg-pink-500/10' },
        { id: 'similarities', label: 'Similarities', icon: GitMerge, count: document.stats?.similarities || 0, color: 'text-yellow-500', bg: 'bg-yellow-500/10' },
    ];

    const renderModalContent = () => {
        switch (activeModal) {
            case 'chunks': return <ChunksTab documentId={documentId} />;
            case 'entities': return <EntitiesTab documentId={documentId} />;
            case 'relationships': return <RelationshipsTab documentId={documentId} />;
            case 'communities': return <CommunitiesTab documentId={documentId} />;
            case 'similarities': return <SimilaritiesTab documentId={documentId} />;
            default: return null;
        }
    };

    const getModalTitle = (id: string) => {
        return statsCards.find(c => c.id === id)?.label || 'Details';
    };

    return (
        <div className="flex flex-col h-full bg-background overflow-y-auto">
            {/* Header */}
            <div className="sticky top-0 z-10 flex items-center justify-between px-6 py-4 border-b bg-card/80 backdrop-blur-sm">
                <div className="flex items-center gap-4">
                    <Button variant="ghost" size="icon" onClick={() => navigate({ to: '/admin/data/documents' })}>
                        <ChevronLeft className="h-5 w-5" />
                    </Button>
                    <div>
                        <div className="flex items-center gap-2">
                            <h1 className="text-xl font-semibold truncate max-w-md" title={document.title || document.filename}>
                                {document.title || document.filename}
                            </h1>
                            <LiveStatusBadge
                                documentId={documentId}
                                initialStatus={document.status}
                                onComplete={() => {
                                    queryClient.invalidateQueries({ queryKey: ['document', documentId] });
                                    queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] });
                                }}
                            />
                        </div>
                        <p className="text-xs text-muted-foreground font-mono mt-0.5">{documentId}</p>
                    </div>
                </div>
                <div className="flex gap-2">
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

            <div className="p-6 space-y-8 max-w-6xl mx-auto w-full">

                {/* Summary Section */}
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
                                    <Badge key={i} variant="secondary" className="text-xs hover:bg-secondary/80 transition-colors">
                                        {keyword}
                                    </Badge>
                                ))}
                            </div>
                        )}
                    </CardContent>
                </Card>

                {/* Statistics Grid */}
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
                    {statsCards.map((card) => (
                        <Card
                            key={card.id}
                            className="cursor-pointer hover:shadow-md transition-all hover:border-primary/50 group"
                            onClick={() => setActiveModal(card.id)}
                        >
                            <CardContent className="p-4 flex flex-col items-center justify-center text-center space-y-2">
                                <div className={`p-3 rounded-full ${card.bg} ${card.color} group-hover:scale-110 transition-transform`}>
                                    <card.icon className="w-5 h-5" />
                                </div>
                                <div>
                                    <div className="text-2xl font-bold">{card.count !== null ? card.count : '—'}</div>
                                    <div className="text-xs text-muted-foreground font-medium">{card.label}</div>
                                </div>
                            </CardContent>
                        </Card>
                    ))}
                </div>

                {/* Metadata Accordion */}
                <Accordion type="single" collapsible>
                    <AccordionItem value="metadata">
                        <AccordionTrigger>Metadata</AccordionTrigger>
                        <AccordionContent>
                            <div className="bg-muted/50 p-4 rounded-md overflow-x-auto">
                                <pre className="text-xs font-mono">{JSON.stringify(document.metadata || {}, null, 2)}</pre>
                            </div>
                        </AccordionContent>
                    </AccordionItem>
                </Accordion>

                {/* Graph Visualization Section (Placeholder/Feature) */}
                <div className="pt-4">
                    <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
                        <VectorSquare className="w-5 h-5" />
                        Graph Explorer
                    </h2>
                    <div className="border rounded-xl h-[500px] bg-card overflow-hidden">
                        {/* Reuse RelationshipsTab as the 'Graph' view for now, or a dedicated Graph component if available */}
                        <RelationshipsTab documentId={documentId} />
                    </div>
                </div>

            </div>

            {/* Details Modal */}
            <Dialog open={!!activeModal} onOpenChange={(open) => !open && setActiveModal(null)}>
                <DialogContent className="max-w-4xl h-[80vh] flex flex-col p-0 gap-0 relative">
                    <DialogClose onClose={() => setActiveModal(null)} />
                    <DialogHeader className="px-6 py-4 border-b pr-12">
                        <DialogTitle className="flex items-center gap-2">
                            {activeModal && (
                                <>
                                    {React.createElement(
                                        statsCards.find(c => c.id === activeModal)?.icon || FileText,
                                        { className: "w-5 h-5 text-primary" }
                                    )}
                                    {getModalTitle(activeModal)}
                                </>
                            )}
                        </DialogTitle>
                    </DialogHeader>
                    <div className="flex-1 overflow-y-auto p-0">
                        {renderModalContent()}
                    </div>
                </DialogContent>
            </Dialog>

            {/* Delete Confirmation Modal */}
            <DeleteDocumentModal
                open={deleteConfirmOpen}
                onOpenChange={setDeleteConfirmOpen}
                documentTitle={document.title || document.filename}
                onConfirm={async () => {
                    await apiClient.delete(`/documents/${documentId}`);
                    // Invalidate queries to refresh lists
                    await queryClient.invalidateQueries({ queryKey: ['documents'] });
                    await queryClient.invalidateQueries({ queryKey: ['maintenance-stats'] });
                    await queryClient.invalidateQueries({ queryKey: ['graph-top-nodes'] });
                    // Navigate back to library
                    navigate({ to: '/admin/data/documents' });
                }}
            />

        </div>
    );
}
