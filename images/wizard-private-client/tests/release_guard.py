"""Fail closed on registry denial; release tags are write-once."""
import base64
import json
import os
import urllib.error
import urllib.request

PACKAGE = 'humanitylabs-org/wizard-private-client'
ACCEPT = 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'

def manifest(tag, token):
    request = urllib.request.Request(f'https://ghcr.io/v2/{PACKAGE}/manifests/{tag}', headers={'Authorization': 'Bearer '+token, 'Accept': ACCEPT})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.headers['Docker-Content-Digest']
    except urllib.error.HTTPError as error:
        if error.code == 404: return None
        raise RuntimeError(f'Registry lookup refused ({error.code}); not evidence of absence') from None

def main():
    basic = base64.b64encode((os.environ['GITHUB_ACTOR']+':'+os.environ['GH_TOKEN']).encode()).decode()
    request = urllib.request.Request(f'https://ghcr.io/token?service=ghcr.io&scope=repository:{PACKAGE}:pull,push', headers={'Authorization':'Basic '+basic})
    with urllib.request.urlopen(request, timeout=30) as response: token=json.load(response)['token']
    version = manifest('0.1.0', token)
    source = manifest('sha-'+os.environ['GITHUB_SHA'], token)
    if version or source:
        if version and version == source:
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output: output.write('digest='+version+'\n')
            print('Reusing existing exact-source immutable release', version)
        else:
            raise RuntimeError('Release/source tag already exists; refusing overwrite. Bump the version.')
    else: print('Both write-once release tags are absent')

if __name__ == '__main__': main()
