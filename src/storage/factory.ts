import { StorageAdapter } from "./adapter.js";
import { LocalStorage } from "./local.js";
export function createStorage(): StorageAdapter {
  return new LocalStorage(process.env.STORAGE_PATH ?? "./artifacts");
}
