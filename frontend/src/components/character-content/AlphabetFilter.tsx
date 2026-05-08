import { useMemo } from 'react'

interface AlphabetFilterProps<T> {
  items: T[]
  getName: (item: T) => string
  selected: string | null
  onSelect: (letter: string | null) => void
}

const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')

function firstLetter(name: string): string {
  const first = (name || '').trim().charAt(0).toUpperCase()
  return /[A-Z]/.test(first) ? first : '#'
}

export function bucketOf(name: string): string {
  return firstLetter(name)
}

export function sortByName<T>(items: T[], getName: (item: T) => string): T[] {
  return [...items].sort((a, b) =>
    getName(a).localeCompare(getName(b), undefined, { sensitivity: 'base' })
  )
}

export function AlphabetFilter<T>({ items, getName, selected, onSelect }: AlphabetFilterProps<T>) {
  const populated = useMemo(() => {
    const s = new Set<string>()
    for (const item of items) s.add(firstLetter(getName(item)))
    return s
  }, [items, getName])

  const buttonClass = (active: boolean, enabled: boolean) =>
    `px-2 h-7 min-w-[28px] text-xs font-mono rounded border transition-colors ${
      active
        ? 'bg-indigo-600 text-white border-indigo-500'
        : enabled
        ? 'bg-gray-800 text-gray-300 border-gray-700 hover:bg-gray-700 hover:text-white'
        : 'bg-gray-900 text-gray-600 border-gray-800 cursor-not-allowed'
    }`

  return (
    <div className="flex flex-wrap items-center gap-1" role="toolbar" aria-label="Filter by first letter">
      <button
        type="button"
        onClick={() => onSelect(null)}
        className={buttonClass(selected === null, true)}
        aria-pressed={selected === null}
      >
        All
      </button>
      {LETTERS.map((letter) => {
        const enabled = populated.has(letter)
        return (
          <button
            key={letter}
            type="button"
            onClick={() => enabled && onSelect(selected === letter ? null : letter)}
            disabled={!enabled}
            className={buttonClass(selected === letter, enabled)}
            aria-pressed={selected === letter}
            aria-label={`Filter to names starting with ${letter}`}
          >
            {letter}
          </button>
        )
      })}
      {populated.has('#') && (
        <button
          type="button"
          onClick={() => onSelect(selected === '#' ? null : '#')}
          className={buttonClass(selected === '#', true)}
          aria-pressed={selected === '#'}
          aria-label="Filter to names starting with a non-letter"
        >
          #
        </button>
      )}
    </div>
  )
}
