export function extractArtifact(text: string, type: string): string {
  const tagMatch = text.match(/<artifact[^>]*>([\s\S]*?)<\/artifact>/i);
  if (tagMatch) return tagMatch[1].trim();
  const codeMatch = text.match(/```(?:jsx?|tsx?|html|svg)?\n([\s\S]*?)```/);
  if (codeMatch) return codeMatch[1].trim();
  return text.trim();
}
