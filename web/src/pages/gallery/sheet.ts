// The component sheet, frame E3ZmN in the .pen file, exported as web/design-reference/E3ZmN.png.
// The gallery shows its sections in this order, and the screenshot report crops the PNG with these
// boxes to set each section beside the gallery's own.
//
// Plain data with no imports: the e2e tests and the report script (Node) read it too.

/** The sheet's node id, which is also its PNG's name. */
export const SHEET_NODE = 'E3ZmN';

/** The sheet's size in CSS px. The PNG is twice this (4800 × 6544). */
export const SHEET_SIZE = { width: 2400, height: 3272 };

export interface SheetSection {
  /** The gallery's anchor for it: 'lists-and-cards'. */
  id: string;
  /** The heading on the sheet, in title case: 'Lists and cards'. */
  title: string;
  /** The section's node id (components.md gives each one). */
  node: string;
  /** Where the section sits on the sheet, in CSS px, with a 24 px margin round its content. */
  box: { x: number; y: number; width: number; height: number };
}

// Boxes measured from E3ZmN.png on 15 Nov 2026: the content's extent, plus 24 px.
export const SHEET_SECTIONS: SheetSection[] = [
  { id: 'brand', title: 'Brand', node: 'MpMbq', box: { x: 40, y: 172, width: 956, height: 320 } },
  { id: 'tokens', title: 'Tokens', node: 'QLSnE', box: { x: 40, y: 504, width: 1972, height: 334 } },
  { id: 'controls', title: 'Controls', node: 'HkFM1', box: { x: 40, y: 849, width: 1228, height: 328 } },
  { id: 'navigation', title: 'Navigation', node: 'q1BBn8', box: { x: 40, y: 1186, width: 1620, height: 910 } },
  { id: 'feedback', title: 'Feedback', node: 'WHUDG', box: { x: 40, y: 2125, width: 1304, height: 268 } },
  { id: 'lists-and-cards', title: 'Lists and cards', node: 'pm5tD', box: { x: 40, y: 2403, width: 1488, height: 829 } },
];

/**
 * The sheet section a gallery section belongs to, by its title in any case: 'Feedback', or a
 * part of it such as 'Feedback · Status pill'. Undefined when the sheet has no such section.
 */
export function sheetSection(title: string): SheetSection | undefined {
  const wanted = title.split(' · ')[0].trim().toLowerCase();
  return SHEET_SECTIONS.find((section) => section.title.toLowerCase() === wanted);
}
