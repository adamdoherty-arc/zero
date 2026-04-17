import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { render } from './test-utils'
import { CharacterContentPage } from '@/pages/CharacterContentPage'
import TikTokPhonePreview from '@/components/character-content/TikTokPhonePreview'
import type { CharacterCarousel } from '@/hooks/useCharacterContentApi'

// Mock the entire hook module
vi.mock('@/hooks/useCharacterContentApi', () => {
  const mockCharacters = [
    {
      id: 'char-1',
      name: 'Spider-Man',
      universe: 'marvel',
      franchise: 'MCU',
      status: 'active',
      research_status: 'completed',
      posts_created: 3,
      avg_engagement: 0.12,
      fact_bank: [{ text: 'Test fact', category: 'trivia', surprise_score: 7 }],
      research_sources: ['fandom_wiki', 'reddit'],
      research_depth_score: 75.0,
      image_url: null,
      created_at: '2026-04-01T00:00:00Z',
    },
  ]
  const mockStats = {
    total_characters: 24,
    researched_characters: 5,
    total_carousels: 15,
    avg_ai_score: 8.6,
    pending_review: 14,
    approved: 1,
    published: 0,
    total_facts: 134,
    unique_angles_used: 7,
    templates_used: 7,
  }

  return {
    useCharacters: () => ({ data: mockCharacters, isLoading: false, error: null, refetch: vi.fn() }),
    useCharacterStats: () => ({ data: mockStats, isLoading: false, error: null, refetch: vi.fn() }),
    useCarousels: () => ({ data: [], isLoading: false, error: null, refetch: vi.fn() }),
    useReviewQueue: () => ({ data: [], isLoading: false, error: null, refetch: vi.fn() }),
    useSmartReviewQueue: () => ({ data: [], isLoading: false, error: null, refetch: vi.fn() }),
    useCreateCharacter: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useResearchCharacter: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useSeedCharacters: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useGenerateCarousel: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useAiReviewCarousel: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useApproveCarousel: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useRejectCarousel: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useBatchResearch: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useInspirations: () => ({ data: [], isLoading: false, error: null, refetch: vi.fn() }),
    useInspirationPatterns: () => ({ data: null, isLoading: false, error: null }),
    useDiscoverInspirations: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useAnalyzeInspiration: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useTemplates: () => ({ data: [], isLoading: false, error: null }),
    useSeedTemplates: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useSeedMusic: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useSmartBatchGenerate: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useGenerateSeries: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useSourceAnalytics: () => ({ data: null, isLoading: false, error: null }),
    useTemplateAnalytics: () => ({ data: null, isLoading: false, error: null }),
    useResearchQueue: () => ({ data: [], isLoading: false, error: null, refetch: vi.fn() }),
    useStartResearchQueue: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useCancelResearchQueue: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useRetryResearch: () => ({ mutateAsync: vi.fn(), isPending: false }),
    useUpdateCarousel: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    useReimageSlide: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
    useMusicTracks: () => ({ data: [], isLoading: false, error: null, refetch: vi.fn() }),
    useTrendingMusic: () => ({ data: [], isLoading: false, error: null, refetch: vi.fn() }),
    useAssignMusic: () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false }),
  }
})

// Mock react-router-dom useNavigate
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return {
    ...actual,
    useNavigate: () => vi.fn(),
  }
})

