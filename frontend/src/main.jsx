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
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Planet Desktop: register the service worker that makes the app installable
// (own window + Dock icon) and delivers desktop push. Served by Django at
// /sw.js with Service-Worker-Allowed:/ — the Vite dev server has no such
// route, so only the built app registers.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
      /* installability is a progressive enhancement — ignore failures */
    });
  });
}
