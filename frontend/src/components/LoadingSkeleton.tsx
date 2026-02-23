import { Skeleton } from '@/components/ui/skeleton'

interface LoadingSkeletonProps {
  variant?: 'page' | 'cards' | 'inline'
  count?: number
  message?: string
}

export function LoadingSkeleton({ variant = 'page', count = 3, message }: LoadingSkeletonProps) {
  if (variant === 'inline') {
    return (
      <div className="text-center py-12 text-zinc-400">
        <div className="inline-flex items-center gap-2">
          <div className="w-4 h-4 border-2 border-zinc-600 border-t-indigo-500 rounded-full animate-spin" />
          <span>{message || 'Loading...'}</span>
        </div>
      </div>
    )
  }

  if (variant === 'cards') {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {Array.from({ length: count }).map((_, i) => (
          <div key={i} className="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-3">
            <Skeleton className="h-5 w-3/4" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        ))}
      </div>
    )
  }

  // variant === 'page'
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-lg p-12 text-center">
      <div className="w-8 h-8 border-2 border-zinc-600 border-t-indigo-500 rounded-full animate-spin mx-auto mb-3" />
      <p className="text-zinc-400">{message || 'Loading...'}</p>
    </div>
  )
}
