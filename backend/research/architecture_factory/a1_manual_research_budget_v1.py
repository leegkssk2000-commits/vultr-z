"""Bounded manual transport audit for the existing Gemini search/video helpers."""
from __future__ import annotations
import hashlib
import json
import urllib.request
from datetime import datetime, timezone


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()


class ManualRequestBudget:
    def __init__(self, max_search=1, max_video=3, max_output_tokens=3500,
                 max_prompt_bytes=18000, max_video_seconds=600):
        if not (0 <= max_search <= 1 and 0 <= max_video <= 3):
            raise ValueError('MANUAL_REQUEST_CAP')
        self.caps = {'search': max_search, 'video': max_video}
        self.max_output_tokens = min(max_output_tokens, 3500)
        self.max_prompt_bytes = min(max_prompt_bytes, 18000)
        self.max_video_seconds = min(max_video_seconds, 600)
        self.requests = []
        self.available = None

    def models(self, api_key, preferred):
        if self.available is None:
            req = urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models',
                                         headers={'x-goog-api-key': api_key})
            record = {'kind': 'model_catalog', 'status': 'ATTEMPTED', 'paid_generation': False}
            self.requests.append(record)
            try:
                with urllib.request.urlopen(req, timeout=20) as response:
                    payload = json.load(response)
                self.available = [x['name'] for x in payload.get('models', [])
                                  if 'generateContent' in x.get('supportedGenerationMethods', [])]
                record.update(status='SUCCESS', response_sha256=sha(payload))
            except Exception as exc:
                record.update(status='FAILED', error_type=type(exc).__name__)
                self.available = []
                raise
        # No unapproved model fallback; one eligible preferred model only.
        return [m for m in preferred if m in self.available][:1]

    def send(self, req, timeout, kind):
        if sum(x['kind'] == kind for x in self.requests) >= self.caps[kind]:
            raise RuntimeError('MANUAL_REQUEST_BUDGET_EXHAUSTED')
        body = json.loads(req.data)
        parts = body['contents'][0]['parts']
        prompt = ''.join(x.get('text', '') for x in parts)
        if len(prompt.encode()) > self.max_prompt_bytes:
            raise RuntimeError('PROMPT_INPUT_CAP')
        body['generationConfig']['maxOutputTokens'] = min(
            body['generationConfig']['maxOutputTokens'], self.max_output_tokens)
        if kind == 'video':
            videos = [x for x in parts if 'file_data' in x]
            if len(videos) != 1:
                raise RuntimeError('ONE_ACTUAL_VIDEO_INPUT_REQUIRED')
            videos[0]['videoMetadata'] = {'startOffset': '0s',
                                         'endOffset': f'{self.max_video_seconds}s', 'fps': 0.2}
        encoded_body = json.dumps(body).encode()
        record = {'kind': kind, 'status': 'ATTEMPTED', 'paid_generation': True,
                  'model': req.full_url.split('/v1beta/')[1].split(':')[0],
                  'at_utc': datetime.now(timezone.utc).isoformat(),
                  'request_sha256': sha(body), 'request_body':body, 'prompt_sha256': sha(prompt),
                  'raw_request_sha256': hashlib.sha256(encoded_body).hexdigest(),
                  'prompt_bytes': len(prompt.encode()),
                  'max_output_tokens': body['generationConfig']['maxOutputTokens'],
                  'video_window_seconds': self.max_video_seconds if kind == 'video' else None,
                  'video_input': kind == 'video', 'usage': None, 'cost_usd': None}
        self.requests.append(record)  # failed/partial attempts consume budget too
        bounded = urllib.request.Request(req.full_url, data=encoded_body,
                                         headers=dict(req.header_items()), method='POST')
        try:
            with urllib.request.urlopen(bounded, timeout=timeout) as response:
                raw_response = response.read()
                record['raw_response_sha256'] = hashlib.sha256(raw_response).hexdigest()
                payload = json.loads(raw_response)
            record.update(status='SUCCESS', response_sha256=sha(payload),
                          usage=payload.get('usageMetadata'), model_version=payload.get('modelVersion'), response_payload=payload)
            return payload
        except Exception as exc:
            record.update(status='FAILED', error_type=type(exc).__name__,
                          http_status=getattr(exc, 'code', None))
            raise RuntimeError('MANUAL_PROVIDER_REQUEST_FAILED:' + type(exc).__name__) from None

    def receipt(self):
        return {'limits': self.caps, 'retries': 0, 'fallbacks': 0,
                'max_prompt_bytes': self.max_prompt_bytes, 'max_video_seconds': self.max_video_seconds,
                'max_output_tokens_per_request': self.max_output_tokens,
                'requests': self.requests,
                'generation_requests': sum(x['paid_generation'] for x in self.requests),
                'cost_usd': 0 if not any(x['paid_generation'] for x in self.requests) else None,
                'cost_status': 'NO_GENERATION_REQUEST' if not any(x['paid_generation'] for x in self.requests)
                               else 'UNVERIFIED_REQUIRES_USAGE_AND_CURRENT_PRICE'}
