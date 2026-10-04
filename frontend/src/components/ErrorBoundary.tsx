import { Component, type ErrorInfo, type ReactNode } from "react";

/** Top-level error boundary.
 *
 * There was none anywhere in the app, so any render throw — a malformed SVG
 * from a chart, bad markdown, an undefined field — replaced the entire UI with
 * a blank white screen with no way back short of a reload.
 *
 * Class component because that is still the only React API for this.
 */

/** One line for the user. Deliberately not the raw message. */
export function errorHeadline(_error: unknown): string {
  return "Something went wrong";
}

/** Detail line: what we were doing, plus the message if it is short and sane. */
export function describeError(error: unknown, context?: string): string {
  const where = context ? `while ${context}` : "in this view";
  let detail = "";
  if (error instanceof Error && error.message && error.message.length <= 200) {
    detail = ` (${error.message})`;
  } else if (typeof error === "string" && error.length <= 200) {
    detail = ` (${error})`;
  }
  return `The app hit an error ${where}${detail}.`;
}

interface Props {
  children: ReactNode;
  /** Shown in the fallback so the user knows which part broke. */
  context?: string;
}

interface State {
  error: unknown;
  /** Bumped on retry so a fresh subtree remounts instead of re-throwing. */
  attempt: number;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, attempt: 0 };

  static getDerivedStateFromError(error: unknown): Partial<State> {
    return { error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo): void {
    // Kept in the console rather than the UI: there is no backend to report to,
    // and the app is local-first by design.
    console.error("[fleeting] unhandled render error", error, info.componentStack);
  }

  private retry = (): void => {
    this.setState((s) => ({ error: null, attempt: s.attempt + 1 }));
  };

  render(): ReactNode {
    const { error, attempt } = this.state;
    if (error === null) {
      return <div key={attempt} className="contents">{this.props.children}</div>;
    }
    return (
      <div
        role="alert"
        className="flex min-h-0 flex-1 flex-col items-center justify-center gap-3 p-8 text-center"
      >
        <p className="text-sm font-semibold text-red-200">{errorHeadline(error)}</p>
        <p className="max-w-md text-xs text-ink-400">{describeError(error, this.props.context)}</p>
        <div className="flex items-center gap-2">
          <button
            onClick={this.retry}
            className="rounded-lg border border-white/10 bg-white/10 px-3 py-1.5 text-xs font-semibold text-white hover:bg-white/20"
          >
            Try again
          </button>
          <button
            onClick={() => window.location.reload()}
            className="rounded-lg border border-white/10 px-3 py-1.5 text-xs text-ink-300 hover:bg-white/5"
          >
            Reload app
          </button>
        </div>
        <p className="text-[11px] text-ink-500">
          Your notes are stored locally and are unaffected.
        </p>
      </div>
    );
  }
}