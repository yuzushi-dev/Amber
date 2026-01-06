
import React, { useEffect, useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { ChevronDown, ChevronRight, Users } from 'lucide-react';
import { apiClient } from '@/lib/api-client';

interface CommunityEntity {
    name: string;
    type: string;
    description?: string;
}

interface Community {
    community_id: number;
    entity_count: number;
    entities: CommunityEntity[];
}

interface CommunitiesTabProps {
    documentId: string;
}

const CommunitiesTab: React.FC<CommunitiesTabProps> = ({ documentId }) => {
    const [communities, setCommunities] = useState<Community[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [expandedCommunities, setExpandedCommunities] = useState<Set<number>>(new Set());
    const [detecting, setDetecting] = useState(false);

    useEffect(() => {
        const fetchCommunities = async () => {
            try {
                const response = await apiClient.get<Community[]>(`/documents/${documentId}/communities`);
                setCommunities(response.data);
            } catch (err) {
                console.error(err);
                setError('Failed to load communities');
            } finally {
                setLoading(false);
            }
        };

        if (documentId) {
            fetchCommunities();
        }
    }, [documentId]);

    const toggleCommunity = (communityId: number) => {
        setExpandedCommunities(prev => {
            const next = new Set(prev);
            if (next.has(communityId)) {
                next.delete(communityId);
            } else {
                next.add(communityId);
            }
            return next;
        });
    };

    if (!documentId) return <div className="p-4 text-center text-yellow-500">No document ID provided</div>;
    if (loading) return <div className="p-4 text-center">Loading communities...</div>;
    if (error) return <div className="p-4 text-center text-red-500">{error}</div>;

    return (
        <Card className="border-0 shadow-none">
            <CardHeader>
                <CardTitle className="flex items-center gap-2">
                    <Users className="h-5 w-5" />
                    Communities ({communities.length})
                </CardTitle>
            </CardHeader>
            <CardContent>
                <div className="space-y-4">
                    {communities.length === 0 ? (
                        <div className="text-center py-8 text-muted-foreground">
                            <p>No communities found. Communities are groups of related entities detected in this document.</p>
                            <Button
                                variant="outline"
                                className="mt-4"
                                onClick={async () => {
                                    try {
                                        setDetecting(true);
                                        await apiClient.post('/communities/refresh');
                                        alert('Community detection started. This process runs in the background. Please check back in a few minutes.');
                                    } catch (err) {
                                        console.error(err);
                                        alert('Failed to trigger community detection');
                                    } finally {
                                        setDetecting(false);
                                    }
                                }}
                                disabled={detecting}
                            >
                                {detecting ? "Starting..." : "Run Community Detection"}
                            </Button>
                        </div>
                    ) : (
                        communities.map(community => {
                            const isExpanded = expandedCommunities.has(community.community_id);
                            return (
                                <div
                                    key={community.community_id}
                                    className="border rounded-lg overflow-hidden"
                                >
                                    {/* Community Header */}
                                    <button
                                        onClick={() => toggleCommunity(community.community_id)}
                                        className="w-full flex items-center justify-between p-4 hover:bg-muted/50 transition-colors"
                                    >
                                        <div className="flex items-center gap-3">
                                            {isExpanded ? (
                                                <ChevronDown className="h-4 w-4" />
                                            ) : (
                                                <ChevronRight className="h-4 w-4" />
                                            )}
                                            <span className="font-medium">
                                                Community #{community.community_id}
                                            </span>
                                            <Badge variant="secondary">
                                                {community.entity_count} entities
                                            </Badge>
                                        </div>
                                    </button>

                                    {/* Community Entities Table */}
                                    {isExpanded && (
                                        <div className="border-t bg-muted/20 p-4">
                                            <Table>
                                                <TableHeader>
                                                    <TableRow>
                                                        <TableHead>Entity</TableHead>
                                                        <TableHead>Type</TableHead>
                                                        <TableHead>Description</TableHead>
                                                    </TableRow>
                                                </TableHeader>
                                                <TableBody>
                                                    {community.entities.map((entity, idx) => (
                                                        <TableRow key={idx}>
                                                            <TableCell className="font-medium">
                                                                {entity.name}
                                                            </TableCell>
                                                            <TableCell>
                                                                <Badge variant="outline">{entity.type}</Badge>
                                                            </TableCell>
                                                            <TableCell className="text-muted-foreground text-sm">
                                                                {entity.description || '-'}
                                                            </TableCell>
                                                        </TableRow>
                                                    ))}
                                                </TableBody>
                                            </Table>
                                        </div>
                                    )}
                                </div>
                            );
                        })
                    )}
                </div>
            </CardContent>
        </Card>
    );
};

export default CommunitiesTab;
