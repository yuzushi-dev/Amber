
import React, { useEffect, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { Card, CardContent } from '@/components/ui/card';
import { ScrollArea } from '@/components/ui/scroll-area';
import { apiClient } from '@/lib/api-client';
import { PDFViewer } from '../PDFViewer';

interface ContentTabProps {
    documentId: string;
}

const ContentTab: React.FC<ContentTabProps> = ({ documentId }) => {
    const [content, setContent] = useState<string>('');
    const [contentType, setContentType] = useState<string | null>(null);
    const [fileUrl, setFileUrl] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchContent = async () => {
            try {
                // Fetch document metadata to get content_type
                const docResponse = await apiClient.get<any>(`/documents/${documentId}`);
                const document = docResponse.data;
                const type = document.content_type || 'text/plain';

                setContentType(type);

                // For PDFs, set file URL
                if (type === 'application/pdf') {
                    setFileUrl(`/api/v1/documents/${documentId}/file`);
                    setLoading(false);
                    return;
                }

                // For text-based formats, fetch chunks to reconstruct content
                const chunksResponse = await apiClient.get<any>(`/documents/${documentId}/chunks`);
                const chunks = chunksResponse.data.chunks || chunksResponse.data;

                // Sort by index and join
                const fullText = chunks
                    .sort((a: any, b: any) => a.index - b.index)
                    .map((c: any) => c.content)
                    .join('\n\n');

                setContent(fullText || 'No text content available.');
            } catch (err) {
                console.error(err);
                setError('Failed to load content');
            } finally {
                setLoading(false);
            }
        };

        if (documentId) {
            fetchContent();
        }
    }, [documentId]);

    if (!documentId) return <div className="p-4 text-center text-yellow-500">No document ID provided</div>;
    if (loading) return <div className="p-4 text-center">Loading content...</div>;
    if (error) return <div className="p-4 text-center text-red-500">{error}</div>;

    // PDF viewer
    if (contentType === 'application/pdf' && fileUrl) {
        return (
            <Card className="border-0 shadow-none h-full flex flex-col">
                <CardContent className="flex-1 overflow-hidden p-0">
                    <PDFViewer url={fileUrl} />
                </CardContent>
            </Card>
        );
    }

    // Markdown renderer
    if (contentType?.includes('markdown')) {
        return (
            <Card className="border-0 shadow-none h-full flex flex-col">
                <CardContent className="flex-1 overflow-hidden p-0">
                    <ScrollArea className="h-full px-6 py-6">
                        <div className="max-w-4xl mx-auto prose prose-lg dark:prose-invert">
                            <ReactMarkdown>{content}</ReactMarkdown>
                        </div>
                    </ScrollArea>
                </CardContent>
            </Card>
        );
    }

    // Plain text fallback
    return (
        <Card className="border-0 shadow-none h-full flex flex-col">
            <CardContent className="flex-1 overflow-hidden p-0">
                <ScrollArea className="h-full px-6 py-6">
                    <div className="max-w-4xl mx-auto whitespace-pre-wrap font-serif text-lg leading-relaxed text-foreground/80">
                        {content}
                    </div>
                </ScrollArea>
            </CardContent>
        </Card>
    );
};

export default ContentTab;
