import { useState, useEffect } from 'react'
import { getAuthHeaders } from '@/lib/auth'
import { Plus, Trash2, Pencil, Power, PowerOff, FlaskConical, Save, X, RefreshCw, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RuleCondition {
  field: string
  operator: string
  value: string | string[] | boolean
  case_sensitive: boolean
}

interface ConditionsBlock {
  match_mode: string
  conditions: RuleCondition[]
}

interface RuleAction {
  type: string
  params: Record<string, unknown>
}

interface EmailRule {
  id: string
  name: string
  description: string | null
  enabled: boolean
  priority: number
  stop_after_match: boolean
  conditions: ConditionsBlock
  actions: RuleAction[]
  match_count: number
  last_matched_at: string | null
  created_at: string
  updated_at: string | null
}

const CONDITION_FIELDS = [
  { value: 'sender', label: 'Sender' },
  { value: 'subject', label: 'Subject' },
  { value: 'body', label: 'Body' },
  { value: 'category', label: 'Category' },
  { value: 'has_attachments', label: 'Has Attachments' },
  { value: 'label', label: 'Label' },
]

const CONDITION_OPERATORS = [
  { value: 'contains', label: 'Contains' },
  { value: 'not_contains', label: 'Does not contain' },
  { value: 'exact', label: 'Equals' },
  { value: 'starts_with', label: 'Starts with' },
  { value: 'ends_with', label: 'Ends with' },
  { value: 'regex', label: 'Regex' },
]

const ACTION_TYPES = [
  { value: 'archive', label: 'Archive' },
  { value: 'star', label: 'Star' },
  { value: 'mark_read', label: 'Mark as Read' },
  { value: 'apply_label', label: 'Apply Label' },
  { value: 'notify', label: 'Notify' },
  { value: 'create_calendar_event', label: 'Create Calendar Event' },
  { value: 'create_task', label: 'Create Task' },
]

const ACTION_COLORS: Record<string, string> = {
  archive: 'bg-red-500/20 text-red-400',
  star: 'bg-yellow-500/20 text-yellow-400',
  mark_read: 'bg-green-500/20 text-green-400',
  apply_label: 'bg-blue-500/20 text-blue-400',
  notify: 'bg-purple-500/20 text-purple-400',
  create_calendar_event: 'bg-cyan-500/20 text-cyan-400',
  create_task: 'bg-orange-500/20 text-orange-400',
}

// ---------------------------------------------------------------------------
// Defaults for new rule
// ---------------------------------------------------------------------------

function emptyCondition(): RuleCondition {
  return { field: 'sender', operator: 'contains', value: '', case_sensitive: false }
}

function emptyAction(): RuleAction {
  return { type: 'archive', params: {} }
}

function defaultParams(actionType: string): Record<string, unknown> {
  switch (actionType) {
    case 'apply_label':
      return { label: '' }
    case 'notify':
      return { title: '' }
    case 'create_calendar_event':
      return { event_prefix: '', default_duration_minutes: 30 }
    case 'create_task':
      return { title_prefix: '[Email] ', priority: 'medium', category: 'chore' }
    default:
      return {}
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function EmailRulesPanel() {
  const [rules, setRules] = useState<EmailRule[]>([])
  const [loading, setLoading] = useState(false)
  const [editorOpen, setEditorOpen] = useState(false)
  const [editingRule, setEditingRule] = useState<EmailRule | null>(null)

  // Editor form state
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState(100)
  const [stopAfterMatch, setStopAfterMatch] = useState(false)
  const [matchMode, setMatchMode] = useState('all')
  const [conditions, setConditions] = useState<RuleCondition[]>([emptyCondition()])
  const [actions, setActions] = useState<RuleAction[]>([emptyAction()])
  const [saving, setSaving] = useState(false)

  // AI rule generation
  const [generatePrompt, setGeneratePrompt] = useState('')
  const [generating, setGenerating] = useState(false)
  const [generateError, setGenerateError] = useState('')

  useEffect(() => {
    loadRules()
  }, [])

  const loadRules = async () => {
    try {
      setLoading(true)
      const res = await fetch('/api/email/rules', { headers: getAuthHeaders() })
      if (res.ok) {
        setRules(await res.json())
      }
    } catch (err) {
      console.error('Failed to load rules:', err)
    } finally {
      setLoading(false)
    }
  }

  const openNewRule = () => {
    setEditingRule(null)
    setName('')
    setDescription('')
    setPriority(100)
    setStopAfterMatch(false)
    setMatchMode('all')
    setConditions([emptyCondition()])
    setActions([emptyAction()])
    setEditorOpen(true)
  }

  const generateRule = async () => {
    if (!generatePrompt.trim()) return
    setGenerating(true)
    setGenerateError('')
    try {
      const res = await fetch('/api/email/rules/generate', {
        method: 'POST',
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: generatePrompt }),
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Generation failed' }))
        setGenerateError(err.detail || 'Generation failed')
        return
      }
      const rule = await res.json()
      setEditingRule(null)
      setName(rule.name || '')
      setDescription(rule.description || '')
      setPriority(rule.priority ?? 100)
      setStopAfterMatch(rule.stop_after_match ?? false)
      setMatchMode(rule.conditions?.match_mode || 'all')
      setConditions(rule.conditions?.conditions || [emptyCondition()])
      setActions(rule.actions || [emptyAction()])
      setEditorOpen(true)
      setGeneratePrompt('')
    } catch {
      setGenerateError('Failed to connect to server')
    } finally {
      setGenerating(false)
    }
  }

  const openEditRule = (rule: EmailRule) => {
    setEditingRule(rule)
    setName(rule.name)
    setDescription(rule.description || '')
    setPriority(rule.priority)
    setStopAfterMatch(rule.stop_after_match)
    setMatchMode(rule.conditions.match_mode)
    setConditions(rule.conditions.conditions.map(c => ({ ...c })))
    setActions(rule.actions.map(a => ({ ...a, params: { ...a.params } })))
    setEditorOpen(true)
  }

  const saveRule = async () => {
    const body = {
      name,
      description: description || null,
      priority,
      stop_after_match: stopAfterMatch,
      conditions: { match_mode: matchMode, conditions },
      actions,
    }

    setSaving(true)
    try {
      const url = editingRule ? `/api/email/rules/${editingRule.id}` : '/api/email/rules'
      const method = editingRule ? 'PATCH' : 'POST'
      const res = await fetch(url, {
        method,
        headers: { ...getAuthHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (res.ok) {
        setEditorOpen(false)
        await loadRules()
      } else {
        const err = await res.json()
        alert(`Failed to save: ${err.detail || JSON.stringify(err)}`)
      }
    } catch (err) {
      console.error('Save failed:', err)
    } finally {
      setSaving(false)
    }
  }

  const deleteRule = async (ruleId: string) => {
    if (!confirm('Delete this rule?')) return
    try {
      await fetch(`/api/email/rules/${ruleId}`, {
        method: 'DELETE',
        headers: getAuthHeaders(),
      })
      await loadRules()
    } catch (err) {
      console.error('Delete failed:', err)
    }
  }

  const toggleRule = async (ruleId: string, enabled: boolean) => {
    try {
      await fetch(`/api/email/rules/${ruleId}/toggle?enabled=${enabled}`, {
        method: 'POST',
        headers: getAuthHeaders(),
      })
      await loadRules()
    } catch (err) {
      console.error('Toggle failed:', err)
    }
  }

  // -- Condition helpers --
  const addCondition = () => setConditions([...conditions, emptyCondition()])
  const removeCondition = (i: number) => setConditions(conditions.filter((_, idx) => idx !== i))
  const updateCondition = (i: number, patch: Partial<RuleCondition>) => {
    setConditions(conditions.map((c, idx) => (idx === i ? { ...c, ...patch } : c)))
  }

  // -- Action helpers --
  const addAction = () => setActions([...actions, emptyAction()])
  const removeAction = (i: number) => setActions(actions.filter((_, idx) => idx !== i))
  const updateActionType = (i: number, type: string) => {
    setActions(actions.map((a, idx) => (idx === i ? { type, params: defaultParams(type) } : a)))
  }
  const updateActionParam = (i: number, key: string, val: unknown) => {
    setActions(actions.map((a, idx) => (idx === i ? { ...a, params: { ...a.params, [key]: val } } : a)))
  }

  // -- Summaries --
  const conditionSummary = (c: RuleCondition) => {
    const val = Array.isArray(c.value) ? c.value.join(', ') : String(c.value)
    return `${c.field} ${c.operator} "${val}"`
  }

  const actionLabel = (type: string) =>
    ACTION_TYPES.find(a => a.value === type)?.label || type

  // -------------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------------

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-400">
          Rules are evaluated in priority order on every new email. Lower priority number = runs first.
        </p>
        <Button onClick={openNewRule} className="gap-2">
          <Plus className="w-4 h-4" /> New Rule
        </Button>
      </div>

      {/* AI Rule Generator */}
      <div className="flex gap-2">
        <Input
          value={generatePrompt}
          onChange={e => { setGeneratePrompt(e.target.value); setGenerateError('') }}
          onKeyDown={e => e.key === 'Enter' && !generating && generateRule()}
          placeholder='Describe a rule, e.g. "star all emails from my bank"'
          className="flex-1 bg-zinc-900 border-zinc-700"
          disabled={generating}
        />
        <Button
          onClick={generateRule}
          disabled={generating || !generatePrompt.trim()}
          variant="outline"
          className="gap-2 whitespace-nowrap"
        >
          {generating ? (
            <RefreshCw className="w-4 h-4 animate-spin" />
          ) : (
            <Sparkles className="w-4 h-4" />
          )}
          {generating ? 'Generating...' : 'Generate with AI'}
        </Button>
      </div>
      {generateError && (
        <p className="text-sm text-red-400">{generateError}</p>
      )}

      {loading ? (
        <Card className="p-8 bg-zinc-900/50 border-zinc-800">
          <p className="text-center text-zinc-400">Loading rules...</p>
        </Card>
      ) : rules.length === 0 ? (
        <Card className="p-8 bg-zinc-900/50 border-zinc-800">
          <div className="text-center">
            <FlaskConical className="w-12 h-12 mx-auto mb-4 text-zinc-600" />
            <p className="text-zinc-400 mb-2">No email rules yet.</p>
            <p className="text-zinc-500 text-sm">
              Create rules to automatically archive newsletters, put bills on your calendar, create tasks from important emails, and more.
            </p>
          </div>
        </Card>
      ) : (
        rules.map(rule => (
          <Card
            key={rule.id}
            className={`p-4 border-zinc-800 transition-colors ${
              rule.enabled ? 'bg-zinc-900/50' : 'bg-zinc-900/20 opacity-60'
            }`}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <h3 className="font-semibold text-white">{rule.name}</h3>
                  <Badge variant="outline" className="text-xs">
                    P{rule.priority}
                  </Badge>
                  {!rule.enabled && (
                    <Badge variant="outline" className="text-xs text-zinc-500">
                      Disabled
                    </Badge>
                  )}
                  {rule.stop_after_match && (
                    <Badge variant="outline" className="text-xs text-amber-400">
                      Stop
                    </Badge>
                  )}
                </div>

                {rule.description && (
                  <p className="text-sm text-zinc-500 mb-2">{rule.description}</p>
                )}

                {/* Conditions */}
                <div className="flex flex-wrap gap-1 mb-2">
                  <span className="text-xs text-zinc-500">
                    {rule.conditions.match_mode === 'all' ? 'All of:' : 'Any of:'}
                  </span>
                  {rule.conditions.conditions.map((c, i) => (
                    <Badge key={i} variant="outline" className="text-xs bg-zinc-800/50">
                      {conditionSummary(c)}
                    </Badge>
                  ))}
                </div>

                {/* Actions */}
                <div className="flex flex-wrap gap-1 mb-1">
                  <span className="text-xs text-zinc-500">Then:</span>
                  {rule.actions.map((a, i) => (
                    <Badge
                      key={i}
                      className={`text-xs ${ACTION_COLORS[a.type] || 'bg-zinc-700 text-zinc-300'}`}
                    >
                      {actionLabel(a.type)}
                    </Badge>
                  ))}
                </div>

                <p className="text-xs text-zinc-600 mt-1">
                  Matched {rule.match_count} time{rule.match_count !== 1 ? 's' : ''}
                  {rule.last_matched_at && (
                    <> &middot; Last: {new Date(rule.last_matched_at).toLocaleString()}</>
                  )}
                </p>
              </div>

              <div className="flex items-center gap-1">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => toggleRule(rule.id, !rule.enabled)}
                  title={rule.enabled ? 'Disable' : 'Enable'}
                  className="text-zinc-400 hover:text-white"
                >
                  {rule.enabled ? <Power className="w-4 h-4" /> : <PowerOff className="w-4 h-4" />}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => openEditRule(rule)}
                  className="text-zinc-400 hover:text-white"
                >
                  <Pencil className="w-4 h-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => deleteRule(rule.id)}
                  className="text-zinc-400 hover:text-red-400"
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              </div>
            </div>
          </Card>
        ))
      )}

      {/* ----------------------------------------------------------------- */}
      {/* Rule Editor Dialog                                                 */}
      {/* ----------------------------------------------------------------- */}
      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto bg-zinc-950 border-zinc-800">
          <DialogHeader>
            <DialogTitle>{editingRule ? 'Edit Rule' : 'New Email Rule'}</DialogTitle>
          </DialogHeader>

          <div className="space-y-6 mt-4">
            {/* Name & Priority */}
            <div className="grid grid-cols-3 gap-4">
              <div className="col-span-2">
                <Label>Name</Label>
                <Input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="e.g. Bills to Calendar"
                  className="bg-zinc-900 border-zinc-700"
                />
              </div>
              <div>
                <Label>Priority</Label>
                <Input
                  type="number"
                  value={priority}
                  onChange={e => setPriority(Number(e.target.value))}
                  min={1}
                  max={10000}
                  className="bg-zinc-900 border-zinc-700"
                />
              </div>
            </div>

            <div>
              <Label>Description (optional)</Label>
              <Input
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder="What does this rule do?"
                className="bg-zinc-900 border-zinc-700"
              />
            </div>

            <div className="flex items-center gap-4">
              <label className="flex items-center gap-2 text-sm text-zinc-300 cursor-pointer">
                <input
                  type="checkbox"
                  checked={stopAfterMatch}
                  onChange={e => setStopAfterMatch(e.target.checked)}
                  className="rounded border-zinc-600"
                />
                Stop processing further rules after this one matches
              </label>
            </div>

            {/* ---- Conditions ---- */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <Label className="text-base">Conditions</Label>
                <Select value={matchMode} onValueChange={setMatchMode}>
                  <SelectTrigger className="w-32 bg-zinc-900 border-zinc-700">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Match ALL</SelectItem>
                    <SelectItem value="any">Match ANY</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-2">
                {conditions.map((c, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <Select
                      value={c.field}
                      onValueChange={val => updateCondition(i, { field: val })}
                    >
                      <SelectTrigger className="w-36 bg-zinc-900 border-zinc-700">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {CONDITION_FIELDS.map(f => (
                          <SelectItem key={f.value} value={f.value}>
                            {f.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>

                    {c.field !== 'has_attachments' ? (
                      <>
                        <Select
                          value={c.operator}
                          onValueChange={val => updateCondition(i, { operator: val })}
                        >
                          <SelectTrigger className="w-40 bg-zinc-900 border-zinc-700">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            {CONDITION_OPERATORS.map(o => (
                              <SelectItem key={o.value} value={o.value}>
                                {o.label}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Input
                          value={String(c.value)}
                          onChange={e => updateCondition(i, { value: e.target.value })}
                          placeholder="Value (comma-separate for OR)"
                          className="flex-1 bg-zinc-900 border-zinc-700"
                        />
                      </>
                    ) : (
                      <Select
                        value={String(c.value)}
                        onValueChange={val => updateCondition(i, { value: val === 'true', operator: 'exact' })}
                      >
                        <SelectTrigger className="w-32 bg-zinc-900 border-zinc-700">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="true">Yes</SelectItem>
                          <SelectItem value="false">No</SelectItem>
                        </SelectContent>
                      </Select>
                    )}

                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => removeCondition(i)}
                      disabled={conditions.length <= 1}
                      className="text-zinc-400 hover:text-red-400"
                    >
                      <X className="w-4 h-4" />
                    </Button>
                  </div>
                ))}
              </div>
              <Button variant="outline" size="sm" onClick={addCondition} className="mt-2 text-xs">
                + Add Condition
              </Button>
            </div>

            {/* ---- Actions ---- */}
            <div>
              <Label className="text-base mb-2 block">Actions</Label>
              <div className="space-y-3">
                {actions.map((a, i) => (
                  <div key={i} className="border border-zinc-800 rounded-lg p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <Select
                        value={a.type}
                        onValueChange={val => updateActionType(i, val)}
                      >
                        <SelectTrigger className="w-56 bg-zinc-900 border-zinc-700">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {ACTION_TYPES.map(at => (
                            <SelectItem key={at.value} value={at.value}>
                              {at.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => removeAction(i)}
                        disabled={actions.length <= 1}
                        className="text-zinc-400 hover:text-red-400 ml-auto"
                      >
                        <X className="w-4 h-4" />
                      </Button>
                    </div>

                    {/* Action-specific params */}
                    {a.type === 'apply_label' && (
                      <Input
                        value={String(a.params.label || '')}
                        onChange={e => updateActionParam(i, 'label', e.target.value)}
                        placeholder="Gmail label name"
                        className="bg-zinc-900 border-zinc-700"
                      />
                    )}
                    {a.type === 'notify' && (
                      <Input
                        value={String(a.params.title || '')}
                        onChange={e => updateActionParam(i, 'title', e.target.value)}
                        placeholder="Notification title (optional)"
                        className="bg-zinc-900 border-zinc-700"
                      />
                    )}
                    {a.type === 'create_calendar_event' && (
                      <div className="grid grid-cols-2 gap-2">
                        <div>
                          <Label className="text-xs text-zinc-500">Event prefix</Label>
                          <Input
                            value={String(a.params.event_prefix || '')}
                            onChange={e => updateActionParam(i, 'event_prefix', e.target.value)}
                            placeholder="e.g. [Bill Due] "
                            className="bg-zinc-900 border-zinc-700"
                          />
                        </div>
                        <div>
                          <Label className="text-xs text-zinc-500">Default duration (min)</Label>
                          <Input
                            type="number"
                            value={String(a.params.default_duration_minutes || 30)}
                            onChange={e => updateActionParam(i, 'default_duration_minutes', Number(e.target.value))}
                            className="bg-zinc-900 border-zinc-700"
                          />
                        </div>
                      </div>
                    )}
                    {a.type === 'create_task' && (
                      <div className="grid grid-cols-3 gap-2">
                        <div>
                          <Label className="text-xs text-zinc-500">Title prefix</Label>
                          <Input
                            value={String(a.params.title_prefix || '[Email] ')}
                            onChange={e => updateActionParam(i, 'title_prefix', e.target.value)}
                            className="bg-zinc-900 border-zinc-700"
                          />
                        </div>
                        <div>
                          <Label className="text-xs text-zinc-500">Priority</Label>
                          <Select
                            value={String(a.params.priority || 'medium')}
                            onValueChange={val => updateActionParam(i, 'priority', val)}
                          >
                            <SelectTrigger className="bg-zinc-900 border-zinc-700">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="low">Low</SelectItem>
                              <SelectItem value="medium">Medium</SelectItem>
                              <SelectItem value="high">High</SelectItem>
                              <SelectItem value="critical">Critical</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                        <div>
                          <Label className="text-xs text-zinc-500">Category</Label>
                          <Select
                            value={String(a.params.category || 'chore')}
                            onValueChange={val => updateActionParam(i, 'category', val)}
                          >
                            <SelectTrigger className="bg-zinc-900 border-zinc-700">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="feature">Feature</SelectItem>
                              <SelectItem value="bug">Bug</SelectItem>
                              <SelectItem value="chore">Chore</SelectItem>
                              <SelectItem value="research">Research</SelectItem>
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
              <Button variant="outline" size="sm" onClick={addAction} className="mt-2 text-xs">
                + Add Action
              </Button>
            </div>

            {/* ---- Save / Cancel ---- */}
            <div className="flex justify-end gap-2 pt-4 border-t border-zinc-800">
              <Button variant="outline" onClick={() => setEditorOpen(false)}>
                Cancel
              </Button>
              <Button onClick={saveRule} disabled={saving || !name.trim() || conditions.length === 0}>
                <Save className="w-4 h-4 mr-2" />
                {saving ? 'Saving...' : editingRule ? 'Update Rule' : 'Create Rule'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
