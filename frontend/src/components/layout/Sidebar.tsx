import { Link } from '@tanstack/react-router'
import { MessageSquare, Files, LayoutDashboard, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
    { label: 'Dashboard', icon: LayoutDashboard, to: '/' },
    { label: 'Chat', icon: MessageSquare, to: '/chat' },
    { label: 'Documents', icon: Files, to: '/documents' },
]

export default function Sidebar() {
    return (
        <aside className="w-64 border-r bg-card flex flex-col">
            <div className="p-6">
                <h1 className="text-xl font-bold tracking-tight text-primary">Amber</h1>
                <p className="text-xs text-muted-foreground">Analyst Interface</p>
            </div>

            <nav className="flex-1 px-4 space-y-1" aria-label="Main navigation">
                {navItems.map((item) => (
                    <Link
                        key={item.to}
                        to={item.to}
                        className={cn(
                            "flex items-center space-x-3 px-3 py-2 rounded-md transition-colors",
                            "text-muted-foreground hover:bg-secondary hover:text-secondary-foreground"
                        )}
                        activeProps={{
                            className: "bg-secondary text-secondary-foreground font-medium",
                        }}
                    >
                        <item.icon className="w-5 h-5" />
                        <span>{item.label}</span>
                    </Link>
                ))}
            </nav>

            <div className="p-4 border-t">
                <Link
                    to="/admin"
                    className="flex items-center space-x-3 px-3 py-2 w-full text-muted-foreground hover:bg-secondary hover:text-secondary-foreground rounded-md transition-colors"
                >
                    <Settings className="w-5 h-5" />
                    <span>Admin Console</span>
                </Link>
            </div>
        </aside>
    )
}

