# Transcriber

A shared, local speech-to-text service for your Wizard server. Install it once; Hermes, DeFleur Video and any other app can send it audio and get back text with word-by-word timings. Nothing leaves your server and there are no API fees.

This is the unmodified [Speaches](https://github.com/speaches-ai/speaches) CPU server (MIT), pinned to an exact image.

**Try it:** it has no web page; call the API:

```
curl http://<server>:8791/v1/audio/transcriptions \
  -F file=@audio.mp3 -F model=Systran/faster-whisper-small \
  -F response_format=verbose_json -F "timestamp_granularities[]=word"
```

**From other Runtipi apps:** `http://transcriber:8000/v1` (OpenAI-compatible base URL; any API key value works).

**Notes**
- The model chosen at install downloads on first start (small is about 0.5 GB). The first start may restart once while Runtipi fixes folder permissions.
- Pass the exact model id in each request. The OpenAI alias `whisper-1` maps to large-v3, which is not downloaded by default.
- Other models can be downloaded with `POST /v1/models/<model-id>`.
- Starting up needs internet: the automatic model download checks Hugging Face each start. If the server is offline, the app retries until the connection is back. Transcription itself runs fully offline.
- No password: keep this server private (e.g. Tailscale only).
