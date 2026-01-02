
import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { apiClient } from '@/lib/api-client';
import { ArrowRight } from 'lucide-react';

interface Relationship {
    source: string;
    target: string;
    type: string;
    description: string;
    weight: number;
}

interface RelationshipsTabProps {
    documentId: string;
}

const RelationshipsTab: React.FC<RelationshipsTabProps> = ({ documentId }) => {
    const [relationships, setRelationships] = useState<Relationship[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchRelationships = async () => {
            try {
                const response = await apiClient.get<Relationship[]>(`/documents/${documentId}/relationships`);
                setRelationships(response.data);
            } catch (err) {
                console.error(err);
                setError('Failed to load relationships');
            } finally {
                setLoading(false);
            }
        };

        if (documentId) {
            fetchRelationships();
        }
    }, [documentId]);

    if (!documentId) return <div className="p-4 text-center text-yellow-500">No document ID provided</div>;
    if (loading) return <div className="p-4 text-center">Loading relationships...</div>;
    if (error) return <div className="p-4 text-center text-red-500">{error}</div>;

    return (
        <Card className="border-0 shadow-none">
            <CardHeader>
                <CardTitle>Relationships ({relationships.length})</CardTitle>
            </CardHeader>
            <CardContent>
                <div className="rounded-md border">
                    <Table>
                        <TableHeader>
                            <TableRow>
                                <TableHead>Source</TableHead>
                                <TableHead className="w-[50px]"></TableHead>
                                <TableHead>Target</TableHead>
                                <TableHead>Type</TableHead>
                                <TableHead>Description</TableHead>
                                <TableHead className="text-right">Weight</TableHead>
                            </TableRow>
                        </TableHeader>
                        <TableBody>
                            {relationships.length === 0 ? (
                                <TableRow>
                                    <TableCell colSpan={6} className="text-center h-24 text-muted-foreground">
                                        No relationships found.
                                    </TableCell>
                                </TableRow>
                            ) : (
                                relationships.map((rel, idx) => (
                                    <TableRow key={idx}>
                                        <TableCell className="font-medium text-amber-600">{rel.source}</TableCell>
                                        <TableCell><ArrowRight className="h-4 w-4 text-muted-foreground" /></TableCell>
                                        <TableCell className="font-medium text-amber-600">{rel.target}</TableCell>
                                        <TableCell className="font-mono text-xs">{rel.type}</TableCell>
                                        <TableCell className="text-muted-foreground max-w-md truncate" title={rel.description}>{rel.description}</TableCell>
                                        <TableCell className="text-right">{rel.weight}</TableCell>
                                    </TableRow>
                                ))
                            )}
                        </TableBody>
                    </Table>
                </div>
            </CardContent>
        </Card>
    );
};

export default RelationshipsTab;
