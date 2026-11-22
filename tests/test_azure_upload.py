"""Exercise real local HTTP uploads, including the wait for Azure's response."""
import concurrent.futures
import email.parser
import email.policy
import http.server
import json
import pathlib
import sys
import threading
from unittest.mock import patch

import httpx
import pytest
import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import transcribe_azure as tr


@pytest.mark.parametrize('client_kind', ['httpx', 'requests'])
def test_upload_progress_finishes_before_response_and_preserves_multipart(
        tmp_path, monkeypatch, capsys, client_kind):
    audio = bytes(range(256)) * 1024
    mp3_dir = tmp_path / 'data/mp3'
    mp3_dir.mkdir(parents=True)
    (mp3_dir / '328.mp3').write_bytes(audio)
    monkeypatch.setattr(tr, 'ROOT', tmp_path)
    monkeypatch.setattr(tr, 'MP3_DIR', mp3_dir)
    received = threading.Event()
    upload_finished = threading.Event()
    respond = threading.Event()
    request_data = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            request_data['headers'] = self.headers
            request_data['body'] = self.rfile.read(int(self.headers['Content-Length']))
            received.set()
            respond.wait(timeout=10)
            payload = b'{"phrases": []}'
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    monkeypatch.setattr(tr, '_transcribe_url', lambda endpoint:
                        f'http://127.0.0.1:{server.server_port}/transcribe')
    if client_kind == 'requests':
        monkeypatch.setattr(tr, '_httpx', None)
    else:
        real_client = httpx.Client
        monkeypatch.setattr(httpx, 'Client', lambda **kwargs:
                            real_client(trust_env=False, **kwargs))
    session = requests.Session()
    session.trust_env = False
    real_print = print

    def report(*args, **kwargs):
        real_print(*args, **kwargs)
        if args and 'Upload finished' in str(args[0]):
            upload_finished.set()

    ep = {'n': 328, 't': 'Test', 'mp3': 'https://example.com/audio.mp3',
          'g': [], 'p': False}
    try:
        with patch('builtins.print', report), concurrent.futures.ThreadPoolExecutor() as pool:
            result = pool.submit(tr.transcribe_episode, ep, 'test-key', 'unused', session)
            try:
                assert received.wait(timeout=5), 'The server must receive the complete upload'
                assert upload_finished.wait(timeout=5), 'Progress must not wait for the response'
                assert not result.done(), 'Azure is still processing after the upload finishes'
                headers = request_data['headers']
                body = request_data['body']
                assert int(headers['Content-Length']) == len(body)
                assert 'Transfer-Encoding' not in headers
                message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
                    b'MIME-Version: 1.0\r\nContent-Type: '
                    + headers['Content-Type'].encode() + b'\r\n\r\n' + body)
                parts = {p.get_param('name', header='content-disposition'): p
                         for p in message.iter_parts()}
                assert parts['audio'].get_payload(decode=True) == audio
                assert parts['audio'].get_filename() == '328.mp3'
                definition = json.loads(parts['definition'].get_payload(decode=True))
                assert definition['enhancedMode']['model'] == 'MAI-Transcribe-2'
                assert definition['diarization']['enabled'] is True
            finally:
                respond.set()
            assert result.result(timeout=5)['episode'] == 328
    finally:
        respond.set()
        session.close()
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)
    output = capsys.readouterr().out
    assert 'Upload:   0%' in output
    assert 'Upload: 100%' in output
    assert 'MB/s' in output
    assert 'waiting for Azure to finish transcription' in output
