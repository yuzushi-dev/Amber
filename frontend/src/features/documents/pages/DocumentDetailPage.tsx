
import React, { useState } from 'react';
import { useParams, useNavigate } from '@tanstack/react-router';

import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ChevronLeft, FileText, Layers, Share2, Database } from 'lucide-react';

import ContentTab from '../components/DocumentTabs/ContentTab';
import ChunksTab from '../components/DocumentTabs/ChunksTab';
import EntitiesTab from '../components/DocumentTabs/EntitiesTab';
import RelationshipsTab from '../components/DocumentTabs/RelationshipsTab';

const DocumentDetailPage: React.FC = () => {
    const { documentId } = useParams({ from: '/admin/data/documents/$documentId' });
    const navigate = useNavigate();
    const [activeTab, setActiveTab] = useState('content');

    return (
        <div className="flex flex-col h-full bg-background">
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b bg-card">
                <div className="flex items-center gap-4">
                    <Button variant="ghost" size="icon" onClick={() => navigate({ to: '/admin/data/documents' })}>
                        <ChevronLeft className="h-5 w-5" />
                    </Button>
                    <div>
                        <h1 className="text-xl font-semibold">Document Details</h1>
                        <p className="text-sm text-muted-foreground font-mono">{documentId}</p>
                    </div>
                </div>
                <div className="flex gap-2">
                    <Button variant="outline" size="sm">Reprocess</Button>
                    <Button variant="destructive" size="sm">Delete</Button>
                </div>
            </div>

            {/* Main Content */}
            <div className="flex-1 overflow-auto p-6">
                <Tabs value={activeTab} onValueChange={setActiveTab} className="h-full flex flex-col">
                    <div className="flex items-center justify-between mb-6">
                        <TabsList className="bg-muted/50">
                            <TabsTrigger value="content" className="flex items-center gap-2">
                                <FileText className="h-4 w-4" />
                                Content
                            </TabsTrigger>
                            <TabsTrigger value="chunks" className="flex items-center gap-2">
                                <Database className="h-4 w-4" />
                                Chunks
                            </TabsTrigger>
                            <TabsTrigger value="entities" className="flex items-center gap-2">
                                <Layers className="h-4 w-4" />
                                Entities
                            </TabsTrigger>
                            <TabsTrigger value="relationships" className="flex items-center gap-2">
                                <Share2 className="h-4 w-4" />
                                Relationships
                            </TabsTrigger>
                        </TabsList>
                    </div>

                    <div className="flex-1 min-h-0 bg-card rounded-lg border shadow-sm overflow-hidden">
                        <TabsContent value="content" className="h-full m-0 p-0 overflow-auto">
                            <ContentTab documentId={documentId} />
                        </TabsContent>
                        <TabsContent value="chunks" className="h-full m-0 p-0 overflow-auto">
                            <ChunksTab documentId={documentId} />
                        </TabsContent>
                        <TabsContent value="entities" className="h-full m-0 p-0 overflow-auto">
                            <EntitiesTab documentId={documentId} />
                        </TabsContent>
                        <TabsContent value="relationships" className="h-full m-0 p-0 overflow-auto">
                            <RelationshipsTab documentId={documentId} />
                        </TabsContent>
                    </div>
                </Tabs>
            </div>
        </div>
    );
};

export default DocumentDetailPage;
