export function SkeletonCabinet() {
  return (
    <section className="stack">
      <article className="panel skeleton-panel">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-line" />
      </article>
      <article className="panel skeleton-panel">
        <div className="skeleton-grid">
          <div className="skeleton skeleton-stat" />
          <div className="skeleton skeleton-stat" />
          <div className="skeleton skeleton-stat" />
        </div>
      </article>
      <article className="panel skeleton-panel">
        <div className="skeleton skeleton-line" />
        <div className="skeleton skeleton-line short" />
      </article>
    </section>
  );
}