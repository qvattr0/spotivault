import { Link } from 'react-router';

export function NotFound() {
  return (
    <section style={{ padding: 'var(--s-8)' }}>
      <h1 className="type-page-title">Page not found</h1>
      <p className="text-sub" style={{ marginTop: 'var(--s-4)' }}>
        <Link to="/">Go to the Dashboard</Link>
      </p>
    </section>
  );
}
