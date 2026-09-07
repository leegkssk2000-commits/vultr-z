"""Explicit one-shot DEV dossier pilot; no search, fallback or automatic retry."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import urllib.request
from backend.research.rebuild.lifecycle_task_v1 import Registry, SCOPE, GateError, digest, utc

OUTPUT = Path('research/development_evidence/TOP5_LIFECYCLE_AI_G5_AFTER_PR1204')
ROUTES = {'gemini': 'https://generativelanguage.googleapis.com/v1beta', 'openai': 'https://api.openai.com/v1/responses'}

def preflight(dossier, approval, quote, *, event, key_present):
    if event != 'workflow_dispatch' or not approval.get('explicit_manual_approval'): raise GateError('MANUAL_ONLY')
    if approval.get('scope_key') != SCOPE or not approval.get('approval_id'): raise GateError('APPROVAL_ID_SCOPE')
    if not key_present: raise GateError('PROVIDER_KEY_UNAVAILABLE')
    if dossier.get('data_class') != 'DEV_USED' or dossier.get('holdout_access') is not False: raise GateError('DEV_ISOLATION')
    if not dossier.get('source_hashes') or approval.get('dossier_sha') != digest(dossier): raise GateError('DOSSIER_BINDING')
    provider = approval.get('provider'); model = approval.get('model')
    if provider not in ROUTES or not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}',model) or quote.get('provider') != provider or quote.get('model') != model:
        raise GateError('SINGLE_ALLOWLISTED_MODEL')
    if approval.get('price_sha') != digest(quote) or model not in approval.get('allowlisted_models', []): raise GateError('PRICE_BINDING')
    if not quote.get('official_source_url') or not quote.get('checked_at') or quote.get('currency') != 'USD': raise GateError('PRICE_AUTHORITY')
    if quote.get('adapter_verified') is not True or quote.get('combined_output_thinking_cap_verified') is not True:
        raise GateError('TOKEN_LIMIT_SEMANTICS_UNVERIFIED')
    if quote.get('tools_disabled') is not True or quote.get('cache_disabled') is not True: raise GateError('UNBOUNDED_TOOLS_OR_CACHE')
    if quote.get('tax_fx_upper_bound_usd') is None: raise GateError('BILLING_COMPONENT_UNKNOWN')
    # Fixed UTF-8 dossier byte length is a conservative token upper bound for
    # the approved tokenizer contract; no paid token-count endpoint is called.
    prompt = json.dumps(dossier, sort_keys=True, ensure_ascii=False)
    nbytes = len(prompt.encode())
    if quote.get('utf8_bytes_bound_tokens_verified') is not True or nbytes > 16000: raise GateError('INPUT_TOKEN_BOUND')
    for field in ('input_usd_per_million', 'output_thinking_usd_per_million', 'tax_fx_upper_bound_usd'):
        if not isinstance(quote.get(field), (int,float)) or not 0 <= quote[field] < float('inf'): raise GateError('INVALID_PRICE')
    maximum = 16000 * quote['input_usd_per_million']/1e6 + 6000 * quote['output_thinking_usd_per_million']/1e6 + quote['tax_fx_upper_bound_usd']
    if not 0 < maximum <= 5: raise GateError('PER_REQUEST_USD_CAP')
    return {'provider': provider, 'model': model, 'prompt': prompt, 'prompt_sha': hashlib.sha256(prompt.encode()).hexdigest(),
            'maximum_reserved_usd': maximum, 'input_token_upper_bound': nbytes, 'output_thinking_cap': 6000,
            'price_sha': digest(quote), 'dossier_sha': digest(dossier)}

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise GateError('PROVIDER_REDIRECT_FORBIDDEN')

def verify_dossier_sources(dossier):
    # Same frozen owner used by the economic entrypoint. Only its preapproved
    # DEV files may be opened; no user-supplied source or observer paths.
    from backend.research.rebuild.top5_lifecycle_v1 import authorize, ROOT
    spec=authorize()
    if digest(dossier)!=spec['dossier_sha'] or dossier['source_hashes']!=spec['dossier_source_hashes']:
        raise GateError('FROZEN_DOSSIER_ALLOWLIST')
    for path,sha in spec['dossier_source_hashes'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=sha: raise GateError('DEV_SOURCE_BYTES')

def request_once(registry, dossier, approval, quote, *, event, transport=None, key=None):
    verify_dossier_sources(dossier)
    provider = approval.get('provider')
    if key is None:
        key = os.getenv('GEMINI_API_KEY' if provider == 'gemini' else 'OPENAI_API_KEY', '')
    plan = preflight(dossier, approval, quote, event=event, key_present=bool(key))
    identity = {'provider': provider, 'model': plan['model'], 'dossier': plan['dossier_sha'], 'prompt': plan['prompt_sha']}
    attempt = registry.reserve(SCOPE, 'W2', 'api', identity, provider=provider, reserve_usd=plan['maximum_reserved_usd'])
    body = ({'contents': [{'role':'user','parts':[{'text':plan['prompt']}]}],
             'generationConfig': {'maxOutputTokens':6000,'responseMimeType':'application/json'}} if provider == 'gemini' else
            {'model':plan['model'],'input':plan['prompt'],'max_output_tokens':6000,'store':False})
    route = ROUTES[provider]+('/models/'+plan['model']+':generateContent' if provider == 'gemini' else '')
    headers = {'Content-Type':'application/json', **({'x-goog-api-key':key} if provider=='gemini' else {'Authorization':'Bearer '+key})}
    req = urllib.request.Request(route,data=json.dumps(body).encode(),headers=headers,method='POST')
    receipt = {'scope_key':SCOPE,'attempt_id':attempt,'approval_id':approval['approval_id'],
        'purpose':dossier['purpose'],'provider':provider,'route':route,'model':plan['model'],
        'dossier_sha':plan['dossier_sha'],'prompt_sha':plan['prompt_sha'],'price_sha':plan['price_sha'],
        'started_at':utc(),'max_reserved':plan['maximum_reserved_usd'],'settled_cost':None,
        'billing_status':'UNKNOWN','retry':False,'fallback':False,'formal_credit':0,'http_status':None}
    try:
        opener = transport or urllib.request.build_opener(NoRedirect()).open
        with opener(req, timeout=45) as response:
            payload = json.loads(response.read(2_000_001))
            receipt.update(http_status=response.status, response_id=payload.get('id',payload.get('responseId')),
                usage=payload.get('usage',payload.get('usageMetadata')), response_sha=digest(payload), response=payload)
        registry.finish_attempt(SCOPE,attempt,'DONE',evidence={'response_sha':receipt['response_sha']})
    except Exception as exc:
        receipt.update(error_type=type(exc).__name__,usage=None)
        registry.finish_attempt(SCOPE,attempt,'UNKNOWN',evidence={'error_type':type(exc).__name__})
    receipt['ended_at']=utc()
    return receipt

def main():
    p=argparse.ArgumentParser();p.add_argument('--approval',type=Path);p.add_argument('--no-network',action='store_true');args=p.parse_args()
    dossier=json.loads((OUTPUT/'DOSSIER.json').read_text())
    verify_dossier_sources(dossier)
    report={'scope_key':SCOPE,'paid_requests':0,'settled_cost':0,'outstanding_reserved_cost':0,'billing_status':'NOT_CALLED',
        'dossier_sha':digest(dossier),'model':None,'reason':'NO_EXPLICIT_PREFLIGHT_PACKAGE','formal_credit':0}
    if args.approval and not args.no_network:
        # A fresh Actions checkout is not a durable cross-run budget ledger.
        # Fail closed until a reviewed remote reservation owner is supplied.
        if os.getenv('GITHUB_ACTIONS') == 'true': raise GateError('REMOTE_DURABLE_RESERVATION_OWNER_UNBOUND')
        if args.approval.resolve().parent != OUTPUT.resolve(): raise GateError('APPROVAL_PATH_OUTSIDE_SCOPE')
        approval=json.loads(args.approval.read_text());quote=json.loads((OUTPUT/'API_PRICE.json').read_text())
        report=request_once(Registry(OUTPUT/'TASK.json'),dossier,approval,quote,event=os.getenv('GITHUB_EVENT_NAME','local'))
    out=Path('out/top5-ai-pilot.json');out.parent.mkdir(exist_ok=True);out.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'response'}))

if __name__=='__main__':main()
