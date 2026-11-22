// The ui-a components: controls, pills, the card badge and the logo. Pages import them from
// '@/components/ui-a', not from the files. Each is drawn in every state at /gallery.
//
// Icons (components.md § Icons), for every component here and the pages that use them:
// - Lucide, from lucide-react, by name: components.md's `circle-dot-dashed` is `CircleDotDashed`.
// - Size: the px components.md gives for that place (20 in Button/Icon, 16 in Secondary, ...).
//   Lucide's default stroke (2) and `currentColor`: colour an icon through its parent's `color`.
// - Decorative icons need nothing: lucide-react adds aria-hidden itself unless the icon gets an
//   aria-label or title. An icon-only control names itself (IconButton's `label`).
// - A prop that takes an icon takes the component, not an element: `icon={RefreshCw}`.
//
// States the drawings leave out (components.md § Differences, row 5) are ours and the same across
// these components: hover grows filled buttons 4 % or turns text white; pressed uses accent-press;
// disabled is 40 % opacity (as Continue is drawn on Setup 4 and 5); focus is base.css's white ring.
// `data-state="hover" | "active" | "focus"` draws a state without the mouse, for the gallery.

export type { LucideIcon as Icon } from 'lucide-react';

export { Button, type ButtonProps } from './Button.tsx';
export { ButtonLink, type ButtonLinkProps } from './ButtonLink.tsx';
export type { ButtonVariant } from './button-parts.tsx';
export { IconButton, type IconButtonProps } from './IconButton.tsx';
export { PlayButton, type PlayButtonProps } from './PlayButton.tsx';
export { SplitButton, type SplitButtonProps } from './SplitButton.tsx';

export { MenuButton, type MenuButtonProps } from './MenuButton.tsx';
export { MenuList, type MenuItem, type MenuListProps } from './MenuList.tsx';
export { useMenu } from './useMenu.ts';

export { TextInput, type TextInputProps } from './TextInput.tsx';
export { SearchInput, type SearchInputProps } from './SearchInput.tsx';
export { Select, type SelectOption, type SelectProps } from './Select.tsx';

export { Toggle, type ToggleProps } from './Toggle.tsx';
export { Checkbox, type CheckboxProps } from './Checkbox.tsx';
export { Chip, type ChipProps } from './Chip.tsx';
export { ChipGroup, type ChipGroupProps, type ChipOption } from './ChipGroup.tsx';
export { ChipLink, type ChipLinkProps } from './ChipLink.tsx';
export { SegmentedControl, type SegmentedControlProps, type SegmentOption } from './SegmentedControl.tsx';
export { ViewSwitch, type ViewMode, type ViewSwitchProps } from './ViewSwitch.tsx';
export { WeekCell, type WeekCellProps } from './WeekCell.tsx';

export { Pill, type PillProps, type PillTone } from './Pill.tsx';
export { TrackBadge, type TrackBadgeProps } from './TrackBadge.tsx';

export { Logo, type LogoProps } from './Logo.tsx';
export { Brand, type BrandProps } from './Brand.tsx';
