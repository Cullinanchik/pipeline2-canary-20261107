import ast
import contextlib
import copy
import html
import http.client
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from collections import Counter
from contextlib import closing
from http import HTTPStatus
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs
import api
import app
from api import ApiError, Inventory, SchemaVersionError
from api import MAX_MIN_QUANTITY, MinQuantityError, filter_items, parse_min_quantity
from app import Handler, make_server, redact_request_line

ROOT = Path(__file__).resolve().parents[1]
INITIAL = [{'id': 1, 'name': 'Notebook', 'quantity': 3}, {'id': 2, 'name': 'Pencil', 'quantity': 5}]
SEED = {1: 3, 2: 5}
CATALOG = INITIAL
MESSAGES = {
    'duplicate': 'min_quantity must be specified at most once',
    'empty': 'min_quantity must not be empty',
    'too_large': 'min_quantity must not exceed 9223372036854775807',
    'negative': 'min_quantity must not be negative',
    'not_integer': 'min_quantity must be a whole number',
    'invalid': 'min_quantity must be a non-negative integer written with digits 0-9',
}
PROBE = 'synthetic_probe'
# Тексты страницы живут в labels.json и могут меняться другими задачами: сравниваем с ними, а не с литералом.
PAGE_LABELS = json.loads((ROOT / 'labels.json').read_text())


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.db = os.path.join(self.tmp, 'inventory.sqlite3')
        self.inv = Inventory(self.db)

    def query(self, sql, params=()):
        with closing(api._connect(self.db)) as c:
            return c.execute(sql, params).fetchall()

    def plain(self, path):
        return closing(sqlite3.connect(path, isolation_level=None))

    def stock(self):
        return dict(self.query('SELECT id, quantity FROM items'))

    def reservation_count(self):
        return self.query('SELECT count(*) FROM reservations')[0][0]

    def assert_invariant(self):
        for i, q in self.stock().items():
            reserved = self.query('SELECT COALESCE(SUM(quantity),0) FROM reservations WHERE item_id=?', (i,))[0][0]
            self.assertEqual(q + reserved, SEED[i])

    def payload(self, key='k-1', item_id=1, quantity=1):
        return dict(item_id=item_id, quantity=quantity, idempotency_key=key)

    def error(self, payload, status, code):
        with self.assertRaises(ApiError) as ctx:
            self.inv.reserve(payload)
        self.assertEqual((ctx.exception.status, ctx.exception.code), (status, code))
        return ctx.exception


