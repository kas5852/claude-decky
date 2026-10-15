import { DialogButton, Focusable } from "@decky/ui";
import { ReactElement, useState } from "react";
import { RiCameraLine, RiMicLine, RiTerminalLine } from "react-icons/ri";
import { AppState, Message, send, SHORTCUT_LABELS } from "../api";
import { BlockView, parseBlocks } from "../markdown";
import { patchStore } from "../store";
import { theme } from "../theme";

const SUGGESTIONS = [
  "What's using my battery?",
  "Check temps and power draw",
  "Why did my last game crash?",
  "Anything wrong in the logs since boot?",
];

function groupExchanges(messages: Message[]): Message[][] {
  const exchanges: Message[][] = [];
  for (const message of messages) {
    if (message.role === "user" || exchanges.length === 0) exchanges.push([]);
    exchanges[exchanges.length - 1].push(message);
  }
  return exchanges.reverse();
}

function UserBubble({ message }: { message: Message }) {
  return (
    <Focusable
      style={theme.userBubble}
      onActivate={() => patchStore({ draft: message.text })}
      onOKActionDescription="Edit and ask again"
    >
      {(message.via === "voice" || message.image) && (
        <div style={{ ...theme.meta, display: "flex", gap: "8px", marginBottom: "2px", color: theme.colors.accent }}>
          {message.via === "voice" && (
            <span style={{ display: "flex", alignItems: "center", gap: "3px" }}>
              <RiMicLine size={11} /> voice
            </span>
          )}
          {message.image && (
            <span style={{ display: "flex", alignItems: "center", gap: "3px" }}>
              <RiCameraLine size={11} /> screen
            </span>
          )}
        </div>
      )}
      {message.text}
    </Focusable>
  );
}

function Steps({ steps }: { steps: Message[] }) {
  const [open, setOpen] = useState(false);
  return (
    <Focusable
      style={{ ...theme.meta, display: "flex", flexDirection: "column", gap: "2px", padding: "2px 0" }}
      onActivate={() => setOpen(!open)}
      onOKActionDescription={open ? "Hide steps" : "Show steps"}
    >
      <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>
        <RiTerminalLine size={11} />
        {steps.length === 1 ? "1 step" : `${steps.length} steps`} {open ? "▾" : "▸"}
      </span>
      {open &&
        steps.map((step, index) => (
          <span key={index} style={{ paddingLeft: "15px", wordBreak: "break-all" }}>
            {step.text}
          </span>
        ))}
    </Focusable>
  );
}

function Reply({ text }: { text: string }) {
  return (
    <>
      {parseBlocks(text).map((block, index) => (
        <Focusable key={index} style={theme.assistantBlock} onActivate={() => {}} noFocusRing={false}>
          <BlockView block={block} />
        </Focusable>
      ))}
    </>
  );
}

function Exchange({ messages, partial }: { messages: Message[]; partial?: string }) {
  const parts: ReactElement[] = [];
  let steps: Message[] = [];
  const flushSteps = (key: string) => {
    if (steps.length) {
      parts.push(<Steps key={key} steps={steps} />);
      steps = [];
    }
  };
  messages.forEach((message, index) => {
    if (message.role === "tool") {
      steps.push(message);
      return;
    }
    flushSteps(`steps-${index}`);
    if (message.role === "user") parts.push(<UserBubble key={index} message={message} />);
    else if (message.role === "assistant") parts.push(<Reply key={index} text={message.text} />);
    else
      parts.push(
        <Focusable key={index} style={{ ...theme.base, fontSize: "12px", color: theme.colors.danger }} onActivate={() => {}}>
          {message.text}
        </Focusable>,
      );
  });
  flushSteps("steps-end");
  if (partial) {
    parts.push(
      <div key="partial" style={{ ...theme.assistantBlock, color: theme.colors.muted }}>
        {partial}
      </div>,
    );
  }
  return <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>{parts}</div>;
}

export function Conversation({ app, partial }: { app: AppState; partial: string }) {
  const exchanges = groupExchanges(app.chat.messages);
  const working = app.chat.status === "working";
  if (exchanges.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
        <div style={{ ...theme.meta, fontSize: "12px", lineHeight: "1.4" }}>
          Ask anything about this handheld or your game.
          {app.voice.ready && app.settings.shortcut !== "off"
            ? ` In game, hold ${SHORTCUT_LABELS[app.settings.shortcut]} and talk.`
            : " Set up voice in Settings to ask without typing."}
        </div>
        {SUGGESTIONS.map((suggestion) => (
          <DialogButton
            key={suggestion}
            style={{ textAlign: "left", fontSize: "13px", padding: "8px 10px" }}
            disabled={working}
            onClick={() => send(suggestion)}
          >
            {suggestion}
          </DialogButton>
        ))}
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
      {exchanges.map((exchange, index) => (
        <div
          key={`${exchange[0].time}-${index}`}
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "6px",
            paddingBottom: "10px",
            borderBottom: index === exchanges.length - 1 ? "none" : `1px solid ${theme.colors.cardLine}`,
          }}
        >
          <Exchange messages={exchange} partial={index === 0 && working ? partial : undefined} />
        </div>
      ))}
    </div>
  );
}
