"""Original API adapters for the privately supplied, pinned upstream mechanics.

No helper is vendored in the public image. Admin must supply a read-only copy via
VIDEO_HELPER_ROOT; client requests cannot choose executables, paths or models.
"""
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import wave
from editing import Rejected

HELPERS = {
    'pcm-assemble': ('skills/defleur-audio/scripts/assemble_pcm.py', '96731e90aac18c4209e4408e0469751e5e8029fe7cb62a4f6795d1e51bde7c1e'),
    'resolve-preset': ('skills/defleur-edit/scripts/preset.py', '5260b709e71a694756e2a9da4088ffb0323f6f4fc02ab4c3ff3c11516b7b75ce'),
}
DEFAULTS_HASH = 'd4992d28e6b0219778e377d696bd6a8db8d5db90bce64f87784d2a4e38f47072'
FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'


def helper(name):
    root = os.environ.get('VIDEO_HELPER_ROOT')
    if not root:
        raise Rejected('Original helper unavailable: administrator must supply the authorized read-only upstream snapshot')
    path, expected = HELPERS[name]
    root = Path(root).resolve()
    file = root / path
    if not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(root):
        raise Rejected('Pinned upstream helper missing')
    if hashlib.sha256(file.read_bytes()).hexdigest() != expected:
        raise Rejected('Pinned upstream helper hash mismatch')
    return file


def capabilities():
    helpers = {}
    for name in HELPERS:
        try:
            helper(name)
            helpers[name] = {'available': True, 'dependency': 'authorized private upstream snapshot'}
        except Rejected as e:
            helpers[name] = {'available': False, 'reason': str(e)}
    return {'operator': 'Hermes or any authenticated client; no autonomous director required',
            'implemented_stages': ['source-audio', *HELPERS], 'helpers': helpers,
            'parity_complete': False, 'unimplemented_api_stages': [
                'asr', 'alignment', 'speech-cut-audit', 'dialogue-lock', 'portrait-face-audit',
                'semantic-browser-capture', 'upstream-caption-encode', 'delivery-gate'],
            'model_downloads': False, 'provider_calls': False}


def validate(stage, value, metadata, validate_plan):
    if stage not in {'source-audio', *HELPERS} or not isinstance(value, dict):
        raise Rejected('Unknown workflow stage or invalid stage body')
    if stage == 'source-audio':
        if value:
            raise Rejected('source-audio takes an empty object')
    elif stage == 'pcm-assemble':
        helper(stage)
        if set(value) != {'segments'}:
            raise Rejected('PCM stage requires only caller-reviewed segments')
        validate_plan(value, metadata['duration'], metadata)
    else:
        helper(stage)
        if set(value) - {'owner', 'project'}:
            raise Rejected('preset stage accepts owner/project JSON objects, not file paths')
        for label, preset in value.items():
            if not isinstance(preset, dict) or preset.get('version', 1) != 1:
                raise Rejected('Unsupported preset JSON')
            caption = preset.get('caption', {})
            if not isinstance(caption, dict) or caption.get('font_path', '') not in {'', FONT}:
                raise Rejected('Only the installed allowlisted font path is accepted')
    return value


