"""Evidence catalog and immutable supplemental Oracle reports; no trading rules."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_catalyst import CatalystStore, CONSOLIDATED_VERSION, clock, stamp
from .sentry_catalyst_audit import build_report as feed_audit
from .sentry_catalyst_service import paths as catalyst_paths
from .sentry_history_cache import read_regular

VERSION = 'blackpod.sentry_synthesis.v1'
MAX_HEADLINES = 20
AUTHORITY = {'authorization_enabled':False,'execution_enabled':False,
             'capital_activation_enabled':False,'allocation_enabled':False,'policy_changes_enabled':False}
LIMITATIONS = ['HEADLINE_ONLY_ARTICLE_BODIES_NOT_READ','INTERPRETATIONS_UNVERIFIED_NOT_FACTUAL_ENTAILMENT',
    'SAME_CATALOG_REVIEW_NOT_INDEPENDENT_ECONOMIC_EVIDENCE','SOURCE_INDEPENDENCE_NOT_VERIFIED',
    'NEWS_COVERAGE_INCOMPLETE_OR_UNKNOWN','PRICE_CONTEXT_NOT_POST_NEWS_REACTION_OR_CAUSATION',
    'NO_MATCHED_SPY_QQQ_RELATIVE_REACTION_COMPUTED','NO_VERIFIED_HOLDINGS_OR_PORTFOLIO_EXPOSURES',
    'NO_RECOMMENDATION_AUTHORIZATION_ORDER_OR_POLICY_CHANGE']


def build_packet(records, verification, as_of):
    """Deterministic bounded selection from a verified complete capture prefix."""
    if not records or as_of.tzinfo is None:
        raise ValueError('no verified source or aware clock')
    latest = records[-1]['projection']
    if clock(latest['captured_at']) > as_of:
        raise ValueError('source follows packet clock')
    selected = latest['symbols']
    recent, first, revision_first = {}, {}, {}
    for record in records:
        for a in record['projection']['articles']:
            first.setdefault(a['provider_id'], record['projection']['captured_at'])
            revision_first.setdefault((a['provider_id'],a['revision_sha256']),record['projection']['captured_at'])
            recent[a['provider_id']] = (a,record)
    eligible, future = [], 0
    for a,record in recent.values():
        if clock(a['updated_at']) > as_of or clock(a['published_at']) > as_of:
            future += 1; continue
        if as_of-clock(a['updated_at']) > timedelta(hours=24) or not set(a['symbols']) & set(selected):
            continue
        eligible.append((a,record))
    eligible.sort(key=lambda row:(clock(row[0]['updated_at']),row[0]['provider_id']),reverse=True)
    # Identical URLs or exact normalized headlines are attention duplicates,
    # never additional corroboration. No claim of real-world event identity.
    distinct, urls, titles = [], set(), set()
    for row in eligible:
        a = row[0]
        title = ' '.join(a['headline'].casefold().split())
        if a['url'] in urls or title in titles:
            continue
        urls.add(a['url']); titles.add(title); distinct.append(row)
    picked, used = [], set()
    for symbol in selected:
        match=next((row for row in distinct if symbol in row[0]['symbols'] and row[0]['provider_id'] not in used),None)
        if match:
            picked.append(match);used.add(match[0]['provider_id'])
    for row in distinct:
        if len(picked)>=MAX_HEADLINES:break
        if row[0]['provider_id'] not in used:
            picked.append(row);used.add(row[0]['provider_id'])
    evidence=[]
    def add(kind,named,data,binding):
        item={'kind':kind,'symbols':named,'data':data,'binding':binding}
        item['evidence_id']='ev-'+sha256_bytes(canonical_json_bytes(item))
        evidence.append(item)
    for a,record in picked:
        add('HEADLINE',sorted(set(a['symbols']) & set(selected)),
            {**a,'first_seen_at':first[a['provider_id']],
             'revision_first_seen_at':revision_first[(a['provider_id'],a['revision_sha256'])],
             'last_seen_at':record['projection']['captured_at'],'content_level':'HEADLINE_ONLY'},
            {'capture_id':record['capture_id'],'captured_at':record['projection']['captured_at'],
             'news_sha256':record['evidence']['news']['sha256'],'provider_id':a['provider_id'],'revision_sha256':a['revision_sha256']})
    fresh=stale=unavailable=future_prices=delayed=0
    consolidated = latest.get('schema_version') == CONSOLIDATED_VERSION
    for row in latest['contexts']:
        age=(as_of-clock(row['minute_at'])).total_seconds() if row.get('minute_at') else None
        label='UNAVAILABLE' if age is None else 'FUTURE_TIMESTAMP' if age<0 else 'RECENT' if age<=900 else 'STALE'
        if consolidated and latest['market_feed'] == 'delayed_sip' and age is not None and 0 <= age <= 1800:
            label = 'DELAYED'
        delayed += label == 'DELAYED'
        fresh+=label=='RECENT';stale+=label=='STALE';unavailable+=label=='UNAVAILABLE';future_prices+=label=='FUTURE_TIMESTAMP'
        add('PRICE_CONTEXT',[row['symbol']],{**row,'freshness_at_packet':label,
            'age_at_packet_seconds':None if age is None else int(age),'price_change_basis':'MINUTE_CLOSE_VS_PREVIOUS_DAILY_CLOSE_NOT_NEWS_RESPONSE'},
            {'capture_id':records[-1]['capture_id'],'captured_at':latest['captured_at'],
             'snapshots_sha256':records[-1]['evidence']['snapshots']['sha256']})
    audit = feed_audit(records,verification,as_of)
    quality={'headline_only':True,'independent_sources_verified':False,
        'source_count':len({a['source'].casefold() for a,_ in picked}),
        'news_truncated':latest['news_truncated'],'truncated_capture_count':audit['news']['truncated_capture_count'],
        'capture_count':len(records),'fresh_context_count':fresh,'stale_context_count':stale,
        'unavailable_context_count':unavailable,'future_context_count':future_prices,
        'latest_capture_at':latest['captured_at'],'overall_news_coverage_fraction':None,
        'post_headline_reaction_available':False,'holdings_available':False}
    if consolidated:
        quality.update(market_feed=latest['market_feed'], feed_delay_seconds=latest['feed_delay_seconds'],
                       delayed_context_count=delayed)
    add('FEED_QUALITY',[],quality,{'audit_report_id':audit['report_id'],
        'audit_report_sha256':sha256_bytes(canonical_json_bytes(audit))})
    signature=sha256_bytes(canonical_json_bytes({'watchlist':sorted(selected),
        'headline_revisions':sorted((a['provider_id'],a['revision_sha256']) for a,_ in distinct)}))
    packet={'schema_version':VERSION,'as_of':stamp(as_of),'source':dict(verification),
        'watchlist':selected,'evidence':evidence,'evidence_signature':signature,'quality':quality,
        'selection':{'window_hours':24,'max_headlines':MAX_HEADLINES,'selected_headline_count':len(picked),
            'eligible_article_count':len(eligible),'attention_duplicate_count':len(eligible)-len(distinct),
            'omitted_headline_count':len(distinct)-len(picked),'excluded_future_article_count':future,
            'method':'LATEST_REVISION_PER_PROVIDER_ID_THEN_EXACT_URL_OR_NORMALIZED_HEADLINE_DEDUP_SYMBOL_FIRST_THEN_RECENT'},
        'portfolio':{'status':'UNAVAILABLE_NO_VERIFIED_HOLDINGS'},'limitations':list(LIMITATIONS),'authority':dict(AUTHORITY)}
    packet['context_id']='sentry-context-'+sha256_bytes(canonical_json_bytes(packet))
    return packet


def current_packet(config,as_of=None):
    records,verification=CatalystStore(catalyst_paths(config)[1]).verified_records()
    return build_packet(records,verification,as_of or datetime.now(timezone.utc))


def verify_packet(packet,config):
    """Replay original selected prefix; later source appends do not rewrite it."""
    records,_=CatalystStore(catalyst_paths(config)[1]).verified_records()
    count=packet['source']['capture_count']
    if type(count) is not int or not 1<=count<=len(records):raise ValueError('source prefix unavailable')
    root=catalyst_paths(config)[1]
    head=sha256_bytes(read_regular(root/'entries'/f'{count:08}.json'))
    if head!=packet['source']['head_sha256'] or build_packet(records[:count],packet['source'],clock(packet['as_of']))!=packet:
        raise ValueError('packet does not replay retained source')
    return packet


def compose_report(packet,oracle,challenge,completed_at,*,validation=None):
    from .contracts.sentry_synthesis import validate_response
    draft=validate_response('oracle',oracle['response'],packet) if oracle['status']=='ACCEPTED' else None
    review=validate_response('challenge',challenge['response'],packet,draft) if draft and challenge['status']=='ACCEPTED' else None
    status='CHALLENGED_INTERPRETATION' if review else 'DRAFT_ONLY' if draft else oracle['status']
    result={'schema_version':VERSION,'status':status,'context':packet,'draft':draft,'challenge':review,
        'provenance':{'oracle':oracle,'challenge':challenge},'completed_at':completed_at,
        'review_independence':{'separate_review_pass':review is not None,'independent_model_verified':False,'independent_sources_verified':False},
        'portfolio':dict(packet['portfolio']),'authority':dict(AUTHORITY)}
    if validation is not None:
        versions={'EXPLICIT_V2_VALIDATION':'blackpod.sentry_synthesis_transport.v2',
            'EXPLICIT_DEADLINE_VALIDATION':'blackpod.sentry_synthesis_transport.v3',
            'EXPLICIT_ERROR_CODE_DIAGNOSTIC':'blackpod.sentry_synthesis_transport.v4',
            'EXPLICIT_RUNTIME_DIAGNOSTIC':'blackpod.sentry_synthesis_transport.v5',
            'EXPLICIT_MODEL_SELECTION_VALIDATION':'blackpod.sentry_synthesis_transport.v6',
            'EXPLICIT_OUTPUT_BUDGET_VALIDATION':'blackpod.sentry_synthesis_transport.v7',
            'EXPLICIT_CONTRACT_VALIDATION':'blackpod.sentry_synthesis_transport.v8',
            'EXPLICIT_TEXT_VALIDATION':'blackpod.sentry_synthesis_transport.v9',
            'EXPLICIT_SYMBOL_VALIDATION':'blackpod.sentry_synthesis_transport.v10'}
        purpose=validation.get('purpose') if isinstance(validation,dict) else None
        manual=purpose in {'EXPLICIT_DEADLINE_VALIDATION','EXPLICIT_ERROR_CODE_DIAGNOSTIC',
            'EXPLICIT_RUNTIME_DIAGNOSTIC','EXPLICIT_MODEL_SELECTION_VALIDATION','EXPLICIT_OUTPUT_BUDGET_VALIDATION','EXPLICIT_CONTRACT_VALIDATION','EXPLICIT_TEXT_VALIDATION','EXPLICIT_SYMBOL_VALIDATION'}
        fields={'purpose','parent_report_id','parent_report_sha256','transport_schema_version'}
        if manual:fields.add('scope')
        if (not isinstance(validation,dict)
                or set(validation)!=fields
                or purpose not in versions
                or validation['transport_schema_version']!=versions[purpose]
                or (manual and validation['scope']!='MANUAL_RETAINED_EVIDENCE')
                or not isinstance(validation['parent_report_id'],str)
                or re.fullmatch(r'sentry-synthesis-[0-9a-f]{64}',validation['parent_report_id']) is None
                or not isinstance(validation['parent_report_sha256'],str)
                or re.fullmatch('[0-9a-f]{64}',validation['parent_report_sha256']) is None):
            raise ValueError('invalid explicit validation linkage')
        result['validation']=dict(validation)
    result['report_id']='sentry-synthesis-'+sha256_bytes(canonical_json_bytes(result))
    return result
