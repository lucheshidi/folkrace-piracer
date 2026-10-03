"""
Lightweight MJPEG Web Video Streamer for PiRacer Pro.
Streams real-time camera view with computer vision overlays to any browser on the local network.
Uses Python standard library http.server and socketserver (Zero extra pip dependencies).
"""

import io
import json
import logging
import threading
import time
from http import server
from socketserver import ThreadingMixIn
from typing import Optional
from urllib.parse import urlsplit
import numpy as np

from webcontrol import RemoteState
from webui import render_page

try:
    import cv2
except ImportError:
    cv2 = None


class StreamingOutput:
    """Thread-safe buffer holding the latest JPEG frame for MJPEG streaming."""

    def __init__(self):
        self.frame: Optional[bytes] = None
        self.buffer = io.BytesIO()
        self.condition = threading.Condition()

    def write(self, frame_bytes: bytes):
        with self.condition:
            self.frame = frame_bytes
            self.condition.notify_all()


class StreamingHandler(server.BaseHTTPRequestHandler):
    """HTTP request handler providing the HTML dashboard, MJPEG feed and control API."""

    output: Optional[StreamingOutput] = None

    def log_message(self, format, *args):
        # Suppress routine per-frame HTTP GET 200 logs to keep console clean
        return

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def remote(self) -> Optional[RemoteState]:
        """Per-server RemoteState (never a class attribute -- see ThreadedHTTPServer)."""
        return getattr(self.server, "remote", None)

    def _send_json(self, payload: dict, status: int = 200):
        content = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _read_json_body(self) -> Optional[dict]:
        """
        Read and parse a JSON request body, or send an error response and return None.

        Requiring application/json is a security measure, not pedantry. A fetch()
        carrying this Content-Type is no longer a CORS "simple request", so the
        browser sends a preflight OPTIONS first -- and this server implements no
        do_OPTIONS and sends no Access-Control-Allow-* headers, so the preflight
        fails and a malicious page on another origin cannot drive the car. A
        text/plain body would skip the preflight entirely. Never add CORS headers.
        """
        content_type = self.headers.get("Content-Type", "")
        if content_type.split(";")[0].strip().lower() != "application/json":
            self._send_json({"ok": False, "error": "Content-Type must be application/json"}, 415)
            return None

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > 8192:
            self._send_json({"ok": False, "error": "missing or oversized body"}, 400)
            return None

        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json({"ok": False, "error": "malformed JSON"}, 400)
            return None

        if not isinstance(payload, dict):
            self._send_json({"ok": False, "error": "body must be a JSON object"}, 400)
            return None
        return payload

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    def do_GET(self):
        # urlsplit, not self.path: "?t=123" cache-busters must not turn into a 404.
        path = urlsplit(self.path).path

        if path == '/':
            existing = self.remote
            # The header sets the first paint's language only; the page carries both
            # and remembers the viewer's own choice from then on.
            content = render_page(existing, self.headers.get('Accept-Language', '')).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(content)))
            # The page structure itself depends on the launch flags, so a cached
            # copy could show a control tab that no longer exists (or hide one that does).
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(content)
        elif path == '/api/state':
            existing = self.remote
            if existing is None:
                self._send_json({"ok": False, "error": "remote control is not available"}, 503)
            else:
                self._send_json(existing.snapshot())
        elif path in ('/stream.mjpg', '/video_feed'):
            self.send_response(200)
            self.send_header('Age', '0')
            self.send_header('Cache-Control', 'no-cache, private')
            self.send_header('Pragma', 'no-cache')
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=FRAME')
            self.end_headers()
            try:
                while True:
                    with self.output.condition:
                        self.output.condition.wait()
                        frame = self.output.frame
                    if frame is not None:
                        self.wfile.write(b'--FRAME\r\n')
                        self.send_header('Content-Type', 'image/jpeg')
                        self.send_header('Content-Length', str(len(frame)))
                        self.end_headers()
                        self.wfile.write(frame)
                        self.wfile.write(b'\r\n')
            except Exception as e:
                logging.debug(f"Streaming client disconnected: {e}")
        else:
            # send_error() writes its own terminating blank line; a following
            # end_headers() would append a stray CRLF into the body.
            self.send_error(404)

    def do_POST(self):
        path = urlsplit(self.path).path

        if path not in ('/api/manual', '/api/tune'):
            self.send_error(404)
            return

        existing = self.remote
        if existing is None:
            self._send_json({"ok": False, "error": "remote control is not available"}, 503)
            return

        payload = self._read_json_body()
        if payload is None:
            return

        if path == '/api/manual':
            action = payload.get("action")
            if action is not None:
                if action in ("arm", "stop", "start"):
                    result = existing.set_mode(action)
                else:
                    result = {"ok": False, "error": f"unknown action '{action}'"}
            else:
                result = existing.set_drive(payload.get("steering", 0.0),
                                            payload.get("throttle", 0.0))
        else:
            applied, rejected = existing.apply_tuning(payload)
            result = {"ok": bool(applied), "applied": applied, "rejected": rejected}

        status = 200 if result.get("ok") else 403
        if not result.get("ok"):
            # Hand the real state back immediately so a stale page resynchronises
            # instead of retrying against a mode the car is not actually in.
            result["state"] = existing.snapshot()
        self._send_json(result, status)


