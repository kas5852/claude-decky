import { DialogButton, Focusable, GamepadButton, GamepadEvent, Navigation, QuickAccessTab, TextField } from "@decky/ui";
import { toaster } from "@decky/api";
import { useEffect, useRef, useState } from "react";
import { RiCameraLine, RiCloseLine, RiMicLine, RiSendPlane2Fill, RiStopFill } from "react-icons/ri";
import {
  AppState,
  cancel,
  captureScreen,
  clearAttachment,
  send,
  voiceCancel,
  voiceStart,
  voiceStop,
  voiceTap,
  SHORTCUT_LABELS,
} from "../api";
import { getStore, patchStore, useStore } from "../store";
import { theme } from "../theme";

const HOLD_MS = 450;
const CLOSE_WAIT_MS = 450;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function attachScreen() {
  if (getStore().busyAttaching) return;
  patchStore({ busyAttaching: true });
  Navigation.CloseSideMenus();
  await sleep(CLOSE_WAIT_MS);
  let error = "";
  try {
    const result = await captureScreen();
    if (!result.ok) error = result.error ?? "Screen capture failed";
  } catch (caught) {
    error = String(caught);
  }
  Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky);
  patchStore({ busyAttaching: false });
  if (error) toaster.toast({ title: "Claude", body: error });
}

let pressedAt = 0;

export async function talkDown() {
  pressedAt = Date.now();
  const result = await voiceStart();
  if (!result.ok && result.error) toaster.toast({ title: "Voice", body: result.error });
}

export async function talkUp() {
  if (!pressedAt) return;
  const held = Date.now() - pressedAt >= HOLD_MS;
  pressedAt = 0;
  const phase = getStore().app?.voice.phase;
  if (phase !== "recording") return;
  if (held) await voiceStop();
  else await voiceTap();
}

export function isTalkButton(event: GamepadEvent) {
  return event.detail.button === GamepadButton.SECONDARY && !event.detail.is_repeat;
}

function elapsed(since: number) {
  return Math.max(0, Math.round(Date.now() / 1000 - since));
}

function useTicker(active: boolean) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setTick((tick) => tick + 1), 1000);
    return () => clearInterval(timer);
  }, [active]);
}

function StatusLine({ app }: { app: AppState }) {
  const { chat, voice } = app;
  const listening = voice.phase === "recording";
  useTicker(chat.status === "working" || listening);
  let color = theme.colors.muted;
  let text = "Ready";
  if (listening) {
    color = theme.colors.listening;
    text = voice.tap
      ? `Listening ${elapsed(voice.started)}s · stops when you pause`
      : `Listening ${elapsed(voice.started)}s · release to send`;
  } else if (voice.phase === "transcribing" || voice.phase === "stopping") {
    color = theme.colors.warn;
    text = "Turning speech into text…";
  } else if (chat.status === "working") {
    color = theme.colors.warn;
    text = `Thinking · ${elapsed(chat.started)}s`;
  } else if (chat.status === "error") {
    color = theme.colors.danger;
    text = chat.authNeeded ? "Sign in needed, open Settings" : "Last request failed";
  } else if (voice.phase === "error" && voice.error) {
    color = theme.colors.danger;
    text = voice.error;
  } else if (voice.error) {
    text = voice.error;
  } else if (voice.ready && app.settings.shortcut !== "off") {
    text = `Ready · hold ${SHORTCUT_LABELS[app.settings.shortcut]} in game to talk`;
  }
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "6px", fontSize: "12px", color, minHeight: "18px" }}>
      <span style={{ width: "7px", height: "7px", borderRadius: "50%", background: color, flexShrink: 0 }} />
      <span style={{ minWidth: 0 }}>{text}</span>
    </div>
  );
}

export function Composer({ app }: { app: AppState }) {
  const store = useStore();
  const [notice, setNotice] = useState("");
  const working = app.chat.status === "working";
  const listening = app.voice.phase === "recording";
  const voiceBusy = listening || app.voice.phase === "transcribing" || app.voice.phase === "stopping";
  const prompt = store.draft;
  const talkRef = useRef(false);

  const ask = async () => {
    const result = await send(prompt);
    if (result.ok) {
      patchStore({ draft: "" });
      setNotice("");
    } else {
      setNotice(result.error ?? "Could not send");
    }
  };

  const startTalk = () => {
    if (talkRef.current || working || voiceBusy) return;
    talkRef.current = true;
    talkDown();
  };

  const endTalk = () => {
    if (!talkRef.current) return;
    talkRef.current = false;
    talkUp();
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <TextField
        {...({ placeholder: "Ask Claude…" } as object)}
        value={prompt}
        disabled={working}
        bShowClearAction={true}
        onChange={(event) => patchStore({ draft: event.target.value })}
      />
      {app.chat.attachment && (
        <Focusable
          style={{ ...theme.card, display: "flex", alignItems: "center", gap: "10px", padding: "6px" }}
          onActivate={() => clearAttachment()}
          onOKActionDescription="Remove screenshot"
        >
          {app.chat.attachment.thumb ? (
            <img src={app.chat.attachment.thumb} style={{ width: "96px", borderRadius: "4px", display: "block" }} />
          ) : (
            <RiCameraLine size={22} />
          )}
          <div style={{ flex: 1, fontSize: "12px", color: theme.colors.muted }}>Screenshot attached</div>
          <RiCloseLine size={18} color={theme.colors.muted} />
        </Focusable>
      )}
      <Focusable style={theme.row} flow-children="horizontal">
        <DialogButton
          style={{
            ...theme.smallButton,
            flex: 1.3,
            ...(listening ? { background: theme.colors.listening, color: "#fff" } : {}),
          }}
          disabled={working || (!app.voice.ready && !listening)}
          onButtonDown={(event: GamepadEvent) => event.detail.button === GamepadButton.OK && !event.detail.is_repeat && startTalk()}
          onButtonUp={(event: GamepadEvent) => event.detail.button === GamepadButton.OK && endTalk()}
          onPointerDown={startTalk}
          onPointerUp={endTalk}
          onPointerCancel={endTalk}
          onClick={() => {
            if (listening && !talkRef.current) voiceStop();
          }}
          onOKActionDescription="Hold to talk"
        >
          <RiMicLine size={16} />
          {listening ? "Listening" : "Talk"}
        </DialogButton>
        <DialogButton
          style={{ ...theme.smallButton, flex: 1 }}
          disabled={working || store.busyAttaching}
          onClick={attachScreen}
          onOKActionDescription="Attach what's on screen"
        >
          <RiCameraLine size={16} />
          Screen
        </DialogButton>
        {working ? (
          <DialogButton style={{ ...theme.smallButton, flex: 1 }} onClick={() => cancel()}>
            <RiStopFill size={16} />
            Stop
          </DialogButton>
        ) : (
          <DialogButton
            style={{ ...theme.smallButton, flex: 1 }}
            disabled={prompt.trim().length === 0}
            onClick={ask}
          >
            <RiSendPlane2Fill size={15} />
            Send
          </DialogButton>
        )}
      </Focusable>
      {listening && (
        <DialogButton style={{ ...theme.smallButton }} onClick={() => voiceCancel()}>
          Cancel recording
        </DialogButton>
      )}
      <StatusLine app={app} />
      {notice && <div style={{ fontSize: "12px", color: theme.colors.danger }}>{notice}</div>}
    </div>
  );
}
