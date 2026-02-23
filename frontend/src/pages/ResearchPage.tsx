import { useState } from 'react'
import {
  Search, Plus, Play, ExternalLink, CheckCircle, XCircle,
  ListTodo, TrendingUp, Clock, Zap, BarChart3, RefreshCw,
  Shield, ToggleLeft, ToggleRight, Trash2, Sparkles
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  useResearchTopics, useCreateResearchTopic, useDeleteResearchTopic,
  useResearchFindings, useTopFindings, useReviewFinding, useDismissFinding,
  useCreateTaskFromFinding, useResearchCycles, useResearchStats,
  useRunResearchCycle, useSeedResearchTopics,
  useResearchRules, useResearchRuleStats, useToggleResearchRule,
  useDeleteResearchRule, useRecalibrateRules,
} from '@/hooks/useSprintApi'
import type { ResearchTopic, ResearchFinding, ResearchTopicCreate, ResearchRule } from '@/types'

function scoreColor(score: number): string {
  if (score >= 75) return 'text-emerald-400'
  if (score >= 50) return 'text-amber-400'
  return 'text-red-400'
}

function scoreBg(score: number): string {
  if (score >= 75) return 'bg-emerald-400/10 border-emerald-800/50'
  if (score >= 50) return 'bg-amber-400/10 border-amber-800/50'
  return 'bg-red-400/10 border-red-800/50'
}

const STATUS_BADGES: Record<string, string> = {
  active: 'text-emerald-400 bg-emerald-400/10',
  paused: 'text-amber-400 bg-amber-400/10',
  archived: 'text-zinc-400 bg-zinc-400/10',
  new: 'text-blue-400 bg-blue-400/10',
  reviewed: 'text-emerald-400 bg-emerald-400/10',
  actionable: 'text-amber-400 bg-amber-400/10',
  task_created: 'text-purple-400 bg-purple-400/10',
  dismissed: 'text-zinc-500 bg-zinc-500/10',
}

