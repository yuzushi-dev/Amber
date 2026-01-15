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
                        <header className="px-6 py-5 border-b border-white/5 flex items-center justify-between bg-white/[0.02] backdrop-blur-xl z-10">
                            <div className="flex items-center gap-3">
                                <div className="p-2 bg-primary/10 rounded-lg ring-1 ring-primary/20 shadow-[0_0_15px_-3px_rgba(var(--primary),0.3)]">
                                    <Sparkles className="w-4 h-4 text-primary" />
                                </div>
                                <div className="space-y-0.5">
                                    <h2 className="font-display font-semibold text-sm tracking-tight text-foreground/90 leading-none">References</h2>
                                    <p className="text-[10px] text-muted-foreground font-medium">{activeCitations.length} sources linked</p>
                                </div>
                            </div>
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 hover:bg-white/5 rounded-full text-muted-foreground hover:text-foreground transition-all"
                                onClick={() => setActiveMessageId(null)}
                            >
                                <X className="w-4 h-4" />
                            </Button>
                        </header>

                        <ScrollArea className="flex-1 px-2">
                            <div className="space-y-4 p-4 pb-20" ref={listRef}>
                                <AnimatePresence mode="popLayout">
                                    {activeCitations.length === 0 ? (
                                        <motion.div
                                            initial={{ opacity: 0 }}
                                            animate={{ opacity: 1 }}
                                            className="flex flex-col items-center justify-center py-32 text-center space-y-6 select-none cursor-default opacity-60"
                                        >
                                            <div className="relative">
                                                <div className="absolute inset-0 bg-primary/20 blur-[40px] rounded-full opacity-20 animate-pulse" />
                                                <div className="relative w-20 h-20 rounded-full border border-white/5 flex items-center justify-center bg-white/[0.01]">
                                                    <div className="absolute inset-0 rounded-full border border-primary/10 border-t-primary/30 animate-[spin_3s_linear_infinite]" />
                                                    <BookOpen className="w-8 h-8 text-muted-foreground/30" />
                                                </div>
                                            </div>
                                            <div className="space-y-2 max-w-[200px]">
                                                <p className="text-foreground/60 font-medium text-xs uppercase tracking-widest">No Citations</p>
                                                <p className="text-muted-foreground/40 text-[10px] leading-relaxed">
                                                    This response generated without direct document references.
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
            <div className="p-4 flex items-start gap-4 border-b border-white/5 bg-gradient-to-r from-white/[0.03] to-transparent">
                <div className="mt-0.5 p-2 rounded-lg bg-black/40 ring-1 ring-white/10 shrink-0">
                    <FileText className="w-4 h-4 text-primary/80" />
                </div>
                <div className="flex-1 min-w-0 space-y-1">
                    <div className="flex items-center justify-between gap-2">
                        <span className="text-[10px] font-mono text-primary/60 font-medium tracking-wider uppercase bg-primary/5 px-1.5 py-0.5 rounded border border-primary/10">
                            DOC-{citation.value}
                        </span>

                        {source?.score && (
                            <div className="flex items-center gap-1.5" title={`Match Score: ${Math.round(source.score * 100)}%`}>
                                <div className="h-1.5 w-12 bg-black/40 rounded-full overflow-hidden border border-white/5">
                                    <div
                                        className={cn(
                                            "h-full rounded-full transition-all duration-500",
                                            source.score > 0.8 ? "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.5)]" :
                                                source.score > 0.5 ? "bg-amber-500" : "bg-muted-foreground"
                                        )}
                                        style={{ width: `${source.score * 100}%` }}
                                    />
                                </div>
                                <span className={cn(
                                    "text-[9px] font-mono font-bold",
                                    source.score > 0.8 ? "text-emerald-500" :
                                        source.score > 0.5 ? "text-amber-500" : "text-muted-foreground"
                                )}>
                                    {Math.round(source.score * 100)}%
                                </span>
                            </div>
                        )}
                    </div>

                    <h3 className="font-display text-sm font-medium text-foreground/90 truncate leading-tight pt-0.5" title={source?.title || citation.label}>
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
                        if (source?.document_id?.startsWith('rule_doc_')) {
                            window.open('/admin/settings/rules', '_blank');
                        } else if (source?.document_id) {
                            window.open(`/admin/data/documents/${source.document_id}`, '_blank');
                        }
                    }}
                >
                    {source?.document_id?.startsWith('rule_doc_') ? (
                        <>View Global Rules <Sparkles className="w-2.5 h-2.5" /></>
                    ) : (
                        <>View Document <ExternalLink className="w-2.5 h-2.5" /></>
                    )}
                </Button>
            </div>


        </motion.div>
    )
}
