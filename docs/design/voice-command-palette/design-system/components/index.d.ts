// Traceback voice-panel bundle — documentation only, not type-checked.

declare namespace Traceback {
  /** Renders the app shell (topbar + sidebar + content) into `el`; returns the content slot element. */
  function shell(el: HTMLElement, opts: { active?: string; hintLabel?: string; bodyHtml?: string }): HTMLElement;

  function bodyTasksOverdue(): string;
  function bodyProjects(opts?: { opened?: string }): string;
  function bodyInbox(): string;

  /** The floating voice-command panel, one function per state. Each returns a positioned `.tb-panel-dock` block. */
  function panelIdle(): string;
  function panelRecording(seconds: number): string;
  function panelProcessing(query: string, note: string): string;
  function panelResult(opts: { title: string; count: number; rows: [string, string][]; primary?: string }): string;
  function panelMultiple(opts: { title: string; count: number; rows: [string, string][]; hint?: string }): string;
  function panelAmbiguity(opts: { query: string; title: string; rows: [string, string][] }): string;
  function panelConfirm(text: string): string;
  function panelNoResults(query: string): string;
  function panelUnavailable(opts: { title: string; detail: string }): string;
  function panelPermission(): string;
  function panelCancelled(): string;

  function notification(opts: { title: string; body: string; action?: string }): string;
  function desktopScene(el: HTMLElement, opts: { notificationHtml?: string }): void;
}
