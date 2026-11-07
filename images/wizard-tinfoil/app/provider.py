"""Pinned official SDK only. stdin and stdout are private subprocess pipes."""
import datetime
import json
import logging
import sys
logging.disable(logging.CRITICAL)

def run(action, request, factory=None):
    if factory is None:
        from tinfoil import TinfoilAI
        factory = TinfoilAI
    # No direct OpenAI fallback, custom host, transport override or measurement bypass.
    client = factory(api_key=request['key'], timeout=30)
    try:
        client.client.max_retries = 0
        if action == 'verify':
            models = sorted({m.id for m in client.client.models.list().data})
            if not models: raise ValueError('No models')
            return {'models':models, 'verifiedAt':datetime.datetime.now(datetime.timezone.utc).isoformat()}
        if action != 'infer': raise ValueError('Invalid action')
        payload = dict(request['payload'])
        # Kimi K3 on Tinfoil accepts only low/high/max; agents default to medium. Map to the nearest supported level.
        if str(payload.get('model','')).startswith('kimi-k3') and payload.get('reasoning_effort') not in (None,'low','high','max'):
            payload['reasoning_effort'] = {'none':'low','minimal':'low','medium':'high','xhigh':'max'}.get(payload['reasoning_effort'],'high')
        # DeepSeek V4.1 Flash on Tinfoil rejects a reasoning effort; send none.
        if payload.get('model') == 'deepseek-v4-1-flash': payload.pop('reasoning_effort', None)
        extra = {k: payload.pop(k) for k in ('thinking','reasoning','chat_template_kwargs','top_k','min_p','repetition_penalty') if k in payload}
        result = client.chat.completions.create(**payload, **({'extra_body': extra} if extra else {}))
        if request['payload'].get('stream'):
            return {'sse': ''.join('data: '+chunk.model_dump_json()+'\n\n' for chunk in result)+'data: [DONE]\n\n'}
        return result.model_dump(mode='json')
    finally:
        client.client.close()

if __name__ == '__main__':
    try:
        result=run(sys.argv[1],json.load(sys.stdin))
        sys.stdout.write(json.dumps(result))
    except BaseException:
        # Upstream errors may contain authorization headers or response bodies.
        sys.exit(1)
