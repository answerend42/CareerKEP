import React from "react";
import ReactDOM from "react-dom/client";

import { AppShell } from "./app/AppShell";
import "./app/styles/tokens.css";
import "./app/styles/globals.css";
import "./app/styles/motion.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <AppShell />
  </React.StrictMode>,
);
