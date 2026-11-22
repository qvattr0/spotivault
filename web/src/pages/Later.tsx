import { Page, PageHeader } from '@/shell';

/**
 * A page that isn't in M1 (plan § Scope: the Schedule page, History's Tracks tab). Its route
 * stays, as web-ui.md § Routes lists it, but nothing links to it.
 */
export function Later({ title }: { title: string }) {
  return (
    <Page>
      <PageHeader title={title} />
      <p className="text-sub">This page isn&apos;t in this version of spotivault yet.</p>
    </Page>
  );
}
