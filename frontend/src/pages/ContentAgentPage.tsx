import { useState } from 'react'
import { Sparkles, Plus, RefreshCw, Trash2, Zap, BarChart3 } from 'lucide-react'
import {
    useContentTopics,
    useContentAgentStats,
    useContentExamples,
    useContentPerformance,
    useCreateTopic,
    useDeleteTopic,
    useGenerateRules,
    useGenerateContent,
    useRunImprovementCycle,
    useAddExample,
    type ContentTopic,
    type ContentTopicStatus,
} from '@/hooks/useContentAgentApi'

const STATUS_COLORS: Record<ContentTopicStatus, string> = {
    draft: 'bg-gray-500/20 text-gray-400',
    active: 'bg-green-500/20 text-green-400',
    paused: 'bg-yellow-500/20 text-yellow-400',
    archived: 'bg-red-500/20 text-red-400',
}

function RuleCard({ rule }: { rule: { id: string; text: string; source: string; effectiveness_score: number; times_applied: number } }) {
    const score = rule.effectiveness_score ?? 0
    const color = score >= 70 ? 'text-green-400' : score >= 40 ? 'text-yellow-400' : 'text-red-400'
    return (
        <div className="bg-white/5 rounded p-3 flex items-start gap-3">
            <div className="text-center min-w-[40px]">
                <div className={`text-lg font-bold ${color}`}>{(rule.effectiveness_score ?? 0).toFixed(0)}</div>
                <div className="text-[10px] text-gray-500">{rule.times_applied}x</div>
            </div>
            <div className="flex-1">
                <p className="text-sm text-gray-300">{rule.text}</p>
                <span className="text-[10px] text-gray-500 uppercase">{rule.source}</span>
            </div>
        </div>
    )
}

