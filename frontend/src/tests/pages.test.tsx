import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import { render } from './test-utils'
import { DashboardPage } from '@/pages/DashboardPage'
import { KnowledgePage } from '@/pages/KnowledgePage'
import { BoardPage } from '@/pages/BoardPage'

describe('DashboardPage', () => {
  it('renders the page heading', () => {
    render(<DashboardPage />)
    expect(screen.getByText('Welcome to Zero')).toBeInTheDocument()
  })
})

describe('KnowledgePage', () => {
  it('renders the knowledge base heading', () => {
    render(<KnowledgePage />)
    expect(screen.getByText('Knowledge Base')).toBeInTheDocument()
  })

  it('renders the tabs', () => {
    render(<KnowledgePage />)
    expect(screen.getByText('Notes')).toBeInTheDocument()
    expect(screen.getByText('Recall')).toBeInTheDocument()
    expect(screen.getByText('Profile')).toBeInTheDocument()
  })
})

describe('BoardPage', () => {
  it('renders the sprint board heading', () => {
    render(<BoardPage />)
    expect(screen.getByText('Sprint Board')).toBeInTheDocument()
  })
})