class ThreadedHTTPServer(ThreadingMixIn, server.HTTPServer):
    """Multi-threaded HTTP server allowing multiple browser tabs to view stream simultaneously."""
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, remote: Optional[RemoteState] = None):
        # Held on the server instance rather than the handler class so that two
        # WebStreamer instances (or a restart) cannot share one RemoteState.
        self.remote = remote
        super().__init__(address, handler)


class WebStreamer:
    """Manager for Web MJPEG live camera stream and the optional control API."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080, jpeg_quality: int = 70,
                 fps: int = 15, remote: Optional[RemoteState] = None):
        self.host = host
        self.port = port
        self.jpeg_quality = jpeg_quality
        self.fps = max(1, min(60, int(fps)))
        self._min_frame_interval = 1.0 / self.fps
        self._last_frame_ts: Optional[float] = None
        self.remote = remote
        self.output = StreamingOutput()
        self.server: Optional[ThreadedHTTPServer] = None
        self.server_thread: Optional[threading.Thread] = None
        self.is_running = False

    def start(self):
        """Start the background HTTP server thread."""
        if self.is_running:
            return

        StreamingHandler.output = self.output
        try:
            self.server = ThreadedHTTPServer((self.host, self.port), StreamingHandler,
                                             remote=self.remote)
            self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
            self.server_thread.start()
            self.is_running = True
            logging.info("=" * 60)
            logging.info(f"🌐 Camera Web Streamer started!")
            logging.info(f"   Open browser at: http://<raspberry_pi_ip>:{self.port}")
            logging.info(f"   Local address:   http://localhost:{self.port}")
            logging.info("=" * 60)
        except Exception as e:
            logging.error(f"Failed to start WebStreamer on {self.host}:{self.port} - {e}")
            self.server = None

    def update_frame(self, frame: np.ndarray):
        """
        Encode an OpenCV BGR frame into JPEG and push to connected clients.

        Rate-limited here rather than in the control loop: the loop has real work
        to do at its full rate, and it is only the encoding and the network push
        that need to come down. See StreamConfig.fps for why they do.
        """
        if not self.is_running or frame is None or frame.size == 0:
            return

        now = time.monotonic()
        if self._last_frame_ts is not None and (now - self._last_frame_ts) < self._min_frame_interval:
            return
        self._last_frame_ts = now

        try:
            if cv2 is not None:
                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.jpeg_quality]
                success, encoded_img = cv2.imencode('.jpg', frame, encode_param)
                if success:
                    self.output.write(encoded_img.tobytes())
        except Exception as e:
            logging.debug(f"Error encoding frame for web stream: {e}")

    def stop(self):
        """Shut down the HTTP streaming server."""
        if self.server is not None:
            logging.info("Stopping Web Streamer server...")
            try:
                self.server.shutdown()
                self.server.server_close()
            except Exception as e:
                logging.debug(f"Error closing stream server: {e}")
            self.server = None
        self.is_running = False
