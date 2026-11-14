#!/usr/bin/env python3
"""Disposable Docker proof. No provider credential is copied to a file or printed."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'pp-test-client'
NETWORK = PREFIX
EGRESS = PREFIX + '-egress'
CLIENT = PREFIX + '-sidecar'
RELAY = PREFIX + '-relay'
IMAGE = PREFIX + ':test'
TEST_IMAGE = PREFIX + ':unit'
RELAY_IMAGE = PREFIX + '-relay:test'


def run(*args, env=None, check=True):
    result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True)
    if check and result.returncode:
        # Container env is never included in arguments or failure diagnostics.
        raise RuntimeError(f'{args[0:3]} failed ({result.returncode}): {result.stdout[-3000:]} {result.stderr[-3000:]}')
    return result.stdout.strip()


def probe(code):
    result = run('docker', 'exec', CLIENT, 'node', '--input-type=module', '-e', code)
    return json.loads(result)


def request(body):
    return probe(f"const r=await fetch('http://127.0.0.1:3301/v1/chat/completions',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({json.dumps(body)})}}); console.log(JSON.stringify({{status:r.status,body:await r.text()}}));")


def start_client(directory, profile='tinfoil', bad_token=False):
    run('docker', 'rm', '-f', CLIENT, check=False)
    token = directory / ('bad-token' if bad_token else 'token')
    run('docker', 'run', '-d', '--name', CLIENT, '--network', NETWORK,
        '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
        '--env', 'PROFILE=' + profile, '--env', 'RELAY_URL=http://' + RELAY + ':8090',
        '--env', 'MODELS=llama3-3-70b', '--env', 'CACHE_SECRET_FILE=/run/wizard/cache-secret',
        '--mount', f'type=bind,src={token},dst=/run/wizard/relay-token,readonly',
        '--mount', f'type=bind,src={directory / "cache-secret"},dst=/run/wizard/cache-secret,readonly', IMAGE)
    for _ in range(60):
        try:
            if probe("const r=await fetch('http://127.0.0.1:3301/healthz');console.log(JSON.stringify(r.status));") == 200:
                return
        except RuntimeError:
            time.sleep(.2)
    raise RuntimeError('Client did not start (configuration or mounted file ownership)')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--key-env-file', type=Path)
    parser.add_argument('--model', default='llama3-3-70b')
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args()
    env = os.environ.copy()
    # Load only in process memory; Docker inherits this env into the stand-in relay.
    if args.live:
        if not args.key_env_file:
            parser.error('--live requires --key-env-file')
        values = {}
        for line in args.key_env_file.read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip().strip('"\'')
        key = values.get('TINFOIL_API_KEY') or values.get('TINFOIL_KEY')
        if not key:
            raise RuntimeError('Expected TINFOIL_API_KEY or TINFOIL_KEY in supplied env file')
        env['TINFOIL_API_KEY'] = key
    env['RELAY_TOKEN'] = secrets.token_urlsafe(40)
    directory = Path(tempfile.mkdtemp(prefix=PREFIX + '-', dir=os.environ.get('TMPDIR')))
    os.chmod(directory, 0o755)
    containers = [CLIENT, RELAY]
    try:
        capture_dir = directory / 'capture'
        capture_dir.mkdir(mode=0o777)
        os.chmod(capture_dir, 0o777)
        for name, value in [('token', env['RELAY_TOKEN']), ('bad-token', secrets.token_urlsafe(40)), ('cache-secret', secrets.token_urlsafe(40))]:
            path = directory / name
            path.write_text(value)
            os.chmod(path, 0o400)
            if os.getuid() != 1000:
                # Docker is already required: use a disposable root container for ownership.
                run('docker', 'run', '--rm', '--name', PREFIX + '-chown', '--network', 'none', '--user', '0:0', '--mount', f'type=bind,src={directory},dst=/scratch', '--entrypoint', 'chown', 'node:22-alpine', '1000:1000', '/scratch/' + name)
        if not args.skip_build:
            for tag, extra in [(IMAGE, []), (TEST_IMAGE, ['--target', 'test']), (RELAY_IMAGE, ['-f', 'tests/Dockerfile.relay'])]:
                output = run('docker', 'build', '-t', tag, *extra, '.')
                print('BUILD', tag, 'OK', flush=True)
        print(run('docker', 'run', '--rm', '--name', PREFIX + '-unit', '--network', 'none', '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m', '--cap-drop=ALL', '--security-opt=no-new-privileges:true', TEST_IMAGE), flush=True)
        run('docker', 'network', 'create', '--internal', '--subnet', '10.252.251.0/24', NETWORK)
        run('docker', 'network', 'create', EGRESS)
        run('docker', 'run', '-d', '--name', RELAY, '--network', NETWORK,
            '--read-only', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
            '--env', 'RELAY_TOKEN', '--env', 'TINFOIL_API_KEY',
            '--mount', f'type=bind,src={capture_dir},dst=/capture', RELAY_IMAGE, env=env)
        run('docker', 'network', 'connect', EGRESS, RELAY)
        start_client(directory)
        state = json.loads(run('docker', 'inspect', '--format', '{{json .HostConfig}}', CLIENT))
        assert state['ReadonlyRootfs'] and 'ALL' in state['CapDrop'] and 'no-new-privileges:true' in state['SecurityOpt']
        assert run('docker', 'inspect', '--format', '{{.Config.User}}', CLIENT) == '1000:1000'
        assert json.loads(run('docker', 'inspect', '--format', '{{json .NetworkSettings.Networks}}', CLIENT)).keys() == {NETWORK}
        assert run('docker', 'network', 'inspect', '--format', '{{.Internal}}', NETWORK) == 'true'
        print('RUNTIME non-root=1000:1000 read-only=true cap-drop=ALL no-new-privileges=true networks=[internal-only]', flush=True)
        isolation = probe("try {await fetch('https://example.com',{signal:AbortSignal.timeout(3000)}); console.log('false')} catch {console.log('true')}")
        assert isolation
        print('ISOLATION sidecar direct internet BLOCKED', flush=True)
        assert probe(f"const r=await fetch('http://{RELAY}:8090/attestation');console.log(JSON.stringify(r.status))") == 401
        print('RELAY missing token -> 401', flush=True)
        model_list = probe("const r=await fetch('http://127.0.0.1:3301/v1/models');console.log(JSON.stringify(await r.json()))")
        assert model_list['data'][0]['id'] == 'llama3-3-70b'
        print('MODELS tinfoil static list -> 200', flush=True)

        if args.live:
            print('LIVE model=' + args.model, flush=True)
            codeword = 'PRIVPROBE-' + secrets.token_hex(12)
            body = {'model': args.model, 'messages': [{'role': 'user', 'content': 'Reply with exactly this codeword and nothing else: ' + codeword}], 'max_tokens': 100, 'temperature': 0}
            for streaming in [False, True]:
                result = request({**body, 'stream': streaming})
                if result['status'] != 200:
                    # Sanitized sidecar errors only; never relay env or upstream error contents.
                    raise RuntimeError(f'Live stream={streaming}: status={result["status"]} {result["body"]}')
                if streaming:
                    events = [line[6:] for line in result['body'].splitlines() if line.startswith('data: ')]
                    assert '[DONE]' in events
                    text = ''.join(json.loads(event).get('choices', [{}])[0].get('delta', {}).get('content', '') or '' for event in events if event != '[DONE]' and json.loads(event).get('choices'))
                else:
                    text = json.loads(result['body'])['choices'][0]['message']['content']
                assert codeword in text, 'Completion did not return probe codeword'
                print(f'LIVE stream={str(streaming).lower()} status=200 answer_contains_codeword=true', flush=True)
            captured = (capture_dir / 'requests.bin').read_bytes()
            assert captured.count(b'Ehbp-Encapsulated-Key: ') == 2 and b'Ehbp-Encapsulated-Key: MISSING' not in captured
            assert codeword.encode() not in captured
            assert (directory / 'cache-secret').read_bytes() not in captured
            assert env['TINFOIL_API_KEY'].encode() not in captured
            print(f'CAPTURE requests=2 bytes={len(captured)} Ehbp-Encapsulated-Key=2 raw_codeword_occurrences=0 raw_cache_secret_occurrences=0 provider_key_occurrences=0', flush=True)
            for mode in ['tampered', 'wrong-domain', 'wrong-enclave']:
                (capture_dir / 'mode').write_text(mode)
                start_client(directory)
                before = (capture_dir / 'requests.bin').read_bytes()
                result = request(body)
                assert result['status'] == 502
                assert json.loads(result['body'])['error']['code'] == 'relay_failed'
                after = (capture_dir / 'requests.bin').read_bytes()
                if mode != 'wrong-enclave':
                    assert before == after, 'Attestation failure sent inference traffic'
                assert codeword.encode() not in after
                print(f'FAIL-CLOSED mode={mode} -> 502 JSON plaintext_retry=false', flush=True)
            (capture_dir / 'mode').write_text('normal')
            start_client(directory, bad_token=True)
            assert request(body)['status'] == 502
            print('FAIL-CLOSED revoked/invalid relay token -> 502 JSON', flush=True)
            for name in containers:
                logs = run('docker', 'logs', name)
                assert codeword not in logs and env['TINFOIL_API_KEY'] not in logs
            print('LOGS sidecar+relay codeword_occurrences=0 provider_key_occurrences=0', flush=True)
        (capture_dir / 'mode').write_text('mock')
        start_client(directory, profile='passthrough')
        for stream in [False, True]:
            result = request({'model': 'mock-local', 'messages': [], 'stream': stream})
            assert result['status'] == 200 and 'mock-ok' in result['body']
            print(f'PASSTHROUGH stream={str(stream).lower()} -> 200 mock-ok', flush=True)
        model_list = probe("const r=await fetch('http://127.0.0.1:3301/v1/models');console.log(JSON.stringify(await r.json()))")
        assert model_list['data'][0]['id'] == 'mock-local'
        print('PASSTHROUGH /v1/models -> relay list', flush=True)
        run('docker', 'stop', RELAY)
        assert request({'model': 'mock-local', 'messages': []})['status'] == 502
        print('FAIL-CLOSED stopped relay -> 502 JSON', flush=True)
    finally:
        for name in containers + [PREFIX + '-unit', PREFIX + '-chown']:
            run('docker', 'rm', '-f', name, check=False)
        for network in [NETWORK, EGRESS]:
            run('docker', 'network', 'rm', network, check=False)
        for image in [IMAGE, TEST_IMAGE, RELAY_IMAGE]:
            run('docker', 'image', 'rm', image, check=False)
        shutil.rmtree(directory)
        remaining = run('docker', 'ps', '-a', '--filter', 'name=pp-test-client', '--format', '{{.Names}}')
        networks = run('docker', 'network', 'ls', '--filter', 'name=pp-test-client', '--format', '{{.Name}}')
        images = run('docker', 'image', 'ls', '--filter', 'reference=pp-test-client*', '--format', '{{.Repository}}:{{.Tag}}')
        assert not remaining and not networks and not images
        print('CLEANUP containers=0 networks=0 images=0 scratch=removed', flush=True)


if __name__ == '__main__':
    main()
