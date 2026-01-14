import { useCitationStore, Citation } from '../store/citationStore'
import { useChatStore } from '../store'
import { cn } from '@/lib/utils'
import { X, FileText, ExternalLink, Sparkles, BookOpen } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { useEffect, useRef, useMemo } from 'react'
import { motion, AnimatePresence, Variants } from 'framer-motion'

export default function CitationExplorer() {
    const {
        activeMessageId,
        citations,
        hoveredCitationId,
        selectedCitationId,
        setActiveMessageId,
        setHoveredCitation,
        selectCitation
    } = useCitationStore()

    const listRef = useRef<HTMLDivElement>(null)

    const rawCitations = useMemo(() =>
        activeMessageId ? citations.get(activeMessageId) || [] : [],
        [activeMessageId, citations]
    )

    // Deduplicate citations based on value
    const activeCitations = useMemo(() =>
        Array.from(new Map(rawCitations.map(c => [c.value, c])).values()),
        [rawCitations]
    )

    // Scroll to selected citation
    useEffect(() => {
        if (selectedCitationId && listRef.current) {
            const selectedRawCitation = rawCitations.find(c => c.id === selectedCitationId)
            if (selectedRawCitation) {
                const targetCitation = activeCitations.find(c => c.value === selectedRawCitation.value)
                if (targetCitation) {
                    setTimeout(() => {
                        const el = document.getElementById(`citation-card-${targetCitation.id}`)
                        if (el) {
                            el.scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' })
                        }
                    }, 100)
                }
            }
        }
    }, [selectedCitationId, rawCitations, activeCitations])

    // Framer Motion Variants
    const containerVariants: Variants = {
        hidden: { width: 0, opacity: 0, x: 20 },
        visible: {
            width: 450,
            opacity: 1,
            x: 0,
            transition: {
                type: "spring",
                stiffness: 300,
                damping: 30,
                staggerChildren: 0.1,
                delayChildren: 0.2
            }
        },
        exit: {
            width: 0,
            opacity: 0,
            x: 20,
            transition: {
                duration: 0.2
            }
        }
    }

    const itemVariants = {
        hidden: { opacity: 0, y: 5 },
        visible: {
            opacity: 1,
            y: 0,
            transition: { duration: 0.3, ease: "easeOut" }
        },
        exit: { opacity: 0, transition: { duration: 0 } }
    }

    return (
        <AnimatePresence mode="wait">
            {activeMessageId && (
                <motion.aside
                    initial="hidden"
                    animate="visible"
                    exit="exit"
                    variants={containerVariants}
                    className="h-full flex flex-col bg-background/80 backdrop-blur-xl border-l border-white/10 shadow-2xl z-40 overflow-hidden whitespace-nowrap"
                    style={{ willChange: 'width, transform, opacity' }}
                >
                    <div className="w-[450px] shrink-0 h-full flex flex-col">
                        <header className="p-4 border-b border-white/5 flex items-center justify-between bg-white/5 backdrop-blur-md">
                            <div className="flex items-center gap-2.5">
                                <div className="p-1.5 bg-primary/10 rounded-md ring-1 ring-primary/20">
                                    <Sparkles className="w-4 h-4 text-primary" />
                                </div>
                                <div>
                                    <h2 className="font-display font-semibold text-sm tracking-tight text-foreground/90 leading-none">References</h2>
                                    <p className="text-[10px] text-muted-foreground font-medium mt-1">{activeCitations.length} sources cited</p>
                                </div>
                            </div>
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 hover:bg-destructive/10 hover:text-destructive transition-colors rounded-full"
                                onClick={() => setActiveMessageId(null)}
                            >
                                <X className="w-4 h-4" />
                            </Button>
                        </header>

                        <ScrollArea className="flex-1 p-5">
                            <div className="space-y-6 pb-20" ref={listRef}>
                                <AnimatePresence mode="popLayout">
                                    {activeCitations.length === 0 ? (
                                        <motion.div
                                            initial={{ opacity: 0, scale: 0.9 }}
                                            animate={{ opacity: 1, scale: 1 }}
                                            className="flex flex-col items-center justify-center py-20 text-center space-y-4"
                                        >
                                            <div className="p-6 bg-muted/20 rounded-full ring-1 ring-white/5">
                                                <BookOpen className="w-10 h-10 text-muted-foreground/30" />
                                            </div>
                                            <div className="space-y-1">
                                                <p className="text-foreground/80 font-medium text-sm">No Citations Found</p>
                                                <p className="text-muted-foreground text-xs leading-relaxed">
                                                    This message doesn't appear to reference any specific documents.
                                                </p>
                                            </div>
                                        </motion.div>
                                    ) : (
                                        activeCitations.map((citation) => (
                                            <CitationCard
                                                key={citation.id}
                                                citation={citation}
                                                isHovered={hoveredCitationId === citation.id}
                                                isSelected={selectedCitationId === citation.id}
                                                onHover={setHoveredCitation}
                                                onSelect={selectCitation}
                                                variants={itemVariants}
                                            />
                                        ))
                                    )}
                                </AnimatePresence>
                            </div>
                        </ScrollArea>
                    </div>
                </motion.aside>
            )}
        </AnimatePresence>
    )
}

