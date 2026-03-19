import { cn } from '../../lib/utils';

interface BadgeProps {
    children: React.ReactNode;
    variant?: 'default' | 'success' | 'warning' | 'error';
}

const variants = {
    default: 'bg-primary/10 text-primary',
    success: 'bg-success/10 text-success',
    warning: 'bg-warning/10 text-warning',
    error: 'bg-error/10 text-error',
};

export function Badge({ children, variant = 'default' }: BadgeProps) {
    return (
        <span className={cn('px-2 py-0.5 rounded-full text-xs font-medium', variants[variant])}>
            {children}
        </span>
    );
}
