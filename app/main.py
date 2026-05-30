from __future__ import annotations
import os, json, shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
load_dotenv()
from . import db
from .security import encrypt_secret, decrypt_secret, mask_secret
from .schemas import ProviderConfig, RunRequest, RunResponse
from .plugin_loader import load_projects, get_project, project_domains
from .file_utils import UPLOAD_DIR, safe_name, extract_text
from .prompt_builder import build_prompt
from .llm_gateway import call_llm, LLMError
from .domain_engine import run_domain_engine, render_engine_markdown
from .exporters import export_job
app=FastAPI(title='AI Suite Platform',version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])
STATIC_DIR=Path(__file__).resolve().parents[1]/'static'; app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')
def seed_default_providers():
    if db.list_providers(): return
    defaults=[
        {'name':'Rule Engine','provider_type':'rule_engine','model':'deterministic-domain-engine-v2','api_key':None,'base_url':None,'endpoint':None,'deployment':None,'enabled':1,'is_local':1,'default_temperature':0.0,'max_tokens':0},
        {'name':'OpenAI','provider_type':'openai','model':'gpt-4.1-mini','api_key':os.getenv('OPENAI_API_KEY') or None,'base_url':None,'endpoint':None,'deployment':None,'enabled':1,'is_local':0,'default_temperature':0.2,'max_tokens':4000},
        {'name':'Anthropic','provider_type':'anthropic','model':'claude-3-5-sonnet-latest','api_key':os.getenv('ANTHROPIC_API_KEY') or None,'base_url':None,'endpoint':None,'deployment':None,'enabled':1,'is_local':0,'default_temperature':0.2,'max_tokens':4000},
        {'name':'Gemini','provider_type':'gemini','model':'gemini-1.5-pro','api_key':os.getenv('GEMINI_API_KEY') or None,'base_url':None,'endpoint':None,'deployment':None,'enabled':1,'is_local':0,'default_temperature':0.2,'max_tokens':4000},
        {'name':'OpenRouter','provider_type':'openrouter','model':'openai/gpt-4o-mini','api_key':os.getenv('OPENROUTER_API_KEY') or None,'base_url':None,'endpoint':None,'deployment':None,'enabled':1,'is_local':0,'default_temperature':0.2,'max_tokens':4000},
        {'name':'Mistral','provider_type':'mistral','model':'mistral-small-latest','api_key':os.getenv('MISTRAL_API_KEY') or None,'base_url':None,'endpoint':None,'deployment':None,'enabled':1,'is_local':0,'default_temperature':0.2,'max_tokens':4000},
        {'name':'Ollama Local','provider_type':'ollama','model':'llama3.1','api_key':None,'base_url':os.getenv('OLLAMA_BASE_URL','http://localhost:11434/v1'),'endpoint':None,'deployment':None,'enabled':1,'is_local':1,'default_temperature':0.2,'max_tokens':4000},
        {'name':'LM Studio Local','provider_type':'lmstudio','model':'local-model','api_key':None,'base_url':os.getenv('LMSTUDIO_BASE_URL','http://localhost:1234/v1'),'endpoint':None,'deployment':None,'enabled':1,'is_local':1,'default_temperature':0.2,'max_tokens':4000},
        {'name':'vLLM Local','provider_type':'vllm','model':'local-model','api_key':None,'base_url':os.getenv('VLLM_BASE_URL','http://localhost:8000/v1'),'endpoint':None,'deployment':None,'enabled':1,'is_local':1,'default_temperature':0.2,'max_tokens':4000},
        {'name':'Azure OpenAI','provider_type':'azure_openai','model':os.getenv('AZURE_OPENAI_DEPLOYMENT','gpt-4o-mini'),'api_key':os.getenv('AZURE_OPENAI_API_KEY') or None,'base_url':None,'endpoint':os.getenv('AZURE_OPENAI_ENDPOINT') or None,'deployment':os.getenv('AZURE_OPENAI_DEPLOYMENT') or None,'enabled':1,'is_local':0,'default_temperature':0.2,'max_tokens':4000},
        {'name':'AWS Bedrock','provider_type':'bedrock','model':'anthropic.claude-3-5-sonnet-20240620-v1:0','api_key':None,'base_url':None,'endpoint':os.getenv('AWS_REGION','us-east-1'),'deployment':None,'enabled':0,'is_local':0,'default_temperature':0.2,'max_tokens':4000}]
    for row in defaults:
        row['encrypted_api_key']=encrypt_secret(row.pop('api_key')); row['updated_at']=db.now(); db.upsert_provider(row)
@app.on_event('startup')
def startup(): db.init_db(); seed_default_providers()
@app.get('/')
def index(): return FileResponse(STATIC_DIR/'index.html')
@app.get('/api/health')
def health(): return {'ok':True,'projects':len(load_projects())}
@app.get('/api/projects')
def projects(): return [p.model_dump() for p in load_projects()]
@app.get('/api/projects/domains')
def domains(): return project_domains()
@app.get('/api/projects/{slug}')
def project(slug:str):
    p=get_project(slug)
    if not p: raise HTTPException(404,'Project not found')
    return p.model_dump()
