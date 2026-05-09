export type RiskLevel = 'low' | 'medium' | 'high' | 'critical'
export type CompanyTaskStatus = 'backlog' | 'ready' | 'on-hold' | 'in-progress' | 'blocked' | 'done'

export interface CompanyTask {
  id: string
  title: string
  domain: string
  sprint: string
  status: CompanyTaskStatus
  owner: string
  priority: number
  due: string
  risk: RiskLevel
  requiresApproval: boolean
  sourceSystem: 'zero' | 'legion' | 'obsidian' | 'legacy-company'
  nextAction: boolean
}

export interface AgentProfile {
  key: string
  name: string
  level: 'observe' | 'draft' | 'recommend' | 'execute-low-risk'
  owner: string
  status: 'active' | 'ready' | 'blocked'
  openTasks: number
  runs7d: number
  approvalsWaiting: number
}

export interface ApprovalItem {
  id: string
  action: string
  owner: string
  risk: RiskLevel
  status: 'pending' | 'approved' | 'rejected'
  due: string
  source: string
}

export interface SubscriptionItem {
  vendor: string
  category: string
  monthlyCost: number
  renewal: string
  owner: string
  evidence: 'missing' | 'partial' | 'ready'
}

export interface AssetItem {
  name: string
  type: string
  cost: number
  businessUse: number
  placedInService: string
  evidence: 'missing' | 'partial' | 'ready'
}

export interface TaxEvent {
  title: string
  date: string
  owner: string
  status: 'not-started' | 'ready' | 'blocked'
}

export interface FinanceSetupRail {
  rail: string
  status: 'ready' | 'blocked' | 'pending' | 'active' | 'review'
  owner: string
  risk: RiskLevel
  next: string
}

export interface EvidencePacket {
  item: string
  owner: string
  status: 'missing' | 'partial' | 'ready'
  artifact: string
  next: string
}

export interface Opportunity {
  account: string
  offer: string
  stage: string
  value: number
  nextStep: string
}

export interface ProductIdea {
  name: string
  thesis: string
  stage: string
  confidence: number
}

export interface LabJob {
  item: string
  material: string
  stage: string
  safety: 'review-needed' | 'clear'
}

export interface CompanyDoc {
  title: string
  path: string
  purpose: string
  owner: string
  route: string
  agent: string
  reviewed: string
}

export const companyKpis = [
  { label: 'Operating home', value: 'Zero', detail: 'Company OS merged into Zero UI and docs' },
  { label: 'Open approvals', value: '9', detail: 'External filings, bank, card, IP, robot, assets, and public gates' },
  { label: 'Active sprints', value: '9', detail: 'Finance setup through second brain' },
  { label: 'Next deadline', value: 'May 2026', detail: 'EIN, bank, books, asset register' },
]

