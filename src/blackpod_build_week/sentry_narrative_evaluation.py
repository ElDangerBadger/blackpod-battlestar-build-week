"""Offline, immutable narrative-quality evaluations of original Sentry reports.

Mechanical observations and explicitly attributed assistant adjudications are
kept separate. Neither is a truth oracle, a trading gate, or a new model call.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import unicodedata

from .contracts.mission_request import parse_strict_json_object_bytes
from .contracts.sentry_synthesis import implication_items
from .decision_journal_store import (JournalStoreError, _absolute_path, _open_root,
    _open_child_directory, _publish_immutable, _read_regular, check_separate_root)
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_catalyst import clock
from .sentry_history_cache import read_regular
from .sentry_synthesis import AUTHORITY, compose_report
from .sentry_synthesis_transport import _read
from .shadow_station import service_lock
from .shadow_station_collection import _off, _pinned_view

VERSION = 'blackpod.sentry_narrative_evaluation.v1'
REVIEW_VERSION = 'blackpod.sentry_narrative_review.v1'
RUBRIC_VERSION = 'blackpod.sentry_narrative_rubric.v1'
RUBRIC_IDS = ('evidence_support', 'economic_mechanism', 'alternatives', 'challenge',
              'missing_evidence', 'boundaries', 'clarity')
ASSESSMENTS = frozenset({'MEETS_RUBRIC', 'PARTIAL', 'NEEDS_WORK', 'NOT_ASSESSED'})
SUPPORT = frozenset({'SUPPORTED_AS_REPORTED', 'PARTIALLY_SUPPORTED', 'UNDER_SUPPORTED', 'NOT_ASSESSABLE'})
RUBRIC = {
    'schema_version': RUBRIC_VERSION,
    'criteria': [
        {'criterion_id': key, 'question': question} for key, question in zip(RUBRIC_IDS, (
            'Do selected citations support the specific reported claim, with uncited packet context distinguished?',
            'Is the event-to-symbol economic connection explained with exposure and materiality unknowns retained?',
            'Is there a substantive competing explanation and evidence that could distinguish it?',
            'Does the challenge test a specific inference and preserve meaningful dissent?',
            'Are genuinely unavailable observations identified rather than available evidence mislabeled as missing?',
            'Are source, freshness, coverage, holdings, uncertainty and authority boundaries preserved?',
            'Is the reasoning clear, specific and free of unnecessary repetition?'))],
    'claim_scope': 'NON_UNSPECIFIED_SYMBOL_TRADING_AND_INVESTMENT_IMPLICATIONS',
    'method': 'ASSISTANT_ADJUDICATION',
    'meaning': 'Descriptive review of retained headlines; not factual truth, an edge, calibrated confidence or authority.',
}
RUBRIC_SHA256 = sha256_bytes(canonical_json_bytes(RUBRIC))
ECONOMIC_REVIEW_VERSION = 'blackpod.sentry_narrative_review.v2'
ECONOMIC_RUBRIC_VERSION = 'blackpod.sentry_narrative_rubric.v2'
ECONOMIC_RUBRIC = {**deepcopy(RUBRIC), 'schema_version':ECONOMIC_RUBRIC_VERSION,
    'claim_scope':'SYMBOL_IMPLICATIONS_AND_STRUCTURED_ECONOMIC_ANALYSES',
    'meaning':'Source-bound review of supplied provider headlines and available content, including linkage, materiality and test conditions; not authenticated truth, investment approval or authority.'}
ECONOMIC_RUBRIC_SHA256 = sha256_bytes(canonical_json_bytes(ECONOMIC_RUBRIC))

def _economic_report(report):
    return report.get('draft',{}).get('schema_version') in {'blackpod.sentry_oracle_draft.v4', 'blackpod.sentry_oracle_draft.v5'}

LIMITATIONS = [
    'MECHANICAL_PATTERNS_ARE_NOT_SEMANTIC_TRUTH_OR_FALSEHOOD',
    'ASSISTANT_ADJUDICATION_NOT_INDEPENDENT_HUMAN_OR_SOURCE_CORROBORATION',
    'CLAIM_SCOPE_IS_SPECIFIED_SYMBOL_IMPLICATIONS_NOT_ALL_PROSE_OR_MARKET_TRUTH',
    'HEADLINE_PACKET_ONLY_NO_LATER_ARTICLE_BODIES_OR_MARKET_OUTCOMES',
    'LATER_USER_CONTEXT_IS_NOT_ORIGINAL_MODEL_INPUT_OR_TRUTH_LABEL',
    'UNSPECIFIED_HORIZONS_AND_INVALIDATIONS_ARE_NOT_INVENTED_OR_FAILED',
    'NO_NUMERIC_GRADE_PROFITABILITY_EDGE_OR_TRADING_AUTHORITY',
]
MAX_BYTES = 1024 * 1024
MAX_EVALUATIONS = 64
MAX_STORE_BYTES = 16 * 1024 * 1024
_ID = re.compile(r'narrative-eval-[0-9a-f]{64}\Z')
_REPORT = re.compile(r'sentry-synthesis-[0-9a-f]{64}\Z')
_TEMP = re.compile(r'\.publish-[0-9a-f]{32}\.tmp\Z')
ERRORS = (ValueError, TypeError, KeyError, OSError, RuntimeError, JournalStoreError)


def analytical_quality(packet, draft, challenge=None):
    """Deterministic blockers only; source entailment is never a keyword verdict.

    Passing this screen still requires the existing attributed narrative review.
    It cannot establish materiality, causal truth, economic support or authority.
    """
    evidence = {e['evidence_id']:e for e in packet['evidence']}
    findings = []
    def flag(code, path, reason):
        findings.append({'code':code,'path':path,'reason':reason})
    labels = {'directmention','hypotheticalreadthrough','unknown','tbd','todo','n/a'}
    def normalized(s): return ''.join(c.lower() for c in s if c.isalnum())
    for ti, theme in enumerate(draft.get('themes',[])):
        for _, implication in implication_items(theme):
            for lens in ('trading','investment'):
                text = implication[lens]
                key = normalized(text)
                path = f'/draft/themes/{ti}/implication/{implication["symbol"]}/{lens}'
                if key in labels or key in {'directmention','hypotheticalreadthrough'}:
                    flag('PLACEHOLDER_OR_LINKAGE_PROSE',path,'A label is not an economic implication.')
                if len(key) >= 20 and any(key in normalized(e['data']['headline']) for e in evidence.values() if e['kind']=='HEADLINE'):
                    flag('HEADLINE_COPIED_AS_ANALYSIS',path,'The implication is a headline or headline fragment.')
    for i, review in enumerate((challenge or {}).get('reviews',[])):
        for j, missing in enumerate(review['missing_evidence']):
            if missing in evidence:
                flag('PRESENT_EVIDENCE_LISTED_AS_MISSING',f'/challenge/reviews/{i}/missing_evidence/{j}','The supplied packet already contains this evidence.')
    candidates = []
    for i, analysis in enumerate(draft.get('economic_analyses',[])):
        path = f'/draft/economic_analyses/{i}'
        for section in ('event','company_linkage'):
            claim = analysis[section]
            source = evidence.get(claim['evidence_id'])
            text = '' if source is None else source['data'].get('headline','') + ' ' + source['data'].get('article_content',{}).get('text','')
            if not claim['source_quote'] or claim['source_quote'] not in text:
                flag('SOURCE_QUOTE_NOT_PRESENT',path+'/'+section,'The claimed quotation is not in its supplied source.')
        if analysis['event']['claim_type'] == 'CONFIRMED_IN_SUPPLIED_PRIMARY_SOURCE':
            flag('PRIMARY_SOURCE_NOT_ESTABLISHED',path+'/event','This packet contains provider reports, not authenticated primary-source documents.')
        hypothesis = analysis['hypothesis']
        if hypothesis['qualification'] == 'NO_ACTIONABLE_HYPOTHESIS':
            continue
        candidates.append(analysis['analysis_id'])
        if analysis['company_linkage']['classification'] in {'UNSUPPORTED','SPECULATIVE'}:
            flag('COMPANY_EXPOSURE_UNSUPPORTED',path+'/company_linkage','A candidate requires a supported economic linkage, reviewed semantically.')
        if analysis['mechanism']['channel'] == 'UNKNOWN':
            flag('MISSING_ECONOMIC_MECHANISM',path+'/mechanism','Unknown transmission cannot qualify a research candidate.')
        if analysis['materiality']['assessment'] != 'PLAUSIBLY_MATERIAL':
            flag('MATERIALITY_NOT_ESTABLISHED',path+'/materiality','Unknown or immaterial events cannot qualify automatically.')
        if hypothesis['direction'] == 'UNDETERMINED' or hypothesis['horizon_days'] <= 0:
            flag('HYPOTHESIS_NOT_TESTABLE',path+'/hypothesis','A candidate needs a direction and review horizon.')
        for key in ('validation_conditions','invalidation_conditions'):
            if not hypothesis[key]:
                flag('OBSERVABLE_CONDITION_MISSING',path+'/hypothesis/'+key,'A research candidate needs observable validation and invalidation tests.')
    return {'schema_version':'blackpod.sentry_analytical_quality.v1',
        'status':'BLOCKED' if findings else 'REQUIRES_SEMANTIC_REVIEW' if candidates else 'NO_QUALIFIED_HYPOTHESIS',
        'deterministic_findings':findings,'candidate_analysis_ids':candidates,
        'semantic_review_required':bool(candidates),'semantic_checks':['factual_grounding','company_linkage','economic_mechanism','materiality','contradictions','testability'],
        'research_handoff_enabled':False,'authority':dict(AUTHORITY)}


def intake_quality(packet, draft, challenge=None):
    """Stricter intake revision; historical report-quality v1 remains replayable."""
    result = deepcopy(analytical_quality(packet, draft, challenge))
    result['schema_version'] = 'blackpod.sentry_analytical_quality.v2'
    findings = result['deterministic_findings']
    for ti, theme in enumerate(draft.get('themes', [])):
        for _, implication in implication_items(theme):
            for lens in ('trading', 'investment'):
                text=implication[lens].strip()
                if text.upper() in packet['watchlist']:
                    findings.append({'code':'TICKER_USED_AS_IMPLICATION',
                        'path':f'/draft/themes/{ti}/implication/{implication["symbol"]}/{lens}',
                        'reason':'A ticker alone does not explain a financial implication.'})
                token=''.join(c.lower() for c in text if c.isalnum())
                if not any(c.isalpha() for c in text) or token in {'na','speculative','sellsignal','buysignal','sell','buy'}:
                    findings.append({'code':'PLACEHOLDER_OR_LINKAGE_PROSE',
                        'path':f'/draft/themes/{ti}/implication/{implication["symbol"]}/{lens}',
                        'reason':'A punctuation-only value or classification label is not explanatory prose.'})
    for i, analysis in enumerate(draft.get('economic_analyses', [])):
        cited = set(analysis['catalyst_evidence_ids'])
        if any(analysis[key]['evidence_id'] not in cited for key in ('event','company_linkage')):
            findings.append({'code':'SOURCE_NOT_IN_CATALYST_CITATIONS',
                'path':f'/draft/economic_analyses/{i}',
                'reason':'Event and exposure quotations must belong to the declared catalyst evidence.'})
        hypothesis=analysis['hypothesis']
        identity=lambda c:tuple(c[k] for k in ('metric','operator','threshold','unit'))
        validation={identity(c) for c in hypothesis['validation_conditions']}
        invalidation={identity(c) for c in hypothesis['invalidation_conditions']}
        if validation & invalidation:
            findings.append({'code':'VALIDATION_AND_INVALIDATION_IDENTICAL',
                'path':f'/draft/economic_analyses/{i}/hypothesis',
                'reason':'The same declared observable cannot both validate and invalidate this test plan.'})
    if findings:
        result['status'] = 'BLOCKED'
    return result


def _object(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('evaluation object fields differ')
    return value


def _text(value, maximum=1600):
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > maximum or any(unicodedata.category(c) in {'Cc', 'Cf', 'Cs', 'Zl', 'Zp'} for c in value)):
        raise ValueError('invalid bounded evaluation text')
    return value


def _array(value, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError('invalid bounded evaluation array')
    return value


def _enum(value, choices):
    if not isinstance(value, str) or value not in choices:
        raise ValueError('unknown evaluation category')
    return value


def _digest(value):
    if not isinstance(value, str) or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise ValueError('invalid evaluation digest')
    return value


def _hash(value):
    return sha256_bytes(canonical_json_bytes(value))


def _source(report):
    if (not isinstance(report, dict) or report.get('status') != 'CHALLENGED_INTERPRETATION'
            or not isinstance(report.get('report_id'), str) or _REPORT.fullmatch(report['report_id']) is None
            or report.get('authority') != AUTHORITY
            or any(type(v) is not bool for v in report['authority'].values())
            or any(report['provenance'][r]['status'] != 'ACCEPTED' for r in ('oracle', 'challenge'))):
        raise ValueError('evaluation requires an accepted original brief and challenge with no authority')
    expected = compose_report(report['context'], report['provenance']['oracle'],
        report['provenance']['challenge'], report['completed_at'],
        **({'validation': report['validation']} if 'validation' in report else {}))
    if (expected != report or report['context'].get('authority') != AUTHORITY
            or any(type(v) is not bool for v in report['context']['authority'].values())):
        raise ValueError('source synthesis does not replay')
    return report


def claim_catalog(report):
    """Exact original symbol-implication paths; no inferred claims or horizons."""
    _source(report)
    claims = []
    for ti, theme in enumerate(report['draft']['themes']):
        for relative_path, implication in implication_items(theme):
            for lens in ('trading', 'investment'):
                text = implication[lens]
                if text == 'UNSPECIFIED':
                    continue
                claims.append({'claim_path': f'/draft/themes/{ti}/{relative_path}/{lens}',
                    'symbol': implication['symbol'], 'lens': lens, 'claim_text': text,
                    'cited_evidence_ids': list(theme['evidence_ids'])})
    if _economic_report(report):
        for index, analysis in enumerate(report['draft']['economic_analyses']):
            for section, field in (('event','statement'),('company_linkage','basis'),
                    ('mechanism','explanation'),('materiality','basis'),('hypothesis','statement')):
                claims.append({'claim_path':f'/draft/economic_analyses/{index}/{section}/{field}',
                    'symbol':analysis['security'],'lens':'STRUCTURED_ECONOMIC_ANALYSIS',
                    'claim_text':analysis[section][field],
                    'cited_evidence_ids':list(analysis['catalyst_evidence_ids'])})
    return claims


def _normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def mechanical_review(report):
    """Exact observable patterns only. No lexical sentiment/entailment grader."""
    _source(report)
    draft, challenge, packet = report['draft'], report['challenge'], report['context']
    findings = []
    def add(code, paths, detail, ids=()):
        findings.append({'code': code, 'paths': paths, 'evidence_ids': list(ids), 'detail': detail})
    texts = [('/draft/overview/text', draft['overview']['text'])]
    themes = {theme['theme_id']: theme for theme in draft['themes']}
    mentioned = set()
    unspecified = {'trading_count': 0, 'investment_count': 0, 'horizon_count': 0, 'invalidation_count': 0}
    for ti, theme in enumerate(draft['themes']):
        base = f'/draft/themes/{ti}'
        texts += [(base + '/' + key, theme[key]) for key in ('interpretation', 'alternative')]
        if _normalized(theme['alternative']) == _normalized(theme['title']):
            add('ALTERNATIVE_REPEATS_TITLE', [base + '/alternative', base + '/title'],
                'Alternative text repeats the theme title after whitespace/case normalization.')
        for relative_path, implication in implication_items(theme):
            mentioned.add(implication['symbol'])
            for lens in ('trading', 'investment'):
                unspecified[lens + '_count'] += implication[lens] == 'UNSPECIFIED'
                texts.append((f'{base}/{relative_path}/{lens}', implication[lens]))
        unspecified['horizon_count'] += theme['proposed_review_horizon'] == 'UNSPECIFIED'
        inv = theme['proposed_invalidation']
        unspecified['invalidation_count'] += inv is None or isinstance(inv, dict) and inv.get('status') == 'UNSPECIFIED'
    evidence = {item['evidence_id']: item for item in packet['evidence']}
    reasons = {}
    for ri, review in enumerate(challenge['reviews']):
        base = f'/challenge/reviews/{ri}'
        reasons.setdefault(_normalized(review['reason']), []).append(base + '/reason')
        texts += [(base + '/' + key, review[key]) for key in ('reason', 'alternative')]
        if _normalized(review['alternative']) == _normalized(themes[review['theme_id']]['title']):
            add('ALTERNATIVE_REPEATS_TITLE', [base + '/alternative'], 'Challenge alternative repeats the original theme title.')
        for mi, missing in enumerate(review['missing_evidence']):
            if missing in evidence:
                add('PRESENT_EVIDENCE_LISTED_AS_MISSING', [f'{base}/missing_evidence/{mi}'],
                    'The missing-evidence entry is exactly an ID already present in the original packet.', [missing])
    for paths in reasons.values():
        if len(paths) > 1:
            add('REPEATED_CHALLENGE_REASON', paths, 'Separate themes have identical normalized challenge reasons.')
    # Deliberately conservative sentence segmentation: punctuation followed by
    # whitespace. It detects this exact pattern; it does not measure prose quality.
    for path, text in texts:
        counts = Counter(_normalized(s) for s in re.split(r'(?<=[.!?])\s+', text) if s.strip())
        for sentence, count in counts.items():
            if count > 1 and len(sentence) >= 12:
                add('REPEATED_SENTENCE', [path], f'A normalized sentence occurs {count} times within this field.')
    if not draft['unresolved_questions']:
        add('EMPTY_UNRESOLVED_QUESTIONS', ['/draft/unresolved_questions'],
            'The draft records no unresolved questions; this is not evidence of completeness.')
    return {'findings': findings,
        'coverage': {'watchlist': list(packet['watchlist']),
            'mentioned_symbols': [s for s in packet['watchlist'] if s in mentioned],
            'unmentioned_symbols': [s for s in packet['watchlist'] if s not in mentioned],
            'headline_count': sum(e['kind'] == 'HEADLINE' for e in packet['evidence']),
            'stale_context_count': packet['quality']['stale_context_count'], 'source_count': packet['quality']['source_count']},
        'unspecified': unspecified, 'limitations': list(LIMITATIONS)}


def validate_review(review, report):
    _source(report)
    value = deepcopy(_object(review, {'schema_version', 'rubric_version', 'review_id', 'reviewed_at', 'reviewer',
        'method', 'source_report_id', 'source_report_sha256', 'packet_sha256', 'criteria', 'claims', 'later_context'}))
    expected_review = ECONOMIC_REVIEW_VERSION if _economic_report(report) else REVIEW_VERSION
    expected_rubric = ECONOMIC_RUBRIC_VERSION if _economic_report(report) else RUBRIC_VERSION
    if (value['schema_version'] != expected_review or value['rubric_version'] != expected_rubric
            or value['method'] != 'ASSISTANT_ADJUDICATION'
            or value['source_report_id'] != report['report_id']
            or _digest(value['source_report_sha256']) != _hash(report)
            or _digest(value['packet_sha256']) != _hash(report['context'])
            or clock(value['reviewed_at']) < clock(report['completed_at'])):
        raise ValueError('review source, version or clock binding differs')
    if re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', _text(value['review_id'], 80)) is None:
        raise ValueError('invalid review identity')
    _text(value['reviewer'], 200)
    known = {e['evidence_id'] for e in report['context']['evidence']}
    def ids(items):
        _array(items, len(known))
        if any(not isinstance(x, str) or x not in known for x in items) or len(set(items)) != len(items):
            raise ValueError('review references unknown or duplicate evidence')
    seen = set()
    for row in _array(value['criteria'], len(RUBRIC_IDS)):
        _object(row, {'criterion_id', 'assessment', 'rationale', 'evidence_ids'})
        key = _enum(row['criterion_id'], RUBRIC_IDS)
        if key in seen:
            raise ValueError('duplicate review criterion')
        seen.add(key); _enum(row['assessment'], ASSESSMENTS); _text(row['rationale']); ids(row['evidence_ids'])
    if seen != set(RUBRIC_IDS):
        raise ValueError('review must explicitly cover every rubric criterion')
    catalog = {row['claim_path']: row for row in claim_catalog(report)}
    seen = set()
    for row in _array(value['claims'], 60):
        _object(row, {'claim_path', 'assessment', 'rationale', 'packet_evidence_ids', 'needed_evidence'})
        path = _enum(row['claim_path'], catalog)
        if path in seen:
            raise ValueError('duplicate claim review')
        seen.add(path); _enum(row['assessment'], SUPPORT); _text(row['rationale']); ids(row['packet_evidence_ids'])
        needed = [_text(t, 500) for t in _array(row['needed_evidence'], 5)]
        if len(set(needed)) != len(needed):
            raise ValueError('duplicate needed evidence')
    if seen != set(catalog):
        raise ValueError('review must cover every specified symbol implication')
    for later in _array(value['later_context'], 5):
        _object(later, {'source', 'text'})
        _enum(later['source'], {'USER_MESSAGE_AFTER_GENERATION'}); _text(later['text'])
    if len(canonical_json_bytes(value)) > MAX_BYTES:
        raise ValueError('oversized narrative review')
    return value


def evaluation_id(review):
    return 'narrative-eval-' + _hash({key: review[key] for key in ('rubric_version', 'source_report_id', 'review_id')})


def build_evaluation(report, review):
    review = validate_review(review, report)
    mechanical = mechanical_review(report)
    catalog = {row['claim_path']: row for row in claim_catalog(report)}
    criteria = sorted(review['criteria'], key=lambda row: RUBRIC_IDS.index(row['criterion_id']))
    counts = {key: sum(row['assessment'] == key for row in criteria) for key in sorted(ASSESSMENTS)}
    status = ('NEEDS_REVISION' if counts['NEEDS_WORK'] else 'REVIEW_INCOMPLETE' if counts['NOT_ASSESSED']
              else 'MIXED_REVIEW' if counts['PARTIAL'] else 'MEETS_REVIEW_RUBRIC')
    economic = _economic_report(report)
    limitations = list(LIMITATIONS)
    if economic:
        limitations.remove('HEADLINE_PACKET_ONLY_NO_LATER_ARTICLE_BODIES_OR_MARKET_OUTCOMES')
        limitations.remove('CLAIM_SCOPE_IS_SPECIFIED_SYMBOL_IMPLICATIONS_NOT_ALL_PROSE_OR_MARKET_TRUTH')
        limitations.extend(['PROVIDER_CONTENT_SCOPE_AND_MISSING_BODIES_RETAINED_NO_MARKET_OUTCOMES',
            'REVIEW_COVERS_STRUCTURED_ECONOMIC_ARGUMENT_NOT_AUTHENTICATED_MARKET_TRUTH'])
    result = {'schema_version': 'blackpod.sentry_narrative_evaluation.v2' if economic else VERSION, 'evaluation_id': evaluation_id(review),
        'source_report_id': report['report_id'], 'source_report_sha256': _hash(report),
        'packet_sha256': _hash(report['context']), 'context_id': report['context']['context_id'],
        'source_prefix': deepcopy(report['context']['source']),
        'draft_sha256': _hash(report['draft']), 'challenge_sha256': _hash(report['challenge']),
        'rubric_version': ECONOMIC_RUBRIC_VERSION if economic else RUBRIC_VERSION,
        'rubric_sha256': ECONOMIC_RUBRIC_SHA256 if economic else RUBRIC_SHA256,
        'rubric': deepcopy(ECONOMIC_RUBRIC if economic else RUBRIC),
        'review_id': review['review_id'], 'review_sha256': _hash(review), 'reviewed_at': review['reviewed_at'],
        'reviewer': review['reviewer'], 'method': review['method'], 'criteria': criteria,
        'claims': [{**catalog[row['claim_path']], **row} for row in sorted(review['claims'], key=lambda r: r['claim_path'])],
        'later_context': review['later_context'], 'mechanical': mechanical,
        'summary': {'status': status, 'criteria_counts': counts, 'reviewed_claim_count': len(review['claims']),
            'claim_count': len(catalog), 'mechanical_finding_count': len(mechanical['findings'])},
        'limitations': limitations, 'authority': dict(AUTHORITY)}
    result['evaluation_sha256'] = _hash(result)
    return result


def paths(config):
    root = _absolute_path(Path(config['station_root']) / 'narrative-evaluations')
    for key in ('runtime_root', 'experiment_root', 'historical_root', 'ui_root'):
        check_separate_root(root, Path(config[key]))
    repo = Path(config['repo_root'])
    for other in [Path(config['station_root']) / 'synthesis', Path(config['station_root']) / 'catalyst',
                  Path(config['credentials_file']).parent, *(repo / name for name in ('src', 'tests', 'fixtures', '.git', 'missions'))]:
        check_separate_root(root, other)
    return root


def _guard(config):
    _off(Path(config['runtime_root']))
    _pinned_view(Path(config['experiment_root']), config['experiment_id'], config['protocol_sha256'])


def load_verified_report(config, report_id):
    """Only the canonical retained-report verifier; no provider client or content probe."""
    from .sentry_synthesis_service import ledger, paths as source_paths, read_report
    if not isinstance(report_id, str) or _REPORT.fullmatch(report_id) is None:
        raise ValueError('invalid source report identity')
    found = []
    for directory, _, _, _ in ledger(source_paths(config)[1]):
        candidate = directory / 'report.json'
        if os.path.lexists(candidate):
            retained = parse_strict_json_object_bytes(read_regular(candidate, max_bytes=MAX_BYTES))
            if retained.get('report_id') == report_id:
                found.append(read_report(directory, config))
    if len(found) != 1:
        raise ValueError('unique retained narrative source unavailable')
    return _source(found[0])


def _inventory(root, *, with_size=False):
    """Inspect bounded anchored capsules, allowing only known interrupted publications."""
    if not os.path.lexists(root):
        return ([], 0) if with_size else []
    fd = _open_root(root, create=False)
    entries, total = [], 0
    try:
        for name in sorted(os.listdir(fd)):
            if name == '.station.lock':
                raw, info = _read_regular(fd, name)
                if raw or info.st_nlink != 1:
                    raise ValueError('unsafe evaluation lock')
                continue
            if _ID.fullmatch(name) is None:
                raise ValueError('unknown evaluation storage entry')
            child = _open_child_directory(fd, name, create=False)
            try:
                names = set(os.listdir(child))
                if names - {'source-report.json', 'review.json', 'evaluation.json', 'staging'}:
                    raise ValueError('unknown evaluation capsule file')
                for file in names - {'staging'}:
                    metadata = os.stat(file, dir_fd=child, follow_symlinks=False)
                    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
                        raise ValueError('unsafe or oversized evaluation artifact')
                    value, raw = _read(child, file)
                    if raw != canonical_json_bytes(value):
                        raise ValueError('noncanonical evaluation artifact')
                    total += len(raw)
                if 'staging' in names:
                    staging = _open_child_directory(child, 'staging', create=False)
                    try:
                        if len(os.listdir(staging)) > 16:
                            raise ValueError('evaluation staging capacity exceeded')
                        for temporary in os.listdir(staging):
                            if _TEMP.fullmatch(temporary) is None:
                                raise ValueError('unknown evaluation staging entry')
                            metadata = os.stat(temporary, dir_fd=staging, follow_symlinks=False)
                            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
                                raise ValueError('unsafe or oversized evaluation staging artifact')
                            raw, info = _read_regular(staging, temporary)
                            if len(raw) > MAX_BYTES or info.st_nlink not in (1, 2):
                                raise ValueError('unsafe evaluation staging file')
                            if info.st_nlink == 2 and not any(os.path.samestat(info, os.stat(n, dir_fd=child, follow_symlinks=False)) for n in names - {'staging'}):
                                raise ValueError('external evaluation staging hardlink')
                            total += len(raw)
                    finally:
                        os.close(staging)
                entries.append(root / name)
            finally:
                os.close(child)
        if len(entries) > MAX_EVALUATIONS or total > MAX_STORE_BYTES:
            raise ValueError('evaluation storage capacity exceeded')
        return (entries, total) if with_size else entries
    finally:
        os.close(fd)


def _json(directory, name):
    fd = _open_root(directory, create=False)
    try:
        value, raw = _read(fd, name)
        if len(raw) > MAX_BYTES or raw != canonical_json_bytes(value):
            raise ValueError('noncanonical evaluation input')
        return value
    finally:
        os.close(fd)


def _write(directory, name, value):
    payload = canonical_json_bytes(value)
    if len(payload) > MAX_BYTES:
        raise ValueError('oversized evaluation artifact')
    fd = _open_root(directory, create=True)
    stage = None
    try:
        stage = _open_child_directory(fd, 'staging', create=True)
        if name in os.listdir(fd):
            _, existing = _read(fd, name)
            if existing != payload:
                raise ValueError('immutable evaluation identity conflict')
        else:
            _publish_immutable(stage, fd, name, payload)
    finally:
        if stage is not None:
            os.close(stage)
        os.close(fd)


def _replay(directory, report):
    original = _json(directory, 'source-report.json')
    review = _json(directory, 'review.json')
    result = _json(directory, 'evaluation.json')
    if (original != report or directory.name != evaluation_id(review)
            or result != build_evaluation(original, review)
            or clock(review['reviewed_at']) > datetime.now(timezone.utc)):
        raise ValueError('narrative evaluation does not replay original source/review')
    return result


def evaluate(config, review):
    """Explicit offline export; same identity retries complete safe partial publication."""
    _guard(config)
    report = load_verified_report(config, review.get('source_report_id') if isinstance(review, dict) else None)
    result = build_evaluation(report, review)
    if clock(review['reviewed_at']) > datetime.now(timezone.utc):
        raise ValueError('review clock is in the future')
    root = paths(config)
    before = _inventory(root)
    directory = root / result['evaluation_id']
    if directory not in before and len(before) >= MAX_EVALUATIONS:
        raise ValueError('evaluation capacity exhausted')
    with service_lock(root):
        current, size = _inventory(root, with_size=True)
        if directory not in current and len(current) >= MAX_EVALUATIONS:
            raise ValueError('evaluation capacity exhausted')
        materials = {'review.json': validate_review(review, report),
                     'source-report.json': report, 'evaluation.json': result}
        additional = 0
        for name, material in materials.items():
            payload = canonical_json_bytes(material)
            if len(payload) > MAX_BYTES:
                raise ValueError('oversized evaluation artifact')
            if os.path.lexists(directory / name):
                if canonical_json_bytes(_json(directory, name)) != payload:
                    raise ValueError('immutable evaluation identity conflict')
            else:
                additional += len(payload)
        if size + additional > MAX_STORE_BYTES:
            raise ValueError('evaluation storage capacity exhausted')
        _guard(config)
        # The review is published first to reserve identity before source/output.
        _write(directory, 'review.json', validate_review(review, report))
        _write(directory, 'source-report.json', report)
        _guard(config)
        if load_verified_report(config, report['report_id']) != report:
            raise ValueError('original synthesis source changed during evaluation')
        _write(directory, 'evaluation.json', result)
        _inventory(root)
        _guard(config)
        if load_verified_report(config, report['report_id']) != report:
            raise ValueError('original synthesis source changed during evaluation')
        return _replay(directory, report)


def verify(config, identity):
    _guard(config)
    if not isinstance(identity, str) or _ID.fullmatch(identity) is None:
        raise ValueError('invalid evaluation identity')
    root = paths(config)
    if root / identity not in _inventory(root):
        raise ValueError('evaluation not recorded')
    review = _json(root / identity, 'review.json')
    report = load_verified_report(config, review['source_report_id'])
    result = _replay(root / identity, report)
    _guard(config)
    return {'status': 'VERIFIED', 'evaluation_id': identity, 'report': result, 'provider_calls': 0}


def evaluation_status(config, report):
    """Read-only attachment to this exact displayed report; never create a review."""
    value = {'status': 'NOT_RECORDED', 'report': None}
    try:
        if report is None:
            return value
        _guard(config)
        root = paths(config)
        entries = _inventory(root)
        matches = []
        for directory in entries:
            review = _json(directory, 'review.json')
            if review.get('source_report_id') == report['report_id']:
                matches.append(_replay(directory, report))
        if matches:
            latest = max(matches, key=lambda r: (clock(r['reviewed_at']), r['evaluation_id']))
            return {'status': 'AVAILABLE', 'report': latest}
        if entries:
            value['status'] = 'NO_MATCHING_REVIEW'
        return value
    except ERRORS:
        return {'status': 'UNAVAILABLE', 'report': None}


def main(argv=None):
    from .shadow_station import load_config
    parser = argparse.ArgumentParser(description='Offline evaluation of preserved Sentry narrative quality; no inference or trading')
    parser.add_argument('command', choices=['evaluate', 'verify'])
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--review', type=Path)
    parser.add_argument('--evaluation-id')
    args = parser.parse_args(argv)
    if args.command == 'evaluate' and (args.review is None or args.evaluation_id is not None):
        parser.error('evaluate requires only --review')
    if args.command == 'verify' and (args.evaluation_id is None or args.review is not None):
        parser.error('verify requires only --evaluation-id')
    try:
        config = load_config(args.config)
        if args.command == 'evaluate':
            review = parse_strict_json_object_bytes(read_regular(args.review, max_bytes=MAX_BYTES))
            report = evaluate(config, review)
            result = {'status': 'RECORDED', 'evaluation_id': report['evaluation_id'],
                'summary': report['summary'], 'provider_calls': 0, 'authority': dict(AUTHORITY)}
        else:
            verified = verify(config, args.evaluation_id)
            result = {key: verified[key] for key in ('status', 'evaluation_id', 'provider_calls')}
        print(json.dumps(result, sort_keys=True))
        return 0
    except ERRORS:
        print(json.dumps({'status': 'BLOCKED', 'provider_calls': 0, 'authority': dict(AUTHORITY)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
