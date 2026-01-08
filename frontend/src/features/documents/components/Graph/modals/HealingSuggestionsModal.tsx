import React, { useEffect, useState } from 'react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Loader2, Sparkles, Network } from 'lucide-react';
import { graphEditorApi } from '@/lib/api-client';
import { HealingSuggestion } from '@/types/graph';
// Removed sonner

interface HealingSuggestionsModalProps {
    isOpen: boolean;
    onClose: () => void;
    nodeId: string | null;
    nodeName: string | null;
    onConnect: (targetId: string, type: string) => Promise<void>;
}

export const HealingSuggestionsModal: React.FC<HealingSuggestionsModalProps> = ({
    isOpen,
    onClose,
    nodeId,
    nodeName,
    onConnect
}) => {
    const [suggestions, setSuggestions] = useState<HealingSuggestion[]>([]);
    const [loading, setLoading] = useState(false);
    const [connecting, setConnecting] = useState<string | null>(null);

    useEffect(() => {
        if (isOpen && nodeId) {
            fetchSuggestions(nodeId);
        } else {
            setSuggestions([]);
        }
    }, [isOpen, nodeId]);

    const fetchSuggestions = async (id: string) => {
        setLoading(true);
        try {
            const results = await graphEditorApi.heal({ node_id: id });
            setSuggestions(results);
        } catch (error) {
            console.error(error);
            alert("Failed to generate healing suggestions");
        } finally {
            setLoading(false);
        }
    };

    const handleConnect = async (suggestion: HealingSuggestion) => {
        setConnecting(suggestion.id);
        try {
            // Default type for healing
            await onConnect(suggestion.id, "RELATED_TO");
            alert(`Connected to ${suggestion.name}`);
            // Remove from list
            setSuggestions(prev => prev.filter(s => s.id !== suggestion.id));
        } catch (error) {
            console.error(error);
            alert("Failed to connect");
        } finally {
            setConnecting(null);
        }
    };


    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            <DialogContent className="sm:max-w-md">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Sparkles className="h-5 w-5 text-amber-500" />
                        Healing: {nodeName}
                    </DialogTitle>
                    <DialogDescription>
                        AI is analyzing the <b>node context</b> and is looking for potential missing connections.
                    </DialogDescription>
                </DialogHeader>

                <ScrollArea className="h-[300px] mt-4 pr-4">
                    {loading ? (
                        <div className="flex flex-col items-center justify-center h-full gap-2 text-muted-foreground p-8">
                            <Loader2 className="h-8 w-8 animate-spin" />
                            <p>Analyzing semantic context...</p>
                        </div>
                    ) : suggestions.length === 0 ? (
                        <div className="text-center text-muted-foreground p-8">
                            <p>No obvious missing connections found for this node.</p>
                            <p className="text-xs mt-2">Try adding more documents to the knowledge graph.</p>
                        </div>
                    ) : (
                        <div className="space-y-3">
                            {suggestions.map((suggestion) => (
                                <div
                                    key={suggestion.id}
                                    className="flex items-start justify-between p-3 rounded-lg border bg-card/50 hover:bg-card/80 transition-colors"
                                >
                                    <div className="flex flex-col gap-1">
                                        <div className="flex items-center gap-2">
                                            <span className="font-medium text-amber-100">{suggestion.name}</span>
                                            <Badge variant="outline" className="text-[10px] h-4 px-1">{suggestion.type}</Badge>
                                        </div>
                                        {suggestion.description && (
                                            <p className="text-xs text-muted-foreground line-clamp-2">
                                                {suggestion.description}
                                            </p>
                                        )}
                                        <div className="flex items-center gap-2 mt-1">
                                            <div className="h-1.5 w-16 bg-muted rounded-full overflow-hidden" title="Confidence Score">
                                                <div
                                                    className="h-full bg-amber-500"
                                                    style={{ width: `${Math.round(suggestion.confidence * 100)}%` }}
                                                />
                                            </div>
                                            <span className="text-[10px] text-muted-foreground">
                                                {Math.round(suggestion.confidence * 100)}% Match
                                            </span>
                                        </div>
                                        <p className="text-[10px] text-amber-500/80 italic">
                                            {suggestion.reason}
                                        </p>
                                    </div>
                                    <Button
                                        size="sm"
                                        variant="outline"
                                        className="ml-2 shrink-0 h-8 w-8 p-0"
                                        onClick={() => handleConnect(suggestion)}
                                        disabled={!!connecting}
                                    >
                                        {connecting === suggestion.id ? (
                                            <Loader2 className="h-4 w-4 animate-spin" />
                                        ) : (
                                            <Network className="h-4 w-4" />
                                        )}
                                    </Button>
                                </div>
                            ))}
                        </div>
                    )}
                </ScrollArea>

                <DialogFooter>
                    <Button variant="ghost" onClick={onClose}>Done</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
};
