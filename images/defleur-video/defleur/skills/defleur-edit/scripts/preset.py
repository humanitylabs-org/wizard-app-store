#!/usr/bin/env python3
"""Resolve neutral defaults, owner preset and project override; keep installation immutable."""
import argparse
import copy
import hashlib
import json
import subprocess
from pathlib import Path

def merge(base, extra):
    out = copy.deepcopy(base)
    for key, value in extra.items():
        out[key] = merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else copy.deepcopy(value)
    return out

def resolve(defaults, owner=None, project=None):
    result, sources = {}, []
    for path in [defaults, owner, project]:
        if path is None: continue
        raw = Path(path).read_bytes(); obj = json.loads(raw)
        if not isinstance(obj, dict) or obj.get('version',1) != 1: raise ValueError('Unsupported preset')
        result = merge(result,obj)
        sources.append({'path':str(path),'sha256':hashlib.sha256(raw).hexdigest()})
    if not result['caption']['font_path']:
        font = subprocess.check_output(['fc-match','-f','%{file}','sans-serif:style=Bold'],text=True).strip()
        if not font or not Path(font).is_file(): raise ValueError('Install a readable licensed sans font and fontconfig, or set caption.font_path')
        result['caption']['font_path'] = font
    font = Path(result['caption']['font_path']).expanduser().resolve()
    result['caption']['font_path'] = str(font)
    return {'preset':result,'sources':sources,'font_sha256':hashlib.sha256(font.read_bytes()).hexdigest()}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path); p.add_argument('--defaults',type=Path,default=Path(__file__).resolve().parents[3]/'defaults/neutral-preset.json')
    p.add_argument('--owner',type=Path);p.add_argument('--project',type=Path);a=p.parse_args()
    result=resolve(a.defaults,a.owner,a.project)
    if a.output.exists(): raise ValueError('Output already exists; preserve earlier resolution before changing it')
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
