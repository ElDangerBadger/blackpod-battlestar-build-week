export function Notice({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="notice-layer" role="dialog" aria-modal="true" aria-labelledby="notice-title">
      <button className="book-focus-scrim" type="button" aria-label="Close notice" onClick={onClose} />
      <section className="cabin-notice">
        <p className="eyebrow">Build Week presentation</p>
        <h2 id="notice-title">{title}</h2>
        <div>{children}</div>
        <button type="button" onClick={onClose}>Return to bridge</button>
      </section>
    </div>
  );
}