function CitationCard({
    citation,
    isHovered,
    isSelected,
    onHover,
    onSelect,
    variants
}: {
    citation: Citation
    isHovered: boolean
    isSelected: boolean
    onHover: (id: string | null) => void
    onSelect: (id: string | null) => void
    variants: any
}) {
    // Retrieve content from chat store
    const activeMessageId = useCitationStore(s => s.activeMessageId)
    const message = useChatStore(s => s.messages.find(m => m.id === activeMessageId))
    const source = message?.sources?.find(s => {
        if (citation.type === 'Source') {
            return s.index?.toString() === citation.value
        }
        return s.title === citation.value
    })

    const fullContent = source?.text || source?.content_preview || "Content loading or unavailable..."

    return (
        <motion.div
            variants={variants}
            id={`citation-card-${citation.id}`}
            className={cn(
                "group relative rounded-xl transition-all duration-300 overflow-hidden cursor-pointer",
                // Base
                "bg-card/40 backdrop-blur-md border border-white/5 shadow-sm",
                // Hover
                "hover:bg-card/60 hover:shadow-lg hover:border-primary/20 hover:-translate-y-0.5",
                // Active/Selected
                (isHovered || isSelected) && "bg-card/80 border-primary/30 shadow-glow-sm ring-1 ring-primary/20",
                isSelected && "bg-primary/5 ring-primary/40"
            )}
            onMouseEnter={() => onHover(citation.id)}
            onMouseLeave={() => onHover(null)}
            onClick={() => isSelected ? onSelect(null) : onSelect(citation.id)}
            layout
        >
            {/* Header Section */}
            <div className="p-3.5 flex items-start gap-3 border-b border-white/5 bg-gradient-to-r from-white/5 to-transparent">
                <div className="mt-0.5 p-1.5 rounded-md bg-black/20 ring-1 ring-white/5 shrink-0">
                    <FileText className="w-3.5 h-3.5 text-primary/80" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="text-[10px] font-mono text-primary/70 font-medium tracking-wider uppercase">
                            Source {citation.value}
                        </span>
                        {source?.score && (
                            <span
                                className={cn(
                                    "text-[9px] px-1.5 py-0.5 rounded-full font-medium border",
                                    source.score > 0.8 ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" :
                                        source.score > 0.5 ? "bg-amber-500/10 text-amber-400 border-amber-500/20" :
                                            "bg-muted text-muted-foreground border-transparent"
                                )}
                            >
                                {Math.round(source.score * 100)}% Match
                            </span>
                        )}
                    </div>

                    <h3 className="font-display text-sm font-medium text-foreground/90 truncate leading-tight" title={source?.title || citation.label}>
                        {source?.title || citation.label}
                    </h3>
                </div>
            </div>

            {/* Content Body */}
            <div className="p-3.5 bg-black/40 text-xs font-mono text-foreground/90 leading-relaxed relative">
                <motion.div
                    initial={false}
                    animate={{ height: isSelected ? "auto" : "6rem" }}
                    transition={{ type: "spring", stiffness: 300, damping: 30 }}
                    className="overflow-hidden"
                >
                    <pre className="whitespace-pre-wrap font-sans break-words pb-2">
                        {fullContent}
                    </pre>
                </motion.div>

                {!isSelected && fullContent.length > 200 && (
                    <div className="absolute bottom-0 left-0 right-0 h-12 bg-gradient-to-t from-black/20 to-transparent pointer-events-none" />
                )}
            </div>

            {/* Footer / Actions */}
            <div className="px-3.5 py-2 bg-white/5 border-t border-white/5 flex items-center justify-between group/footer">
                <div className="flex items-center gap-2">
                    {source?.page && (
                        <span className="text-[10px] text-muted-foreground/60">Page {source.page}</span>
                    )}
                </div>

                <Button
                    variant="ghost"
                    size="sm"
                    className="h-6 text-[10px] px-2 gap-1.5 text-primary hover:text-primary hover:bg-primary/10 transition-all font-medium uppercase tracking-wide"
                    onClick={(e) => {
                        e.stopPropagation();
                        if (source?.document_id) {
                            window.open(`/admin/data/documents/${source.document_id}`, '_blank');
                        }
                    }}
                >
                    View Document <ExternalLink className="w-2.5 h-2.5" />
                </Button>
            </div>


        </motion.div>
    )
}
