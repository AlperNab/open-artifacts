# Open Artifacts — Standalone Real GUI Implementation

This folder is now its own runnable project app. It does not depend on the root all-project dashboard at runtime.

## Run

```bash
./run_gui.sh
```

Windows:

```powershell
.\run_gui_windows.ps1
```

Default URL: `http://127.0.0.1:9142`

## What is inside this project folder

- `app/` — FastAPI backend for this project.
- `static/` — elegant browser GUI.
- `plugins/open-artifacts.json` — this project’s own feature/customization/input schema.
- `project_config.json` — readable copy of the same project-specific configuration.
- `data/` — local SQLite jobs, uploads, exports.
- `tests/` — verifies this project has a registered real local engine.

## Project-specific scope

- Domain: `AI Platform / Artifact Runtime`
- Target user: `Domain operator, business owner, analyst, or team member who needs this workflow executed reliably.`
- Core job: AI-generated artifacts → self-hosted runtime
- Suite: `AI Platform Core`

## Deep features applied

- sandbox execution
- file storage
- component gallery
- permissions
- package allowlist
- workspace sharing
- version history
- embedding API

## Customization controls

- `execution_mode` — Execution mode (select)
- `runtime_limits` — runtime limits (text)
- `allowed_packages` — allowed packages (text)
- `auth_provider` — auth provider (text)
- `storage_backend` — storage backend (text)
- `tenant_policy` — tenant policy (text)
- `branding` — branding (text)
- `execution_timeout` — execution timeout (text)
- `output_format` — output format (select)
- `language` — language (select)
- `privacy_mode` — privacy mode (select)
- `confidence_threshold` — Confidence threshold (slider)

## Input fields

- `ai_generated_artifacts` — AI-generated artifacts (text) required
- `work_brief` — Work brief / source text / URL / instructions (textarea) required

## External data policy

The local deterministic core is real and executable. Live external systems are not simulated. If Shopify, ATS, ERP, OCR/STT, maps, SERP, market data, medical databases, tax/customs databases, or other live systems are required, this project reports the missing connector/API requirement instead of inventing data.

---

## Final UX/UI Layer

This project now uses the **AI Platform Control Plane** pattern.

**UX workflow:** Provider/tool intake → routing/security → execution → audit/export

**Domain components:**
- Provider routing matrix
- Tool registry
- Cost/billing controls
- Security settings
- Audit trail

**Quick actions:**
- Configure providers
- Review routing rules
- Check security controls
- Export audit package

**No fake-data policy:** external/live actions require real connectors or API keys. Missing connectors are reported instead of simulated.
