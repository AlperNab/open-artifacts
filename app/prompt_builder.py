from __future__ import annotations
import json
from .schemas import ProjectSpec

SYSTEM_BASE = 'You are a senior domain operator inside an AI business application. Execute the selected project workflow seriously and practically.\nRules:\n- Use only the user input, uploaded file text, and clearly marked assumptions.\n- Do not fabricate facts, citations, laws, prices, medical claims, financial claims, security exploit details, or source evidence.\n- For legal, medical, finance, hiring, security, and compliance outputs, include a human-review warning and confidence/uncertainty notes.\n- Return a polished, structured deliverable that a user can export.\n- Apply the project-specific workflow, features, customization, UI panels, and output format below.\n'

def build_prompt(project: ProjectSpec, inputs: dict, customization: dict, file_contexts: list[dict], output_style: str, engine_result: dict | None = None) -> list[dict]:
    uploaded_text = []
    for f in file_contexts:
        text = (f.get('extracted_text') or '')[:50000]
        uploaded_text.append(f"FILE: {f.get('original_name')}\n{text}")
    project_spec = {
        'slug': project.slug,
        'name': project.name,
        'domain': project.domain,
        'target_user': project.target_user,
        'core_job': project.core_job,
        'deep_features_to_apply': project.deep_features,
        'workflow_steps': project.workflow_steps,
        'ui_panels_to_support': project.ui_panels,
        'required_outputs': project.output_formats,
        'guardrails': project.guardrails,
        'suite': getattr(project, 'suite', 'General Automation Suite'),
        'analysis_modules': getattr(project, 'analysis_modules', []),
        'scorecards': getattr(project, 'scorecards', []),
        'output_sections': getattr(project, 'output_sections', []),
    }
    system = SYSTEM_BASE + '\nPROJECT SPECIFICATION:\n' + json.dumps(project_spec, ensure_ascii=False, indent=2)
    user = {
        'inputs': inputs,
        'customization': customization,
        'uploaded_files': uploaded_text,
        'deterministic_domain_engine_result': engine_result or {},
        'requested_output_style': output_style,
        'deliverable_requirements': [
            'Start with a one-paragraph executive result based on the deterministic engine and source evidence.',
            'Then provide domain-specific sections matching the workflow.',
            'Include extracted tables/checklists where useful.',
            'Include validation warnings, risks, missing information, and next actions.',
            'End with export-ready summary data in a compact JSON block.',
            'Do not overwrite deterministic warnings; refine and expand them with clear uncertainty notes.'
        ]
    }
    return [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': json.dumps(user, ensure_ascii=False, indent=2)}
    ]
