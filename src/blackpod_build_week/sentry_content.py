"""Deterministic provider-content projection; no URL fetching or generated text."""
from copy import deepcopy
from html.parser import HTMLParser
import json

from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_catalyst import clock
from .sentry_catalyst_capture import validate_receipt

PACKET_VERSION = 'blackpod.sentry_synthesis.v2'
EXTRACTION_VERSION = 'blackpod.provider_html_text.v1'
MAX_ARTICLE_CHARACTERS = 8000
MAX_PACKET_CONTENT_CHARACTERS = 64000


class ProviderText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style'}:
            self.hidden += 1
        if tag in {'p', 'br', 'div', 'li', 'h1', 'h2', 'h3'}:
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in {'script', 'style'}:
            self.hidden = max(0, self.hidden - 1)
        if tag in {'p', 'div', 'li'}:
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def provider_text(raw):
    parser = ProviderText()
    parser.feed(raw)
    parser.close()
    return ' '.join(''.join(parser.parts).split())


def enrich_packet(packet, records, read_blob):
    """Rebuild richer evidence from exact retained provider bodies/receipts.

    A later headline-only poll does not erase a body previously retrieved for
    the same provider revision. Bodies retrieved after as_of are never used.
    Raw HTML stays in the immutable source store; only deterministic, explicitly
    bounded text is supplied to inference. No publisher-completeness claim.
    """
    result = deepcopy(packet)
    as_of = clock(packet['as_of'])
    bodies = {}
    for record in records:
        receipt = validate_receipt(json.loads(read_blob(record['evidence']['news_receipt']['sha256'])), 'news')
        if receipt['query']['include_content'] != 'true' or clock(receipt['captured_at']) > as_of:
            continue
        raw = read_blob(record['evidence']['news']['sha256'])
        if sha256_bytes(raw) != receipt['body_sha256']:
            raise ValueError('provider-content receipt mismatch')
        news = json.loads(raw)
        projected = {a['provider_id']: a for a in record['projection']['articles']}
        for item in news['news']:
            identity = str(item['id'])
            if identity not in projected:
                continue
            bodies[(identity, projected[identity]['revision_sha256'])] = (item, receipt, record)
    remaining, signatures, available, excerpts = MAX_PACKET_CONTENT_CHARACTERS, [], 0, 0
    for evidence in result['evidence']:
        if evidence['kind'] != 'HEADLINE':
            continue
        data = evidence['data']
        found = bodies.get((data['provider_id'], data['revision_sha256']))
        content = {'status': 'NOT_RETRIEVED', 'scope': 'NO_CONTENT', 'text': '',
            'raw_content_sha256': None, 'text_sha256': None, 'retrieved_at': None,
            'source_news_sha256': None, 'extraction_version': EXTRACTION_VERSION,
            'available_text_characters': 0, 'supplied_text_characters': 0,
            'publisher_completeness_verified': False}
        if found:
            item, receipt, source = found
            body = item.get('content')
            content.update(retrieved_at=receipt['captured_at'], source_news_sha256=receipt['body_sha256'])
            content['status'] = 'PROVIDER_CONTENT_UNAVAILABLE'
            if isinstance(body, str) and body.strip():
                text = provider_text(body)
                supplied = text[:min(MAX_ARTICLE_CHARACTERS, remaining)]
                remaining -= len(supplied)
                content.update(raw_content_sha256=sha256_bytes(body.encode('utf-8')),
                    available_text_characters=len(text), supplied_text_characters=len(supplied),
                    text=supplied, text_sha256=sha256_bytes(supplied.encode('utf-8')),
                    status='AVAILABLE' if supplied else 'CONTEXT_BUDGET_OR_EMPTY_CONTENT',
                    scope='FULL_PROVIDER_TEXT' if supplied and supplied == text else 'VERIFIED_EXCERPT' if supplied else 'NO_CONTENT')
                available += bool(supplied)
                excerpts += content['scope'] == 'VERIFIED_EXCERPT'
        publication_age = int((as_of - clock(data['published_at'])).total_seconds())
        first_age = int((as_of - clock(data['first_seen_at'])).total_seconds())
        data.update(article_content=content, publication_age_seconds=publication_age,
            information_state='NEWLY_PUBLISHED' if publication_age <= 3600 and first_age <= 600 else
                'NEWLY_RETRIEVED_HISTORICAL' if first_age <= 600 else 'PREVIOUSLY_OBSERVED',
            content_level=content['scope'])
        evidence['evidence_id'] = 'ev-' + sha256_bytes(canonical_json_bytes({k:v for k,v in evidence.items() if k != 'evidence_id'}))
        signatures.append([data['provider_id'], data['revision_sha256'], content['raw_content_sha256'], content['scope'], content['text_sha256']])
    result['schema_version'] = PACKET_VERSION
    result['quality'].update(headline_only=available == 0, article_content_count=available,
        excerpt_count=excerpts, article_body_completeness_verified=False)
    for evidence in result['evidence']:
        evidence['evidence_id'] = 'ev-' + sha256_bytes(canonical_json_bytes({k:v for k,v in evidence.items() if k != 'evidence_id'}))
    result['limitations'] = [s for s in result['limitations'] if s != 'HEADLINE_ONLY_ARTICLE_BODIES_NOT_READ']
    result['limitations'] += ['ARTICLE_CONTENT_PROVIDER_REPORTED_NOT_INDEPENDENTLY_VERIFIED',
        'CONTENT_AVAILABILITY_AND_EXCERPT_LIMITS_EXPLICIT']
    result['evidence_signature'] = sha256_bytes(canonical_json_bytes({'baseline':packet['evidence_signature'], 'content':signatures}))
    result['context_id'] = 'sentry-context-' + sha256_bytes(canonical_json_bytes({k:v for k,v in result.items() if k != 'context_id'}))
    return result


