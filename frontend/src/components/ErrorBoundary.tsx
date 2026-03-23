import { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}
interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        this.props.fallback ?? (
          <div className="min-h-screen flex items-center justify-center bg-surface p-6">
            <div className="card max-w-2xl w-full space-y-4 border border-danger/40">
              <h2 className="text-sm font-semibold text-danger">⚠ Runtime Error</h2>
              <pre className="text-xs text-slate-300 bg-slate-900 rounded p-3 overflow-auto max-h-60 whitespace-pre-wrap">
                {this.state.error.message}
              </pre>
              <pre className="text-xs text-muted overflow-auto max-h-40 whitespace-pre-wrap">
                {this.state.error.stack}
              </pre>
              <button
                className="text-xs px-4 py-2 rounded border border-accent text-accent hover:bg-accent/10"
                onClick={() => this.setState({ error: null })}
              >
                Try again
              </button>
            </div>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
