// The ui-b components' public exports. Pages import from '@/components/ui-b', not from the files.
//
// Lists and cards, feedback, modals, tooltips, toasts and the stepper's steps. Controls (buttons,
// toggles, pills, menus, the card badge) are ui-a's: rows and cards take them as slots (`toggle`,
// `status`, `menu`, `action`, `footer`), so pages pass ui-a's components in.
//
// Icons follow ui-a's rules (src/components/ui-a/index.ts). Shared conventions here:
// - Cover art goes through <Cover>: an image with a placeholder tile when there's none.
// - Live regions: Alert and Banner are role="alert" when red, role="status" otherwise; toasts are
//   announced through <ToastViewport>.

// Covers, cards and rows
export { Cover, type CoverKind, type CoverProps } from './Cover.tsx';
export { Card, type CardProps, type CardTracking } from './Card.tsx';
export { ListTable, type ListTableProps } from './ListTable.tsx';
export { PlaylistRow, type PlaylistRowProps } from './PlaylistRow.tsx';
export { PlaylistHeader } from './PlaylistHeader.tsx';
export { AlbumRow, type AlbumRowProps } from './AlbumRow.tsx';
export { AlbumHeader } from './AlbumHeader.tsx';
export { TrackRow, type TrackRowProps } from './TrackRow.tsx';
export { TrackHeader } from './TrackHeader.tsx';
export { TrackStatus, type TrackStatusKind, type TrackStatusProps } from './TrackStatus.tsx';
export { ItemRow, type ItemRowProps } from './ItemRow.tsx';
export { RowTitle, type RowTitleProps } from './RowTitle.tsx';
export { EmptyState, type EmptyStateProps } from './EmptyState.tsx';

// Feedback
export { Progress, type ProgressProps } from './Progress.tsx';
export { LevelMeter, type LevelMeterProps } from './LevelMeter.tsx';
export { LiveLevelMeter, SILENCE_AFTER_MS, type LiveLevelMeterProps } from './LiveLevelMeter.tsx';
export { litSegments, SEGMENTS, FLOOR_DBFS, WARN_FROM_SEGMENT } from './level-scale.ts';
export { Alert, type AlertProps, type AlertTone } from './Alert.tsx';
export { Banner, type BannerAction, type BannerProps, type BannerTone } from './Banner.tsx';
export { Toast, type ToastProps } from './Toast.tsx';
export { ToastProvider } from './ToastProvider.tsx';
export { ToastViewport } from './ToastViewport.tsx';
export { useToast } from './use-toast.ts';
export { TOAST_DURATION_MS, type ToastOptions, type ToastActions } from './toast-context.ts';
export { Tooltip, type TooltipProps } from './Tooltip.tsx';
export { TooltipBubble, type TooltipBubbleProps } from './TooltipBubble.tsx';

// Modals and the wizard
export { focusableIn } from './focusable.ts';
export { Modal, type ModalProps } from './Modal.tsx';
export { ModalBox, type ModalBoxProps } from './ModalBox.tsx';
export { ConfirmDialog, type ConfirmDialogProps } from './ConfirmDialog.tsx';
export { StepperStep, type StepperStepProps, type StepperStepState } from './StepperStep.tsx';
