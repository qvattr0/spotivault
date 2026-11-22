import { LayoutGrid, List } from 'lucide-react';
import { SegmentedControl, type SegmentOption } from './SegmentedControl.tsx';

export type ViewMode = 'list' | 'grid';

const VIEWS: SegmentOption<ViewMode>[] = [
  { value: 'list', label: 'List', icon: List },
  { value: 'grid', label: 'Grid', icon: LayoutGrid },
];

export interface ViewSwitchProps {
  value: ViewMode;
  onChange: (value: ViewMode) => void;
  className?: string;
}

/**
 * List / Grid for the Library and Albums (components.md § View switch). The page remembers the
 * choice per browser (web-ui.md § Library, Header).
 */
export function ViewSwitch({ value, onChange, className }: ViewSwitchProps) {
  return <SegmentedControl label="View" options={VIEWS} value={value} onChange={onChange} className={className} />;
}
