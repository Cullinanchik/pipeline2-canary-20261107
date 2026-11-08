import http.client
import json
import os
import socket
import tempfile
import threading
import unittest
from collections import Counter
from contextlib import closing
from pathlib import Path
from unittest import mock
import api
import app
from test_api import INITIAL, SEED

PARTIAL = json.dumps({'item_id': 1, 'quantity': 1, 'idempotency_key': 'partial'}).encode()


class HttpTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = os.path.join(tmp.name, 'inventory.sqlite3')
        patch = mock.patch.object(app.Handler, 'log_message', lambda *a, **k: None)
        patch.start()
        self.addCleanup(patch.stop)
        self.server = None
        self.addCleanup(self.stop_server)
        self.start_server()

    def start_server(self):
        self.server = app.make_server('127.0.0.1', 0, self.db)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        self.thread.start()

    def stop_server(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.thread.join(10)
            self.server = None

    def request(self, method, path, body=None, raw=None, headers=None, headers_only=False):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        try:
            data = raw if raw is not None else json.dumps(body).encode() if body is not None else b''
            c.putrequest(method, path)
            for k, v in headers or []:
                c.putheader(k, v)
            if not headers_only:
                c.putheader('Content-Length', str(len(data)))
            c.endheaders(None if headers_only else data)
            r = c.getresponse()
            return r.status, dict((k.lower(), v) for k, v in r.getheaders()), r.read()
        finally:
            c.close()

    def raw_post(self, declared_length, body, half_close):
        with socket.create_connection(('127.0.0.1', self.port), timeout=10) as s:
            s.sendall(b'POST /api/reservations HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: %d\r\n\r\n' % declared_length + body)
            if half_close:
                s.shutdown(socket.SHUT_WR)
            data = b''
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
        head, body = data.split(b'\r\n\r\n', 1)
        return int(head.split()[1]), json.loads(body)

    def payload(self, key='k', item_id=1, quantity=1):
        return dict(item_id=item_id, quantity=quantity, idempotency_key=key)

    def post(self, payload):
        status, headers, body = self.request('POST', '/api/reservations', body=payload)
        return status, headers, json.loads(body)

    def stock(self):
        return {r['id']: r['quantity'] for r in self.server.inventory.list_items()}

    def count(self):
        with closing(api._connect(self.db)) as c:
            return c.execute('SELECT count(*) FROM reservations').fetchone()[0]

    def unchanged(self):
        self.assertEqual(self.stock(), SEED)
        self.assertEqual(self.count(), 0)

    def test_ac1_get_items_initial_and_after_reservation(self):
        s, h, b = self.request('GET', '/api/items')
        self.assertEqual((s, h['content-type'], json.loads(b)), (200, 'application/json', INITIAL))
        self.post(self.payload(quantity=2))
        self.assertEqual(json.loads(self.request('GET', '/api/items')[2])[0]['quantity'], 1)

    def test_ac2_post_creates_reservation(self):
        s, _, r = self.post(self.payload())
        self.assertEqual(s, 201)
        self.assertEqual(set(r), {'id', 'item_id', 'quantity', 'idempotency_key', 'created_at'})
        self.assertRegex(r['created_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$')

    def test_ac2_unicode_keys_round_trip(self):
        for key, raw in [('заказ-№42 ✓', json.dumps(self.payload('заказ-№42 ✓', 2), ensure_ascii=False).encode()), ('🧾-1', b'{"item_id":2,"quantity":1,"idempotency_key":"\\ud83e\\uddfe-1"}')]:
            s, _, b = self.request('POST', '/api/reservations', raw=raw)
            self.assertEqual(s, 201)
            self.assertEqual(json.loads(b)['idempotency_key'], key)
            s2, _, b2 = self.request('POST', '/api/reservations', raw=raw)
            self.assertEqual((s2, b2), (200, b))
        self.assertEqual(self.stock()[2], 3)

    def test_ac2_method_and_route_errors(self):
        for method, path, status, code, allow in [('GET', '/api/reservations', 405, 'method_not_allowed', 'POST'), ('POST', '/api/items', 405, 'method_not_allowed', 'GET'), ('POST', '/api/other', 404, 'not_found', None)]:
            s, h, b = self.request(method, path)
            self.assertEqual((s, json.loads(b)['error'], h.get('allow')), (status, code, allow))

    def test_ac3_content_length_parsing(self):
        for values, status in [([], 411), (['10', '10'], 400)] + [([v], 400) for v in ['abc', '-1', '+5', '1.5', '', '١٢', '²']] + [([v], 413) for v in ['9'*5000, '4097', '00000004097']]:
            with self.subTest(values=values), self.assertRaises(api.ApiError) as ctx:
                app.parse_content_length(values)
            self.assertEqual(ctx.exception.status, status)
        for value, expected in [('0'*5000+'12', 12), ('4096', 4096), (' 7 ', 7), ('0', 0)]:
            self.assertEqual(app.parse_content_length([value]), expected)

    def test_ac3_invalid_requests_rejected_without_write(self):
        for raw in [b'{', b'\xff', b'[1]', b'{"item_id":1,"item_id":2,"quantity":1,"idempotency_key":"k"}', b'{"item_id":1,"quantity":1}', b'{"item_id":1,"quantity":true,"idempotency_key":"k"}', b'{"item_id":1,"quantity":1,"idempotency_key":"\\ud800"}']:
            s, _, b = self.request('POST', '/api/reservations', raw=raw)
            self.assertEqual((s, json.loads(b)['error']), (400, 'invalid_request'))
            self.unchanged()
        for headers, status, code in [([('Content-Length', 'abc')], 400, 'invalid_request'), ([('Content-Length', '10')]*2, 400, 'invalid_request'), ([], 411, 'length_required'), ([('Content-Length', '5000')], 413, 'payload_too_large'), ([('Content-Length', '9'*5000)], 413, 'payload_too_large')]:
            s, _, b = self.request('POST', '/api/reservations', headers=headers, headers_only=True)
            self.assertEqual((s, json.loads(b)['error']), (status, code))
            self.unchanged()
        for p, status, code in [(self.payload(item_id=999), 404, 'item_not_found'), (self.payload(item_id=2, quantity=6), 409, 'insufficient_stock')]:
            s, _, r = self.post(p)
            self.assertEqual((s, r['error']), (status, code))
            self.unchanged()

    def short_body(self, half_close):
        s, r = self.raw_post(len(PARTIAL)+10, PARTIAL, half_close)
        self.assertEqual((s, r['error']), (400, 'invalid_request'))
        self.unchanged()
        self.assertEqual(self.post(json.loads(PARTIAL))[0], 201)

    def test_ac3_short_body_eof_rejected_without_write(self):
        self.short_body(True)

    def test_ac3_stalled_body_times_out_without_write(self):
        with mock.patch.object(app, 'REQUEST_TIMEOUT_SECONDS', 0.5):
            self.short_body(False)

    def test_ac4_replay_returns_identical_body(self):
        p = self.payload(item_id=2, quantity=2)
        s, _, b = self.request('POST', '/api/reservations', body=p)
        s2, _, b2 = self.request('POST', '/api/reservations', body=p)
        self.assertEqual((s, s2, b2), (201, 200, b))
        self.assertEqual(self.stock()[2], 3)
        self.assertEqual(self.count(), 1)

    def test_ac5_conflicting_replay_returns_409(self):
        self.post(self.payload())
        for p in [self.payload(quantity=2), self.payload(item_id=2)]:
            s, _, r = self.post(p)
            self.assertEqual((s, r['error']), (409, 'idempotency_key_conflict'))
        self.assertEqual(self.stock(), {1: 2, 2: 5})
        self.assertEqual(self.count(), 1)

    def test_ac6_http_race_never_oversells(self):
        barrier = threading.Barrier(20)
        results = []
        def run(i):
            try:
                barrier.wait(timeout=10)
                s, _, r = self.post(self.payload(str(i)))
                results.append((s, r.get('error')))
            except Exception as e:
                results.append(('exception', repr(e)))
        threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertEqual(Counter(results), {(201, None): 3, (409, 'insufficient_stock'): 17})
        self.assertEqual(self.stock()[1], 0)
        self.assertEqual(self.count(), 3)

    def test_ac7_internal_error_rolls_back(self):
        with closing(api._connect(self.db)) as c:
            c.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON reservations BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        s, _, r = self.post(self.payload())
        self.assertEqual((s, r['error']), (500, 'internal_error'))
        self.unchanged()
        with closing(api._connect(self.db)) as c:
            c.execute('DROP TRIGGER fail_insert')
        self.assertEqual(self.post(self.payload())[0], 201)

    def test_ac8_restart_preserves_state(self):
        p = self.payload(quantity=2)
        s, _, b = self.request('POST', '/api/reservations', body=p)
        self.assertEqual(s, 201)
        self.stop_server()
        self.start_server()
        self.assertEqual(self.stock()[1], 1)
        s2, _, b2 = self.request('POST', '/api/reservations', body=p)
        self.assertEqual((s2, b2), (200, b))
        self.assertEqual(self.post(dict(p, quantity=1))[0], 409)

    def test_ac10_busy_database_returns_503(self):
        with closing(api._connect(self.db)) as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                with mock.patch.object(api, 'BUSY_TIMEOUT_SECONDS', 0.2):
                    s, h, r = self.post(self.payload())
                self.assertEqual((s, h['retry-after'], r['error']), (503, '1', 'storage_busy'))
                self.unchanged()
            finally:
                c.execute('ROLLBACK')
        self.assertEqual(self.post(self.payload())[0], 201)

    def test_ac11_root_page_and_health_unchanged(self):
        s, _, b = self.request('GET', '/')
        self.assertEqual(s, 200)
        self.assertIn(b'Inventory canary', b)
        for value in json.loads(Path(app.__file__).with_name('labels.json').read_text()).values():
            self.assertIn(value.encode(), b)
        self.assertEqual(json.loads(self.request('GET', '/health')[2]), {'ok': True})