export const tasks: CompanyTask[] = [
  { id: 'form-001', title: 'Verify ADA AI LLC name on Sunbiz', domain: 'Formation', sprint: 'Formation Sprint', status: 'done', owner: 'legal', priority: 1, due: '2026-05-06', risk: 'medium', requiresApproval: true, sourceSystem: 'zero', nextAction: false },
  { id: 'form-002', title: 'File Florida LLC Articles of Organization', domain: 'Formation', sprint: 'Formation Sprint', status: 'done', owner: 'legal', priority: 1, due: '2026-05-10', risk: 'critical', requiresApproval: true, sourceSystem: 'zero', nextAction: false },
  { id: 'form-003', title: 'Confirm ADA AI LLC has no existing EIN', domain: 'Finance', sprint: 'Finance Sprint', status: 'in-progress', owner: 'finance', priority: 1, due: '2026-05-06', risk: 'medium', requiresApproval: false, sourceSystem: 'zero', nextAction: true },
  { id: 'form-004', title: 'Apply for EIN and archive CP 575 confirmation', domain: 'Finance', sprint: 'Finance Sprint', status: 'blocked', owner: 'finance', priority: 1, due: '2026-05-07', risk: 'high', requiresApproval: true, sourceSystem: 'zero', nextAction: false },
  { id: 'admin-001', title: 'Choose business email, password vault, and receipt inbox', domain: 'Admin', sprint: 'Admin Sprint', status: 'ready', owner: 'security', priority: 2, due: '2026-05-15', risk: 'medium', requiresApproval: true, sourceSystem: 'zero', nextAction: false },
  { id: 'finance-001', title: 'Create receipt inbox and bookkeeping categories for AI/API spend', domain: 'Finance', sprint: 'Finance Sprint', status: 'in-progress', owner: 'procurement', priority: 2, due: '2026-05-08', risk: 'low', requiresApproval: false, sourceSystem: 'zero', nextAction: false },
  { id: 'finance-002', title: 'Create home-office evidence log and hardware asset register', domain: 'Finance', sprint: 'Finance Sprint', status: 'in-progress', owner: 'finance', priority: 2, due: '2026-05-09', risk: 'medium', requiresApproval: false, sourceSystem: 'zero', nextAction: false },
  { id: 'finance-003', title: 'Open ADA AI LLC checking after EIN and signed operating agreement', domain: 'Finance', sprint: 'Finance Sprint', status: 'blocked', owner: 'finance', priority: 1, due: '2026-05-10', risk: 'high', requiresApproval: true, sourceSystem: 'zero', nextAction: false },
  { id: 'finance-004', title: 'Document business credit card personal-credit policy before applying', domain: 'Finance', sprint: 'Finance Sprint', status: 'in-progress', owner: 'finance', priority: 1, due: '2026-05-11', risk: 'medium', requiresApproval: false, sourceSystem: 'zero', nextAction: false },
  { id: 'asset-001', title: 'Build existing equipment FMV transfer packet', domain: 'Finance', sprint: 'Asset Transfer Sprint', status: 'in-progress', owner: 'procurement', priority: 1, due: '2026-05-12', risk: 'medium', requiresApproval: false, sourceSystem: 'zero', nextAction: false },
  { id: 'robot-001', title: 'Record robot purchase or transfer decision for ADA AI LLC', domain: 'Robotics', sprint: 'Robotics Sprint', status: 'in-progress', owner: 'robotics', priority: 1, due: '2026-05-13', risk: 'medium', requiresApproval: false, sourceSystem: 'zero', nextAction: false },
  { id: 'ip-001', title: 'Draft robot-control software IP assignment schedule', domain: 'Legal', sprint: 'IP Sprint', status: 'in-progress', owner: 'legal', priority: 1, due: '2026-05-13', risk: 'medium', requiresApproval: false, sourceSystem: 'zero', nextAction: false },
  { id: 'zero-merge-001', title: 'Merge Company OS docs and UI into Zero', domain: 'Zero', sprint: 'Dashboard Sprint', status: 'in-progress', owner: 'engineering', priority: 1, due: '2026-05-02', risk: 'low', requiresApproval: false, sourceSystem: 'legion', nextAction: true },
  { id: 'agent-001', title: 'Define permission tiers and approval gates for every company agent', domain: 'Agents', sprint: 'Agent Sprint', status: 'in-progress', owner: 'ceo', priority: 1, due: '2026-05-08', risk: 'high', requiresApproval: true, sourceSystem: 'zero', nextAction: true },
  { id: 'consult-001', title: 'Draft ICP, consulting packages, and discovery questionnaire', domain: 'Consulting', sprint: 'Consulting Sprint', status: 'ready', owner: 'consulting', priority: 2, due: '2026-05-24', risk: 'medium', requiresApproval: true, sourceSystem: 'zero', nextAction: false },
  { id: 'product-001', title: 'Choose first software product thesis and MVP spec', domain: 'Product', sprint: 'Product Sprint', status: 'ready', owner: 'product', priority: 2, due: '2026-05-27', risk: 'medium', requiresApproval: true, sourceSystem: 'zero', nextAction: false },
  { id: 'robotics-001', title: 'Create printer, materials, maintenance, and safety inventory', domain: 'Robotics', sprint: 'Robotics Sprint', status: 'ready', owner: 'robotics', priority: 3, due: '2026-06-01', risk: 'medium', requiresApproval: false, sourceSystem: 'zero', nextAction: false },
  { id: 'brain-001', title: 'Create Obsidian effort mirror and weekly review note', domain: 'Second Brain', sprint: 'Second-Brain Sprint', status: 'in-progress', owner: 'knowledge', priority: 2, due: '2026-05-04', risk: 'low', requiresApproval: false, sourceSystem: 'obsidian', nextAction: true },
]

