# Prepare one project

Hermes remains the orchestrator. Claude Opus authors the edit and visual composition using the skills and project evidence. Use the recipient's authorized Claude route: native Hermes provider selection for this task or Claude Code CLI. Discover the actual available Opus model identifier rather than guessing a version. Give it the complete three-stage instructions and read access only to the project and installed module. For CLI authoring, permit project-scoped tools needed to inspect/edit/run the composition; a no-tools prompt cannot perform the full workflow. Record the model/effort and all repairs. Never change the owner's global provider or substitute another model silently.

## Environment
- Git and a Hermes release supporting portable plugins and pinned installs.
- Media worker: Python 3.11+, FFmpeg/ffprobe, Node.js, Chromium, a readable licensed sans font and fontconfig. Linux CPU rendering is supported in principle; actual host capability is checked per project.
- Create a project virtualenv and install the package requirements there. Install CPU-only torch/torchaudio with the compatible PyTorch CPU index when GPU is absent; installing their GPU builds wastes disk. Do not install into Hermes' runtime environment.
- Project Node dependencies: `npm install --save-exact puppeteer-core gsap`. Record resolved package versions/lockfile. Point CHROME_PATH to the real Chromium executable.
- Dependencies/models may require network downloads. Use the owner's existing authorized image-generation route for fresh assets; stock/illustration permissions must fit the project. Core editing supports any topic; language-specific recognition still needs a compatible model.
- ASR uses faster-whisper. Alignment uses stable-ts plus a compatible Whisper model. The optional CTC helper takes explicit model/vocabulary files and a supported-language declaration. Ordinary ASR alone cannot certify absence of fillers. If an independent acoustic route is unavailable, preserve the checkpoint and report that gate precisely.

## Execute
1. Create project/work and project/plans. Probe all source media with defleur-edit/scripts/probe_source.py. Decode source audio to 48 kHz PCM s16le source.wav in work. Run each helper with --help first to confirm its exact parameters.
2. Resolve preset with defleur-edit/scripts/preset.py OUTPUT_JSON [--owner OWNER_PRESET] [--project PROJECT_PRESET]. This records hashes and discovers a usable default font. Copy its preset.caption to work/caption-style.json and keep the full resolution in plans. These mechanical choices need no user styling round-trip.
3. Follow defleur-edit, then defleur-audio through the dialogue gate. The scripts and evidence schemas are in each skill's references. Editorial decisions always come from this source, never a supplied target cut.
4. On locked audio, extract/crop frames with the exact picture ledger. Use an available local face detector to audit every live range; inspect misses and scene changes. Cache one stable crop per camera setup, keep the full face/head and natural margins, and use an inset/letterbox layout if a portrait crop cannot contain the relevant people.
5. Write the project HTML/SVG/GSAP composition and visual plan. All font/image/library assets should be project-local for deterministic capture. Expose renderFrame(t), sourceFrameForOutputFrame(frame), visualMode(t), and captionSuppressed(t). The source-frame function maps to the actual base_frames naming convention; never apply the cut map twice.
6. Run the motion capture proof and a short smoke first. Review continuous playback, transition timing, explanatory meaning and phone-size type; revise actual render evidence before full capture. Run defleur-motion/scripts/encode.py on the work directory after full capture. It composites captions, checks safe bounds, encodes H.264/yuv420p + AAC/faststart, and performs actual exact-file decode. Preserve the picture ledger to within one output frame.
7. Decode the exact final MP4, run the full acoustic/filler scan and delivery gate, verify all portrait/caption bounds, record checksum and resource timing, then return the final plus title/thumbnail ideas and a concise evidence report. Generated captions are pixels in the video, not just a sidecar subtitle.

## Resource contract
Choose limits from the actual host, reserve memory for Hermes/OS, and run heavy local stages sequentially. For a clean 16 GiB VPS test, use an 8 GiB media-job budget with no swap and bounded CPU, record actual available host memory and peak cgroup usage. A capped job on a larger machine is a capped-job test, not a physical-host certification. Cloud Opus and image-generation requests execute remotely; their inference memory is not local RAM.

## First-run quality
This is an agent-operated production module with tested component/lifecycle seams. It is not a one-command autonomous video editor and its first clean-host creative reproduction remains the pilot test. Preserve failures and improve the generalized module from them; don't add clip-specific answers to make a benchmark pass.
