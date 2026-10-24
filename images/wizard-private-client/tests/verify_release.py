"""Fresh anonymous GHCR readback and both-platform Docker pull proof."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request

PACKAGE = 'humanitylabs-org/wizard-private-client'
ACCEPT = 'application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json'

def main():
    # No registry publication token or stored login is available in this job.
    for name in ('GH_TOKEN', 'GITHUB_TOKEN', 'DOCKER_AUTH_CONFIG', 'REGISTRY_AUTH_FILE'):
        os.environ.pop(name, None)
    Path(os.environ['HOME']).mkdir(mode=0o700, parents=True, exist_ok=True)
    config = Path(os.environ['DOCKER_CONFIG']); config.mkdir(mode=0o700, parents=True, exist_ok=True)
    (config/'config.json').write_text('{}')
    with urllib.request.urlopen(f'https://ghcr.io/token?service=ghcr.io&scope=repository:{PACKAGE}:pull', timeout=30) as response:
        token=json.load(response)['token']
    def fetch(ref, kind='manifests'):
        request=urllib.request.Request(f'https://ghcr.io/v2/{PACKAGE}/{kind}/{ref}', headers={'Authorization':'Bearer '+token, 'Accept':ACCEPT})
        with urllib.request.urlopen(request, timeout=30) as response: raw=response.read()
        digest='sha256:'+hashlib.sha256(raw).hexdigest()
        return json.loads(raw), digest
    expected=os.environ['DIGEST']; sha=os.environ['EXPECTED_SHA']
    index,digest=fetch(expected); assert digest == expected
    tags=['sha-'+sha]
    release=os.environ.get('RELEASE_VERSION', '')
    if release: tags.append(release)
    for tag in tags: assert fetch(tag)[1] == expected, tag
    platforms={}
    for entry in index['manifests']:
        platform=entry['platform']; arch=platform['architecture']
        if platform['os'] != 'linux' or arch not in ('amd64','arm64'): continue
        child,actual=fetch(entry['digest']); assert actual == entry['digest']
        cfg,actual=fetch(child['config']['digest'],'blobs'); assert actual == child['config']['digest']
        assert cfg['architecture'] == arch and cfg['os'] == 'linux'
        assert cfg['config']['Labels']['org.opencontainers.image.revision'] == sha
        platforms[arch]=entry['digest']
    assert set(platforms) == {'amd64','arm64'}
    for arch in sorted(platforms):
        for ref in [expected,*tags]:
            image=os.environ['IMAGE']+('@' if ref.startswith('sha256:') else ':')+ref
            subprocess.run(['docker','pull','--platform','linux/'+arch,image], check=True)
            subprocess.run(['docker','image','rm',image], check=True)
        print('ANONYMOUS linux/'+arch+' digest and both tags pulled; source='+sha, flush=True)
    print('PUBLIC_INDEX_DIGEST='+expected)

if __name__ == '__main__': main()
