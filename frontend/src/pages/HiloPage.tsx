import { MessageCircle, ScanFace } from "lucide-react";
import { useState } from "react";

import { ChatPanel } from "../components/ChatPanel";
import { FacePanel } from "../components/FacePanel";

type Mode = "chat" | "cara";

export function HiloPage() {
  const [mode, setMode] = useState<Mode>("chat");

  return (
    <section className="console-page" aria-label="El hilo con Vibi">
      <div className="console-switch" role="tablist" aria-label="Modo de conversación">
        <button
          role="tab"
          aria-selected={mode === "chat"}
          className={`console-switch-tab${mode === "chat" ? " is-active" : ""}`}
          onClick={() => setMode("chat")}
        >
          <MessageCircle size={16} /> Chat
        </button>
        <button
          role="tab"
          aria-selected={mode === "cara"}
          className={`console-switch-tab${mode === "cara" ? " is-active" : ""}`}
          onClick={() => setMode("cara")}
        >
          <ScanFace size={16} /> Cara
        </button>
      </div>

      {mode === "chat" ? <ChatPanel /> : <FacePanel />}
    </section>
  );
}
