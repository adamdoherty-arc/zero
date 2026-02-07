import { useEffect, useRef, useState } from 'react'
import { renderMermaid } from 'beautiful-mermaid'

interface MermaidDiagramProps {
  diagram: string
  className?: string
}

export function MermaidDiagram({ diagram, className }: MermaidDiagramProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    setError(null)

    renderMermaid(diagram, {
      bg: '#0a0e1a',
      fg: '#e2e8f0',
      line: '#475569',
      accent: '#6366f1',
      muted: '#94a3b8',
      surface: '#1e293b',
      border: '#334155',
      font: 'Inter',
      transparent: true,
    })
      .then((svg) => {
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg
        }
      })
      .catch((err) => {
        if (!cancelled) setError(String(err))
      })

    return () => {
      cancelled = true
    }
  }, [diagram])

  if (error) {
    return (
      <div className="text-red-400 text-sm p-4">
        Diagram render error: {error}
      </div>
    )
  }

  return <div ref={containerRef} className={className} />
}
