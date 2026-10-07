#!/usr/bin/env python3
"""App-original helper (not part of James DeFleur's plugin).

render  - live-footage picture frames for James' encode.py when there is NO motion
          layer: every output frame is the source frame named by assemble_pcm.py's
          source_frame_indices ledger, cut to the fixed crop of its setup in
          crop-ledger.json and scaled to the canvas. Writes picture-frames/NNNNNN.jpg
          and capture-full.json in the shape capture.cjs writes (declared
          producer: this app, not Chromium; no HTML/GSAP motion).
check   - decoded-pixel checks of the exact final.mp4: sampled frames must match an
          independent FFmpeg crop+scale of the ledger's source frame outside the
          caption band, and the caption band must change exactly while James'
          caption_layer.py draws a cue.
regions - per kept segment correlation between source.wav and the decoded final
          audio at its output position (James' delivery `source_regions`).
Evidence for review; not perceptual approval.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import wave
from fractions import Fraction
from pathlib import Path


def src_input(path: Path) -> list[str]:
    return ["-protocol_whitelist", "file", "-format_whitelist", "mov", "-f", "mov", "-enable_drefs", "0",
            "-use_absolute_path", "0", "-threads", "1", "-i", str(path)]


def crop_at(ledger: dict, t: float) -> list[int]:
    ranges = ledger["ranges"]
    for row in ranges:
        if row["start"] <= t < row["end"]:
            return row["crop"]
    return ranges[-1]["crop"] if t >= ranges[-1]["end"] else ranges[0]["crop"]


def probe_size(path: Path) -> tuple[int, int]:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                                   "-of", "csv=p=0", str(path)], text=True)
    w, h = out.strip().split(",")[:2]
    return int(w), int(h)


def render(a) -> None:
    import cv2
    import numpy as np
    edit = json.loads(a.edit_map.read_text())
    ledger = json.loads(a.crop_ledger.read_text())
    cw, ch = ledger["canvas"]
    fps = Fraction(edit["fps"])
    indices = edit["source_frame_indices"]
    if len(indices) != edit["frames"] or any(b < x for x, b in zip(indices, indices[1:])):
        raise SystemExit("source_frame_indices must cover every output frame and be nondecreasing")
    W, H = probe_size(a.source)
    out = a.project / "picture-frames"
    out.mkdir()
    size = W * H * 3
    cmd = ["ffmpeg", "-v", "error", "-nostdin", *src_input(a.source), "-map", "0:v:0", "-fps_mode", "passthrough",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    held, current, cur_index = 0, None, -1
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as p:
        assert p.stdout is not None
        for frame, wanted in enumerate(indices):
            while cur_index < wanted:
                data = p.stdout.read(size)
                if len(data) != size:
                    break
                current, cur_index = data, cur_index + 1
            if current is None:
                raise SystemExit("source produced no frames")
            held += cur_index < wanted
            x, y, w, h = crop_at(ledger, frame / float(fps))
            img = np.frombuffer(current, np.uint8).reshape(H, W, 3)[y:y + h, x:x + w]
            img = cv2.resize(img, (cw, ch), interpolation=cv2.INTER_LANCZOS4)
            ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                raise SystemExit("jpeg encode failed")
            (out / f"{frame:06d}.jpg").write_bytes(jpg.tobytes())
        p.stdout.close()
        p.kill()
    frames = edit["frames"]
    (a.project / "capture-full.json").write_text(json.dumps({
        "canvas": [cw, ch], "fps": edit["fps"], "frame_count": frames, "indices": list(range(frames)),
        "reverse_seek_checked": [], "errors": [], "geometry": {"crop_ledger_ranges": len(ledger["ranges"])},
        "producer": "DeFleur Video app final_render.py (live footage only); capture.cjs/Chromium not run: no motion layer",
        "held_frames_past_source_end": held}, indent=2))
    print(json.dumps({"frames": frames, "held": held}))


def decode_frames(path: Path, frames: list[int], vf_tail: str, w: int, h: int, extra_in=None):
    import numpy as np
    expr = "+".join(f"eq(n\\,{i})" for i in frames)
    inp = extra_in if extra_in is not None else ["-threads", "1", "-i", str(path)]
    cmd = ["ffmpeg", "-v", "error", "-nostdin", *inp, "-map", "0:v:0", "-vf", f"select='{expr}'{vf_tail}",
           "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]
    data = subprocess.run(cmd, check=True, capture_output=True).stdout
    size = w * h * 3
    if len(data) != size * len(frames):
        raise SystemExit(f"decoded {len(data) // size} of {len(frames)} frames from {path.name}")
    return [np.frombuffer(data[i * size:(i + 1) * size], np.uint8).reshape(h, w, 3) for i in range(len(frames))]


def psnr(a, b) -> float:
    import numpy as np
    mse = float(np.mean((a.astype(np.float32) - b.astype(np.float32)) ** 2))
    return 99.0 if mse == 0 else round(10 * math.log10(255 ** 2 / mse), 2)


def check(a) -> None:
    import numpy as np
    from PIL import Image
    sys.path.insert(0, str(a.caption_dir))
    from caption_layer import _chunks, caption_engine  # James' adapter decides when and which cue is on
    root = a.project
    timeline = json.loads((root / "locked-timeline.json").read_text())
    ledger = json.loads(a.crop_ledger.read_text())
    edit = json.loads(a.edit_map.read_text())
    style = json.loads((root / "caption-style.json").read_text())
    cw, ch = timeline["canvas"]
    fps = Fraction(str(timeline["fps"]))
    frames = timeline["frames"]
    left, top, right, bottom = style["safe_rect"]
    draw = caption_engine(root)
    blank = Image.new("RGB", (cw, ch))
    cue = lambda f: draw(blank, f / float(fps)).getbbox() is not None
    states = [cue(f) for f in range(frames)]
    on = [f for f in range(frames) if states[f]]
    off = [f for f in range(frames) if not states[f]]
    pick = lambda xs, n: [xs[round(i * (len(xs) - 1) / max(1, n - 1))] for i in range(min(n, len(xs)))] if xs else []
    sample = sorted(set(pick(on, 8) + pick(off, 6) + [0, frames - 1]))
    final = dict(zip(sample, decode_frames(root / "final.mp4", sample, "", cw, ch)))
    W, H = probe_size(a.source)
    src_idx = sorted({edit["source_frame_indices"][f] for f in sample})
    full = dict(zip(src_idx, decode_frames(a.source, src_idx, "", W, H, src_input(a.source))))
    band = lambda img: img[top:bottom, left:right].astype(np.int16)
    rows = []
    for f in sample:
        x, y, w, h = crop_at(ledger, f / float(fps))
        frame = Image.fromarray(full[edit["source_frame_indices"][f]])
        fin = final[f]
        def ref(dx):  # independent PIL crop+Lanczos of the decoded source frame
            xx = min(max(0, x + dx), W - w)
            return np.asarray(frame.crop((xx, y, xx + w, y + h)).resize((cw, ch), Image.LANCZOS))
        exp = ref(0)
        shifts = {d: psnr(fin[:top - 20], ref(d)[:top - 20]) for d in (-max(8, w // 8), -4, 4, max(8, w // 8)) if 0 <= x + d <= W - w}
        rows.append({"frame": f, "source_frame": edit["source_frame_indices"][f], "cue_on": states[f], "crop": [x, y, w, h],
                     "psnr_outside_band_db": psnr(fin[:top - 20], exp[:top - 20]),
                     "psnr_shifted_crops_db": shifts,
                     "band_mean_abs_diff": round(float(np.mean(np.abs(band(fin) - band(exp)))), 2)})
    crop_ok = all(r["psnr_outside_band_db"] >= 25 and all(r["psnr_outside_band_db"] > v for v in r["psnr_shifted_crops_db"].values())
                  for r in rows)
    on_d = [r["band_mean_abs_diff"] for r in rows if r["cue_on"]]
    off_d = [r["band_mean_abs_diff"] for r in rows if not r["cue_on"]]
    caption_ok = bool(on_d) and min(on_d) >= 4.0 and (not off_d or max(off_d) < min(on_d) / 2)
    shown = [f for f in sample if states[f]] or sample
    sheet = Image.fromarray(final[shown[len(shown) // 2]]).resize((cw // 4, ch // 4))
    sheet.save(root / "final-frame-sample.png")
    cues = len(_chunks(timeline["words"], int(style["max_words"]), int(style["max_chars"])))
    result = {"frames": frames, "caption_cues": cues, "cue_on_frames": len(on), "cue_off_frames": len(off), "samples": rows,
              "crop_matches_ledger": crop_ok, "caption_band_changes_with_cues": caption_ok,
              "cue_off_band_checked": bool(off_d), "pass": crop_ok and caption_ok,
              "method": "final.mp4 decoded by FFmpeg vs an independent PIL crop+Lanczos of the ledger's decoded source frame; the "
                        "ledger crop must score PSNR>=25 dB outside the caption band and beat crops shifted by +-4 px and +-w/8; "
                        "cue state from James' caption_layer.py; band diff >=4 with a cue and < half that without."}
    (root / "live-check.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: result[k] for k in ("pass", "crop_matches_ledger", "caption_band_changes_with_cues")}))


def read_wav(path: Path):
    import numpy as np
    with wave.open(str(path)) as r:
        if r.getsampwidth() != 2:
            raise SystemExit("PCM s16 expected")
        rate, ch = r.getframerate(), r.getnchannels()
        x = np.frombuffer(r.readframes(r.getnframes()), np.int16).reshape(-1, ch).mean(axis=1) / 32768.0
    return rate, x


def regions(a) -> None:
    import numpy as np
    edit = json.loads(a.edit_map.read_text())
    rs, src = read_wav(a.source_wav)
    rf, fin = read_wav(a.final_wav)
    if rs != rf:
        raise SystemExit("sample rates differ")
    rows = []
    for k, s in enumerate(edit["segments"]):
        ref = src[s["start_sample"]:s["end_sample"]]
        best = (-2.0, 0)
        for lag in range(-a.max_lag, a.max_lag + 1, 8):
            o = s["output_start_sample"] + lag
            if o < 0 or o + len(ref) > len(fin):
                continue
            seg = fin[o:o + len(ref)]
            d = float(np.linalg.norm(ref) * np.linalg.norm(seg))
            c = float(np.dot(ref, seg) / d) if d else 0.0
            best = max(best, (c, lag))
        lo, hi = best[1] - 8, best[1] + 8
        for lag in range(lo, hi + 1):
            o = s["output_start_sample"] + lag
            if 0 <= o and o + len(ref) <= len(fin):
                seg = fin[o:o + len(ref)]
                d = float(np.linalg.norm(ref) * np.linalg.norm(seg))
                best = max(best, (float(np.dot(ref, seg) / d) if d else 0.0, lag))
        rows.append({"segment": k, "source_start_s": s["start_s"], "source_end_s": s["end_s"], "output_start_s": s["output_start"],
                     "correlation": round(best[0], 5), "lag_samples": best[1]})
    print(json.dumps(rows))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render"); r.add_argument("source", type=Path); r.add_argument("edit_map", type=Path)
    r.add_argument("crop_ledger", type=Path); r.add_argument("project", type=Path)
    c = sub.add_parser("check"); c.add_argument("source", type=Path); c.add_argument("edit_map", type=Path)
    c.add_argument("crop_ledger", type=Path); c.add_argument("project", type=Path); c.add_argument("--caption-dir", type=Path, required=True)
    g = sub.add_parser("regions"); g.add_argument("source_wav", type=Path); g.add_argument("final_wav", type=Path)
    g.add_argument("edit_map", type=Path); g.add_argument("--max-lag", type=int, default=2400)
    a = ap.parse_args()
    {"render": render, "check": check, "regions": regions}[a.cmd](a)


if __name__ == "__main__":
    main()
