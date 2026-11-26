---
name: transcriber
description: Use when you need text or word timings from an audio or video file on the Wizard. Transcribes locally through the Transcriber app's MCP; nothing leaves the box.
version: 0.1.0
license: WTFPL
metadata:
  hermes:
    tags: [transcription, speech-to-text, audio, video, local, wizard-app]
---

# Transcriber

Local speech-to-text (Speaches / faster-whisper) shared by every Wizard app.

## Use the MCP

- `transcriber_status`: is it up, which models are downloaded. Run this first if a call fails; right after install the model may still be downloading.
- `transcribe(path, language?, word_timestamps?, model?)`: `path` is relative to the owner's Files root, for example `Videos/talk.mp4` or `Inbox/2026-10-09/voice.ogg`. Set `word_timestamps: true` only when you need per-word start/end times (editing, captions); otherwise you get segments.

## Rules

- Files outside the owner's Files folder are refused. Ask the owner to put the file in Files, or save it there yourself.
- Limit is 512 MB per file. For longer recordings, split first.
- Language is auto-detected; pass `language` (e.g. `en`) when you already know it, it is faster and more accurate.
- Report the transcript faithfully. Do not "clean up" quotes unless asked.

## Other apps

Apps on the same box call the OpenAI-compatible API directly at `http://transcriber:8000/v1/audio/transcriptions` (multipart, `response_format=verbose_json`, `timestamp_granularities[]=word`). DeFleur Video uses this.
