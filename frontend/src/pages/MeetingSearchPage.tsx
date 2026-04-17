import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Search, Clock, User, ArrowRight } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { useMeetingSearch } from '@/hooks/useMeetings'

const SEARCH_TYPES = [
  { label: 'All', value: undefined },
  { label: 'Semantic', value: 'semantic' },
  { label: 'Fulltext', value: 'fulltext' },
]

export function MeetingSearchPage() {
  const [query, setQuery] = useState('')
  const [activeQuery, setActiveQuery] = useState('')
  const [searchType, setSearchType] = useState<string | undefined>()

  const { data, isPending } = useMeetingSearch(activeQuery, searchType)

  const handleSearch = () => {
    if (query.trim()) {
      setActiveQuery(query.trim())
    }
  }

  return (
    <div className="flex-1 space-y-6 p-6">
      {/* Search Bar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search transcripts, summaries, topics..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
            className="pl-10"
          />
        </div>
        <Button onClick={handleSearch} disabled={!query.trim()}>
          Search
        </Button>
      </div>

      {/* Search Type Pills */}
      <div className="flex gap-1">
        {SEARCH_TYPES.map((t) => (
          <Button
            key={t.label}
            variant={searchType === t.value ? 'secondary' : 'ghost'}
            size="sm"
            onClick={() => setSearchType(t.value)}
          >
            {t.label}
          </Button>
        ))}
      </div>

      {/* Results */}
      {isPending && activeQuery ? (
        <div className="space-y-3">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-24 w-full" />
          ))}
        </div>
      ) : data && data.results.length > 0 ? (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            {data.total} results for "{data.query}"
          </p>
          {data.results.map((result, idx) => (
            <Link key={idx} to={`/meetings/${result.meeting_id}`}>
              <Card className="p-4 hover:bg-accent/50 transition-colors cursor-pointer">
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-medium">{result.meeting_title}</span>
                      <Badge variant="secondary" className="text-xs">
                        {(result.score * 100).toFixed(0)}% match
                      </Badge>
                    </div>
                    <p className="text-sm text-muted-foreground line-clamp-2">
                      {result.snippet}
                    </p>
                    <div className="flex items-center gap-3 mt-2 text-xs text-muted-foreground">
                      {result.speaker && (
                        <span className="flex items-center gap-1">
                          <User className="h-3 w-3" />
                          {result.speaker}
                        </span>
                      )}
                      {result.timestamp != null && (
                        <span className="flex items-center gap-1">
                          <Clock className="h-3 w-3" />
                          {Math.floor(result.timestamp / 60)}:{String(Math.floor(result.timestamp % 60)).padStart(2, '0')}
                        </span>
                      )}
                    </div>
                  </div>
                  <ArrowRight className="h-4 w-4 text-muted-foreground flex-shrink-0 mt-1" />
                </div>
              </Card>
            </Link>
          ))}
        </div>
      ) : activeQuery && !isPending ? (
        <div className="text-center text-muted-foreground py-12">
          <Search className="h-12 w-12 mx-auto mb-4 opacity-50" />
          <p>No results found for "{activeQuery}"</p>
          <p className="text-sm mt-1">Try different keywords or search type</p>
        </div>
      ) : (
        <div className="text-center text-muted-foreground py-12">
          <Search className="h-12 w-12 mx-auto mb-4 opacity-50" />
          <p>Enter a search query to find meeting content</p>
        </div>
      )}
    </div>
  )
}
