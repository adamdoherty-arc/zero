import { useState } from 'react'
import {
    Building2, ChevronRight, ChevronDown, CheckCircle2, AlertTriangle,
    DollarSign, Clock, ExternalLink, Lightbulb, Send, Loader2,
    FileText, Scale, CreditCard, Shield, ArrowRight,
} from 'lucide-react'
import {
    useGenerateGuidance, useAskLlcQuestion,
    type GuidanceRequest, type GuidanceResponse, type BusinessType, type LLCType,
} from '@/hooks/useLlcGuidanceApi'

const BUSINESS_OPTIONS: { value: BusinessType; label: string; description: string }[] = [
    { value: 'tiktok_shop', label: 'TikTok Shop', description: 'Sell products through TikTok Shop marketplace' },
    { value: 'consulting', label: 'Consulting', description: 'Professional consulting or advisory services' },
    { value: 'ecommerce', label: 'E-commerce', description: 'Online store (Shopify, Amazon, etc.)' },
    { value: 'content_creation', label: 'Content Creation', description: 'YouTube, TikTok, social media content' },
    { value: 'dropshipping', label: 'Dropshipping', description: 'Sell products without holding inventory' },
    { value: 'affiliate_marketing', label: 'Affiliate Marketing', description: 'Earn commissions promoting products' },
    { value: 'agency', label: 'Agency', description: 'Marketing, creative, or digital agency' },
    { value: 'software', label: 'Software', description: 'Software development or SaaS products' },
    { value: 'other', label: 'Other', description: 'Other business activity' },
]

const US_STATES = [
    'AL','AK','AZ','AR','CA','CO','CT','DE','FL','GA',
    'HI','ID','IL','IN','IA','KS','KY','LA','ME','MD',
    'MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ',
    'NM','NY','NC','ND','OH','OK','OR','PA','RI','SC',
    'SD','TN','TX','UT','VT','VA','WA','WV','WI','WY',
]

// ============================================
// WIZARD FORM
// ============================================

