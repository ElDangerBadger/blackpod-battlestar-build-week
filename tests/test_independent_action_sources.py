"""Offline bounded workbook and explicitly authored independent-source profiles."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape

from blackpod_build_week.contracts.effective_date_reconciliation import *
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.independent_action_sources import HEADERS, parse_independent_inventory


def ref(path, raw): return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def workbook(rows=None, *, replacements=None):
    values = [list(HEADERS), *(rows or [["SPY Trust", "SPY", "78462F103", "12/15/2023", "12/18/2023", "01/31/2024", "1.906073", "0.000000", "", "Quarterly"]])]
    strings, lookup, xml_rows = [], {}, []
    for number, row in enumerate(values, 1):
        cells = []
        for key, value in zip("ABCDEFGHIJ", row):
            if value not in lookup: lookup[value] = len(strings); strings.append(value)
            cells.append('<c r="%s%d" t="s"><v>%d</v></c>' % (key, number, lookup[value]))
        xml_rows.append('<row r="%d">%s</row>' % (number, ''.join(cells)))
    ns = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    members = {
        'xl/workbook.xml': '<workbook xmlns="%s" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="dividend" sheetId="1" r:id="rId1"/></sheets></workbook>' % ns,
        'xl/_rels/workbook.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/><Relationship Id="rId2" Target="sharedStrings.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings"/></Relationships>',
        'xl/sharedStrings.xml': '<sst xmlns="%s">%s</sst>' % (ns, ''.join('<si><t>%s</t></si>' % escape(value) for value in strings)),
        'xl/worksheets/sheet1.xml': '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (ns, ''.join(xml_rows)),
    }
    for name, change in (replacements or {}).items(): members[name] = change(members.get(name, '')) if callable(change) else change
    buffer = BytesIO()
    with ZipFile(buffer, 'w', ZIP_DEFLATED) as archive:
        for name, value in members.items(): archive.writestr(name, value)
    return buffer.getvalue()


def inventory(raw, profile=SSGA_PROFILE):
    return IndependentActionInventory.from_mapping({"schema_version": INVENTORY_VERSION, "inventory_id": "unit-independent-inventory", "recorded_at": "2026-10-14T01:00:00Z",
        "profile": profile, "evidence_scope": "RETAINED_HISTORY_RESEARCH", "publisher": "SSGA" if profile == SSGA_PROFILE else "authored-unverified",
        "source_url": SSGA_URL if profile == SSGA_PROFILE else "https://example.invalid/authored", "captured_at": "2026-10-13T23:56:44.442482Z",
        "body_evidence": ref("source/workbook.xlsx" if profile == SSGA_PROFILE else "source/authored.json", raw),
        "declared_coverage": {"symbols": ["SPY"], "action_types": ["cash_dividends"], "effective_start": "2023-10-02", "effective_end": "2026-10-12", "completeness": "DECLARED_COMPLETE"},
        "supporting_evidence": [], "auto_trading_enabled": False, "authority": AUTHORITY})


def action(identity="independent-cash-1", **changes):
    return {"source_action_id": identity, "native_type": "cash_dividends", "affected_symbols": ["SPY"], "effective_date": "2023-12-15", "record_date": "2023-12-18", "payable_date": "2024-01-31",
        "status": "EFFECTIVE", "cusip": "78462F103", "amount_lexemes": {"dividend": "1.906073", "short_term_capital_gain": "0.000000", "long_term_capital_gain": None}, "replaces_source_action_id": None, **changes}


class IndependentActionSourceTests(unittest.TestCase):
    def parse(self, raw, profile=SSGA_PROFILE): return parse_independent_inventory(inventory(raw, profile), {sha256_bytes(raw): raw})

    def test_exact_shared_string_dates_amounts_and_cell_provenance(self):
        raw = workbook(); result = self.parse(raw); row = result['actions'][0]
        self.assertEqual(row['effective_date'], '2023-12-15'); self.assertEqual(row['payable_date'], '2024-01-31')
        self.assertEqual(row['amount_lexemes']['dividend'], '1.906073')
        self.assertEqual(row['amount_lexemes']['short_term_capital_gain'], '0.000000')
        self.assertEqual(row['provenance']['cells']['D']['cell'], 'D2')
        self.assertEqual(row['provenance']['cells']['D']['lexeme'], '12/15/2023')
        self.assertEqual(row['provenance']['row_sha256'], sha256_bytes(canonical_json_bytes(row['provenance']['cells'])))
        self.assertEqual(result['observed_action_types'], ['cash_dividends']); self.assertFalse(result['completeness_verified'])
        self.assertEqual(result['evidence']['source/workbook.xlsx'], raw)

    def test_unknown_completeness_and_unsupported_types_never_become_verified(self):
        raw = workbook(); value = inventory(raw).to_dict(); value['declared_coverage']['action_types'] = list(ACTION_TYPES)
        result = parse_independent_inventory(value, {sha256_bytes(raw): raw})
        self.assertEqual(result['observed_action_types'], ['cash_dividends']); self.assertFalse(result['completeness_verified'])

    def test_header_formula_cell_reference_and_shared_index_corruption_reject(self):
        member = 'xl/worksheets/sheet1.xml'
        mutations = [lambda text: text.replace('<v>0</v>', '<v>999999</v>', 1), lambda text: text.replace('r="D2"', 'r="D3"'),
            lambda text: text.replace('<v>13</v>', '<f>1+1</f><v>13</v>'), lambda text: text.replace('r="B2"', 'r="A2"'),
            lambda text: text.replace('<row r="2">', '<row r="1">')]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                with self.assertRaises(ContractValidationError): self.parse(workbook(replacements={member: mutate}))

    def test_malformed_target_identity_date_and_amount_reject(self):
        base = ["SPY Trust", "SPY", "78462F103", "12/15/2023", "12/18/2023", "01/31/2024", "1.906073", "0.000000", "", "Quarterly"]
        for position, value in ((1, ' SPY '), (2, 'INVALID'), (3, '2023-12-15'), (3, '02/30/2023'), (6, '-0.1'), (6, '1e3')):
            row = list(base); row[position] = value
            with self.subTest(value=value), self.assertRaises(ContractValidationError): self.parse(workbook([row]))

    def test_dtd_entities_and_extra_sheet_external_target_reject(self):
        cases = [ {'xl/sharedStrings.xml': lambda text: '<!DOCTYPE x [<!ENTITY bomb "x">]>' + text},
            {'xl/workbook.xml': lambda text: text.replace('</sheets>', '<sheet name="other" sheetId="2" r:id="rId2"/></sheets>')},
            {'xl/_rels/workbook.xml.rels': lambda text: text.replace('Target="worksheets/sheet1.xml"', 'Target="https://example.invalid" TargetMode="External"')} ]
        for change in cases:
            with self.assertRaises(ContractValidationError): self.parse(workbook(replacements=change))

    def test_shared_strings_relationship_cannot_point_elsewhere_or_duplicate(self):
        name = 'xl/_rels/workbook.xml.rels'
        for mutate in (lambda text:text.replace('Target="sharedStrings.xml"','Target="other.xml"'),lambda text:text.replace('Id="rId2"','Id="rId1"')):
            with self.assertRaises(ContractValidationError): self.parse(workbook(replacements={name:mutate}))

    def test_utf16_xml_cannot_bypass_dtd_entity_prohibition(self):
        source = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE sst [<!ENTITY x "amplification">]><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>&x;</t></si></sst>'
        with self.assertRaises(ContractValidationError): self.parse(workbook(replacements={'xl/sharedStrings.xml':source.encode('utf-16')}))

    def test_zip_traversal_bomb_missing_member_and_resource_limits_reject(self):
        for changes in ({'../escape': 'data'}, {'large.xml': '0' * 100000}, {'xl/sharedStrings.xml': '<wrong/>'}):
            with self.assertRaises(ContractValidationError): self.parse(workbook(replacements=changes))
        raw = workbook()
        with patch('blackpod_build_week.independent_action_sources.MAX_ZIP_BYTES', len(raw)-1), self.assertRaises(ContractValidationError): self.parse(raw)
        with patch('blackpod_build_week.independent_action_sources.MAX_UNCOMPRESSED_BYTES', 10), self.assertRaises(ContractValidationError): self.parse(raw)
        with self.assertRaises(ContractValidationError): self.parse(b'not a zip')

    def test_non_target_rows_are_not_misrepresented_as_target_evidence(self):
        raw = workbook([["Other Trust", "OTHER", "123456789", "12/15/2023", "12/18/2023", "01/31/2024", "1.00", "", "", "Annual"]])
        result = self.parse(raw); self.assertEqual(result['actions'], []); self.assertEqual(result['rows_scanned'], 1)

    def test_authored_statuses_corrections_and_unknowns_remain_unverified(self):
        actions = [action('authored-' + status.lower(), status=status, effective_date=None if status == 'UNKNOWN' else '2023-12-15') for status in ('EFFECTIVE','SCHEDULED','CANCELLED','REVISED','UNKNOWN')]
        raw = canonical_json_bytes({'schema_version': AUTHORED_VERSION, 'label': 'AUTHORED_UNVERIFIED', 'actions': actions})
        result = self.parse(raw, 'AUTHORED_EFFECTIVE_DATE_ACTIONS_JSON_V1')
        self.assertEqual([row['status'] for row in result['actions']], [row['status'] for row in actions])
        self.assertEqual(result['actions'][0]['provenance']['value_pointer'], '/actions/0'); self.assertFalse(result['completeness_verified'])

    def test_authored_duplicates_unknown_fields_and_approval_claims_reject(self):
        for rows in ([action(), action()], [{**action(), 'approval': True}], [action(status='APPROVED')], [action(amount_lexemes={'dividend':'1'})]):
            raw = canonical_json_bytes({'schema_version': AUTHORED_VERSION, 'label': 'AUTHORED_UNVERIFIED', 'actions': rows})
            with self.assertRaises(ContractValidationError): self.parse(raw, 'AUTHORED_EFFECTIVE_DATE_ACTIONS_JSON_V1')

    def test_source_hash_and_closed_manifest_authority_reject(self):
        raw = workbook(); value = inventory(raw).to_dict()
        with self.assertRaises(ContractValidationError): parse_independent_inventory(value, {sha256_bytes(raw): raw+b' '})
        for field, changed in (('source_url', 'https://example.invalid/fake.xlsx'), ('auto_trading_enabled', True), ('supporting_evidence', [{}])):
            row = deepcopy(value); row[field] = changed
            with self.assertRaises(ContractValidationError): IndependentActionInventory.from_mapping(row)

    @unittest.skipUnless(Path('output/effective-date-applicability-real-001/source/ssga-historical-distributions.xlsx').exists(), 'retained real workbook not present')
    def test_retained_real_workbook_exact_hash_rows_and_lexemes(self):
        raw = Path('output/effective-date-applicability-real-001/source/ssga-historical-distributions.xlsx').read_bytes()
        self.assertEqual(len(raw), 581242); self.assertEqual(sha256_bytes(raw), 'b162dd17027d1128f2209e312b0f634960daa78319dafe0ab821ab0b7e77ce23')
        parsed = self.parse(raw); self.assertEqual(parsed['rows_scanned'], 13383); self.assertEqual(len(parsed['actions']), 136)
        rows = {row['provenance']['row']: row for row in parsed['actions']}
        self.assertEqual(rows[9129]['effective_date'], '2026-09-18'); self.assertEqual(rows[9129]['payable_date'], '2026-10-30')
        self.assertEqual(rows[9140]['amount_lexemes']['dividend'], '1.906073'); self.assertFalse(parsed['completeness_verified'])


if __name__ == '__main__': unittest.main()
