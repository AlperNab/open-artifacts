from __future__ import annotations
import os
from pathlib import Path
from cryptography.fernet import Fernet
KEY_FILE = Path('./data/secret.key')
def _load_key() -> bytes:
    env=os.getenv('AI_SUITE_SECRET_KEY','').strip()
    if env: return env.encode()
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    if KEY_FILE.exists(): return KEY_FILE.read_bytes().strip()
    key=Fernet.generate_key(); KEY_FILE.write_bytes(key)
    try: KEY_FILE.chmod(0o600)
    except Exception: pass
    return key
fernet=Fernet(_load_key())
def encrypt_secret(value: str | None) -> str | None:
    return fernet.encrypt(value.encode()).decode() if value else None
def decrypt_secret(value: str | None) -> str | None:
    return fernet.decrypt(value.encode()).decode() if value else None
def mask_secret(value: str | None) -> str | None:
    if not value: return None
    return '••••' if len(value)<=8 else value[:4]+'••••'+value[-4:]
