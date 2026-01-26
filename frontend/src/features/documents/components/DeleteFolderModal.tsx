import { useState } from "react"
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { FileText, Trash2 } from "lucide-react"
import { ScrollArea } from "@/components/ui/scroll-area"

interface DeleteFolderModalProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    folderName: string
    documents?: { id: string; title?: string; filename: string }[]
    onConfirm: (deleteContents: boolean) => void
}

export function DeleteFolderModal({
    open,
    onOpenChange,
    folderName,
    documents = [],
    onConfirm,
}: DeleteFolderModalProps) {
    const [deleteContents, setDeleteContents] = useState(false)
    const hasDocuments = documents.length > 0

    const handleConfirm = () => {
        onConfirm(deleteContents)
        onOpenChange(false)
        setDeleteContents(false)
    }

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="sm:max-w-[480px] p-0 gap-0 overflow-hidden border-destructive/20 shadow-2xl">
                {/* Header */}
                <div className="bg-destructive/10 px-6 py-6 border-b border-destructive/10">
                    <DialogHeader className="gap-2">
                        <div className="flex items-center gap-3 text-destructive">
                            <div className="p-2 bg-destructive/20 rounded-full">
                                <Trash2 className="h-5 w-5" />
                            </div>
                            <DialogTitle className="text-xl">Delete Folder</DialogTitle>
                        </div>
                        <DialogDescription className="text-base text-muted-foreground/90 ml-1">
                            Are you sure you want to delete <span className="font-semibold text-foreground">"{folderName}"</span>?
                        </DialogDescription>
                    </DialogHeader>
                </div>

                {/* Content */}
                <div className="px-6 py-6 space-y-6">
                    {!hasDocuments ? (
                        <p className="text-muted-foreground">
                            This folder is empty. It will be permanently removed.
                        </p>
                    ) : (
                        <div className="space-y-4">
                            <div className="space-y-3">
                                <p className="text-sm font-medium text-foreground">
                                    Contains {documents.length} document{documents.length !== 1 && 's'}:
                                </p>
                                <div className="bg-muted/30 rounded-lg border px-3 py-2">
                                    <ScrollArea className="h-[120px] pr-2">
                                        <ul className="space-y-2">
                                            {documents.slice(0, 5).map(doc => (
                                                <li key={doc.id} className="flex items-center gap-2 text-sm text-muted-foreground">
                                                    <FileText className="h-3.5 w-3.5 shrink-0 opacity-70" />
                                                    <span className="truncate">{doc.title || doc.filename}</span>
                                                </li>
                                            ))}
                                            {documents.length > 5 && (
                                                <li className="text-xs text-muted-foreground/70 pl-5.5 pt-1">
                                                    + {documents.length - 5} more...
                                                </li>
                                            )}
                                        </ul>
                                    </ScrollArea>
                                </div>
                            </div>

                            <div className="pt-2">
                                <div className="flex items-start gap-3 p-4 border border-destructive/20 bg-destructive/5 rounded-lg transition-colors hover:bg-destructive/10">
                                    <Checkbox
                                        id="delete-contents"
                                        checked={deleteContents}
                                        onCheckedChange={(checked) => setDeleteContents(checked as boolean)}
                                        className="mt-1 data-[state=checked]:bg-destructive data-[state=checked]:border-destructive"
                                    />
                                    <div className="grid gap-1.5 leading-none">
                                        <label
                                            htmlFor="delete-contents"
                                            className="text-sm font-semibold leading-none cursor-pointer text-destructive"
                                        >
                                            Also delete these {documents.length} documents
                                        </label>
                                        <p className="text-xs text-muted-foreground/80 leading-normal">
                                            If unchecked, documents will be moved to <strong>Unfiled</strong>.
                                            <br />
                                            <span className="text-destructive/80 font-medium">Warning: Checked deletion is permanent.</span>
                                        </p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>

                {/* Footer */}
                <div className="px-6 py-4 bg-muted/50 flex justify-end gap-3 border-t">
                    <Button variant="ghost" onClick={() => onOpenChange(false)}>
                        Cancel
                    </Button>
                    <Button
                        variant={deleteContents || !hasDocuments ? "destructive" : "default"}
                        onClick={handleConfirm}
                        className="shadow-sm"
                    >
                        {deleteContents
                            ? `Delete Folder & ${documents.length} Files`
                            : "Delete Folder Only"
                        }
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    )
}
