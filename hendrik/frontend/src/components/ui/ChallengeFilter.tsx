import { cn } from '../../lib/utils';

interface ChallengeFilterProps {
    selected: number | null;
    onChange: (challenge: number | null) => void;
}

const challenges = [1, 2, 3];

export function ChallengeFilter({ selected, onChange }: ChallengeFilterProps) {
    return (
        <div className="flex items-center gap-2">
            <button
                onClick={() => onChange(null)}
                className={cn(
                    'px-3 py-1.5 rounded-md text-sm font-medium transition-all duration-200',
                    selected === null
                        ? 'bg-primary text-white'
                        : 'bg-surface border border-border text-secondary hover:text-foreground hover:bg-surface-dim'
                )}
            >
                All
            </button>
            {challenges.map((c) => (
                <button
                    key={c}
                    onClick={() => onChange(c)}
                    className={cn(
                        'px-3 py-1.5 rounded-md text-sm font-medium transition-all duration-200',
                        selected === c
                            ? 'bg-primary text-white'
                            : 'bg-surface border border-border text-secondary hover:text-foreground hover:bg-surface-dim'
                    )}
                >
                    Challenge {c}
                </button>
            ))}
        </div>
    );
}
