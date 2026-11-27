---
name: wizard-interface
description: "Where is, what is, how to: any Wizard setting or screen. Use when the owner asks what something in Wizard is, where a setting or screen is, or how to do something in Wizard on the phone or computer (Settings pages and rows, Try new features switches, updates, Chats, Home, apps, voice). Load it before wizard-guide for these."
---

# Wizard interface manual

Every screen, Settings page and feature switch of the Wizard interface (the phone app and the desktop in a browser or the Mac app), with where it is and what it does. Written from the interface code of this Wizard's release.

- Give the exact path the way it reads on screen, e.g. Settings › About & updates › Updates › Automatic, and how to open Settings (Open Settings, below).
- Say the condition when there is one (For testers channel only, Android app only, desktop only, only when the box has it).
- You can't flip these switches or settings for the owner: they are owner-only, on the owner's screen. Tell them what to tap.
- Never invent a setting, page or button. If what they ask for isn't in this manual, say it isn't in the Wizard interface as far as you know, and ask for a screenshot of where they are looking. Don't search your own files for interface text: the interface code isn't in your container.
- Names in Wizard: the agent is 'Wizard' (or the name the owner gave it); 'WizardOS' is the server software; the interface on phone and desktop is just 'Wizard'.

## Screens

- **Home**: The start screen: what's Working and Ready, the Resources bars (server and AI accounts), your apps. Desktop: AI apps view: close the open chat (✕, Esc or ⌥`) to get the empty Home with the message box, the orb and your pinned apps; Desks view: the house at the left of the top bar (⌥`). Phone: the first desk; the gear at its top right opens Settings.
- **Chats**: All your conversations with the agent, in sections: Errors, Working, Saved, Ready, Yesterday, Past week, Snoozed, Archive (By day), or Working, Ready, Snoozed, Archive (By status; chosen in the Filter sheet). Search, Filter and + New chat. Long-press or right-click a chat for Pin, Rename, Mark unread, Snooze, Archive / Restore. Desktop: AI apps view: the chats sidebar on the left (search ⌥K, + New chat ⌥N); Desks view: the Inbox count in the top bar (⌥I). Phone: the Chats desk, or hold the orb and say 'chats'.
- **Work**: Chats opened at a section (a link to Working, Ready, Archive …).
- **Chats › Errors**: Chats whose last reply failed, with Retry (and why, with Why a reply failed on).
- **Chats › Working**: Chats where the agent is still working; order set in Settings › Chats & app screens › Working threads.
- **Chats › Saved**: Messages you sent while Wizard was restarting its Agent Service; they are kept and send by themselves after the restart.
- **Chats › Ready**: Chats with a reply for you (needs you and unread first); its order bar offers Priority, Newest, Oldest, By subject.
- **Chats › Yesterday**: Ready chats from yesterday (By day layout).
- **Chats › Past week**: Ready chats from the past week (By day layout).
- **Chats › Snoozed**: Chats you snoozed (row menu › Snooze, pick when); they come back to Ready at that time, or Restore now.
- **Chats › Archive**: Chats you archived (or done notifications); Restore brings one back. Archive on top moves it first.
- **Chats › Drafts**: An older link name; it opens Chats (unsent words stay in each chat's own box).
- **Apps**: Every installed app, with search; an app opens on a desk of its own (desktop AI apps view: as a panel beside the chat). Desktop: AI apps view: the Apps column on the right (pinned apps, then open ones; + Add an app lists the rest and Get more; Tidy closes apps unused for 24 h, with Undo); any view: search (⌥Space). Phone: swipe the orb up.
- **App Store**: Get new apps for this Wizard: each app's page with Get / Open. Desktop: Apps column › + Add an app › Get more, or search 'App Store' (⌥Space). Phone: swipe the orb up › Get more.
- **App Store install link**: A link that opens one app's page in the App Store to install it.
- **Agents**: The Agents app: your agents (main and others), each with its own chats, look and what it may use.
- **Files**: The Files app: your Wizard's files and folders (on a Mac, the shared Wizard folder).
- **Settings**: See Settings below. Desktop: the cog at the bottom left under the chats list (AI apps view); the gear in the top bar (Desks view, ⌥,). Phone: the gear at the top right of Home.
- **Settings › Appearance**: A link straight to the skin picker.
- **Settings › Resources**: A link straight to the Resources (AI usage) page.
- **Gestures & help**: Phone: How Wizard works: tap the orb to talk, hold it for a command, swipe it up for apps, down to hide the bars, sideways between desks; Back is always one step back; Practice again. Desktop: the keys guide (hold ⌥ to see the keys). Desktop: Settings › About & updates › Gestures & help, or ⌥/. Phone: Settings › About & updates › Gestures & help, or say 'help'.
- **Practice tour**: The first-run practice of the orb gestures; start it again from Gestures & help › Practice again.
- **AI apps view (desktop)**: The standard desktop. Left: the chats sidebar (Wizard switcher, search ⌥K, ◫ folds it ⌥L, Settings cog, + New chat below). Middle: the open chat, message box, model and orb. Right: the Apps column (pinned apps, open apps, + Add an app, Tidy). ⌥1–⌥0 pick an app, ⌥W closes, ⌥F widens the app panel, ⌥R folds the column, ⌥H hides both sides. Sidebar sort: Settings › Chats & app screens.
- **Apps view**: A view where every open app has its own full-screen window, with a + sheet listing Open, Installed and Get more apps.
- **Orb view**: A view where your apps float as satellites around the orb (phone Home and a desktop scene).
- **Desktop top bar (Desks view)**: Left: Home and your desks (+ New desktop). Right: search (⌥Space, also ⌘K), Talk about this (⌥S), Tell the computer (⌥C, local commands), Dictate (⌥D), New voice chat (⌥V), the Inbox count (⌥I, opens Chats), Settings (⌥,), Keys guide (⌥/). The AI apps view has no top bar.
- **Desks (phone) / desktops**: Separate spaces for apps and chats. Phone: swipe the orb sideways or tap the dots under it (long-press: all). Desktop (Desks view): the desks in the top bar, + New desktop; ⌥` or ⌥1 Home, ⌥2–⌥9 the next desks.
- **Phone orb**: Tap: talk to Wizard (tap again to send). Hold: a command for the phone (e.g. 'calendar', 'next desk', 'settings'). Swipe up: apps; down: hide the bars; sideways: desks. While recording: Cancel, Pause, Screenshot, Attach.
- **Spaces**: Named groups of chats you make (a chat can be in several); pick one in Chats' Focus strip. Ask the agent to make or fill a Space. Spaces are the channels (Chats › Tags tab at the bottom).
- **Snooze and Archive**: From a chat's menu (long-press or right-click): Snooze hides it until a time you pick (Chats › Snoozed); Archive files it (Chats › Archive); Restore brings either back. One-tap Snooze parks it at the bottom of Ready in one tap.
- **Update card**: At the top of Settings (and a small pop-up on Home): Interface updated · Reload, or WizardOS update · Install / Install now, or Updating WizardOS… with progress.
- **My skin**: Your own skin, made with + New skin in Settings › Appearance › Skin; ask the agent to change it ('make my chat text a little bigger').

## Settings

Open Settings: desktop, the cog at the bottom left under the chats list (older Desks view: the top-bar gear, ⌥,); phone, the gear at the top right of Home or an empty desk, or hold the orb and say 'settings'. Settings is a list of pages under System and Preferences (wide screen: list left, page right); empty pages are hidden. Pages are the same on phone and desktop, except rows only one of them has (named below).
Search settings: the box at the top of the Settings list. Typing keeps only the pages that mention the words and marks them on the open page, scrolled to the first; Esc clears it, Enter opens the first page.

### System › Your network
Your network: the computers and devices this Wizard runs on, filled by the apps that report them. (only when an installed app adds something here; with Machines on Home on, Settings › System holds network, AI, security and storage).

### System › AI
AI: settings for the AI accounts and models this Wizard uses, filled by the installed AI connectors. (only when an installed app adds something here).

### System › Network & security
Network & security: how this Wizard is protected, e.g. whether its disk is encrypted. (only when this Wizard reports it).
- Disk: one line saying whether this Wizard's disk is encrypted (e.g. unlocks with the box's security chip, or protected by FileVault on a Mac).
  - Disk encryption: the line written by the box itself

### System › Storage & backups
Storage & backups: disk space and backups, filled by the apps that handle them. (only when an installed app adds something here).

### Appearance
Appearance: the skin (look), colors, mode, background, desktop view, window opacity, and Try new features.
- Skin: pick a skin (a whole look) and one of its colors; + New skin makes your own skin (name, base skin, color, tweaks), which the agent can change ('change my <name> skin so…'). Your own skins show here with Edit with your Wizard and Remove skin. Some skins also offer Mode (Dark or Light) and Background (plain, pictures, or your own image).
  - Colors: the colors of the chosen skin
  - Mode: Dark or Light, for skins that have both
  - Background: Plain, pictures, or (some skins) your own image with Choose image
  - Shell view: desktop only: how this desktop is laid out, chosen per device
  - Try new features: the feature switches (For testers channel only), see Feature switches below
  - Desks: the classic desktop: a top bar, desks of windows
  - AI apps: chats in a sidebar on the left, the chat in the middle, apps on the right (like the ChatGPT and Claude apps); the standard desktop view
- Windows › Window opacity: a slider for how see-through every window and app is, on this device; Use skin default puts it back.
- Home: a switch for Machines on Home, shown here only when it is on for everyone.
- Advanced › Import skin JSON: apply a skin file (up to 8 KB) on this device.

### Chats & app screens
Chats & app screens: how Chats behaves and looks, which Chats app is the default, and app screens.
- After actions on your phone: after sending, archiving, snoozing or marking unread on the phone, Stay on this chat or go Back to chats list. Desktop chats stay open.
- Reply style: a note that each agent keeps its own reply style; tell the agent how you like replies and it remembers.
- Working threads › Sort Working: the order of the Working section in Chats, the same on phone and desktop.
- Notifications › Notifications in Chats: alerts from Notifications and from apps with an inbox show as yellow threads in Chats (Open, Done, Snooze, Resolve this). On for everyone; switch it off to keep them out of Chats.
- Default Chats: which Chats app shows your chats: Wizard Chats (built in) or another Chats app installed from the Store; you confirm before it switches.
  - Store: opens the Store to get another Chats app
- Temporary chats › Offer Incognito: lets you start text-only chats that are never saved, on a private agent that supports them. Off by default. (only when a private agent supports Incognito).
- Your app screens: apps whose screen you (or the agent) changed; Use original goes back to the app's own screen and keeps your version's files. (only when an app has your own screen).
- Workspace sync › Same workspaces on every device: the same desks with the same apps on all your devices (layout and the current desk stay per device), plus Recently closed desks with Reopen. (when the box supports it).

### Notifications
Notifications: per app, Badge (a count on its icon) or Chats (its alerts arrive as threads in Chats). Saved on this device.
- One row per app that sends notifications, each with Badge or Chats.

### Voice & typing
Voice & typing: speech-to-text, which microphone the phone uses, the text selection menu, and the desktop's voice buttons.
- Voice transcription: which speech-to-text service this Wizard uses and whether it is ready.
  - Your speech-to-text service: its name and status
- Text selection menu: what the menu offers when you select words in a chat (Copy, Share, Quote, Look up, Search, Select all), each on or off. (Android app 0.9.7 or later).
  - Quote: quote the words in your reply
- Top bar › Show every voice button: show New voice chat, Dictate and Tell the computer next to the mic in the desktop top bar. Off, they are in the mic's menu (right-click or hold) and on ⌥V, ⌥D and ⌥C. (desktop).
- Microphone: which mic the phone records with: Phone mic only, Any connected mic, or a specific Bluetooth/USB/headset mic when it is connected. (Android app).

### Phones & devices
Phones & devices: connect your phone to this Wizard (over Tailscale, with a QR code), see the devices that can reach it, and turn device access off. (owner only).
- Device access: connect a phone or another device (scan the QR code with the Wizard app; uses Tailscale, private and free). Your devices: the devices on your Tailscale account and whether they are online. Remove a device happens on the Tailscale website. Turn off device access disconnects this Wizard from Tailscale (asks first; chats stay).
  - Remove a device: opens Tailscale's device list in the browser
  - Turn off device access: asks to confirm, then every device loses access until you connect one again

### Connections
Connections: the agents on this Wizard, what each one may use, how apps are linked to each other, and other Wizards you can switch to. (owner only).
- The App Manager's own view: each agent, the apps it may use (Disconnect, Reconnect, agent access), app-to-app links, Restore defaults.
- Wizards › Add a Wizard: connect to a Wizard on another computer; your Wizards then show in the Wizard switcher.

### Unsent & recovered
Unsent & recovered: messages that weren't sent and voice recordings that were cancelled or kept, with Retry, Play, Save and Delete. Its count shows next to the page name.
- Unsent & retained: messages and recordings kept on this device because they weren't delivered, each with Retry, Edit, Play audio, Save audio, Transcribe only, Copy transcript, Open thread or Delete; Retry all when there are several.
- Recovered & cancelled recordings: voice recordings you cancelled or that were saved after a problem, to play, send or delete.

### Resources
Resources (called AI usage on older builds): the same bars as on Home, the server's CPU, memory and disk and how much of each AI account is left; tap a bar for details, devices and reset times.
- The resource bars (server CPU, memory, disk; AI accounts); tap one for details and a manual refresh.

### Schedules
Schedules: jobs the agent runs on a timer (e.g. a daily summary), with their next and last run, Run now, New schedule and Import from Hermes. (only when this Wizard supports schedules).
- The scheduled jobs with their timing, next run and last result; tap one to edit, pause, Run now or delete.
  - New schedule: make a new timed job
  - Import from Hermes: bring over schedules from your own Hermes

### About & updates
About & updates: update WizardOS (Automatic or Ask me), the release channel (For everyone or For testers), versions, connection status, and Gestures & help.
- WizardOS (server): installed version, up to date or not. Updates: Automatic installs at night, not mid-chat; Ask me waits for Install. Channel: For everyone gets releases testers used for 3 days; For testers gets every release at once and shows Try new features in Appearance. A ready update shows Install at the top of Settings.
  - Apps: every installed app with its version and the newest, Update now, Retry, Hold, and Automatic / Ask me for app updates (Automatic checks and updates apps every hour)
  - WizardOS (server) {version}: the installed server version
  - Automatic: updates install overnight, never during a chat
  - Ask me: nothing installs until you tap Install
  - For testers: every new release as soon as it's out; shows Try new features
  - For everyone: releases testers have used for about 3 days
- Wizard: whether this device is connected (Connected, Connecting…, Sign-in needed) and its address; interface and server update separately. Technical details shows the interface revision. Gestures & help: How Wizard works (phone) or the keys guide (desktop). On Android also Recording, Reply notifications and the app's version (tap it to update).
  - Connected: this device's connection to your Wizard
  - Recording: Android: recording keeps going with the screen off
  - Reply notifications: Android: a notification when the agent answers a chat you sent from the phone
  - Phone app (Android) {version}: Android: the app's version; tap to update it
- Which build of WizardOS this is, for test builds: the commit it was built from and how far it is behind main. (test builds).
- Connection › Change Wizard: connect the phone app to another Wizard (scan its QR code or type its address). (Android app).

### Phone
Phone: things only the Android app can do: Wizard Everywhere (floating orb), side button, voice typing, Wizard ID, Downloads, the orb switcher. (Android app only).
- Identity › Wizard ID: your Wizard ID, a signing key that stays on this phone, with its backup state; tap to set it up. (Android app).
- Assistant: Wizard Everywhere puts a floating Wizard button over your other apps (tap to talk, drag to move; Android asks to let Wizard display over other apps); Voice typing & screenshots lets the orb type into any app; Side button: hold the phone's side button to talk, even when locked. (Android app).
  - Voice typing & screenshots: shown when Wizard Everywhere is on
- Orb switcher: choose what holding or swiping the orb offers on the phone. (phone).
- Downloads: files you downloaded in Wizard apps, with their progress; reopens the Downloads sheet. (Android app).

## Feature switches (Settings › Appearance › Try new features)

Settings › Appearance › Try new features lists unfinished features to try, A to Z, each 'by <author>'. It only shows on the For testers channel; on For everyone these switches stay hidden and off. The same switches are also in the WizardOS Tracker app (Try it). Choices follow the owner to every device.

- **Action cards in chat**: An app's proposed action (a draft, an event) shows in chat with Approve, Edit, Open in app.
- **Add an app: search the App Store too**: Add an app's search also finds App Store apps.
- **Agent access under the browser boundary**: Connected accounts' Agent access, boundary on.
- **Agents run code without asking**: Container agents run code without an approval nobody sees (Agents: Just run, Ask me, Refuse); prompts wait an hour.
- **App switches in chat**: A reply's switch card also lists an app's own feature switches, flipped right in the chat.
- **Archive on top**: Archive is the first section of the Chats list in both By day and By status, so switching layouts never moves it.
- **Ask before sharing feature counts**: Shared only after you say Share.
- **Backup health in Resources**: Resources shows your backup's health.
- **Bottom app bar on desktop**: Apps bar at the bottom on any width.
- **Calm offline card**: The can't-reach-your-Wizard card shows one dotted path (Internet · Tailscale · Wizard), one short next step and a small Check again with the automatic re-check time.
- **Catch me up**: Say catch me up: a two-step summary.
- **Channels: a fitting emoji for new channels**: New channels get a fitting emoji.
- **Channels: an AI-picked emoji for new channels**: New channels with no emoji get one picked by your Wizard's fast model.
- **Chat replies as Chats notifications**: Android app: your agent's chat replies reach the phone as Notifications items under Chats; tap opens the chat.
- **Chats: title bar names the tab**: Chats' title bar names the tab.
- **Clear chat notifications**: Android app: reading a LINE, WhatsApp, Telegram or other bridged chat in Messenger clears that app's own notification (needs Android's Notification access).
- **Desktop sidebar follows Default Chats**: AI apps desktop: the chats sidebar uses the Chats look picked in Settings › Chats & app screens › Default Chats.
- **Five-choice first chat**: Five picks, then a first win.
- **Get set up list in Setup**: Setup lists optional accounts to connect.
- **Icons on the attach menu**: Android app: the + menu in a chat (and the orb's Attach) shows icons before Photo or video, Camera and File, on bigger rows. (Android app only).
- **Inbox until archived**: Chats stay in Inbox until archived.
- **Inbox: only what needs you**: Inbox: only what needs you.
- **Inbox: pin threads to the top**: Pin threads on top.
- **Install apps your agent builds**: Apps I build install with one tap.
- **Install sheet recommends private AI**: Installing a personal-data app suggests private AI.
- **Instant home-screen apps**: Android: pinned app icons open at once on their last screen.
- **Instant phone notifications**: Android app, with Phone notifications per app on: app notifications reach the phone within seconds, even locked (one Tailscale connection, no Google).
- **Location for Maps**: Only apps whose wizard.md asks for location (today Maps) may use it, after your browser's or phone's own yes; others stay blocked.
- **Machines on Home**: Home shows a slim strip (Wizard, AI fuel, chats, backup, network); Settings › System holds your network, AI, security and storage.
- **Now playing**: While an app plays audio or video, small moving bars sit on that app's icon in the AI apps view (the desktop apps column; the phone Home dock and grid); click or tap them to pause without opening the app. Option+P pauses or plays what played last on the desktop. Nothing shows while nothing plays.
- **One UI icon count**: Android: Messenger icon count shows the exact number in a One UI-style corner badge.
- **One-tap Snooze · bottom of Ready**: Snooze is one tap and the lowest priority: the thread waits at the bottom of Ready, below approvals, until you restore or reply.
- **Phone bar: bigger orb, one badge**: Phone bar: bigger orb, one badge. (phone only).
- **Phone media player for Music and Podcasts**: Android and iPhone: Music and Podcasts play through the phone's media player (lock screen, Control Center, headset buttons), and keep playing locked.
- **Phone notifications per app**: Android app: what any app sends to Notifications shows as a phone notification under that app's name, one Android channel per app.
- **Phone recovery mode**: Android: a frozen start reopens in recovery mode.
- **Phone tester builds**: Phones get the newest tester build.
- **Private first setup**: New installs start private: Welcome leads with Tinfoil; Claude and ChatGPT are optional extras.
- **Private mode switch-over**: Settings › Privacy: Private mode, Privacy check.
- **Private routing**: Orb opens the named agent's thread; a chip moves it.
- **Repair the agent's Wizard connection**: If the agent's app tools fail (unauthorized), `wizard link` restores the box's token; `wizard doctor` checks it.
- **Result reader**: A private model files each finished background task.
- **Running view in the AI apps sidebar**: AI apps: Running view in the sidebar.
- **Send and go**: On desktop, sending opens a fresh chat.
- **Sent: the same rows as Inbox**: Sent uses Inbox's rows.
- **Sent: threads, like email**: Sent lists threads.
- **Share feature counts**: Sends features you tried and your thumbs, plus a random box id.
- **Share to people in any window**: Share's People row shows Messenger's recent chats in every window.
- **Short answer first**: A long agent reply shows only its one-line plain answer; tap it for the full reply. Choose whether replies start collapsed and how long the short answer is. Where: Settings › Appearance › Try new features › Short answer first; its options show under it when on.
- **Shorter app updates**: App updates stop an app once.
- **Side button opens the Agent chat**: Android app: the side button opens Messenger's Agent chat for a note instead of a new Wizard chat.
- **Skins are look only**: Skins become a look only: only feature switches decide what runs. Your skin's own choices come back when you switch this off.
- **Smart inbox: only what needs you**: Inbox: only what blocks you.
- **Stop write loops**: Stops repeated saves: an identical save within 10 s is not resent; over 20 a minute pauses.
- **Swap sides**: Chats right, apps left (⌥⇧L).
- **Tags**: A chat can carry several tags.
- **Tap to answer in replies**: Tap-to-answer buttons in agent replies.
- **Tell the team about failed updates**: When an app or WizardOS update fails on this box, the App Manager files a bug for the team (or adds to the open one) with the box, versions, failing step and error, using this box's GitHub login. Your notification then says the team was told.
- **Why a reply failed**: When a reply fails and Wizard knows why (subscription ended, usage limit, signed out, network), Chats > Errors and the thread say so plainly, with Choose another model first when Retry can't work.
- **Wizard for Mac in About & updates**: Wizard for Mac: About & updates gets a Wizard for Mac group: its version, up to date or not, Check for updates, Update and restart, Download. (Wizard for Mac only).

Switches that are ordinary settings or views, not tester switches:
- **Notifications in Chats**: Chats is the inbox: Notifications’ alerts and every app with an inbox feed are yellow threads in Chats, labelled with their app; several from one app fold into one row. They open in the chat window with Open, Done, Snooze and Resolve this (the rest from that app listed under, with Done all); done ones under Archive. Where: Settings › Chats & app screens › Notifications › Notifications in Chats (on for everyone).
- **Different shell view - AI apps**: The AI apps view: chats in a left sidebar that folds to a slim rail, the chat in a centred column, your apps in a right column; an app opens beside the chat. Where: desktop: Settings › Appearance › Shell view › AI apps (the standard desktop view; Desks is the other choice). (desktop only).

No longer switches (owners and old chats may still name them):
- **Channels in Chats**: on for everyone now, nothing to turn on: open Chats and use the tabs at the bottom: Inbox (what needs you), Tags (your channels) and Sent. Tags lists your Spaces one per line, plus General; open one to see its chats as posts with a reply line.
- **Thread tracker**: retired: Needs you now shows in the thread itself, on the reply that needs the owner (with Mark done), and in Inbox; Reply works on any message.
- **Apps in Updates**: on for everyone: Settings › About & updates › Apps.
- **Reply to Telegram and Slack chats**: on for everyone: reply in Chats to a chat started on Telegram or Slack; it goes through that app's own connection and shows there too.
- **Models from your connectors**: removed: the model menu in Chats lists the models of every AI connection you connected.

## How do I…

- **Turn on a new feature (or get them first)?** Settings › About & updates › Channel › For testers (if not already), then Settings › Appearance › Try new features › the feature's switch.
- **Turn on Channels?** Nothing to turn on any more: open Chats and tap Tags in the tabs at the bottom (Inbox · Tags · Sent); your channels and General are listed there. (A box whose Agent Service has no Sent log shows Channels / Activity tabs at the top instead.)
- **Make Wizard update automatically?** Settings › About & updates › Updates › Automatic (installs overnight, never during a chat). For apps: Settings › About & updates › Apps › Automatic (checks and updates apps every hour).
- **Update now?** When an update is ready, the card at the top of Settings shows Install (or Install now); tap it. 'Interface updated · Reload' just reloads the screen.
- **Use Wizard on my phone?** Settings › Phones & devices: scan the QR code with the Wizard phone app (needs Tailscale; the page walks you through it).
- **Change the look?** Settings › Appearance › Skin and Colors; + New skin to make your own.
- **Switch the desktop layout?** Settings › Appearance › Shell view: AI apps (standard) or Desks.
- **Get alerts in Chats or as badges?** Settings › Notifications, per app; Notifications in Chats (Settings › Chats & app screens) must be on for Chats.
- **Find a message that didn't send?** Settings › Unsent & recovered.
- **See AI usage or server load?** Home's resource bars, or Settings › Resources.
- **Add another Wizard?** Settings › Connections › Wizards › Add a Wizard.
- **Install an app?** Open the App Store (desktop: Apps column › + Add an app › Get more; phone: swipe the orb up › Get more), open the app, Get.
- **See keyboard shortcuts?** Desktop: ⌥/ or hold ⌥.
- **Why would I want private AI?** Claude and ChatGPT keep what you send on their servers; private AI runs in sealed hardware (Tinfoil) that nobody else, not even us, can see into. Settings › Privacy › Why it matters.
