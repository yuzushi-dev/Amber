interface FormatDateProps {
    date: string | Date | null | undefined
    mode?: 'full' | 'short'
    className?: string
}

export function FormatDate({ date, mode = 'full', className }: FormatDateProps) {
    if (!date) return <span className="text-muted-foreground">-</span>

    const d = new Date(date)

    if (mode === 'short') {
        return (
            <span title={d.toLocaleString()} className={className}>
                {new Intl.DateTimeFormat('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric'
                }).format(d)}
            </span>
        )
    }

    return (
        <span className={className}>
            {new Intl.DateTimeFormat('en-US', {
                month: 'short',
                day: 'numeric',
                year: 'numeric',
                hour: 'numeric',
                minute: 'numeric',
                hour12: true
            }).format(d)}
        </span>
    )
}
