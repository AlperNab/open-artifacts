from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.plugin_loader import load_projects
from app.domain_engine import PROJECT_IMPLEMENTATIONS

def test_single_project_registered():
    projects = load_projects()
    assert len(projects) == 1
    assert projects[0].slug in PROJECT_IMPLEMENTATIONS
