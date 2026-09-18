import { describe, expect, it } from "vitest";
import { createOracleMarketBriefFixture } from "../test/oracleMarketBriefFixture";
import { validateOracleMarketBrief } from "./validateOracleMarketBrief";

describe("Oracle market brief transport validation", () => {
  it("accepts the bounded real-inference shape without changing original data", () => {
    const value = createOracleMarketBriefFixture(), before = JSON.stringify(value);
    expect(validateOracleMarketBrief(value)).toBe(value); expect(JSON.stringify(value)).toBe(before);
  });

  const mutations: [string, (value: ReturnType<typeof createOracleMarketBriefFixture>) => void][] = [
    ["new authority", (v) => Object.assign(v, { authoritative: true })],
    ["execution", (v) => Object.assign(v, { order_submission_enabled: true })],
    ["observation", (v) => Object.assign(v, { observation_only: false })],
    ["other generation method", (v) => Object.assign(v, { generation_method: "BROWSER_GENERATED" })],
    ["stronger validation claim", (v) => Object.assign(v, { validation_status: "ENTAILMENT_VERIFIED" })],
    ["mocked provenance", (v) => Object.assign(v.provenance, { mocked: true })],
    ["other provider", (v) => Object.assign(v.provenance, { provider: "unknown" })],
    ["missing provenance", (v) => { delete (v.provenance as Partial<typeof v.provenance>).response_sha256; }],
    ["hash", (v) => { v.provenance.request_sha256 = "wrong"; }],
    ["brief identity", (v) => { v.brief_id = "wrong"; }],
    ["evidence identity", (v) => { v.evidence.evidence_id = "wrong"; }],
    ["unknown field", (v) => Object.assign(v, { orders: [] })],
    ["replay", (v) => Object.assign(v.evidence, { run_mode: "REPLAY" })],
    ["same request identity", (v) => { v.evidence.request_id = v.evidence.mission_id; }],
    ["unknown fact", (v) => { v.report.headline.fact_ids = ["not-a-fact"]; }],
    ["no citations", (v) => { v.report.headline.fact_ids = []; }],
    ["duplicate citations", (v) => { v.report.headline.fact_ids.push(v.report.headline.fact_ids[0]); }],
    ["duplicate fact identity", (v) => { v.evidence.facts[1].fact_id = v.evidence.facts[0].fact_id; }],
    ["unknown source", (v) => Object.assign(v.evidence.facts[0], { source_artifact: "orders" })],
    ["invalid pointer", (v) => { v.evidence.facts[0].json_pointer = "/bad~3"; }],
    ["relative pointer", (v) => { v.evidence.facts[0].json_pointer = "breadth_score"; }],
    ["fact object", (v) => Object.assign(v.evidence.facts[0], { value: { unexpected: true } })],
    ["nonfinite value", (v) => { v.evidence.facts[0].value = Infinity; }],
    ["unsafe integer", (v) => { v.evidence.facts[0].value = Number.MAX_SAFE_INTEGER + 1; }],
    ["mixed array", (v) => Object.assign(v.evidence.facts[0], { value: [true] })],
    ["source set", (v) => { delete (v.evidence.source_artifacts as Partial<typeof v.evidence.source_artifacts>).oracle_report; }],
    ["source mismatch", (v) => { v.evidence.source_artifacts.oracle_report.name = "oracle_assessment"; }],
    ["source parent traversal", (v) => { v.evidence.source_artifacts.oracle_report.path = "../secret.json"; }],
    ["source escaped traversal", (v) => { v.evidence.source_artifacts.oracle_report.path = "oracle/%2e%2e/secret.json"; }],
    ["source URL", (v) => { v.evidence.source_artifacts.oracle_report.path = "https://example.invalid/secret"; }],
    ["source path query", (v) => { v.evidence.source_artifacts.oracle_report.path += "?token=secret"; }],
    ["source missing size", (v) => { v.evidence.source_artifacts.oracle_report.byte_size = null; }],
    ["source missing timestamp", (v) => { v.evidence.source_artifacts.oracle_report.observed_at = null; }],
    ["source too late", (v) => { v.evidence.source_artifacts.oracle_report.observed_at = "2027-01-01T00:00:00Z"; }],
    ["headline bound", (v) => { v.report.headline.text = "a".repeat(241); }],
    ["paragraph bound", (v) => { v.report.sections[0].paragraphs[0].text = "a".repeat(1201); }],
    ["control in prose", (v) => { v.report.headline.text = "Bad\u0000text"; }],
    ["section ordering", (v) => { v.report.sections.reverse(); }],
    ["missing section", (v) => { v.report.sections.pop(); }],
    ["empty section", (v) => { v.report.sections[0].paragraphs = []; }],
    ["too many paragraphs", (v) => { v.report.sections[0].paragraphs = Array(3).fill(v.report.sections[0].paragraphs[0]); }],
    ["response before start", (v) => { v.provenance.observed_at = "2026-09-15T23:00:00Z"; }],
    ["generated before response", (v) => { v.generated_at = v.provenance.started_at; }],
    ["naive timestamp", (v) => { v.generated_at = "2026-09-16T01:01:00"; }],
    ["calendar rollover", (v) => { v.generated_at = "2026-02-30T01:01:00Z"; }],
    ["invalid hour", (v) => { v.generated_at = "2026-09-16T24:01:00Z"; }],
  ];
  it.each(mutations)("rejects %s", (_label, change) => {
    const value = createOracleMarketBriefFixture(); change(value);
    expect(() => validateOracleMarketBrief(value)).toThrow(/Oracle market brief|artifact|source/);
  });
});
