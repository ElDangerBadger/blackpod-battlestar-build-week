"""Offline presentation tests; original historical evidence stays immutable."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from html.parser import HTMLParser
from io import StringIO
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import shadow_historical_baseline_cli as baseline_cli
from blackpod_build_week import shadow_historical_dashboard as dashboard
from blackpod_build_week.decision_journal_store import JournalStoreError
from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.shadow_experiment import freeze_experiment
from test_shadow_experiment import fixture as protocol_fixture
from test_shadow_historical_baseline import calculate, fixture
from test_shadow_historical_cli import protected_fixture


def snapshot(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns,
                                        path.stat().st_mode)
            for path in root.rglob("*") if path.is_file()}


def historical_bundle(base):
    """Build the existing real verifier's synthetic, source-bound fixture."""
    arguments, _ = fixture()
    material = calculate(arguments)
    history = base / "history"
    history.mkdir()
    for symbol, raw in arguments["source_blobs"].items():
        (history / (symbol + ".csv")).write_bytes(raw)
    manifest = history / "backfill.json"
    manifest.write_bytes(canonical_json_bytes({"provider": "yfinance", "interval": "1d",
        "generated_at": "2026-07-16T23:30:11Z", "series": [{"symbol": row["symbol"],
            "row_count": row["source_row_count"], "first_date": row["source_first_date"],
            "last_date": row["source_last_date"]} for row in material["report"]["source_coverage"]]}))
    calendar = base / "calendar"
    calendar.mkdir()
    (calendar / "calendar.json").write_bytes(arguments["calendar_raw"])
    (calendar / "calendar.receipt.json").write_bytes(arguments["calendar_receipt_raw"])
    protected = base / "protected"
    source_paths = {"protected-plan.json": "trading-research/registered-plan.v2.json",
                    "protected-calendar.json": "source/calendar.raw",
                    "protected-calendar.receipt.json": "source/calendar.receipt.v1.json"}
    for name, raw in protected_fixture().items():
        target = protected / source_paths[Path(name).name]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    pilot = base / "pilot"
    protocol, evidence = protocol_fixture()
    freeze_experiment(pilot, protocol, evidence)
    args = argparse.Namespace(output_root=base / "baseline", experiment_root=pilot,
        history_root=history, backfill_manifest=manifest, calendar_root=calendar,
        protected_study_root=protected, runtime_root=base / "runtime")
    baseline_cli.build_bundle(args)
    return args


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.text = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, text):
        self.text.append(text)


class DashboardRenderingTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")))
        arguments, _ = fixture()
        self.report = calculate(arguments)["report"]

    def render(self, *, rule="0.000726206353359939", control="0.000735181424074393",
               gap="-0.000008975070714454"):
        report = deepcopy(self.report)
        report["summary"].update(mean_gross_return=rule, mean_control_gross_return=control,
                                  mean_gross_excess_over_control=gap)
        return dashboard.render_historical_dashboard(report)

    def test_small_real_gap_is_explained_without_claiming_alpha_or_pnl(self):
        html = self.render()
        text = " ".join(Markup(html).text)
        self.assertIn("No advantage over the control.", text)
        self.assertIn("0.0726%", text)
        self.assertIn("0.0735%", text)
        self.assertIn("percentage points", text)
        self.assertIn("before costs", text.lower())
        self.assertIn("auto-trading off", text.lower())
        self.assertIn("not account", text.lower())
        self.assertNotIn("statistically significant", text.lower())

    def test_chart_exposes_exact_values_uses_common_zero_and_does_not_exaggerate_gap(self):
        markup = Markup(self.render())
        rects = {attrs["data-series"]: attrs for tag, attrs in markup.elements
                 if tag == "rect" and "data-series" in attrs}
        self.assertEqual(set(rects), {"rule", "control"})
        self.assertEqual(rects["rule"]["data-value"], "0.000726206353359939")
        self.assertEqual(rects["control"]["data-value"], "0.000735181424074393")
        self.assertEqual(float(rects["rule"]["x"]), float(rects["control"]["x"]))
        ratio = float(rects["rule"]["width"]) / float(rects["control"]["width"])
        self.assertAlmostEqual(ratio, 0.000726206353359939 / 0.000735181424074393, places=3)
        self.assertTrue(any(attrs.get("aria-label") ==
            "Rule versus control: average gross price change per observation"
            for _, attrs in markup.elements))

    def test_signed_axis_places_negative_left_of_positive(self):
        rects = {attrs["data-series"]: attrs for tag, attrs in
                 Markup(self.render(rule="-0.01", control="0.02", gap="-0.03")).elements
                 if tag == "rect" and "data-series" in attrs}
        left, right = rects["rule"], rects["control"]
        self.assertGreater(float(left["width"]), 0)
        self.assertGreater(float(right["width"]), 0)
        self.assertAlmostEqual(float(left["x"]) + float(left["width"]), float(right["x"]), places=2)
        self.assertLess(float(left["x"]), float(right["x"]))

    def test_both_negative_bars_share_zero_endpoint(self):
        rects = {attrs["data-series"]: attrs for tag, attrs in
                 Markup(self.render(rule="-0.01", control="-0.02", gap="0.01")).elements
                 if tag == "rect" and "data-series" in attrs}
        endpoints = [float(attrs["x"]) + float(attrs["width"]) for attrs in rects.values()]
        self.assertAlmostEqual(*endpoints, places=2)
        self.assertIn("Ahead of control, but the rule average was not positive.",
                      self.render(rule="-0.01", control="-0.02", gap="0.01"))

    def test_exact_zero_is_tie_without_false_positive(self):
        html = self.render(rule="0", control="0", gap="0")
        self.assertIn("Rule and control tied before costs.", html)
        rects = [attrs for tag, attrs in Markup(html).elements
                 if tag == "rect" and "data-series" in attrs]
        self.assertEqual(len(rects), 2)
        self.assertTrue(all(float(row["width"]) == 0 for row in rects))
        self.assertNotIn("nan", html.lower())

    def test_positive_gross_comparison_still_does_not_claim_execution(self):
        html = self.render(rule="0.02", control="0.01", gap="0.01")
        self.assertIn("Rule ahead before costs.", html)
        text = " ".join(Markup(html).text).lower()
        self.assertIn("before costs", text)
        self.assertIn("not account", text)

    def test_missing_comparison_does_not_render_fabricated_bar(self):
        for field in ("mean_gross_return", "mean_control_gross_return"):
            with self.subTest(field=field):
                report = deepcopy(self.report)
                report["summary"][field] = None
                html = dashboard.render_historical_dashboard(report)
                self.assertIn("Comparison unavailable.", html)
                self.assertFalse(any("data-series" in attrs for _, attrs in Markup(html).elements))

    def test_missing_excess_remains_unavailable_while_preserving_known_means(self):
        report = deepcopy(self.report)
        report["summary"]["mean_gross_excess_over_control"] = None
        html = dashboard.render_historical_dashboard(report)
        self.assertIn("Comparison unavailable.", html)
        self.assertNotIn("Rule and control tied", html)
        self.assertNotIn("Rule ahead before costs.", html)

    def test_tiny_nonzero_gap_is_not_mislabeled_tie_or_zero(self):
        html = self.render(rule="0.0000000000001", control="0.0000000000002",
                           gap="-0.0000000000001")
        self.assertIn("No advantage over the control.", html)
        self.assertNotIn("Rule and control tied", html)
        text = " ".join(Markup(html).text)
        self.assertTrue("E-" in text or "e-" in text, "tiny nonzero gap must remain visible")

    def test_tiny_positive_gap_is_not_rounded_into_tie(self):
        html = self.render(rule="0.0000000000002", control="0.0000000000001",
                           gap="0.0000000000001")
        self.assertIn("Rule ahead before costs.", html)
        self.assertNotIn("Rule and control tied", html)

    def test_nonfinite_values_are_rejected_without_rendering_invalid_chart(self):
        for field in ("mean_gross_return", "mean_control_gross_return", "mean_gross_excess_over_control"):
            for value in ("NaN", "Infinity", "-Infinity"):
                with self.subTest(field=field, value=value):
                    report = deepcopy(self.report)
                    report["summary"][field] = value
                    with self.assertRaises(ValueError):
                        dashboard.render_historical_dashboard(report)

    def test_coverage_is_from_retained_report_and_forward_text_does_not_stale(self):
        html = dashboard.render_historical_dashboard(self.report)
        for row in self.report["source_coverage"]:
            for field in ("source_first_date", "source_last_date"):
                self.assertIn(row[field], html)
        self.assertNotIn("Its empty checks", html)
        text = " ".join(Markup(html).text).lower()
        self.assertIn("research record: auto-trading off", text)
        self.assertIn("no execution controls", text)

    def test_source_text_is_escaped_and_links_remain_static_local_paths(self):
        report = deepcopy(self.report)
        report["report_id"] = '<script>alert("unsafe")</script>'
        report["first_signal_session"] = '\"><img src=x onerror=alert(1)>'
        html = dashboard.render_historical_dashboard(report)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;", html)
        links = [attrs["href"] for tag, attrs in Markup(html).elements if tag == "a"]
        self.assertTrue({"report.html", "report.json", "rows.csv"}.issubset(links))
        self.assertTrue(all(link in {"report.html", "report.json", "rows.csv", "cohorts.json",
            "bundle-manifest.json", "dashboard-manifest.json", "http://127.0.0.1:5181/?view=research"}
            for link in links))

    def test_rendering_is_deterministic_and_preserves_input(self):
        before = canonical_json_bytes(self.report)
        one = dashboard.render_historical_dashboard(self.report)
        self.assertEqual(one, dashboard.render_historical_dashboard(self.report))
        self.assertEqual(before, canonical_json_bytes(self.report))
        self.assertFalse(any(tag in {"script", "form", "button", "input"}
                             for tag, _ in Markup(one).elements))


class DashboardExportTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.args = historical_bundle(self.base)
        self.root = self.args.output_root
        self.output = self.base / "dashboard"

    def test_verified_export_copies_original_material_without_mutating_source_or_pilot(self):
        before = snapshot(self.root)
        pilot_before = snapshot(self.args.experiment_root)
        dashboard.export_dashboard(self.root, self.output)
        self.assertEqual(before, snapshot(self.root))
        self.assertEqual(pilot_before, snapshot(self.args.experiment_root))
        self.assertFalse(self.args.runtime_root.exists())
        self.assertTrue(baseline_cli.verify_bundle(self.output)["valid"])
        bundle = json.loads((self.root / "bundle-manifest.json").read_bytes())
        for path in [row["path"] for row in bundle["files"]] + ["bundle-manifest.json"]:
            self.assertEqual((self.root / path).read_bytes(), (self.output / path).read_bytes(), path)
        for name in ("dashboard.html", "dashboard-source.py", "dashboard-manifest.json"):
            self.assertTrue((self.output / name).is_file(), name)

    def test_retry_is_deterministic_and_idempotent(self):
        dashboard.export_dashboard(self.root, self.output)
        before = snapshot(self.output)
        dashboard.export_dashboard(self.root, self.output)
        self.assertEqual(before, snapshot(self.output))

    def test_invalid_source_is_rejected_before_any_output_publication(self):
        path = self.root / "rows.json"
        path.chmod(0o600)
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises((ValueError, JournalStoreError)):
            dashboard.export_dashboard(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_output_conflict_does_not_replace_original_files(self):
        dashboard.export_dashboard(self.root, self.output)
        path = self.output / "dashboard.html"
        path.chmod(0o600)
        path.write_bytes(b"existing conflicting report")
        source_before = snapshot(self.root)
        with self.assertRaises((ValueError, RuntimeError, JournalStoreError)):
            dashboard.export_dashboard(self.root, self.output)
        self.assertEqual(path.read_bytes(), b"existing conflicting report")
        self.assertEqual(source_before, snapshot(self.root))

    def test_copied_evidence_conflict_does_not_get_overwritten(self):
        dashboard.export_dashboard(self.root, self.output)
        path = self.output / "sources" / "QQQ.csv"
        path.chmod(0o600)
        path.write_bytes(b"conflict")
        with self.assertRaises((ValueError, RuntimeError, JournalStoreError)):
            dashboard.export_dashboard(self.root, self.output)
        self.assertEqual(path.read_bytes(), b"conflict")

    def test_source_journal_runtime_and_repository_destinations_are_rejected(self):
        for target in (self.root, self.root / "dashboard", self.root.parent,
                       self.args.experiment_root / "dashboard", self.base / "src" / "dashboard"):
            with self.subTest(target=target):
                before = snapshot(self.root)
                with self.assertRaises((ValueError, JournalStoreError)):
                    dashboard.export_dashboard(self.root, target)
                self.assertEqual(before, snapshot(self.root))

    def test_symlinked_output_rejected(self):
        self.output.symlink_to(self.root, target_is_directory=True)
        before = snapshot(self.root)
        with self.assertRaises((ValueError, JournalStoreError)):
            dashboard.export_dashboard(self.root, self.output)
        self.assertEqual(before, snapshot(self.root))

    def test_interrupted_export_retries_without_rewriting_evidence(self):
        actual_write = dashboard._write
        def interrupted(path, raw, sources):
            if Path(path).name == "dashboard.html":
                raise OSError("authored interruption")
            return actual_write(path, raw, sources)
        source_before = snapshot(self.root)
        with patch.object(dashboard, "_write", side_effect=interrupted):
            with self.assertRaises(OSError):
                dashboard.export_dashboard(self.root, self.output)
        self.assertFalse((self.output / "dashboard-manifest.json").exists())
        dashboard.export_dashboard(self.root, self.output)
        self.assertTrue(baseline_cli.verify_bundle(self.output)["valid"])
        self.assertEqual(source_before, snapshot(self.root))

    def test_cli_export_is_explicit_offline_and_json_readable(self):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = dashboard.main(["export", "--baseline-root", str(self.root),
                                   "--output-root", str(self.output)])
        self.assertEqual(code, 0, err.getvalue())
        result = json.loads(out.getvalue())
        self.assertEqual(result["provider_calls"], 0)
        self.assertFalse(result["auto_trading_changed"])
        self.assertTrue((self.output / "dashboard.html").is_file())


if __name__ == "__main__":
    unittest.main()