export const agentProfiles: AgentProfile[] = [
  { key: 'ceo', name: 'CEO / Chief-of-Staff Agent', level: 'recommend', owner: 'Operating cadence', status: 'active', openTasks: 12, runs7d: 5, approvalsWaiting: 2 },
  { key: 'finance', name: 'Finance / CPA Ops Agent', level: 'draft', owner: 'Books and tax packet', status: 'ready', openTasks: 10, runs7d: 3, approvalsWaiting: 1 },
  { key: 'legal', name: 'Legal / Compliance Ops Agent', level: 'draft', owner: 'LLC, contracts, disclaimers', status: 'ready', openTasks: 9, runs7d: 2, approvalsWaiting: 2 },
  { key: 'procurement', name: 'Procurement / Asset Agent', level: 'execute-low-risk', owner: 'Vendors and renewals', status: 'active', openTasks: 8, runs7d: 4, approvalsWaiting: 1 },
  { key: 'consulting', name: 'Consulting Revenue Agent', level: 'draft', owner: 'ICP, offers, pipeline', status: 'ready', openTasks: 11, runs7d: 4, approvalsWaiting: 0 },
  { key: 'delivery', name: 'Delivery Agent', level: 'draft', owner: 'Client onboarding', status: 'ready', openTasks: 6, runs7d: 1, approvalsWaiting: 0 },
  { key: 'product', name: 'Product Agent', level: 'recommend', owner: 'Product thesis and roadmap', status: 'active', openTasks: 9, runs7d: 5, approvalsWaiting: 0 },
  { key: 'engineering', name: 'Engineering Agent', level: 'execute-low-risk', owner: 'Implementation sprints', status: 'active', openTasks: 14, runs7d: 7, approvalsWaiting: 0 },
  { key: 'llmops', name: 'LLM Ops Agent', level: 'recommend', owner: 'Models, costs, evals', status: 'ready', openTasks: 7, runs7d: 2, approvalsWaiting: 0 },
  { key: 'knowledge', name: 'Knowledge / Second-Brain Agent', level: 'execute-low-risk', owner: 'Vault mirror and reviews', status: 'active', openTasks: 6, runs7d: 6, approvalsWaiting: 0 },
  { key: 'marketing', name: 'Marketing / Content Agent', level: 'draft', owner: 'Website and content', status: 'ready', openTasks: 8, runs7d: 2, approvalsWaiting: 1 },
  { key: 'robotics', name: 'Robotics / 3D Lab Agent', level: 'draft', owner: 'Printers, materials, safety', status: 'ready', openTasks: 7, runs7d: 1, approvalsWaiting: 0 },
  { key: 'security', name: 'Security / Risk Agent', level: 'recommend', owner: 'Secrets and controls', status: 'ready', openTasks: 8, runs7d: 2, approvalsWaiting: 0 },
]

