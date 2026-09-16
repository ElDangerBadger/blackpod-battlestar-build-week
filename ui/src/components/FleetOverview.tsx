import { useId, useState } from "react";
import { createRecordedFleetOverview, ORACLE_COVERAGE_LABELS } from "../data/fleetOverview";
import { missionRelativeUrl } from "../data/loadMission";
import { hasNavigatorCapture } from "../data/navigatorSelection";
import type { MissionViewModel } from "../data/viewModel";
import "./fleet-overview.css";

const candidates: Readonly<Record<string, string>> = {
  OBSERVE: "Observe", WATCH: "Watch", REVIEW: "Review", REJECT: "Reject",
};
function numeric(value: number | null, suffix = "") { return value === null ? "Not recorded" : `${value.toLocaleString("en-US", { maximumFractionDigits: 4 })}${suffix}`; }

export function FleetOverview({ mission, onOpenNavigator, onOpenReferenceTape }: {
  mission: MissionViewModel;
  onOpenNavigator?: (symbol: string) => void;
  onOpenReferenceTape?: (symbol: string) => void;
}) {
  const fleet = createRecordedFleetOverview(mission);
  const [filter, setFilter] = useState("");
  const filterId = useId();
  const query = filter.trim().toLowerCase();
  const visible = fleet.rows.filter((row) => `${row.symbol} ${ORACLE_COVERAGE_LABELS[row.coverage]} ${row.candidateState ?? ""}`.toLowerCase().includes(query));
  return <section className="fleet-overview" aria-label="Recorded fleet overview">
    <h3>Recorded fleet and analysis coverage</h3>
    <p>{fleet.source === "normalized"
      ? `${fleet.rows.length} observed symbols are listed in this mission's saved normalized snapshot.`
      : fleet.source === "fallback" ? "The normalized snapshot is unavailable. These symbols come from the available diagnostic and candidate records; prices are not substituted."
        : "No usable observed symbol list is available in the supplied mission evidence."}</p>
    <p>This is a saved analysis record—not your current Harbor registry, a portfolio, or a complete list of configured membership. The original fleet input is linked below when present; its membership is not reconstructed here.</p>
    <dl className="fleet-overview-meta">
      <div><dt>Recorded fleet ID</dt><dd>{fleet.fleetId ?? "Not recorded"}</dd></div>
      <div><dt>Snapshot as of</dt><dd>{fleet.observedAt ?? "Not recorded"}</dd></div>
      <div><dt>Navigator reference</dt><dd>{mission.market.navigatorMarket ? `${mission.market.navigatorMarket.symbol} · separate supplemental chart, not evidence that this symbol belongs to the Oracle fleet` : "No supplemental Navigator capture is attached to this mission."}</dd></div>
    </dl>
    {fleet.notes.length > 0 ? <ul className="fleet-overview-notes">{fleet.notes.map((note) => <li key={note}>{note}</li>)}</ul> : null}
    {fleet.rows.length > 0 ? <>
      <label htmlFor={filterId}>Filter recorded symbols and statuses</label>
      <input id={filterId} type="search" value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="Symbol or recorded status" autoComplete="off" />
      <p role="status" className="fleet-overview-count">Showing {visible.length} of {fleet.rows.length} recorded symbols. Filtering changes this view only.</p>
      <div className="fleet-overview-table-scroll" tabIndex={0} role="region" aria-label="Recorded fleet table">
        <table>
          <caption>Captured observations and separate Oracle/Council classifications</caption>
          <thead><tr><th scope="col">Symbol</th><th scope="col">Captured price</th><th scope="col">Recorded return</th><th scope="col">Oracle coverage</th><th scope="col">Candidate record</th>{onOpenNavigator || onOpenReferenceTape ? <th scope="col">Navigator reference</th> : null}</tr></thead>
          <tbody>{visible.map((row) => <tr key={row.symbol}>
            <th scope="row">{row.symbol}</th>
            <td>{numeric(row.price)}{row.timestamp ? <small>{row.timestamp}</small> : null}</td>
            <td>{numeric(row.returnPct, "%")}</td>
            <td>{ORACLE_COVERAGE_LABELS[row.coverage]}</td>
            <td>{row.candidateState ? Object.hasOwn(candidates, row.candidateState) ? candidates[row.candidateState] : row.candidateState : "Not recorded"}{row.candidateReasons.length ? <ul>{row.candidateReasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul> : null}</td>
            {onOpenNavigator || onOpenReferenceTape ? <td><div className="fleet-overview-actions">
              {onOpenReferenceTape ? <button type="button" onClick={() => onOpenReferenceTape(row.symbol)} aria-label={`View ${row.symbol} reference tape`} aria-haspopup="dialog">View details</button> : null}
              {hasNavigatorCapture(mission, row.symbol)
                ? onOpenNavigator ? <button type="button" onClick={() => onOpenNavigator(row.symbol)} aria-label={`Review ${row.symbol} in Navigator`}>Review chart</button> : null
                : <span>No chart capture</span>}
            </div></td> : null}
          </tr>)}</tbody>
        </table>
        {visible.length === 0 ? <p>No recorded symbols match this filter.</p> : null}
      </div>
      <p className="fleet-overview-boundary">Prices and returns retain their source units; no currency, quote freshness, or missing values are inferred. Oracle exclusions do not mean a symbol was absent from the capture. Candidate labels are review classifications, not buy/sell instructions.</p>
    </> : null}
    {fleet.links.length > 0 ? <section aria-label="Fleet source evidence"><h4>Original saved evidence</h4><ul>{fleet.links.map(({ label, reference }) => <li key={reference.name}><a href={missionRelativeUrl(mission.baseUrl, reference.path)} target="_blank" rel="noreferrer">{label}</a></li>)}</ul></section> : null}
    <p className="fleet-overview-boundary">Read-only: viewing and filtering this list does not add or remove symbols, refresh data, or authorize trading. {onOpenNavigator ? "Review chart opens separately captured Navigator history; its prices and capture time can differ from this saved fleet snapshot." : "Filtering does not change the reference chart."}</p>
  </section>;
}