export function ResearchPage() {
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [findingFilter, setFindingFilter] = useState<string>('all')

  const { data: topics, isLoading: topicsLoading } = useResearchTopics()
  const { data: findings, isLoading: findingsLoading } = useResearchFindings({
    status: findingFilter !== 'all' ? findingFilter : undefined,
    limit: 50,
  })
  const { data: topFindings } = useTopFindings(5)
  const { data: cycles } = useResearchCycles(5)
  const { data: stats } = useResearchStats()

  const { data: rules, isLoading: rulesLoading } = useResearchRules()
  const { data: ruleStats } = useResearchRuleStats()

  const createTopic = useCreateResearchTopic()
  const deleteTopic = useDeleteResearchTopic()
  const reviewFinding = useReviewFinding()
  const dismissFinding = useDismissFinding()
  const createTask = useCreateTaskFromFinding()
  const runCycle = useRunResearchCycle()
  const seedTopics = useSeedResearchTopics()
  const toggleRule = useToggleResearchRule()
  const deleteRule = useDeleteResearchRule()
  const recalibrateRules = useRecalibrateRules()

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2">Research Agent</h1>
          <p className="text-zinc-400">Automated research cycles, findings, and self-improvement</p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={() => runCycle.mutate()}
            disabled={runCycle.isPending}
            variant="outline"
            className="gap-2"
          >
            <Play className={`w-4 h-4 ${runCycle.isPending ? 'animate-spin' : ''}`} />
            {runCycle.isPending ? 'Running...' : 'Run Cycle'}
          </Button>
          <Button onClick={() => setShowCreateDialog(true)} className="gap-2">
            <Plus className="w-4 h-4" />
            New Topic
          </Button>
        </div>
      </div>

      {/* Stats Bar */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3 mb-6">
          <StatCard label="Active Topics" value={stats.active_topics} icon={<Search className="w-4 h-4 text-teal-400" />} />
          <StatCard label="Total Findings" value={stats.total_findings} icon={<Zap className="w-4 h-4 text-amber-400" />} />
          <StatCard label="This Week" value={stats.findings_this_week} icon={<TrendingUp className="w-4 h-4 text-emerald-400" />} />
          <StatCard label="Tasks Created" value={stats.tasks_created_total} icon={<ListTodo className="w-4 h-4 text-purple-400" />} />
          <StatCard
            label="Avg Relevance"
            value={Math.round(stats.avg_relevance_score)}
            icon={<BarChart3 className={`w-4 h-4 ${scoreColor(stats.avg_relevance_score)}`} />}
            suffix="%"
          />
        </div>
      )}

      <Tabs defaultValue="topics" className="space-y-4">
        <TabsList className="bg-zinc-900 border-zinc-800">
          <TabsTrigger value="topics">Topics</TabsTrigger>
          <TabsTrigger value="findings">Findings</TabsTrigger>
          <TabsTrigger value="cycles">Cycles</TabsTrigger>
          <TabsTrigger value="rules">Rules</TabsTrigger>
        </TabsList>

        {/* Topics Tab */}
        <TabsContent value="topics" className="space-y-4">
          {topicsLoading ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <Card key={i} className="p-4 bg-zinc-900/50 border-zinc-800">
                  <Skeleton className="h-5 w-48 mb-2" />
                  <Skeleton className="h-4 w-full" />
                </Card>
              ))}
            </div>
          ) : !topics || topics.length === 0 ? (
            <Card className="p-12 bg-zinc-900/50 border-zinc-800">
              <div className="text-center">
                <Search className="w-12 h-12 mx-auto mb-4 text-zinc-600" />
                <p className="text-zinc-400 mb-4">No research topics yet.</p>
                <div className="flex gap-2 justify-center">
                  <Button onClick={() => seedTopics.mutate()} variant="outline" className="gap-2" disabled={seedTopics.isPending}>
                    <RefreshCw className={`w-4 h-4 ${seedTopics.isPending ? 'animate-spin' : ''}`} />
                    Seed Default Topics
                  </Button>
                  <Button onClick={() => setShowCreateDialog(true)} className="gap-2">
                    <Plus className="w-4 h-4" />
                    Create Topic
                  </Button>
                </div>
              </div>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {topics.map((topic) => (
                <TopicCard
                  key={topic.id}
                  topic={topic}
                  onDelete={() => deleteTopic.mutate(topic.id)}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Findings Tab */}
        <TabsContent value="findings" className="space-y-4">
          {/* Top findings highlight */}
          {topFindings && topFindings.length > 0 && (
            <Card className="p-4 bg-indigo-900/20 border-indigo-800/50">
              <h3 className="text-sm font-medium text-indigo-300 mb-2">Top Findings</h3>
              <div className="space-y-2">
                {topFindings.slice(0, 3).map((f) => (
                  <div key={f.id} className="flex items-center gap-2 text-sm">
                    <span className={`font-mono font-bold ${scoreColor(f.composite_score)}`}>
                      {Math.round(f.composite_score)}
                    </span>
                    <span className="text-zinc-300 truncate">{f.title}</span>
                  </div>
                ))}
              </div>
            </Card>
          )}

          <div className="flex gap-2">
            {['all', 'new', 'reviewed', 'actionable', 'task_created', 'dismissed'].map((s) => (
              <Button
                key={s}
                variant={findingFilter === s ? 'default' : 'outline'}
                size="sm"
                onClick={() => setFindingFilter(s)}
                className="capitalize"
              >
                {s === 'all' ? 'All' : s.replace('_', ' ')}
              </Button>
            ))}
          </div>

          {findingsLoading ? (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <Card key={i} className="p-4 bg-zinc-900/50 border-zinc-800">
                  <Skeleton className="h-5 w-64 mb-2" />
                  <Skeleton className="h-4 w-full" />
                </Card>
              ))}
            </div>
          ) : !findings || findings.length === 0 ? (
            <Card className="p-8 bg-zinc-900/50 border-zinc-800">
              <p className="text-center text-zinc-400">No findings yet. Run a research cycle to discover new content.</p>
            </Card>
          ) : (
            <div className="space-y-2">
              {findings.map((finding) => (
                <FindingCard
                  key={finding.id}
                  finding={finding}
                  onReview={() => reviewFinding.mutate(finding.id)}
                  onDismiss={() => dismissFinding.mutate(finding.id)}
                  onCreateTask={() => createTask.mutate(finding.id)}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Cycles Tab */}
        <TabsContent value="cycles" className="space-y-4">
          {!cycles || cycles.length === 0 ? (
            <Card className="p-8 bg-zinc-900/50 border-zinc-800">
              <div className="text-center">
                <Clock className="w-12 h-12 mx-auto mb-4 text-zinc-600" />
                <p className="text-zinc-400 mb-4">No research cycles run yet.</p>
                <Button onClick={() => runCycle.mutate()} disabled={runCycle.isPending} className="gap-2">
                  <Play className="w-4 h-4" />
                  Run First Cycle
                </Button>
              </div>
            </Card>
          ) : (
            <div className="space-y-3">
              {cycles.map((cycle) => (
                <Card key={cycle.cycle_id} className="p-4 bg-zinc-900/50 border-zinc-800">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <Clock className="w-4 h-4 text-zinc-500" />
                      <span className="text-sm text-zinc-300">
                        {new Date(cycle.started_at).toLocaleString()}
                      </span>
                    </div>
                    {cycle.errors.length > 0 && (
                      <Badge variant="outline" className="text-red-400 border-red-800">
                        {cycle.errors.length} errors
                      </Badge>
                    )}
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
                    <div>
                      <p className="text-zinc-500">Topics</p>
                      <p className="text-white font-medium">{cycle.topics_researched}</p>
                    </div>
                    <div>
                      <p className="text-zinc-500">Results</p>
                      <p className="text-white font-medium">{cycle.total_results}</p>
                    </div>
                    <div>
                      <p className="text-zinc-500">New Findings</p>
                      <p className="text-emerald-400 font-medium">{cycle.new_findings}</p>
                    </div>
                    <div>
                      <p className="text-zinc-500">High Value</p>
                      <p className="text-amber-400 font-medium">{cycle.high_value_findings}</p>
                    </div>
                    <div>
                      <p className="text-zinc-500">Tasks Created</p>
                      <p className="text-purple-400 font-medium">{cycle.tasks_created}</p>
                    </div>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </TabsContent>
        {/* Rules Tab */}
        <TabsContent value="rules" className="space-y-4">
          {/* Rules Stats */}
          {ruleStats && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <Card className="p-3 bg-zinc-900/50 border-zinc-800">
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-indigo-400" />
                  <div>
                    <p className="text-xl font-bold text-white">{ruleStats.enabled_rules}/{ruleStats.total_rules}</p>
                    <p className="text-xs text-zinc-500">Active Rules</p>
                  </div>
                </div>
              </Card>
              <Card className="p-3 bg-zinc-900/50 border-zinc-800">
                <div className="flex items-center gap-2">
                  <Zap className="w-4 h-4 text-amber-400" />
                  <div>
                    <p className="text-xl font-bold text-white">{ruleStats.total_fires}</p>
                    <p className="text-xs text-zinc-500">Total Fires</p>
                  </div>
                </div>
              </Card>
              <Card className="p-3 bg-zinc-900/50 border-zinc-800">
                <div className="flex items-center gap-2">
                  <CheckCircle className="w-4 h-4 text-emerald-400" />
                  <div>
                    <p className="text-xl font-bold text-white">{ruleStats.total_useful}</p>
                    <p className="text-xs text-zinc-500">Useful Hits</p>
                  </div>
                </div>
              </Card>
              <Card className="p-3 bg-zinc-900/50 border-zinc-800">
                <div className="flex items-center gap-2">
                  <BarChart3 className="w-4 h-4 text-cyan-400" />
                  <div>
                    <p className="text-xl font-bold text-white">
                      {ruleStats.total_fires > 0 ? Math.round((ruleStats.total_useful / ruleStats.total_fires) * 100) : 0}%
                    </p>
                    <p className="text-xs text-zinc-500">Hit Rate</p>
                  </div>
                </div>
              </Card>
            </div>
          )}

          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => recalibrateRules.mutate()}
              disabled={recalibrateRules.isPending}
              className="gap-2"
            >
              <Sparkles className={`w-4 h-4 ${recalibrateRules.isPending ? 'animate-spin' : ''}`} />
              {recalibrateRules.isPending ? 'Recalibrating...' : 'Recalibrate'}
            </Button>
          </div>

          {rulesLoading ? (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <Card key={i} className="p-4 bg-zinc-900/50 border-zinc-800">
                  <Skeleton className="h-5 w-48 mb-2" />
                  <Skeleton className="h-4 w-full" />
                </Card>
              ))}
            </div>
          ) : !rules || rules.length === 0 ? (
            <Card className="p-12 bg-zinc-900/50 border-zinc-800">
              <div className="text-center">
                <Shield className="w-12 h-12 mx-auto mb-4 text-zinc-600" />
                <p className="text-zinc-400">No research rules yet. Rules are seeded automatically on startup.</p>
              </div>
            </Card>
          ) : (
            <div className="space-y-2">
              {rules.map((rule: ResearchRule) => (
                <RuleCard
                  key={rule.id}
                  rule={rule}
                  onToggle={() => toggleRule.mutate(rule.id)}
                  onDelete={() => deleteRule.mutate(rule.id)}
                />
              ))}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* Create Topic Dialog */}
      <CreateTopicDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        onSave={(data) => {
          createTopic.mutate(data, { onSuccess: () => setShowCreateDialog(false) })
        }}
        saving={createTopic.isPending}
      />
    </div>
  )
}

function StatCard({ label, value, icon, suffix }: { label: string; value: number; icon: React.ReactNode; suffix?: string }) {
  return (
    <Card className="p-3 bg-zinc-900/50 border-zinc-800">
      <div className="flex items-center gap-2">
        {icon}
        <div>
          <p className="text-xl font-bold text-white">{value}{suffix}</p>
          <p className="text-xs text-zinc-500">{label}</p>
        </div>
      </div>
    </Card>
  )
}

function TopicCard({ topic, onDelete: _onDelete }: { topic: ResearchTopic; onDelete: () => void }) {
  return (
    <Card className={`p-4 border ${scoreBg(topic.relevance_score)}`}>
      <div className="flex items-start justify-between mb-2">
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-white">{topic.name}</h3>
          <Badge className={`text-xs ${STATUS_BADGES[topic.status] || ''}`}>{topic.status}</Badge>
        </div>
        <span className={`text-lg font-mono font-bold ${scoreColor(topic.relevance_score)}`}>
          {Math.round(topic.relevance_score)}
        </span>
      </div>
      {topic.description && (
        <p className="text-sm text-zinc-400 mb-2 line-clamp-2">{topic.description}</p>
      )}
      <div className="flex items-center justify-between text-xs text-zinc-500">
        <div className="flex items-center gap-3">
          <span>{topic.findings_count} findings</span>
          <span>{topic.frequency}</span>
          {topic.last_researched_at && (
            <span>Last: {new Date(topic.last_researched_at).toLocaleDateString()}</span>
          )}
        </div>
        <div className="flex gap-1">
          {topic.category_tags.slice(0, 3).map((tag) => (
            <Badge key={tag} variant="outline" className="text-xs">{tag}</Badge>
          ))}
        </div>
      </div>
    </Card>
  )
}

function FindingCard({ finding, onReview, onDismiss, onCreateTask }: {
  finding: ResearchFinding
  onReview: () => void
  onDismiss: () => void
  onCreateTask: () => void
}) {
  return (
    <Card className="p-4 bg-zinc-900/50 border-zinc-800 hover:border-zinc-700 transition-colors">
      <div className="flex items-start gap-3">
        <div className={`text-lg font-mono font-bold ${scoreColor(finding.composite_score)} shrink-0 w-10 text-center`}>
          {Math.round(finding.composite_score)}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <a
              href={finding.url}
              target="_blank"
              rel="noopener noreferrer"
              className="font-semibold text-white hover:text-indigo-300 transition-colors truncate"
            >
              {finding.title}
              <ExternalLink className="inline w-3 h-3 ml-1 opacity-50" />
            </a>
            <Badge className={`text-xs shrink-0 ${STATUS_BADGES[finding.status] || ''}`}>{finding.status}</Badge>
            <Badge variant="outline" className="text-xs shrink-0">{finding.category}</Badge>
          </div>
          {finding.llm_summary && (
            <p className="text-sm text-zinc-400 mb-2 line-clamp-2">{finding.llm_summary}</p>
          )}
          {!finding.llm_summary && finding.snippet && (
            <p className="text-sm text-zinc-500 mb-2 line-clamp-2">{finding.snippet}</p>
          )}
          <div className="flex items-center justify-between">
            <div className="flex gap-2 text-xs text-zinc-600">
              <span>R:{Math.round(finding.relevance_score)}</span>
              <span>N:{Math.round(finding.novelty_score)}</span>
              <span>A:{Math.round(finding.actionability_score)}</span>
              {finding.source_engine && <span>{finding.source_engine}</span>}
              <span>{new Date(finding.discovered_at).toLocaleDateString()}</span>
            </div>
            {finding.status === 'new' && (
              <div className="flex gap-1">
                <Button variant="ghost" size="sm" onClick={onReview} className="text-emerald-400 hover:text-emerald-300 h-7 px-2 text-xs">
                  <CheckCircle className="w-3 h-3 mr-1" />
                  Review
                </Button>
                <Button variant="ghost" size="sm" onClick={onCreateTask} className="text-purple-400 hover:text-purple-300 h-7 px-2 text-xs">
                  <ListTodo className="w-3 h-3 mr-1" />
                  Task
                </Button>
                <Button variant="ghost" size="sm" onClick={onDismiss} className="text-zinc-500 hover:text-zinc-300 h-7 px-2 text-xs">
                  <XCircle className="w-3 h-3 mr-1" />
                  Dismiss
                </Button>
              </div>
            )}
          </div>
        </div>
      </div>
    </Card>
  )
}

function CreateTopicDialog({
  open, onOpenChange, onSave, saving,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSave: (data: ResearchTopicCreate) => void
  saving: boolean
}) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [queries, setQueries] = useState('')
  const [tags, setTags] = useState('')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-zinc-900 border-zinc-800 text-white max-w-lg">
        <DialogHeader>
          <DialogTitle>New Research Topic</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label className="text-zinc-400">Topic Name</Label>
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. AI Agent Frameworks"
              className="bg-zinc-800 border-zinc-700"
            />
          </div>
          <div>
            <Label className="text-zinc-400">Description</Label>
            <Input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What to research and why..."
              className="bg-zinc-800 border-zinc-700"
            />
          </div>
          <div>
            <Label className="text-zinc-400">Search Queries (one per line)</Label>
            <textarea
              value={queries}
              onChange={(e) => setQueries(e.target.value)}
              placeholder={"AI agent frameworks 2026\nautonomous coding tools\nLLM orchestration patterns"}
              rows={3}
              className="w-full px-3 py-2 rounded-md bg-zinc-800 border border-zinc-700 text-white placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-y"
            />
          </div>
          <div>
            <Label className="text-zinc-400">Tags (comma separated)</Label>
            <Input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="e.g. ai, agents, tools"
              className="bg-zinc-800 border-zinc-700"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            onClick={() => {
              if (!name.trim()) return
              onSave({
                name: name.trim(),
                description: description.trim() || undefined,
                search_queries: queries.split('\n').map(q => q.trim()).filter(Boolean),
                category_tags: tags.split(',').map(t => t.trim()).filter(Boolean),
              })
            }}
            disabled={saving || !name.trim()}
          >
            {saving ? 'Creating...' : 'Create Topic'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

const RULE_TYPE_COLORS: Record<string, string> = {
  scoring: 'text-amber-400 bg-amber-400/10',
  categorization: 'text-blue-400 bg-blue-400/10',
  routing: 'text-purple-400 bg-purple-400/10',
  scheduling: 'text-cyan-400 bg-cyan-400/10',
  auto_action: 'text-emerald-400 bg-emerald-400/10',
}

function RuleCard({ rule, onToggle, onDelete }: {
  rule: ResearchRule
  onToggle: () => void
  onDelete: () => void
}) {
  const effectiveness = rule.times_fired > 0
    ? Math.round((rule.times_useful / rule.times_fired) * 100)
    : null

  return (
    <Card className={`p-4 border ${rule.enabled ? 'bg-zinc-900/50 border-zinc-800' : 'bg-zinc-900/30 border-zinc-800/50 opacity-60'}`}>
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="font-semibold text-white truncate">{rule.name}</h3>
            <Badge className={`text-xs ${RULE_TYPE_COLORS[rule.rule_type] || ''}`}>
              {rule.rule_type.replace('_', ' ')}
            </Badge>
            <Badge variant="outline" className="text-xs text-zinc-500">
              p:{rule.priority}
            </Badge>
            {rule.created_by !== 'system' && (
              <Badge variant="outline" className="text-xs text-indigo-300 border-indigo-800">
                {rule.created_by}
              </Badge>
            )}
          </div>
          {rule.description && (
            <p className="text-sm text-zinc-400 mb-2">{rule.description}</p>
          )}
          <div className="flex items-center gap-4 text-xs text-zinc-500">
            <span>Fired: {rule.times_fired}</span>
            <span>Useful: {rule.times_useful}</span>
            {effectiveness !== null && (
              <span className={effectiveness >= 50 ? 'text-emerald-400' : effectiveness >= 25 ? 'text-amber-400' : 'text-red-400'}>
                {effectiveness}% effective
              </span>
            )}
            <span className={`font-mono ${scoreColor(rule.effectiveness_score)}`}>
              Score: {Math.round(rule.effectiveness_score)}
            </span>
          </div>
          {/* Condition summary */}
          <div className="flex flex-wrap gap-1 mt-2">
            {rule.conditions.url_domain?.map((d) => (
              <Badge key={d} variant="outline" className="text-xs text-zinc-400">domain: {d}</Badge>
            ))}
            {rule.conditions.title_contains?.slice(0, 3).map((k) => (
              <Badge key={k} variant="outline" className="text-xs text-zinc-400">title: {k}</Badge>
            ))}
            {rule.conditions.min_composite_score != null && (
              <Badge variant="outline" className="text-xs text-zinc-400">score &ge; {rule.conditions.min_composite_score}</Badge>
            )}
            {rule.conditions.snippet_contains?.slice(0, 2).map((k) => (
              <Badge key={k} variant="outline" className="text-xs text-zinc-400">snippet: {k}</Badge>
            ))}
          </div>
          {/* Action summary */}
          <div className="flex flex-wrap gap-1 mt-1">
            {rule.actions.boost_relevance != null && (
              <Badge className="text-xs bg-emerald-400/10 text-emerald-400">relevance {rule.actions.boost_relevance > 0 ? '+' : ''}{rule.actions.boost_relevance}</Badge>
            )}
            {rule.actions.boost_actionability != null && (
              <Badge className="text-xs bg-amber-400/10 text-amber-400">actionability {rule.actions.boost_actionability > 0 ? '+' : ''}{rule.actions.boost_actionability}</Badge>
            )}
            {rule.actions.set_category && (
              <Badge className="text-xs bg-blue-400/10 text-blue-400">cat: {rule.actions.set_category}</Badge>
            )}
            {rule.actions.add_tags?.map((t) => (
              <Badge key={t} className="text-xs bg-purple-400/10 text-purple-400">+{t}</Badge>
            ))}
            {rule.actions.auto_dismiss && (
              <Badge className="text-xs bg-red-400/10 text-red-400">auto-dismiss</Badge>
            )}
            {rule.actions.auto_create_task && (
              <Badge className="text-xs bg-purple-400/10 text-purple-400">auto-task</Badge>
            )}
            {rule.actions.notify_discord && (
              <Badge className="text-xs bg-indigo-400/10 text-indigo-400">notify</Badge>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 ml-3 shrink-0">
          <Button
            variant="ghost"
            size="sm"
            onClick={onToggle}
            className={rule.enabled ? 'text-emerald-400 hover:text-emerald-300' : 'text-zinc-500 hover:text-zinc-300'}
            title={rule.enabled ? 'Disable rule' : 'Enable rule'}
          >
            {rule.enabled ? <ToggleRight className="w-5 h-5" /> : <ToggleLeft className="w-5 h-5" />}
          </Button>
          {!rule.created_by || rule.created_by !== 'system' ? (
            <Button variant="ghost" size="sm" onClick={onDelete} className="text-zinc-400 hover:text-red-400">
              <Trash2 className="w-4 h-4" />
            </Button>
          ) : null}
        </div>
      </div>
    </Card>
  )
}
