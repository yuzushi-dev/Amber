/**
 * DocumentViewer
 * ==============
 * Fetches and renders the original document file in a modal dialog.
 * Supports: PDF (iframe), HTML (iframe with sandbox), Markdown/Text (rendered),
 * and all other types (download fallback).
 */

import { useState } from 'react'
import { FileText, X, Download, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { apiClient } from '@/lib/api-client'
import { toast } from 'sonner'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface DocumentViewerProps {
    documentId: string
    filename: string
}

type ViewerState = 'idle' | 'loading' | 'ready' | 'error'

export function DocumentViewer({ documentId, filename }: DocumentViewerProps) {
    const [open, setOpen] = useState(false)
    const [state, setState] = useState<ViewerState>('idle')
    const [blobUrl, setBlobUrl] = useState<string | null>(null)
    const [textContent, setTextContent] = useState<string | null>(null)
    const [contentType, setContentType] = useState<string | null>(null)

    const isMarkdown = (ct: string | null, fn: string) =>
        ct === 'text/markdown' || fn.toLowerCase().endsWith('.md') || fn.toLowerCase().endsWith('.markdown')

    const isText = (ct: string | null) =>
        ct?.startsWith('text/') && ct !== 'text/html' && ct !== 'text/markdown'

    const isPdf = (ct: string | null) => ct === 'application/pdf'
    const isHtml = (ct: string | null) => ct === 'text/html'

    const handleOpen = async () => {
        setOpen(true)
        if (state !== 'idle') return

        setState('loading')
        try {
            const response = await apiClient.get(`/documents/${documentId}/file`, {
                responseType: 'blob',
            })

            const blob: Blob = response.data
            const ct = response.headers['content-type']?.split(';')[0] ?? null
            setContentType(ct)

            if (isMarkdown(ct, filename) || isText(ct)) {
                const text = await blob.text()
                setTextContent(text)
            } else {
                const url = URL.createObjectURL(blob)
                setBlobUrl(url)
            }

            setState('ready')
        } catch {
            setState('error')
            toast.error('Failed to load document')
        }
    }

    const handleClose = () => {
        setOpen(false)
        if (blobUrl) {
            URL.revokeObjectURL(blobUrl)
            setBlobUrl(null)
        }
        setTextContent(null)
        setState('idle')
    }

    const handleDownload = async () => {
        try {
            const response = await apiClient.get(`/documents/${documentId}/file`, {
                responseType: 'blob',
            })
            const url = URL.createObjectURL(response.data)
            const a = document.createElement('a')
            a.href = url
            a.download = filename
            document.body.appendChild(a)
            a.click()
            a.remove()
            URL.revokeObjectURL(url)
        } catch {
            toast.error('Download failed')
        }
    }

    const renderContent = () => {
        if (state === 'loading') {
            return (
                <div className="flex items-center justify-center h-full">
                    <Loader2 className="h-8 w-8 animate-spin text-primary/40" />
                </div>
            )
        }

        if (state === 'error') {
            return (
                <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
                    <X className="h-8 w-8 text-destructive/60" />
                    <p className="text-sm">Failed to load document</p>
                    <Button variant="outline" size="sm" onClick={handleDownload}>
                        <Download className="w-4 h-4 mr-2" /> Download instead
                    </Button>
                </div>
            )
        }

        if (state === 'ready') {
            if (isMarkdown(contentType, filename) && textContent !== null) {
                return (
                    <div className="p-6 overflow-y-auto h-full prose prose-sm dark:prose-invert max-w-none">
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{textContent}</ReactMarkdown>
                    </div>
                )
            }

            if (isText(contentType) && textContent !== null) {
                return (
                    <pre className="p-6 text-xs font-mono overflow-auto h-full whitespace-pre-wrap text-foreground/80">
                        {textContent}
                    </pre>
                )
            }

            if ((isPdf(contentType) || isHtml(contentType)) && blobUrl) {
                return (
                    <iframe
                        src={blobUrl}
                        className="w-full h-full border-0"
                        title={filename}
                        sandbox={isHtml(contentType) ? '' : undefined}
                    />
                )
            }

            // Unknown type: show download prompt
            return (
                <div className="flex flex-col items-center justify-center h-full gap-3 text-muted-foreground">
                    <FileText className="h-10 w-10 text-muted-foreground/40" />
                    <p className="text-sm">Preview not available for this file type</p>
                    <Button variant="outline" size="sm" onClick={handleDownload}>
                        <Download className="w-4 h-4 mr-2" /> Download
                    </Button>
                </div>
            )
        }

        return null
    }

    return (
        <>
            <Button variant="outline" size="sm" onClick={handleOpen}>
                <FileText className="w-4 h-4 mr-2" />
                View Document
            </Button>

            <Dialog open={open} onOpenChange={(o) => { if (!o) handleClose() }}>
                <DialogContent className="max-w-5xl h-[85vh] flex flex-col p-0 gap-0 overflow-hidden">
                    <DialogHeader className="px-6 py-4 border-b border-white/5 flex-row items-center justify-between pr-12">
                        <DialogTitle className="text-base font-medium truncate max-w-lg" title={filename}>
                            {filename}
                        </DialogTitle>
                        <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 rounded-md shrink-0"
                            onClick={handleDownload}
                            title="Download"
                        >
                            <Download className="h-4 w-4" />
                        </Button>
                    </DialogHeader>
                    <div className="flex-1 overflow-hidden bg-muted/20">
                        {renderContent()}
                    </div>
                </DialogContent>
            </Dialog>
        </>
    )
}
