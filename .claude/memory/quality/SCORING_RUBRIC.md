# Zero Platform Quality Scoring Rubric

## Dimensions & Weights

| Dimension | Weight | Description |
|-----------|--------|-------------|
| Backend | 30% | Async patterns, error handling, structlog, Pydantic validation, service separation |
| Frontend | 25% | TypeScript quality, React Query, loading/error states, dark theme, shadcn/ui |
| Testing | 20% | Test files per feature, pass rates, integration coverage |
| Docs | 15% | CLAUDE.md accuracy, inline docs, API documentation |
| Architecture | 10% | Router-service-data separation, DB schema, resilience patterns |

**Formula**: `Overall = (Backend * 0.30) + (Frontend * 0.25) + (Testing * 0.20) + (Docs * 0.15) + (Arch * 0.10)`

**Infra-only features** (no frontend): `Overall = (Backend * 0.55) + (Testing * 0.20) + (Docs * 0.15) + (Arch * 0.10)`
**Frontend-only features**: `Overall = (Frontend * 0.55) + (Testing * 0.20) + (Docs * 0.15) + (Arch * 0.10)`

## Grade Scale

| Grade | Range | Description |
|-------|-------|-------------|
| A+ | 97-100 | Exceptional |
| A | 93-96 | Excellent |
| A- | 90-92 | Very Good |
| B+ | 87-89 | Good |
| B | 83-86 | Above Average |
| B- | 80-82 | Solid |
| C+ | 77-79 | Acceptable |
| C | 73-76 | Average |
| C- | 70-72 | Below Average |
| D | 60-69 | Poor |
| F | 0-59 | Failing |

## Per-Dimension Scoring Guide

### Backend (0-100)
- **90-100**: Full async, structured logging, Pydantic in/out, circuit breakers, retry logic, zero bare exceptions
- **80-89**: Good async, mostly structured logging, Pydantic validation, proper error handling
- **70-79**: Async present but inconsistent, some print() usage, broad except blocks
- **60-69**: Mixed sync/async, print statements, bare exceptions, missing validation
- **Below 60**: Significant sync blocking, no validation, poor error handling

### Frontend (0-100)
- **90-100**: Strict TypeScript (no `any`), React Query everywhere, error boundaries, loading states, responsive
- **80-89**: Good TypeScript, React Query, some missing error boundaries
- **70-79**: TypeScript with occasional `any`, inconsistent loading states
- **60-69**: Loose TypeScript, missing error handling, no loading states
- **Below 60**: Significant `any` usage, no React Query, poor UX

### Testing (0-100)
- **90-100**: >80% coverage, unit + integration + e2e, all passing
- **80-89**: 60-80% coverage, unit + integration, mostly passing
- **70-79**: 40-60% coverage, unit tests, some failing
- **60-69**: 20-40% coverage, basic tests exist
- **Below 60**: <20% coverage or no tests

### Documentation (0-100)
- **90-100**: Complete API docs, inline comments on complex logic, README, architecture docs
- **80-89**: Good API docs, key functions documented
- **70-79**: CLAUDE.md covers basics, some inline comments
- **60-69**: Minimal docs, CLAUDE.md only
- **Below 60**: No meaningful documentation

### Architecture (0-100)
- **90-100**: Clean separation, DB migrations, connection pooling, circuit breakers, caching
- **80-89**: Good separation, migrations, some resilience patterns
- **70-79**: Mostly separated, basic DB patterns
- **60-69**: Some coupling, missing patterns
- **Below 60**: Tightly coupled, no clear architecture