class InventoryStorageTests(StorageTestCase):
    def test_ac1_items_have_unique_ids(self):
        items = self.inv.list_items()
        self.assertEqual(len({i['id'] for i in items}), len(items))
        self.assertTrue(all(i['quantity'] >= 0 for i in items))

    def test_ac1_items_are_fresh_values(self):
        items = self.inv.list_items()
        items[0]['quantity'] = -1
        items.append({})
        self.assertEqual(self.inv.list_items(), INITIAL)

    def test_ac1_fresh_database_has_initial_items(self):
        self.assertEqual(self.inv.list_items(), INITIAL)

    def test_ac1_reservation_reduces_listed_quantity(self):
        self.inv.reserve(self.payload(quantity=2))
        self.assertEqual(self.inv.list_items()[0]['quantity'], 1)

    def test_ac2_reserve_creates_reservation(self):
        status, r = self.inv.reserve(self.payload())
        self.assertEqual(status, 201)
        self.assertEqual(set(r), {'id', 'item_id', 'quantity', 'idempotency_key', 'created_at'})
        self.assertRegex(r['created_at'], r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$')
        self.assertEqual(self.stock()[1], 2)

    def test_ac2_reserve_exact_remaining_stock(self):
        self.assertEqual(self.inv.reserve(self.payload(quantity=3))[0], 201)
        self.error(self.payload('next'), 409, 'insufficient_stock')

    def test_ac2_unicode_keys_accepted(self):
        for key in ['заказ-№42 ✓', '🧾-1']:
            p = self.payload(key, 2)
            status, r = self.inv.reserve(p)
            self.assertEqual(status, 201)
            self.assertEqual(r['idempotency_key'], key)
            self.assertEqual(self.inv.reserve(p), (200, r))
        self.assertEqual(self.stock()[2], 3)
        self.assertEqual(self.reservation_count(), 2)

    def test_ac3_invalid_payloads_rejected_without_write(self):
        cases = [[], 'text', None, {}, {'item_id': 1, 'quantity': 1}, dict(self.payload(), note='x')]
        for field, values in [('item_id', ['1', True, 0, 2**63, 1.0]), ('quantity', [0, -1, 1.5, True, '2', 1_000_001]), ('idempotency_key', ['', '   ', 'x'*129, 5, None, '\ud800', 'x\udc00y'])]:
            cases.extend(dict(self.payload(), **{field: v}) for v in values)
        self.assertEqual(len(cases), 24)
        for p in cases:
            with self.subTest(p=p):
                self.error(p, 400, 'invalid_request')
        self.assertEqual(self.stock(), SEED)
        self.assertEqual(self.reservation_count(), 0)

    def test_ac3_unknown_item_rejected_without_write(self):
        self.error(self.payload(item_id=999), 404, 'item_not_found')
        self.assertEqual(self.stock(), SEED)
        self.assertEqual(self.reservation_count(), 0)

    def test_ac3_insufficient_stock_rejected_without_write(self):
        self.error(self.payload(item_id=2, quantity=6), 409, 'insufficient_stock')
        self.assertEqual(self.stock(), SEED)
        self.assertEqual(self.reservation_count(), 0)

    def test_ac4_replay_returns_original_reservation(self):
        p = self.payload(item_id=2, quantity=2)
        _, r = self.inv.reserve(p)
        self.assertEqual(self.inv.reserve(p), (200, r))
        self.assertEqual(self.stock()[2], 3)
        self.assertEqual(self.reservation_count(), 1)

    def test_ac4_replay_after_stock_exhausted(self):
        p = self.payload(quantity=3)
        _, r = self.inv.reserve(p)
        self.assertEqual(self.inv.reserve(p), (200, r))

    def test_ac5_same_key_different_data_conflicts(self):
        self.inv.reserve(self.payload())
        for p in [self.payload(quantity=2), self.payload(item_id=2)]:
            self.error(p, 409, 'idempotency_key_conflict')
        self.assertEqual(self.stock(), {1: 2, 2: 5})
        self.assertEqual(self.reservation_count(), 1)

    def test_ac5_failed_attempt_does_not_bind_key(self):
        for n, (changes, status, code) in enumerate([({'quantity': 6}, 409, 'insufficient_stock'), ({'item_id': 999}, 404, 'item_not_found'), ({'quantity': 0}, 400, 'invalid_request')]):
            p = self.payload(str(n), 2)
            self.error(dict(p, **changes), status, code)
            self.assertEqual(self.inv.reserve(p)[0], 201)

    def test_ac7_failure_after_stock_update_rolls_back(self):
        self.query("CREATE TRIGGER fail_insert BEFORE INSERT ON reservations BEGIN SELECT RAISE(ABORT, 'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.inv.reserve(self.payload())
        self.assertEqual(self.stock(), SEED)
        self.assertEqual(self.reservation_count(), 0)
        self.assert_invariant()
        with closing(api._connect(self.db)) as c:
            self.assertFalse(c.in_transaction)
        self.query('DROP TRIGGER fail_insert')
        self.assertEqual(self.inv.reserve(self.payload())[0], 201)

    def test_ac8_reinitialization_preserves_state(self):
        _, r = self.inv.reserve(self.payload())
        for _ in range(2):
            inv = Inventory(self.db)
            self.assertEqual(inv.reserve(self.payload()), (200, r))
            self.assertEqual(self.stock(), {1: 2, 2: 5})
            self.assertEqual(self.reservation_count(), 1)

    def test_ac8_schema_version_and_journal_mode(self):
        self.assertEqual(self.query('PRAGMA user_version'), [(1,)])
        self.assertEqual(self.query('PRAGMA journal_mode'), [('delete',)])

    def test_ac8_newer_schema_is_refused(self):
        self.query('PRAGMA user_version = 99')
        with self.assertRaises(SchemaVersionError):
            Inventory(self.db)
        self.assertEqual(self.query('PRAGMA user_version'), [(99,)])
        self.assertEqual(self.stock(), SEED)

    def test_ac8_newer_wal_schema_is_refused_unchanged(self):
        path = os.path.join(self.tmp, 'future.sqlite3')
        with self.plain(path) as c:
            c.execute('PRAGMA journal_mode = WAL')
            c.execute('CREATE TABLE marker (v TEXT)')
            c.execute("INSERT INTO marker VALUES ('keep')")
            c.execute('PRAGMA user_version = 99')
        with self.assertRaises(SchemaVersionError):
            Inventory(path)
        with self.plain(path) as c:
            self.assertEqual(c.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], 99)
            self.assertEqual(c.execute('SELECT v FROM marker').fetchall(), [('keep',)])
            self.assertEqual(c.execute('SELECT name FROM sqlite_master WHERE type="table"').fetchall(), [('marker',)])
        self.assertEqual(sorted(n for n in os.listdir(self.tmp) if n.startswith('future.sqlite3')), ['future.sqlite3'])

    def test_ac8_version_recheck_under_migration_lock(self):
        path = os.path.join(self.tmp, 'recheck.sqlite3')
        with mock.patch.object(api, '_user_version', side_effect=[0, 99]):
            with self.assertRaises(SchemaVersionError):
                Inventory(path)
        with self.plain(path) as c:
            self.assertEqual(c.execute('SELECT count(*) FROM sqlite_master').fetchone()[0], 0)
            self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0], 0)

    def test_ac8_v1_wal_database_is_converted_to_delete(self):
        self.inv.reserve(self.payload(item_id=2, quantity=2))
        with self.plain(self.db) as c:
            c.execute('PRAGMA journal_mode = WAL')
        Inventory(self.db)
        self.assertEqual(self.query('PRAGMA journal_mode'), [('delete',)])
        self.assertEqual(self.stock()[2], 3)
        self.assertEqual(self.reservation_count(), 1)

    def test_ac10_connection_mode_probe(self):
        self.assertGreaterEqual(sqlite3.sqlite_version_info, (3, 7, 11))
        with closing(api._connect(self.db)) as c:
            self.assertFalse(c.in_transaction)
            if hasattr(sqlite3, 'LEGACY_TRANSACTION_CONTROL'):
                self.assertIs(c.autocommit, True)
            c.execute('BEGIN IMMEDIATE')
            self.assertTrue(c.in_transaction)
            c.execute('ROLLBACK')
            self.assertFalse(c.in_transaction)

    def test_ac10_busy_database_maps_to_503(self):
        with closing(api._connect(self.db)) as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                with mock.patch.object(api, 'BUSY_TIMEOUT_SECONDS', 0.2):
                    err = self.error(self.payload(), 503, 'storage_busy')
                    self.assertIn(('Retry-After', '1'), err.headers)
                    self.assertEqual(self.reservation_count(), 0)
            finally:
                c.execute('ROLLBACK')
        self.assertEqual(self.inv.reserve(self.payload())[0], 201)

    def test_ac11_only_stdlib_imports(self):
        allowed = {'argparse', 'html', 'http', 'json', 'pathlib', 'sqlite3', 'urllib', 'contextlib', 'api'}
        for filename in ['app.py', 'api.py']:
            for n in ast.walk(ast.parse((ROOT / filename).read_text())):
                names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module] if isinstance(n, ast.ImportFrom) else []
                self.assertTrue(all(s.split('.')[0] in allowed for s in names))


