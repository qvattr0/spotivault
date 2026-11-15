import { describe, expect, it } from 'vitest';
import { arrangeSections } from './arrange.ts';
import type { GallerySection } from './types.ts';

function section(id: string, title: string, ...entries: string[]): GallerySection {
  return { id, title, entries: entries.map((e) => ({ id: e, title: e, render: () => e })) };
}

describe('arrangeSections', () => {
  it("follows the component sheet's order and fills in its node ids", () => {
    const arranged = arrangeSections([
      section('lists', 'Lists and cards', 'row'),
      section('tokens', 'Tokens', 'colour'),
      section('controls', 'Controls', 'button'),
    ]);
    expect(arranged.map((s) => [s.title, s.node])).toEqual([
      ['Tokens', 'QLSnE'],
      ['Controls', 'HkFM1'],
      ['Lists and cards', 'pm5tD'],
    ]);
  });

  it("merges the parts of a sheet section, in any case, under the sheet's title and id", () => {
    const [feedback, ...rest] = arrangeSections([
      section('status-pill', 'Feedback · Status pill', 'pill'),
      section('ui-b-feedback', 'FEEDBACK', 'progress', 'toast'),
    ]);
    expect(rest).toEqual([]);
    expect([feedback?.id, feedback?.title, feedback?.node]).toEqual(['feedback', 'Feedback', 'WHUDG']);
    expect(feedback?.entries.map((e) => e.id)).toEqual(['pill', 'progress', 'toast']);
  });

  it('merges other sections with the same title under the first id', () => {
    const [shell] = arrangeSections([section('shell', 'Shell', 'sidebar'), section('more', 'Shell', 'banner')]);
    expect([shell?.id, shell?.node]).toEqual(['shell', undefined]);
    expect(shell?.entries.map((e) => e.id)).toEqual(['sidebar', 'banner']);
  });

  it("puts sections the sheet doesn't have last, in the order given", () => {
    const arranged = arrangeSections([
      section('b', 'Screens', 'x'),
      section('a', 'Extras', 'y'),
      section('brand', 'Brand', 'logo'),
    ]);
    expect(arranged.map((s) => s.title)).toEqual(['Brand', 'Screens', 'Extras']);
    expect(arranged[1]?.node).toBeUndefined();
  });

  it("gives sheet sections the sheet's node, others their own, and leaves the groups' arrays alone", () => {
    const pill = { ...section('pill', 'Feedback · Status pill', 'pill'), node: 'n6C5Bb' };
    const more = section('more', 'Feedback', 'toast');
    const extra = { ...section('extra', 'Extras', 'x'), node: 'abc12' };
    const [feedback, extras] = arrangeSections([pill, more, extra]);
    expect(feedback?.node).toBe('WHUDG');
    expect(extras?.node).toBe('abc12');
    expect(pill.entries).toHaveLength(1);
    expect(more.entries).toHaveLength(1);
  });
});
