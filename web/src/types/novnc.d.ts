// Types for @novnc/novnc, which ships none. Only what the UI uses; add to it as needed.
// The API is documented in node_modules/@novnc/novnc/docs/API.md.

declare module '@novnc/novnc' {
  export interface RFBOptions {
    shared?: boolean;
    credentials?: { username?: string; password?: string; target?: string };
    repeaterID?: string;
    wsProtocols?: string[];
  }

  export default class RFB extends EventTarget {
    /** Connects at once. `url` is the WebSocket address, here ws(s)://<host>/vnc. */
    constructor(target: HTMLElement, urlOrChannel: string | WebSocket, options?: RFBOptions);
    /** Ignore mouse and keyboard: the Player's view-only mode during a run. */
    viewOnly: boolean;
    /** Scale the remote screen to fit the element ("Fit"). False is 100 %. */
    scaleViewport: boolean;
    /** Ask the server to resize to the element. */
    resizeSession: boolean;
    /** Clip instead of scale, with scrollbars when it's larger. */
    clipViewport: boolean;
    focusOnClick: boolean;
    background: string;
    qualityLevel: number;
    compressionLevel: number;
    showDotCursor: boolean;
    readonly capabilities: { power: boolean };
    disconnect(): void;
    focus(options?: FocusOptions): void;
    blur(): void;
  }
}
