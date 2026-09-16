import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useModalFocus } from "./useModalFocus";

function Dialog() {
  return <div {...useModalFocus()} role="dialog">
    <button type="button">Close</button>
    <details><summary>Recorded details</summary><a href="#evidence">Original evidence</a></details>
  </div>;
}

describe("modal disclosure keyboard containment", () => {
  it("includes the summary but skips links inside a closed disclosure", () => {
    render(<Dialog />);
    const close = screen.getByRole("button", { name: "Close" });
    const summary = screen.getByText("Recorded details");
    close.focus();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Tab", shiftKey: true });
    expect(summary).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Tab" });
    expect(close).toHaveFocus();
  });

  it("includes source links after the disclosure is expanded", () => {
    render(<Dialog />);
    const summary = screen.getByText("Recorded details");
    summary.closest("details")!.open = true;
    const close = screen.getByRole("button", { name: "Close" });
    close.focus();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Tab", shiftKey: true });
    expect(screen.getByRole("link", { name: "Original evidence" })).toHaveFocus();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Tab" });
    expect(close).toHaveFocus();
  });
});
