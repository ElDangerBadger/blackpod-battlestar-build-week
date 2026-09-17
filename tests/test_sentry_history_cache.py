"""No-network recovery cache tests; all mutations stay in temporary folders."""
from __future__ import annotations

import hashlib
from datetime import date, timedelta
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.sentry_history_cache import (
    CheckpointStore, EMPTY_CSV, MAX_BYTES, RecoveryError, atomic_write,
    read_regular, validate_csv,
)


START, END = "2026-07-18", "2026-09-16"
NOW = "2026-09-17T01:02:03Z"
ROW = b"2026-09-15,10,12,9,11,10.5,1000\n"
DATA = EMPTY_CSV + ROW


class CSVValidationTests(unittest.TestCase):
    def test_canonical_cells_are_preserved_not_reserialized(self):
        data = (EMPTY_CSV.replace(b"\n", b"\r\n")
                + b"2026-09-15,1e1,12.00,9,11,,1000.0\r\n"
                + b"2026-09-16,11,13,10,12,12,0\r\n")
        rows = validate_csv(data, START, END)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["open"], "1e1")
        self.assertEqual(rows[0]["adj_close"], "")
        self.assertEqual(rows[0]["volume"], "1000.0")

    def test_empty_requires_explicit_permission_and_valid_header(self):
        with self.assertRaises(RecoveryError):
            validate_csv(EMPTY_CSV, START, END)
        self.assertEqual(validate_csv(EMPTY_CSV, START, END, allow_empty=True), [])
        for data in (b"", b"date,close\n", EMPTY_CSV + b"\n"):
            with self.subTest(data=data), self.assertRaises(RecoveryError):
                validate_csv(data, START, END, allow_empty=True)

    def test_invalid_headers_row_width_encoding_and_bounds(self):
        invalid = (DATA.replace(b"adj_close", b"Adj Close"), DATA.replace(b"volume", b"close"),
                   DATA + b"2026-09-16,1,2,1,2,2,10,extra\n", EMPTY_CSV + b"2026-09-15,1,2\n",
                   b"\xef\xbb\xbf" + DATA, b"\xff", b"x" * (MAX_BYTES + 1),
                   EMPTY_CSV + ROW * 1001)
        for data in invalid:
            with self.subTest(length=len(data)), self.assertRaises(RecoveryError):
                validate_csv(data, START, END)

    def test_invalid_dates_duplicate_reversed_and_outside_window(self):
        for value in ("2026-07-17", "2026-09-17", "20260915", "2026-9-15", "2026-02-30"):
            with self.subTest(value=value), self.assertRaises(RecoveryError):
                validate_csv(DATA.replace(b"2026-09-15", value.encode()), START, END)
        for data in (DATA + ROW, DATA + ROW.replace(b"09-15", b"09-14")):
            with self.assertRaises(RecoveryError):
                validate_csv(data, START, END)
        with self.assertRaises(RecoveryError):
            validate_csv(DATA, END, START)

    def test_row_limit_with_otherwise_valid_unique_dates(self):
        first = date(2020, 1, 1)
        rows = [f"{first + timedelta(days=index)},10,12,9,11,11,1000\n".encode()
                for index in range(1001)]
        with self.assertRaisesRegex(RecoveryError, "count"):
            validate_csv(EMPTY_CSV + b"".join(rows), "2020-01-01", "2022-12-31")

    def test_prices_and_volume_are_strict_finite_numbers(self):
        cells = ROW.decode().strip().split(",")
        for column in range(1, 7):
            values = ["NaN", "inf", "1e999", "1_000", " 1", "n/a"]
            values += ["", "0", "-1", "1e-999"] if column != 6 else ["", "-1", "1.5"]
            for value in values:
                if column == 5 and value == "":
                    continue
                changed = list(cells)
                changed[column] = value
                with self.subTest(column=column, value=value), self.assertRaises(RecoveryError):
                    validate_csv(EMPTY_CSV + (",".join(changed) + "\n").encode(), START, END)


class SafePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_atomic_write_and_regular_read(self):
        target = self.root / "nested" / "file.csv"
        atomic_write(target, DATA)
        self.assertEqual(read_regular(target), DATA)
        atomic_write(target, DATA + ROW.replace(b"09-15", b"09-16"))
        self.assertTrue(read_regular(target).endswith(b"1000\n"))
        self.assertEqual(list(target.parent.glob(".sentry-*.tmp")), [])
        with self.assertRaises(RecoveryError):
            read_regular(target, 1)

    def test_symlink_file_or_ancestor_and_hardlink_are_rejected(self):
        target = self.root / "real.csv"
        target.write_bytes(DATA)
        linked = self.root / "linked.csv"
        linked.symlink_to(target)
        parent_link = self.root / "linkdir"
        parent_link.symlink_to(self.root, target_is_directory=True)
        hard = self.root / "hard.csv"
        os.link(target, hard)
        for path in (linked, parent_link / "real.csv", hard, target):
            with self.subTest(path=path), self.assertRaises(RecoveryError):
                read_regular(path)
            with self.subTest(write=path), self.assertRaises(RecoveryError):
                atomic_write(path, b"do not overwrite")
        self.assertEqual(target.read_bytes(), DATA)

    def test_special_files_and_traversal_are_rejected(self):
        fifo = self.root / "pipe"
        os.mkfifo(fifo)
        for path in (fifo, self.root, self.root / "../outside"):
            with self.subTest(path=path), self.assertRaises(RecoveryError):
                read_regular(path)
        with self.assertRaises(RecoveryError):
            atomic_write(fifo, DATA)
        with self.assertRaises(RecoveryError):
            atomic_write(self.root / "../outside", DATA)

    def test_replacement_during_read_fails_closed(self):
        target = self.root / "capture.csv"
        target.write_bytes(DATA)
        real_read = os.read
        def replace(descriptor, count):
            content = real_read(descriptor, count)
            replacement = self.root / "replacement.csv"
            replacement.write_bytes(DATA)
            replacement.replace(target)
            return content
        with patch("blackpod_build_week.sentry_history_cache.os.read", side_effect=replace):
            with self.assertRaises(RecoveryError):
                read_regular(target)


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "run"
        self.identity = {"source_snapshot": "snapshot-one", "policy_sha256": "a" * 64,
                         "request": {"provider": "captured", "offline": False}}
        self.symbols = ("A.B", "A-B", "A_B", "EMPTY")

    def store(self, **updates):
        args = dict(root=self.root, identity=self.identity, start=START, end=END,
                    symbols=self.symbols, now=lambda: NOW)
        args.update(updates)
        return CheckpointStore(**args)

    def test_adoption_preserves_bytes_and_distinguishes_first_seen_from_source_time(self):
        store = self.store()
        source = self.root.parent / "original.csv"
        source.write_bytes(DATA.replace(b"\n", b"\r\n"))
        original = source.read_bytes()
        entry = store.adopt("A.B", original, "legacy_validated", source_path=str(source))
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(read_regular(self.root / "cache" / entry["file_name"]), original)
        self.assertEqual(entry["operation"], "adopt")
        self.assertEqual(entry["first_seen_at"], NOW)
        self.assertIsNone(entry["source_time"])
        self.assertEqual(entry["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(len(self.store().rows("A.B")), 1)

    def test_checkpoint_after_each_symbol_distinct_hashed_names_and_defensive_copies(self):
        store = self.store()
        names = []
        for symbol in self.symbols[:3]:
            entry = store.record(symbol, DATA, source_time=NOW)
            names.append(entry["file_name"])
            self.assertEqual(entry["file_name"], hashlib.sha256(symbol.encode()).hexdigest() + ".csv")
            self.assertIsNotNone(self.store().rows(symbol))
            entry["sha256"] = "corrupt external copy"
        self.assertEqual(len(set(names)), 3)
        copied = store.entries
        copied["A.B"]["source_kind"] = "changed"
        self.assertEqual(store.entries["A.B"]["source_kind"], "provider")

    def test_empty_adoption_and_generic_provider_empty_remain_pending(self):
        store = self.store()
        for call in (lambda: store.adopt("EMPTY", EMPTY_CSV, "legacy"),
                     lambda: store.record("EMPTY", EMPTY_CSV)):
            with self.assertRaises(RecoveryError):
                call()
        self.assertIsNone(self.store().rows("EMPTY"))
        self.assertNotIn("EMPTY", store.entries)

    def test_recorded_unavailable_is_explicit_pinned_and_not_a_valid_market_history(self):
        store = self.store()
        entry = store.record_unavailable("EMPTY", "YFPricesMissingError", source_time=NOW)
        self.assertEqual(entry["status"], "unavailable")
        self.assertEqual(entry["row_count"], 0)
        self.assertEqual(entry["reason"], "YFPricesMissingError")
        self.assertEqual(read_regular(self.root / "cache" / entry["file_name"]), EMPTY_CSV)
        self.assertEqual(self.store().rows("EMPTY"), [])
        with self.assertRaises(RecoveryError):
            store.record_unavailable("A.B", "provider says: private/path")

    def test_unavailable_cannot_override_ready_or_be_silently_replaced(self):
        store = self.store()
        store.record("A.B", DATA)
        with self.assertRaises(RecoveryError):
            store.record_unavailable("A.B", "YFPricesMissingError")
        store.record_unavailable("EMPTY", "YFTzMissingError")
        with self.assertRaises(RecoveryError):
            store.record("EMPTY", DATA)
        self.assertEqual(self.store().rows("EMPTY"), [])

    def test_request_identity_dates_and_symbol_order_cannot_change_on_resume(self):
        self.store().record("A.B", DATA)
        for change in ({"identity": {"source_snapshot": "another"}},
                       {"start": "2026-07-19"}, {"end": "2026-09-15"},
                       {"symbols": tuple(reversed(self.symbols))}):
            with self.subTest(change=change), self.assertRaises(RecoveryError):
                self.store(**change)

    def test_source_identity_and_bytes_are_immutable_with_idempotent_retry(self):
        store = self.store()
        first = store.adopt("A.B", DATA, "legacy", source_path="original.csv")
        self.assertEqual(store.adopt("A.B", DATA, "legacy", source_path="original.csv"), first)
        for call in (lambda: store.adopt("A.B", DATA, "legacy", source_path="different.csv"),
                     lambda: store.record("A.B", DATA),
                     lambda: store.adopt("A.B", DATA.replace(b"1000", b"2000"), "legacy", source_path="original.csv")):
            with self.assertRaises(RecoveryError):
                call()

    def test_cache_tampering_rejected_on_read_and_resume(self):
        store = self.store()
        entry = store.record("A.B", DATA)
        (self.root / "cache" / entry["file_name"]).write_bytes(DATA.replace(b"1000", b"2000"))
        with self.assertRaises(RecoveryError):
            store.rows("A.B")
        with self.assertRaises(RecoveryError):
            self.store()

    def test_metadata_tampering_and_duplicate_json_keys_fail_closed(self):
        store = self.store()
        entry = store.record("A.B", DATA)
        path = self.root / "entries" / entry["file_name"].replace(".csv", ".json")
        original = path.read_bytes()
        changed = json.loads(original)
        changed["source_kind"] = "different"
        path.write_text(json.dumps(changed))
        with self.assertRaises(RecoveryError):
            self.store()
        with self.assertRaises(RecoveryError):
            store.rows("A.B")
        path.write_bytes(original.replace(b'"symbol":', b'"symbol":"A.B","symbol":', 1))
        with self.assertRaises(RecoveryError):
            self.store()

    def test_entry_from_another_request_and_null_commit_marker_are_rejected(self):
        store = self.store()
        entry = store.record("A.B", DATA)
        other_root = self.root.parent / "different-run"
        other_identity = {**self.identity, "source_snapshot": "another-snapshot"}
        self.store(root=other_root, identity=other_identity)
        csv_name = entry["file_name"]
        json_name = csv_name.replace(".csv", ".json")
        atomic_write(other_root / "cache" / csv_name, read_regular(self.root / "cache" / csv_name))
        atomic_write(other_root / "entries" / json_name, read_regular(self.root / "entries" / json_name))
        with self.assertRaises(RecoveryError):
            self.store(root=other_root, identity=other_identity)
        atomic_write(self.root / "entries" / json_name, b"null\n")
        with self.assertRaises(RecoveryError):
            self.store()

    def test_request_checkpoint_cannot_be_lost_or_silently_recreated(self):
        store = self.store()
        state_path = self.root / "state.json"
        original = state_path.read_bytes()
        store.record("A.B", DATA)
        self.assertEqual(state_path.read_bytes(), original)
        state_path.unlink()
        with self.assertRaises(RecoveryError):
            self.store()
        self.assertFalse(state_path.exists())

    def test_orphan_cache_is_not_trusted_as_completed(self):
        store = self.store()
        name = hashlib.sha256(b"A.B").hexdigest() + ".csv"
        atomic_write(self.root / "cache" / name, DATA)
        resumed = self.store()
        self.assertIsNone(resumed.rows("A.B"))
        self.assertEqual(resumed.entries, {})
        self.assertEqual(store.entries, {})

    def test_checkpoint_failure_leaves_only_untrusted_orphan(self):
        store = self.store()
        from blackpod_build_week import sentry_history_cache as module
        real_write = module.atomic_write
        def fail_state(path, data):
            if path.parent.name == "entries":
                raise RecoveryError("simulated checkpoint failure")
            return real_write(path, data)
        with patch.object(module, "atomic_write", side_effect=fail_state):
            with self.assertRaises(RecoveryError):
                store.record("A.B", DATA)
        self.assertIsNone(store.rows("A.B"))
        self.assertIsNone(self.store().rows("A.B"))

    def test_unknown_symbols_bad_metadata_and_unsafe_checkpoint_paths_rejected(self):
        store = self.store()
        for call in (lambda: store.rows("OTHER"), lambda: store.record("../A", DATA),
                     lambda: store.record("A.B", DATA, source_time="2026-09-17"),
                     lambda: store.record("A.B", DATA, source_kind="bad\ntext")):
            with self.assertRaises(RecoveryError):
                call()
        linked = self.root.parent / "linked"
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(RecoveryError):
            self.store(root=linked)
        state = self.root / "state.json"
        original = self.root.parent / "state-copy.json"
        state.replace(original)
        state.symlink_to(original)
        with self.assertRaises(RecoveryError):
            self.store()


if __name__ == "__main__":
    unittest.main()
