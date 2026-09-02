"""
This is the little HTTP API the *viewer itself* exposes (separate from the
Hydrus Client API it talks to). Other programs / scripts can POST to this
to add tags to whatever post is currently on screen, or to step forward
and backward through the search results - exactly like pressing the arrow
keys yourself.

It runs Flask in a background thread. Flask handlers never touch the Qt
GUI directly (Qt widgets aren't thread-safe) - instead every request is
turned into an ActionRequest, dropped on a queue, and the main window's
QTimer drains that queue on the GUI thread. The Flask handler blocks on
a threading.Event until the GUI thread has done the work and filled in
the result, then returns it as JSON. This keeps things simple and correct
without needing any Qt-specific cross-thread signal plumbing.
"""

import logging
import queue
import threading

from flask import Flask, jsonify, request

# Shared between this module and viewer.py. The GUI's QTimer calls
# drain_action_queue() (see viewer.py) to process whatever has piled up here.
action_queue = queue.Queue()


class ActionRequest:
    def __init__(self, kind, payload=None):
        self.kind = kind
        self.payload = payload or {}
        self.event = threading.Event()
        self.result = None


def _submit(kind, payload=None, timeout=10.0):
    req = ActionRequest(kind, payload)
    action_queue.put(req)
    if req.event.wait(timeout=timeout):
        return req.result
    return {"success": False, "error": "Timed out waiting for the viewer window to respond."}


def create_app():
    app = Flask("hydrus_viewer_local_api")
    # Quiet down Flask's default per-request console spam.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

    @app.route("/status", methods=["GET"])
    def status():
        """What's currently on screen: file_id, position, tags, mime."""
        result = _submit("status")
        return jsonify(result)

    @app.route("/tags", methods=["POST"])
    def add_tags():
        """Add one or more tags to the currently displayed post.

        Body: {"tags": ["tag one", "tag two"]}   -- or --   {"tag": "tag one"}
        """
        data = request.get_json(silent=True) or {}
        tags = data.get("tags")
        if tags is None:
            single = data.get("tag")
            tags = [single] if single else []
        if isinstance(tags, str):
            tags = [tags]
        tags = [t.strip() for t in tags if isinstance(t, str) and t.strip()]
        if not tags:
            return jsonify({
                "success": False,
                "error": "Provide a 'tag' (string) or 'tags' (list of strings) in the JSON body.",
            }), 400

        result = _submit("add_tags", {"tags": tags})
        return jsonify(result), (200 if result.get("success") else 500)

    @app.route("/navigate", methods=["POST"])
    def navigate():
        """Move to the next or previous post in the current search results.

        Body: {"direction": "next"}   -- or --   {"direction": "previous"}
        """
        data = request.get_json(silent=True) or {}
        direction = data.get("direction", "")
        if direction not in ("next", "previous"):
            return jsonify({
                "success": False,
                "error": "'direction' must be 'next' or 'previous'.",
            }), 400

        result = _submit("navigate", {"direction": direction})
        return jsonify(result), (200 if result.get("success") else 409)

    @app.route("/search", methods=["POST"])
    def search():
        """Optional bonus endpoint: change the active search tags entirely.

        Body: {"tags": ["new", "search", "terms"]}
        """
        data = request.get_json(silent=True) or {}
        tags = data.get("tags")
        if not isinstance(tags, list) or not tags:
            return jsonify({
                "success": False,
                "error": "Provide 'tags' as a non-empty list of strings.",
            }), 400

        result = _submit("search", {"tags": tags})
        return jsonify(result), (200 if result.get("success") else 500)

    @app.route("/", methods=["GET"])
    def index():
        return jsonify({
            "name": "Hydrus Tag Viewer - local API",
            "endpoints": {
                "GET /status": "info about the currently displayed post",
                "POST /tags": '{"tags": [...]} or {"tag": "..."} - add tags to current post',
                "POST /navigate": '{"direction": "next"|"previous"} - change current post',
                "POST /search": '{"tags": [...]} - run a brand new search',
            },
        })

    return app


def start_local_api(host, port):
    """Starts the Flask app in a daemon thread and returns the thread."""
    app = create_app()

    def _run():
        # use_reloader=False is required - the reloader spawns a second
        # process, which would also try to talk to Hydrus and to this
        # same port.
        app.run(host=host, port=port, debug=False, use_reloader=False, threaded=True)

    thread = threading.Thread(target=_run, daemon=True, name="local-api-thread")
    thread.start()
    return thread
