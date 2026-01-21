import React from 'react';
import {
    MousePointer2,
    Network,
    Wand2,
    Scissors,
    Download,
    Upload,
    History,
    Minimize2,
    HelpCircle,
    Move,
    Rotate3d,
    ZoomIn,
} from 'lucide-react';
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogBody,
    DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from '@/components/ui/tooltip';

export type GraphMode = 'view' | 'connect' | 'heal' | 'prune' | 'merge';

interface GraphToolbarProps {
    mode: GraphMode;
    onModeChange: (mode: GraphMode) => void;
    onBackup?: () => void;
    onRestore?: () => void;
    onHistoryClick?: () => void;
    pendingCount?: number;
}

export const GraphToolbar: React.FC<GraphToolbarProps> = ({
    mode,
    onModeChange,
    onBackup,
    onRestore,
    onHistoryClick,
    pendingCount = 0,
}) => {
    const [isHelpOpen, setIsHelpOpen] = React.useState(false);

    const tools = [
        {
            id: 'view',
            icon: MousePointer2,
            label: 'Select / View',
            desc: 'View node details and navigate'
        },
        {
            id: 'connect',
            icon: Network,
            label: 'Connect',
            desc: 'Draw connections between nodes'
        },
        {
            id: 'heal',
            icon: Wand2,
            label: 'Heal',
            desc: 'AI-assisted connection suggestions'
        },
        {
            id: 'prune',
            icon: Scissors,
            label: 'Prune',
            desc: 'Remove edges or nodes'
        },
        {
            id: 'merge',
            icon: Minimize2,
            label: 'Merge',
            desc: 'Merge duplicates nodes'
        }
    ] as const;

    return (
        <>
            <div className="absolute top-4 left-4 z-10 flex flex-col gap-2 bg-background/80 backdrop-blur-sm p-1.5 rounded-lg border shadow-sm">
                <TooltipProvider>
                    {tools.map((tool) => (
                        <Tooltip key={tool.id}>
                            <TooltipTrigger asChild>
                                <Button
                                    variant={mode === tool.id ? "default" : "ghost"}
                                    size="icon"
                                    className={`h-8 w-8 ${mode === tool.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'}`}
                                    onClick={() => onModeChange(tool.id)}
                                >
                                    <tool.icon className="h-4 w-4" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent side="right">
                                <p className="font-semibold">{tool.label}</p>
                                <p className="text-xs text-muted-foreground">{tool.desc}</p>
                            </TooltipContent>
                        </Tooltip>
                    ))}

                    {/* History Button */}
                    {onHistoryClick && (
                        <>
                            <div className="h-px bg-border my-1" />
                            <Tooltip>
                                <TooltipTrigger asChild>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        className="h-8 w-8 text-muted-foreground relative"
                                        onClick={onHistoryClick}
                                    >
                                        <History className="h-4 w-4" />
                                        {pendingCount > 0 && (
                                            <span className="absolute -top-1 -right-1 bg-amber-500 text-black text-[10px] font-bold rounded-full h-4 min-w-4 px-1 flex items-center justify-center">
                                                {pendingCount > 9 ? '9+' : pendingCount}
                                            </span>
                                        )}
                                    </Button>
                                </TooltipTrigger>
                                <TooltipContent side="right">
                                    <p className="font-semibold">Edit History</p>
                                    <p className="text-xs text-muted-foreground">Review and manage graph changes</p>
                                </TooltipContent>
                            </Tooltip>
                        </>
                    )}

                    {(onBackup || onRestore) && <div className="h-px bg-border my-1" />}

                    {onBackup && (
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground" onClick={onBackup}>
                                    <Download className="h-4 w-4" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent side="right">Backup Graph</TooltipContent>
                        </Tooltip>
                    )}
                    {onRestore && (
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground" onClick={onRestore}>
                                    <Upload className="h-4 w-4" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent side="right">Restore Graph</TooltipContent>
                        </Tooltip>
                    )}

                    <div className="h-px bg-border my-1" />

                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                variant="ghost"
                                size="icon"
                                className="h-8 w-8 text-muted-foreground"
                                onClick={() => setIsHelpOpen(true)}
                            >
                                <HelpCircle className="h-4 w-4" />
                            </Button>
                        </TooltipTrigger>
                        <TooltipContent side="right">
                            <p className="font-semibold">Graph Help</p>
                            <p className="text-xs text-muted-foreground">Controls & Actions guide</p>
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>

                <div className="absolute top-0 left-full ml-2 bg-secondary/80 text-secondary-foreground text-[10px] px-1.5 py-0.5 rounded pointer-events-none whitespace-nowrap opacity-0 group-hover:opacity-100 transition-opacity">
                    {mode.toUpperCase()} MODE
                </div>
            </div>

            <Dialog open={isHelpOpen} onOpenChange={setIsHelpOpen}>
                <DialogContent className="max-w-2xl">
                    <DialogHeader>
                        <DialogTitle className="flex items-center gap-2">
                            <HelpCircle className="h-5 w-5 text-amber-500" />
                            Graph Navigation & Actions
                        </DialogTitle>
                        <DialogDescription>
                            Guide to navigating the 3D graph and using editing tools.
                        </DialogDescription>
                    </DialogHeader>

                    <DialogBody className="grid gap-6">
                        {/* Navigation Controls */}
                        <div className="space-y-3">
                            <h3 className="text-sm font-medium text-foreground border-b pb-1">3D Navigation</h3>
                            <div className="grid grid-cols-2 gap-4">
                                <div className="flex items-start gap-3 p-3 rounded-lg bg-secondary/30">
                                    <MousePointer2 className="h-5 w-5 text-amber-500 mt-0.5" />
                                    <div>
                                        <p className="text-sm font-medium">Left Click</p>
                                        <p className="text-xs text-muted-foreground">Select nodes or trigger active tool</p>
                                    </div>
                                </div>
                                <div className="flex items-start gap-3 p-3 rounded-lg bg-secondary/30">
                                    <Move className="h-5 w-5 text-amber-500 mt-0.5" />
                                    <div>
                                        <p className="text-sm font-medium">Right Click / Drag</p>
                                        <p className="text-xs text-muted-foreground">Pan the camera view</p>
                                    </div>
                                </div>
                                <div className="flex items-start gap-3 p-3 rounded-lg bg-secondary/30">
                                    <Rotate3d className="h-5 w-5 text-amber-500 mt-0.5" />
                                    <div>
                                        <p className="text-sm font-medium">Left Drag</p>
                                        <p className="text-xs text-muted-foreground">Rotate (Orbit) around focus</p>
                                    </div>
                                </div>
                                <div className="flex items-start gap-3 p-3 rounded-lg bg-secondary/30">
                                    <ZoomIn className="h-5 w-5 text-amber-500 mt-0.5" />
                                    <div>
                                        <p className="text-sm font-medium">Scroll Wheel</p>
                                        <p className="text-xs text-muted-foreground">Zoom in / out</p>
                                    </div>
                                </div>
                            </div>
                        </div>

                        {/* Action Tools */}
                        <div className="space-y-3">
                            <h3 className="text-sm font-medium text-foreground border-b pb-1">Editing Actions</h3>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                                <div className="flex items-start gap-3 p-3 rounded-lg bg-secondary/30">
                                    <Network className="h-5 w-5 text-sky-400 mt-0.5" />
                                    <div>
                                        <p className="text-sm font-medium">Connect</p>
                                        <p className="text-xs text-muted-foreground">Link two nodes. Click source, then click target.</p>
                                    </div>
                                </div>
                                <div className="flex items-start gap-3 p-3 rounded-lg bg-secondary/30">
                                    <Minimize2 className="h-5 w-5 text-purple-400 mt-0.5" />
                                    <div>
                                        <p className="text-sm font-medium">Merge</p>
                                        <p className="text-xs text-muted-foreground">Combine nodes. 1st click = Target. Others = Sources (deleted).</p>
                                    </div>
                                </div>
                                <div className="flex items-start gap-3 p-3 rounded-lg bg-secondary/30">
                                    <Scissors className="h-5 w-5 text-red-400 mt-0.5" />
                                    <div>
                                        <p className="text-sm font-medium">Prune</p>
                                        <p className="text-xs text-muted-foreground">Delete items. Click a node to remove it and its edges.</p>
                                    </div>
                                </div>
                                <div className="flex items-start gap-3 p-3 rounded-lg bg-secondary/30">
                                    <Wand2 className="h-5 w-5 text-amber-400 mt-0.5" />
                                    <div>
                                        <p className="text-sm font-medium">Heal</p>
                                        <p className="text-xs text-muted-foreground">AI suggestions. Fix missing links or inconsistencies.</p>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </DialogBody>
                    <DialogFooter>
                        <Button className="w-full sm:w-auto" onClick={() => setIsHelpOpen(false)}>
                            Got it!
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
};
