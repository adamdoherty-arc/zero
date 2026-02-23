import { useState } from 'react'
import {
  Brain, Plus, Search, Trash2, Edit3, Tag, BookOpen,
  User, Lightbulb, Bookmark, Code, FileText, Clock, FolderTree
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
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import {
  useNotes, useCreateNote, useUpdateNote, useDeleteNote,
  useUserProfile, useKnowledgeStats, useRecall, useKnowledgeCategories,
} from '@/hooks/useSprintApi'
import type { Note, NoteType, NoteCreate, NoteUpdate, KnowledgeCategory } from '@/types'

const NOTE_TYPE_ICONS: Record<NoteType, React.ReactNode> = {
  note: <FileText className="w-4 h-4" />,
  idea: <Lightbulb className="w-4 h-4" />,
  fact: <Brain className="w-4 h-4" />,
  preference: <User className="w-4 h-4" />,
  memory: <Clock className="w-4 h-4" />,
  bookmark: <Bookmark className="w-4 h-4" />,
  snippet: <Code className="w-4 h-4" />,
}

const NOTE_TYPE_COLORS: Record<NoteType, string> = {
  note: 'text-blue-400 bg-blue-400/10',
  idea: 'text-amber-400 bg-amber-400/10',
  fact: 'text-emerald-400 bg-emerald-400/10',
  preference: 'text-purple-400 bg-purple-400/10',
  memory: 'text-pink-400 bg-pink-400/10',
  bookmark: 'text-cyan-400 bg-cyan-400/10',
  snippet: 'text-orange-400 bg-orange-400/10',
}

export function KnowledgePage() {
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [categoryFilter, setCategoryFilter] = useState<string>('all')
  const [showCreateDialog, setShowCreateDialog] = useState(false)
  const [editingNote, setEditingNote] = useState<Note | null>(null)
  const [recallQuery, setRecallQuery] = useState('')
  const [activeRecallQuery, setActiveRecallQuery] = useState('')

  const filters = {
    search: search || undefined,
    type: typeFilter !== 'all' ? typeFilter as NoteType : undefined,
    category_id: categoryFilter !== 'all' ? categoryFilter : undefined,
    limit: 50,
  }
  const { data: notes, isLoading: notesLoading } = useNotes(filters)
  const { data: profile } = useUserProfile()
  const { data: stats } = useKnowledgeStats()
  const { data: categories } = useKnowledgeCategories()
  const { data: recallResult, isFetching: recalling } = useRecall(
    activeRecallQuery,
    { include_notes: true, include_facts: true, include_tasks: true, limit: 10 }
  )

  const createNote = useCreateNote()
  const updateNote = useUpdateNote()
  const deleteNote = useDeleteNote()

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2">Knowledge Base</h1>
          <p className="text-zinc-400">Your second brain - notes, ideas, facts, and semantic recall</p>
        </div>
        <Button onClick={() => setShowCreateDialog(true)} className="gap-2">
          <Plus className="w-4 h-4" />
          New Note
        </Button>
      </div>

      {/* Stats Bar */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
          <StatCard label="Notes" value={stats.total_notes} icon={<FileText className="w-4 h-4 text-blue-400" />} />
          <StatCard label="Facts" value={stats.total_facts} icon={<Brain className="w-4 h-4 text-emerald-400" />} />
          <StatCard label="Contacts" value={stats.total_contacts} icon={<User className="w-4 h-4 text-purple-400" />} />
          <StatCard label="Tags" value={stats.total_tags} icon={<Tag className="w-4 h-4 text-amber-400" />} />
          <StatCard label="Skills" value={stats.total_skills} icon={<Code className="w-4 h-4 text-orange-400" />} />
          <StatCard label="Interests" value={stats.total_interests} icon={<Lightbulb className="w-4 h-4 text-cyan-400" />} />
        </div>
      )}

      <Tabs defaultValue="notes" className="space-y-4">
        <TabsList className="bg-zinc-900 border-zinc-800">
          <TabsTrigger value="notes">Notes</TabsTrigger>
          <TabsTrigger value="recall">Recall</TabsTrigger>
          <TabsTrigger value="profile">Profile</TabsTrigger>
        </TabsList>

        {/* Notes Tab */}
        <TabsContent value="notes" className="space-y-4">
          <div className="flex gap-3">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-500" />
              <Input
                placeholder="Search notes..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-10 bg-zinc-900 border-zinc-800 text-white"
              />
            </div>
            <Select value={typeFilter} onValueChange={setTypeFilter}>
              <SelectTrigger className="w-40 bg-zinc-900 border-zinc-800 text-white">
                <SelectValue placeholder="All types" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All types</SelectItem>
                <SelectItem value="note">Notes</SelectItem>
                <SelectItem value="idea">Ideas</SelectItem>
                <SelectItem value="fact">Facts</SelectItem>
                <SelectItem value="bookmark">Bookmarks</SelectItem>
                <SelectItem value="snippet">Snippets</SelectItem>
                <SelectItem value="memory">Memories</SelectItem>
              </SelectContent>
            </Select>
            <Select value={categoryFilter} onValueChange={setCategoryFilter}>
              <SelectTrigger className="w-48 bg-zinc-900 border-zinc-800 text-white">
                <div className="flex items-center gap-2">
                  <FolderTree className="w-3 h-3 text-zinc-500" />
                  <SelectValue placeholder="All categories" />
                </div>
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All categories</SelectItem>
                {categories?.map((cat: KnowledgeCategory) => (
                  <SelectItem key={cat.id} value={cat.id}>
                    <span>{cat.icon || ''} {cat.name}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {notesLoading ? (
            <div className="space-y-3">
              {[...Array(5)].map((_, i) => (
                <Card key={i} className="p-4 bg-zinc-900/50 border-zinc-800">
                  <Skeleton className="h-5 w-48 mb-2" />
                  <Skeleton className="h-4 w-full mb-1" />
                  <Skeleton className="h-4 w-3/4" />
                </Card>
              ))}
            </div>
          ) : !notes || notes.length === 0 ? (
            <Card className="p-12 bg-zinc-900/50 border-zinc-800">
              <div className="text-center">
                <BookOpen className="w-12 h-12 mx-auto mb-4 text-zinc-600" />
                <p className="text-zinc-400 mb-4">No notes yet. Start building your knowledge base.</p>
                <Button onClick={() => setShowCreateDialog(true)} variant="outline" className="gap-2">
                  <Plus className="w-4 h-4" />
                  Create your first note
                </Button>
              </div>
            </Card>
          ) : (
            <div className="space-y-2">
              {notes.map((note) => (
                <NoteCard
                  key={note.id}
                  note={note}
                  categories={categories}
                  onEdit={() => setEditingNote(note)}
                  onDelete={() => deleteNote.mutate(note.id)}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Recall Tab */}
        <TabsContent value="recall" className="space-y-4">
          <Card className="p-6 bg-zinc-900/50 border-zinc-800">
            <h3 className="text-lg font-semibold text-white mb-2">Semantic Recall</h3>
            <p className="text-zinc-400 text-sm mb-4">
              Search your knowledge base by meaning. Ask a question or describe what you're looking for.
            </p>
            <div className="flex gap-3">
              <Input
                placeholder="e.g. What do I know about Docker networking?"
                value={recallQuery}
                onChange={(e) => setRecallQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && recallQuery.trim()) {
                    setActiveRecallQuery(recallQuery.trim())
                  }
                }}
                className="bg-zinc-800 border-zinc-700 text-white"
              />
              <Button
                onClick={() => recallQuery.trim() && setActiveRecallQuery(recallQuery.trim())}
                disabled={recalling || !recallQuery.trim()}
                className="gap-2"
              >
                <Search className="w-4 h-4" />
                Recall
              </Button>
            </div>
          </Card>

          {recalling && (
            <div className="space-y-3">
              {[...Array(3)].map((_, i) => (
                <Card key={i} className="p-4 bg-zinc-900/50 border-zinc-800">
                  <Skeleton className="h-5 w-32 mb-2" />
                  <Skeleton className="h-4 w-full" />
                </Card>
              ))}
            </div>
          )}

          {recallResult && !recalling && (
            <div className="space-y-4">
              {recallResult.summary && (
                <Card className="p-4 bg-indigo-900/20 border-indigo-800/50">
                  <h4 className="text-sm font-medium text-indigo-300 mb-1">Summary</h4>
                  <p className="text-zinc-300 text-sm">{recallResult.summary}</p>
                </Card>
              )}

              {recallResult.notes.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-zinc-400 mb-2">Related Notes ({recallResult.notes.length})</h4>
                  <div className="space-y-2">
                    {recallResult.notes.map((note) => (
                      <NoteCard key={note.id} note={note} categories={categories} onEdit={() => setEditingNote(note)} />
                    ))}
                  </div>
                </div>
              )}

              {recallResult.facts.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-zinc-400 mb-2">Related Facts ({recallResult.facts.length})</h4>
                  <div className="space-y-2">
                    {recallResult.facts.map((fact) => (
                      <Card key={fact.id} className="p-3 bg-zinc-900/50 border-zinc-800">
                        <div className="flex items-center gap-2">
                          <Brain className="w-4 h-4 text-emerald-400" />
                          <span className="text-zinc-200 text-sm">{fact.fact}</span>
                          <Badge variant="outline" className="text-xs ml-auto">{fact.category}</Badge>
                        </div>
                      </Card>
                    ))}
                  </div>
                </div>
              )}

              {recallResult.related_tasks.length > 0 && (
                <div>
                  <h4 className="text-sm font-medium text-zinc-400 mb-2">Related Tasks ({recallResult.related_tasks.length})</h4>
                  <div className="space-y-2">
                    {recallResult.related_tasks.map((task) => (
                      <Card key={task.id} className="p-3 bg-zinc-900/50 border-zinc-800">
                        <div className="flex items-center gap-2">
                          <div className={`w-2 h-2 rounded-full ${task.status === 'done' ? 'bg-green-400' : task.status === 'in_progress' ? 'bg-blue-400' : 'bg-zinc-500'}`} />
                          <span className="text-zinc-200 text-sm">{task.title}</span>
                          <Badge variant="outline" className="text-xs ml-auto">{task.status}</Badge>
                        </div>
                      </Card>
                    ))}
                  </div>
                </div>
              )}

              {recallResult.notes.length === 0 && recallResult.facts.length === 0 && recallResult.related_tasks.length === 0 && (
                <Card className="p-8 bg-zinc-900/50 border-zinc-800">
                  <p className="text-center text-zinc-400">No results found. Try a different query.</p>
                </Card>
              )}
            </div>
          )}
        </TabsContent>

        {/* Profile Tab */}
        <TabsContent value="profile" className="space-y-4">
          {profile ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <Card className="p-6 bg-zinc-900/50 border-zinc-800">
                <h3 className="text-lg font-semibold text-white mb-4">User Profile</h3>
                <div className="space-y-3">
                  <ProfileField label="Name" value={profile.name} />
                  <ProfileField label="Timezone" value={profile.timezone} />
                  <ProfileField label="Communication Style" value={profile.communication_style || 'Not set'} />
                  {profile.work_hours && (
                    <ProfileField label="Work Hours" value={`${profile.work_hours.start} - ${profile.work_hours.end}`} />
                  )}
                </div>
              </Card>

              <Card className="p-6 bg-zinc-900/50 border-zinc-800">
                <h3 className="text-lg font-semibold text-white mb-4">Goals</h3>
                {profile.goals.length > 0 ? (
                  <ul className="space-y-2">
                    {profile.goals.map((goal, i) => (
                      <li key={i} className="flex items-start gap-2 text-zinc-300 text-sm">
                        <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 shrink-0" />
                        {goal}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-zinc-500 text-sm">No goals set yet.</p>
                )}
              </Card>

              <Card className="p-6 bg-zinc-900/50 border-zinc-800">
                <h3 className="text-lg font-semibold text-white mb-4">Skills & Interests</h3>
                <div className="mb-4">
                  <h4 className="text-sm text-zinc-400 mb-2">Skills</h4>
                  <div className="flex flex-wrap gap-2">
                    {profile.skills.length > 0 ? profile.skills.map((skill) => (
                      <Badge key={skill} variant="outline" className="text-orange-300 border-orange-800">{skill}</Badge>
                    )) : <span className="text-zinc-500 text-sm">None recorded</span>}
                  </div>
                </div>
                <div>
                  <h4 className="text-sm text-zinc-400 mb-2">Interests</h4>
                  <div className="flex flex-wrap gap-2">
                    {profile.interests.length > 0 ? profile.interests.map((interest) => (
                      <Badge key={interest} variant="outline" className="text-cyan-300 border-cyan-800">{interest}</Badge>
                    )) : <span className="text-zinc-500 text-sm">None recorded</span>}
                  </div>
                </div>
              </Card>

              <Card className="p-6 bg-zinc-900/50 border-zinc-800">
                <h3 className="text-lg font-semibold text-white mb-4">Learned Facts ({profile.facts.length})</h3>
                {profile.facts.length > 0 ? (
                  <div className="space-y-2 max-h-64 overflow-y-auto">
                    {profile.facts.map((fact) => (
                      <div key={fact.id} className="flex items-start gap-2 p-2 rounded bg-zinc-800/50">
                        <Brain className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
                        <div className="flex-1 min-w-0">
                          <p className="text-zinc-300 text-sm">{fact.fact}</p>
                          <div className="flex items-center gap-2 mt-1">
                            <Badge variant="outline" className="text-xs">{fact.category}</Badge>
                            <span className="text-xs text-zinc-500">{Math.round(fact.confidence * 100)}% confidence</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-zinc-500 text-sm">No facts learned yet. Zero learns about you through conversations.</p>
                )}
              </Card>

              {profile.contacts.length > 0 && (
                <Card className="p-6 bg-zinc-900/50 border-zinc-800 lg:col-span-2">
                  <h3 className="text-lg font-semibold text-white mb-4">Contacts ({profile.contacts.length})</h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                    {profile.contacts.map((contact, i) => (
                      <div key={i} className="p-3 rounded bg-zinc-800/50">
                        <p className="text-white font-medium text-sm">{contact.name}</p>
                        {contact.relation && <p className="text-zinc-400 text-xs">{contact.relation}</p>}
                        {contact.email && <p className="text-zinc-500 text-xs">{contact.email}</p>}
                      </div>
                    ))}
                  </div>
                </Card>
              )}
            </div>
          ) : (
            <Card className="p-12 bg-zinc-900/50 border-zinc-800">
              <div className="text-center">
                <User className="w-12 h-12 mx-auto mb-4 text-zinc-600" />
                <p className="text-zinc-400">Profile data will appear as Zero learns about you.</p>
              </div>
            </Card>
          )}
        </TabsContent>
      </Tabs>

      {/* Create/Edit Note Dialog */}
      <NoteDialog
        open={showCreateDialog}
        onOpenChange={setShowCreateDialog}
        categories={categories}
        onSave={(data) => {
          createNote.mutate(data, { onSuccess: () => setShowCreateDialog(false) })
        }}
        saving={createNote.isPending}
      />

      {editingNote && (
        <NoteDialog
          open={!!editingNote}
          onOpenChange={(open) => !open && setEditingNote(null)}
          note={editingNote}
          categories={categories}
          onSave={(data) => {
            updateNote.mutate(
              { id: editingNote.id, data: data as NoteUpdate },
              { onSuccess: () => setEditingNote(null) }
            )
          }}
          saving={updateNote.isPending}
        />
      )}
    </div>
  )
}

function StatCard({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return (
    <Card className="p-3 bg-zinc-900/50 border-zinc-800">
      <div className="flex items-center gap-2">
        {icon}
        <div>
          <p className="text-xl font-bold text-white">{value}</p>
          <p className="text-xs text-zinc-500">{label}</p>
        </div>
      </div>
    </Card>
  )
}

function ProfileField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="text-zinc-200">{value}</p>
    </div>
  )
}

function NoteCard({ note, onEdit, onDelete, categories }: { note: Note; onEdit?: () => void; onDelete?: () => void; categories?: KnowledgeCategory[] }) {
  const category = categories?.find(c => c.id === note.category_id)
  const typeColor = NOTE_TYPE_COLORS[note.type] || 'text-zinc-400 bg-zinc-400/10'
  const typeIcon = NOTE_TYPE_ICONS[note.type] || <FileText className="w-4 h-4" />

  return (
    <Card className="p-4 bg-zinc-900/50 border-zinc-800 hover:border-zinc-700 transition-colors">
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium ${typeColor}`}>
              {typeIcon}
              {note.type}
            </span>
            {note.title && (
              <h3 className="font-semibold text-white truncate">{note.title}</h3>
            )}
          </div>
          <p className="text-sm text-zinc-300 line-clamp-3 whitespace-pre-wrap">{note.content}</p>
          <div className="flex items-center gap-2 mt-2">
            {category && (
              <Badge variant="outline" className="text-xs text-indigo-300 border-indigo-800">
                {category.icon || ''} {category.name}
              </Badge>
            )}
            {note.tags.map((tag) => (
              <Badge key={tag} variant="outline" className="text-xs">{tag}</Badge>
            ))}
            <span className="text-xs text-zinc-600 ml-auto">
              {new Date(note.created_at).toLocaleDateString()}
            </span>
            {note.source !== 'manual' && (
              <Badge variant="outline" className="text-xs text-zinc-500">{note.source}</Badge>
            )}
          </div>
        </div>
        {(onEdit || onDelete) && (
          <div className="flex items-center gap-1 ml-3 shrink-0">
            {onEdit && (
              <Button variant="ghost" size="sm" onClick={onEdit} className="text-zinc-400 hover:text-white">
                <Edit3 className="w-4 h-4" />
              </Button>
            )}
            {onDelete && (
              <Button variant="ghost" size="sm" onClick={onDelete} className="text-zinc-400 hover:text-red-400">
                <Trash2 className="w-4 h-4" />
              </Button>
            )}
          </div>
        )}
      </div>
    </Card>
  )
}

function NoteDialog({
  open, onOpenChange, note, onSave, saving, categories,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  note?: Note
  onSave: (data: NoteCreate) => void
  saving: boolean
  categories?: KnowledgeCategory[]
}) {
  const [title, setTitle] = useState(note?.title || '')
  const [content, setContent] = useState(note?.content || '')
  const [type, setType] = useState<NoteType>(note?.type || 'note')
  const [tags, setTags] = useState(note?.tags.join(', ') || '')
  const [categoryId, setCategoryId] = useState(note?.category_id || 'none')

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="bg-zinc-900 border-zinc-800 text-white max-w-lg">
        <DialogHeader>
          <DialogTitle>{note ? 'Edit Note' : 'New Note'}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-zinc-400">Type</Label>
              <Select value={type} onValueChange={(v) => setType(v as NoteType)}>
                <SelectTrigger className="bg-zinc-800 border-zinc-700">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="note">Note</SelectItem>
                  <SelectItem value="idea">Idea</SelectItem>
                  <SelectItem value="fact">Fact</SelectItem>
                  <SelectItem value="bookmark">Bookmark</SelectItem>
                  <SelectItem value="snippet">Snippet</SelectItem>
                  <SelectItem value="memory">Memory</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-zinc-400">Category</Label>
              <Select value={categoryId} onValueChange={setCategoryId}>
                <SelectTrigger className="bg-zinc-800 border-zinc-700">
                  <SelectValue placeholder="No category" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="none">No category</SelectItem>
                  {categories?.map((cat) => (
                    <SelectItem key={cat.id} value={cat.id}>
                      {cat.icon || ''} {cat.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <div>
            <Label className="text-zinc-400">Tags (comma separated)</Label>
            <Input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="e.g. docker, devops"
              className="bg-zinc-800 border-zinc-700"
            />
          </div>
          <div>
            <Label className="text-zinc-400">Title (optional)</Label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Note title..."
              className="bg-zinc-800 border-zinc-700"
            />
          </div>
          <div>
            <Label className="text-zinc-400">Content</Label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Write your note..."
              rows={6}
              className="w-full px-3 py-2 rounded-md bg-zinc-800 border border-zinc-700 text-white placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-y"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            onClick={() => {
              if (!content.trim()) return
              onSave({
                title: title.trim() || undefined,
                content: content.trim(),
                type,
                tags: tags.split(',').map(t => t.trim()).filter(Boolean),
                source: 'manual',
                category_id: categoryId !== 'none' ? categoryId : undefined,
              })
            }}
            disabled={saving || !content.trim()}
          >
            {saving ? 'Saving...' : note ? 'Update' : 'Create'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
