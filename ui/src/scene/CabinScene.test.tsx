import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CabinScene } from "./CabinScene";

describe("CabinScene", () => {
  it("lets Vite resolve the cabin artwork instead of overriding it from an inline CSS variable", () => {
    render(<CabinScene />);

    const scene = screen.getByRole("region", {
      name: "BlackPod Battlestar Captain's Cabin mission presentation",
    });
    expect(scene.style.getPropertyValue("--cabin-background")).toBe("");
    expect(scene).not.toHaveAttribute("style");
  });
});