class ConcurrencyTests(StorageTestCase):
    def race(self, count, same=False):
        barrier = threading.Barrier(count)
        results = []
        def run(i):
            try:
                barrier.wait(timeout=10)
                status, r = self.inv.reserve(self.payload('same' if same else f'race-{i}', 2 if same else 1, 2 if same else 1))
                results.append(('ok', status, r['id']))
            except ApiError as e:
                results.append(('api', e.code, None))
            except Exception as e:
                results.append(('exc', repr(e), None))
        threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(count)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assert_invariant()
        return results

    def test_ac6_concurrent_reservations_never_oversell(self):
        r = self.race(30)
        self.assertEqual(Counter((a, b) for a, b, _ in r), {('ok', 201): 3, ('api', 'insufficient_stock'): 27})
        self.assertEqual(self.stock()[1], 0)
        self.assertEqual(self.reservation_count(), 3)

    def test_ac6_concurrent_same_key_creates_one_reservation(self):
        r = self.race(10, True)
        self.assertEqual(Counter((a, b) for a, b, _ in r), {('ok', 201): 1, ('ok', 200): 9})
        self.assertEqual(len({i for _, _, i in r}), 1)
        self.assertEqual(self.stock()[2], 3)
        self.assertEqual(self.reservation_count(), 1)


