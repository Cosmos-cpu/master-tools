# Hydrus Multi-Viewer

A configurable multi-window media viewer for Hydrus Network. Pick how many
viewers you want, group them into windows however you like, give each one
its own search/sort/tags/file-domain, and bind global hotkeys to each one.

## Features

- **Any mix of viewers per window** — 2 viewers in one window, 1 viewer in
  another, or 1-per-window — you assign a "window number" to each viewer;
  matching numbers share a window (arranged in an auto grid).
- **Per-viewer Hydrus search** — tags/system predicates, sort type, sort
  direction, and file domain, editable any time from the "Search / Hotkeys…"
  button on the viewer itself or from the setup screen.
- **Content always scaled to fit** — images and video are letterboxed to
  fit the panel, aspect ratio preserved.
- **Clean, no-UI viewer windows, fullscreenable** — viewer windows launch
  with no buttons/labels/status bar, just the media grid. Press **F11** to
  toggle fullscreen, **F1** to bring the controls back (to change search,
  edit hotkeys, or use the timer button), **Esc** to leave fullscreen.
- **Optional auto-advance timer, per viewer** — set a "seconds per post"
  interval and it'll auto-advance. Two opt-in behaviors on top of that:
  - **Autostart**: the timer starts on its own as soon as that viewer's
    search loads.
  - **Stop after each post**: instead of looping continuously, the timer
    advances once then stops, waiting for you to press the Start Timer
    button (or a hotkey) again before it advances to the next post. This
    is off by default — the regular behavior is a continuous slideshow —
    turn it on if you want manual pacing.
  - Any hotkey can be set to "Start/Resume Timer", "Stop Timer", or
    "Toggle Timer" as its action, so you can drive the timer from your
    keyboard without any HTTP call at all — this works even with the UI
    hidden or another window focused.
- **Preloads the next 2 posts** — as soon as a search loads and shows its
  first post, the next two posts' metadata (and, for images, the decoded
  image data) are fetched in the background, so Next/timer-advance is
  instant instead of waiting on the network. Video isn't pre-downloaded
  (it streams straight from the Hydrus API URL), but its metadata is
  still pre-fetched so switching to it is faster.
- **Global hotkeys, window-independent** — hotkeys are registered at the
  OS level and tied to a *viewer*, not a window. If viewer B lives in a
  window you're not currently focused on, its hotkey still fires.
- **Generic HTTP hotkey action too** — alongside the timer actions, a
  hotkey can fire an arbitrary HTTP request (method + URL + optional JSON
  body) you configure. Placeholders `{api_url}`, `{api_key}`, `{file_id}`,
  `{hash}` get filled in from whatever file the bound viewer is currently
  showing. Wire up real hydrus actions (archive/delete/etc.) later by
  pointing the URL at the right endpoint — the plumbing is already there.
- **Global settings** for your Hydrus API URL + access key.
- **Save/load layouts** — your whole setup (windows, viewers, searches,
  hotkeys, timer settings) is saved to `config.json` next to the script,
  and there's also File → Save/Open Layout As… for multiple named profiles.

## Setup

1. In Hydrus: `services -> manage services -> add -> client api`, turn it
   on, note the port (default `45869`).
2. In Hydrus: `services -> review services -> client api -> add`, generate
   an access key with at least **Search Files** permission (and anything
   else you plan to use from hotkeys later, e.g. Import/Delete Files, Edit
   Ratings, etc).
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Run it:
   ```
   python main.py
   ```
5. In the app: **Settings → Hydrus API Settings…**, enter the URL
   (e.g. `http://127.0.0.1:45869`) and your access key, hit **Test
   Connection**.
6. Set **Number of viewers**, click **Apply Count**, then for each row:
   - Set the **Window #** (same number = same window).
   - Click **Search / Hotkeys…** to set tags/sort/file domain, the
     auto-advance timer, and hotkeys.
7. Click **Launch**. Viewer windows open clean (no UI) — press **F1** in a
   window any time to bring its controls back, **F11** to fullscreen it.

## Notes & limitations

- **Global hotkeys use the `keyboard` package**, which hooks input at the
  OS level:
  - **Windows**: works out of the box.
  - **Linux**: needs access to `/dev/uinput` (often means running as root,
    or granting your user permission via a udev rule). Without it, hotkeys
    silently fail to bind and you'll see a warning in the Activity Log —
    the viewers themselves still work fine, just without hotkeys.
  - **macOS**: not well supported by this library; you'd likely need to
    swap in `pynput` with Accessibility permissions granted to your
    terminal/Python. Left as a future swap since it's arch-specific.
- Video playback uses Qt's built-in multimedia (`QMediaPlayer` +
  `QVideoWidget`), streaming directly from the Hydrus API URL. If a format
  doesn't play, it's a Qt/ffmpeg backend codec gap, not this app.
- Hydrus file search returns **all** matching file IDs in one call (that's
  how the API works); metadata for the currently-displayed file is fetched
  on demand as you navigate, so opening a search with a huge result count
  is still fast.
- Two viewers with the exact same hotkey combo will both fire when you
  press it — that's intentional (lets you build "next on every viewer"
  style combos later), just be aware of it.

## File overview

| File | Purpose |
|---|---|
| `main.py` | Entry point |
| `launcher.py` | Setup screen: viewer count, window grouping, launch |
| `viewer_window.py` | A window hosting a grid of viewers |
| `viewer_widget.py` | One media panel: search, navigation, display |
| `hotkey_manager.py` | Global OS-level hotkeys → generic HTTP calls |
| `hydrus_api.py` | Hydrus Client API wrapper |
| `ui_common.py` | Shared search/hotkey editor widgets |
| `settings_dialog.py` | Global API URL/key settings |
| `models.py` | Config data model (JSON-serializable) |
| `config_store.py` | Load/save config to disk |