def comparison_fixture(parent, recipe):
    """Explicit, reproducible evidence subsets; authored stress cases stay labeled."""
    if (set(recipe) != {'fixture_id','symbols','article_ids','stress'} or recipe['stress'] not in {'NONE','DUPLICATE','CONTRADICTION'}
            or not set(recipe['symbols']) <= set(parent['watchlist'])):
        raise ValueError('invalid comparison fixture recipe')
    result = deepcopy(parent)
    result['watchlist'] = list(recipe['symbols'])
    chosen = []
    for row in result['evidence']:
        if row['kind'] == 'HEADLINE' and row['data']['provider_id'] not in recipe['article_ids']:
            continue
        if row['kind'] == 'PRICE_CONTEXT' and not set(row['symbols']) & set(recipe['symbols']):
            continue
        row['symbols'] = [s for s in row['symbols'] if s in recipe['symbols']]
        chosen.append(row)
    originals = [e for e in chosen if e['kind']=='HEADLINE']
    if not originals:
        raise ValueError('fixture has no retained headline')
    if recipe['stress'] != 'NONE':
        row = deepcopy(originals[0])
        row['binding'] = {'authored_fixture_parent': originals[0]['evidence_id'], 'stress':recipe['stress']}
        if recipe['stress'] == 'CONTRADICTION':
            row['data']['headline'] = 'AUTHORED REGRESSION FIXTURE: issuer denies the reported financing deterioration.'
            row['data']['source'] = 'AUTHORED_REGRESSION_FIXTURE_NOT_MARKET_FACT'
            row['data']['article_content'] = {'status':'AUTHORED_FIXTURE','scope':'AUTHORED_FIXTURE',
                'text':'This is a synthetic conflicting test claim. The reported deterioration in financing conditions is disputed; source reliability and the underlying figures are unresolved.'}
        chosen.append(row)
    for row in chosen:
        row['evidence_id']='ev-'+sha256_bytes(canonical_json_bytes({k:v for k,v in row.items() if k!='evidence_id'}))
    result['evidence'] = chosen
    result['derivation'] = {'parent_packet_sha256':sha256_bytes(canonical_json_bytes(parent)),
        'parent_version':parent['schema_version'],'recipe':deepcopy(recipe),
        'evidence_scope':'RETAINED_PROVIDER_EVIDENCE' if recipe['stress']=='NONE' else 'AUTHORED_ADVERSARIAL_FIXTURE'}
    result['limitations'] += ['COMPARISON_SUBSET_NOT_COMPLETE_MARKET_COVERAGE']
    if recipe['stress'] != 'NONE':
        result['limitations'] += ['AUTHORED_STRESS_TRANSFORM_NOT_REAL_MARKET_EVIDENCE']
    result['selection'] = {**result['selection'],'selected_headline_count':len(originals),'comparison_subset':True}
    result['evidence_signature'] = sha256_bytes(canonical_json_bytes({'parent':parent['evidence_signature'],'recipe':recipe}))
    result['context_id']='sentry-context-'+sha256_bytes(canonical_json_bytes({k:v for k,v in result.items() if k!='context_id'}))
    return result
