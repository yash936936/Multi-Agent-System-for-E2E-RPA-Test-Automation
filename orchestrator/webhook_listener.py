import json
import logging
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone

from config.settings import settings

TRIGGER_DIR = str(settings.triggers_pending_dir)


def queue_trigger(payload: dict) -> str:
    """
    Writes one pending CI/CD trigger record to disk and returns its
    trigger_id. Shared by both live trigger-ingestion entrypoints --
    this CLI-mode listener's WebhookHandler below, and
    api/routers/webhooks.py::cicd_webhook (the FastAPI service's
    equivalent endpoint, mounted at /api/v1/webhooks/cicd). Those two
    previously reimplemented this exact record-shape-plus-atomic-write
    logic independently and had quietly drifted apart (this module wrote
    with indent=2 and a real 400 on malformed JSON at the transport
    layer; the FastAPI router wrote unindented and silently treated any
    unparseable body as an empty payload instead of rejecting it) --
    consolidated here so both trigger-ingestion paths behave identically
    and any future fix (e.g. real Phase 17 execution wiring) only needs
    to happen once.
    """
    os.makedirs(TRIGGER_DIR, exist_ok=True)
    trigger_id = str(uuid.uuid4())
    final_path = os.path.join(TRIGGER_DIR, f"{trigger_id}.json")
    tmp_path = final_path + ".tmp"

    trigger_record = {
        "trigger_id": trigger_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }

    # Atomic write so the CLI processor (aura trigger process) never reads
    # a partially-written file. Clean up the tmp file on any failure so a
    # write error doesn't leave an orphaned .tmp file behind in the
    # pending-triggers directory.
    try:
        with open(tmp_path, "w") as f:
            json.dump(trigger_record, f, indent=2)
        os.replace(tmp_path, final_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    return trigger_id


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/webhook/cicd':
            # Debug Fix: Safely handle missing Content-Length header
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length) if content_length > 0 else b""
            
            try:
                payload = json.loads(post_data.decode('utf-8')) if post_data else {}
            except json.JSONDecodeError:
                self._send_response(400, {"error": "Invalid JSON"})
                return

            try:
                trigger_id = queue_trigger(payload)
            except Exception as e:
                logging.getLogger(__name__).error("webhook_listener: failed to queue trigger (%s)", e)
                self._send_response(500, {"error": f"Failed to queue trigger: {str(e)}"})
                return

            self._send_response(202, {"message": "Trigger queued", "trigger_id": trigger_id})
        else:
            self._send_response(404, {"error": "Not found"})

    def _send_response(self, code, body):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode('utf-8'))

    def log_message(self, format, *args):
        # Suppress default stderr logging to keep AURA CLI output clean
        pass

def start_listener(host="0.0.0.0", port=8099):
    """Starts the threaded webhook listener."""
    # Debug Fix: Use ThreadingHTTPServer for concurrent webhook handling
    server = ThreadingHTTPServer((host, port), WebhookHandler)
    print(f"[AURA] Webhook listener started on http://{host}:{port}/webhook/cicd")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("[AURA] Webhook listener stopped.")