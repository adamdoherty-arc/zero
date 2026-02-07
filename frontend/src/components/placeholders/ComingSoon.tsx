import { Construction } from 'lucide-react'

interface ComingSoonProps {
  title: string
  description: string
  icon?: React.ReactNode
}

export function ComingSoon({ title, description, icon }: ComingSoonProps) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center animate-fade-in">
      <div className="glass-card p-12 max-w-md">
        <div className="flex justify-center mb-6">
          {icon || <Construction className="w-16 h-16 text-muted-foreground" />}
        </div>
        <h2 className="text-2xl font-bold text-foreground mb-2">{title}</h2>
        <p className="text-muted-foreground">{description}</p>
        <div className="mt-6 text-xs text-muted-foreground/50">Coming in a future phase</div>
      </div>
    </div>
  )
}
