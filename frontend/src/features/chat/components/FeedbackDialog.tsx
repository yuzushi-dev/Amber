import React, { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import {
    Dialog,
    DialogContent,
    DialogDescription,

    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { cn } from '@/lib/utils';
import { CheckCircle2, AlertCircle, MessageSquare } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';

interface FeedbackDialogProps {
    isOpen: boolean;
    onClose: () => void;
    onSubmit: (comment: string, selectedSnippets: string[]) => void;
    content: string;
}

const SelectableBlock = ({
    children,
    className,
    onSelect,
    isSelected
}: {
    children: React.ReactNode,
    className?: string,
    onSelect: (content: string) => void,
    isSelected: boolean
}) => {
    // Extract text content recursively
    const getContent = (node: React.ReactNode): string => {
        if (node === null || node === undefined) return '';
        if (typeof node === 'string' || typeof node === 'number') return String(node);
        if (Array.isArray(node)) return node.map(getContent).join('');
        // @ts-ignore
        if (React.isValidElement(node)) {
            // @ts-ignore
            return getContent(node.props.children);
        }
        if (typeof node === 'object') return ''; // Fallback for unknown objects
        return String(node);
    };

    const content = getContent(children);

    return (
        <motion.div
            layout
            onClick={() => onSelect(content)}
            initial={false}
            animate={{
                backgroundColor: isSelected ? "rgba(239, 68, 68, 0.08)" : "transparent",
                borderColor: isSelected ? "rgba(239, 68, 68, 0.5)" : "transparent",
            }}
            whileHover={{
                backgroundColor: isSelected ? "rgba(239, 68, 68, 0.12)" : "rgba(255, 255, 255, 0.03)",
                borderColor: isSelected ? "rgba(239, 68, 68, 0.6)" : "rgba(255, 255, 255, 0.1)",
            }}
            transition={{ duration: 0.2 }}
            className={cn(
                "relative rounded-xl border-2 transition-colors cursor-pointer p-3 -mx-3 mb-2 group",
                !isSelected && "border-transparent",
                className
            )}
        >
            <AnimatePresence>
                {isSelected && (
                    <motion.div
                        initial={{ scale: 0, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        exit={{ scale: 0, opacity: 0 }}
                        className="absolute -right-2 -top-2 bg-red-500 text-white rounded-full p-1 shadow-lg z-10 ring-2 ring-background"
                    >
                        <CheckCircle2 size={14} fill="currentColor" className="text-white" />
                    </motion.div>
                )}
            </AnimatePresence>
            {children}
        </motion.div>
    );
};

export function FeedbackDialog({ isOpen, onClose, onSubmit, content }: FeedbackDialogProps) {
    const [comment, setComment] = useState("");
    const [selectedSnippets, setSelectedSnippets] = useState<Set<string>>(new Set());

    const toggleSnippet = (snippet: string) => {
        const newSelected = new Set(selectedSnippets);
        if (newSelected.has(snippet)) {
            newSelected.delete(snippet);
        } else {
            newSelected.add(snippet);
        }
        setSelectedSnippets(newSelected);
    };

    const handleSubmit = () => {
        onSubmit(comment, Array.from(selectedSnippets));
        onClose();
    };

    const components = {
        p: ({ children }: any) => (
            <SelectableBlock
                isSelected={selectedSnippets.has(children?.toString() || '')}
                onSelect={() => toggleSnippet(children?.toString() || '')}
            >
                <p className="leading-relaxed text-foreground/90">{children}</p>
            </SelectableBlock>
        ),
        li: ({ children }: any) => (
            <SelectableBlock
                isSelected={selectedSnippets.has(children?.toString() || '')}
                onSelect={() => toggleSnippet(children?.toString() || '')}
            >
                <li>{children}</li>
            </SelectableBlock>
        ),
        pre: ({ children, ...props }: any) => {
            const codeContent = children?.props?.children || '';
            return (
                <SelectableBlock
                    isSelected={selectedSnippets.has(codeContent)}
                    onSelect={() => toggleSnippet(codeContent)}
                >
                    <pre {...props} className="bg-black/40 border border-white/10 p-4 rounded-lg overflow-x-auto font-mono text-sm shadow-inner">{children}</pre>
                </SelectableBlock>
            )
        }
    };

    return (
        <Dialog open={isOpen} onOpenChange={onClose}>
            <DialogContent className="max-w-5xl h-[85vh] p-0 gap-0 overflow-hidden bg-background/95 backdrop-blur-xl border-white/10 shadow-2xl flex flex-col">
                <DialogHeader className="p-6 border-b border-white/5 bg-white/5">
                    <div className="flex items-center gap-3">
                        <div className="p-2.5 bg-red-500/10 rounded-lg ring-1 ring-red-500/20">
                            <AlertCircle className="w-5 h-5 text-red-500" />
                        </div>
                        <div>
                            <DialogTitle className="text-xl font-display tracking-tight">Report an Issue</DialogTitle>
                            <DialogDescription className="text-muted-foreground mt-1">
                                Help us improve by flagging specific parts of the response that are incorrect.
                            </DialogDescription>
                        </div>
                    </div>
                </DialogHeader>

                <div className="flex-1 grid grid-cols-1 lg:grid-cols-5 min-h-0 divide-y lg:divide-y-0 lg:divide-x divide-white/5">
                    {/* Left: Message Preview */}
                    <div className="lg:col-span-3 overflow-y-auto p-6 bg-black/20">
                        <div className="flex items-center justify-between mb-4 px-1">
                            <h4 className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Select Incorrect Snippets</h4>
                            <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-muted-foreground border border-white/5">
                                Click on text to select
                            </span>
                        </div>
                        <div className="prose prose-sm dark:prose-invert max-w-none">
                            <ReactMarkdown
                                remarkPlugins={[remarkGfm, remarkBreaks]}
                                components={components}
                            >
                                {content}
                            </ReactMarkdown>
                        </div>
                    </div>

                    {/* Right: Comment Input */}
                    <div className="lg:col-span-2 flex flex-col p-6 bg-background">
                        <div className="flex-1 flex flex-col">
                            <label htmlFor="comment" className="flex items-center gap-2 mb-3 text-sm font-medium text-foreground">
                                <MessageSquare className="w-4 h-4 text-primary" />
                                Details
                            </label>

                            <Textarea
                                id="comment"
                                placeholder="Describe what was wrong with the response..."
                                className="flex-1 min-h-[150px] resize-none bg-muted/30 border-white/10 focus:border-primary/50 focus:ring-primary/20 transition-all p-4 text-sm leading-relaxed"
                                value={comment}
                                onChange={(e) => setComment(e.target.value)}
                                autoFocus
                            />

                            <div className="mt-4 pt-4 border-t border-white/5">
                                <div className="flex items-center justify-between text-xs text-muted-foreground mb-4">
                                    <span>Selected snippets:</span>
                                    <span className={cn("font-medium", selectedSnippets.size > 0 ? "text-primary" : "text-muted-foreground")}>
                                        {selectedSnippets.size}
                                    </span>
                                </div>
                            </div>
                        </div>

                        <div className="mt-auto flex gap-3 pt-2">
                            <Button variant="ghost" onClick={onClose} className="flex-1 text-muted-foreground hover:text-foreground">
                                Cancel
                            </Button>
                            <Button
                                onClick={handleSubmit}
                                disabled={!comment && selectedSnippets.size === 0}
                                className={cn(
                                    "flex-[2]",
                                    selectedSnippets.size > 0
                                        ? "bg-red-600 hover:bg-red-700 text-white shadow-red-900/20 shadow-lg"
                                        : "bg-primary hover:bg-primary/90 text-primary-foreground"
                                )}
                            >
                                Submit Feedback
                            </Button>
                        </div>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
