import { Component } from "react";
import { buttonStyle, card, ghostButton } from "./ui.jsx";

/* A crash in one screen used to blank the entire app — nav, header and all —
 * leaving nothing on screen and nothing to report but "it went white" (owner
 * 2026-09-09). Now the failure is contained and legible: the rest of the app
 * keeps working, and the message says what broke so it can be fixed rather
 * than guessed at.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    // Still log it: the console is where a developer looks first.
    console.error("Screen crashed:", error, info?.componentStack);
  }

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;
    const where = this.props.label ? ` on ${this.props.label}` : "";
    return (
      <section style={{ ...card, borderLeft: "3px solid #c0392b" }}>
        <h3 style={{ margin: "0 0 4px", color: "#c0392b", fontSize: 16 }}>
          This screen hit a problem{where}
        </h3>
        <p style={{ margin: "0 0 10px", fontSize: 13, color: "#5a6b78" }}>
          Nothing you did is saved wrongly — the page simply failed to draw.
          The details below are what a fix needs.
        </p>
        <pre style={{ background: "#fbeaea", color: "#7d1f1f", padding: 10,
                      borderRadius: 6, fontSize: 12, whiteSpace: "pre-wrap",
                      overflowX: "auto", margin: 0 }}>
{/* Safari's and Firefox's stacks carry no message line, so every report
    from the owner's Mac arrived as frames with the one line that names the
    fault missing (owner 2026-09-12). Message first, always. */}
{String(error?.message || error)}{"\n\n"}{String(error?.stack || "")}
{info?.componentStack ? `\n\nWhere:${info.componentStack}` : ""}
        </pre>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <button style={buttonStyle}
                  onClick={() => this.setState({ error: null, info: null })}>
            Try again</button>
          <button style={ghostButton}
                  onClick={() => window.location.reload()}>
            Reload the app</button>
          <button style={ghostButton}
                  onClick={() => navigator.clipboard?.writeText(
                    `${error?.message || error}\n\n${error?.stack || ""}`
                    + (info?.componentStack || ""))}>
            Copy the details</button>
        </div>
      </section>
    );
  }
}
