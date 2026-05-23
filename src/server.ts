/**
 * open-artifacts — server entry point
 * Express API + static artifact serving + Claude streaming
 */
import express from "express";
import cors from "cors";
import { randomUUID } from "crypto";
import Anthropic from "@anthropic-ai/sdk";
import { StorageAdapter } from "./storage/adapter.js";
import { createStorage } from "./storage/factory.js";
import { ARTIFACT_SYSTEM_PROMPT, buildUserPrompt } from "./runtime/prompts.js";
import { extractArtifact } from "./runtime/extractor.js";

const app = express();
const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
const storage: StorageAdapter = createStorage();

const PORT = parseInt(process.env.PORT ?? "3000");
const BASE_URL = process.env.BASE_URL ?? `http://localhost:${PORT}`;
const DEFAULT_MODEL = process.env.DEFAULT_MODEL ?? "claude-sonnet-4-20250514";
const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGINS ?? "*").split(",");

app.use(cors({ origin: ALLOWED_ORIGINS }));
app.use(express.json({ limit: "1mb" }));
app.use(express.static("public"));

// ── Create artifact (streaming) ───────────────────────────────────────────────
app.post("/api/artifacts", async (req, res) => {
  const {
    prompt,
    type = "react",
    system_prompt,
    model = DEFAULT_MODEL,
    max_tokens = 8192,
    conversation = [],
  } = req.body;

  if (!prompt) return res.status(400).json({ error: "prompt is required" });

  const id = `art_${randomUUID().replace(/-/g, "").slice(0, 12)}`;
  const systemPrompt = system_prompt
    ? `${ARTIFACT_SYSTEM_PROMPT}\n\n${system_prompt}`
    : ARTIFACT_SYSTEM_PROMPT;

  // Set up SSE streaming
  res.setHeader("Content-Type", "text/event-stream");
  res.setHeader("Cache-Control", "no-cache");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Artifact-Id", id);

  const send = (event: string, data: unknown) => {
    res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`);
  };

  send("start", { id, type });

  try {
    const messages: Anthropic.MessageParam[] = [
      ...conversation,
      { role: "user", content: buildUserPrompt(prompt, type) },
    ];

    let fullText = "";

    const stream = await client.messages.stream({
      model,
      max_tokens,
      system: systemPrompt,
      messages,
    });

    for await (const chunk of stream) {
      if (chunk.type === "content_block_delta" && chunk.delta.type === "text_delta") {
        fullText += chunk.delta.text;
        send("delta", { text: chunk.delta.text });
      }
    }

    // Extract the artifact HTML/code from Claude's response
    const artifact = extractArtifact(fullText, type);
    const renderedHtml = renderArtifact(artifact, type, id);

    // Save to storage
    await storage.save({
      id,
      type,
      prompt,
      model,
      raw_response: fullText,
      html: renderedHtml,
      created_at: new Date().toISOString(),
    });

    send("done", {
      id,
      url: `${BASE_URL}/a/${id}`,
      type,
      html: renderedHtml,
    });

    res.end();
  } catch (error: any) {
    send("error", { message: error.message });
    res.end();
  }
});

// ── Get artifact ──────────────────────────────────────────────────────────────
app.get("/api/artifacts/:id", async (req, res) => {
  const artifact = await storage.get(req.params.id);
  if (!artifact) return res.status(404).json({ error: "Not found" });
  res.json(artifact);
});

// ── Serve artifact as standalone page ────────────────────────────────────────
app.get("/a/:id", async (req, res) => {
  const artifact = await storage.get(req.params.id);
  if (!artifact) return res.status(404).send("Artifact not found");
  res.setHeader("Content-Type", "text/html");
  res.send(artifact.html);
});

// ── List artifacts ────────────────────────────────────────────────────────────
app.get("/api/artifacts", async (req, res) => {
  const limit = parseInt(req.query.limit as string ?? "20");
  const offset = parseInt(req.query.offset as string ?? "0");
  const artifacts = await storage.list(limit, offset);
  res.json({ artifacts, limit, offset });
});

// ── Delete artifact ───────────────────────────────────────────────────────────
app.delete("/api/artifacts/:id", async (req, res) => {
  await storage.delete(req.params.id);
  res.json({ deleted: true });
});

// ── Render artifact into sandboxed HTML ───────────────────────────────────────
function renderArtifact(code: string, type: string, id: string): string {
  const sandboxAttrs = "allow-scripts allow-forms allow-popups";

  if (type === "html") {
    // Inject sandbox meta + artifact id
    return code.replace(
      "<head>",
      `<head>\n<meta name="artifact-id" content="${id}">`
    );
  }

  if (type === "react") {
    return `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="artifact-id" content="${id}">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/react/18.2.0/umd/react.production.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/react-dom/18.2.0/umd/react-dom.production.min.js"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/babel-standalone/7.23.5/babel.min.js"></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>body{margin:0;padding:0;font-family:system-ui,sans-serif}</style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
    ${code}
    
    // Mount the default export or App component
    const Component = typeof App !== 'undefined' ? App : (typeof module !== 'undefined' && module.exports) ? module.exports.default : null;
    if (Component) {
      ReactDOM.createRoot(document.getElementById('root')).render(React.createElement(Component));
    }
  </script>
</body>
</html>`;
  }

  if (type === "svg") {
    return `<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>
  body{margin:0;display:flex;align-items:center;justify-content:center;min-height:100vh;background:#f8f9fa}
  svg{max-width:100%;max-height:100vh}
</style></head><body>${code}</body></html>`;
  }

  if (type === "mermaid") {
    return `<!DOCTYPE html>
<html><head><meta charset="UTF-8">
  <script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
</head><body style="padding:20px;font-family:system-ui">
  <div class="mermaid">${code}</div>
  <script>mermaid.initialize({startOnLoad:true,theme:'default'})</script>
</body></html>`;
  }

  // markdown
  return `<!DOCTYPE html>
<html><head><meta charset="UTF-8">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/github-markdown-css/5.5.1/github-markdown-light.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.0/marked.min.js"></script>
  <style>body{max-width:800px;margin:40px auto;padding:0 20px}</style>
</head><body class="markdown-body">
  <script>document.body.innerHTML = marked.parse(${JSON.stringify(code)})</script>
</body></html>`;
}

app.listen(PORT, () => {
  console.log(`open-artifacts running at ${BASE_URL}`);
  console.log(`Storage: ${process.env.STORAGE ?? "local"}`);
});
