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
import "./mobile.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Register the service worker (app-shell cache + push). Served by Django at
// /m/sw.js with Service-Worker-Allowed:/m/ so its scope covers the app.
// Not under a sister instance's path prefix: that worker would be the main
// instance's and would push the wrong company's approvals.
if ("serviceWorker" in navigator && !/^\/marine(\/|$)/.test(window.location.pathname)) {
  window.addEventListener("load", () => {
    navigator.serviceWorker
      .register("/m/sw.js", { scope: "/m/" })
      .catch(() => {
        /* offline shell is a progressive enhancement — ignore failures */
      });
  });
}
