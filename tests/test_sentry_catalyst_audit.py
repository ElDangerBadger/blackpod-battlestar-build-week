"""Offline feed audit: no providers, agents, orders or source-evidence writes."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import sentry_catalyst_audit as audit
from blackpod_build_week import sentry_catalyst as core
from blackpod_build_week import shadow_station
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from test_sentry_catalyst import NOW, WATCH, packet
from test_shadow_station import _LocalHTTPMixin


def changed_packet(at=NOW, selected=WATCH, change=None):
    _, blobs = packet(at=at)
    news, snapshots = json.loads(blobs['news']), json.loads(blobs['snapshots'])
    snapshots = {k:v for k,v in snapshots.items() if k in selected}
    if change:
        change(news,snapshots)
    for kind, value in [('news',news),('snapshots',snapshots)]:
        blobs[kind] = canonical_json_bytes(value)
        receipt = json.loads(blobs[kind+'_receipt'])
        receipt['query']['symbols'] = ','.join(selected)
        receipt.update(body_sha256=sha256_bytes(blobs[kind]),size_bytes=len(blobs[kind]))
        blobs[kind+'_receipt'] = canonical_json_bytes(receipt)
    return core.project(blobs['news'],blobs['snapshots'],selected,core.stamp(at)),blobs


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name).resolve()
        self.store=core.CatalystStore(self.base/'station/catalyst/evidence-store')
        self.config={key:str(self.base/key) for key in ('repo_root','runtime_root','experiment_root','historical_root','ui_root')}
        self.config['station_root']=str(self.base/'station')
        self.config['credentials_file']=str(self.base/'private/keys.yaml')

    def report(self,as_of=NOW):
        records,proof=self.store.verified_records()
        return audit.build_report(records,proof,as_of)

    def test_startup_baseline_excluded_from_later_discovery(self):
        self.store.append(*packet())
        report=self.report()
        self.assertEqual(report['news']['initial_or_watchlist_baseline_article_count'],1)
        self.assertEqual(report['news']['later_discovery_article_count'],0)
        self.assertIsNone(report['news']['later_publication_to_first_seen']['p50_ms'])
        self.assertEqual(report['news']['baseline_publication_to_first_seen']['p50_ms'],3600000)
        self.assertEqual(report['authority'],'OBSERVATION_ONLY')

    def test_later_discovery_once_per_article_not_every_repeat_or_revision(self):
        self.store.append(*packet())
        later=NOW+timedelta(minutes=5)
        def story(news,snaps):
            news['news'][0].update(id=456,created_at=core.stamp(later-timedelta(seconds=90)),updated_at=core.stamp(later-timedelta(seconds=30)))
        second,blobs=changed_packet(later,change=story)
        self.store.append(second,blobs)
        # Same article/version returned in a subsequent complete capture.
        third=core.project(blobs['news'],blobs['snapshots'],WATCH,core.stamp(later+timedelta(minutes=5)))
        self.store.append(third,blobs)
        report=self.report(later+timedelta(minutes=5))
        self.assertEqual(report['news']['later_discovery_article_count'],1)
        self.assertEqual(report['news']['later_publication_to_first_seen']['p50_ms'],90000)
        self.assertEqual(report['news']['observed_version_count'],2)
        self.assertEqual(report['news']['repeated_observation_count'],1)
        self.assertEqual(report['news']['version_update_to_first_seen']['min_ms'],30000)

    def test_percentiles_empty_sample_and_negative_clock_exclusions(self):
        self.assertEqual(audit.distribution([1000,2000,3000,4000,5000,-1]),
            {'count':5,'excluded_negative_count':1,'min_ms':1000,'p50_ms':3000,'p95_ms':5000,'max_ms':5000})
        self.assertIsNone(audit.distribution([])['p95_ms'])
        self.assertEqual(audit.distribution([0])['p50_ms'],0)

    def test_prices_partition_known_capture_denominator_not_global_market_coverage(self):
        def change(news,snaps):
            snaps['SPY']['minuteBar']['t']=core.stamp(NOW-timedelta(hours=1))
            del snaps['QQQ']
            news['next_page_token']='more'
        self.store.append(*changed_packet(change=change))
        report=self.report()
        prices=report['prices']
        self.assertEqual(prices['symbol_capture_pairs'],2)
        self.assertEqual(prices['fresh_at_capture_count'],0)
        self.assertEqual(prices['stale_at_capture_count'],1)
        self.assertEqual(prices['unavailable_count'],1)
        self.assertEqual(report['news']['truncated_capture_count'],1)
        self.assertIsNone(report['news']['overall_news_coverage_fraction'])
        self.assertIsNone(report['news']['missed_article_count'])

    def test_audit_age_does_not_reclassify_original_capture_freshness(self):
        self.store.append(*packet())
        report=self.report(NOW+timedelta(hours=2))
        self.assertEqual(report['prices']['fresh_at_capture_count'],2)
        self.assertTrue(all(r['latest_bar_status_at_audit']=='STALE' for r in report['prices']['symbols']))

    def test_watchlist_changes_create_baseline_cohort_and_correct_denominators(self):
        self.store.append(*packet())
        def story(news,snaps):news['news'][0]['id']=456
        self.store.append(*changed_packet(NOW+timedelta(minutes=5),selected=['SPY'],change=story))
        report=self.report(NOW+timedelta(minutes=5))
        self.assertEqual(report['window']['watchlist_change_count'],1)
        self.assertEqual(report['news']['initial_or_watchlist_baseline_article_count'],2)
        self.assertEqual(report['news']['later_discovery_article_count'],0)
        self.assertEqual({r['symbol']:r['requested_capture_count'] for r in report['prices']['symbols']},{'QQQ':1,'SPY':2})

    def test_watchlist_reordering_is_not_a_new_cohort(self):
        self.store.append(*packet())
        self.store.append(*changed_packet(NOW+timedelta(minutes=5),selected=list(reversed(WATCH))))
        self.assertEqual(self.report(NOW+timedelta(minutes=5))['window']['watchlist_change_count'],0)

    def test_weekend_and_night_are_not_counted_as_missing_monitoring_slots(self):
        start=datetime.fromisoformat('2026-10-16T16:57:00-07:00')
        end=datetime.fromisoformat('2026-10-19T05:03:00-07:00')
        self.store.append(*changed_packet(start))
        self.store.append(*changed_packet(end-timedelta(minutes=1)))
        report=self.report(end)
        self.assertEqual(report['collection']['nominal_completed_slots'],1)
        self.assertEqual(report['collection']['slots_without_complete_capture'],0)
        self.assertEqual(report['collection']['inter_capture_gaps_over_ten_minutes'],1)
        self.assertIsNone(report['collection']['historical_failed_attempt_count'])

    def test_empty_nominal_slots_do_not_become_invented_failure_counts(self):
        self.store.append(*packet())
        report=self.report(NOW+timedelta(minutes=16))
        self.assertEqual(report['collection']['nominal_completed_slots'],3)
        self.assertEqual(report['collection']['slots_with_complete_capture'],1)
        self.assertEqual(report['collection']['slots_without_complete_capture'],2)
        self.assertIsNone(report['collection']['http_request_latency'])

    def test_dst_uses_local_monitoring_hours_and_excludes_open_slot(self):
        start=datetime.fromisoformat('2026-11-02T05:01:00-08:00')
        self.assertEqual(len(audit._monitoring_slots(start,start+timedelta(minutes=4))),1)
        self.assertEqual(len(audit._monitoring_slots(start,start+timedelta(minutes=3))),0)

    def test_small_future_provider_clocks_are_flagged_not_clamped_or_fresh(self):
        def change(news,snaps):
            news['news'][0].update(created_at=core.stamp(NOW+timedelta(seconds=2)),updated_at=core.stamp(NOW+timedelta(seconds=2)))
            snaps['SPY']['minuteBar']['t']=core.stamp(NOW+timedelta(seconds=2))
        self.store.append(*changed_packet(change=change))
        report=self.report()
        self.assertEqual(report['news']['baseline_publication_to_first_seen']['excluded_negative_count'],1)
        self.assertEqual(report['prices']['future_timestamp_count'],1)
        self.assertEqual(report['prices']['fresh_at_capture_count'],1)

    def test_report_deterministic_for_same_prefix_clock_and_no_source_writes(self):
        self.store.append(*packet())
        before={str(p.relative_to(self.store.root)):p.read_bytes() for p in self.store.root.rglob('*') if p.is_file()}
        first,second=self.report(),self.report()
        self.assertEqual(first,second)
        expected=deepcopy(first);identity=expected.pop('report_id')
        self.assertEqual(identity,'sentry-audit-'+sha256_bytes(canonical_json_bytes(expected)))
        after={str(p.relative_to(self.store.root)):p.read_bytes() for p in self.store.root.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_partial_transport_does_not_manufacture_complete_capture(self):
        _,blobs=packet()
        self.store.retain_transport(blobs['news'],blobs['news_receipt'])
        report=self.report()
        self.assertEqual(report['source']['capture_count'],0)
        self.assertEqual(report['source']['orphan_evidence_count'],2)
        self.assertEqual(report['news']['unique_article_count'],0)
        self.assertEqual(report['assessment'],'NO_VERIFIED_CAPTURES')

    def test_source_count_clock_and_naive_clock_refused(self):
        self.store.append(*packet())
        records,proof=self.store.verified_records()
        for at,receipt in [(NOW-timedelta(seconds=1),proof),(NOW.replace(tzinfo=None),proof),(NOW,{**proof,'capture_count':2})]:
            with self.subTest(at=at),self.assertRaises(ValueError):audit.build_report(records,receipt,at)

    def test_audit_uses_no_provider_credentials_or_collector(self):
        self.store.append(*packet())
        with patch('blackpod_build_week.shadow_station_collection._off') as off, patch('blackpod_build_week.sentry_catalyst_service.parse_credentials',side_effect=AssertionError('forbidden')),patch('blackpod_build_week.sentry_catalyst_service.market_get',side_effect=AssertionError('forbidden')),patch('blackpod_build_week.sentry_catalyst_service.cycle',side_effect=AssertionError('forbidden')):
            result=audit.audit(self.config,NOW)
            self.assertEqual(result['source']['capture_count'],1)
            self.assertEqual(off.call_count,2)

    def test_corrupt_evidence_or_on_gate_yields_no_cached_audit(self):
        self.store.append(*packet())
        with patch('blackpod_build_week.shadow_station_collection._off',side_effect=ValueError('private-secret')):
            self.assertEqual(audit.audit_status(self.config),{'status':'UNAVAILABLE','report':None})
        path=next((self.store.root/'evidence').iterdir());path.chmod(0o600);path.write_bytes(b'{}')
        with patch('blackpod_build_week.shadow_station_collection._off'):
            self.assertEqual(audit.audit_status(self.config),{'status':'UNAVAILABLE','report':None})

    def test_export_is_idempotent_conflicts_block_and_manifest_binds_files(self):
        self.store.append(*packet());report=self.report();root=self.base/'repo_root/output/audit'
        first=audit.export_report(report,root,self.config)
        self.assertEqual(audit.export_report(report,root,self.config),first)
        manifest=json.loads((root/'manifest.json').read_bytes())
        for name,ref in manifest['files'].items():self.assertEqual(sha256_bytes((root/name).read_bytes()),ref['sha256'])
        self.assertNotIn(b'http-equiv="refresh"',(root/'report.html').read_bytes())
        with self.assertRaises(ValueError):audit.export_report(self.report(NOW+timedelta(seconds=1)),root,self.config)
        self.assertEqual(json.loads((root/'report.json').read_bytes())['report_id'],report['report_id'])

    def test_export_replays_original_prefix_after_later_captures(self):
        self.store.append(*packet());report=self.report();root=self.base/'repo_root/output/audit'
        audit.export_report(report,root,self.config)
        self.store.append(*packet(at=NOW+timedelta(minutes=5)))
        with patch('blackpod_build_week.shadow_station_collection._off'):
            result=audit.verify_export(root,self.config)
        self.assertEqual(result['source_capture_count'],1)
        self.assertTrue(result['verified'])
        self.assertEqual(result['provider_calls'],0)
        html=root/'report.html';html.chmod(0o600);html.write_bytes(b'changed')
        with patch('blackpod_build_week.shadow_station_collection._off'),self.assertRaises(ValueError):audit.verify_export(root,self.config)

    def test_export_forbids_source_overlap_symlinks_and_unrelated_files(self):
        self.store.append(*packet());report=self.report()
        for root in [self.store.root,self.base/'repo_root',self.base/'outside']:
            with self.subTest(root=root),self.assertRaises(ValueError):audit.export_report(report,root,self.config)
        root=self.base/'repo_root/output/link';root.parent.mkdir(parents=True)
        root.symlink_to(self.base,target_is_directory=True)
        with self.assertRaises(RuntimeError):audit.export_report(report,root,self.config)
        root.unlink();root.mkdir();(root/'unrelated').write_text('keep')
        with self.assertRaises(ValueError):audit.export_report(report,root,self.config)
        self.assertEqual((root/'unrelated').read_text(),'keep')

    def test_interrupted_export_keeps_complete_files_and_retry_recovers(self):
        self.store.append(*packet());report=self.report();root=self.base/'repo_root/output/audit'
        from blackpod_build_week import decision_journal_store as publisher
        real=publisher._publish_immutable
        def interrupted(staging,target,name,raw):
            if name=='manifest.json':raise OSError('fixture interruption')
            return real(staging,target,name,raw)
        with patch.object(publisher,'_publish_immutable',side_effect=interrupted),self.assertRaises(OSError):audit.export_report(report,root,self.config)
        original=(root/'report.json').read_bytes()
        self.assertFalse((root/'manifest.json').exists())
        audit.export_report(report,root,self.config)
        self.assertEqual((root/'report.json').read_bytes(),original)
        self.assertTrue((root/'manifest.json').exists())


class AuditHTTPTests(_LocalHTTPMixin,unittest.TestCase):
    def setUp(self):
        self.value={'status':'UNAVAILABLE','report':None}
        self.start(shadow_station.LocalStatusServer(('127.0.0.1',0),lambda:{},bind_and_activate=False,catalyst_audit_supplier=lambda:self.value))

    def test_read_only_routes_and_no_implicit_collection(self):
        with patch('blackpod_build_week.sentry_catalyst_service.market_get',side_effect=AssertionError('forbidden')):
            self.assertEqual(self.request('/sentry-audit')[0],200)
            self.assertEqual(json.loads(self.request('/sentry-audit.json')[2]),self.value)
        self.assertEqual(self.request('/sentry-audit','HEAD')[2],b'')
        self.assertEqual(self.request('/sentry-audit','POST')[0],405)
        self.assertEqual(self.request('/sentry-audit?collect=true')[0],404)
        self.assertEqual(self.request('/sentry-audit',headers={'Origin':'https://evil.example'})[0],403)

    def test_unavailable_and_rendered_source_text_are_escaped(self):
        self.assertIn('Audit unavailable',audit.render(self.value))
        report=audit.build_report([],{'capture_count':0,'head_sha256':None,'evidence_count':0,'orphan_evidence_count':0,'staging_orphan_count':0},NOW)
        report['source']['head_sha256']='<script>bad</script>'
        html=audit.render({'status':'VERIFIED','report':report})
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertIn('Overall headline coverage',html)
        self.assertIn('Unknown',html)