def run(stage, value, source, root, metadata, native, input_args, digest):
    root.mkdir(mode=0o700)
    def write(name, obj):
        (root / name).write_text(json.dumps(obj, allow_nan=False, indent=2))
    write('request.json', {'stage': stage, 'input': value, 'source_sha256': metadata['source_sha256']})
    helper_hash = None
    if stage in {'source-audio', 'pcm-assemble'}:
        raw = json.loads(native(['/usr/bin/ffprobe', '-v', 'error', *input_args(),
            '-show_streams', '-show_format', '-of', 'json'], source))
        video = next(s for s in raw['streams'] if s['codec_type'] == 'video')
        fps = Fraction(video['r_frame_rate'])
        if not 0 < fps <= 60:
            raise Rejected('Native workflow supports a positive source cadence up to 60 fps')
        stamps = native(['/usr/bin/ffprobe', '-v', 'error', *input_args(), '-select_streams', 'v:0',
            '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'csv=p=0'], source, timeout=90).decode()
        pts = []
        for row in stamps.splitlines():
            if not row.strip():
                continue
            try:
                pts.append(Fraction(row.split(',')[0]))
            except (ValueError, ZeroDivisionError):
                raise Rejected('Source has incomplete frame timestamps')
        tick = Fraction(video['time_base'])
        tolerance = max(float(tick) * 1.1, .000002)
        cfr = len(pts) >= 2 and abs(float(pts[0])) <= tolerance and all(
            abs(float(t - pts[0] - Fraction(i, 1) / fps)) <= tolerance for i, t in enumerate(pts))
        write('source-probe.json', {'source_sha256': metadata['source_sha256'], 'video': video,
            'audio': next(s for s in raw['streams'] if s['codec_type'] == 'audio'),
            'fps': str(fps), 'frames': len(pts), 'constant_frame_rate': cfr,
            'mapping_support': 'cfr-frame-map' if cfr else 'requires-pts-picture-ledger'})
        native(['/usr/bin/ffmpeg', '-v', 'error', '-xerror', '-n', *input_args(),
            '-map', '0:a:0', '-vn', '-c:a', 'pcm_s16le', '-ar', '48000', '-threads', '1',
            root / 'source.wav'], source, timeout=90, file_limit=128 * 1024 * 1024)
        with wave.open(str(root / 'source.wav')) as pcm:
            pcm_info = {'samples': pcm.getnframes(), 'rate': pcm.getframerate(), 'channels': pcm.getnchannels()}
            if pcm.getsampwidth() != 2 or not pcm.getnframes():
                raise Rejected('PCM decode produced no s16 samples')
        write('pcm-source.json', {**pcm_info, 'sha256': digest(root / 'source.wav')})
        if stage == 'pcm-assemble':
            if not cfr:
                raise Rejected('Upstream PCM picture map requires verified CFR; VFR needs a PTS ledger')
            write('edit-plan.json', value)
            script = helper(stage)
            helper_hash = digest(script)
            native(['/usr/bin/python3', '-I', script, root, '--fps', str(fps), '--source-frames', str(len(pts))],
                   timeout=90, file_limit=128 * 1024 * 1024)
            mapped = json.loads((root / 'edit-map.json').read_text())
            with wave.open(str(root / 'edited.wav')) as edited:
                if edited.getnframes() != mapped['samples']:
                    raise Rejected('Assembled PCM does not match sample ledger')
    else:
        script = helper(stage)
        helper_hash = digest(script)
        defaults = script.parents[3] / 'defaults/neutral-preset.json'
        if defaults.is_symlink() or digest(defaults) != DEFAULTS_HASH:
            raise Rejected('Pinned preset defaults mismatch')
        command = ['/usr/bin/python3', '-I', script, root / 'preset-resolution.json', '--defaults', defaults]
        # Never read an owner Hermes home; caller explicitly supplies the intended JSON.
        for label in ('owner', 'project'):
            if label in value:
                write(label + '-preset.json', value[label])
                command += ['--' + label, root / (label + '-preset.json')]
        native(command, timeout=15)
    artifacts = []
    for path in sorted(root.iterdir()):
        if path.suffix not in {'.json', '.wav'} or not path.is_file() or path.is_symlink():
            raise Rejected('Unexpected helper output')
        artifacts.append({'name': path.name, 'sha256': digest(path), 'bytes': path.stat().st_size,
            'content_type': 'audio/wav' if path.suffix == '.wav' else 'application/json'})
    return {'stage': stage, 'helper_sha256': helper_hash, 'artifacts': artifacts,
            'scope': 'Real mechanics and hash-bound artifacts; not dialogue lock or final delivery approval'}
