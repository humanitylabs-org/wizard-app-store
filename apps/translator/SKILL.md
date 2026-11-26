---
name: translator
description: Use when the owner wants text translated (Thai, English and more) privately, or asks about recent translations.
---

# Translator

Private translation. The server engine is a private AI model (gemma4-31b) through the box's Tinfoil app, in an
attested Tinfoil enclave; it handles register, Thai politeness (ครับ/ค่ะ), slang and menus far better than classic
machine translation. The owner's phone can also translate offline with Firefox Translations (on-device only; the MCP
always uses the server engine). Languages: Thai, English, Japanese, Chinese (zh-Hans), Korean, Vietnamese, Spanish,
French, German, Russian; every pair works directly.

## Tools (MCP on the Translator app)

- `translate(text, target, source="auto", save=true)` → `{text, translation, source, target, detected, engine, model, id}`.
  Use `source="auto"` unless the owner names the language. Max 5000 characters per call: split longer text by
  paragraph. Use `save=false` for bulk or agent-internal work so the owner's Recent list stays his.
- `languages()` → `{engine: "ready"|"not_linked", server: {linked, model}, languages: [...]}`.
- `history(limit=20)` → newest first.

## When it fails

- `not_linked` / "Tinfoil is not linked to Translator": the owner opens Translator once (`?open=translator`) with the
  Tinfoil app connected; the page links itself. If Tinfoil isn't connected, he connects it on the Tinfoil page. Never
  ask for an API key in chat, and never fall back to an online translation service without asking.
- Tinfoil errors: say so and retry once; the owner's phone still works offline.

## Notes

- Thai output uses the owner's politeness setting (default ครับ; switch to ค่ะ under Engines in the app).
- For contracts, medical or legal text, say it is a machine translation and suggest a human check.
- The owner opens the app at `?open=translator`. Speaking into it is behind the `voice-input` switch (off by default).
