"""Authored full-watchlist economic responses; no provider or market calls."""
from copy import deepcopy
from itertools import combinations
import json
import unittest

from blackpod_build_week.contracts import sentry_synthesis as contracts
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.sentry_economic_reasoning import (
    ARRAY_ORACLE_VERSION, ORACLE_VERSION, economic_schema, validate_economic,
)
from test_sentry_economic_reasoning import economic_draft
from test_sentry_synthesis_contracts import challenge, draft, packet


WATCHLIST = ['SPY', 'QQQ', 'NVDA', 'AMZN', 'LULU', 'NKE', 'DG', 'PG', 'CLX', 'GOOGL']


def full_packet():
    value = packet()
    value['watchlist'] = list(WATCHLIST)
    value['evidence'][0]['symbols'] = list(WATCHLIST)
    return value


def array_draft(source=None, *, symbols=None, candidate=True):
    """Explicit fixture authoring, never a live response conversion or repair."""
    source = full_packet() if source is None else source
    selected = source['watchlist'] if symbols is None else list(symbols)
    value = economic_draft(source, candidate=candidate)
    value['schema_version'] = ARRAY_ORACLE_VERSION
    theme = value['themes'][0]
    row = next(iter(theme.pop('implications_by_symbol').values()))
    theme['implications'] = [{'symbol': symbol, **deepcopy(row)} for symbol in selected]
    if not candidate:
        value['economic_analyses'][0]['hypothesis'].update(
            direction='UNDETERMINED', horizon_days=0,
            validation_conditions=[], invalidation_conditions=[])
        value['economic_analyses'][0]['materiality']['assessment'] = 'UNKNOWN'
    return value


