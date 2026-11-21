// Short names for the contract's schemas, so code can write `Setup` instead of
// `components['schemas']['Setup']`. All of them come from the generated schema.ts.

import type { components } from './schema.ts';

export type Schemas = components['schemas'];

export type ErrorBody = Schemas['Error'];
export type ErrorCode = Schemas['ErrorCode'];

// Setup and the client
export type Setup = Schemas['Setup'];
export type SetupStepId = Schemas['SetupStepId'];
export type ClientStatus = Schemas['ClientStatus'];
export type ClientInstall = Schemas['ClientInstall'];
export type Checklist = Schemas['Checklist'];
export type ChecklistRow = Schemas['ChecklistRow'];

// Spotify Web API connection
export type Connection = Schemas['Connection'];
export type Devices = Schemas['Devices'];
export type AuthStart = Schemas['AuthStart'];

// Settings and storage
export type Settings = Schemas['Settings'];
export type Layout = Schemas['Layout'];
export type Format = Schemas['Format'];
export type SettingsUpdate = Schemas['SettingsUpdate'];
export type Storage = Schemas['Storage'];
export type Container = Schemas['Container'];

// Library and Albums
export type LibraryItem = Schemas['LibraryItem'];
export type LibraryKind = Schemas['LibraryKind'];
export type ItemProgress = Schemas['ItemProgress'];
export type LibraryStatus = Schemas['LibraryStatus'];
export type LibrarySummary = Schemas['LibrarySummary'];
export type LibraryRefresh = Schemas['LibraryRefresh'];
export type PlaylistPreview = Schemas['PlaylistPreview'];
export type TrackList = Schemas['TrackList'];
export type ItemTrack = Schemas['ItemTrack'];
export type TrackState = Schemas['TrackState'];
export type Album = Schemas['Album'];
export type AlbumStatus = Schemas['AlbumStatus'];
export type AlbumsSummary = Schemas['AlbumsSummary'];
export type SavedAlbum = Schemas['SavedAlbum'];

// Runs, the Dashboard and History
export type Status = Schemas['Status'];
export type RunState = Schemas['RunState'];
export type RunSummary = Schemas['RunSummary'];
export type Trigger = Schemas['Trigger'];
export type Outcome = Schemas['Outcome'];
export type Counters = Schemas['Counters'];
export type PausedReason = Schemas['PausedReason'];
export type QueueItem = Schemas['QueueItem'];
export type ItemState = Schemas['ItemState'];
export type NowPlaying = Schemas['NowPlaying'];
export type SessionState = Schemas['SessionState'];
export type CurrentRun = Schemas['CurrentRun'];
export type RunTrack = Schemas['RunTrack'];
export type RunTrackState = Schemas['RunTrackState'];
export type Backlog = Schemas['Backlog'];
export type HistoryRow = Schemas['HistoryRow'];
export type RunDetail = Schemas['RunDetail'];
export type RunItem = Schemas['RunItem'];
export type ItemBadge = Schemas['ItemBadge'];
export type RunCreated = Schemas['RunCreated'];
export type TrackResult = Schemas['TrackResult'];
export type LastRun = Schemas['LastRun'];

// Schedule
export type Schedule = Schemas['Schedule'];
export type ScheduleNext = Schemas['ScheduleNext'];
export type Hours = Schemas['Hours'];

// System
export type Health = Schemas['Health'];
export type WebApiUsage = Schemas['WebApiUsage'];
