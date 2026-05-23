export const ARTIFACT_SYSTEM_PROMPT = `You are an expert developer generating self-contained interactive artifacts.

CRITICAL RULES:
- Output ONLY the code inside <artifact> tags
- The artifact must be completely self-contained
- For React: use hooks freely, React/ReactDOM available globally, export default function App
- For HTML: include all CSS and JS inline
- Use Tailwind CSS for React (CDN available)
- Make it visually polished and fully functional

Format:
<artifact type="react|html|svg|mermaid|markdown">
[CODE]
</artifact>`;

export function buildUserPrompt(prompt: string, type: string): string {
  const hints: Record<string, string> = {
    react: "Build as a React component. Export a default function called App.",
    html: "Build as a complete HTML page with inline CSS and JavaScript.",
    svg: "Create as SVG. Output only the <svg> element.",
    mermaid: "Create as Mermaid diagram. Output only the diagram definition.",
    markdown: "Write as Markdown.",
  };
  return `${prompt}\n\n${hints[type] ?? ""}`;
}
