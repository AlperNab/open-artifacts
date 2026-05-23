# open-artifacts

> **Self-hosted Claude artifacts runtime.** Embed Claude's artifact execution environment in your own app — with your own API key, your own domain, your own storage. No claude.ai required.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Node](https://img.shields.io/badge/Node.js-18%2B-339933?style=flat&logo=node.js)](https://nodejs.org)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat&logo=docker)](https://docker.com)

Claude artifacts are powerful — interactive React apps, SVG diagrams, HTML tools — but they're locked to claude.ai. This project is the open-source runtime that lets anyone run them anywhere.

## What you get

```
claude.ai artifacts            open-artifacts
──────────────────────         ──────────────────────────────
✓ Runs Claude                  ✓ Runs Claude (your API key)
✓ Renders artifacts            ✓ Renders artifacts
✗ Your domain                  ✓ Your domain
✗ Your storage                 ✓ Your storage (S3, local, DB)
✗ Your branding                ✓ Your branding
✗ Embeddable                   ✓ Embeddable anywhere (iframe)
✗ API access                   ✓ Full REST API
✗ Custom system prompts        ✓ Custom system prompts
✗ User management              ✓ Bring your own auth
```

## Quickstart

### Docker (fastest)

```bash
docker run -p 3000:3000 \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  ghcr.io/alpernab/open-artifacts:latest
```

Open `http://localhost:3000` — full artifact runtime running locally.

### npm

```bash
npm install -g open-artifacts
open-artifacts serve --api-key sk-ant-xxx --port 3000
```

### Self-hosted with config

```bash
git clone https://github.com/AlperNab/open-artifacts
cd open-artifacts
cp .env.example .env
# Edit .env with your API key and storage config
npm install && npm run build && npm start
```

## Embedding in your app

```html
<!-- Drop into any HTML page -->
<iframe
  src="https://your-artifacts-instance.com/embed"
  width="100%"
  height="600px"
  allow="clipboard-write"
/>
```

```javascript
// Or use the JS SDK
import { ArtifactsClient } from 'open-artifacts-sdk';

const client = new ArtifactsClient({ 
  host: 'https://your-artifacts-instance.com' 
});

// Generate and render an artifact
const artifact = await client.create({
  prompt: 'Build a BMI calculator with a dark theme',
  type: 'react',
  systemPrompt: 'You are a UI designer. Always use Tailwind classes.',
});

// artifact.url — shareable link
// artifact.html — raw rendered HTML (for iframe src=blob:)
```

## REST API

```bash
# Create an artifact
POST /api/artifacts
{
  "prompt": "Create a sortable data table with mock sales data",
  "type": "react",         // react | html | svg | markdown | mermaid
  "system_prompt": "...",  // optional
  "model": "claude-sonnet-4-20250514"
}

# Response
{
  "id": "art_abc123",
  "url": "https://your-host.com/a/art_abc123",
  "type": "react",
  "created_at": "2025-05-22T...",
  "html": "<!DOCTYPE html>..."
}

# Get artifact
GET /api/artifacts/:id

# List artifacts
GET /api/artifacts?limit=20&offset=0

# Update (regenerate with new prompt)
PUT /api/artifacts/:id
{ "prompt": "Add a dark mode toggle" }

# Delete
DELETE /api/artifacts/:id
```

## Configuration

```env
# Required
ANTHROPIC_API_KEY=sk-ant-xxx

# Server
PORT=3000
HOST=0.0.0.0
BASE_URL=https://your-domain.com   # for shareable links

# Storage (pick one)
STORAGE=local                       # files saved to ./artifacts/
STORAGE=s3                          # AWS S3
STORAGE=postgres                    # PostgreSQL

# S3 config (if STORAGE=s3)
AWS_BUCKET=your-bucket
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=xxx
AWS_SECRET_ACCESS_KEY=xxx

# Postgres (if STORAGE=postgres)
DATABASE_URL=postgresql://...

# Auth (optional — leave blank for open access)
AUTH_SECRET=your-secret             # signs session tokens
ALLOWED_ORIGINS=https://app.example.com,https://dashboard.example.com

# Model defaults
DEFAULT_MODEL=claude-sonnet-4-20250514
MAX_TOKENS=8192
```

## Supported artifact types

| Type | Description | Example |
|------|-------------|---------|
| `react` | React components (JSX + hooks) | Dashboards, calculators, games |
| `html` | Full HTML with JS and CSS | Landing pages, tools |
| `svg` | SVG diagrams and illustrations | Flowcharts, icons, art |
| `mermaid` | Mermaid diagrams | ERDs, sequence diagrams |
| `markdown` | Rendered markdown | Reports, documentation |

## Features

- **Streaming** — artifact content streams to the browser as Claude generates it
- **Shareable links** — every artifact gets a permanent URL
- **Version history** — regenerate with a follow-up prompt, keep the history
- **Storage backends** — local filesystem, S3, or PostgreSQL
- **CORS control** — whitelist which origins can embed your runtime
- **Rate limiting** — per-IP and per-API-key limits
- **Custom system prompts** — define per-app behavior and constraints
- **Execution sandbox** — artifacts run in a sandboxed iframe, no access to parent page

## Architecture

```
Browser
  └── ArtifactViewer (React)
        ├── GeneratePanel — prompt input, model selection
        ├── StreamingRenderer — SSE stream → live preview
        └── Sandbox iframe — isolated artifact execution

Server (Express)
  ├── POST /api/artifacts → Claude API (streaming)
  ├── GET  /api/artifacts/:id → storage lookup
  ├── static /a/:id → serve artifact HTML
  └── Storage adapter (local | S3 | postgres)
```

## License

MIT © [Alper Nabil Gabra Zakher](https://github.com/AlperNab)

---

<div align="center">

**Claude artifacts, everywhere.**

⭐ Star if you've ever wanted to embed Claude artifacts in your own product

</div>
