import { SHEET_SECTIONS, sheetSection } from './sheet.ts';
import type { GallerySection } from './types.ts';

/**
 * The groups' sections as the gallery shows them:
 * - sections of the same sheet section become one, under the sheet's title and id: 'Feedback'
 *   and 'Feedback · Status pill' from two groups make one Feedback section;
 * - other sections with the same title become one too, under the first one's id;
 * - they follow the component sheet's order, with its node ids (the screenshots pair by them);
 * - sections the sheet doesn't have come last, in the order given.
 */
export function arrangeSections(sections: GallerySection[]): GallerySection[] {
  const byTitle = new Map<string, GallerySection>();
  for (const section of sections) {
    const sheet = sheetSection(section.title);
    const title = sheet?.title ?? section.title;
    const key = title.trim().toLowerCase();
    const seen = byTitle.get(key);
    byTitle.set(
      key,
      seen
        ? { ...seen, node: seen.node ?? section.node, entries: [...seen.entries, ...section.entries] }
        : { ...section, id: sheet?.id ?? section.id, title, node: sheet?.node ?? section.node },
    );
  }

  const place = (section: GallerySection) => {
    const sheet = sheetSection(section.title);
    return sheet ? SHEET_SECTIONS.indexOf(sheet) : SHEET_SECTIONS.length;
  };
  // Array.sort is stable, so sections off the sheet keep their order.
  return [...byTitle.values()].sort((a, b) => place(a) - place(b));
}
