#!/usr/bin/env python3
"""App-original helper (not part of James DeFleur's plugin).

Face audit and fixed portrait crop per setup, following James' contract
(skills/defleur-edit/SKILL.md "Picture, visual and caption planning" and
references/project-contract.md crop-ledger.json): sample real source frames
across every kept segment, detect faces locally with OpenCV's YuNet model,
choose ONE fixed crop per setup (never a detector-driven pan), and audit that
every detected face sits inside the crop with a safety margin and above the
caption band. With no face at all the crop is centered and flagged.

Outputs in OUT: crop-ledger.json, face-audit.json, face-audit-setup-<k>.json,
setup-<k>-crop.png. Evidence for review; not a perceptual judgement.

--framing (optional) lets the operator pick, per kept segment, which detected face
a two-person shot frames (largest|left|right|center) and force new setups at
named segments. A change of target always starts a new fixed-crop setup.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from fractions import Fraction
from pathlib import Path

DETECT_WIDTH = 960
MAX_SAMPLES = 240
SCORE = 0.6
MARGIN = 0.15          # fraction of the face box kept clear on every side
ZOOMS = (1.0, 0.92, 0.85, 0.78)
FACE_TOP = 0.36        # preferred face-center height in the crop (fraction of crop height)


def even(v: float) -> int:
    return max(2, int(v // 2) * 2)


def ffmpeg_input(source: Path) -> list[str]:
    return ["-protocol_whitelist", "file", "-format_whitelist", "mov", "-f", "mov", "-enable_drefs", "0",
            "-use_absolute_path", "0", "-threads", "1", "-i", str(source)]


def probe(source: Path) -> dict:
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                   "stream=width,height,r_frame_rate,nb_frames", "-of", "json", str(source)], text=True)
    s = json.loads(out)["streams"][0]
    return {"width": int(s["width"]), "height": int(s["height"]), "fps": Fraction(s["r_frame_rate"])}


def decode_frames(source: Path, indices: list[int], width: int, height: int, out_w: int):
    """Yield (index, BGR array) for the sorted unique source frame indices, scaled to out_w."""
    import numpy as np
    out_h = even(height * out_w / width)
    expr = "+".join(f"eq(n\\,{i})" for i in indices)
    cmd = ["ffmpeg", "-v", "error", "-nostdin", *ffmpeg_input(source), "-map", "0:v:0", "-vf",
           f"select='{expr}',scale={out_w}:{out_h}:flags=area", "-fps_mode", "passthrough",
           "-f", "rawvideo", "-pix_fmt", "bgr24", "pipe:1"]
    size = out_w * out_h * 3
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as p:
        assert p.stdout is not None
        for index in indices:
            data = p.stdout.read(size)
            if len(data) != size:
                break
            yield index, np.frombuffer(data, np.uint8).reshape(out_h, out_w, 3)
        p.stdout.close()
        if p.wait() != 0:
            raise SystemExit("ffmpeg failed while sampling frames")


def plan_crop(boxes, width, height, aspect, cap_frac):
    """Fixed crop [x,y,w,h] containing every face box plus margin and above the caption band."""
    full_h = min(height, width / aspect)
    if not boxes:
        ch = even(full_h); cw = even(ch * aspect)
        return [even((width - cw) / 2) if width > cw else 0, even((height - ch) / 2) if height > ch else 0, cw, ch], 1.0, False
    fw = sorted(b[2] for b in boxes)[len(boxes) // 2]
    fh = sorted(b[3] for b in boxes)[len(boxes) // 2]
    mx, my = MARGIN * fw, MARGIN * fh
    ux0, uy0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    ux1, uy1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
    cx, cy = (ux0 + ux1) / 2, (uy0 + uy1) / 2
    best = None
    for zoom in ZOOMS:
        ch = even(full_h * zoom); cw = even(ch * aspect)
        if cw > width or ch > height:
            continue
        x_lo, x_hi = max(0, ux1 + mx - cw), min(width - cw, ux0 - mx)
        y_lo, y_hi = max(0, uy1 + my - ch * cap_frac), min(height - ch, uy0 - my)
        x = min(max(cx - cw / 2, x_lo), x_hi) if x_lo <= x_hi else min(max(cx - cw / 2, 0), width - cw)
        y = min(max(cy - FACE_TOP * ch, y_lo), y_hi) if y_lo <= y_hi else min(max(cy - FACE_TOP * ch, 0), height - ch)
        crop = [int(round(x)), int(round(y)), cw, ch]
        if x_lo <= x_hi and y_lo <= y_hi:
            return crop, zoom, True
        if best is None:
            best = (crop, zoom, False)
    assert best is not None, 'source smaller than a 9:16 crop'
    return best


def judge(box, crop, cap_frac):
    x, y, w, h = box
    cx, cy, cw, ch = crop
    mx, my = MARGIN * w, MARGIN * h
    inside = x - mx >= cx and y - my >= cy and x + w + mx <= cx + cw and y + h + my <= cy + ch
    clear = y + h + my <= cy + ch * cap_frac
    return inside, clear


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", type=Path)
    ap.add_argument("edit_map", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--canvas", default="1080x1920")
    ap.add_argument("--caption-top", type=int, required=True, help="caption safe_rect top on the output canvas")
    ap.add_argument("--framing", type=Path, help="optional JSON {targets: {segment: largest|left|right|center}, new_setup_at: [segment]}")
    a = ap.parse_args()
    framing = json.loads(a.framing.read_text()) if a.framing else {}
    targets = {int(k): v for k, v in (framing.get("targets") or {}).items()}
    breaks = set(int(k) for k in framing.get("new_setup_at") or [])
    import cv2
    cw_out, ch_out = (int(v) for v in a.canvas.split("x"))
    aspect, cap_frac = cw_out / ch_out, a.caption_top / ch_out
    edit = json.loads(a.edit_map.read_text())
    info = probe(a.source)
    W, H, fps = info["width"], info["height"], Fraction(edit["fps"])
    segments = edit["segments"]
    total = sum(s["end_s"] - s["start_s"] for s in segments)
    step = max(0.5, total / MAX_SAMPLES)
    samples = []  # (segment, source frame)
    for k, s in enumerate(segments):
        t, frames = s["start_s"] + 0.04, set()
        while t < s["end_s"] - 0.02:
            frames.add(int(t * fps)); t += step
        frames.add(max(int(s["start_s"] * fps), int((s["end_s"] - 0.04) * fps)))
        samples += [(k, f) for f in sorted(frames)]
    wanted = sorted({f for _, f in samples})
    scale = W / DETECT_WIDTH
    detector = None
    found, thumbs = {}, {}
    for index, img in decode_frames(a.source, wanted, W, H, DETECT_WIDTH):
        if detector is None:
            detector = cv2.FaceDetectorYN.create(str(a.model), "", (img.shape[1], img.shape[0]), SCORE)
        _, faces = detector.detect(img)
        rows = [] if faces is None else sorted(([float(v) * scale for v in f[:4]] + [float(f[14])] for f in faces),
                                               key=lambda r: -r[2] * r[3])
        found[index] = rows
        if len(thumbs) < 64:
            thumbs[index] = img
    if len(found) != len(wanted):
        raise SystemExit(f"sampled {len(found)} of {len(wanted)} frames")
    def choose(k, faces):
        """The face this segment frames: the largest (default), or the operator's per-segment speaker choice."""
        mode = targets.get(k, "largest")
        if not faces or mode == "largest":
            return faces[0] if faces else None
        big = [r for r in faces if r[2] * r[3] >= 0.35 * faces[0][2] * faces[0][3]] or faces[:1]
        key = {"left": lambda r: r[0] + r[2] / 2, "right": lambda r: -(r[0] + r[2] / 2),
               "center": lambda r: abs(r[0] + r[2] / 2 - W / 2)}[mode]
        return min(big, key=key)
    for k, f in samples:
        if found[f]:
            chosen = choose(k, found[f])
            found[(k, f)] = [chosen] + [r for r in found[f] if r is not chosen]
    face = lambda k, f: found.get((k, f), found[f])
    seg_boxes = {k: [face(kk, f)[0][:4] for kk, f in samples if kk == k and found[f]] for k in range(len(segments))}
    # Greedy setups: consecutive kept segments share one fixed crop while their faces still fit it.
    setups, current = [], []
    for k in range(len(segments)):
        trial = current + [k]
        boxes = [b for j in trial for b in seg_boxes[j]]
        forced = k in breaks or (current and targets.get(k, "largest") != targets.get(current[-1], "largest"))
        if current and (forced or not plan_crop(boxes, W, H, aspect, cap_frac)[2] and plan_crop([b for j in current for b in seg_boxes[j]], W, H, aspect, cap_frac)[2]):
            setups.append(current); current = [k]
        else:
            current = trial
    setups.append(current)
    ledger = {"source_mode": "cfr", "canvas": [cw_out, ch_out], "source_size": [W, H], "ranges": [], "fullscreen_exceptions": [],
              "detector": "OpenCV FaceDetectorYN (YuNet 2023mar, opencv_zoo, MIT)", "policy": "fixed crop per setup; no detector-driven motion"}
    summary = {"setups": [], "samples": len(samples), "pass": True, "flags": []}
    for sid, members in enumerate(setups):
        boxes = [b for j in members for b in seg_boxes[j]]
        crop, zoom, feasible = plan_crop(boxes, W, H, aspect, cap_frac)
        rows, bad = [], 0
        for k, f in samples:
            if k not in members:
                continue
            faces = face(k, f)
            row = {"segment": k, "target": targets.get(k, "largest"), "source_frame": f, "source_s": round(f / float(fps), 3), "faces": len(faces)}
            if faces:
                inside, clear = judge(faces[0][:4], crop, cap_frac)
                row.update({"box": [round(v, 1) for v in faces[0][:4]], "score": round(faces[0][4], 3), "inside_crop_with_margin": inside,
                            "clear_of_caption_band": clear})
                bad += not (inside and clear)
            rows.append(row)
        detected = sum(1 for r in rows if r["faces"])
        flags = []
        if not detected:
            flags.append("no face found: centered crop")
        if bad:
            flags.append(f"{bad} sampled face(s) outside the crop margin or inside the caption band")
        if detected and detected < len(rows):
            flags.append(f"face missed in {len(rows) - detected} of {len(rows)} samples")
        if zoom < 1.0:
            flags.append(f"crop zoomed to {zoom:.2f} of full height to keep the face above the captions")
        passed = bool(detected) and not bad and feasible
        audit = {"setup": f"setup-{sid}", "segments": members, "crop": crop, "zoom": zoom, "samples": rows, "detected": detected,
                 "violations": bad, "pass": passed, "flags": flags, "margin_fraction": MARGIN, "caption_band_top_fraction": round(cap_frac, 4),
                 "scope": "Sampled-frame face containment; a face missed by the detector is not audited."}
        (a.out / f"face-audit-setup-{sid}.json").write_text(json.dumps(audit, indent=2))
        for k in members:
            s = segments[k]
            ledger["ranges"].append({"start": s["output_start"], "end": s["output_end"], "setup": f"setup-{sid}", "crop": crop,
                                     "source_start_s": s["start_s"], "source_end_s": s["end_s"], "face_audit": f"face-audit-setup-{sid}.json",
                                     "target": targets.get(k, "largest")})
        # Evidence image: a representative sampled frame with crop (green), faces (red) and caption band (yellow).
        pick = next((f for k, f in samples if k in members and f in thumbs), None)
        if pick is not None:
            img = thumbs[pick].copy()
            s_ = 1 / scale
            x, y, w, h = crop
            cv2.rectangle(img, (int(x * s_), int(y * s_)), (int((x + w) * s_), int((y + h) * s_)), (0, 255, 0), 3)
            band = int((y + h * cap_frac) * s_)
            cv2.line(img, (int(x * s_), band), (int((x + w) * s_), band), (0, 220, 255), 2)
            for fx, fy, fw, fh, _ in found[pick]:
                cv2.rectangle(img, (int(fx * s_), int(fy * s_)), (int((fx + fw) * s_), int((fy + fh) * s_)), (0, 0, 255), 2)
            cv2.imwrite(str(a.out / f"setup-{sid}-crop.png"), img)
        summary["setups"].append({"setup": f"setup-{sid}", "segments": members, "crop": crop, "zoom": zoom, "samples": len(rows),
                                  "detected": detected, "violations": bad, "pass": passed, "flags": flags})
        summary["pass"] = summary["pass"] and passed
        summary["flags"] += [f"setup-{sid}: {x}" for x in flags]
    ledger["ranges"].sort(key=lambda r: r["start"])
    (a.out / "crop-ledger.json").write_text(json.dumps(ledger, indent=2))
    (a.out / "face-audit.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({"setups": len(setups), "pass": summary["pass"], "samples": len(samples)}))


if __name__ == "__main__":
    main()
