# DeFleur Video

Ask your Wizard to "edit this video". It transcribes through the Transcriber app, proposes one combined cut + motion plan for approval, renders through the shared Browser app, and saves the finished short to Files/Videos/Edited.

Split out of `wizard-app-store` with full history on 9 Oct 2026. The Runtipi files are unchanged and live in `runtipi/`. This repo builds, tests and publishes its own image (`.github/workflows/image.yml`): every push to `main` publishes `ghcr.io/humanitylabs-org/defleur-video-app:<version>`.
