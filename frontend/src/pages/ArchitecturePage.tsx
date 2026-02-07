import { MermaidDiagram } from '@/components/MermaidDiagram'
import {
  Network,
  Workflow,
  Brain,
  Shield,
} from 'lucide-react'

const architectureDiagram = `graph TB
    User([You])

    subgraph Zero["ZERO - Personal AI Assistant :18792"]
        direction TB
        subgraph ZeroBrain["Second Brain"]
            Knowledge["Knowledge Base"]
            Briefing["Daily Briefing"]
            Research["Research Engine"]
        end
        subgraph ZeroIntegrations["Integrations"]
            Email["Gmail"]
            Calendar["Google Calendar"]
            SearX["SearXNG Search"]
        end
        subgraph ZeroAutopilot["Autonomous Orchestration"]
            DailyPrompts["Daily Prompts"]
            AutoPilot["Autopilot Engine"]
            EnhanceScan["Enhancement Scanner"]
            EcoSync["Ecosystem Sync"]
        end
    end

    subgraph Legion["LEGION - Sprint Execution Engine :8005"]
        direction TB
        subgraph LegionExec["Execution"]
            Swarm["Agent Swarm"]
            Coder["Coder"]
            Tester["Tester"]
            Reviewer["Reviewer"]
            Committer["Committer"]
        end
        subgraph LegionMgmt["Management"]
            Projects["Project Registry"]
            Sprints["Sprint Lifecycle"]
            Tasks["Task Queue"]
            Ideas["Ideas Repo"]
        end
        subgraph LegionKnowledge["Knowledge"]
            RAG["RAG Vector DB"]
            Learnings["Learnings DB"]
            Patterns["Success Patterns"]
        end
    end

    subgraph Ecosystem["Managed Projects"]
        P1["Zero :8"]
        P2["Legion :3"]
        P3["ADA :6"]
        P4["FortressOS :7"]
        P5["+ Future Projects"]
    end

    GitHub["GitHub"]

    User -->|"Prompts & Commands"| Zero
    User -->|"Daily Prompts"| DailyPrompts

    DailyPrompts -->|"Create Sprint Tasks"| Tasks
    AutoPilot -->|"Trigger Swarm Lifecycle"| Swarm
    EnhanceScan -->|"Auto-create Tasks"| Tasks
    EcoSync -->|"Sync Every 15min"| Projects
    Briefing -->|"Query Past Decisions"| RAG

    Tasks --> Coder
    Coder --> Tester
    Tester --> Reviewer
    Reviewer --> Committer
    Committer -->|"Auto-commit & PR"| GitHub
    Committer -->|"Record Outcomes"| Learnings
    Learnings --> RAG
    RAG -->|"Feed Intelligence"| AutoPilot

    Projects --> P1
    Projects --> P2
    Projects --> P3
    Projects --> P4
    Projects --> P5
    GitHub -.->|"Commits & PRs"| Ecosystem`

const flowCards = [
  {
    icon: Workflow,
    title: 'Daily Orchestration',
    color: 'text-blue-400',
    description:
      'You enter daily prompts into Zero. Zero converts them into sprint tasks in Legion. Legion\'s agent swarm (Coder → Tester → Reviewer → Committer) executes the work, commits to GitHub, and reports back.',
  },
  {
    icon: Brain,
    title: 'Knowledge & Learning Loop',
    color: 'text-purple-400',
    description:
      'Every sprint outcome gets recorded in Legion\'s Learnings DB and indexed in the RAG vector store. Zero queries this knowledge for briefings, suggestions, and smarter orchestration over time.',
  },
  {
    icon: Shield,
    title: 'Enhancement Cycle',
    color: 'text-green-400',
    description:
      'Zero scans all project codebases for TODOs, security issues, and code smells. High-confidence findings are auto-created as Legion tasks. Legion executes fixes and commits them — fully autonomous.',
  },
]

export function ArchitecturePage() {
  return (
    <div className="page-content">
      {/* Header */}
      <div className="flex items-center gap-3 mb-8">
        <Network className="w-8 h-8 text-primary" />
        <div>
          <h1 className="page-title">Architecture</h1>
          <p className="text-xs text-muted-foreground">
            Zero + Legion ecosystem overview
          </p>
        </div>
      </div>

      {/* Intro Card */}
      <div className="glass-card p-5 mb-6">
        <h2 className="text-sm font-semibold text-foreground mb-1">
          Zero + Legion Ecosystem
        </h2>
        <p className="text-xs text-muted-foreground leading-relaxed">
          <strong className="text-foreground">Zero</strong> is your personal AI
          assistant and second brain — it manages your email, calendar,
          knowledge base, research, and daily briefings.{' '}
          <strong className="text-foreground">Legion</strong> is the sprint
          execution engine that manages all your projects, plans sprints, and
          deploys agent swarms to write, test, review, and commit code. Zero
          orchestrates Legion autonomously, creating tasks from your prompts
          and feeding intelligence back from every execution.
        </p>
      </div>

      {/* Architecture Diagram */}
      <div className="glass-card p-6 mb-6 overflow-x-auto">
        <MermaidDiagram
          diagram={architectureDiagram}
          className="w-full flex justify-center"
        />
      </div>

      {/* Flow Explanation Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {flowCards.map((card) => (
          <div key={card.title} className="glass-card p-5">
            <div className="flex items-center gap-2 mb-2">
              <card.icon className={`w-4 h-4 ${card.color}`} />
              <h3 className="text-sm font-semibold text-foreground">
                {card.title}
              </h3>
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              {card.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  )
}
