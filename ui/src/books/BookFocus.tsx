import { useEffect, useRef, useState } from "react";

import type { BookDefinition } from "./bookPages";

type BookFocusProps = {
  book: BookDefinition;
  artifactBaseUrl: string;
  onClose: () => void;
};

export function BookFocus({ book, artifactBaseUrl, onClose }: BookFocusProps) {
  const [pageIndex, setPageIndex] = useState(0);
  const pageStrip = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setPageIndex(0);
    pageStrip.current?.scrollTo({ left: 0 });
  }, [book.id]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowLeft") goTo(pageIndex - 1);
      if (event.key === "ArrowRight") goTo(pageIndex + 1);
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  });

  const goTo = (nextIndex: number) => {
    const bounded = Math.max(0, Math.min(book.pages.length - 1, nextIndex));
    setPageIndex(bounded);
    const strip = pageStrip.current;
    if (strip) strip.scrollTo({ left: bounded * strip.clientWidth, behavior: "smooth" });
  };

  const syncPageFromScroll = () => {
    const strip = pageStrip.current;
    if (!strip || strip.clientWidth === 0) return;
    setPageIndex(Math.round(strip.scrollLeft / strip.clientWidth));
  };

  return (
    <div className="book-focus-layer" role="dialog" aria-modal="true" aria-labelledby="book-focus-title">
      <button className="book-focus-scrim" type="button" aria-label="Return to cabin" onClick={onClose} />
      <article className="book-focus" style={{ "--book-accent": book.accent } as React.CSSProperties}>
        <header className="book-focus-header">
          <div>
            <p className="eyebrow">Mission record · {book.state}</p>
            <h2 id="book-focus-title">{book.title}</h2>
            <p>{book.subtitle}</p>
          </div>
          <button className="book-close" type="button" onClick={onClose} aria-label="Return to full cabin">
            Return to cabin <span aria-hidden="true">×</span>
          </button>
        </header>

        <div className="book-page-strip" ref={pageStrip} onScroll={syncPageFromScroll}>
          {book.pages.map((page, index) => (
            <section className="book-page" key={page.id} aria-label={`${book.title}: ${page.title}`}>
              <div className="book-page-copy">
                {page.eyebrow ? <p className="eyebrow">{page.eyebrow}</p> : null}
                <h3>{page.title}</h3>
                {page.content}
              </div>
              {page.evidencePaths?.length ? (
                <footer className="evidence-links">
                  <span>Canonical evidence</span>
                  {page.evidencePaths.map((path) => (
                    <a key={path} href={`${artifactBaseUrl}${path}`} target="_blank" rel="noreferrer">
                      {path.split("/").at(-1)}
                    </a>
                  ))}
                </footer>
              ) : null}
              <span className="page-folio" aria-hidden="true">{index + 1}</span>
            </section>
          ))}
        </div>

        <footer className="book-pagination">
          <button type="button" onClick={() => goTo(pageIndex - 1)} disabled={pageIndex === 0}>
            Previous
          </button>
          <span aria-live="polite">Page {pageIndex + 1} of {book.pages.length}</span>
          <button type="button" onClick={() => goTo(pageIndex + 1)} disabled={pageIndex === book.pages.length - 1}>
            Next
          </button>
        </footer>
        <p className="focus-safety-line">Navigator SHADOW handoff only — no trade or order execution.</p>
      </article>
    </div>
  );
}