class CodexEconomicContractTests(unittest.TestCase):
    def setUp(self):
        self.packet = full_packet()
        self.original = array_draft(self.packet)

    def validate(self, value=None):
        return contracts.validate_response('oracle', self.original if value is None else value, self.packet)

    def test_all_ten_symbols_remain_original_array_with_economic_fields(self):
        before = deepcopy((self.packet, self.original))
        result = self.validate()
        self.assertEqual(result, self.original)
        self.assertEqual(result['schema_version'], ARRAY_ORACLE_VERSION)
        self.assertEqual([r['symbol'] for r in result['themes'][0]['implications']], WATCHLIST)
        self.assertNotIn('implications_by_symbol', result['themes'][0])
        self.assertEqual((self.packet, self.original), before)

    def test_every_nonempty_watchlist_subset_is_valid_without_filling_omissions(self):
        checked = 0
        for size in range(1, len(WATCHLIST) + 1):
            for selected in combinations(WATCHLIST, size):
                value = array_draft(self.packet, symbols=selected)
                with self.subTest(symbols=selected):
                    self.assertEqual(self.validate(value), value)
                    checked += 1
        self.assertEqual(checked, 1023)

    def test_array_order_is_preserved_without_sorting_or_canonical_map_projection(self):
        value = deepcopy(self.original)
        value['themes'][0]['implications'].reverse()
        self.assertEqual(self.validate(value), value)

    def test_returned_response_is_detached(self):
        value = self.validate()
        value['themes'][0]['implications'][0]['trading'] = 'Changed only in caller.'
        value['economic_analyses'][0]['hypothesis']['uncertainties'].append('Caller edit.')
        self.assertEqual(self.original, array_draft(self.packet))

    def test_duplicate_symbols_are_rejected_instead_of_deduplicated(self):
        value = array_draft(self.packet, symbols=['SPY', 'SPY'])
        with self.assertRaisesRegex(ValueError, 'duplicate implication symbol'):
            self.validate(value)

    def test_unknown_or_unnormalized_symbols_are_rejected(self):
        for symbol in ('CRWV', 'spy', ' SPY', '', None, True):
            value = array_draft(self.packet, symbols=[symbol])
            with self.subTest(symbol=symbol), self.assertRaises(ValueError):
                self.validate(value)

    def test_empty_and_oversized_implication_arrays_are_rejected(self):
        for symbols in ([], WATCHLIST + ['SPY']):
            with self.subTest(symbols=symbols), self.assertRaises(ValueError):
                self.validate(array_draft(self.packet, symbols=symbols))

    def test_extra_fields_cannot_create_authority(self):
        targets = (
            lambda d: d,
            lambda d: d['themes'][0],
            lambda d: d['themes'][0]['implications'][0],
            lambda d: d['economic_analyses'][0],
            lambda d: d['economic_analyses'][0]['hypothesis'],
        )
        for index, target in enumerate(targets):
            value = deepcopy(self.original)
            target(value)['execution_enabled'] = True
            with self.subTest(scope=index), self.assertRaises(ValueError):
                self.validate(value)

    def test_keyed_map_is_not_repaired_into_an_array(self):
        value = deepcopy(self.original)
        rows = value['themes'][0].pop('implications')
        value['themes'][0]['implications_by_symbol'] = {
            r['symbol']: {k: v for k, v in r.items() if k != 'symbol'} for r in rows}
        with self.assertRaises(ValueError):
            self.validate(value)

    def test_source_bound_direct_mentions_still_require_a_cited_headline(self):
        value = deepcopy(self.original)
        value['themes'][0]['evidence_ids'] = ['price-1']
        with self.assertRaisesRegex(ValueError, 'DIRECT_MENTION requires cited headline'):
            self.validate(value)

    def test_unknown_duplicate_and_empty_citations_are_rejected(self):
        for citations in (['unknown'], ['headline-1', 'headline-1'], []):
            value = deepcopy(self.original)
            value['themes'][0]['evidence_ids'] = citations
            with self.subTest(citations=citations), self.assertRaises(ValueError):
                self.validate(value)
        for field in ('catalyst_evidence_ids', 'supporting_evidence_ids', 'contradictory_evidence_ids'):
            value = deepcopy(self.original)
            target = value['economic_analyses'][0]
            if field != 'catalyst_evidence_ids':
                target = target['hypothesis']
            target[field] = ['headline-1', 'headline-1']
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(value)

    def test_economic_structure_and_analysis_theme_binding_remain_enforced(self):
        mutations = (
            lambda d: d['economic_analyses'][0]['hypothesis'].update(horizon_days=True),
            lambda d: d['economic_analyses'][0]['hypothesis'].update(horizon_days=366),
            lambda d: d['economic_analyses'][0]['event'].update(evidence_id='unknown'),
            lambda d: d['economic_analyses'][0].update(theme_id='theme-3'),
            lambda d: d['economic_analyses'].append(deepcopy(d['economic_analyses'][0])),
            lambda d: d['economic_analyses'][0]['hypothesis'].update(confidence=0.9),
        )
        for index, mutate in enumerate(mutations):
            value = deepcopy(self.original)
            mutate(value)
            with self.subTest(mutation=index), self.assertRaises(ValueError):
                self.validate(value)

    def test_honest_no_hypothesis_preserves_zero_horizon_and_empty_conditions(self):
        value = array_draft(self.packet, symbols=['SPY'], candidate=False)
        self.assertEqual(self.validate(value), value)
        hypothesis = value['economic_analyses'][0]['hypothesis']
        self.assertEqual(hypothesis['horizon_days'], 0)
        self.assertEqual(hypothesis['direction'], 'UNDETERMINED')
        self.assertEqual(hypothesis['validation_conditions'], [])
        self.assertEqual(hypothesis['invalidation_conditions'], [])

    def test_missing_analysis_or_descriptive_theme_is_not_fabricated(self):
        for field in ('themes', 'economic_analyses'):
            value = deepcopy(self.original)
            value[field] = []
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(value)

    def test_response_bytes_keep_exact_original_version_and_reject_ambiguous_json(self):
        raw = canonical_json_bytes(self.original)
        self.assertEqual(self.validate(raw), self.original)
        self.assertEqual(self.validate(raw.decode()), self.original)
        duplicate = raw.replace(b'"symbol": "SPY"', b'"symbol": "SPY", "symbol": "SPY"', 1)
        self.assertNotEqual(duplicate, raw)
        for invalid in (duplicate, b'```json\n' + raw + b'\n```', raw + raw):
            with self.subTest(raw=invalid[:25]), self.assertRaises(ValueError):
                self.validate(invalid)

    def test_challenge_binds_exact_original_v5_draft_and_retains_dissent(self):
        review = challenge(self.original)
        before = deepcopy((self.original, review))
        for original in (self.original, canonical_json_bytes(self.original)):
            result = contracts.validate_response('challenge', review, self.packet, original)
            self.assertEqual(result, review)
            self.assertEqual(result['reviews'][0]['status'], 'UNTESTED')
        schema = contracts.response_schema('challenge', self.packet, self.original, version='v5')
        self.assertEqual(schema['properties']['draft_sha256']['const'], sha256_bytes(canonical_json_bytes(self.original)))
        self.assertEqual((self.original, review), before)

    def test_challenge_never_hashes_a_v4_conversion_or_reordered_array(self):
        review = challenge(self.original)
        for original in (economic_draft(self.packet), deepcopy(self.original)):
            if original['schema_version'] == ARRAY_ORACLE_VERSION:
                original['themes'][0]['implications'].reverse()
            with self.subTest(version=original['schema_version']), self.assertRaisesRegex(ValueError, 'draft_sha256'):
                contracts.validate_response('challenge', review, self.packet, original)

    def test_empty_draft_challenge_does_not_bypass_economic_analysis_requirements(self):
        empty = deepcopy(self.original)
        empty['themes'] = []
        empty['economic_analyses'] = []
        with self.assertRaises(ValueError):
            contracts.response_schema('challenge', self.packet, empty, version='v5')
        with self.assertRaises(ValueError):
            contracts.validate_response('challenge', challenge(empty), self.packet, empty)
        # The existing valid empty legacy draft remains a zero-review challenge.
        legacy = draft()
        legacy['themes'] = []
        legacy_review = challenge(legacy)
        self.assertEqual(contracts.validate_response('challenge', legacy_review, self.packet, legacy), legacy_review)

    def test_strict_schema_uses_only_modeldock_supported_keywords_and_required_properties(self):
        schema = contracts.response_schema('oracle', self.packet, version='v5')
        supported = {
            'object': {'properties', 'required', 'additionalProperties'},
            'array': {'items', 'minItems', 'maxItems'},
            'string': {'minLength', 'maxLength'},
            'integer': {'minimum', 'maximum'},
        }
        def inspect(rule):
            self.assertLessEqual(set(rule), {'type', 'enum', 'const'} | supported[rule['type']])
            if rule['type'] == 'object':
                self.assertEqual(set(rule['properties']), set(rule['required']))
                self.assertIs(rule['additionalProperties'], False)
                for child in rule['properties'].values():
                    inspect(child)
            elif rule['type'] == 'array':
                inspect(rule['items'])
        inspect(schema)
        self.assertLess(len(json.dumps(schema, ensure_ascii=False).encode()), 65536)
        implications = schema['properties']['themes']['items']['properties']['implications']
        self.assertEqual(implications['items']['properties']['symbol']['enum'], WATCHLIST)
        self.assertEqual(implications['minItems'], 1)
        self.assertEqual(implications['maxItems'], 10)
        self.assertEqual(schema['properties']['schema_version']['const'], ARRAY_ORACLE_VERSION)

    def test_v4_keyed_schema_and_original_draft_remain_unchanged(self):
        keyed = economic_draft(self.packet)
        before = deepcopy(keyed)
        self.assertEqual(contracts.validate_response('oracle', keyed, self.packet), keyed)
        expected = economic_schema(self.packet, contracts.response_schema('oracle', self.packet, version='v3'))
        self.assertEqual(contracts.response_schema('oracle', self.packet, version='v4'), expected)
        self.assertEqual(keyed, before)
        self.assertEqual(keyed['schema_version'], ORACLE_VERSION)
        self.assertEqual(expected['properties']['themes']['items']['properties']['implications_by_symbol']['required'], [])

    def test_version_mismatch_is_rejected_without_output_relabeling(self):
        for version in (ORACLE_VERSION, 'blackpod.sentry_oracle_draft.v2', 'future'):
            value = deepcopy(self.original)
            value['schema_version'] = version
            with self.subTest(version=version), self.assertRaises(ValueError):
                self.validate(value)
        with self.assertRaises(ValueError):
            economic_schema(self.packet, {}, version='future')
        with self.assertRaises(ValueError):
            validate_economic({**self.original, 'schema_version': 'future'}, self.packet)


if __name__ == '__main__':
    unittest.main()
