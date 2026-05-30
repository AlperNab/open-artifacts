from __future__ import annotations

import csv
import difflib
import io
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlparse

from .schemas import ProjectSpec

# -----------------------------------------------------------------------------
# Real deterministic project engine
# -----------------------------------------------------------------------------
# This module intentionally does not fabricate external facts. Every project has
# a registered implementation. When a live API/database is needed, the output
# reports the missing connector instead of inventing data.

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s)\]>'\"]+|www\.[^\s)\]>'\"]+", re.I)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)")
DATE_RE = re.compile(r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b", re.I)
MONEY_RE = re.compile(r"(?i)(USD|EUR|GBP|EGP|AED|SAR|USDT|\$|€|£|ج\.م|د\.إ|ر\.س)?\s*([-+]?\d[\d,]*(?:\.\d+)?)\s*(USD|EUR|GBP|EGP|AED|SAR|USDT)?")
PERCENT_RE = re.compile(r"[-+]?\d+(?:\.\d+)?\s?%")
NUMBER_RE = re.compile(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?")
CODE_BLOCK_RE = re.compile(r"```([A-Za-z0-9_+-]*)\n([\s\S]*?)```")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")

STOP = {
    'the','and','for','with','that','this','from','your','you','are','was','will','have','has','not','but','can','all','any','use','our','their','there','into','about','what','when','where','which','shall','must','may','per','page','file','text','data','a','an','of','to','in','on','as','by','or','be','is','it','at','we','i','he','she','they','them','his','her','its','than','then'
}

LEGAL_CLAUSES = {
    'Confidentiality': ['confidential', 'non-disclosure', 'proprietary', 'trade secret'],
    'Term and termination': ['termination', 'terminate', 'expiry', 'expiration', 'term of this agreement'],
    'Liability cap': ['limitation of liability', 'liability cap', 'aggregate liability', 'consequential damages'],
    'Indemnity': ['indemnify', 'indemnification', 'hold harmless'],
    'IP ownership': ['intellectual property', 'copyright', 'patent', 'ownership', 'work product'],
    'Governing law': ['governing law', 'jurisdiction', 'venue', 'court'],
    'Assignment': ['assign', 'assignment', 'transfer this agreement'],
    'Auto renewal': ['renewal', 'auto-renew', 'automatic renewal'],
    'Payment': ['invoice', 'payment', 'late fee', 'tax', 'fees'],
    'Data processing': ['personal data', 'processor', 'controller', 'data protection', 'gdpr', 'ccpa'],
}

SECRET_PATTERNS = {
    'AWS access key': re.compile(r'AKIA[0-9A-Z]{16}'),
    'Google API key': re.compile(r'AIza[0-9A-Za-z_\-]{35}'),
    'Slack token': re.compile(r'xox[baprs]-[0-9A-Za-z-]{10,}'),
    'GitHub token': re.compile(r'gh[pousr]_[A-Za-z0-9_]{30,}'),
    'Stripe key': re.compile(r'(?:sk|pk)_(?:live|test)_[0-9a-zA-Z]{20,}'),
    'Private key block': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----'),
    'Generic assignment secret': re.compile(r'(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*["\']?([A-Za-z0-9_\-./+=]{12,})'),
}

DRUG_RULES = [
    (('warfarin','aspirin'), 'Major bleeding risk', 'Avoid combination or monitor INR/bleeding closely under clinician supervision.'),
    (('warfarin','ibuprofen'), 'Major bleeding risk', 'Avoid NSAID use unless clinician-approved; monitor bleeding and INR.'),
    (('sildenafil','nitroglycerin'), 'Contraindicated hypotension risk', 'Do not combine PDE5 inhibitors with nitrates.'),
    (('spironolactone','lisinopril'), 'Hyperkalemia risk', 'Monitor potassium and renal function.'),
    (('spironolactone','losartan'), 'Hyperkalemia risk', 'Monitor potassium and renal function.'),
    (('clarithromycin','simvastatin'), 'Myopathy/rhabdomyolysis risk', 'Consider holding statin or choosing alternative antibiotic/statin.'),
    (('sertraline','tramadol'), 'Serotonin syndrome/seizure risk', 'Avoid or monitor closely; consider alternative analgesic.'),
    (('metformin','contrast'), 'Renal/lactic acidosis precaution', 'Follow renal-function and contrast protocols.'),
]

EMISSION_FACTORS = {
    # Conservative built-in defaults for rough internal estimates only. Final reports
    # should load country/year-specific factors from a real configured factor table.
    'electricity_kwh': 0.4,
    'gasoline_liter': 2.31,
    'diesel_liter': 2.68,
    'natural_gas_m3': 2.0,
    'flight_km': 0.15,
    'truck_km': 0.62,
}

PROJECT_IMPLEMENTATIONS: dict[str, dict[str, Any]] = {
    'ad-copy-generator': {'workflow':'Marketing / Ads', 'algorithms':['claims_check','marketing_variants','compliance_review'], 'connectors':[], 'outputs':['Ad variants','Angle matrix','Claims risk','A/B test plan']},
    'api-doc-generator': {'workflow':'Developer / API', 'algorithms':['api_doc','code_inventory','developer_review'], 'connectors':[], 'outputs':['Endpoint inventory','Auth notes','Examples','OpenAPI gaps']},
    'bank-statement-normalizer': {'workflow':'Finance / Accounting', 'algorithms':['transaction_parser','finance_reconciliation'], 'connectors':[], 'outputs':['Normalized transactions','Category suggestions','Anomalies','Export CSV']},
    'candidate-scorer': {'workflow':'HR / Recruiting', 'algorithms':['resume_parse','candidate_match','fair_hiring_guardrails'], 'connectors':['ATS optional'], 'outputs':['Fit score','Skill matrix','Interview focus','Risk notes']},
    'carbon-footprint-api': {'workflow':'ESG / Sustainability', 'algorithms':['carbon_calc','esg_review'], 'connectors':['Country/year emission-factor database optional'], 'outputs':['Scope map','CO2e estimates','Missing factor warnings','Evidence table']},
    'clause-extractor': {'workflow':'Legal / Contract Review', 'algorithms':['legal_clause_scan','obligation_calendar','risk_register'], 'connectors':[], 'outputs':['Clause table','Risk register','Obligations','Negotiation notes']},
    'clinical-note-parser': {'workflow':'Medical / Healthcare Data', 'algorithms':['clinical_extract','phi_scan','coding_candidates'], 'connectors':['FHIR/EHR optional','ICD/SNOMED/RxNorm optional'], 'outputs':['SOAP sections','Problem/medication list','PHI warnings','Coding candidates']},
    'code-review-bot': {'workflow':'Developer / Code Quality', 'algorithms':['code_inventory','code_review','secret_scan'], 'connectors':['GitHub/GitLab optional'], 'outputs':['Review comments','Risk findings','Suggested tests','Merge checklist']},
    'code-tutor-api': {'workflow':'Education / Coding', 'algorithms':['code_inventory','learning_diagnosis','exercise_builder'], 'connectors':[], 'outputs':['Explanation','Mistake diagnosis','Next exercises','Rubric']},
    'competitor-intel-ai': {'workflow':'Business / Competitive Intelligence', 'algorithms':['url_inventory','positioning_extract','gap_matrix'], 'connectors':['HTTP fetch/Browser/SerpAPI optional'], 'outputs':['Positioning','Pricing clues','Feature gaps','Battlecard']},
    'contract-diff': {'workflow':'Legal / Contract Ops', 'algorithms':['text_diff','legal_clause_scan','risk_register'], 'connectors':[], 'outputs':['Semantic diff','Changed clauses','Risk delta','Negotiation checklist']},
    'crypto-portfolio-analyzer': {'workflow':'Finance / Crypto Portfolio', 'algorithms':['portfolio_parser','concentration_risk','finance_risk'], 'connectors':['Exchange/price feed optional'], 'outputs':['Holdings table','Concentration','Cost/risk notes','Rebalance checklist']},
    'customs-doc-classifier': {'workflow':'Supply Chain / Customs', 'algorithms':['supply_doc_parse','hs_candidate_rules','compliance_review'], 'connectors':['Customs/tariff database required for final HS/duty'], 'outputs':['Document class','Line items','HS candidates','Broker review list']},
    'cv-parser-api': {'workflow':'HR / Resume Parsing', 'algorithms':['resume_parse','skills_extract','contact_extract'], 'connectors':[], 'outputs':['Candidate JSON','Skills','Experience timeline','Missing fields']},
    'data-quality-checker': {'workflow':'Data Engineering', 'algorithms':['csv_profile','data_quality_rules'], 'connectors':['Database optional'], 'outputs':['Profile','Null/duplicate report','Type issues','Fix plan']},
    'delivery-note-parser': {'workflow':'Supply Chain / Warehouse', 'algorithms':['supply_doc_parse','quantity_check'], 'connectors':['ERP/WMS optional'], 'outputs':['Delivery note fields','Received items','Mismatch flags','GRN export']},
    'dropship-radar': {'workflow':'E-commerce / Product Research', 'algorithms':['product_opportunity','margin_calc','claims_check'], 'connectors':['Marketplace/supplier/ad library APIs optional'], 'outputs':['Opportunity score','Margin table','Risk flags','Launch queue']},
    'drug-interaction-api': {'workflow':'Medical / Medication Safety', 'algorithms':['drug_interaction_screen','clinical_context','phi_scan'], 'connectors':['RxNorm/RxNav/OpenFDA/full interaction DB required for clinical completeness'], 'outputs':['Interaction matrix','Severity','Monitoring plan','Clinical review warning']},
    'email-sequence-writer': {'workflow':'Marketing / Lifecycle Email', 'algorithms':['email_sequence','claims_check','compliance_review'], 'connectors':[], 'outputs':['Email sequence','Subject lines','Personalization tokens','Compliance flags']},
    'esg-report-parser': {'workflow':'ESG / Report Parsing', 'algorithms':['esg_metric_extract','evidence_map'], 'connectors':['Framework/factor database optional'], 'outputs':['ESG metrics','Scope mapping','Evidence table','Assurance gaps']},
    'expense-categorizer': {'workflow':'Finance / Expense Ops', 'algorithms':['transaction_parser','expense_rules','finance_reconciliation'], 'connectors':['Accounting software optional'], 'outputs':['Categorized expenses','Policy flags','Tax hints','Export table']},
    'financial-report-parser': {'workflow':'Finance / Equity Research', 'algorithms':['financial_metric_extract','ratio_calc','risk_register'], 'connectors':['Market data optional'], 'outputs':['Financial metrics','Ratios','Risk factors','Questions']},
    'flashcard-factory': {'workflow':'Education / Study Tools', 'algorithms':['flashcard_generate','learning_objectives'], 'connectors':[], 'outputs':['Cards','Cloze deletions','Difficulty tags','Study plan']},
    'gemini-audio-transcriber': {'workflow':'Media / Transcription', 'algorithms':['transcript_structure','speaker_segment'], 'connectors':['Gemini/Whisper/local STT required for raw audio'], 'outputs':['Transcript structure','Speaker notes','Chapters','Export formats']},
    'green-claims-checker': {'workflow':'ESG / Marketing Compliance', 'algorithms':['green_claims_review','claims_check','evidence_map'], 'connectors':['Regulatory reference library optional'], 'outputs':['Claim risk','Required evidence','Rewrite suggestions','Approval checklist']},
    'incident-report-gen': {'workflow':'Ops / Incident Management', 'algorithms':['incident_timeline','root_cause_hypotheses','action_tracker'], 'connectors':['PagerDuty/Jira/Slack optional'], 'outputs':['Incident report','Timeline','Impact','Corrective actions']},
    'interview-question-gen': {'workflow':'HR / Interviewing', 'algorithms':['jd_parse','interview_kit','fair_hiring_guardrails'], 'connectors':[], 'outputs':['Question bank','Rubric','Panel guide','Bias guardrails']},
    'invoice-ai': {'workflow':'Finance / Accounts Payable', 'algorithms':['invoice_extract','tax_check','po_match','finance_reconciliation'], 'connectors':['ERP/accounting optional','Tax/VAT database optional','OCR vision optional'], 'outputs':['Invoice fields','Tax validation','PO mismatch','Approval route']},
    'job-description-optimizer': {'workflow':'HR / Hiring Marketing', 'algorithms':['jd_parse','inclusive_language','role_scorecard'], 'connectors':[], 'outputs':['Optimized JD','Requirements audit','Comp/benefit checklist','Bias flags']},
    'launch-kit': {'workflow':'Startup / GTM', 'algorithms':['launch_assets','marketing_variants','roadmap_builder'], 'connectors':[], 'outputs':['Launch plan','Messaging','Channels','Assets']},
    'lease-analyzer': {'workflow':'Legal / Real Estate', 'algorithms':['legal_clause_scan','lease_terms','risk_register'], 'connectors':[], 'outputs':['Lease terms','Tenant/landlord risks','Dates/fees','Action list']},
    'listing-writer': {'workflow':'E-commerce / Product Content', 'algorithms':['listing_builder','claims_check','seo_terms'], 'connectors':['Shopify/Amazon/eBay optional'], 'outputs':['Title','Bullets','Description','SEO fields']},
    'llm-billing-engine': {'workflow':'Platform / Billing', 'algorithms':['llm_usage_meter','invoice_calc','budget_guard'], 'connectors':['Stripe/accounting optional'], 'outputs':['Usage table','Cost calculation','Budget alerts','Invoice lines']},
    'log-anomaly-detector': {'workflow':'DevOps / Observability', 'algorithms':['log_parse','anomaly_detect','root_cause_hypotheses'], 'connectors':['Datadog/CloudWatch/Grafana optional'], 'outputs':['Anomalies','Timeline','Likely causes','Runbook links']},
    'mcp-composer': {'workflow':'AI Platform / Agents', 'algorithms':['mcp_tool_parse','approval_policy','agent_flow'], 'connectors':['MCP servers/tools configured by user'], 'outputs':['Tool inventory','Workflow graph','Risk gates','Config JSON']},
    'medical-literature-ai': {'workflow':'Medical / Research', 'algorithms':['pico_extract','study_table','evidence_grade'], 'connectors':['PubMed/Crossref/semantic scholar optional'], 'outputs':['PICO','Study table','Evidence grade','Search strategy']},
    'model-router': {'workflow':'AI Platform / Routing', 'algorithms':['routing_decision','budget_guard','privacy_gate'], 'connectors':['Provider health endpoints optional'], 'outputs':['Model choice','Fallback chain','Cost/risk estimate','Routing rules']},
    'mortgage-doc-analyzer': {'workflow':'Finance / Mortgage', 'algorithms':['mortgage_terms','fee_extract','risk_register'], 'connectors':['Rate/credit bureau systems optional'], 'outputs':['Loan terms','Fees','APR/escrow questions','Risk list']},
    'nda-analyzer': {'workflow':'Legal / NDA Review', 'algorithms':['legal_clause_scan','nda_risk','negotiation_notes'], 'connectors':[], 'outputs':['NDA risk','Clause comments','Negotiation fallback','Obligations']},
    'neighborhood-report-ai': {'workflow':'Real Estate / Location Intelligence', 'algorithms':['address_parse','local_data_requirements','weighted_scorecard'], 'connectors':['Maps/geocoding/school/crime/flood/transport APIs required for live facts'], 'outputs':['Data requirement map','Priority scorecard','Known inputs','Connector gaps']},
    'offer-letter-generator': {'workflow':'HR / Legal Docs', 'algorithms':['offer_terms','legal_doc_builder','fair_hiring_guardrails'], 'connectors':[], 'outputs':['Offer letter','Comp table','Conditions','Review checklist']},
    'open-artifacts': {'workflow':'AI Platform / Artifact Runtime', 'algorithms':['artifact_runtime_spec','security_review','deployment_plan'], 'connectors':['Hosting/storage optional'], 'outputs':['Runtime config','Security checks','Deployment steps','Artifact manifest']},
    'paper-explainer': {'workflow':'Education / Research', 'algorithms':['paper_structure','plain_language_summary','flashcard_generate'], 'connectors':['DOI/PubMed/Crossref optional'], 'outputs':['Plain summary','Methods map','Limitations','Study cards']},
    'performance-review-ai': {'workflow':'HR / Performance', 'algorithms':['feedback_cluster','review_builder','fair_hiring_guardrails'], 'connectors':['HRIS optional'], 'outputs':['Review draft','Evidence clusters','Bias flags','Development plan']},
    'phishing-detector-api': {'workflow':'Cybersecurity / Email Safety', 'algorithms':['phishing_score','url_inventory','security_review'], 'connectors':['Safe Browsing/VirusTotal optional'], 'outputs':['Risk score','Indicators','User-safe explanation','Action']},
    'pipeline-debugger': {'workflow':'DevOps / CI/CD', 'algorithms':['log_parse','pipeline_failure','runbook_links'], 'connectors':['GitHub Actions/GitLab/Jenkins optional'], 'outputs':['Failure stage','Likely cause','Fix commands','Retry safety']},
    'podcast-show-notes': {'workflow':'Creator / Podcast Ops', 'algorithms':['transcript_structure','chapter_builder','social_snippets'], 'connectors':['STT provider optional'], 'outputs':['Show notes','Chapters','Clips','SEO metadata']},
    'privacy-policy-grader': {'workflow':'Legal / Privacy Compliance', 'algorithms':['privacy_policy_scan','legal_clause_scan','compliance_review'], 'connectors':['Regulatory reference library optional'], 'outputs':['Grade','Missing disclosures','Risk flags','Fix checklist']},
    'runbook-generator': {'workflow':'DevOps / SRE', 'algorithms':['service_inventory','runbook_builder','incident_timeline'], 'connectors':['Monitoring/CMDB optional'], 'outputs':['Runbook','Alerts','Rollback','Escalation']},
    'schema-documenter': {'workflow':'Data / Database Docs', 'algorithms':['schema_parse','data_dictionary','relationship_map'], 'connectors':['Database optional'], 'outputs':['Data dictionary','Relationships','Quality risks','Docs']},
    'secrets-scanner': {'workflow':'Security / DevSecOps', 'algorithms':['secret_scan','security_review'], 'connectors':['Git provider optional'], 'outputs':['Secret findings','Severity','Rotation plan','Ignore rules']},
    'seo-content-brief': {'workflow':'Marketing / SEO', 'algorithms':['seo_terms','content_brief','claims_check'], 'connectors':['SERP/keyword-volume provider optional'], 'outputs':['Brief','Outline','Internal links','SERP data gaps']},
    'shopify-mcp-server': {'workflow':'E-commerce / Shopify Ops', 'algorithms':['shopify_action_plan','approval_policy','mcp_tool_parse'], 'connectors':['Shopify Admin API required for live store actions'], 'outputs':['Action plan','Risk gates','Tool schema','API setup checklist']},
    'social-caption-engine': {'workflow':'Marketing / Social Media', 'algorithms':['social_captions','claims_check','content_calendar'], 'connectors':['Platform scheduler optional'], 'outputs':['Captions','Hashtag sets','CTA variants','Calendar']},
    'sql-from-english': {'workflow':'Data / Analytics', 'algorithms':['sql_builder','sql_guard','schema_parse'], 'connectors':['Database optional'], 'outputs':['Safe SQL','Assumptions','Risk flags','Test query']},
    'subtitle-generator': {'workflow':'Media / Subtitles', 'algorithms':['subtitle_from_text','speaker_segment','reading_speed_check'], 'connectors':['STT provider required for raw audio'], 'outputs':['SRT/VTT draft','Speaker map','Timing warnings','Translation notes']},
    'supplier-email-parser': {'workflow':'Supply Chain / Procurement', 'algorithms':['email_thread_parse','supply_doc_parse','po_match'], 'connectors':['Email/ERP optional'], 'outputs':['Supplier fields','Quote terms','PO actions','Follow-up email']},
    'tax-doc-parser': {'workflow':'Finance / Tax', 'algorithms':['tax_doc_classify','amount_extract','compliance_review'], 'connectors':['Country tax database/accounting optional'], 'outputs':['Tax fields','Document class','Missing info','Advisor checklist']},
    'test-generator': {'workflow':'Developer / QA', 'algorithms':['code_inventory','test_plan','edge_cases'], 'connectors':['Repo/CI optional'], 'outputs':['Test cases','Test file draft','Mocks','Coverage gaps']},
    'thumbnail-analyzer': {'workflow':'Creator / YouTube Design', 'algorithms':['thumbnail_critique_from_notes','visual_asset_requirements','marketing_variants'], 'connectors':['Vision model required for image-only analysis'], 'outputs':['CTR critique','Composition checklist','A/B concepts','Missing vision warning']},
    'tos-plain-english': {'workflow':'Legal / Consumer Rights', 'algorithms':['legal_clause_scan','plain_english_risks','consumer_rights'], 'connectors':[], 'outputs':['Plain summary','User risks','Opt-out actions','Clause map']},
    'universal-doc-parser': {'workflow':'Document AI / Finance Docs', 'algorithms':['doc_type_detect','key_value_extract','table_extract'], 'connectors':['OCR vision optional'], 'outputs':['Detected schema','Key-values','Tables','Confidence gaps']},
    'video-brief-writer': {'workflow':'Creator / Video Strategy', 'algorithms':['video_brief','chapter_builder','marketing_variants'], 'connectors':['Trend/URL fetch optional'], 'outputs':['Video brief','Hook structure','Shot list','Distribution plan']},
    'vulnerability-explainer': {'workflow':'Cybersecurity / AppSec', 'algorithms':['cve_parse','security_review','remediation_plan'], 'connectors':['NVD/GitHub advisory feed optional'], 'outputs':['Risk explanation','Affected surface','Fix plan','Verification steps']},
    'AlperNab': {'workflow':'General AI Utility / Repository', 'algorithms':['repo_readme_analyzer','project_inventory','action_tracker'], 'connectors':[], 'outputs':['Project summary','Detected purpose','Missing setup','Next actions']},
}

# ---------------------------- core utilities ---------------------------------

def _text_from(inputs: dict[str, Any], customization: dict[str, Any], file_contexts: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for k, v in inputs.items():
        if isinstance(v, (str, int, float, bool)) and str(v).strip():
            parts.append(f"INPUT {k}:\n{v}")
        elif isinstance(v, (list, dict)):
            parts.append(f"INPUT {k}:\n{json.dumps(v, ensure_ascii=False)}")
    for f in file_contexts:
        extracted = f.get('extracted_text') or ''
        parts.append(f"FILE {f.get('original_name','uploaded_file')}:\n{extracted[:200000]}")
    return "\n\n".join(parts).strip()


def _lines(text: str, min_len: int = 2) -> list[str]:
    return [" ".join(l.strip().split()) for l in re.split(r"[\r\n]+", text or '') if len(l.strip()) >= min_len]


def _sentences(text: str, min_len: int = 35, limit: int = 60) -> list[str]:
    flat = re.sub(r"\s+", " ", text or '').strip()
    if not flat:
        return []
    chunks = SENTENCE_RE.split(flat)
    return [c.strip()[:500] for c in chunks if len(c.strip()) >= min_len][:limit]


def _top_terms(text: str, n: int = 24) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_+.#/-]{2,}", text.lower())
    counts = Counter(w for w in words if w not in STOP and not w.isdigit())
    return [w for w, _ in counts.most_common(n)]


def _find_lines(text: str, terms: list[str], limit: int = 40) -> list[str]:
    if not terms:
        return _lines(text)[:limit]
    found: list[str] = []
    terms_l = [t.lower() for t in terms]
    for line in _lines(text, min_len=6):
        low = line.lower()
        if any(t in low for t in terms_l):
            found.append(line[:450])
        if len(found) >= limit:
            break
    return found


def _amounts(text: str) -> list[dict[str, Any]]:
    out = []
    for m in MONEY_RE.finditer(text or ''):
        symbol = (m.group(1) or m.group(3) or '').strip()
        raw = m.group(2).replace(',', '')
        try:
            val = float(raw)
        except Exception:
            continue
        if abs(val) > 0:
            out.append({'raw': m.group(0).strip(), 'currency_or_symbol': symbol, 'value': val})
    return out[:200]


def _numbers(text: str) -> list[float]:
    vals=[]
    for m in NUMBER_RE.finditer(text or ''):
        try: vals.append(float(m.group(0).replace(',','')))
        except Exception: pass
    return vals[:500]


def _basic_entities(text: str) -> dict[str, Any]:
    urls = URL_RE.findall(text or '')
    domains = []
    for u in urls:
        candidate = u if u.startswith('http') else 'http://' + u
        try:
            domains.append(urlparse(candidate).netloc.lower())
        except Exception:
            pass
    return {
        'emails': sorted(set(EMAIL_RE.findall(text or '')))[:50],
        'phones': sorted(set(PHONE_RE.findall(text or '')))[:50],
        'urls': sorted(set(urls))[:50],
        'domains': sorted(set(domains))[:50],
        'dates': sorted(set(DATE_RE.findall(text or '')))[:50],
        'percentages': sorted(set(PERCENT_RE.findall(text or '')))[:50],
        'amounts': _amounts(text)[:50],
        'top_terms': _top_terms(text, 30),
    }


def _csv_profile(text: str) -> dict[str, Any]:
    sample = "\n".join(_lines(text)[:200])
    if not sample or (',' not in sample and '\t' not in sample and ';' not in sample):
        return {'detected': False, 'reason': 'No delimited table detected in text.'}
    dialect = None
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',;\t|')
    except Exception:
        dialect = csv.excel
    rows=[]
    try:
        for row in csv.DictReader(io.StringIO(sample), dialect=dialect):
            rows.append(row)
            if len(rows)>=500: break
    except Exception:
        rows=[]
    if not rows:
        try:
            rows=[r for r in csv.reader(io.StringIO(sample), dialect=dialect)][:100]
        except Exception:
            rows=[]
    if rows and isinstance(rows[0], dict):
        cols=list(rows[0].keys())
        nulls={c:0 for c in cols}
        uniques={c:set() for c in cols}
        for r in rows:
            for c in cols:
                val=(r.get(c) or '').strip()
                if val=='': nulls[c]+=1
                uniques[c].add(val)
        return {'detected': True, 'rows_sampled': len(rows), 'columns': cols, 'null_counts': nulls, 'unique_counts': {c:len(v) for c,v in uniques.items()}}
    return {'detected': True, 'rows_sampled': len(rows), 'columns': [], 'raw_rows': rows[:5]}


def _readiness_score(result: dict[str, Any]) -> int:
    txt_len = result['input_summary']['source_character_count']
    evidence = sum(len(v) for k, v in result.get('tables', {}).items() if isinstance(v, list))
    warning_penalty = min(45, len(result.get('warnings', []))*7)
    score = 25 + min(35, txt_len // 800) + min(30, evidence // 2) - warning_penalty
    return max(0, min(100, int(score)))


def _required_missing(project: ProjectSpec, inputs: dict[str, Any], text: str) -> list[str]:
    missing=[]
    for f in project.input_schema:
        if getattr(f, 'required', False) and not str(inputs.get(f.key, '')).strip():
            missing.append(f.key)
    return missing


def _base(project: ProjectSpec, inputs: dict[str, Any], customization: dict[str, Any], file_contexts: list[dict[str, Any]]) -> tuple[dict[str, Any], str, dict[str, Any]]:
    if project.slug not in PROJECT_IMPLEMENTATIONS:
        raise RuntimeError(f"No real implementation is registered for project {project.slug}")
    cfg = PROJECT_IMPLEMENTATIONS[project.slug]
    text = _text_from(inputs, customization, file_contexts)
    entities = _basic_entities(text)
    missing = _required_missing(project, inputs, text)
    result = {
        'project': {
            'slug': project.slug,
            'name': project.name,
            'domain': project.domain,
            'suite': getattr(project, 'suite', cfg['workflow']),
            'workflow': cfg['workflow'],
            'core_job': project.core_job,
        },
        'implementation': {
            'status': 'real_local_engine_registered',
            'algorithms': cfg['algorithms'],
            'no_fake_data_policy': True,
            'external_connectors': cfg.get('connectors', []),
            'live_connector_status': [],
        },
        'execution': {
            'engine': 'registered_real_project_engine_v3',
            'ran_at': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
            'mode': customization.get('execution_mode', 'Production'),
        },
        'input_summary': {
            'input_keys': list(inputs.keys()),
            'customization_keys': list(customization.keys()),
            'uploaded_files': [f.get('original_name') for f in file_contexts],
            'source_character_count': len(text),
            **entities,
        },
        'validation': {
            'missing_required_inputs': missing,
            'field_rules': getattr(project, 'field_validations', []) or [],
            'ready_for_final_export': False,
        },
        'findings': [],
        'tables': {},
        'scorecards': {},
        'warnings': [],
        'action_items': [],
        'export_payload': {},
    }
    if missing:
        result['warnings'].append({'level':'high', 'issue':'Required inputs are missing.', 'evidence': missing})
    for c in cfg.get('connectors', []):
        result['implementation']['live_connector_status'].append(_connector_status(c))
    return result, text, cfg


def _connector_status(name: str) -> dict[str, Any]:
    mapping = {
        'Shopify Admin API required for live store actions': ['SHOPIFY_SHOP_DOMAIN', 'SHOPIFY_ADMIN_ACCESS_TOKEN'],
        'ERP/accounting optional': ['ERP_API_BASE_URL', 'ERP_API_KEY'],
        'Tax/VAT database optional': ['TAX_API_BASE_URL', 'TAX_API_KEY'],
        'OCR vision optional': ['VISION_PROVIDER_API_KEY'],
        'RxNorm/RxNav/OpenFDA/full interaction DB required for clinical completeness': ['RXNAV_BASE_URL or DRUG_DB_API_KEY'],
        'Maps/geocoding/school/crime/flood/transport APIs required for live facts': ['MAPS_API_KEY or GEOCODING_API_KEY'],
        'SERP/keyword-volume provider optional': ['SERPAPI_KEY or DATAFORSEO_LOGIN'],
        'HTTP fetch/Browser/SerpAPI optional': ['ALLOW_HTTP_FETCH or SERPAPI_KEY'],
        'NVD/GitHub advisory feed optional': ['NVD_API_KEY optional'],
        'Country/year emission-factor database optional': ['EMISSION_FACTOR_TABLE_PATH or CLIMATIQ_API_KEY'],
        'Customs/tariff database required for final HS/duty': ['CUSTOMS_TARIFF_API_KEY'],
        'Gemini/Whisper/local STT required for raw audio': ['GEMINI_API_KEY or WHISPER_SERVER_URL'],
        'STT provider required for raw audio': ['GEMINI_API_KEY or WHISPER_SERVER_URL'],
        'Vision model required for image-only analysis': ['VISION_PROVIDER_API_KEY'],
    }
    envs = mapping.get(name, [])
    configured = bool(envs) and any(os.getenv(e.split()[0]) for e in envs if e and ' or ' not in e)
    if ' or ' in ''.join(envs):
        configured = any(os.getenv(part.strip()) for e in envs for part in e.replace(' optional','').split(' or '))
    return {'connector': name, 'configured': configured, 'required_env': envs, 'behavior': 'real_api_when_configured_else_report_missing'}


def _add_table(result: dict[str, Any], name: str, rows: list[dict[str, Any]] | list[Any]):
    result['tables'][name] = rows


def _warning(result: dict[str, Any], level: str, issue: str, evidence: Any = None):
    result['warnings'].append({'level': level, 'issue': issue, 'evidence': evidence})


def _finding(result: dict[str, Any], typ: str, title: str, detail: str, **extra):
    item={'type':typ, 'title':title, 'detail':detail}
    item.update(extra)
    result['findings'].append(item)

# ---------------------------- algorithm implementations -----------------------

def run_algorithm(name: str, result: dict[str, Any], project: ProjectSpec, inputs: dict[str, Any], customization: dict[str, Any], text: str):
    fn = ALGORITHMS.get(name)
    if not fn:
        raise RuntimeError(f"Algorithm {name} is declared but not implemented")
    fn(result, project, inputs, customization, text)


def claims_check(result, project, inputs, customization, text):
    risky_terms=['best','guaranteed','guarantee','cure','risk-free','scientifically proven','number one','#1','instant','permanent','eco-friendly','zero emissions','free forever','no risk']
    lines=_find_lines(text, risky_terms, 30)
    _add_table(result, 'claim_risk_review', [{'claim_line':l, 'risk':'Needs evidence/substantiation before publishing'} for l in lines])
    if lines:
        _warning(result, 'medium', 'Potential advertising/compliance claims need proof.', lines[:10])
    _finding(result, 'claims_check', 'Claims substantiation scan', f'Checked {len(risky_terms)} risky claim patterns and found {len(lines)} evidence lines.', risky_terms_found=lines[:10])


def marketing_variants(result, project, inputs, customization, text):
    terms=_top_terms(text, 18)
    audience = inputs.get('target_audience') or inputs.get('audience') or customization.get('icp') or customization.get('audience persona') or 'target audience'
    offer = inputs.get('offer') or inputs.get('product') or inputs.get('work_brief') or project.name
    platform = customization.get('platform') or customization.get('ad_platform') or customization.get('output_format') or 'selected platform'
    variants=[]
    angles=[('Problem-aware', f'Stop wasting time on {terms[0] if terms else "the old way"}'), ('Outcome-led', f'Get a cleaner result for {audience}'), ('Proof-led', f'See why {terms[1] if len(terms)>1 else "users"} choose this'), ('Objection-handling', 'Built for people who need control, speed, and reliability')]
    for angle, hook in angles:
        variants.append({'angle': angle, 'platform': platform, 'hook': hook, 'body': f'Position {str(offer)[:120]} around the strongest user pain and a specific next action.', 'cta': 'Try it / Learn more', 'evidence_needed': 'Attach proof for measurable claims'})
    _add_table(result, 'marketing_variants', variants)
    _finding(result, 'marketing_strategy', 'Campaign variant builder', f'Built {len(variants)} structured variants using provided audience/offer/platform inputs.', audience=audience, top_terms=terms[:10])


def compliance_review(result, project, inputs, customization, text):
    domain=(project.domain+' '+project.slug).lower()
    rules=[]
    if any(k in domain for k in ['finance','tax','mortgage','crypto']):
        rules += ['No guaranteed returns.', 'Separate factual extraction from financial advice.', 'Require advisor review for tax/loan decisions.']
    if any(k in domain for k in ['medical','drug','clinical']):
        rules += ['Not medical advice.', 'Require clinician/pharmacist review.', 'De-identify PHI before cloud processing.']
    if any(k in domain for k in ['legal','contract','privacy','lease','nda','tos']):
        rules += ['Not legal advice.', 'Jurisdiction matters.', 'Lawyer review required before signing.']
    if any(k in domain for k in ['hr','candidate','interview','offer','performance']):
        rules += ['Avoid protected-class inference.', 'Score only job-related criteria.', 'Keep evidence for every decision.']
    if any(k in domain for k in ['security','phishing','vulnerability','secrets']):
        rules += ['Verify in controlled environment.', 'Do not expose secrets in prompts.', 'Use remediation approvals.']
    _add_table(result, 'domain_guardrails', [{'guardrail':r} for r in rules])
    if rules:
        _warning(result, 'medium', 'Domain-sensitive workflow requires human review.', rules)


def api_doc(result, project, inputs, customization, text):
    endpoints=[]
    for line in _lines(text):
        if re.search(r'\b(GET|POST|PUT|PATCH|DELETE)\s+[/a-zA-Z0-9_{}/:-]+', line):
            m=re.search(r'\b(GET|POST|PUT|PATCH|DELETE)\s+([^\s]+)', line)
            endpoints.append({'method':m.group(1), 'path':m.group(2), 'source_line':line[:240]})
        elif re.search(r'@(app|router)\.(get|post|put|patch|delete)\(', line, re.I):
            endpoints.append({'method':'decorator', 'path':'extract from decorator', 'source_line':line[:240]})
    _add_table(result, 'endpoint_inventory', endpoints[:80])
    _finding(result, 'api_docs', 'API documentation inventory', f'Detected {len(endpoints)} endpoint/API route clues.', endpoints=endpoints[:10])
    if not endpoints:
        _warning(result, 'low', 'No routes detected. Upload OpenAPI/code/routes for full docs.', None)


def code_inventory(result, project, inputs, customization, text):
    blocks=CODE_BLOCK_RE.findall(text)
    imports=_find_lines(text, ['import ', 'from ', 'require(', 'using ', '#include'], 40)
    todos=_find_lines(text, ['TODO','FIXME','HACK','XXX'], 20)
    metrics={'fenced_code_blocks':len(blocks),'import_lines':len(imports),'todo_fixme_lines':len(todos),'approx_lines':len(_lines(text))}
    _add_table(result, 'code_inventory', [metrics])
    if todos: _add_table(result, 'todo_fixme', [{'line':l} for l in todos])
    _finding(result, 'code_inventory', 'Code inventory', 'Measured code/document structure and risk markers.', metrics=metrics)


def developer_review(result, project, inputs, customization, text):
    risks=_find_lines(text, ['eval(', 'exec(', 'innerHTML', 'SELECT *', 'DROP TABLE', 'DELETE FROM', 'except Exception', 'console.log', 'print(', 'password', 'token'], 40)
    _add_table(result, 'developer_risks', [{'line':l, 'review':'Needs engineering review'} for l in risks])
    if risks: _warning(result, 'medium', 'Code quality/security risks found.', risks[:10])
    result['action_items'] += ['Run unit tests and static analysis before merging.', 'Review destructive operations and credentials before deployment.']


def transaction_parser(result, project, inputs, customization, text):
    transactions=[]
    for line in _lines(text):
        dates=DATE_RE.findall(line)
        amounts=_amounts(line)
        if dates and amounts:
            val=amounts[-1]
            transactions.append({'date':dates[0], 'description':re.sub(DATE_RE, '', line).strip()[:180], 'amount':val['value'], 'currency':val['currency_or_symbol'], 'raw_line':line[:300]})
    _add_table(result, 'normalized_transactions', transactions[:200])
    if transactions:
        amounts=[t['amount'] for t in transactions]
        _add_table(result, 'transaction_summary', [{'count':len(transactions),'total':round(sum(amounts),2),'average':round(statistics.mean(amounts),2),'max':max(amounts),'min':min(amounts)}])
    _finding(result, 'transaction_parser', 'Transaction parser', f'Parsed {len(transactions)} transaction-like rows from dates plus money patterns.')


def finance_reconciliation(result, project, inputs, customization, text):
    amounts=_amounts(text)
    if amounts:
        vals=[a['value'] for a in amounts]
        _add_table(result, 'amount_summary', [{'count':len(vals),'sum':round(sum(vals),2),'max':max(vals),'min':min(vals)}])
    duplicate_lines=[line for line,count in Counter(_lines(text)).items() if count>1 and len(line)>10]
    if duplicate_lines:
        _warning(result, 'medium', 'Duplicate lines detected; possible duplicate transactions/invoices.', duplicate_lines[:10])
    _finding(result, 'finance_reconciliation', 'Finance reconciliation checks', f'Checked {len(amounts)} amounts and {len(duplicate_lines)} duplicate line candidates.')


def resume_parse(result, project, inputs, customization, text):
    skills=['python','javascript','typescript','react','node','sql','excel','power bi','tableau','aws','azure','docker','kubernetes','laravel','php','django','fastapi','machine learning','sales','marketing','seo','shopify','supply chain','accounting','finance']
    found=sorted({s for s in skills if s in text.lower()})
    emails=EMAIL_RE.findall(text); phones=PHONE_RE.findall(text)
    exp_lines=_find_lines(text, ['experience','worked','managed','developed','built','led','responsible','education','university','degree','certification'], 30)
    _add_table(result, 'candidate_profile', [{'emails':emails[:3], 'phones':phones[:3], 'skills':found, 'evidence_lines':len(exp_lines)}])
    _add_table(result, 'experience_evidence', [{'line':l} for l in exp_lines[:30]])
    _finding(result, 'resume_parse', 'Resume/CV parser', f'Extracted {len(found)} skill matches, {len(emails)} emails, and {len(exp_lines)} experience evidence lines.')


def skills_extract(result, project, inputs, customization, text):
    terms=_top_terms(text, 40)
    _add_table(result, 'skills_and_keywords', [{'term':t} for t in terms])


def contact_extract(result, project, inputs, customization, text):
    _add_table(result, 'contact_entities', [{'emails':EMAIL_RE.findall(text)[:20], 'phones':PHONE_RE.findall(text)[:20], 'urls':URL_RE.findall(text)[:20]}])


def candidate_match(result, project, inputs, customization, text):
    jd = inputs.get('job_description') or inputs.get('work_brief') or ''
    resume = text
    jd_terms=set(_top_terms(str(jd), 40)); resume_terms=set(_top_terms(resume, 80))
    overlap=sorted(jd_terms & resume_terms)
    score=int(min(100, 15 + 3*len(overlap))) if jd_terms else int(min(100, 35 + len(resume_terms)))
    _add_table(result, 'candidate_match', [{'fit_score':score, 'matched_terms':', '.join(overlap[:30]), 'jd_terms_count':len(jd_terms), 'resume_terms_count':len(resume_terms)}])
    _finding(result, 'candidate_match', 'Explainable candidate match', f'Computed fit from evidence-term overlap. Score: {score}/100.', matched_terms=overlap[:30])


def fair_hiring_guardrails(result, project, inputs, customization, text):
    protected=['age','married','pregnant','religion','nationality','race','gender','disability','children','photo']
    lines=_find_lines(text, protected, 20)
    if lines:
        _warning(result, 'high', 'Potential protected-class or non-job-related hiring data detected. Do not use for selection.', lines)
    _add_table(result, 'fair_hiring_review', [{'rule':'Use job-related criteria only'}, {'rule':'Keep evidence for every rating'}, {'rule':'Do not infer protected attributes'}])


def carbon_calc(result, project, inputs, customization, text):
    rows=[]
    low=text.lower()
    for factor, kg_per_unit in EMISSION_FACTORS.items():
        key=factor.replace('_',' ')
        if key.split()[0] in low:
            # pick nearby numbers roughly; final factors should be explicitly provided.
            nums=_numbers(text)
            qty=nums[0] if nums else None
            if qty is not None:
                rows.append({'activity':factor, 'quantity_detected':qty, 'kg_co2e_factor_default':kg_per_unit, 'estimated_kg_co2e':round(qty*kg_per_unit,2), 'factor_warning':'Built-in rough factor; replace with country/year factor for reporting.'})
    _add_table(result, 'co2e_estimates', rows)
    if not rows:
        _warning(result, 'medium', 'No activity quantity matched built-in factor keys. Provide activity units such as electricity_kwh, gasoline_liter, diesel_liter, natural_gas_m3, flight_km.', None)
    _finding(result, 'carbon_calc', 'Carbon factor calculation', f'Computed {len(rows)} local CO2e estimate rows without inventing missing activity data.')


def esg_review(result, project, inputs, customization, text):
    lines=_find_lines(text, ['scope 1','scope 2','scope 3','co2e','emission','energy','fuel','waste','water','supplier','ghg','renewable'], 50)
    _add_table(result, 'esg_evidence_map', [{'line':l} for l in lines])
    _finding(result, 'esg_review', 'ESG evidence mapping', f'Found {len(lines)} ESG/sustainability evidence lines.')


def legal_clause_scan(result, project, inputs, customization, text):
    rows=[]
    for clause, terms in LEGAL_CLAUSES.items():
        lines=_find_lines(text, terms, 8)
        if lines:
            risk='High' if clause in {'Liability cap','Indemnity','Auto renewal','Data processing'} else 'Medium'
            rows.append({'clause':clause, 'risk':risk, 'evidence_count':len(lines), 'sample_evidence':' | '.join(lines[:2])[:500]})
    _add_table(result, 'clause_extraction', rows)
    _finding(result, 'legal_clause_scan', 'Clause scanner', f'Mapped {len(rows)} clause categories from contract/legal text.')
    if rows:
        _warning(result, 'medium', 'Legal clause analysis requires jurisdiction-specific lawyer review before signing.', [r['clause'] for r in rows])


def obligation_calendar(result, project, inputs, customization, text):
    lines=_find_lines(text, ['within','days','notice','renewal','expire','termination','deadline','monthly','annually','payment due'], 40)
    obligations=[]
    for l in lines:
        dates=DATE_RE.findall(l)
        nums=NUMBER_RE.findall(l)
        obligations.append({'trigger_or_deadline': dates[0] if dates else (nums[0]+' days?' if nums else 'review line'), 'obligation_line':l})
    _add_table(result, 'obligation_calendar_candidates', obligations[:40])


def risk_register(result, project, inputs, customization, text):
    terms=['unlimited','exclusive','irrevocable','waive','penalty','late fee','terminate','indemnify','breach','non-refundable','personal data','guaranteed','material adverse','default']
    rows=[{'risk_line':l, 'risk_level':'High' if any(x in l.lower() for x in ['unlimited','waive','indemnify','personal data']) else 'Medium'} for l in _find_lines(text, terms, 50)]
    _add_table(result, 'risk_register', rows)
    if rows: _warning(result, 'medium', 'Risk register contains items requiring owner review.', rows[:10])


def text_diff(result, project, inputs, customization, text):
    left=inputs.get('old_contract') or inputs.get('version_a') or ''
    right=inputs.get('new_contract') or inputs.get('version_b') or ''
    if not left or not right:
        # fallback: split uploaded combined text into halves, but state it explicitly.
        lines=_lines(text)
        mid=len(lines)//2
        left='\n'.join(lines[:mid]); right='\n'.join(lines[mid:])
        _warning(result, 'low', 'Two explicit versions were not supplied; diff used first half vs second half of provided text.', None)
    diff=list(difflib.unified_diff(left.splitlines(), right.splitlines(), n=2))[:300]
    _add_table(result, 'diff_lines', [{'line':d} for d in diff])
    _finding(result, 'text_diff', 'Contract/text diff', f'Generated {len(diff)} unified diff lines from supplied versions.')


def clinical_extract(result, project, inputs, customization, text):
    terms=['chief complaint','history','assessment','plan','diagnosis','medication','allergy','vital','blood pressure','bp','hr','spo2','lab','impression']
    rows=[]
    for t in terms:
        lines=_find_lines(text,[t],5)
        if lines: rows.append({'section_or_entity':t,'evidence':' | '.join(lines[:2])[:500]})
    _add_table(result, 'clinical_entities', rows)
    _finding(result, 'clinical_extract', 'Clinical note extractor', f'Extracted {len(rows)} clinical section/entity groups.')


def phi_scan(result, project, inputs, customization, text):
    phi={'emails':EMAIL_RE.findall(text)[:20], 'phones':PHONE_RE.findall(text)[:20]}
    if phi['emails'] or phi['phones']:
        _warning(result, 'high', 'PHI/contact-like identifiers detected. Use local-only mode or redact before cloud calls.', phi)
    _add_table(result, 'phi_scan', [phi])


def coding_candidates(result, project, inputs, customization, text):
    # Local candidates only from text; no invented ICD/SNOMED code IDs.
    lines=_find_lines(text, ['diagnosis','assessment','impression','icd','snomed','cpt','rxnorm'], 40)
    _add_table(result, 'coding_candidate_evidence', [{'line':l, 'code':'not_assigned_without_configured_code_database'} for l in lines])


def code_review(result, project, inputs, customization, text):
    developer_review(result, project, inputs, customization, text)


def secret_scan(result, project, inputs, customization, text):
    rows=[]
    for name, pat in SECRET_PATTERNS.items():
        for m in pat.finditer(text or ''):
            raw=m.group(0)
            masked=raw[:6]+'…'+raw[-4:] if len(raw)>12 else 'masked'
            rows.append({'type':name,'masked_secret':masked,'start_index':m.start(),'action':'Rotate, revoke, and remove from history if real.'})
    _add_table(result, 'secret_findings', rows)
    if rows: _warning(result, 'critical', 'Potential secrets detected. Treat as compromised until verified.', rows[:10])
    _finding(result, 'secret_scan', 'Secret scanner', f'Found {len(rows)} secret-pattern matches using local regex detectors.')


def learning_diagnosis(result, project, inputs, customization, text):
    terms=_top_terms(text, 20)
    _add_table(result, 'learning_diagnosis', [{'concept':t,'status':'needs explanation/practice'} for t in terms[:12]])
    _finding(result, 'learning_diagnosis', 'Learning diagnosis', 'Built a concept map from submitted code/topic terms.', concepts=terms[:12])


def exercise_builder(result, project, inputs, customization, text):
    terms=_top_terms(text, 8) or ['core concept']
    rows=[{'level':'easy','exercise':f'Explain {terms[0]} in your own words and write a minimal example.'}, {'level':'medium','exercise':f'Build a small function using {terms[0]} and add input validation.'}, {'level':'hard','exercise':f'Refactor the solution and write tests for edge cases involving {terms[0]}.'}]
    _add_table(result, 'next_exercises', rows)


def url_inventory(result, project, inputs, customization, text):
    entities=_basic_entities(text)
    rows=[{'url':u,'domain':urlparse(u if u.startswith('http') else 'http://'+u).netloc} for u in entities['urls']]
    _add_table(result, 'url_inventory', rows)
    if rows and any('competitor' in project.slug for _ in [0]):
        _warning(result, 'medium', 'URL-only competitor analysis needs an HTTP/browser/SerpAPI connector or pasted page content. No website facts were invented.', rows[:5])


def positioning_extract(result, project, inputs, customization, text):
    lines=_find_lines(text, ['pricing','features','customers','integrations','case study','testimonial','benefit','alternative','compare','plans','enterprise'], 50)
    _add_table(result, 'positioning_evidence', [{'line':l} for l in lines])
    _finding(result, 'positioning_extract', 'Positioning extraction', f'Extracted {len(lines)} positioning/pricing/feature evidence lines from supplied content.')


def gap_matrix(result, project, inputs, customization, text):
    terms=_top_terms(text, 16)
    rows=[{'dimension':t, 'your_position':'fill from your_product_profile', 'competitor_position':'fill from supplied competitor evidence', 'gap_action':'collect proof or build counter-positioning'} for t in terms[:10]]
    _add_table(result, 'gap_matrix', rows)


def portfolio_parser(result, project, inputs, customization, text):
    rows=[]
    asset_re=re.compile(r'\b(BTC|ETH|SOL|BNB|XRP|ADA|DOGE|USDT|USDC|AVAX|LINK|DOT|MATIC|TON)\b', re.I)
    for line in _lines(text):
        a=asset_re.search(line)
        nums=_numbers(line)
        if a and nums:
            rows.append({'asset':a.group(1).upper(),'numbers_detected':nums[:4], 'raw_line':line[:250]})
    _add_table(result, 'crypto_holdings_detected', rows)
    if rows: _finding(result, 'portfolio_parser', 'Portfolio parser', f'Detected {len(rows)} crypto holding/transaction lines. Live prices are not invented.')
    else: _warning(result,'medium','No crypto holdings detected. Provide asset symbols and quantities.',None)


def concentration_risk(result, project, inputs, customization, text):
    table=result['tables'].get('crypto_holdings_detected', [])
    assets=[r['asset'] for r in table]
    cnt=Counter(assets)
    _add_table(result, 'concentration_risk', [{'asset':a,'line_count':c,'risk_note':'High concentration if this asset dominates portfolio value'} for a,c in cnt.most_common()])


def finance_risk(result, project, inputs, customization, text):
    lines=_find_lines(text,['guaranteed','leverage','margin','apr','interest','late fee','balloon','variable','default','penalty','loss','drawdown'],50)
    _add_table(result,'finance_risk_lines',[{'line':l} for l in lines])
    if lines: _warning(result,'medium','Finance-risk terms require expert review.',lines[:10])


def supply_doc_parse(result, project, inputs, customization, text):
    terms=['sku','qty','quantity','carton','pcs','unit','po','invoice','hs','origin','destination','incoterm','fob','cif','supplier','awb','bl','container','delivery']
    rows=[{'line':l} for l in _find_lines(text, terms, 80)]
    _add_table(result, 'supply_chain_lines', rows)
    _finding(result,'supply_doc_parse', 'Supply-chain document parser', f'Extracted {len(rows)} procurement/shipping evidence lines.')


def hs_candidate_rules(result, project, inputs, customization, text):
    items=_find_lines(text,['description','material','product','item','sku','hs','tariff'],40)
    _add_table(result,'hs_classification_candidates',[{'evidence':l,'hs_code':'not_final_without_tariff_database','review':'Broker/customs specialist required'} for l in items])
    _warning(result,'high','Final HS classification/duty requires official tariff database and broker review. No final codes are invented.',None)


def quantity_check(result, project, inputs, customization, text):
    qty_lines=_find_lines(text,['qty','quantity','pcs','units','received','ordered','delivered'],50)
    _add_table(result,'quantity_check_lines',[{'line':l} for l in qty_lines])


def product_opportunity(result, project, inputs, customization, text):
    terms=_top_terms(text,20)
    budget_text=str(customization.get('budget') or customization.get('margin_target') or '')
    amounts=_amounts(budget_text+'\n'+text)
    score=40+min(25,len(terms))+min(20,len(amounts)*5)
    if any(x in text.lower() for x in ['fragile','battery','regulated','copyright','trademark','medical','weapon']): score-=20
    _add_table(result,'product_opportunity_score',[{'score':max(0,min(100,score)),'basis':'local input richness + margin evidence + risk penalties; no marketplace demand was invented','top_terms':', '.join(terms[:10])}])
    _finding(result,'product_opportunity','Product opportunity radar',f'Computed local opportunity score from provided niche/product evidence. Score {max(0,min(100,score))}/100.')


def margin_calc(result, project, inputs, customization, text):
    nums=_numbers(text+' '+str(customization.get('budget',''))+' '+str(customization.get('margin_target','')))
    rows=[]
    if len(nums)>=2:
        cost=min(nums[0],nums[1]); price=max(nums[0],nums[1])
        margin=(price-cost)/price*100 if price else 0
        rows.append({'detected_cost_candidate':cost,'detected_price_candidate':price,'gross_margin_percent':round(margin,2),'warning':'Verify which number is cost vs price.'})
    else:
        rows.append({'status':'need_cost_and_selling_price','required_inputs':'supplier cost, shipping, payment fees, ad CPA, expected selling price'})
    _add_table(result,'margin_calculator',rows)


def drug_interaction_screen(result, project, inputs, customization, text):
    low=text.lower()
    meds=sorted({m for pair,_,_ in DRUG_RULES for m in pair if m in low})
    rows=[]
    for pair,severity,action in DRUG_RULES:
        if all(p in low for p in pair):
            rows.append({'drug_pair':' + '.join(pair),'severity':severity,'local_rule_action':action,'database_status':'limited built-in rule; verify with configured clinical database'})
    _add_table(result,'drug_interaction_matrix',rows)
    _add_table(result,'detected_medication_terms',[{'medication':m} for m in meds])
    if rows: _warning(result,'critical','Potential medication interaction detected. Requires clinician/pharmacist verification.',rows)
    else: _warning(result,'high','No built-in interaction rule matched. This is not a clean bill of safety; configure full drug database for clinical completeness.',None)


def clinical_context(result, project, inputs, customization, text):
    context=_find_lines(text,['age','pregnan','renal','hepatic','kidney','liver','allergy','dose','mg','mcg','frequency'],50)
    _add_table(result,'clinical_context_modifiers',[{'line':l} for l in context])


def email_sequence(result, project, inputs, customization, text):
    terms=_top_terms(text,10)
    sequence=[]
    stages=['Awareness','Problem agitation','Value proof','Objection handling','Urgency/close']
    for i,stage in enumerate(stages,1):
        sequence.append({'email':i,'stage':stage,'subject':f'{stage}: {terms[0] if terms else project.name}','body_outline':'hook → relevance → value/proof → single CTA','personalization_tokens':'{first_name}, {pain_point}, {offer}'})
    _add_table(result,'email_sequence',sequence)
    _finding(result,'email_sequence','Lifecycle email sequence',f'Built {len(sequence)} email-stage outlines from the supplied offer/persona.')


def esg_metric_extract(result, project, inputs, customization, text):
    lines=_find_lines(text,['scope','co2e','emissions','energy','water','waste','employee','supplier','diversity','governance','materiality','assurance'],80)
    _add_table(result,'esg_metrics_detected',[{'metric_evidence':l,'normalized_value':'extract_from_line_or_manual_review'} for l in lines])


def evidence_map(result, project, inputs, customization, text):
    sents=_sentences(text,40,40)
    _add_table(result,'evidence_map',[{'evidence_id':i+1,'evidence':s[:400]} for i,s in enumerate(sents[:40])])


def expense_rules(result, project, inputs, customization, text):
    cats={'travel':['uber','taxi','flight','hotel','airbnb','train'], 'meals':['restaurant','cafe','coffee','meal'], 'software':['saas','software','subscription','github','aws','openai'], 'office':['stationery','paper','printer'], 'marketing':['ads','facebook','google','tiktok','campaign']}
    rows=[]
    for line in _lines(text):
        low=line.lower(); amounts=_amounts(line)
        for cat, terms in cats.items():
            if any(t in low for t in terms):
                rows.append({'category':cat,'amount':amounts[-1]['value'] if amounts else None,'line':line[:250]})
                break
    _add_table(result,'categorized_expenses',rows)


def financial_metric_extract(result, project, inputs, customization, text):
    terms=['revenue','gross profit','operating income','ebitda','net income','cash flow','assets','liabilities','equity','debt','eps','margin']
    rows=[]
    for line in _find_lines(text,terms,80):
        rows.append({'metric_line':line,'amounts':_amounts(line),'percentages':PERCENT_RE.findall(line)})
    _add_table(result,'financial_metrics',rows)


def ratio_calc(result, project, inputs, customization, text):
    rows=[]
    # Only calculate when labeled metrics are detectable in the same text.
    vals={}
    for name in ['revenue','net income','assets','liabilities','debt','equity']:
        for l in _find_lines(text,[name],10):
            amounts=_amounts(l)
            if amounts:
                vals[name]=amounts[-1]['value']; break
    if vals.get('revenue') and vals.get('net income'):
        rows.append({'ratio':'net_margin','value_percent':round(vals['net income']/vals['revenue']*100,2)})
    if vals.get('assets') and vals.get('liabilities'):
        rows.append({'ratio':'liabilities_to_assets','value_percent':round(vals['liabilities']/vals['assets']*100,2)})
    _add_table(result,'calculated_ratios',rows or [{'status':'need_labeled_financial_metrics_for_ratio_calculation'}])


def flashcard_generate(result, project, inputs, customization, text):
    cards=[]
    for s in _sentences(text,50,30):
        terms=_top_terms(s,3)
        if terms:
            cards.append({'front':f'What is the key idea involving {terms[0]}?','back':s[:450],'difficulty':'medium'})
        if len(cards)>=20: break
    _add_table(result,'flashcards',cards)
    _finding(result,'flashcards','Flashcard generator',f'Generated {len(cards)} source-grounded flashcards from supplied material.')


def learning_objectives(result, project, inputs, customization, text):
    terms=_top_terms(text,12)
    _add_table(result,'learning_objectives',[{'objective':f'Understand and apply {t}'} for t in terms])


def transcript_structure(result, project, inputs, customization, text):
    lines=_lines(text)
    segments=[]
    for i,l in enumerate(lines[:120],1):
        if re.match(r'\[?\d{1,2}:\d{2}',l) or len(l)>20:
            segments.append({'segment':i,'text':l[:300]})
    _add_table(result,'transcript_segments',segments[:80])
    if not segments:
        _warning(result,'medium','No transcript text detected. Raw audio requires a configured STT connector.',None)


def speaker_segment(result, project, inputs, customization, text):
    rows=[]
    for l in _lines(text):
        if re.match(r'^[A-Z][A-Za-z0-9 _-]{1,30}:',l):
            sp,rest=l.split(':',1)
            rows.append({'speaker':sp.strip(),'utterance':rest.strip()[:300]})
    _add_table(result,'speaker_segments',rows[:120])


def green_claims_review(result, project, inputs, customization, text):
    terms=['green','eco','sustainable','recyclable','biodegradable','carbon neutral','net zero','environmentally friendly','plastic-free','zero waste','organic']
    rows=[]
    for l in _find_lines(text,terms,50):
        rows.append({'claim':l,'risk':'Needs specific evidence, scope, and qualification. Avoid vague absolute environmental claims.'})
    _add_table(result,'green_claims_review',rows)
    if rows: _warning(result,'high','Green/environmental claims detected. Require evidence and legal/compliance review.',rows[:10])


def incident_timeline(result, project, inputs, customization, text):
    rows=[]
    for l in _lines(text):
        if DATE_RE.findall(l) or re.search(r'\b\d{1,2}:\d{2}\b',l):
            rows.append({'time_or_date':(DATE_RE.findall(l) or re.findall(r'\b\d{1,2}:\d{2}\b',l) or ['unknown'])[0], 'event':l[:300]})
    _add_table(result,'incident_timeline',rows[:100])
    _finding(result,'incident_timeline','Incident timeline reconstruction',f'Extracted {len(rows)} dated/time-stamped incident events.')


def root_cause_hypotheses(result, project, inputs, customization, text):
    terms=['timeout','error','exception','deploy','database','network','cpu','memory','disk','permission','auth','rate limit','config','dns','ssl']
    lines=_find_lines(text,terms,80)
    rows=[]
    for term in terms:
        ev=[l for l in lines if term in l.lower()]
        if ev: rows.append({'hypothesis':term,'evidence_count':len(ev),'first_evidence':ev[0][:250]})
    _add_table(result,'root_cause_hypotheses',rows)


def action_tracker(result, project, inputs, customization, text):
    actions=[]
    for l in _find_lines(text,['todo','action','fix','owner','next','follow up','mitigation','corrective'],60):
        actions.append({'action':l,'owner':'unassigned','status':'open'})
    _add_table(result,'action_tracker',actions)
    result['action_items'] += [a['action'] for a in actions[:10]]


def jd_parse(result, project, inputs, customization, text):
    rows=[]
    for t in ['responsibilities','requirements','qualifications','benefits','salary','location','remote','experience']:
        lines=_find_lines(text,[t],8)
        if lines: rows.append({'section':t,'evidence':' | '.join(lines[:2])[:500]})
    _add_table(result,'job_description_sections',rows)


def interview_kit(result, project, inputs, customization, text):
    terms=_top_terms(text,12)
    questions=[]
    for t in terms[:10]:
        questions.append({'competency':t,'question':f'Tell me about a time you used {t} to solve a real problem. What was the result?','rubric':'specific situation, action, impact, trade-offs, evidence'})
    _add_table(result,'interview_questions',questions)


def invoice_extract(result, project, inputs, customization, text):
    patterns={'invoice_number':r'(?i)(invoice\s*(no\.?|number|#)\s*[:#-]?\s*)([A-Z0-9-]{3,})','po_number':r'(?i)(po\s*(no\.?|number|#)\s*[:#-]?\s*)([A-Z0-9-]{3,})','tax_id':r'(?i)(vat|tax id|trn)\s*[:#-]?\s*([A-Z0-9-]{5,})'}
    row={}
    for k,pat in patterns.items():
        m=re.search(pat,text or '')
        row[k]=m.group(3 if k!='tax_id' else 2) if m else None
    amounts=_amounts(text); row['amount_candidates']=amounts[:20]
    dates=DATE_RE.findall(text); row['date_candidates']=dates[:10]
    _add_table(result,'invoice_extraction',[row])
    _finding(result,'invoice_extract','Invoice extraction',f'Extracted invoice/PO/tax identifiers and {len(amounts)} amount candidates.')


def tax_check(result, project, inputs, customization, text):
    tax_lines=_find_lines(text,['vat','tax','gst','sales tax','trn'],50)
    _add_table(result,'tax_validation_lines',[{'line':l,'validation':'needs configured country tax rules for final validation'} for l in tax_lines])


def po_match(result, project, inputs, customization, text):
    lines=_find_lines(text,['po','purchase order','ordered','received','invoice','delivery','qty','quantity'],80)
    _add_table(result,'po_matching_evidence',[{'line':l,'match_status':'needs PO source for actual 2-way/3-way match'} for l in lines])


def inclusive_language(result, project, inputs, customization, text):
    terms=['rockstar','ninja','young','native speaker','aggressive','work hard play hard','able-bodied','he/she']
    lines=_find_lines(text,terms,30)
    _add_table(result,'inclusive_language_flags',[{'line':l,'suggestion':'rewrite with neutral, job-related wording'} for l in lines])
    if lines: _warning(result,'medium','Potentially exclusionary language detected.',lines)


def role_scorecard(result, project, inputs, customization, text):
    terms=_top_terms(text,12)
    _add_table(result,'role_scorecard',[{'criterion':t,'evidence_required':'define observable evidence and rating scale'} for t in terms])


def launch_assets(result, project, inputs, customization, text):
    terms=_top_terms(text,10)
    rows=[{'asset':'Landing page hero','content':f'Lead with {terms[0] if terms else "core benefit"} and one CTA.'},{'asset':'Launch email','content':'problem → product → proof → CTA'},{'asset':'Founder post','content':'origin story → user pain → result → invite'}]
    _add_table(result,'launch_assets',rows)


def roadmap_builder(result, project, inputs, customization, text):
    _add_table(result,'launch_roadmap',[{'phase':'Pre-launch','actions':'waitlist, proof, beta feedback'},{'phase':'Launch week','actions':'content, outreach, demos, retargeting'},{'phase':'Post-launch','actions':'case studies, onboarding fixes, upsell tests'}])


def lease_terms(result, project, inputs, customization, text):
    terms=['rent','deposit','security deposit','term','renewal','maintenance','utilities','pet','parking','sublet','notice','late fee']
    rows=[]
    for t in terms:
        lines=_find_lines(text,[t],5)
        if lines: rows.append({'term':t,'evidence':' | '.join(lines[:2])[:500]})
    _add_table(result,'lease_terms',rows)


def listing_builder(result, project, inputs, customization, text):
    terms=_top_terms(text,12)
    _add_table(result,'listing_content',[{'field':'title','draft':' '.join([t.title() for t in terms[:6]])[:120]},{'field':'bullets','draft':'\n'.join([f'- {t}: explain user benefit with proof' for t in terms[:5]])},{'field':'description_structure','draft':'Problem → Features → Benefits → Specs → FAQ → CTA'}])


def seo_terms(result, project, inputs, customization, text):
    terms=_top_terms(text,30)
    _add_table(result,'seo_terms',[{'term':t,'usage':'candidate keyword/entity; validate with live SERP/volume provider if needed'} for t in terms])


def llm_usage_meter(result, project, inputs, customization, text):
    rows=[]
    for l in _lines(text):
        if any(t in l.lower() for t in ['prompt','completion','token','cost','model','provider']):
            nums=_numbers(l); rows.append({'usage_line':l[:300], 'numbers':nums[:5]})
    _add_table(result,'llm_usage_lines',rows)


def invoice_calc(result, project, inputs, customization, text):
    nums=_numbers(text)
    _add_table(result,'billing_calculation',[{'detected_numbers':nums[:20], 'calculation_status':'provide explicit unit price per model/token class for final invoices'}])


def budget_guard(result, project, inputs, customization, text):
    budget=customization.get('budget') or inputs.get('budget') or ''
    _add_table(result,'budget_guard',[{'budget_input':budget, 'policy':'block or warn when estimated cost exceeds configured budget'}])


def log_parse(result, project, inputs, customization, text):
    lines=_find_lines(text,['error','exception','failed','timeout','warn','critical','traceback','denied','segmentation','oom','killed'],120)
    _add_table(result,'log_events',[{'event_line':l} for l in lines])
    if lines: _warning(result,'medium','Failure/anomaly log events detected.',lines[:10])


def anomaly_detect(result, project, inputs, customization, text):
    lines=_lines(text); counts=Counter()
    for l in lines:
        key=re.sub(r'\d+','<num>',l.lower())[:120]
        counts[key]+=1
    common=[{'pattern':k,'count':v} for k,v in counts.most_common(20) if v>1]
    _add_table(result,'repeated_log_patterns',common)


def mcp_tool_parse(result, project, inputs, customization, text):
    lines=_find_lines(text,['tool','function','schema','input','output','mcp','permission','scope'],80)
    _add_table(result,'mcp_tool_inventory',[{'line':l} for l in lines])


def approval_policy(result, project, inputs, customization, text):
    _add_table(result,'approval_policy',[{'action_type':'read-only','approval':'not required'},{'action_type':'write/update/delete/send/payment','approval':'required before execution'},{'action_type':'external data export','approval':'required if sensitive data present'}])


def agent_flow(result, project, inputs, customization, text):
    _add_table(result,'agent_workflow',[{'step':1,'name':'Validate inputs'},{'step':2,'name':'Select allowed tools'},{'step':3,'name':'Run read actions'},{'step':4,'name':'Prepare write plan'},{'step':5,'name':'Human approval for destructive actions'}])


def pico_extract(result, project, inputs, customization, text):
    mapping={'Population':['patient','children','adult','elderly','pediatric'], 'Intervention':['intervention','treatment','surgery','therapy'], 'Comparison':['versus','compared','control','placebo'], 'Outcome':['outcome','mortality','recurrence','hearing','quality','risk']}
    rows=[]
    for k,terms in mapping.items(): rows.append({'pico':k,'evidence':' | '.join(_find_lines(text,terms,3))[:500]})
    _add_table(result,'pico_framework',rows)


def study_table(result, project, inputs, customization, text):
    lines=_find_lines(text,['randomized','cohort','case-control','systematic review','meta-analysis','patients','n=','study','trial','doi'],80)
    _add_table(result,'study_evidence',[{'line':l} for l in lines])


def evidence_grade(result, project, inputs, customization, text):
    low=text.lower(); grade='low'
    if 'randomized' in low or 'meta-analysis' in low: grade='higher'
    elif 'cohort' in low or 'case-control' in low: grade='moderate'
    _add_table(result,'evidence_grade',[{'local_grade':grade,'basis':'keyword-based preliminary grade; verify with full critical appraisal'}])


def routing_decision(result, project, inputs, customization, text):
    privacy=str(customization.get('privacy_mode') or '').lower()
    task=text.lower()
    if 'local' in privacy or any(x in task for x in ['phi','medical','contract','secret','password']):
        route='local model first; cloud only after redaction/approval'
    elif any(x in task for x in ['code','sql','json','api']):
        route='coding-capable model with structured-output support'
    else:
        route='lowest-cost quality model that meets context length'
    _add_table(result,'routing_decision',[{'recommended_route':route,'reason':'privacy/content/task heuristic'}])


def privacy_gate(result, project, inputs, customization, text):
    sensitive=bool(EMAIL_RE.findall(text) or PHONE_RE.findall(text) or any(x in text.lower() for x in ['password','secret','patient','contract','salary']))
    _add_table(result,'privacy_gate',[{'sensitive_detected':sensitive,'recommended_policy':'local/redacted processing' if sensitive else 'cloud allowed if provider policy is acceptable'}])
    if sensitive: _warning(result,'high','Sensitive data detected; check privacy mode before cloud provider use.',None)


def mortgage_terms(result, project, inputs, customization, text):
    terms=['loan amount','interest rate','apr','escrow','closing cost','points','down payment','term','fixed','adjustable','balloon','prepayment']
    rows=[{'term_line':l,'amounts':_amounts(l),'percentages':PERCENT_RE.findall(l)} for l in _find_lines(text,terms,80)]
    _add_table(result,'mortgage_terms',rows)


def fee_extract(result, project, inputs, customization, text):
    rows=[{'fee_line':l,'amounts':_amounts(l)} for l in _find_lines(text,['fee','cost','charge','escrow','points','insurance','tax'],80)]
    _add_table(result,'fee_extract',rows)


def nda_risk(result, project, inputs, customization, text):
    terms=['residual knowledge','indefinite','return or destroy','injunctive','non-solicit','non-compete','affiliates','representatives']
    rows=[{'risk_line':l} for l in _find_lines(text,terms,40)]
    _add_table(result,'nda_specific_risks',rows)


def negotiation_notes(result, project, inputs, customization, text):
    rows=[{'position':'Limit confidentiality term','fallback':'3-5 years except trade secrets'}, {'position':'Mutuality','fallback':'Make obligations mutual when both sides disclose'}, {'position':'Liability/indemnity','fallback':'Avoid unlimited liability for disclosure mistakes'}]
    _add_table(result,'negotiation_notes',rows)


def address_parse(result, project, inputs, customization, text):
    urls=URL_RE.findall(text); nums=_numbers(text)
    _add_table(result,'address_input_parse',[{'address_input':inputs.get('address') or text[:200], 'numbers_detected':nums[:10], 'urls':urls[:10]}])


def local_data_requirements(result, project, inputs, customization, text):
    req=['geocoding coordinates','school ratings/source','crime/safety source','transport/commute API','flood/noise/environment source','recent property comparables']
    _add_table(result,'live_data_requirements',[{'required_dataset':r,'status':'not_fabricated_configure_connector'} for r in req])
    _warning(result,'high','Neighborhood facts require live/local data connectors. No school, crime, price, or commute facts were invented.',req)


def weighted_scorecard(result, project, inputs, customization, text):
    weights=str(customization.get('priority_weights') or '')
    _add_table(result,'weighted_scorecard_template',[{'criterion':'safety','weight_input':weights or 'not provided','score':'pending live dataset'}, {'criterion':'commute','weight_input':weights or 'not provided','score':'pending live dataset'}, {'criterion':'amenities','weight_input':weights or 'not provided','score':'pending live dataset'}])


def offer_terms(result, project, inputs, customization, text):
    rows=[{'term_line':l} for l in _find_lines(text,['salary','compensation','bonus','equity','start date','benefits','probation','reporting','location','employment'],60)]
    _add_table(result,'offer_terms',rows)


def legal_doc_builder(result, project, inputs, customization, text):
    terms=result['tables'].get('offer_terms',[])
    _add_table(result,'document_sections',[{'section':'Role and start date'},{'section':'Compensation'},{'section':'Benefits and policies'},{'section':'Conditions and contingencies'},{'section':'Acceptance signature'}])
    if not terms: _warning(result,'medium','Offer details are incomplete; document should not be sent until comp/start date/conditions are confirmed.',None)


def artifact_runtime_spec(result, project, inputs, customization, text):
    _add_table(result,'artifact_runtime_spec',[{'component':'sandboxing','requirement':'isolate untrusted code/artifacts'}, {'component':'storage','requirement':'version artifacts and outputs'}, {'component':'permissions','requirement':'approval for network/file writes'}])


def security_review(result, project, inputs, customization, text):
    sec_lines=_find_lines(text,['secret','token','password','permission','admin','rce','xss','csrf','sqli','cve','vulnerability','exposed','public'],80)
    _add_table(result,'security_review',[{'line':l} for l in sec_lines])
    if sec_lines: _warning(result,'high','Security-sensitive evidence found.',sec_lines[:10])


def deployment_plan(result, project, inputs, customization, text):
    _add_table(result,'deployment_plan',[{'step':1,'task':'Set environment variables/secrets'}, {'step':2,'task':'Run tests and lint'}, {'step':3,'task':'Deploy behind auth/reverse proxy'}, {'step':4,'task':'Enable logging/backups'}, {'step':5,'task':'Run smoke tests'}])


def paper_structure(result, project, inputs, customization, text):
    sections=[]
    for sec in ['abstract','introduction','methods','results','discussion','conclusion','limitations']:
        lines=_find_lines(text,[sec],5)
        if lines: sections.append({'section':sec,'evidence':lines[0][:400]})
    _add_table(result,'paper_structure',sections)


def plain_language_summary(result, project, inputs, customization, text):
    sents=_sentences(text,60,5)
    _add_table(result,'plain_language_summary',[{'point':i+1,'summary':s[:350]} for i,s in enumerate(sents,1)])


def feedback_cluster(result, project, inputs, customization, text):
    themes=['impact','communication','ownership','quality','teamwork','leadership','growth','delivery']
    rows=[]
    for t in themes:
        lines=_find_lines(text,[t],6)
        if lines: rows.append({'theme':t,'evidence_count':len(lines),'evidence':' | '.join(lines[:2])[:500]})
    _add_table(result,'feedback_clusters',rows)


def review_builder(result, project, inputs, customization, text):
    _add_table(result,'performance_review_sections',[{'section':'Achievements'}, {'section':'Strengths'}, {'section':'Growth areas'}, {'section':'Next-period goals'}, {'section':'Manager support needed'}])


def phishing_score(result, project, inputs, customization, text):
    terms={'urgency':['urgent','immediately','within 24 hours','final notice'], 'credential':['password','login','verify your account','2fa','bank account'], 'financial':['invoice','payment','wire','refund'], 'threat':['suspend','locked','legal action'], 'attachment':['attachment','open file','download']}
    score=0; rows=[]
    for cat,ts in terms.items():
        lines=_find_lines(text,ts,10)
        if lines:
            score+= {'urgency':15,'credential':25,'financial':15,'threat':20,'attachment':15}[cat]
            rows.append({'indicator':cat,'evidence':' | '.join(lines[:2])[:500]})
    if URL_RE.findall(text): score+=10
    score=min(100,score)
    _add_table(result,'phishing_indicators',rows)
    _add_table(result,'phishing_score',[{'score':score,'risk':'high' if score>=60 else 'medium' if score>=30 else 'low'}])
    if score>=30: _warning(result,'high' if score>=60 else 'medium','Potential phishing indicators detected.',rows)


def runbook_links(result, project, inputs, customization, text):
    _add_table(result,'runbook_reference_candidates',[{'trigger':'service down','runbook_section':'health checks → logs → rollback'}, {'trigger':'deploy failure','runbook_section':'build logs → dependency/cache → retry policy'}, {'trigger':'db issue','runbook_section':'connection pool → slow queries → backup/restore'}])


def pipeline_failure(result, project, inputs, customization, text):
    stages=['install','build','test','lint','deploy','docker','migration','cache']
    rows=[]
    for s in stages:
        lines=_find_lines(text,[s],8)
        if lines: rows.append({'stage':s,'evidence':' | '.join(lines[:2])[:500]})
    _add_table(result,'pipeline_failure_stage',rows)


def chapter_builder(result, project, inputs, customization, text):
    sents=_sentences(text,60,12)
    chapters=[{'chapter':i+1,'title':(_top_terms(s,3) or ['Segment'])[0].title(),'summary':s[:260]} for i,s in enumerate(sents[:10],1)]
    _add_table(result,'chapters',chapters)


def social_snippets(result, project, inputs, customization, text):
    terms=_top_terms(text,8)
    rows=[{'platform':'TikTok/Reels','snippet':f'Hook around {terms[0] if terms else "main pain"} in the first 2 seconds.'},{'platform':'LinkedIn','snippet':'Insight-led post with one practical takeaway.'},{'platform':'X/Twitter','snippet':'Short contrarian takeaway + link/CTA.'}]
    _add_table(result,'social_snippets',rows)


def privacy_policy_scan(result, project, inputs, customization, text):
    req=['data collected','purpose','sharing','retention','user rights','cookies','children','security','contact','jurisdiction','third parties']
    rows=[]
    for r in req:
        lines=_find_lines(text,[r],4)
        rows.append({'requirement':r,'present':bool(lines),'evidence':lines[0][:300] if lines else ''})
    _add_table(result,'privacy_policy_grade',rows)


def service_inventory(result, project, inputs, customization, text):
    terms=['service','database','queue','cache','api','worker','cron','load balancer','docker','kubernetes','redis','postgres','mysql','s3']
    rows=[{'component_line':l} for l in _find_lines(text,terms,80)]
    _add_table(result,'service_inventory',rows)


def runbook_builder(result, project, inputs, customization, text):
    _add_table(result,'runbook_sections',[{'section':'Overview'}, {'section':'Dependencies'}, {'section':'Health checks'}, {'section':'Common alerts'}, {'section':'Rollback'}, {'section':'Escalation'}, {'section':'Post-incident checklist'}])


def schema_parse(result, project, inputs, customization, text):
    rows=[]
    for line in _lines(text):
        if re.search(r'\b(CREATE TABLE|ALTER TABLE|PRIMARY KEY|FOREIGN KEY|VARCHAR|INT|UUID|SERIAL|REFERENCES)\b', line, re.I):
            rows.append({'schema_line':line[:300]})
    _add_table(result,'schema_lines',rows)
    if not rows: _add_table(result,'csv_profile',[_csv_profile(text)])


def data_dictionary(result, project, inputs, customization, text):
    profile=_csv_profile(text)
    rows=[]
    if profile.get('columns'):
        rows=[{'column':c,'null_count':profile.get('null_counts',{}).get(c),'unique_count':profile.get('unique_counts',{}).get(c),'description':'fill from schema/business context'} for c in profile['columns']]
    _add_table(result,'data_dictionary',rows)


def relationship_map(result, project, inputs, customization, text):
    refs=_find_lines(text,['foreign key','references','join','relationship','belongs_to','has_many'],40)
    _add_table(result,'relationship_map',[{'relationship_evidence':l} for l in refs])


def csv_profile(result, project, inputs, customization, text):
    profile=_csv_profile(text)
    _add_table(result, 'csv_profile', [profile])
    if not profile.get('detected'):
        _warning(result, 'medium', 'No delimited dataset detected. Upload CSV/XLSX or paste table data for full profiling.', profile.get('reason'))



def data_quality_rules(result, project, inputs, customization, text):
    profile=_csv_profile(text)
    rows=[]
    if profile.get('detected') and profile.get('columns'):
        for c,n in profile.get('null_counts',{}).items():
            if n: rows.append({'column':c,'issue':'nulls','count':n})
        for c,n in profile.get('unique_counts',{}).items():
            if n==1: rows.append({'column':c,'issue':'constant_value','count':n})
    _add_table(result,'data_quality_issues',rows)


def content_brief(result, project, inputs, customization, text):
    terms=_top_terms(text,20)
    _add_table(result,'seo_content_brief',[{'section':'Search intent','content':'infer from keyword and SERP connector if available'}, {'section':'Outline','content':'H1 + H2s around '+', '.join(terms[:8])}, {'section':'FAQs','content':'Build questions from objections and related entities'}])


def shopify_action_plan(result, project, inputs, customization, text):
    actions=[]
    allowed=str(customization.get('allowed_actions') or '').lower()
    for action in ['read_products','create_product','update_inventory','create_discount','read_orders','customer_segment']:
        permitted=(action in allowed) if allowed else action.startswith('read')
        actions.append({'shopify_action':action,'permitted_by_config':permitted,'requires_approval':not action.startswith('read')})
    _add_table(result,'shopify_action_plan',actions)
    _warning(result,'medium','Live Shopify actions require SHOPIFY_SHOP_DOMAIN and SHOPIFY_ADMIN_ACCESS_TOKEN; write actions require approval gates.',None)


def social_captions(result, project, inputs, customization, text):
    terms=_top_terms(text,12)
    rows=[]
    for platform in ['TikTok','Instagram','Facebook','LinkedIn','X']:
        rows.append({'platform':platform,'caption_structure':f'Hook with {terms[0] if terms else "main benefit"} → value line → CTA','hashtags':', '.join('#'+t.replace('-','') for t in terms[:5])})
    _add_table(result,'social_captions',rows)


def content_calendar(result, project, inputs, customization, text):
    _add_table(result,'content_calendar',[{'day':i+1,'post_type':pt} for i,pt in enumerate(['problem','proof','demo','objection','offer','behind the scenes','faq'],1)])


def sql_builder(result, project, inputs, customization, text):
    request=str(inputs.get('question') or inputs.get('natural_language') or inputs.get('work_brief') or text[:500])
    lower=request.lower()
    sql='-- Need schema to generate safe executable SQL.\nSELECT *\nFROM your_table\nLIMIT 100;'
    if 'count' in lower:
        sql='SELECT COUNT(*) AS row_count\nFROM your_table;'
    elif 'sum' in lower or 'total' in lower:
        sql='SELECT category, SUM(amount) AS total_amount\nFROM your_table\nGROUP BY category\nORDER BY total_amount DESC;'
    _add_table(result,'safe_sql_draft',[{'sql':sql,'assumptions':'Replace table/column names from provided schema. No destructive SQL generated.'}])


def sql_guard(result, project, inputs, customization, text):
    destructive=_find_lines(text,['drop table','delete from','truncate','alter table','update '],40)
    _add_table(result,'sql_safety_review',[{'line':l,'risk':'destructive_or_mutating'} for l in destructive])
    if destructive: _warning(result,'high','Destructive/mutating SQL detected. Require explicit approval and backup.',destructive)


def subtitle_from_text(result, project, inputs, customization, text):
    sents=_sentences(text,20,80)
    rows=[]
    t=0
    for i,s in enumerate(sents[:60],1):
        dur=max(2, min(7, math.ceil(len(s.split())/3)))
        rows.append({'index':i,'start_seconds':t,'end_seconds':t+dur,'text':s[:120]})
        t+=dur
    _add_table(result,'subtitle_draft',rows)
    if not rows: _warning(result,'medium','No transcript text detected. Raw media requires STT connector.',None)


def reading_speed_check(result, project, inputs, customization, text):
    rows=[]
    for row in result['tables'].get('subtitle_draft',[]):
        cps=len(row['text'])/max(1,row['end_seconds']-row['start_seconds'])
        rows.append({'index':row['index'],'chars_per_second':round(cps,1),'status':'too_fast' if cps>20 else 'ok'})
    _add_table(result,'subtitle_reading_speed',rows)


def email_thread_parse(result, project, inputs, customization, text):
    rows=[]
    for l in _find_lines(text,['from:','to:','subject:','quote','price','lead time','moq','payment','shipping','incoterm'],80):
        rows.append({'thread_line':l})
    _add_table(result,'supplier_email_thread',rows)


def tax_doc_classify(result, project, inputs, customization, text):
    docs={'W-2':['w-2','wage and tax'], '1099':['1099','nonemployee'], 'VAT invoice':['vat','tax invoice'], 'Receipt':['receipt','paid'], 'Bank statement':['statement','balance']}
    rows=[]
    low=text.lower()
    for doc,terms in docs.items():
        if any(t in low for t in terms): rows.append({'document_type_candidate':doc,'basis':', '.join([t for t in terms if t in low])})
    _add_table(result,'tax_document_classification',rows or [{'document_type_candidate':'unknown','basis':'Provide recognizable tax form labels or configured classifier.'}])


def amount_extract(result, project, inputs, customization, text):
    _add_table(result,'amount_extract',_amounts(text)[:100])


def test_plan(result, project, inputs, customization, text):
    terms=_top_terms(text,12)
    rows=[]
    for t in terms[:8]:
        rows.append({'test_area':t,'unit_test':f'Validate expected behavior for {t}', 'edge_case':f'Empty/invalid inputs involving {t}'})
    _add_table(result,'test_plan',rows)


def edge_cases(result, project, inputs, customization, text):
    _add_table(result,'edge_cases',[{'case':'empty input'}, {'case':'invalid type'}, {'case':'large file'}, {'case':'network/API failure'}, {'case':'permission denied'}, {'case':'duplicate data'}])


def thumbnail_critique_from_notes(result, project, inputs, customization, text):
    # No fake vision. Analyze only supplied textual notes unless a vision connector is configured.
    lines=_find_lines(text,['thumbnail','face','contrast','text','color','emotion','click','ctr','background','title'],50)
    _add_table(result,'thumbnail_textual_critique',[{'evidence':l,'review':'visual assessment requires uploaded image + vision connector for full accuracy'} for l in lines])
    _warning(result,'medium','Image-only thumbnail analysis requires a configured vision model. This run analyzed text notes only.',None)


def visual_asset_requirements(result, project, inputs, customization, text):
    _add_table(result,'visual_requirements',[{'requirement':'high contrast focal point'}, {'requirement':'readable text at mobile size'}, {'requirement':'single emotional promise'}, {'requirement':'no clutter'}, {'requirement':'A/B variants'}])


def plain_english_risks(result, project, inputs, customization, text):
    rows=[]
    for l in _find_lines(text,['terminate','waive','arbitration','share','sell','track','renew','fee','license','delete','refund'],80):
        rows.append({'plain_english_issue':l,'user_meaning':'Review this clause because it may affect rights, cost, data, or cancellation.'})
    _add_table(result,'plain_english_risks',rows)


def consumer_rights(result, project, inputs, customization, text):
    _add_table(result,'consumer_action_checklist',[{'action':'Check cancellation/renewal'}, {'action':'Check data sharing and deletion'}, {'action':'Check arbitration/class-action waiver'}, {'action':'Check refund and fee clauses'}])


def doc_type_detect(result, project, inputs, customization, text):
    classes={'invoice':['invoice','total due','vat'], 'contract':['agreement','party','term','governing law'], 'resume':['experience','skills','education'], 'bank statement':['balance','transaction','debit','credit'], 'report':['executive summary','financial statements','management discussion']}
    low=text.lower(); rows=[]
    for c,terms in classes.items():
        hits=[t for t in terms if t in low]
        if hits: rows.append({'document_type':c,'hits':hits,'confidence':min(95,30+20*len(hits))})
    _add_table(result,'document_type_detection',rows or [{'document_type':'unknown','hits':[], 'confidence':0}])


def key_value_extract(result, project, inputs, customization, text):
    rows=[]
    for l in _lines(text):
        if ':' in l and len(l)<300:
            k,v=l.split(':',1)
            if 1<=len(k)<=60 and v.strip(): rows.append({'key':k.strip(), 'value':v.strip()[:220]})
    _add_table(result,'key_value_pairs',rows[:120])


def table_extract(result, project, inputs, customization, text):
    profile=_csv_profile(text)
    _add_table(result,'table_profile',[profile])


def video_brief(result, project, inputs, customization, text):
    terms=_top_terms(text,10)
    _add_table(result,'video_brief',[{'section':'Hook','content':f'Open with tension around {terms[0] if terms else "the core problem"}.'}, {'section':'Main beats','content':'problem → stakes → solution → proof → CTA'}, {'section':'Shot list','content':'wide context, close-up problem, demo, proof, CTA card'}])


def cve_parse(result, project, inputs, customization, text):
    cves=sorted(set(re.findall(r'CVE-\d{4}-\d{4,7}',text,re.I)))
    _add_table(result,'cve_ids',[{'cve':c.upper(),'live_enrichment':'requires NVD/GitHub advisory connector; not invented'} for c in cves])
    if not cves: _warning(result,'low','No CVE IDs detected. Provide CVE ID, advisory, or vulnerability finding text.',None)


def remediation_plan(result, project, inputs, customization, text):
    _add_table(result,'remediation_plan',[{'step':'Identify affected assets'}, {'step':'Verify exploitability'}, {'step':'Patch/upgrade or apply mitigation'}, {'step':'Rotate secrets if exposed'}, {'step':'Add regression/security tests'}, {'step':'Document verification evidence'}])


def repo_readme_analyzer(result, project, inputs, customization, text):
    lines=_find_lines(text,['install','usage','features','configuration','api','license','deploy','run','requirements'],80)
    _add_table(result,'repository_readme_analysis',[{'line':l} for l in lines])


def project_inventory(result, project, inputs, customization, text):
    terms=_top_terms(text,20)
    _add_table(result,'project_inventory',[{'detected_term':t} for t in terms])


ALGORITHMS: dict[str, Callable[..., None]] = {name: obj for name, obj in globals().items() if callable(obj) and name not in {'run_algorithm','run_domain_engine','render_engine_markdown'} and not name.startswith('_')}

# ------------------------------- public API ----------------------------------

def run_domain_engine(project: ProjectSpec, inputs: dict[str, Any], customization: dict[str, Any], file_contexts: list[dict[str, Any]]) -> dict[str, Any]:
    result, text, cfg = _base(project, inputs, customization, file_contexts)
    for alg in cfg['algorithms']:
        run_algorithm(alg, result, project, inputs, customization, text)
    threshold = int(float(customization.get('confidence_threshold') or 75)) if str(customization.get('confidence_threshold','')).strip() else 75
    result['scorecards'] = {
        'Input completeness': 100 if not result['validation']['missing_required_inputs'] else max(0, 100-25*len(result['validation']['missing_required_inputs'])),
        'Evidence richness': min(100, 15 + result['input_summary']['source_character_count']//500 + sum(len(v) for v in result['tables'].values() if isinstance(v, list))),
        'External connector readiness': 100 if not result['implementation']['live_connector_status'] else int(100 * sum(1 for c in result['implementation']['live_connector_status'] if c['configured']) / max(1, len(result['implementation']['live_connector_status']))),
        'Export readiness': _readiness_score(result),
    }
    low=[{'scorecard':k,'score':v,'threshold':threshold} for k,v in result['scorecards'].items() if v<threshold]
    if low:
        _warning(result,'medium','One or more scorecards are below selected threshold.',low)
    missing_live=[c for c in result['implementation']['live_connector_status'] if not c['configured']]
    if missing_live:
        _warning(result,'medium','Some live connectors are not configured. Features depending on them return connector requirements instead of fake data.',missing_live)
    result['validation']['ready_for_final_export'] = not result['validation']['missing_required_inputs'] and not any(w['level'] in {'critical'} for w in result['warnings'])
    result['action_items'] = list(dict.fromkeys(result['action_items'] + [
        'Review all warnings before external use.',
        'Configure missing connectors for live data/actions, or keep output as local analysis only.',
        'Use exports only after validating source evidence and jurisdiction/domain-specific rules.',
    ]))
    result['export_payload'] = {
        'project_slug': project.slug,
        'implementation_status': result['implementation']['status'],
        'algorithms': cfg['algorithms'],
        'inputs': inputs,
        'customization': customization,
        'scorecards': result['scorecards'],
        'findings': result['findings'],
        'tables': result['tables'],
        'warnings': result['warnings'],
        'action_items': result['action_items'],
    }
    return result


def render_engine_markdown(result: dict[str, Any]) -> str:
    p=result['project']; impl=result['implementation']
    out=[]
    out.append(f"# {p['name']} — Real Project Engine Result")
    out.append(f"\n**Slug:** `{p['slug']}`  \n**Workflow:** {p['workflow']}  \n**Domain:** {p['domain']}  \n**Engine:** {result['execution']['engine']}  \n")
    out.append('## Real implementation status')
    out.append(f"- Status: **{impl['status']}**")
    out.append(f"- Algorithms executed: `{', '.join(impl['algorithms'])}`")
    out.append(f"- Fake/simulated external data: **disabled**")
    if impl.get('external_connectors'):
        out.append('- Live connectors:')
        for c in impl['live_connector_status']:
            state='configured' if c['configured'] else 'missing'
            out.append(f"  - **{c['connector']}** — {state}; env: `{', '.join(c.get('required_env') or [])}`")
    else:
        out.append('- Live connectors: none required for the local deterministic core.')
    out.append('\n## Scorecards')
    for k,v in result.get('scorecards',{}).items(): out.append(f"- **{k}:** {v}/100")
    out.append('\n## Findings')
    if not result.get('findings'):
        out.append('_No findings generated._')
    for f in result.get('findings',[]):
        out.append(f"### {f.get('title', f.get('type','Finding'))}")
        out.append(str(f.get('detail','')))
        extra={k:v for k,v in f.items() if k not in {'type','title','detail'}}
        if extra:
            out.append('```json\n'+json.dumps(extra, ensure_ascii=False, indent=2)+'\n```')
    out.append('\n## Structured outputs')
    for name, rows in result.get('tables',{}).items():
        out.append(f"### {name.replace('_',' ').title()}")
        if not rows:
            out.append('_No rows._')
            continue
        if isinstance(rows, list) and rows and isinstance(rows[0], dict):
            keys=[]
            for r in rows[:30]:
                for k in r.keys():
                    if k not in keys: keys.append(k)
            out.append('| '+' | '.join(keys)+' |')
            out.append('| '+' | '.join(['---']*len(keys))+' |')
            for r in rows[:50]:
                vals=[]
                for k in keys:
                    val=r.get(k,'')
                    if isinstance(val,(list,dict)): val=json.dumps(val, ensure_ascii=False)
                    vals.append(str(val)[:300].replace('|','/').replace('\n',' '))
                out.append('| '+' | '.join(vals)+' |')
        else:
            out.append('```json\n'+json.dumps(rows[:50] if isinstance(rows,list) else rows, ensure_ascii=False, indent=2)+'\n```')
    out.append('\n## Validation and warnings')
    out.append('```json\n'+json.dumps({'validation':result.get('validation',{}), 'warnings':result.get('warnings',[])}, ensure_ascii=False, indent=2)+'\n```')
    out.append('\n## Action checklist')
    for a in result.get('action_items',[]): out.append(f"- [ ] {a}")
    out.append('\n## Export-ready JSON')
    out.append('```json\n'+json.dumps(result.get('export_payload',{}), ensure_ascii=False, indent=2)+'\n```')
    return '\n'.join(out)
