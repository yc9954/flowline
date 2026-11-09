import { Component, type ErrorInfo, type ReactNode } from 'react';

interface State { error: Error | null }

/** Keeps a page crash on one page: the sidebar stays, and the error is printed in plain words. */
export class ErrorBoundary extends Component<{ children: ReactNode; name?: string }, State> {
  state: State = { error: null };
  static getDerivedStateFromError(error: Error): State { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error('[board] render error', error, info.componentStack); }
  componentDidUpdate(prev: { children: ReactNode }) { if (prev.children !== this.props.children && this.state.error) this.setState({ error: null }); }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="main">
        <div style={{ padding: '40px 0', maxWidth: 640 }}>
          <div className="label">This page could not render</div>
          <h1 className="headline" style={{ fontSize: 24 }}>{this.state.error.message}</h1>
          <pre className="mono" style={{ fontSize: 11, color: 'var(--muted)', whiteSpace: 'pre-wrap', marginTop: 12 }}>{this.state.error.stack}</pre>
        </div>
      </main>
    );
  }
}
