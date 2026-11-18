// The ui-c components: parts S8's pages share that S7 didn't build. Pages import them from
// '@/components/ui-c', not from the files. Each is drawn in every state at /gallery ("Pages:
// shared parts"). Icons and states follow ui-a's rules (src/components/ui-a/index.ts).
//
// - ChoiceCardGroup, ChoiceCard, ChoiceCount: the large choice cards of wizard steps 7 and 8, and
//   the compact format cards of step 6. A radio group.
// - Disclosure: "More formats" (step 6 inline; Settings › Recording as a row).
// - InsertChips + useInsertAtCursor: the Edit layout modal's "Insert:" chips.
// - StatusButton: Settings › Spotify account's joined "OK | Reconnect".
// - DetailHeader: the top of the Library's and Albums' detail views.
// - OutcomePill: a run's outcome (History, the Dashboard's Last run).
// - VncView: the client's screen through noVNC (wizard steps 3 and 4, the Player).
//
// Menus drawn on top of the page are ui-a's MenuButton and SplitButton themselves: their list
// is a portal now, so no parent clips it.

export { ChoiceCard, ChoiceCardGroup, ChoiceCount, type ChoiceCardGroupProps, type ChoiceCardProps } from './ChoiceCard.tsx';
export { Disclosure, type DisclosureProps } from './Disclosure.tsx';
export { InsertChips, type InsertChipsProps } from './InsertChips.tsx';
export { useInsertAtCursor } from './use-insert-at-cursor.ts';
export { StatusButton, type StatusButtonProps } from './StatusButton.tsx';
export { DetailHeader, type DetailHeaderProps } from './DetailHeader.tsx';
export { OutcomePill } from './OutcomePill.tsx';
export { VncView, VNC_TRIES, vncUrl, type VncState, type VncViewProps } from './VncView.tsx';
