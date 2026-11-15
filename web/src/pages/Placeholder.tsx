/**
 * Stands in for a page until S8 builds it. Says which spec section and which drawings it follows.
 */
export function Placeholder({ title, spec, frames }: { title: string; spec: string; frames?: string }) {
  return (
    <section>
      <h1 className="type-page-title">{title}</h1>
      <p className="text-sub" style={{ marginTop: 'var(--s-4)' }}>
        Placeholder. Spec: docs/web-ui.md § {spec}.
        {frames ? ` Drawings: ${frames}.` : ''}
      </p>
    </section>
  );
}