function WizardForm({ onSubmit, isLoading }: { onSubmit: (req: GuidanceRequest) => void; isLoading: boolean }) {
    const [step, setStep] = useState(0)
    const [businessTypes, setBusinessTypes] = useState<BusinessType[]>([])
    const [state, setState] = useState('WY')
    const [llcType, setLlcType] = useState<LLCType>('single_member')
    const [numMembers, setNumMembers] = useState(1)
    const [nameIdeas, setNameIdeas] = useState('')
    const [revenue, setRevenue] = useState('')
    const [hasExisting, setHasExisting] = useState(false)
    const [questions, setQuestions] = useState('')

    const toggleBusiness = (bt: BusinessType) => {
        setBusinessTypes(prev =>
            prev.includes(bt) ? prev.filter(b => b !== bt) : [...prev, bt]
        )
    }

    const canProceed = () => {
        if (step === 0) return businessTypes.length > 0
        if (step === 1) return state.length === 2
        return true
    }

    const handleSubmit = () => {
        onSubmit({
            business_types: businessTypes,
            state,
            llc_name_ideas: nameIdeas.split(',').map(s => s.trim()).filter(Boolean),
            llc_type: llcType,
            num_members: numMembers,
            annual_revenue_estimate: revenue || undefined,
            has_existing_llc: hasExisting,
            specific_questions: questions || undefined,
        })
    }

    const steps = [
        // Step 0: Business types
        <div key="business">
            <h3 className="text-lg font-semibold text-white mb-2">What will your LLC do?</h3>
            <p className="text-sm text-gray-400 mb-4">Select all that apply. A single LLC can cover multiple business activities.</p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {BUSINESS_OPTIONS.map(opt => (
                    <button
                        key={opt.value}
                        onClick={() => toggleBusiness(opt.value)}
                        className={`p-3 rounded-lg border text-left transition-all ${
                            businessTypes.includes(opt.value)
                                ? 'border-indigo-500 bg-indigo-500/10 text-white'
                                : 'border-gray-700 bg-gray-800/50 text-gray-300 hover:border-gray-600'
                        }`}
                    >
                        <div className="font-medium text-sm">{opt.label}</div>
                        <div className="text-xs text-gray-400 mt-1">{opt.description}</div>
                    </button>
                ))}
            </div>
            {businessTypes.length > 1 && (
                <div className="mt-3 p-3 bg-indigo-500/10 border border-indigo-500/30 rounded-lg">
                    <div className="flex items-start gap-2">
                        <Lightbulb className="w-4 h-4 text-indigo-400 mt-0.5 flex-shrink-0" />
                        <p className="text-sm text-indigo-300">
                            Great choice! A single LLC with a broad operating agreement can cover all {businessTypes.length} activities.
                            This is cheaper than forming separate LLCs.
                        </p>
                    </div>
                </div>
            )}
        </div>,

        // Step 1: State + LLC type
        <div key="state">
            <h3 className="text-lg font-semibold text-white mb-2">Where will you form your LLC?</h3>
            <p className="text-sm text-gray-400 mb-4">
                Wyoming and New Mexico are popular for online businesses. Your home state may be simpler if you operate locally.
            </p>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">State</label>
                    <select
                        value={state}
                        onChange={e => setState(e.target.value)}
                        className="w-full p-2.5 bg-gray-800 border border-gray-700 rounded-lg text-white focus:border-indigo-500 focus:outline-none"
                    >
                        {US_STATES.map(s => (
                            <option key={s} value={s}>{s}</option>
                        ))}
                    </select>

                    <div className="mt-4 space-y-2">
                        {['WY', 'NM', 'DE', 'NV'].map(rec => (
                            <button
                                key={rec}
                                onClick={() => setState(rec)}
                                className={`w-full p-2 rounded border text-left text-sm ${
                                    state === rec
                                        ? 'border-indigo-500 bg-indigo-500/10 text-white'
                                        : 'border-gray-700 bg-gray-800/30 text-gray-400 hover:border-gray-600'
                                }`}
                            >
                                <span className="font-medium">{rec}</span>
                                <span className="text-gray-500 ml-2">
                                    {rec === 'WY' && '- Best overall for online biz'}
                                    {rec === 'NM' && '- Cheapest ($50, no annual fee)'}
                                    {rec === 'DE' && '- Most prestigious for investors'}
                                    {rec === 'NV' && '- No state income tax, strong privacy'}
                                </span>
                            </button>
                        ))}
                    </div>
                </div>

                <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">LLC Type</label>
                    <div className="space-y-2">
                        {([
                            { value: 'single_member' as LLCType, label: 'Single-Member LLC', desc: 'One owner — simplest structure' },
                            { value: 'multi_member' as LLCType, label: 'Multi-Member LLC', desc: 'Multiple owners/partners' },
                            { value: 'series_llc' as LLCType, label: 'Series LLC', desc: 'Separate liability for each business line (not all states)' },
                        ]).map(opt => (
                            <button
                                key={opt.value}
                                onClick={() => { setLlcType(opt.value); if (opt.value === 'single_member') setNumMembers(1) }}
                                className={`w-full p-3 rounded-lg border text-left ${
                                    llcType === opt.value
                                        ? 'border-indigo-500 bg-indigo-500/10 text-white'
                                        : 'border-gray-700 bg-gray-800/50 text-gray-300 hover:border-gray-600'
                                }`}
                            >
                                <div className="font-medium text-sm">{opt.label}</div>
                                <div className="text-xs text-gray-400">{opt.desc}</div>
                            </button>
                        ))}
                    </div>

                    {llcType === 'multi_member' && (
                        <div className="mt-3">
                            <label className="block text-sm text-gray-300 mb-1">Number of members</label>
                            <input
                                type="number"
                                min={2}
                                max={100}
                                value={numMembers}
                                onChange={e => setNumMembers(Math.max(2, parseInt(e.target.value) || 2))}
                                className="w-24 p-2 bg-gray-800 border border-gray-700 rounded text-white"
                            />
                        </div>
                    )}
                </div>
            </div>
        </div>,

        // Step 2: Details
        <div key="details">
            <h3 className="text-lg font-semibold text-white mb-2">A few more details</h3>
            <p className="text-sm text-gray-400 mb-4">All fields are optional — they help Zero give you more personalized guidance.</p>
            <div className="space-y-4">
                <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">LLC name ideas (comma-separated)</label>
                    <input
                        type="text"
                        value={nameIdeas}
                        onChange={e => setNameIdeas(e.target.value)}
                        placeholder="e.g., Apex Ventures, Adam Holdings, Pinnacle Group"
                        className="w-full p-2.5 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
                    />
                </div>
                <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">Estimated annual revenue</label>
                    <select
                        value={revenue}
                        onChange={e => setRevenue(e.target.value)}
                        className="w-full p-2.5 bg-gray-800 border border-gray-700 rounded-lg text-white focus:border-indigo-500 focus:outline-none"
                    >
                        <option value="">Not sure yet</option>
                        <option value="under_10k">Under $10,000</option>
                        <option value="10k_50k">$10,000 - $50,000</option>
                        <option value="50k_100k">$50,000 - $100,000</option>
                        <option value="100k_500k">$100,000 - $500,000</option>
                        <option value="500k_plus">$500,000+</option>
                    </select>
                </div>
                <div className="flex items-center gap-3">
                    <input
                        type="checkbox"
                        checked={hasExisting}
                        onChange={e => setHasExisting(e.target.checked)}
                        className="w-4 h-4 rounded bg-gray-800 border-gray-600"
                    />
                    <label className="text-sm text-gray-300">I already have an existing LLC</label>
                </div>
                <div>
                    <label className="block text-sm font-medium text-gray-300 mb-1">Any specific questions?</label>
                    <textarea
                        value={questions}
                        onChange={e => setQuestions(e.target.value)}
                        placeholder="e.g., Should I get an S-Corp election? Do I need a DBA?"
                        rows={3}
                        className="w-full p-2.5 bg-gray-800 border border-gray-700 rounded-lg text-white placeholder-gray-500 focus:border-indigo-500 focus:outline-none resize-none"
                    />
                </div>
            </div>
        </div>,
    ]

    return (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            {/* Progress */}
            <div className="flex items-center gap-2 mb-6">
                {['Business Activities', 'State & Structure', 'Details'].map((label, i) => (
                    <div key={label} className="flex items-center gap-2">
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                            i < step ? 'bg-indigo-500 text-white'
                            : i === step ? 'bg-indigo-500/20 border border-indigo-500 text-indigo-400'
                            : 'bg-gray-800 text-gray-500'
                        }`}>
                            {i < step ? <CheckCircle2 className="w-4 h-4" /> : i + 1}
                        </div>
                        <span className={`text-sm hidden sm:inline ${i === step ? 'text-white' : 'text-gray-500'}`}>{label}</span>
                        {i < 2 && <ChevronRight className="w-4 h-4 text-gray-600" />}
                    </div>
                ))}
            </div>

            {steps[step]}

            {/* Navigation */}
            <div className="flex justify-between mt-6 pt-4 border-t border-gray-800">
                <button
                    onClick={() => setStep(Math.max(0, step - 1))}
                    disabled={step === 0}
                    className="px-4 py-2 text-sm text-gray-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
                >
                    Back
                </button>
                {step < 2 ? (
                    <button
                        onClick={() => setStep(step + 1)}
                        disabled={!canProceed()}
                        className="px-6 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                    >
                        Next <ArrowRight className="w-4 h-4" />
                    </button>
                ) : (
                    <button
                        onClick={handleSubmit}
                        disabled={isLoading || !canProceed()}
                        className="px-6 py-2 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-medium rounded-lg disabled:opacity-50 flex items-center gap-2"
                    >
                        {isLoading ? (
                            <><Loader2 className="w-4 h-4 animate-spin" /> Generating Guide...</>
                        ) : (
                            <><Building2 className="w-4 h-4" /> Generate My LLC Guide</>
                        )}
                    </button>
                )}
            </div>
        </div>
    )
}

// ============================================
// GUIDANCE RESULTS
// ============================================

function GuidanceResults({ guidance, onReset }: { guidance: GuidanceResponse; onReset: () => void }) {
    const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set([1]))

    const toggleStep = (n: number) => {
        setExpandedSteps(prev => {
            const next = new Set(prev)
            if (next.has(n)) next.delete(n)
            else next.add(n)
            return next
        })
    }

    return (
        <div className="space-y-6">
            {/* Header Summary */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                <div className="flex items-start justify-between">
                    <div>
                        <h2 className="text-xl font-bold text-white mb-2">Your LLC Formation Guide</h2>
                        <p className="text-gray-400 text-sm">{guidance.why_this_structure}</p>
                    </div>
                    <button
                        onClick={onReset}
                        className="text-sm text-gray-500 hover:text-white px-3 py-1 border border-gray-700 rounded-lg"
                    >
                        Start Over
                    </button>
                </div>

                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
                    <div className="bg-gray-800/50 p-3 rounded-lg">
                        <div className="flex items-center gap-2 text-gray-400 text-xs mb-1">
                            <DollarSign className="w-3 h-3" /> Total Cost
                        </div>
                        <div className="text-white text-sm font-medium">{guidance.estimated_total_cost}</div>
                    </div>
                    <div className="bg-gray-800/50 p-3 rounded-lg">
                        <div className="flex items-center gap-2 text-gray-400 text-xs mb-1">
                            <Clock className="w-3 h-3" /> Timeline
                        </div>
                        <div className="text-white text-sm font-medium">{guidance.estimated_timeline}</div>
                    </div>
                    <div className="bg-gray-800/50 p-3 rounded-lg">
                        <div className="flex items-center gap-2 text-gray-400 text-xs mb-1">
                            <Building2 className="w-3 h-3" /> State
                        </div>
                        <div className="text-white text-sm font-medium">{guidance.recommended_state}</div>
                    </div>
                    <div className="bg-gray-800/50 p-3 rounded-lg">
                        <div className="flex items-center gap-2 text-gray-400 text-xs mb-1">
                            <FileText className="w-3 h-3" /> Steps
                        </div>
                        <div className="text-white text-sm font-medium">{guidance.formation_steps.length} steps</div>
                    </div>
                </div>
            </div>

            {/* Name Suggestions */}
            {guidance.llc_name_suggestions.length > 0 && (
                <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                    <h3 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
                        <Lightbulb className="w-5 h-5 text-yellow-400" /> LLC Name Suggestions
                    </h3>
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
                        {guidance.llc_name_suggestions.map((name, i) => (
                            <div key={i} className="p-2.5 bg-gray-800/50 border border-gray-700 rounded-lg text-white text-sm">
                                {name}
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Formation Steps */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <FileText className="w-5 h-5 text-indigo-400" /> Formation Steps
                </h3>
                <div className="space-y-2">
                    {guidance.formation_steps.map((step) => (
                        <div key={step.step_number} className="border border-gray-800 rounded-lg overflow-hidden">
                            <button
                                onClick={() => toggleStep(step.step_number)}
                                className="w-full p-4 flex items-center gap-3 hover:bg-gray-800/50 transition-colors"
                            >
                                <div className="w-8 h-8 rounded-full bg-indigo-500/20 flex items-center justify-center text-indigo-400 text-sm font-medium flex-shrink-0">
                                    {step.step_number}
                                </div>
                                <div className="flex-1 text-left">
                                    <div className="text-white text-sm font-medium">{step.title}</div>
                                    <div className="flex items-center gap-3 text-xs text-gray-500 mt-0.5">
                                        {step.estimated_cost && <span className="flex items-center gap-1"><DollarSign className="w-3 h-3" />{step.estimated_cost}</span>}
                                        {step.estimated_time && <span className="flex items-center gap-1"><Clock className="w-3 h-3" />{step.estimated_time}</span>}
                                        {step.required && <span className="text-amber-500">Required</span>}
                                    </div>
                                </div>
                                {expandedSteps.has(step.step_number) ? <ChevronDown className="w-4 h-4 text-gray-400" /> : <ChevronRight className="w-4 h-4 text-gray-400" />}
                            </button>
                            {expandedSteps.has(step.step_number) && (
                                <div className="px-4 pb-4 pt-0 border-t border-gray-800">
                                    <p className="text-gray-300 text-sm mt-3">{step.description}</p>

                                    {step.tips.length > 0 && (
                                        <div className="mt-3">
                                            <div className="text-xs font-medium text-gray-500 uppercase mb-2">Tips</div>
                                            <ul className="space-y-1.5">
                                                {step.tips.map((tip, i) => (
                                                    <li key={i} className="flex items-start gap-2 text-sm text-gray-400">
                                                        <span className="text-indigo-400 mt-1">&#8226;</span> {tip}
                                                    </li>
                                                ))}
                                            </ul>
                                        </div>
                                    )}

                                    {step.links.length > 0 && (
                                        <div className="mt-3 flex flex-wrap gap-2">
                                            {step.links.map((link, i) => (
                                                <a
                                                    key={i}
                                                    href={link.url}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="inline-flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300 bg-indigo-500/10 px-2 py-1 rounded"
                                                >
                                                    <ExternalLink className="w-3 h-3" /> {link.text}
                                                </a>
                                            ))}
                                        </div>
                                    )}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            </div>

            {/* Tax + Operating Agreement + Warnings side by side */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Tax */}
                <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                    <h3 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
                        <CreditCard className="w-5 h-5 text-green-400" /> Tax Considerations
                    </h3>
                    <ul className="space-y-2">
                        {guidance.tax_considerations.map((item, i) => (
                            <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                                <span className="text-green-400 mt-1">&#8226;</span> {item}
                            </li>
                        ))}
                    </ul>
                </div>

                {/* Operating Agreement */}
                <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                    <h3 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
                        <Scale className="w-5 h-5 text-blue-400" /> Operating Agreement Must-Haves
                    </h3>
                    <ul className="space-y-2">
                        {guidance.operating_agreement_points.map((item, i) => (
                            <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                                <span className="text-blue-400 mt-1">&#8226;</span> {item}
                            </li>
                        ))}
                    </ul>
                </div>
            </div>

            {/* Business-Specific Tips */}
            {Object.keys(guidance.business_specific_tips).length > 0 && (
                <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                    <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                        <Lightbulb className="w-5 h-5 text-yellow-400" /> Tips by Business Type
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {Object.entries(guidance.business_specific_tips).map(([type, tips]) => (
                            <div key={type} className="bg-gray-800/50 p-4 rounded-lg">
                                <div className="text-sm font-medium text-indigo-300 mb-2 capitalize">{type.replace(/_/g, ' ')}</div>
                                <ul className="space-y-1.5">
                                    {tips.map((tip, i) => (
                                        <li key={i} className="text-xs text-gray-400 flex items-start gap-1.5">
                                            <span className="text-indigo-400">&#8226;</span> {tip}
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        ))}
                    </div>
                </div>
            )}

            {/* Next Steps */}
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                <h3 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
                    <ArrowRight className="w-5 h-5 text-indigo-400" /> After Formation
                </h3>
                <ul className="space-y-2">
                    {guidance.next_steps_after_formation.map((item, i) => (
                        <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                            <CheckCircle2 className="w-4 h-4 text-indigo-400 mt-0.5 flex-shrink-0" /> {item}
                        </li>
                    ))}
                </ul>
            </div>

            {/* Warnings */}
            {guidance.warnings.length > 0 && (
                <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-6">
                    <h3 className="text-lg font-semibold text-amber-300 mb-3 flex items-center gap-2">
                        <AlertTriangle className="w-5 h-5" /> Important Warnings
                    </h3>
                    <ul className="space-y-2">
                        {guidance.warnings.map((item, i) => (
                            <li key={i} className="flex items-start gap-2 text-sm text-amber-200/80">
                                <AlertTriangle className="w-4 h-4 text-amber-400 mt-0.5 flex-shrink-0" /> {item}
                            </li>
                        ))}
                    </ul>
                </div>
            )}
        </div>
    )
}

// ============================================
// ASK ZERO
// ============================================

function AskZeroSection() {
    const [question, setQuestion] = useState('')
    const askMutation = useAskLlcQuestion()
    const [history, setHistory] = useState<{ q: string; a: string }[]>([])

    const handleAsk = () => {
        if (!question.trim()) return
        const q = question.trim()
        setQuestion('')
        askMutation.mutate({ question: q }, {
            onSuccess: (data) => {
                setHistory(prev => [...prev, { q, a: data.answer }])
            },
        })
    }

    return (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-lg font-semibold text-white mb-3 flex items-center gap-2">
                <Shield className="w-5 h-5 text-indigo-400" /> Ask Zero About LLCs
            </h3>
            <p className="text-sm text-gray-400 mb-4">
                Have a specific question about LLC formation, taxes, or business structure? Ask Zero.
            </p>

            {history.map((item, i) => (
                <div key={i} className="mb-4 space-y-2">
                    <div className="flex items-start gap-2">
                        <span className="text-indigo-400 text-sm font-medium">Q:</span>
                        <p className="text-sm text-white">{item.q}</p>
                    </div>
                    <div className="flex items-start gap-2 bg-gray-800/50 p-3 rounded-lg">
                        <span className="text-green-400 text-sm font-medium">A:</span>
                        <p className="text-sm text-gray-300 whitespace-pre-wrap">{item.a}</p>
                    </div>
                </div>
            ))}

            {askMutation.isPending && (
                <div className="flex items-center gap-2 text-gray-400 text-sm mb-4">
                    <Loader2 className="w-4 h-4 animate-spin" /> Thinking...
                </div>
            )}

            <div className="flex gap-2">
                <input
                    type="text"
                    value={question}
                    onChange={e => setQuestion(e.target.value)}
                    onKeyDown={e => e.key === 'Enter' && handleAsk()}
                    placeholder="e.g., Do I need a separate LLC for my TikTok Shop and consulting?"
                    className="flex-1 p-2.5 bg-gray-800 border border-gray-700 rounded-lg text-white text-sm placeholder-gray-500 focus:border-indigo-500 focus:outline-none"
                />
                <button
                    onClick={handleAsk}
                    disabled={!question.trim() || askMutation.isPending}
                    className="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg disabled:opacity-50 flex items-center gap-1"
                >
                    <Send className="w-4 h-4" />
                </button>
            </div>
        </div>
    )
}

// ============================================
// MAIN PAGE
// ============================================

export function LlcGuidancePage() {
    const [guidance, setGuidance] = useState<GuidanceResponse | null>(null)
    const generateMutation = useGenerateGuidance()

    const handleSubmit = (req: GuidanceRequest) => {
        generateMutation.mutate(req, {
            onSuccess: (data) => setGuidance(data),
        })
    }

    return (
        <div className="p-6 max-w-6xl mx-auto space-y-6">

            {/* Wizard or Results */}
            {!guidance ? (
                <WizardForm onSubmit={handleSubmit} isLoading={generateMutation.isPending} />
            ) : (
                <GuidanceResults guidance={guidance} onReset={() => setGuidance(null)} />
            )}

            {/* Always show Q&A */}
            <AskZeroSection />

            {/* Disclaimer */}
            <div className="text-xs text-gray-600 text-center">
                This guidance is for informational purposes only and does not constitute legal or tax advice.
                Consult a qualified attorney or CPA for advice specific to your situation.
            </div>
        </div>
    )
}