@app.get('/api/providers')
def providers():
    rows=[]
    for r in db.list_providers():
        r['api_key_masked']=mask_secret(decrypt_secret(r.get('encrypted_api_key'))); r.pop('encrypted_api_key',None); rows.append(r)
    return rows
@app.post('/api/providers')
def save_provider(payload: ProviderConfig):
    row=payload.model_dump(); api_key=row.pop('api_key',None)
    encrypted=(db.get_provider(payload.name) or {}).get('encrypted_api_key') if api_key=='__KEEP__' else encrypt_secret(api_key)
    row['encrypted_api_key']=encrypted; row['enabled']=1 if row.get('enabled') else 0; row['is_local']=1 if row.get('is_local') else 0; row['updated_at']=db.now(); db.upsert_provider(row); return {'ok':True}
@app.post('/api/upload')
async def upload(file: UploadFile = File(...)):
    name=safe_name(file.filename or 'file'); stored=UPLOAD_DIR/f"{db.now().replace(':','').replace('-','')}_{name}"
    with stored.open('wb') as out: shutil.copyfileobj(file.file,out)
    text=extract_text(stored,file.content_type); file_id=db.save_uploaded_file(name,str(stored),file.content_type,stored.stat().st_size,text)
    return {'id':file_id,'name':name,'size_bytes':stored.stat().st_size,'extracted_preview':text[:1200]}
@app.post('/api/run', response_model=RunResponse)
async def run(req: RunRequest):
    project=get_project(req.project_slug)
    if not project: raise HTTPException(404,'Project not found')
    provider=db.get_provider(req.provider_name)
    if not provider: raise HTTPException(404,'Provider not found')
    provider['api_key']=decrypt_secret(provider.get('encrypted_api_key'))
    file_contexts=db.get_uploaded_files(req.uploaded_file_ids)
    job_id=db.create_job(req.project_slug,req.provider_name,req.model or provider.get('model'),req.inputs,req.customization,req.uploaded_file_ids)
    try:
        engine_result=run_domain_engine(project,req.inputs,req.customization,file_contexts)
        if provider.get('provider_type') == 'rule_engine':
            output=render_engine_markdown(engine_result)
            usage={'mode':'deterministic_domain_engine','llm_tokens':0,'modules_applied':engine_result.get('modules_applied',[])}
            db.finish_job(job_id,'completed',output=output,usage=usage)
            return RunResponse(job_id=job_id,status='completed',output=output,usage=usage)
        messages=build_prompt(project,req.inputs,req.customization,file_contexts,req.output_style,engine_result=engine_result)
        result=await call_llm(provider,messages,model=req.model or provider.get('model'),temperature=req.temperature,max_tokens=req.max_tokens)
        output=result['content']
        if not output.strip():
            output=render_engine_markdown(engine_result)
        db.finish_job(job_id,'completed',output=output,usage=result.get('usage'))
        return RunResponse(job_id=job_id,status='completed',output=output,usage=result.get('usage') or {})
    except LLMError as e:
        db.finish_job(job_id,'failed',error=str(e)); raise HTTPException(502,str(e))
    except Exception as e:
        db.finish_job(job_id,'failed',error=f'{type(e).__name__}: {e}'); raise HTTPException(500,f'{type(e).__name__}: {e}')
@app.get('/api/jobs')
def jobs(limit:int=100):
    rows=db.list_jobs(limit)
    for r in rows:
        for k in ['inputs_json','customization_json','uploaded_file_ids_json','usage_json']:
            if k in r and isinstance(r[k],str):
                try: r[k]=json.loads(r[k])
                except Exception: pass
    return rows
@app.get('/api/jobs/{job_id}')
def job(job_id:int):
    r=db.get_job(job_id)
    if not r: raise HTTPException(404,'Job not found')
    for k in ['inputs_json','customization_json','uploaded_file_ids_json','usage_json']:
        if k in r and isinstance(r[k],str):
            try: r[k]=json.loads(r[k])
            except Exception: pass
    return r
@app.get('/api/jobs/{job_id}/export/{fmt}')
def export(job_id:int, fmt:str):
    r=db.get_job(job_id)
    if not r: raise HTTPException(404,'Job not found')
    path=export_job(r,fmt); return FileResponse(path, filename=path.name)


@app.get('/api/project-local-status')
def project_local_status():
    p = load_projects()[0]
    from .domain_engine import PROJECT_IMPLEMENTATIONS
    impl = PROJECT_IMPLEMENTATIONS.get(p.slug, {})
    return {
        'standalone_project_folder': True,
        'project_slug': p.slug,
        'project_name': p.name,
        'registered_local_engine': p.slug in PROJECT_IMPLEMENTATIONS,
        'workflow': impl.get('workflow'),
        'algorithms': impl.get('algorithms', []),
        'connectors': impl.get('connectors', []),
        'fake_external_data_policy': 'disabled; missing live connectors are reported as required setup'
    }
