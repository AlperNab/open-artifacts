from __future__ import annotations
import json
from pathlib import Path
from functools import lru_cache
from .schemas import ProjectSpec
PLUGIN_DIR = Path(__file__).resolve().parents[1] / 'plugins'
@lru_cache(maxsize=1)
def load_projects() -> list[ProjectSpec]:
    projects=[]
    for path in sorted(PLUGIN_DIR.glob('*.json')):
        if path.name == 'projects_index.json':
            continue
        projects.append(ProjectSpec(**json.loads(path.read_text(encoding='utf-8'))))
    return sorted(projects, key=lambda p: (p.domain, p.name))
@lru_cache(maxsize=None)
def get_project(slug: str) -> ProjectSpec | None:
    return next((p for p in load_projects() if p.slug==slug), None)
def project_domains() -> dict[str, list[dict]]:
    out={}
    for p in load_projects():
        out.setdefault(p.domain,[]).append({'slug':p.slug,'name':p.name,'core_job':p.core_job})
    return out