export const approvals: ApprovalItem[] = [
  { id: 'ap-001', action: 'Apply for EIN using ADA AI LLC legal name', owner: 'Finance / CPA Ops', risk: 'high', status: 'pending', due: '2026-05-07', source: 'Finance Setup' },
  { id: 'ap-002', action: 'Sign operating agreement and banking authorization', owner: 'Legal / Compliance', risk: 'critical', status: 'pending', due: '2026-05-09', source: 'LLC Compliance' },
  { id: 'ap-003', action: 'Open ADA AI LLC business checking', owner: 'Finance / CPA Ops', risk: 'high', status: 'pending', due: '2026-05-10', source: 'Finance Setup' },
  { id: 'ap-004', action: 'Apply for one business credit card after reporting policy is documented', owner: 'Finance / CPA Ops', risk: 'high', status: 'pending', due: '2026-05-11', source: 'Finance Setup' },
  { id: 'ap-005', action: 'Transfer existing equipment only at documented FMV', owner: 'Procurement / Asset', risk: 'high', status: 'pending', due: '2026-05-12', source: 'Asset Transfer Sprint' },
  { id: 'ap-006', action: 'Sign robot-control software IP assignment or license schedule', owner: 'Legal / Compliance', risk: 'critical', status: 'pending', due: '2026-05-13', source: 'IP Sprint' },
  { id: 'ap-007', action: 'Buy or transfer robot hardware through ADA AI LLC records', owner: 'Robotics / Asset', risk: 'high', status: 'pending', due: '2026-05-13', source: 'Robotics Sprint' },
  { id: 'ap-008', action: 'Publish public consulting positioning on adamdoherty.com', owner: 'Marketing / Content', risk: 'high', status: 'pending', due: '2026-05-24', source: 'Consulting Sprint' },
  { id: 'ap-009', action: 'Use financial-software disclaimers publicly', owner: 'Legal / Compliance', risk: 'critical', status: 'pending', due: '2026-06-07', source: 'Product Sprint' },
]

export const subscriptions: SubscriptionItem[] = [
  { vendor: 'OpenAI', category: 'AI platform', monthlyCost: 20, renewal: 'Monthly', owner: 'LLM Ops', evidence: 'partial' },
  { vendor: 'Anthropic', category: 'AI coding', monthlyCost: 20, renewal: 'Monthly', owner: 'Engineering', evidence: 'partial' },
  { vendor: 'Google Gemini / AI Studio', category: 'AI platform', monthlyCost: 0, renewal: 'Usage-based', owner: 'LLM Ops', evidence: 'missing' },
  { vendor: 'GitHub', category: 'Source control', monthlyCost: 10, renewal: 'Monthly', owner: 'Engineering', evidence: 'ready' },
  { vendor: 'Google Workspace', category: 'Business email', monthlyCost: 14, renewal: 'Monthly', owner: 'Admin', evidence: 'missing' },
  { vendor: 'QuickBooks / Wave decision', category: 'Bookkeeping', monthlyCost: 30, renewal: 'TBD', owner: 'Finance', evidence: 'missing' },
  { vendor: 'Cloud / VPS / storage', category: 'Infrastructure', monthlyCost: 0, renewal: 'Usage-based', owner: 'Engineering', evidence: 'missing' },
  { vendor: 'Legion local stack', category: 'Internal platform', monthlyCost: 0, renewal: 'Self-hosted', owner: 'Engineering', evidence: 'ready' },
]

export const assets: AssetItem[] = [
  { name: 'Main AI workstation', type: 'Computer hardware transfer', cost: 0, businessUse: 90, placedInService: 'TBD', evidence: 'partial' },
  { name: 'Monitors and peripherals', type: 'Computer hardware transfer', cost: 0, businessUse: 90, placedInService: 'TBD', evidence: 'missing' },
  { name: 'Upgraded components', type: 'Computer component transfer', cost: 0, businessUse: 90, placedInService: 'TBD', evidence: 'missing' },
  { name: 'Robot hardware', type: 'Robotics lab purchase/transfer', cost: 0, businessUse: 100, placedInService: 'TBD', evidence: 'missing' },
  { name: 'Robot-control software', type: 'Software/IP schedule', cost: 0, businessUse: 100, placedInService: 'TBD', evidence: 'missing' },
  { name: 'Home office equipment', type: 'Office', cost: 0, businessUse: 100, placedInService: 'TBD', evidence: 'partial' },
]