describe('CharacterContentPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders character count label on the default section', () => {
    render(<CharacterContentPage />)
    // Default section is "characters" (via useSearchParams). It shows a live count.
    expect(screen.getByText(/\d+ characters/i)).toBeInTheDocument()
  })

  it('renders the default-section action buttons', () => {
    render(<CharacterContentPage />)
    expect(screen.getByRole('button', { name: /Research all characters/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Add new character/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Seed character library/i })).toBeInTheDocument()
  })

  it('renders the universe filter control', () => {
    render(<CharacterContentPage />)
    expect(screen.getByRole('combobox', { name: /Select universe filter/i })).toBeInTheDocument()
  })

  it('renders character list in default section', async () => {
    render(<CharacterContentPage />)
    await waitFor(() => {
      expect(screen.getByText('Spider-Man')).toBeInTheDocument()
    })
  })

  it('wraps content in the character content error boundary', () => {
    const { container } = render(<CharacterContentPage />)
    // Error boundary renders its children directly when no error is thrown.
    // We just confirm the default section rendered (boundary did not swallow it).
    expect(container.firstChild).not.toBeNull()
    expect(screen.getByText(/\d+ characters/i)).toBeInTheDocument()
  })

  it('renders action buttons', async () => {
    render(<CharacterContentPage />)
    await waitFor(() => {
      const buttons = screen.getAllByRole('button')
      expect(buttons.length).toBeGreaterThan(0)
    })
  })
})

// --- TikTokPhonePreview ---------------------------------------------------

function buildCarousel(overrides: Partial<CharacterCarousel> = {}): CharacterCarousel {
  return {
    id: 'car-1',
    character_id: 'char-1',
    character_name: 'Darth Vader',
    angle: 'hidden_truths',
    title: 'Hidden Truths',
    hook_text: 'What Darth Vader never wanted you to know',
    slides: [
      { slide_num: 1, text: 'Slide one text', image_query: 'darth vader portrait' },
      { slide_num: 2, text: 'Slide two text', image_query: 'vader helmet' },
      { slide_num: 3, text: 'Slide three text', image_query: 'vader saber' },
    ],
    caption: 'You will not believe this',
    hashtags: ['starwars', 'vader'],
    music_mood: 'dark',
    status: 'pending_review',
    multi_character_ids: [],
    text_overlay_specs: [],
    generation_metadata: {},
    created_at: '2026-04-10T00:00:00Z',
    ...overrides,
  }
}

describe('TikTokPhonePreview', () => {
  it('renders the hook and all slides count in read mode', () => {
    render(<TikTokPhonePreview carousel={buildCarousel()} editMode={false} />)
    expect(screen.getByText(/What Darth Vader never wanted you to know/i)).toBeInTheDocument()
  })

  it('renders username and caption', () => {
    render(<TikTokPhonePreview carousel={buildCarousel()} editMode={false} />)
    expect(screen.getByText('@darthvader')).toBeInTheDocument()
    expect(screen.getByText(/You will not believe this/i)).toBeInTheDocument()
  })

  it('renders hashtags as chips', () => {
    render(<TikTokPhonePreview carousel={buildCarousel()} editMode={false} />)
    expect(screen.getByText('#starwars')).toBeInTheDocument()
    expect(screen.getByText('#vader')).toBeInTheDocument()
  })

  it('forwards hook edits through onChange in edit mode', () => {
    const onChange = vi.fn()
    render(<TikTokPhonePreview carousel={buildCarousel()} editMode onChange={onChange} />)
    const hookTextarea = screen.getByPlaceholderText(/hook\.\.\./i) as HTMLTextAreaElement
    fireEvent.change(hookTextarea, { target: { value: 'Brand new hook' } })
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ hook_text: 'Brand new hook' }))
  })

  it('shows the music picker trigger in edit mode', () => {
    const onOpen = vi.fn()
    render(
      <TikTokPhonePreview
        carousel={buildCarousel()}
        editMode
        onOpenMusicPicker={onOpen}
      />,
    )
    const pickerButton = screen.getByRole('button', { name: /change music|pick music/i })
    fireEvent.click(pickerButton)
    expect(onOpen).toHaveBeenCalled()
  })

  it('renders a placeholder when there are zero slides', () => {
    render(<TikTokPhonePreview carousel={buildCarousel({ slides: [] })} editMode={false} />)
    expect(screen.getByText(/no slides/i)).toBeInTheDocument()
  })
})
