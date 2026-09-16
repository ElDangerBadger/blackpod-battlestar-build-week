import { useEffect, useRef, type KeyboardEvent } from "react";

const FOCUSABLE = 'button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], summary, [tabindex]';

function insideClosedDetails(element: HTMLElement): boolean {
  for (let details = element.closest("details:not([open])"); details;
    details = details.parentElement?.closest("details:not([open])") ?? null) {
    if (!details.querySelector(":scope > summary")?.contains(element)) return true;
  }
  return false;
}

function focusableElements(dialog: HTMLElement): HTMLElement[] {
  return Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((element) => (
    element.tabIndex >= 0
    && !element.closest('[hidden], [inert], [aria-hidden="true"]')
    && !insideClosedDetails(element)
    && getComputedStyle(element).display !== "none"
    && getComputedStyle(element).visibility !== "hidden"
  ));
}

/** Keyboard containment complements the scene's inert background. */
export function useModalFocus() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    const containFocus = () => {
      if (!dialog.isConnected) return;
      if (!dialog.contains(document.activeElement)) {
        (focusableElements(dialog)[0] ?? dialog).focus();
      }
    };
    containFocus();
    document.addEventListener("focusin", containFocus);
    return () => document.removeEventListener("focusin", containFocus);
  }, []);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Tab" || !ref.current) return;
    const dialog = ref.current;
    const elements = focusableElements(dialog);
    const first = elements[0];
    const last = elements.at(-1);
    if (!first || !last) {
      event.preventDefault();
      dialog.focus();
      return;
    }
    const active = document.activeElement;
    if (event.shiftKey && (active === first || !elements.includes(active as HTMLElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !elements.includes(active as HTMLElement))) {
      event.preventDefault();
      first.focus();
    }
  };

  return { ref, onKeyDown, tabIndex: -1 };
}
