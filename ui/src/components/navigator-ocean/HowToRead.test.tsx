import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NavigatorMarketProvenance } from "../NavigatorMarketProvenance";
import { HowToRead } from "./HowToRead";

describe("Navigator consumer information panel", () => {
  it("keeps supplied provenance inside the existing scrollable help panel", () => {
    render(
      <HowToRead maPeriod={250}>
        <NavigatorMarketProvenance market={{
          data: { stale: true, age_seconds: 120.5, source: "disk", provider: "yfinance" },
          disclaimer: "Educational visualization only. Data may be delayed.",
        }} />
      </HowToRead>,
    );

    const panel = screen.getByRole("complementary", { name: "How to read the Navigator ocean" });
    expect(panel).toHaveClass("navigator-ocean__how-to");
    expect(within(panel).getByLabelText("Navigator market provenance")).toHaveTextContent("STALE at capture");
    expect(within(panel).getByLabelText("Navigator market provenance")).toHaveTextContent("120.5s");
    expect(within(panel).getByText(/Yellow bearing: supplied MA250/)).toBeInTheDocument();
  });
});
