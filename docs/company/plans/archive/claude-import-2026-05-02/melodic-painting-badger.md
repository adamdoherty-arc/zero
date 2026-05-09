# Plan: Professional Resume Formatting with Google Docs Export

## Context

The current resume system uses a basic WeasyPrint HTML template ([resume_ats.html](backend/app/templates/resume_ats.html)) that produces functional but visually plain PDFs. You want:
1. Professional, well-formatted resume templates
2. Export to `.docx` format (opens natively in Google Docs)
3. Direct export to Google Docs in your Drive
4. PDF export via Google Docs for higher-quality rendering

## Approach: `docxtpl` + Google Drive API

**Why this approach:** `docxtpl` (Jinja2 templating inside Word files) lets us design pixel-perfect `.docx` templates in Word/Docs, then fill them programmatically. Google Drive API auto-converts uploaded `.docx` to native Google Docs. All Google libraries (`google-api-python-client`, `google-auth-oauthlib`) are already in `requirements.txt`.

**Scope:** Both phases ship together. Templates built programmatically in Python (no external .docx template files).

## Phase 1 - DOCX Template Engine

### 1.1 Add dependency
- Add `docxtpl>=0.18.0` to [requirements.txt](backend/requirements.txt)

### 1.2 Programmatic template builders
Instead of `.docx` template files, each template is a Python function that builds the document using `python-docx` directly (fonts, styles, spacing, section headings all in code). This is fully version-controlled and avoids external binary files.

Directory: `backend/app/templates/resumes/` (empty, templates live in code)

4 template builder functions in `ResumeFormatterService`:

| Template ID | Style | Best for |
|-------------|-------|----------|
| `ats_classic` | Single-column, Calibri, standard headings, max ATS compatibility | ATS systems, large corps |
| `modern_clean` | Two-column header area, clean sans-serif, blue accent lines | Tech companies, startups |
| `executive_serif` | Times New Roman/Georgia, centered header, conservative spacing | Senior roles, finance |
| `creative_accent` | Accent color sidebar header, skills highlighted, modern feel | Design-adjacent, marketing |

Each builder function takes a context dict and returns `python-docx.Document` bytes.

### 1.3 New service: `ResumeFormatterService`
File: `backend/app/services/resume_formatter.py`

- `list_templates()` - returns template metadata (name, description, best_for, available)
- `render_variant_docx(variant_id, user_id, template)` - renders ResumeVariant to `.docx` bytes
- `render_base_resume_docx(resume_id, user_id, template)` - renders plain Resume to `.docx`
- Reuses `PdfService` patterns: `_get_variant_for_user()`, `_get_user()`, `_build_context()`, `_contact_line()`

### 1.4 New API endpoints

**[resume.py](backend/app/api/resume.py):**
- `GET /resume/templates` - list available templates
- `GET /resume/{id}/docx?template=ats_classic` - download resume as formatted `.docx`
- `GET /resume/{id}/pdf` - download resume as PDF (wires existing PdfService)

**[resume_variants.py](backend/app/api/resume_variants.py):**
- `GET /resume-variants/templates` - list templates
- `GET /resume-variants/{id}/docx?template=ats_classic` - download variant as `.docx`

### 1.5 Frontend updates

**[api.js](frontend/src/services/api.js):**
- Add `resumeAPI.templates()`, `.downloadDocx(id, template)`, `.downloadPdf(id)`
- Add `resumeVariantsAPI.downloadDocx(id, template)`

**New component: `ResumeExportModal.jsx`**
- Template picker grid (4 cards with name, description, best-for tags)
- Format selector: DOCX or PDF
- Download button triggers blob download

**[Resume.jsx](frontend/src/pages/Resume.jsx):**
- Add download/export button (DocumentArrowDownIcon) to each resume card
- Opens `ResumeExportModal` on click

---

## Phase 2 - Google Docs Direct Export

### 2.1 Config additions
Add to [config.py](backend/app/core/config.py):
- `google_docs_enabled: bool = False`
- `google_docs_credentials_path` / `google_docs_token_path`
- Scopes: `drive.file` + `documents`

### 2.2 New service: `GoogleDocsService`
File: `backend/app/services/google_docs_service.py`

- `get_auth_url(user_id)` - generates OAuth URL (per-user tokens)
- `handle_callback(user_id, code)` - exchanges code for token, stores per-user
- `is_connected(user_id)` - checks if user has valid credentials
- `upload_docx_to_drive(docx_bytes, title, user_id)` - uploads `.docx`, auto-converts to Google Docs, returns `web_view_link`
- `export_as_pdf(file_id, user_id)` - exports Google Doc as high-quality PDF

### 2.3 API endpoints
- `GET /resume/google/status` - check connection
- `GET /resume/google/auth-url` - get OAuth URL
- `GET /resume/google/callback` - handle OAuth redirect
- `POST /resume/{id}/export/google-docs` - render DOCX -> upload to Drive -> return Google Doc URL
- `POST /resume/{id}/export/google-pdf` - render DOCX -> upload to Drive -> export PDF -> return PDF

### 2.4 Frontend
- Add "Google Docs" option in `ResumeExportModal` (greyed out if not connected)
- Add "Connect Google Account" button that initiates OAuth flow
- On export: opens Google Doc URL in new tab

---

## Files to modify/create

### New files
1. `backend/app/services/resume_formatter.py` - DOCX template service (programmatic builders)
2. `backend/app/services/google_docs_service.py` - Google Drive/Docs API
3. `frontend/src/components/ResumeExportModal.jsx` - Export modal

### Modified files
1. `backend/requirements.txt` - add `docxtpl>=0.18.0`
2. `backend/app/api/resume.py` - add `/templates`, `/{id}/docx`, `/{id}/pdf`, Google Docs endpoints
3. `backend/app/api/resume_variants.py` - add `/templates`, `/{id}/docx`, Google Docs endpoints
4. `backend/app/core/config.py` - add `google_docs_*` settings
5. `frontend/src/services/api.js` - add download/template/Google Docs API methods
6. `frontend/src/pages/Resume.jsx` - add export button per resume card
7. `.env.example` - add Google Docs config vars

### Key existing code to reuse
- [PdfService](backend/app/services/pdf_service.py) - `_get_variant_for_user()`, `_get_user()`, `_build_context()`, `_contact_line()` patterns
- [GmailService](backend/app/services/gmail_service.py) - OAuth credential storage pattern
- [deps.py](backend/app/api/deps.py) - `DbSession`, `CurrentUserId`, `not_found_error`
- Google libs already in requirements: `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`

---

## Verification

1. **Phase 1 smoke test:**
   - `GET /api/resume/templates` returns 4 templates
   - `GET /api/resume/{id}/docx?template=modern_clean` downloads a valid `.docx`
   - Open downloaded `.docx` in Google Docs - verify formatting preserved
   - Frontend: click Export on resume card, pick template, download works
   - Rebuild containers: `docker compose up -d --build backend frontend`

2. **Phase 2 smoke test:**
   - `GET /api/resume/google/status` returns `{enabled: true, connected: false}`
   - OAuth flow: click Connect -> authorize -> callback stores token
   - `POST /api/resume/{id}/export/google-docs` creates Doc in Drive, returns URL
   - Open URL in browser -> see formatted resume in Google Docs
   - Export as PDF from Google Docs -> verify quality
