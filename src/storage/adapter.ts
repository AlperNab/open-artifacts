export interface ArtifactRecord {
  id: string; type: string; prompt: string; model: string;
  raw_response: string; html: string; created_at: string;
}
export interface StorageAdapter {
  save(a: ArtifactRecord): Promise<void>;
  get(id: string): Promise<ArtifactRecord | null>;
  list(limit: number, offset: number): Promise<ArtifactRecord[]>;
  delete(id: string): Promise<void>;
}
