#!/usr/bin/env python3
"""A CLI fixture: validates isolation before emitting deterministic stream-json."""
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
for flag in ('--safe-mode', '--no-session-persistence', '--strict-mcp-config', '--disable-slash-commands'):
    assert flag in args
assert args[args.index('--setting-sources') + 1] == ''
assert args[args.index('--mcp-config') + 1] == '{"mcpServers":{}}'
assert args[args.index('--tools') + 1] in ('', 'WebSearch')
assert args[args.index('--tools') + 1] == args[args.index('--allowedTools') + 1]
assert not any(k in os.environ for k in ('ANTHROPIC_API_KEY', 'OPENAI_API_KEY', 'CLAUDECODE', 'ANTHROPIC_BASE_URL'))
assert Path(os.environ['CLAUDE_CONFIG_DIR']).parent == Path.cwd().parent
assert not list(Path(os.environ['CLAUDE_CONFIG_DIR']).iterdir())
mode = sys.stdin.read()
model = args[args.index('--model') + 1]
if '--input-format' in args:
    assert os.environ.get('CLAUDE_CODE_DISABLE_THINKING') == '1'
    assert os.environ.get('MAX_THINKING_TOKENS') == '0'
    mode = json.loads(mode)['message']['content']
assistant_model = model
if mode == 'snapshot':
    assistant_model = 'claude-haiku-4-5-20251001'
if mode == 'wrong-snapshot':
    assistant_model = 'claude-haiku-4-5-unknown'
if mode == 'stall':
    import time
    time.sleep(60)
if mode == 'mismatch':
    model = 'wrong-model'
if mode == 'bad-json':
    print('no json', flush=True)
    sys.exit(0)
if mode.startswith('error:'):
    print(json.dumps({'type': 'result', 'is_error': True, 'result': mode[6:]}), flush=True)
    sys.exit(1)
print(json.dumps({'type': 'assistant', 'message': {'model': assistant_model, 'content': []}}), flush=True)
print(json.dumps({'type': 'stream_event', 'event': {'delta': {'type': 'text_delta', 'text': 'hello'}}}), flush=True)
if mode != 'missing':
    result = {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'hello',
              'modelUsage': {model: {}}, 'usage': {'input_tokens': 2, 'output_tokens': 1}}
    if mode == 'denied':
        result['permission_denials'] = [{'tool': 'Read'}]
    if mode == 'no-model':
        result['modelUsage'] = {}
    if mode == 'text-mismatch':
        result['result'] = 'different'
    if mode == 'no-usage':
        result.pop('usage')
    print(json.dumps(result), flush=True)
