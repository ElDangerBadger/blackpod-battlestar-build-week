import type { NavigatorMarket } from "../contracts/cabinContext";

/** Display supplied capture metadata only; cache age is not quote freshness. */
export function NavigatorMarketProvenance({ market }: { market: Pick<NavigatorMarket, "data" | "disclaimer"> }) {
  return (
    <div aria-label="Navigator market provenance">
      <p>
        {market.data ? (
          <>
            Provider: {market.data.provider} · Source: {market.data.source} · {market.data.stale ? "STALE at capture" : "Not stale at capture"}
            {" · "}Provider cache age at capture: {market.data.age_seconds}s. This is not a streaming quote.
          </>
        ) : "Provider/cache provenance was not recorded in this capture. This is not a streaming quote."}
      </p>
      {market.disclaimer ? <p>{market.disclaimer}</p> : null}
    </div>
  );
}
