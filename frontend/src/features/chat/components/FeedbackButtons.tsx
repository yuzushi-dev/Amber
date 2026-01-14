import React, { useState } from "react";
import { ThumbsUp, ThumbsDown, Loader2 } from "lucide-react";
import { motion } from "framer-motion";
import confetti from "canvas-confetti";
import { apiClient } from "@/lib/api-client";
import { FeedbackDialog } from "./FeedbackDialog";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { cn } from "@/lib/utils";

interface FeedbackProps {
    messageId: string;
    requestId?: string; // Prefer request_id if available
    sessionId?: string;
    content: string; // The message content for the dialog

    // Optional pre-existing state
    initialScore?: number;
}

export const FeedbackButtons: React.FC<FeedbackProps> = ({
    messageId,
    requestId,
    sessionId,
    content,
    initialScore
}) => {
    const [submitted, setSubmitted] = useState<number | null>(initialScore ?? null);
    const [loading, setLoading] = useState(false);
    const [isDialogOpen, setIsDialogOpen] = useState(false);

    // The identifier to use: Request ID is best for backend, fallback to message ID
    const effectiveId = requestId || messageId;

    const handleFeedback = async (
        rating: number,
        comment?: string,
        selectedSnippets?: string[]
    ) => {
        setLoading(true);
        try {
            await apiClient.post('/feedback/', {
                request_id: effectiveId,
                is_positive: rating > 0,
                score: rating === 1 ? 1.0 : 0.0,
                comment: comment,
                metadata: {
                    session_id: sessionId,
                    message_id: messageId,
                    selected_snippets: selectedSnippets
                }
            });

            setSubmitted(rating);
            toast.success("Feedback submitted");
        } catch (err) {
            console.error("Feedback failed", err);
            toast.error("Failed to submit feedback");
        } finally {
            setLoading(false);
        }
    };

    // Thumbs Up: Immediate submit
    const handleThumbsUp = (event: React.MouseEvent<HTMLButtonElement>) => {
        // Trigger confetti from the button's position
        const rect = event.currentTarget.getBoundingClientRect();
        const x = (rect.left + rect.width / 2) / window.innerWidth;
        const y = (rect.top + rect.height / 2) / window.innerHeight;

        confetti({
            origin: { x, y },
            particleCount: 60,
            spread: 70,
            colors: ['#22c55e', '#86efac', '#16a34a'] // Green theme
        });

        handleFeedback(1);
    };

    // Thumbs Down: Open Dialog
    const handleThumbsDown = () => {
        setIsDialogOpen(true);
    };

    // Dialog Submit: Call handleFeedback with -1
    const handleDialogSubmit = (comment: string, selectedSnippets: string[]) => {
        handleFeedback(-1, comment, selectedSnippets);
    };

    return (
        <>
            <div className="flex items-center gap-1">
                <motion.div whileTap={{ scale: 0.9 }}>
                    <Button
                        variant="ghost"
                        size="icon"
                        className={cn(
                            "h-7 w-7 rounded-md hover:bg-primary/10 hover:text-primary transition-colors",
                            submitted === 1 && "text-primary bg-primary/10"
                        )}
                        onClick={handleThumbsUp}
                        disabled={loading || submitted !== null}
                        title="Helpful"
                    >
                        {loading && submitted === 1 ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <ThumbsUp className="h-4 w-4" />
                        )}
                    </Button>
                </motion.div>

                <motion.div whileTap={{ scale: 0.9 }}>
                    <Button
                        variant="ghost"
                        size="icon"
                        className={cn(
                            "h-7 w-7 rounded-md hover:bg-destructive/10 hover:text-destructive transition-colors",
                            submitted === -1 && "text-destructive bg-destructive/10"
                        )}
                        onClick={handleThumbsDown}
                        disabled={loading || submitted !== null}
                        title="Not Helpful"
                    >
                        {loading && submitted === -1 ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <ThumbsDown className="h-4 w-4" />
                        )}
                    </Button>
                </motion.div>
            </div>

            <FeedbackDialog
                isOpen={isDialogOpen}
                onClose={() => setIsDialogOpen(false)}
                content={content}
                onSubmit={handleDialogSubmit}
            />
        </>
    );
};
