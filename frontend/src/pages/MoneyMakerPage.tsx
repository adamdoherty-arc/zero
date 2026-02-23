import { useState } from 'react'
import { Plus, DollarSign, Activity } from 'lucide-react'
import {
    useMoneyMakerIdeas,
    useGenerateIdeas,
    useResearchIdea,
    type MoneyIdea,
    type IdeaStatus
} from '@/hooks/useMoneyMakerApi'

export function MoneyMakerPage() {
    const [activeTab, setActiveTab] = useState<IdeaStatus | 'all'>('all')
    const { data: ideas, isLoading } = useMoneyMakerIdeas(activeTab === 'all' ? undefined : activeTab)
    const generateMutation = useGenerateIdeas()
    const researchMutation = useResearchIdea()

    const handleGenerate = () => {
        generateMutation.mutate({ count: 3 })
    }

    const handleResearch = (id: string) => {
        researchMutation.mutate(id)
    }

    return (
        <div className="page-content space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="page-title flex items-center gap-2">
                        <DollarSign className="w-8 h-8 text-green-400" />
                        Money Maker
                    </h1>
                    <p className="text-muted-foreground">AI-powered business idea generator & validator</p>
                </div>
                <button
                    onClick={handleGenerate}
                    disabled={generateMutation.isPending}
                    className="btn-primary gap-2"
                >
                    <Plus className="w-4 h-4" />
                    {generateMutation.isPending ? 'Generating...' : 'Generate New Ideas'}
                </button>
            </div>

            {/* Stats Cards Placeholder */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="glass-card p-4">
                    <div className="text-sm text-gray-400 mb-1">Total Ideas</div>
                    <div className="text-2xl font-bold">{ideas?.length || 0}</div>
                </div>
                <div className="glass-card p-4">
                    <div className="text-sm text-gray-400 mb-1">High Potential</div>
                    <div className="text-2xl font-bold text-green-400">
                        {ideas?.filter(i => i.viability_score > 70).length || 0}
                    </div>
                </div>
            </div>

            {/* Tabs */}
            <div className="flex gap-2 border-b border-white/10 pb-2">
                {['all', 'new', 'researching', 'validated', 'pursuing'].map((tab) => (
                    <button
                        key={tab}
                        onClick={() => setActiveTab(tab as IdeaStatus | 'all')}
                        className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${activeTab === tab
                                ? 'bg-primary/20 text-primary'
                                : 'text-muted-foreground hover:bg-white/5'
                            }`}
                    >
                        {tab.charAt(0).toUpperCase() + tab.slice(1)}
                    </button>
                ))}
            </div>

            {/* Content */}
            {isLoading ? (
                <div className="text-center py-12 text-muted-foreground">Loading ideas...</div>
            ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {ideas?.map((idea) => (
                        <IdeaCard key={idea.id} idea={idea} onResearch={() => handleResearch(idea.id)} isResearching={researchMutation.isPending} />
                    ))}
                    {ideas?.length === 0 && (
                        <div className="col-span-full text-center py-12 text-muted-foreground glass-card">
                            No ideas found. Click "Generate" to start.
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

function IdeaCard({ idea, onResearch, isResearching }: { idea: MoneyIdea; onResearch: () => void, isResearching: boolean }) {
    const getScoreColor = (score: number) => {
        if (score >= 75) return 'text-green-400'
        if (score >= 50) return 'text-yellow-400'
        return 'text-red-400'
    }

    return (
        <div className="glass-card p-5 flex flex-col h-full hover:border-primary/50 transition-colors">
            <div className="flex justify-between items-start mb-3">
                <span className={`badge ${idea.category === 'saas' ? 'badge-info' : 'badge-neutral'
                    }`}>
                    {idea.category}
                </span>
                <div className="flex items-center gap-1 font-mono text-sm">
                    <Activity className="w-3 h-3 text-muted-foreground" />
                    <span className={getScoreColor(idea.viability_score)}>
                        {idea.viability_score.toFixed(0)}
                    </span>
                </div>
            </div>

            <h3 className="font-semibold text-lg mb-2 line-clamp-2">{idea.title}</h3>
            <p className="text-sm text-muted-foreground mb-4 line-clamp-3 flex-1">
                {idea.description}
            </p>

            <div className="grid grid-cols-2 gap-2 text-xs text-muted-foreground mb-4">
                <div className="flex flex-col">
                    <span>Effort</span>
                    <span className="font-medium text-foreground">{idea.effort_score}/100</span>
                </div>
                <div className="flex flex-col">
                    <span>Revenue</span>
                    <span className="font-medium text-foreground">${idea.revenue_potential.toLocaleString()}/mo</span>
                </div>
            </div>

            <div className="mt-auto border-t border-white/10 pt-4 flex gap-2">
                {idea.status === 'new' && (
                    <button
                        onClick={onResearch}
                        disabled={isResearching}
                        className="btn-secondary w-full text-xs"
                    >
                        {isResearching ? 'Researching...' : 'Deep Research'}
                    </button>
                )}
                {idea.status === 'validated' && (
                    <button className="btn-primary w-full text-xs">
                        Pursue Idea
                    </button>
                )}
                <button className="btn-ghost w-full text-xs">
                    Details
                </button>
            </div>
        </div>
    )
}
