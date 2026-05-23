import { mkdirSync, writeFileSync, readFileSync, existsSync, readdirSync, unlinkSync } from "fs";
import { join } from "path";
import { StorageAdapter, ArtifactRecord } from "./adapter.js";

export class LocalStorage implements StorageAdapter {
  constructor(private dir: string) { mkdirSync(dir, { recursive: true }); }
  async save(a: ArtifactRecord) { writeFileSync(join(this.dir, `${a.id}.json`), JSON.stringify(a)); }
  async get(id: string) {
    const p = join(this.dir, `${id}.json`);
    return existsSync(p) ? JSON.parse(readFileSync(p, "utf-8")) : null;
  }
  async list(limit: number, offset: number) {
    return readdirSync(this.dir).filter(f => f.endsWith(".json"))
      .sort().reverse().slice(offset, offset + limit)
      .map(f => JSON.parse(readFileSync(join(this.dir, f), "utf-8")));
  }
  async delete(id: string) { const p = join(this.dir, `${id}.json`); if (existsSync(p)) unlinkSync(p); }
}
