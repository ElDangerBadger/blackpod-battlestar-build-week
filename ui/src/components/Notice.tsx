import { useModalFocus } from "../scene/useModalFocus";

export function Notice({ title, children, onClose }: { title: string; children: React.ReactNode; onClose: () => void }) {
  const modalFocus = useModalFocus();
  return (
    <div {...modalFocus} className="notice-layer" role="dialog" aria-modal="true" aria-labelledby="notice-title">
      <button className="book-focus-scrim" type="button" aria-hidden="true" tabIndex={-1} onClick={onClose} />
      <section className="cabin-notice">
        <p className="eyebrow">Build Week presentation</p>
        <h2 id="notice-title">{title}</h2>
        <div>{children}</div>
        <button type="button" onClick={onClose} autoFocus>Return to bridge</button>
      </section>
    </div>
  );
}
