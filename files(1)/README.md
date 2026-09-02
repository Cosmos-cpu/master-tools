# Hydrus Tag Viewer

A full-screen image/video viewer that pulls posts straight out of [Hydrus
Network](https://hydrusnetwork.github.io/hydrus/) by tag search. Flip through
results with the arrow keys, tweak the search/connection settings from a
popup menu, and add tags (or jump forward/back) remotely through a small
HTTP API this app exposes.

This is an unofficial third-party tool. It talks to your own local Hydrus
client over its official [Client API](https://hydrusnetwork.github.io/hydrus/developer_api.html) -
no data goes anywhere outside your machine.

## Features

- **Search by tag**: shows full-size images/gifs/videos for whatever tags
  you configure.
- **Keyboard controls**:
  - `→` / `←` - next / previous post
  - `Esc` - open Settings
  - `F11` - toggle fullscreen
- **Settings menu (Esc)**: edit the Hydrus API URL/key, which tag service to
  add tags to, the search tags, and the local API's host/port - all backed
  by `config.json`.
- **Exposed local HTTP API** so other scripts can drive the viewer:
  - `GET  /status` - info about the currently displayed post
  - `POST /tags` - add tag(s) to the current post
  - `POST /navigate` - move to the next/previous post
  - `POST /search` - (bonus) run a brand-new search

## Setup

### 1. Install dependencies

```bash
python3 -m venv venv
source venv/bin/activate   # on Windows: venv\Scripts\activate
pip install -r requirements.txt
```

On Linux, video playback uses Qt's multimedia backend, which usually needs
GStreamer plugins installed system-wide:

```bash
sudo apt install gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
```

(Images and animated GIFs work regardless, since those are rendered
directly by Qt without GStreamer.)

### 2. Turn on the Hydrus Client API

In the Hydrus client: `services -> manage services -> add -> Client API`.
Give it a port (the default is `45869`) and apply.

### 3. Get an access key

Easiest way: in Hydrus, go to `services -> review services`, find the
Client API entry, and use its "add from api request" mini-dialog - or just
generate one manually and give it at least these permissions:

- **Search for and Fetch Files**
- **Edit File Tags**

Copy the resulting 64-character hex key.

### 4. Run the viewer

```bash
python3 main.py
```

On first run it creates `config.json` next to `main.py` with placeholder
values. Press **Esc** to open Settings and fill in:

- **Hydrus API URL** - e.g. `http://127.0.0.1:45869`
- **Hydrus API access key** - the key from step 3
- **Tag service name** - whatever you call your local tag service in Hydrus
  (default is `my tags`) - this is where added tags will land
- **Search tags** - one tag (or [system
  predicate](https://hydrusnetwork.github.io/hydrus/getting_started_searching.html))
  per line, e.g.:
  ```
  character:samus aran
  -rating:explicit
  ```
- **Local API host/port** - where *this app's* API will listen (see below)

Hit **Test Hydrus connection** to confirm the URL/key work before saving.

## Using the local API

By default the local API listens on `http://127.0.0.1:9876`.

**See what's currently on screen:**

```bash
curl http://127.0.0.1:9876/status
```

```json
{
  "success": true,
  "file_id": 4821,
  "index": 12,
  "total": 340,
  "mime": "image/jpeg",
  "tags": ["character:samus aran", "rating:safe"],
  "search_tags": ["character:samus aran"]
}
```

**Add tag(s) to the post currently being viewed:**

```bash
curl -X POST http://127.0.0.1:9876/tags \
     -H "Content-Type: application/json" \
     -d '{"tags": ["favorite", "needs_review"]}'

# or a single tag:
curl -X POST http://127.0.0.1:9876/tags \
     -H "Content-Type: application/json" \
     -d '{"tag": "favorite"}'
```

**Move to the next or previous post (same as pressing an arrow key):**

```bash
curl -X POST http://127.0.0.1:9876/navigate \
     -H "Content-Type: application/json" \
     -d '{"direction": "next"}'

curl -X POST http://127.0.0.1:9876/navigate \
     -H "Content-Type: application/json" \
     -d '{"direction": "previous"}'
```

**Run a brand-new search (bonus endpoint):**

```bash
curl -X POST http://127.0.0.1:9876/search \
     -H "Content-Type: application/json" \
     -d '{"tags": ["character:other character", "system:limit=200"]}'
```

## How it's put together

| File                 | Purpose                                                              |
|----------------------|-----------------------------------------------------------------------|
| `main.py`            | Entry point - creates the Qt application and main window             |
| `viewer.py`          | The main window: image/video display, keyboard handling, settings   |
| `hydrus_client.py`   | Thin wrapper around the Hydrus Client API (search, fetch, add tags) |
| `local_api.py`       | This app's own exposed HTTP API (Flask, runs in a background thread) |
| `settings_dialog.py` | The Esc-triggered settings popup                                      |
| `config.py`          | Loads/saves `config.json`                                            |

The local API runs in its own thread. Since Qt widgets can't safely be
touched from a non-GUI thread, every API request is dropped onto a queue
and processed by the main window on a timer, with the HTTP handler blocking
on a `threading.Event` until that's done - so requests get an accurate,
synchronous response without ever touching Qt from the wrong thread.

## Notes & limitations

- Changing the local API's host/port in Settings requires restarting the
  app (the HTTP server doesn't currently support hot-restarting).
- Very large search results are handled lazily - metadata and file bytes
  are only fetched for the post you're actually viewing, not the whole
  result set up front.
- Video/audio files are written to a temporary file before playback (Qt's
  media player needs a real file or URL); the previous temp file is cleaned
  up automatically as you navigate, and the temp directory is removed when
  you close the app.
