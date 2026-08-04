import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { CompanionApp } from "./components/CompanionApp";
import "./styles/companion.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <CompanionApp />
  </StrictMode>,
);

