import { createRoot } from "react-dom/client";
import App from "./App";
import { installUiDiagnostics } from "./state/uiDiagnostics";
import "./tokens.css";
import "./app.css";
import "./layout/viewport.css";
import "./layout/management.css";
installUiDiagnostics();
createRoot(document.getElementById("root")!).render(<App />);
