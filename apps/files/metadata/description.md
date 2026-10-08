# Files

Your own cloud folder on your server: videos, documents and folders in one place, reachable from any browser, including iPhone Safari. It is the unmodified, open-source [File Browser](https://filebrowser.org) (Apache-2.0) on Runtipi's standard shared `media` folder (`runtipi/media`), the same folder other Runtipi apps such as Jellyfin or Immich can use.

**One folder for every app.** On first start Files creates `Videos/`, `Videos/Edited/` and `Documents/` (it never changes anything that already exists). Wizard apps read and write the same folder:

1. Open Files, go to **Videos**, tap **Upload** and pick a clip (from an iPhone: Safari → Files → Upload → Photo Library).
2. Ask Hermes: *"Edit IMG_5644.mov from my Files with the DeFleur video editor."*
3. The finished video appears in **Videos → Edited**. Tap it to watch, then **Download** or **Share**.

**Large files.** Uploads go in 10 MB resumable chunks, so phone videos of several GB work. If the connection drops, retry and the upload continues from the last chunk.

**Login.** By default there is no login, because Runtipi is meant to be reached only over your private network (e.g. Tailscale). To turn the login on, set a password (12+ characters) in the app settings, then sign in as `admin`. **Never expose Files on a public domain without a password**: anyone who can open it could read, change or delete your files.

**Sharing.** File Browser's share links (the share icon on a file) let you send one file to someone else; they only work for people who can reach the server.

**Permissions.** Runtipi creates `runtipi/media` owned by root, so apps that run as user 1000 can't write to it. When the folder itself is root-owned, Files hands it to user 1000 at startup and creates the starter folders as user 1000. This changes only the folder itself, never its contents. File Browser itself always runs as user 1000, with no command runner and no admin rights.
