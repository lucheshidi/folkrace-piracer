"""
Lightweight MJPEG Web Video Streamer for PiRacer Pro.
Streams real-time camera view with computer vision overlays to any browser on the local network.
Uses Python standard library http.server and socketserver (Zero extra pip dependencies).
"""

import io
import logging
import threading
import time
from http import server
from socketserver import ThreadingMixIn
from typing import Optional
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

PAGE = """\
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PiRacer Pro - Live Camera Stream</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background-color: #121212;
            color: #ffffff;
            margin: 0;
            padding: 20px;
            display: flex;
            flex-direction: column;
            align-items: center;
        }
        .container {
            max-width: 900px;
            width: 100%;
            background: #1e1e1e;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 8px 24px rgba(0,0,0,0.5);
            text-align: center;
        }
        h1 {
            font-size: 1.5rem;
            margin-top: 0;
            color: #00e676;
            letter-spacing: 1px;
        }
        .stream-box {
            position: relative;
            margin: 15px 0;
            border: 2px solid #333;
            border-radius: 8px;
            overflow: hidden;
            background: #000;
            min-height: 240px;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        img {
            width: 100%;
            height: auto;
            max-height: 70vh;
            object-fit: contain;
            display: block;
        }
        .footer {
            margin-top: 15px;
            font-size: 0.85rem;
            color: #888;
        }
        .status-badge {
            display: inline-block;
            background: #2e7d32;
            color: #fff;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 0.8rem;
            font-weight: bold;
            margin-bottom: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏎️ PiRacer Pro - Folkrace Vision Stream</h1>
        <div><span class="status-badge">● LIVE STREAMING</span></div>
        <div class="stream-box">
            <img src="/stream.mjpg" alt="Live Camera Video Stream" />
        </div>
        <div class="footer">
            Waveshare PiRacer Pro AI Kit | Chalmers Folkrace Autonomous Driving
        </div>
    </div>
</body>
</html>
"""


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
    """HTTP request handler providing both HTML dashboard and MJPEG video feed."""

    output: Optional[StreamingOutput] = None

    def log_message(self, format, *args):
        # Suppress routine per-frame HTTP GET 200 logs to keep console clean
        return

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            content = PAGE.encode('utf-8')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        elif self.path in ('/stream.mjpg', '/video_feed'):
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
            self.send_error(404)
            self.end_headers()


class ThreadedHTTPServer(ThreadingMixIn, server.HTTPServer):
    """Multi-threaded HTTP server allowing multiple browser tabs to view stream simultaneously."""
    allow_reuse_address = True
    daemon_threads = True


class WebStreamer:
    """Manager for Web MJPEG live camera stream."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8080, jpeg_quality: int = 70):
        self.host = host
        self.port = port
        self.jpeg_quality = jpeg_quality
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
            self.server = ThreadedHTTPServer((self.host, self.port), StreamingHandler)
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
        """
        if not self.is_running or frame is None or frame.size == 0:
            return

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
