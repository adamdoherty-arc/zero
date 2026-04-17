"""Add AI Company tables: agent_roles, agent_tasks, experiments, council_decisions, deep_research_reports

Revision ID: 015_ai_company
Revises: 014_add_assistant_intelligence
Create Date: 2026-04-04
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, ARRAY

revision = '015_ai_company'
down_revision = '014_add_assistant_intelligence'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Agent roles
    op.create_table(
        'agent_roles',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('capabilities', ARRAY(sa.Text()), server_default='{}'),
        sa.Column('system_prompt', sa.Text(), nullable=False),
        sa.Column('llm_provider', sa.String(64), nullable=False),
        sa.Column('llm_model', sa.String(128), nullable=False),
        sa.Column('llm_temperature', sa.Float(), server_default='0.7'),
        sa.Column('execution_llm_provider', sa.String(64)),
        sa.Column('execution_llm_model', sa.String(128)),
        sa.Column('delegation_rules', JSONB(), server_default='{}'),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Agent tasks
    op.create_table(
        'agent_tasks',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('project_id', sa.String(64)),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('task_type', sa.String(32), nullable=False, index=True),
        sa.Column('assigned_role', sa.String(64), sa.ForeignKey('agent_roles.id', ondelete='SET NULL'), index=True),
        sa.Column('status', sa.String(20), server_default='pending', index=True),
        sa.Column('priority', sa.Integer(), server_default='3'),
        sa.Column('dependencies', ARRAY(sa.String(64)), server_default='{}'),
        sa.Column('context', JSONB(), server_default='{}'),
        sa.Column('result', JSONB()),
        sa.Column('parent_task_id', sa.String(64)),
        sa.Column('cost_usd', sa.Float(), server_default='0.0'),
        sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
    )
    op.create_index('idx_agent_tasks_parent', 'agent_tasks', ['parent_task_id'])
    op.create_index('idx_agent_tasks_created', 'agent_tasks', ['created_at'])

    # Experiments
    op.create_table(
        'experiments',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('hypothesis', sa.Text(), nullable=False),
        sa.Column('methodology', sa.Text()),
        sa.Column('experiment_type', sa.String(32), nullable=False, index=True),
        sa.Column('status', sa.String(20), server_default='designed', index=True),
        sa.Column('parameters', JSONB(), server_default='{}'),
        sa.Column('metrics', JSONB(), server_default='{}'),
        sa.Column('results', JSONB()),
        sa.Column('conclusion', sa.Text()),
        sa.Column('linked_idea_id', sa.String(64)),
        sa.Column('linked_research_id', sa.String(64)),
        sa.Column('created_by_role', sa.String(64)),
        sa.Column('cost_usd', sa.Float(), server_default='0.0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
    )

    # Council decisions
    op.create_table(
        'council_decisions',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('topic', sa.String(500), nullable=False),
        sa.Column('context', JSONB(), server_default='{}'),
        sa.Column('proposer_role', sa.String(64)),
        sa.Column('rounds', JSONB(), server_default='[]'),
        sa.Column('votes', JSONB(), server_default='{}'),
        sa.Column('decision', sa.String(20)),
        sa.Column('confidence_score', sa.Float()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('decided_at', sa.DateTime(timezone=True)),
    )
    op.create_index('idx_council_decisions_status', 'council_decisions', ['decision'])

    # Deep research reports
    op.create_table(
        'deep_research_reports',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('query', sa.Text(), nullable=False),
        sa.Column('status', sa.String(20), server_default='pending', index=True),
        sa.Column('outline', JSONB()),
        sa.Column('perspectives', JSONB(), server_default='[]'),
        sa.Column('sources', JSONB(), server_default='[]'),
        sa.Column('sections', JSONB(), server_default='{}'),
        sa.Column('report_markdown', sa.Text()),
        sa.Column('executive_summary', sa.Text()),
        sa.Column('cost_usd', sa.Float(), server_default='0.0'),
        sa.Column('error', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
    )

    # Seed default roles
    op.execute("""
        INSERT INTO agent_roles (id, name, description, capabilities, system_prompt, llm_provider, llm_model, llm_temperature, execution_llm_provider, execution_llm_model, delegation_rules) VALUES
        ('ceo', 'Chief Executive Agent', 'Strategic planning, task decomposition, delegation, and final synthesis. The CEO breaks complex requests into structured subtasks for other roles and synthesizes their outputs into coherent results.', ARRAY['planning', 'delegation', 'synthesis', 'decision_making'], 'You are the CEO agent of an AI company. Your role is to:
1. Analyze incoming requests and break them into clear, structured subtasks
2. Assign subtasks to the right specialist roles (researcher, analyst, engineer, validator)
3. Synthesize results from multiple agents into coherent final outputs
4. Make strategic decisions when agents disagree

When creating subtasks, always include:
- Clear task description
- Expected output format (JSON schema)
- Evaluation criteria
- Context from previous steps

Always respond with valid JSON.', 'kimi', 'kimi-k2.5', 0.7, NULL, NULL, '{"delegate_research": "researcher", "delegate_analysis": "analyst", "delegate_implementation": "engineer", "delegate_validation": "validator"}'),

        ('researcher', 'Research Agent', 'Deep research, web search, multi-source synthesis, and trend analysis. Uses SearXNG for web research and can summarize findings from multiple sources.', ARRAY['deep_research', 'web_search', 'synthesis', 'trend_analysis'], 'You are a Research Agent. Your role is to:
1. Execute web searches using the provided search queries
2. Analyze and synthesize information from multiple sources
3. Identify key trends, patterns, and insights
4. Provide citations and source URLs for all claims
5. Flag areas of uncertainty or conflicting information

When given a structured research task, follow the instructions exactly and return results in the specified JSON format. Be thorough but concise.', 'kimi', 'kimi-k2.5', 0.7, 'ollama', 'qwen3.6:35b-a3b-q8_0', '{}'),

        ('analyst', 'Analyst Agent', 'Data analysis, scoring, market sizing, financial projections, and structured evaluation. Works with structured rubrics provided by the CEO.', ARRAY['data_analysis', 'scoring', 'market_sizing', 'financial_projection', 'swot'], 'You are an Analyst Agent. Your role is to:
1. Perform quantitative analysis on provided data
2. Score ideas/products using structured rubrics
3. Calculate market size estimates (TAM/SAM/SOM)
4. Generate financial projections
5. Produce SWOT analyses

Always follow the rubric or schema provided. Return structured JSON with clear numerical scores and supporting reasoning. Be data-driven and conservative in estimates.', 'ollama', 'qwen3.6:35b-a3b-q8_0', 0.3, NULL, NULL, '{}'),

        ('engineer', 'Engineer Agent', 'Implementation, code generation, prototyping, and technical feasibility assessment. Handles structured coding tasks.', ARRAY['implementation', 'code_generation', 'prototyping', 'technical_assessment'], 'You are an Engineer Agent. Your role is to:
1. Implement solutions based on structured specifications
2. Generate code following best practices
3. Assess technical feasibility of proposed ideas
4. Build prototypes and proof-of-concepts
5. Run benchmarks and performance tests

Follow specifications exactly. Return structured JSON with code, explanations, and any issues found.', 'ollama', 'qwen3.6:35b-a3b-q8_0', 0.2, NULL, NULL, '{}'),

        ('validator', 'Validator Agent', 'Assumption testing, feasibility checking, risk assessment, and quality validation. Uses structured rubrics to evaluate outputs from other agents.', ARRAY['validation', 'risk_assessment', 'feasibility_check', 'assumption_testing'], 'You are a Validator Agent. Your role is to:
1. Test assumptions using structured evaluation criteria
2. Assess feasibility across 5 dimensions: Desirability, Viability, Feasibility, Usability, Ethical
3. Identify risks and potential failure modes
4. Spot-check claims against available evidence
5. Flag unsupported assertions or logical gaps

Be critical but constructive. Return structured JSON with pass/fail assessments, confidence scores, and specific concerns.', 'ollama', 'qwen3.6:35b-a3b-q8_0', 0.3, NULL, NULL, '{}')
    """)


def downgrade() -> None:
    op.drop_table('deep_research_reports')
    op.drop_table('council_decisions')
    op.drop_table('experiments')
    op.drop_table('agent_tasks')
    op.drop_table('agent_roles')
