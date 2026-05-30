from __future__ import annotations
import os, json, asyncio
from typing import Any
import httpx

class LLMError(RuntimeError):
    pass

OPENAI_COMPATIBLE = {'openai','openrouter','mistral','ollama','lmstudio','vllm','custom_openai_compatible'}

async def call_llm(provider: dict[str, Any], messages: list[dict[str,str]], model: str | None=None, temperature: float | None=None, max_tokens: int | None=None) -> dict[str, Any]:
    ptype = provider['provider_type']
    model = model or provider.get('model')
    temperature = provider.get('default_temperature', 0.2) if temperature is None else temperature
    max_tokens = max_tokens or provider.get('max_tokens') or 4000
    if not provider.get('enabled', True):
        raise LLMError(f"Provider {provider.get('name')} is disabled")
    if ptype == 'rule_engine':
        # Handled in app.main before LLM calls. Kept here as a guard.
        return {'content': messages[-1].get('content',''), 'raw': {}, 'usage': {'mode':'rule_engine'}}
    if ptype in OPENAI_COMPATIBLE:
        return await call_openai_compatible(provider, messages, model, temperature, max_tokens)
    if ptype == 'anthropic':
        return await call_anthropic(provider, messages, model, temperature, max_tokens)
    if ptype == 'gemini':
        return await call_gemini(provider, messages, model, temperature, max_tokens)
    if ptype == 'azure_openai':
        return await call_azure_openai(provider, messages, model, temperature, max_tokens)
    if ptype == 'bedrock':
        return await call_bedrock(provider, messages, model, temperature, max_tokens)
    raise LLMError(f'Unsupported provider_type: {ptype}')

async def call_openai_compatible(provider, messages, model, temperature, max_tokens):
    ptype = provider['provider_type']
    api_key = provider.get('api_key') or ''
    base_url = provider.get('base_url')
    if not base_url:
        base_url = {
            'openai': 'https://api.openai.com/v1',
            'openrouter': 'https://openrouter.ai/api/v1',
            'mistral': 'https://api.mistral.ai/v1',
            'ollama': 'http://localhost:11434/v1',
            'lmstudio': 'http://localhost:1234/v1',
            'vllm': 'http://localhost:8000/v1',
        }.get(ptype)
        if not base_url:
            raise LLMError('base_url is required for custom OpenAI-compatible providers')
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'
    if ptype == 'openrouter':
        headers.update({'HTTP-Referer': 'http://localhost', 'X-Title': 'AI Suite Platform'})
    payload = {'model': model, 'messages': messages, 'temperature': temperature, 'max_tokens': max_tokens}
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(base_url.rstrip('/') + '/chat/completions', headers=headers, json=payload)
    if r.status_code >= 400:
        raise LLMError(f'{ptype} API error {r.status_code}: {r.text[:1000]}')
    data = r.json()
    return {'content': data.get('choices', [{}])[0].get('message', {}).get('content', ''), 'raw': data, 'usage': data.get('usage', {})}

async def call_anthropic(provider, messages, model, temperature, max_tokens):
    api_key = provider.get('api_key')
    if not api_key:
        raise LLMError('Anthropic API key is required')
    system = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
    user_msgs = [{'role': m['role'] if m['role'] in {'user','assistant'} else 'user', 'content': m['content']} for m in messages if m['role'] != 'system']
    headers = {'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'Content-Type': 'application/json'}
    payload = {'model': model, 'system': system, 'messages': user_msgs, 'temperature': temperature, 'max_tokens': max_tokens}
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post('https://api.anthropic.com/v1/messages', headers=headers, json=payload)
    if r.status_code >= 400:
        raise LLMError(f'Anthropic API error {r.status_code}: {r.text[:1000]}')
    data = r.json()
    return {'content': ''.join(b.get('text','') for b in data.get('content', []) if b.get('type') == 'text'), 'raw': data, 'usage': data.get('usage', {})}

async def call_gemini(provider, messages, model, temperature, max_tokens):
    api_key = provider.get('api_key')
    if not api_key:
        raise LLMError('Gemini API key is required')
    text = '\n\n'.join(f"{m['role'].upper()}: {m['content']}" for m in messages)
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}'
    payload = {'contents': [{'parts': [{'text': text}]}], 'generationConfig': {'temperature': temperature, 'maxOutputTokens': max_tokens}}
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(url, json=payload)
    if r.status_code >= 400:
        raise LLMError(f'Gemini API error {r.status_code}: {r.text[:1000]}')
    data = r.json()
    candidates = data.get('candidates') or []
    content = ''.join(p.get('text','') for p in candidates[0].get('content', {}).get('parts', [])) if candidates else ''
    return {'content': content, 'raw': data, 'usage': data.get('usageMetadata', {})}

async def call_azure_openai(provider, messages, model, temperature, max_tokens):
    api_key = provider.get('api_key')
    endpoint = (provider.get('endpoint') or '').rstrip('/')
    deployment = provider.get('deployment') or model
    if not endpoint or not api_key or not deployment:
        raise LLMError('Azure OpenAI endpoint, deployment, and API key are required')
    url = f'{endpoint}/openai/deployments/{deployment}/chat/completions?api-version=2024-10-21'
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(url, headers={'api-key': api_key, 'Content-Type': 'application/json'}, json={'messages': messages, 'temperature': temperature, 'max_tokens': max_tokens})
    if r.status_code >= 400:
        raise LLMError(f'Azure OpenAI API error {r.status_code}: {r.text[:1000]}')
    data = r.json()
    return {'content': data.get('choices', [{}])[0].get('message', {}).get('content', ''), 'raw': data, 'usage': data.get('usage', {})}

async def call_bedrock(provider, messages, model, temperature, max_tokens):
    try:
        import boto3
    except ImportError as e:
        raise LLMError('Install boto3 to use AWS Bedrock provider') from e
    region = provider.get('endpoint') or os.getenv('AWS_REGION') or 'us-east-1'
    client = boto3.client('bedrock-runtime', region_name=region)
    prompt = '\n\n'.join(f"{m['role'].upper()}: {m['content']}" for m in messages)
    body = json.dumps({'messages': [{'role': 'user', 'content': [{'text': prompt}]}], 'inferenceConfig': {'temperature': temperature, 'maxTokens': max_tokens}})
    resp = await asyncio.to_thread(lambda: client.invoke_model(modelId=model, body=body, contentType='application/json', accept='application/json'))
    data = json.loads(resp['body'].read())
    try:
        content = data['output']['message']['content'][0]['text']
    except Exception:
        content = json.dumps(data, ensure_ascii=False)
    return {'content': content, 'raw': data, 'usage': data.get('usage', {})}
