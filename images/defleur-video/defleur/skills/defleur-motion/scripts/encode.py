#!/usr/bin/env python3
"""Composite every captured frame with captions, then encode and verify exact media."""
import argparse, hashlib, json, subprocess
from fractions import Fraction
from pathlib import Path
from PIL import Image
from caption_layer import caption_engine

def digest(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def verify(project, final):
    timeline=json.loads((project/'locked-timeline.json').read_text())
    rate=Fraction(str(timeline['fps'])); width,height=timeline.get('canvas',[1080,1920])
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-count_frames','-show_streams','-show_format','-of','json',str(final)],text=True))
    video=next(x for x in probe['streams'] if x['codec_type']=='video')
    audio=next(x for x in probe['streams'] if x['codec_type']=='audio')
    if (video['width'],video['height'])!=(width,height) or int(video['nb_read_frames'])!=timeline['frames']: raise ValueError('Encoded dimensions/frame count mismatch')
    if Fraction(video['avg_frame_rate'])!=rate: raise ValueError('Encoded cadence mismatch')
    if abs(float(audio['duration'])-timeline['duration']) > max(float(1/rate),.05): raise ValueError('Encoded audio duration mismatch')
    subprocess.run(['ffmpeg','-v','error','-xerror','-i',str(final),'-f','null','-'],check=True)
    return {'sha256':digest(final),'full_decode_pass':True,'width':width,'height':height,'frames':int(video['nb_read_frames']),'fps':str(rate),'audio_duration':float(audio['duration']),'scope':'Exact-file decode and numeric media checks; semantic/audio perception requires separate review.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('project',type=Path);p.add_argument('--verify-only',action='store_true');a=p.parse_args();root=a.project
    final=root/'final.mp4'
    if not a.verify_only:
        if final.exists(): raise ValueError('Preserve existing final before creating a candidate')
        timeline=json.loads((root/'locked-timeline.json').read_text());rate=str(timeline['fps']);frames=timeline['frames'];width,height=timeline.get('canvas',[1080,1920])
        capture=json.loads((root/'capture-full.json').read_text())
        if capture['indices']!=list(range(frames)): raise ValueError('Full capture is incomplete')
        plan=json.loads((root/'visual-plan.json').read_text())
        suppress=timeline.get('caption_suppressions',timeline.get('caption_suppress',plan.get('caption_suppressions',plan.get('caption_suppress',[]))))
        for row in suppress:
            if not row.get('reason') or not any(b.get('caption_treatment')=='suppress' and b['start']<=row['start']<row['end']<=b['end'] for b in plan['beats']): raise ValueError('Undeclared caption suppression')
        draw=caption_engine(root);rows=[]
        cmd=['ffmpeg','-v','error','-n','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width}x{height}','-r',rate,'-i','pipe:0','-i',str(root/'edited.wav'),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-threads','4','-preset','medium','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-movflags','+faststart',str(final)]
        process=subprocess.Popen(cmd,stdin=subprocess.PIPE)
        if process.stdin is None: raise RuntimeError('Encoder stdin unavailable')
        try:
            for frame in range(frames):
                source=root/'picture-frames'/f'{frame:06d}.jpg'
                with Image.open(source) as opened:
                    image=opened.convert('RGB')
                    if image.size!=(width,height): raise ValueError('Capture canvas mismatch')
                    result=draw(image,frame/float(Fraction(rate)))
                    raw=result.tobytes();process.stdin.write(raw)
                rows.append({'frame':frame,'source_sha256':digest(source),'captioned_rgb_sha256':hashlib.sha256(raw).hexdigest()})
            process.stdin.close()
            if process.wait()!=0: raise ValueError('Encoder failed')
        except BaseException:
            process.terminate();process.wait();raise
        (root/'caption-composite.json').write_text(json.dumps({'timeline_sha256':digest(root/'locked-timeline.json'),'style_sha256':digest(root/'caption-style.json'),'visual_plan_sha256':digest(root/'visual-plan.json'),'frames':rows,'caption_bounds_pass':True},indent=2))
    result=verify(root,final)
    result['caption_composite_sha256']=digest(root/'caption-composite.json')
    (root/'media-verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':main()
