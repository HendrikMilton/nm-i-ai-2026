import { Link } from 'react-router-dom';
import { Images, Package, FlaskConical } from 'lucide-react';
import { Breadcrumbs } from '../components/Breadcrumbs';

const cards = [
    {
        to: '/challenges/2/dataset',
        icon: Images,
        title: 'Dataset',
        description: '248 shelf images with 22,731 bounding box annotations across 356 product categories',
    },
    {
        to: '/challenges/2/products',
        icon: Package,
        title: 'Products',
        description: '327 products with multi-angle reference photos (main, front, back, left, right, top, bottom)',
    },
    {
        to: '/challenges/2/training',
        icon: FlaskConical,
        title: 'Training Runs',
        description: 'YOLO training experiments, epoch metrics, mAP scores, and submission readiness',
    },
];

export function ChallengePage() {
    return (
        <div>
            <Breadcrumbs crumbs={[{ label: '2 - NorgesGruppen Data' }]} />

            <div className="mb-6">
                <h1 className="text-xl font-semibold text-foreground">2 - NorgesGruppen Data</h1>
                <p className="text-sm text-secondary mt-1">
                    Object detection on grocery store shelves. Detect and classify 356 product categories.
                </p>
                <p className="text-xs text-muted mt-1">
                    Score = 0.7 x detection mAP@0.5 + 0.3 x classification mAP@0.5
                </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {cards.map(({ to, icon: Icon, title, description }) => (
                    <Link
                        key={to}
                        to={to}
                        className="bg-surface rounded-lg border border-border/60 shadow-gcp p-6 hover:shadow-gcp-hover hover:border-primary/30 transition-all group"
                    >
                        <div className="flex items-center gap-3 mb-3">
                            <div className="p-2 rounded-lg bg-primary/10 text-primary group-hover:bg-primary/20 transition-colors">
                                <Icon className="w-5 h-5" />
                            </div>
                            <h2 className="text-base font-semibold text-foreground">{title}</h2>
                        </div>
                        <p className="text-sm text-secondary leading-relaxed">{description}</p>
                    </Link>
                ))}
            </div>
        </div>
    );
}
