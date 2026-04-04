#!/usr/bin/env python3
"""
Then — local server
No external dependencies. Uses Python's built-in libraries only.
Supports Anthropic (paid) and Groq (free tier).
Run: python server.py
"""
import json
import http.client
import ssl
import os
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

PUBLIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public')


class ThenHandler(SimpleHTTPRequestHandler):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PUBLIC_DIR, **kwargs)

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_POST(self):
        if self.path == '/api/chat':
            self._handle_chat()
        else:
            self.send_response(404)
            self.end_headers()

    # ── Main handler ─────────────────────────────────────────────────────────

    def _handle_chat(self):
        api_key = self.headers.get('x-api-key', '').strip()
        if not api_key:
            self._error(401, 'API key required. Add it in Settings.')
            return

        length = int(self.headers.get('Content-Length', 0))
        if not length:
            self._error(400, 'Empty request.')
            return

        try:
            body = json.loads(self.rfile.read(length))
        except Exception:
            self._error(400, 'Invalid JSON.')
            return

        messages = body.get('messages', [])
        system   = body.get('system', '')

        # Auto-detect provider by key prefix
        if api_key.startswith('sk-ant-'):
            self._call_anthropic(api_key, messages, system)
        else:
            # Groq keys start with gsk_ — also works for any OpenAI-compatible key
            self._call_groq(api_key, messages, system)

    # ── Anthropic ─────────────────────────────────────────────────────────────

    def _call_anthropic(self, api_key, messages, system):
        payload = {
            'model': 'claude-opus-4-6',
            'max_tokens': 1024,
            'system': system,
            'messages': messages,
            'stream': True,
        }

        resp, err = self._post(
            host='api.anthropic.com',
            path='/v1/messages',
            payload=payload,
            headers={
                'Content-Type': 'application/json',
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
            }
        )
        if err:
            self._error(500, err)
            return

        if resp.status != 200:
            msg = self._read_error(resp)
            resp.close()
            self._error(resp.status, msg)
            return

        self._stream_start()

        buf = b''
        try:
            while True:
                chunk = resp.read(256)
                if not chunk:
                    break
                buf += chunk

                while b'\n' in buf:
                    raw, buf = buf.split(b'\n', 1)
                    line = raw.decode('utf-8').rstrip('\r')
                    if not line.startswith('data: '):
                        continue

                    data = line[6:]
                    if data == '[DONE]':
                        self._done()
                        resp.close()
                        return

                    try:
                        ev = json.loads(data)
                        if ev.get('type') == 'content_block_delta':
                            delta = ev.get('delta', {})
                            if delta.get('type') == 'text_delta':
                                self._emit(delta.get('text', ''))
                        elif ev.get('type') == 'message_stop':
                            self._done()
                            resp.close()
                            return
                    except Exception:
                        pass
        except Exception as e:
            print(f'[Then] Stream error (Anthropic): {e}')

        self._done()
        try: resp.close()
        except Exception: pass

    # ── Groq (OpenAI-compatible) ──────────────────────────────────────────────

    def _call_groq(self, api_key, messages, system):
        # Convert to OpenAI message format (system as first message)
        openai_msgs = []
        if system:
            openai_msgs.append({'role': 'system', 'content': system})
        openai_msgs.extend(messages)

        payload = {
            'model': 'llama-3.3-70b-versatile',
            'max_tokens': 1024,
            'messages': openai_msgs,
            'stream': True,
        }

        resp, err = self._post(
            host='api.groq.com',
            path='/openai/v1/chat/completions',
            payload=payload,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            }
        )
        if err:
            self._error(500, err)
            return

        if resp.status != 200:
            msg = self._read_error(resp)
            resp.close()
            self._error(resp.status, msg)
            return

        self._stream_start()

        buf = b''
        try:
            while True:
                chunk = resp.read(256)
                if not chunk:
                    break
                buf += chunk

                while b'\n' in buf:
                    raw, buf = buf.split(b'\n', 1)
                    line = raw.decode('utf-8').rstrip('\r')
                    if not line.startswith('data: '):
                        continue

                    data = line[6:]
                    if data == '[DONE]':
                        self._done()
                        resp.close()
                        return

                    try:
                        ev = json.loads(data)
                        choices = ev.get('choices', [])
                        if choices:
                            delta = choices[0].get('delta', {})
                            text  = delta.get('content', '')
                            if text:
                                self._emit(text)
                            if choices[0].get('finish_reason') == 'stop':
                                self._done()
                                resp.close()
                                return
                    except Exception:
                        pass
        except Exception as e:
            print(f'[Then] Stream error (Groq): {e}')

        self._done()
        try: resp.close()
        except Exception: pass

    # ── Shared HTTP helper ────────────────────────────────────────────────────

    def _post(self, host, path, payload, headers):
        import time
        body = json.dumps(payload).encode('utf-8')
        max_attempts = 4
        last_err = None

        for attempt in range(max_attempts):
            try:
                ctx = ssl.create_default_context()
                # More tolerant SSL settings for mobile/hotspot connections
                ctx.check_hostname = True
                ctx.verify_mode = ssl.CERT_REQUIRED
                # Allow the OS to pick the best TLS version
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2

                conn = http.client.HTTPSConnection(host, context=ctx, timeout=60)
                conn.request('POST', path, body=body, headers=headers)
                return conn.getresponse(), None
            except ssl.SSLError as e:
                last_err = e
                if attempt < max_attempts - 1:
                    wait = 0.5 * (2 ** attempt)  # 0.5s, 1s, 2s
                    print(f'[Then] SSL error (attempt {attempt+1}/{max_attempts}), retrying in {wait}s: {e}')
                    time.sleep(wait)
                    continue
            except OSError as e:
                last_err = e
                if attempt < max_attempts - 1:
                    wait = 0.5 * (2 ** attempt)
                    print(f'[Then] Network error (attempt {attempt+1}/{max_attempts}), retrying in {wait}s: {e}')
                    time.sleep(wait)
                    continue
            except Exception as e:
                return None, str(e)

        return None, str(last_err)

    def _read_error(self, resp):
        try:
            raw = resp.read().decode('utf-8', errors='replace')
            data = json.loads(raw)
            # Anthropic error shape
            if 'error' in data and isinstance(data['error'], dict):
                return data['error'].get('message', raw)
            # Groq/OpenAI error shape
            if 'error' in data and isinstance(data['error'], str):
                return data['error']
            return raw
        except Exception:
            return 'Unknown error from API.'

    # ── SSE helpers ───────────────────────────────────────────────────────────

    def _stream_start(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self._cors()
        self.end_headers()

    def _emit(self, text):
        try:
            out = ('data: ' + json.dumps({'text': text}) + '\n\n').encode('utf-8')
            self.wfile.write(out)
            self.wfile.flush()
        except Exception:
            pass

    def _done(self):
        try:
            self.wfile.write(b'data: [DONE]\n\n')
            self.wfile.flush()
        except Exception:
            pass

    def _error(self, code, msg):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps({'error': msg}).encode('utf-8'))

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, x-api-key')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')

    def log_message(self, fmt, *args):
        pass  # keep terminal clean


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    server = ThreadingHTTPServer(('localhost', port), ThenHandler)
    print(f'\033[1mThen\033[0m is running → \033[4mhttp://localhost:{port}\033[0m')
    print('Press Ctrl+C to stop.\n')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nThen stopped.')
