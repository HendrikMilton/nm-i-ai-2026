import { Link } from 'react-router-dom';
import { ChevronRight, Home } from 'lucide-react';

export interface Crumb {
    label: string;
    to?: string;
}

interface BreadcrumbsProps {
    crumbs: Crumb[];
}

export function Breadcrumbs({ crumbs }: BreadcrumbsProps) {
    return (
        <nav className="flex items-center gap-1.5 text-sm mb-4">
            <Link
                to="/"
                className="text-secondary hover:text-foreground transition-colors"
            >
                <Home className="w-4 h-4" />
            </Link>
            {crumbs.map((crumb, i) => (
                <span key={i} className="flex items-center gap-1.5">
                    <ChevronRight className="w-3.5 h-3.5 text-muted" />
                    {crumb.to ? (
                        <Link
                            to={crumb.to}
                            className="text-secondary hover:text-foreground transition-colors"
                        >
                            {crumb.label}
                        </Link>
                    ) : (
                        <span className="text-foreground font-medium">{crumb.label}</span>
                    )}
                </span>
            ))}
        </nav>
    );
}
