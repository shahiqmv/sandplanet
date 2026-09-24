import React from "react";
import ReactDOM from "react-dom/client";
// Self-hosted fonts (design brief: island bandwidth — no CDN)
import "@fontsource/barlow-condensed/600.css";
import "@fontsource/barlow-condensed/700.css";
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import App from "./App.jsx";
import ErrorBoundary from "../ErrorBoundary.jsx";
import "../index.css";
import "./trading.css";

// Sand Planet Trading — the trading arm's own app (TRADING_BUILD_BRIEF.md
// §5). Same server, same session, same API origin as Planet; its own entry,
// its own navigation, and nothing of the project world on screen.
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