class RecoveryTests(StorageTestCase):
    def child(self, code):
        return subprocess.run([sys.executable, '-I', '-c', 'import sys, os; sys.path.insert(0, sys.argv[1]); import api\ndb=sys.argv[2]\n' + code, str(ROOT), self.db], timeout=30)

    def test_ac9_crash_before_commit_rolls_back(self):
        r = self.child("""c=api._connect(db)
c.execute('PRAGMA cache_size = 10')
c.execute('BEGIN IMMEDIATE')
c.execute('UPDATE items SET quantity = 0 WHERE id = 1')
c.executemany('INSERT INTO reservations (idempotency_key,item_id,quantity) VALUES (?, ?, ?)', [('crash-%05d-' % i + 'x'*100, 2, 1) for i in range(2000)])
os._exit(1)
""")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(os.path.exists(self.db + '-journal'))
        Inventory(self.db)
        self.assertEqual(self.stock(), SEED)
        self.assertEqual(self.reservation_count(), 0)
        self.assertEqual(self.query('PRAGMA integrity_check'), [('ok',)])
        self.assertEqual(self.inv.reserve(self.payload())[0], 201)

    def test_ac9_committed_reservation_survives_abrupt_exit(self):
        p = self.payload('child-commit', 2, 2)
        r = self.child(f"status, _ = api.Inventory(db).reserve({p!r})\nos._exit(0 if status == 201 else 3)")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.stock()[2], 3)
        self.assertEqual(self.inv.reserve(p)[0], 200)


class FilterItemsTests(unittest.TestCase):
    SAMPLE = [
        {'id': 1, 'quantity': 0},
        {'id': 2, 'quantity': 2},
        {'id': 3, 'quantity': 3},
        {'id': 4, 'quantity': 3},
        {'id': 5, 'quantity': 10},
    ]

    def test_boundary_is_inclusive_and_order_preserved(self):
        self.assertEqual([item['id'] for item in filter_items(self.SAMPLE, 3)], [3, 4, 5])

    def test_zero_returns_all(self):
        self.assertEqual([item['id'] for item in filter_items(self.SAMPLE, 0)], [1, 2, 3, 4, 5])

    def test_threshold_above_maximum_returns_empty(self):
        for threshold in (11, MAX_MIN_QUANTITY):
            with self.subTest(threshold=threshold):
                self.assertEqual(filter_items(self.SAMPLE, threshold), [])

    def test_empty_input_returns_empty(self):
        self.assertEqual(filter_items([], 0), [])

    def test_input_not_mutated_and_result_is_new_list(self):
        before = copy.deepcopy(self.SAMPLE)
        result = filter_items(self.SAMPLE, 0)
        self.assertIsNot(result, self.SAMPLE)
        result.append({})
        self.assertEqual(self.SAMPLE, before)


