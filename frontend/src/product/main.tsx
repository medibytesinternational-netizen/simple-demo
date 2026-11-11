import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./styles/tokens.css";

const root = document.getElementById("product-root");
if (!root) throw new Error("Missing #product-root element");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
