import { useModalFocus } from "../scene/useModalFocus";
import "./cabin-notices.css";

export function Notice({ title, children, onClose, eyebrow = "Read-only mission record" }: { title: string; children: React.ReactNode; onClose: () => void; eyebrow?: string }) {
  const modalFocus = useModalFocus();
  return (
    <div {...modalFocus} id="notice-dialog" className="notice-layer" role="dialog" aria-modal="true" aria-labelledby="notice-title">
      <button className="book-focus-scrim" type="button" aria-hidden="true" tabIndex={-1} onClick={onClose} />
      <section className="cabin-notice">
        <p className="eyebrow">{eyebrow}</p>
        <h2 id="notice-title">{title}</h2>
        <div className="cabin-notice__body">{children}</div>
        <button type="button" onClick={onClose} autoFocus>Return to bridge</button>
      </section>
    </div>
  );
}