export const taxEvents: TaxEvent[] = [
  { title: 'EIN confirmation archived', date: '2026-05-07', owner: 'Finance', status: 'blocked' },
  { title: 'Business checking opened', date: '2026-05-10', owner: 'Finance', status: 'blocked' },
  { title: 'Business card reporting policy documented', date: '2026-05-11', owner: 'Finance', status: 'ready' },
  { title: 'Asset transfer packet ready for CPA', date: '2026-05-12', owner: 'Finance', status: 'ready' },
  { title: 'IP assignment schedule ready for attorney', date: '2026-05-13', owner: 'Legal', status: 'ready' },
  { title: 'Duval Local Business Tax Receipt', date: '2026-05-25', owner: 'Legal', status: 'not-started' },
  { title: 'CPA setup consult', date: '2026-06-15', owner: 'Finance', status: 'not-started' },
  { title: 'Florida annual report', date: '2027-05-01', owner: 'Finance', status: 'not-started' },
  { title: 'Review 475(f) trader-tax decision', date: '2027-04-15', owner: 'Finance', status: 'not-started' },
]

export const financeSetupRails: FinanceSetupRail[] = [
  { rail: 'EIN', status: 'ready', owner: 'Finance / CPA Ops', risk: 'high', next: 'Confirm no existing EIN, then use IRS assistant and archive CP 575.' },
  { rail: 'Banking', status: 'blocked', owner: 'Finance / CPA Ops', risk: 'high', next: 'Open checking after EIN, operating agreement, and ownership memo are ready.' },
  { rail: 'Business card', status: 'active', owner: 'Finance / CPA Ops', risk: 'high', next: 'Document issuer reporting policy, personal guarantee, hard pull, and autopay before the card application approval.' },
  { rail: 'Books', status: 'active', owner: 'Finance / CPA Ops', risk: 'medium', next: 'Track AI/API, cloud, SaaS, hardware, robot, home-office, contributions, and reimbursements.' },
  { rail: 'Home office', status: 'active', owner: 'Finance / CPA Ops', risk: 'medium', next: 'Measure exclusive business space and collect monthly actual-cost evidence.' },
  { rail: 'Assets', status: 'active', owner: 'Procurement / Asset', risk: 'high', next: 'Gather serials, photos, receipts, upgrades, business-use percent, and FMV comparables.' },
  { rail: 'Robot', status: 'review', owner: 'Robotics / Asset', risk: 'high', next: 'Prepare buy-vs-transfer evidence; actual purchase or transfer stays approval-gated.' },
  { rail: 'Software/IP', status: 'active', owner: 'Legal / Compliance', risk: 'critical', next: 'Draft assignment or license schedule; signing and valuation stay attorney/CPA-gated.' },
]

export const financeEvidencePackets: EvidencePacket[] = [
  { item: 'EIN confirmation', owner: 'Finance', status: 'missing', artifact: 'Secure company docs', next: 'Save IRS confirmation letter with issue date and responsible party.' },
  { item: 'Bank/card decision log', owner: 'Finance', status: 'ready', artifact: 'docs/company/templates/bank-card-decision-log.md', next: 'Fill bank packet and card reporting-policy fields before applying.' },
  { item: 'Asset transfer memo', owner: 'Procurement', status: 'ready', artifact: 'docs/company/templates/owner-equipment-transfer-memo.md', next: 'Add main computer, monitors, peripherals, robot, receipts, photos, and FMV comparables.' },
  { item: 'Software/IP schedule', owner: 'Legal', status: 'ready', artifact: 'docs/company/templates/ip-assignment-schedule.md', next: 'List robot-control repositories, included modules, dependencies, and proposed transfer method.' },
  { item: 'Home-office worksheet', owner: 'Finance', status: 'partial', artifact: 'Finance workbook', next: 'Measure business area and collect rent/mortgage interest, utilities, internet, insurance, and repairs.' },
  { item: 'CPA setup agenda', owner: 'Finance', status: 'ready', artifact: 'docs/company/templates/cpa-setup-agenda.md', next: 'Bring P&L, receipts, subscriptions, asset register, home office, and decisions needed.' },
]