class ParseMinQuantityTests(unittest.TestCase):
    def test_absent_returns_none(self):
        for query in ('', '&', '=5', 'foo=1', 'min_qty=3', 'MIN_QUANTITY=3'):
            with self.subTest(query=query):
                self.assertIsNone(parse_min_quantity(query))

    def test_valid_values(self):
        cases = [
            ('min_quantity=0', 0),
            ('min_quantity=00', 0),
            ('min_quantity=3', 3),
            ('min_quantity=007', 7),
            ('min_quantity=9223372036854775807', MAX_MIN_QUANTITY),
            ('min_quantity=' + '0' * 5000 + '1', 1),
            ('min_quantity=4&foo=bar', 4),
            ('foo=&min_quantity=4', 4),
            ('min%5Fquantity=4', 4),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                result = parse_min_quantity(query)
                self.assertEqual(result, expected)
                self.assertIs(type(result), int)

    def test_error_codes(self):
        cases = [
            ('min_quantity=', 'empty'),
            ('min_quantity', 'empty'),
            ('min_quantity=9223372036854775808', 'too_large'),
            ('min_quantity=99999999999999999999', 'too_large'),
            ('min_quantity=1' + '0' * 5000, 'too_large'),
            ('min_quantity=-1', 'negative'),
            ('min_quantity=-05', 'negative'),
            ('min_quantity=2.5', 'not_integer'),
            ('min_quantity=3.0', 'not_integer'),
            ('min_quantity=.5', 'not_integer'),
            ('min_quantity=5.', 'not_integer'),
            ('min_quantity=-2.5', 'not_integer'),
            ('min_quantity=%2B2.5', 'not_integer'),
            ('min_quantity=-0', 'invalid'),
            ('min_quantity=--1', 'invalid'),
            ('min_quantity=abc', 'invalid'),
            ('min_quantity=%2B1', 'invalid'),
            ('min_quantity=+1', 'invalid'),
            ('min_quantity=1e3', 'invalid'),
            ('min_quantity=%D9%A1', 'invalid'),
            ('min_quantity=%C2%B2', 'invalid'),
            ('min_quantity=1%0A', 'invalid'),
            ('min_quantity=1_000', 'invalid'),
            ('min_quantity=0x10', 'invalid'),
            ('min_quantity=%FF', 'invalid'),
            ('min_quantity=1;min_quantity=2', 'invalid'),
            ('min_quantity=-', 'invalid'),
            ('min_quantity=.', 'invalid'),
            ('min_quantity=%20', 'invalid'),
            ('min_quantity=3&min_quantity=3', 'duplicate'),
            ('min_quantity=3&min%5Fquantity=4', 'duplicate'),
            ('min_quantity=3&min_quantity=', 'duplicate'),
        ]
        for query, code in cases:
            with self.subTest(query=query, code=code):
                with self.assertRaises(MinQuantityError) as ctx:
                    parse_min_quantity(query)
                self.assertEqual(ctx.exception.code, code)

    def test_error_messages_and_payload(self):
        for code in MESSAGES:
            with self.subTest(code=code):
                err = MinQuantityError(code)
                self.assertIsInstance(err, ValueError)
                self.assertEqual(str(err), MESSAGES[code])
                self.assertEqual(err.message, MESSAGES[code])
                self.assertEqual(err.to_dict(), {
                    'error': {'code': code, 'parameter': 'min_quantity', 'message': MESSAGES[code]},
                })

    def test_parse_qs_semantics_probe(self):
        cases = [
            ('min_quantity=', {'min_quantity': ['']}),
            ('min_quantity', {'min_quantity': ['']}),
            ('min_quantity=+1', {'min_quantity': [' 1']}),
            ('min_quantity=1;min_quantity=2', {'min_quantity': ['1;min_quantity=2']}),
            ('min_quantity=3&min%5Fquantity=4', {'min_quantity': ['3', '4']}),
        ]
        for query, expected in cases:
            with self.subTest(query=query):
                self.assertEqual(parse_qs(query, keep_blank_values=True), expected)


class CatalogHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        silence = mock.patch.object(Handler, 'log_message', lambda *args, **kwargs: None)
        silence.start()
        cls.addClassCleanup(silence.stop)
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.db = os.path.join(cls.tmp.name, 'inventory.sqlite3')
        cls.server = make_server('127.0.0.1', 0, cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(10)

    def get(self, target):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=10)
        try:
            connection.request('GET', target)
            response = connection.getresponse()
            body = response.read()
            return (response.status, response.getheader('Content-Type'),
                    response.getheader('Content-Length'), body)
        finally:
            connection.close()

    def test_no_filter_returns_full_catalog(self):
        for target in ('/api/items', '/api/items?'):
            with self.subTest(target=target):
                status, content_type, content_length, body = self.get(target)
                self.assertEqual(status, 200)
                self.assertEqual(content_type, 'application/json')
                self.assertEqual(int(content_length), len(body))
                self.assertEqual(body, json.dumps(Inventory(self.db).list_items()).encode())
                self.assertEqual(json.loads(body), CATALOG)

    def test_filter_results(self):
        cases = [
            ('0', [1, 2]),
            ('3', [1, 2]),
            ('4', [2]),
            ('5', [2]),
            ('004', [2]),
            ('6', []),
            ('9223372036854775807', []),
        ]
        for value, ids in cases:
            with self.subTest(value=value):
                status, content_type, content_length, body = self.get('/api/items?min_quantity=' + value)
                self.assertEqual(status, 200)
                self.assertEqual(content_type, 'application/json')
                self.assertEqual(int(content_length), len(body))
                self.assertEqual(json.loads(body), [item for item in CATALOG if item['id'] in ids])
                if value == '0':
                    self.assertEqual(body, json.dumps(Inventory(self.db).list_items()).encode())

    def test_invalid_values_return_400_json(self):
        cases = [
            ('?min_quantity=', 'empty'),
            ('?min_quantity', 'empty'),
            ('?min_quantity=-1', 'negative'),
            ('?min_quantity=2.5', 'not_integer'),
            ('?min_quantity=3.0', 'not_integer'),
            ('?min_quantity=abc', 'invalid'),
            ('?min_quantity=%2B1', 'invalid'),
            ('?min_quantity=+1', 'invalid'),
            ('?min_quantity=%D9%A1', 'invalid'),
            ('?min_quantity=1%0A', 'invalid'),
            ('?min_quantity=9223372036854775808', 'too_large'),
            ('?min_quantity=3&min_quantity=3', 'duplicate'),
            ('?min_quantity=3&min%5Fquantity=4', 'duplicate'),
            ('?min_quantity=1;min_quantity=2', 'invalid'),
        ]
        for suffix, code in cases:
            with self.subTest(target='/api/items' + suffix):
                status, content_type, content_length, body = self.get('/api/items' + suffix)
                self.assertEqual(status, 400)
                self.assertEqual(content_type, 'application/json')
                self.assertEqual(int(content_length), len(body))
                self.assertEqual(json.loads(body), {
                    'error': {'code': code, 'parameter': 'min_quantity', 'message': MESSAGES[code]},
                })

    def test_unknown_parameters_are_ignored(self):
        for target in ('/api/items?min_qty=3', '/api/items?MIN_QUANTITY=4', '/api/items?foo=bar'):
            with self.subTest(target=target):
                status, content_type, content_length, body = self.get(target)
                self.assertEqual(status, 200)
                self.assertEqual(content_type, 'application/json')
                self.assertEqual(json.loads(body), CATALOG)
        for target in ('/api/items?foo=bar&min_quantity=4', '/api/items?min_quantity=4&foo='):
            with self.subTest(target=target):
                status, content_type, content_length, body = self.get(target)
                self.assertEqual(status, 200)
                self.assertEqual(content_type, 'application/json')
                self.assertEqual(json.loads(body), [CATALOG[1]])

    def test_other_routes_unchanged(self):
        page_status, page_type, page_length, page_body = self.get('/')
        filtered_status, filtered_type, filtered_length, filtered_body = self.get('/?min_quantity=abc')
        self.assertEqual(page_status, 200)
        self.assertEqual(filtered_status, 200)
        self.assertEqual(page_type, 'text/html; charset=utf-8')
        self.assertEqual(filtered_type, 'text/html; charset=utf-8')
        self.assertEqual(int(page_length), len(page_body))
        self.assertIn(b'<h1>Inventory canary</h1>', page_body)
        self.assertIn(b'Status: ' + html.escape(PAGE_LABELS['badge']).encode(), page_body)
        self.assertIn(b'>' + html.escape(PAGE_LABELS['button']).encode() + b'</button>', page_body)
        self.assertEqual(page_body, filtered_body)
        for target in ('/health', '/health?min_quantity=-1'):
            with self.subTest(target=target):
                status, content_type, content_length, body = self.get(target)
                self.assertEqual(status, 200)
                self.assertEqual(content_type, 'application/json')
                self.assertEqual(body, b'{"ok": true}')
        for target in ('/missing', '/api/items/', '/api/items/?min_quantity=1'):
            with self.subTest(target=target):
                status, content_type, content_length, body = self.get(target)
                self.assertEqual(status, 404)


class RedactRequestLineTests(unittest.TestCase):
    def test_redact_request_line(self):
        cases = [
            ('GET /api/items?min_quantity=synthetic_probe HTTP/1.1', 'GET /api/items [query redacted]'),
            ('GET /api/items HTTP/1.1', 'GET /api/items HTTP/1.1'),
            ('GET /api/items#min_quantity=synthetic_probe HTTP/1.1', 'GET /api/items [query redacted]'),
            ('GET /api/items?min_quantity=1 2 HTTP/1.1', 'GET /api/items [query redacted]'),
            ('GET /?a#b HTTP/1.1', 'GET / [query redacted]'),
            ('GET /api/items? HTTP/1.1', 'GET /api/items [query redacted]'),
            ('', ''),
        ]
        for line, expected in cases:
            with self.subTest(line=line):
                self.assertEqual(redact_request_line(line), expected)

    def test_log_request_redacts_query(self):
        handler = object.__new__(Handler)
        handler.requestline = 'GET /api/items?min_quantity=' + PROBE + ' HTTP/1.1'
        handler.client_address = ('127.0.0.1', 0)
        for code, text in ((HTTPStatus.BAD_REQUEST, '400'), (200, '200'), ('-', '-')):
            with self.subTest(code=code):
                captured = io.StringIO()
                with contextlib.redirect_stderr(captured):
                    handler.log_request(code)
                log = captured.getvalue()
                self.assertIn('"GET /api/items [query redacted]" ' + text + ' -', log)
                self.assertNotIn(PROBE, log)
                self.assertNotIn('min_quantity', log)


class RequestLogHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.db = os.path.join(cls.tmp.name, 'inventory.sqlite3')
        cls.server = make_server('127.0.0.1', 0, cls.db)
        cls.thread = threading.Thread(target=cls.server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(10)

    def get_logged(self, target):
        captured = io.StringIO()
        with contextlib.redirect_stderr(captured):
            connection = http.client.HTTPConnection('127.0.0.1', self.server.server_address[1], timeout=10)
            try:
                connection.request('GET', target)
                response = connection.getresponse()
                body = response.read()
                status = response.status
            finally:
                connection.close()
        return status, body, captured.getvalue()

    def test_access_log_omits_query(self):
        cases = [
            ('/api/items?min_quantity=' + PROBE, 400, '/api/items', [PROBE]),
            ('/api/items?min_quantity=' + 'x' * 5000, 400, '/api/items', ['x' * 64]),
            ('/api/items?min_quantity=' + '0' * 64 + '4' + '&note=' + PROBE, 200, '/api/items', ['0' * 64, PROBE]),
            ('/health?min_quantity=' + PROBE, 200, '/health', [PROBE]),
            ('/missing?min_quantity=' + PROBE, 404, '/missing', [PROBE]),
        ]
        for target, expected_status, path, secrets in cases:
            with self.subTest(path=path, status=expected_status):
                status, body, log = self.get_logged(target)
                self.assertEqual(status, expected_status)
                self.assertIn('"GET ' + path + ' [query redacted]" ' + str(expected_status) + ' -', log)
                self.assertNotIn('min_quantity', log)
                for secret in secrets:
                    self.assertNotIn(secret, log)
                    self.assertNotIn(secret.encode(), body)

    def test_access_log_without_query_unchanged(self):
        status, body, log = self.get_logged('/api/items')
        self.assertEqual(status, 200)
        self.assertIn('"GET /api/items HTTP/1.1" 200 -', log)
        self.assertNotIn('[query redacted]', log)
