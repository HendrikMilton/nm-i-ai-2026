import { type ReactNode, type ButtonHTMLAttributes } from 'react';
import { cn } from '../../lib/utils';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: 'primary' | 'secondary' | 'ghost';
    size?: 'sm' | 'md';
    children: ReactNode;
}

export const Button = ({
    variant = 'secondary',
    size = 'sm',
    children,
    disabled,
    className = '',
    ...props
}: ButtonProps) => {
    return (
        <button
            className={cn(
                'font-medium rounded-md transition-all duration-200 flex items-center justify-center focus:outline-none',
                variant === 'primary' && 'bg-primary text-white hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed',
                variant === 'secondary' && 'border border-border bg-surface text-foreground hover:bg-surface-dim disabled:opacity-40 disabled:cursor-not-allowed',
                variant === 'ghost' && 'text-foreground hover:bg-surface-dim disabled:opacity-40 disabled:cursor-not-allowed',
                size === 'sm' && 'px-3 py-1.5 text-sm',
                size === 'md' && 'px-4 py-2 text-sm',
                className,
            )}
            disabled={disabled}
            {...props}
        >
            {children}
        </button>
    );
};
