import type { NavigatorMarket } from "../contracts/cabinContext";
import type { NavigatorMarketVariant } from "../contracts/navigatorCatalog";
import type { ArtifactReference } from "../contracts/presentation";
import type { MissionViewModel } from "./viewModel";

export type NavigatorCaptureSelection = Pick<NavigatorMarket, "symbol" | "timeframe" | "ma_period">;

export type NavigatorCaptureChoice = Readonly<{
  market: NavigatorMarket;
  capturedAt: string | null;
  sourceIdentity: string | null;
  reference: ArtifactReference | null;
  navigatorGitRevision: string | null;
  navigatorSourceSha256?: string;
  navigatorWorktreeDirty?: boolean;
  original: boolean;
}>;

/** Validated presentation captures only; local watchlist labels are not datasets. */
export function navigatorVariants(mission: MissionViewModel): readonly NavigatorMarketVariant[] {
  return [...(mission.market.navigatorVariants ?? []), ...(mission.market.navigatorFleetVariants ?? [])];
}

/** Selection metadata wraps the supplied market/reference objects without rewriting them. */
export function navigatorCaptures(mission: MissionViewModel): readonly NavigatorCaptureChoice[] {
  const original = mission.market.navigatorMarket;
  return [
    ...(original ? [{
      market: original,
      capturedAt: mission.market.capturedAt,
      sourceIdentity: mission.market.sourceIdentity,
      reference: mission.market.artifactReference ?? null,
      // The presentation view model does not carry the original capture revision.
      navigatorGitRevision: null,
      original: true,
    }] : []),
    ...navigatorVariants(mission).map((variant) => ({ ...variant, original: false })),
  ];
}

export function navigatorCaptureKey(selection: NavigatorCaptureSelection): string {
  return `${selection.symbol}:${selection.timeframe}:${selection.ma_period}`;
}

/** Prefer a supplied pair, then interval, then daily MA250, within this symbol only. */
export function chooseNavigatorCapture(
  captures: readonly NavigatorCaptureChoice[],
  symbol: string,
  preferred?: Pick<NavigatorCaptureSelection, "timeframe" | "ma_period">,
): NavigatorCaptureChoice | undefined {
  const available = captures.filter((choice) => choice.market.symbol === symbol);
  return (preferred && available.find(({ market }) => market.timeframe === preferred.timeframe && market.ma_period === preferred.ma_period))
    ?? (preferred && available.find(({ market }) => market.timeframe === preferred.timeframe))
    ?? available.find(({ market }) => market.timeframe === "1d" && market.ma_period === 250)
    ?? available[0];
}

export function hasNavigatorCapture(mission: MissionViewModel, symbol: string): boolean {
  const original = mission.market.navigatorMarket;
  return original !== null && (original.symbol === symbol || navigatorVariants(mission).some((entry) => entry.market.symbol === symbol));
}
