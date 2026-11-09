import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/globals.css";
import "./styles/document.css";

// Latin — variable fonts
import "@fontsource-variable/inter";
import "@fontsource-variable/geist-mono";
import "@fontsource/space-grotesk/500.css";

// Indic scripts — static weights 400/500/600/700 to match next/font config
import "@fontsource/noto-serif-devanagari/400.css";
import "@fontsource/noto-serif-devanagari/500.css";
import "@fontsource/noto-serif-devanagari/600.css";
import "@fontsource/noto-serif-devanagari/700.css";
import "@fontsource/noto-serif-bengali/400.css";
import "@fontsource/noto-serif-bengali/500.css";
import "@fontsource/noto-serif-bengali/600.css";
import "@fontsource/noto-serif-bengali/700.css";
import "@fontsource/noto-serif-tamil/400.css";
import "@fontsource/noto-serif-tamil/500.css";
import "@fontsource/noto-serif-tamil/600.css";
import "@fontsource/noto-serif-tamil/700.css";
import "@fontsource/noto-serif-telugu/400.css";
import "@fontsource/noto-serif-telugu/500.css";
import "@fontsource/noto-serif-telugu/600.css";
import "@fontsource/noto-serif-telugu/700.css";
import "@fontsource/noto-serif-kannada/400.css";
import "@fontsource/noto-serif-kannada/500.css";
import "@fontsource/noto-serif-kannada/600.css";
import "@fontsource/noto-serif-kannada/700.css";
import "@fontsource/noto-serif-gurmukhi/400.css";
import "@fontsource/noto-serif-gurmukhi/500.css";
import "@fontsource/noto-serif-gurmukhi/600.css";
import "@fontsource/noto-serif-gurmukhi/700.css";
import "@fontsource/noto-serif-gujarati/400.css";
import "@fontsource/noto-serif-gujarati/500.css";
import "@fontsource/noto-serif-gujarati/600.css";
import "@fontsource/noto-serif-gujarati/700.css";
import "@fontsource/noto-serif-oriya/400.css";
import "@fontsource/noto-serif-oriya/500.css";
import "@fontsource/noto-serif-oriya/600.css";
import "@fontsource/noto-serif-oriya/700.css";
import "@fontsource/noto-serif-malayalam/400.css";
import "@fontsource/noto-serif-malayalam/500.css";
import "@fontsource/noto-serif-malayalam/600.css";
import "@fontsource/noto-serif-malayalam/700.css";

const container = document.getElementById("root");
if (!container) throw new Error("Root element #root not found");

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