export const opportunities: Opportunity[] = [
  { account: 'Local professional services firm', offer: 'AI adoption readiness audit', stage: 'Prospect', value: 2500, nextStep: 'Draft discovery questions' },
  { account: 'Solo founder SaaS peer', offer: 'Agent workflow buildout', stage: 'Warm lead', value: 5000, nextStep: 'Prepare sample automation map' },
  { account: 'Jacksonville SMB operator', offer: 'AI operations sprint', stage: 'Research', value: 7500, nextStep: 'Find decision-maker and pain signals' },
]

export const productIdeas: ProductIdea[] = [
  { name: 'AI adoption command center', thesis: 'A dashboard and agent workflow kit for small companies adopting AI safely.', stage: 'MVP spec', confidence: 78 },
  { name: 'Financial decision-support workspace', thesis: 'Personal research and portfolio context without autonomous advice claims.', stage: 'Compliance review', confidence: 64 },
  { name: 'Second-brain operations sync', thesis: 'Repo, Legion, and Obsidian state reconciler for founder-operators.', stage: 'Internal tool', confidence: 83 },
]

export const labJobs: LabJob[] = [
  { item: 'Cable clips for workstation', material: 'PETG', stage: 'Queued', safety: 'clear' },
  { item: 'Printer calibration artifact', material: 'PLA', stage: 'Draft', safety: 'clear' },
  { item: 'Client-facing physical prototype', material: 'TBD', stage: 'Blocked', safety: 'review-needed' },
]

export const companyDocs: CompanyDoc[] = [
  { title: 'Company Operating Model', path: 'docs/company/company-operating-model.md', purpose: 'Business model and source-of-truth rules', owner: 'Company model', route: '/company', agent: 'CEO / Chief-of-Staff Agent', reviewed: '2026-05-02' },
  { title: 'LLC And Compliance', path: 'docs/company/llc-compliance.md', purpose: 'Florida SMLLC, tax, CPA, attorney checklist', owner: 'Legal / finance', route: '/company/legal', agent: 'Legal / Compliance Ops Agent', reviewed: '2026-05-02' },
  { title: 'Agent Company Structure', path: 'docs/company/agent-company-structure.md', purpose: 'Agent org chart, permissions, approval gates', owner: 'Agents', route: '/company/agents', agent: 'CEO / Chief-of-Staff Agent', reviewed: '2026-05-02' },
  { title: 'Task Management System', path: 'docs/company/task-management-system.md', purpose: 'Zero task source of truth and Obsidian/Notion decision', owner: 'Tasks', route: '/company/tasks', agent: 'Knowledge / Second-Brain Agent', reviewed: '2026-05-02' },
  { title: 'Finance Procurement System', path: 'docs/company/finance-procurement-system.md', purpose: 'Subscriptions, assets, renewals, CPA evidence', owner: 'Finance', route: '/company/finance', agent: 'Finance / CPA Ops Agent', reviewed: '2026-05-02' },
  { title: 'Dashboard Spec', path: 'docs/company/dashboard-spec.md', purpose: 'Company dashboard views and acceptance criteria', owner: 'Dashboard', route: '/company', agent: 'Engineering Agent', reviewed: '2026-05-02' },
  { title: 'Consulting Playbook', path: 'docs/company/consulting-playbook.md', purpose: 'Offers, discovery, proposal, delivery flow', owner: 'Revenue', route: '/company/revenue', agent: 'Consulting Revenue Agent', reviewed: '2026-05-02' },
  { title: 'Product Robotics Roadmap', path: 'docs/company/product-robotics-roadmap.md', purpose: 'Product studio and 3D/robotics lab plan', owner: 'Product / robotics', route: '/company/product', agent: 'Product Agent', reviewed: '2026-05-02' },
  { title: 'Second Brain Sync', path: 'docs/company/second-brain-sync.md', purpose: 'Obsidian mirror and weekly review convention', owner: 'Knowledge', route: '/company/docs', agent: 'Knowledge / Second-Brain Agent', reviewed: '2026-05-02' },
  { title: 'Sources', path: 'docs/company/sources.md', purpose: 'Official sources and research links', owner: 'Sources', route: '/company/docs', agent: 'Legal / Compliance Ops Agent', reviewed: '2026-05-02' },
]
