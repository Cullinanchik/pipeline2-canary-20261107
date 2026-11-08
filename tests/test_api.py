import ast
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from collections import Counter
from contextlib import closing
from pathlib import Path
from unittest import mock
import api
from api import ApiError, Inventory, SchemaVersionError

ROOT = Path(__file__).resolve().parents[1]
INITIAL = [{'id': 1, 'name': 'Notebook', 'quantity': 3}, {'id': 2, 'name': 'Pencil', 'quantity': 5}]
SEED = {1: 3, 2: 5}


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
