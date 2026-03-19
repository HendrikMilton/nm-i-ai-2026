import { type ReactNode, useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { Menu, X, ChevronRight, ScrollText, Play, Sun, Moon, Images, Package, FlaskConical } from 'lucide-react';
import { clsx } from 'clsx';
import { useTheme } from '../hooks/useTheme';

const navItems = [
    { to: '/dataset', icon: Images, label: 'Dataset' },
    { to: '/products', icon: Package, label: 'Products' },
    { to: '/training', icon: FlaskConical, label: 'Training' },
    { to: '/logs', icon: ScrollText, label: 'Debug Logs' },
    { to: '/replay/1/0', icon: Play, label: 'Replay' },
];

const SIDEBAR_OPEN_KEY = 'sidebar-open';

interface LayoutProps {
    children: ReactNode;
}

export function Layout({ children }: LayoutProps) {
    const { theme, toggleTheme } = useTheme();
    const [isOpen, setIsOpen] = useState(() => {
        const stored = localStorage.getItem(SIDEBAR_OPEN_KEY);
        return stored !== 'false';
    });

    useEffect(() => {
        localStorage.setItem(SIDEBAR_OPEN_KEY, String(isOpen));
    }, [isOpen]);

    return (
        <div className="min-h-screen flex flex-col bg-background">
            <header className="h-14 bg-surface border-b border-border/60 flex items-center px-4 gap-4 sticky top-0 z-50">
                <button
                    onClick={() => setIsOpen((prev) => !prev)}
                    className="p-2 -ml-2 rounded-md text-secondary hover:text-foreground hover:bg-surface-dim transition-colors"
                    title={isOpen ? 'Close menu' : 'Open menu'}
                >
                    {isOpen ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
                </button>

                <div className="h-5 w-px bg-border/60 mx-1.5" />
                <span className="text-sm font-medium text-foreground">NM AI Debug</span>
                <div className="flex-1" />

                <button
                    onClick={toggleTheme}
                    className="p-2 rounded-md text-secondary hover:text-foreground hover:bg-surface-dim transition-colors"
                    title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
                >
                    {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                </button>
            </header>

            <div className="flex flex-1">
                <aside
                    className={clsx(
                        'bg-surface border-r border-border/60 flex flex-col flex-shrink-0 transition-all duration-200 ease-out overflow-hidden',
                        isOpen ? 'w-60' : 'w-0'
                    )}
                >
                    <div className="w-60">
                        <nav className="flex-1 py-3">
                            {navItems.map(({ to, icon: Icon, label }) => (
                                <NavLink
                                    key={to}
                                    to={to}
                                    className={({ isActive }) =>
                                        clsx(
                                            'group flex items-center px-6 py-3 text-sm font-medium transition-all duration-150 relative',
                                            isActive
                                                ? 'text-primary bg-primary/8'
                                                : 'text-secondary hover:bg-surface-dim hover:text-foreground'
                                        )
                                    }
                                >
                                    {({ isActive }) => (
                                        <>
                                            {isActive && (
                                                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-7 bg-primary rounded-r-full" />
                                            )}
                                            <Icon className="w-5 h-5 mr-4" strokeWidth={isActive ? 2 : 1.5} />
                                            <span>{label}</span>
                                            <ChevronRight
                                                className={clsx(
                                                    'w-4 h-4 ml-auto opacity-0 -translate-x-1 transition-all duration-150',
                                                    'group-hover:opacity-50 group-hover:translate-x-0'
                                                )}
                                            />
                                        </>
                                    )}
                                </NavLink>
                            ))}
                        </nav>
                    </div>
                </aside>

                <main className="flex-1 overflow-auto">
                    <div className="p-8 max-w-[1600px]">{children}</div>
                </main>
            </div>
        </div>
    );
}