function TopicDetail({ topic }: { topic: ContentTopic }) {
    const { data: examples } = useContentExamples(topic.id)
    const { data: performance } = useContentPerformance(topic.id)
    const generateRules = useGenerateRules()
    const generateContent = useGenerateContent()
    const addExample = useAddExample()
    const [showAddExample, setShowAddExample] = useState(false)
    const [exampleTitle, setExampleTitle] = useState('')
    const [exampleCaption, setExampleCaption] = useState('')

    const handleAddExample = () => {
        if (!exampleTitle.trim()) return
        addExample.mutate({
            topicId: topic.id,
            data: { title: exampleTitle, caption: exampleCaption || undefined },
        })
        setExampleTitle('')
        setExampleCaption('')
        setShowAddExample(false)
    }

    return (
        <div className="space-y-4">
            {/* Rules */}
            <div>
                <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-medium text-gray-300">Rules ({topic.rules?.length || 0})</h3>
                    <button
                        onClick={() => generateRules.mutate({ topicId: topic.id })}
                        disabled={generateRules.isPending}
                        className="btn-secondary text-xs gap-1"
                    >
                        <Sparkles className="w-3 h-3" />
                        {generateRules.isPending ? 'Generating...' : 'Generate Rules'}
                    </button>
                </div>
                {topic.rules && topic.rules.length > 0 ? (
                    <div className="space-y-2">
                        {topic.rules.map(rule => <RuleCard key={rule.id} rule={rule} />)}
                    </div>
                ) : (
                    <p className="text-sm text-gray-500">No rules yet. Add examples then generate rules.</p>
                )}
            </div>

            {/* Examples */}
            <div>
                <div className="flex items-center justify-between mb-2">
                    <h3 className="text-sm font-medium text-gray-300">Examples ({examples?.length || 0})</h3>
                    <button
                        onClick={() => setShowAddExample(!showAddExample)}
                        className="btn-secondary text-xs gap-1"
                    >
                        <Plus className="w-3 h-3" />
                        Add Example
                    </button>
                </div>
                {showAddExample && (
                    <div className="bg-white/5 rounded p-3 mb-2 space-y-2">
                        <input
                            type="text"
                            placeholder="Example title..."
                            value={exampleTitle}
                            onChange={e => setExampleTitle(e.target.value)}
                            className="w-full bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm"
                        />
                        <textarea
                            placeholder="Caption / script (optional)..."
                            value={exampleCaption}
                            onChange={e => setExampleCaption(e.target.value)}
                            className="w-full bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm h-20 resize-none"
                        />
                        <button onClick={handleAddExample} disabled={addExample.isPending} className="btn-primary text-xs">
                            {addExample.isPending ? 'Adding...' : 'Add'}
                        </button>
                    </div>
                )}
                {examples && examples.length > 0 ? (
                    <div className="space-y-1">
                        {examples.slice(0, 10).map(ex => (
                            <div key={ex.id} className="bg-white/5 rounded p-2 flex items-center justify-between">
                                <div>
                                    <div className="text-sm font-medium">{ex.title}</div>
                                    {ex.caption && <div className="text-xs text-gray-400 truncate max-w-md">{ex.caption}</div>}
                                </div>
                                <div className="text-xs text-gray-500">
                                    {ex.views > 0 && <span>{ex.views.toLocaleString()} views</span>}
                                    {' '}<span className="text-indigo-400">{(ex.performance_score ?? 0).toFixed(0)}pts</span>
                                </div>
                            </div>
                        ))}
                    </div>
                ) : (
                    <p className="text-sm text-gray-500">No examples yet.</p>
                )}
            </div>

            {/* Generate Content */}
            <div className="flex gap-2 pt-2 border-t border-white/5">
                <button
                    onClick={() => generateContent.mutate({ topic_id: topic.id })}
                    disabled={generateContent.isPending}
                    className="btn-primary text-xs gap-1"
                >
                    <Zap className="w-3 h-3" />
                    {generateContent.isPending ? 'Generating...' : 'Generate Content'}
                </button>
            </div>

            {/* Performance */}
            {performance && performance.length > 0 && (
                <div>
                    <h3 className="text-sm font-medium text-gray-300 mb-2">Recent Performance</h3>
                    <div className="space-y-1">
                        {performance.slice(0, 5).map(perf => (
                            <div key={perf.id} className="bg-white/5 rounded p-2 flex items-center justify-between text-xs">
                                <span className="text-gray-400">{perf.platform} | {perf.content_type || 'video'}</span>
                                <div className="flex gap-3 text-gray-300">
                                    <span>{perf.views.toLocaleString()} views</span>
                                    <span>{perf.likes} likes</span>
                                    <span className="text-indigo-400">{(perf.engagement_rate ?? 0).toFixed(1)}% eng</span>
                                    <span className="font-medium">{(perf.performance_score ?? 0).toFixed(0)}pts</span>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}

export function ContentAgentPage() {
    const [statusFilter, setStatusFilter] = useState<ContentTopicStatus | ''>('')
    const [selectedTopicId, setSelectedTopicId] = useState<string | null>(null)
    const { data: topics, isLoading } = useContentTopics(statusFilter || undefined)
    const { data: stats } = useContentAgentStats()
    const createTopic = useCreateTopic()
    const deleteTopic = useDeleteTopic()
    const improvementCycle = useRunImprovementCycle()
    const [showCreate, setShowCreate] = useState(false)
    const [newName, setNewName] = useState('')
    const [newPlatform, setNewPlatform] = useState('tiktok')
    const [newNiche, setNewNiche] = useState('')

    const selectedTopic = topics?.find(t => t.id === selectedTopicId)

    const handleCreate = () => {
        if (!newName.trim()) return
        createTopic.mutate({
            name: newName,
            platform: newPlatform,
            niche: newNiche || undefined,
        })
        setNewName('')
        setNewNiche('')
        setShowCreate(false)
    }

    return (
        <div className="page-content space-y-6">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="page-title flex items-center gap-2">
                        <Sparkles className="w-8 h-8 text-purple-400" />
                        Content Agent
                    </h1>
                    <p className="text-muted-foreground">Topics, rules, examples & self-improving content generation</p>
                </div>
                <div className="flex gap-2">
                    <button
                        onClick={() => improvementCycle.mutate(undefined)}
                        disabled={improvementCycle.isPending}
                        className="btn-secondary gap-2"
                    >
                        <RefreshCw className={`w-4 h-4 ${improvementCycle.isPending ? 'animate-spin' : ''}`} />
                        {improvementCycle.isPending ? 'Improving...' : 'Improvement Cycle'}
                    </button>
                    <button
                        onClick={() => setShowCreate(!showCreate)}
                        className="btn-primary gap-2"
                    >
                        <Plus className="w-4 h-4" />
                        New Topic
                    </button>
                </div>
            </div>

            {/* Create Topic Form */}
            {showCreate && (
                <div className="glass-card p-4 space-y-3">
                    <div className="flex gap-3">
                        <input
                            type="text"
                            placeholder="Topic name..."
                            value={newName}
                            onChange={e => setNewName(e.target.value)}
                            className="flex-1 bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm"
                        />
                        <select
                            value={newPlatform}
                            onChange={e => setNewPlatform(e.target.value)}
                            className="bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm"
                        >
                            <option value="tiktok">TikTok</option>
                            <option value="instagram">Instagram</option>
                            <option value="youtube_shorts">YouTube Shorts</option>
                            <option value="general">General</option>
                        </select>
                        <input
                            type="text"
                            placeholder="Niche (optional)..."
                            value={newNiche}
                            onChange={e => setNewNiche(e.target.value)}
                            className="bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm w-40"
                        />
                        <button onClick={handleCreate} disabled={createTopic.isPending} className="btn-primary text-sm">
                            {createTopic.isPending ? 'Creating...' : 'Create'}
                        </button>
                    </div>
                </div>
            )}

            {/* Stats */}
            {stats && (
                <div className="grid grid-cols-2 md:grid-cols-6 gap-4">
                    <div className="glass-card p-4">
                        <div className="text-sm text-gray-400 mb-1">Topics</div>
                        <div className="text-2xl font-bold">{stats.total_topics}</div>
                    </div>
                    <div className="glass-card p-4">
                        <div className="text-sm text-gray-400 mb-1">Active</div>
                        <div className="text-2xl font-bold text-green-400">{stats.active_topics}</div>
                    </div>
                    <div className="glass-card p-4">
                        <div className="text-sm text-gray-400 mb-1">Examples</div>
                        <div className="text-2xl font-bold text-blue-400">{stats.total_examples}</div>
                    </div>
                    <div className="glass-card p-4">
                        <div className="text-sm text-gray-400 mb-1">Generated</div>
                        <div className="text-2xl font-bold text-purple-400">{stats.total_generated}</div>
                    </div>
                    <div className="glass-card p-4">
                        <div className="text-sm text-gray-400 mb-1">Rules</div>
                        <div className="text-2xl font-bold text-yellow-400">{stats.total_rules}</div>
                    </div>
                    <div className="glass-card p-4">
                        <div className="text-sm text-gray-400 mb-1">Avg Score</div>
                        <div className="text-2xl font-bold text-indigo-400">{(stats.avg_performance_score ?? 0).toFixed(0)}</div>
                    </div>
                </div>
            )}

            {/* Filter */}
            <div className="flex gap-3">
                <select
                    value={statusFilter}
                    onChange={e => setStatusFilter(e.target.value as ContentTopicStatus | '')}
                    className="bg-gray-800 border border-white/10 rounded px-3 py-1.5 text-sm"
                >
                    <option value="">All Statuses</option>
                    <option value="draft">Draft</option>
                    <option value="active">Active</option>
                    <option value="paused">Paused</option>
                    <option value="archived">Archived</option>
                </select>
            </div>

            {/* Two-column layout: Topics list + Detail */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Topics List */}
                <div className="lg:col-span-1 space-y-2">
                    {isLoading ? (
                        <div className="text-center text-gray-500 py-8">Loading topics...</div>
                    ) : !topics || topics.length === 0 ? (
                        <div className="text-center text-gray-500 py-8">
                            <Sparkles className="w-10 h-10 mx-auto mb-2 opacity-30" />
                            <p>No content topics yet.</p>
                        </div>
                    ) : (
                        topics.map(topic => (
                            <div
                                key={topic.id}
                                onClick={() => setSelectedTopicId(topic.id)}
                                className={`glass-card p-3 cursor-pointer hover:bg-white/5 transition-colors ${
                                    selectedTopicId === topic.id ? 'ring-1 ring-indigo-500' : ''
                                }`}
                            >
                                <div className="flex items-center justify-between">
                                    <div className="font-medium truncate">{topic.name}</div>
                                    <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${STATUS_COLORS[topic.status]}`}>
                                        {topic.status}
                                    </span>
                                </div>
                                <div className="text-xs text-gray-400 mt-1 flex items-center gap-2">
                                    <span>{topic.platform}</span>
                                    <span className="text-gray-600">|</span>
                                    <span>{topic.rules?.length || 0} rules</span>
                                    <span className="text-gray-600">|</span>
                                    <span>{topic.examples_count} examples</span>
                                </div>
                                {topic.avg_performance_score > 0 && (
                                    <div className="text-xs text-indigo-400 mt-0.5 flex items-center gap-1">
                                        <BarChart3 className="w-3 h-3" />
                                        {(topic.avg_performance_score ?? 0).toFixed(0)} avg score
                                    </div>
                                )}
                                <div className="flex justify-end mt-1">
                                    <button
                                        onClick={(e) => { e.stopPropagation(); deleteTopic.mutate(topic.id) }}
                                        className="text-gray-600 hover:text-red-400 transition-colors"
                                    >
                                        <Trash2 className="w-3 h-3" />
                                    </button>
                                </div>
                            </div>
                        ))
                    )}
                </div>

                {/* Topic Detail */}
                <div className="lg:col-span-2">
                    {selectedTopic ? (
                        <div className="glass-card p-4">
                            <div className="flex items-center justify-between mb-4">
                                <div>
                                    <h2 className="text-lg font-semibold">{selectedTopic.name}</h2>
                                    <div className="text-sm text-gray-400">
                                        {selectedTopic.platform} | {selectedTopic.niche || 'general'}
                                        {selectedTopic.content_generated_count > 0 && ` | ${selectedTopic.content_generated_count} generated`}
                                    </div>
                                </div>
                                <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[selectedTopic.status]}`}>
                                    {selectedTopic.status}
                                </span>
                            </div>
                            {selectedTopic.description && (
                                <p className="text-sm text-gray-400 mb-4">{selectedTopic.description}</p>
                            )}
                            <TopicDetail topic={selectedTopic} />
                        </div>
                    ) : (
                        <div className="glass-card p-8 text-center text-gray-500">
                            <Sparkles className="w-12 h-12 mx-auto mb-3 opacity-30" />
                            <p>Select a topic to view details, rules & examples</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
