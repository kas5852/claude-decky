import {
  DialogButton,
  Focusable,
  GamepadButton,
  GamepadEvent,
  Navigation,
  PanelSection,
  PanelSectionRow,
  QuickAccessTab,
  staticClasses,
} from "@decky/ui";
import { addEventListener, definePlugin, removeEventListener, toaster, useQuickAccessVisible } from "@decky/api";
import { useEffect } from "react";
import { RiAddLine, RiChat3Line, RiSettings3Line, RiSparkling2Fill } from "react-icons/ri";
import { AppState, AuthState, ChatState, Notice, VoiceState, getState, newChat, setVisible } from "./api";
import { Composer, isTalkButton, talkDown, talkUp } from "./components/Composer";
import { Conversation } from "./components/Conversation";
import { SettingsView } from "./components/SettingsView";
import { getStore, patchStore, setApp, setAuth, setChat, setPartial, setVoice, useStore } from "./store";
import { theme } from "./theme";

const icon = <RiSparkling2Fill />;
let lastVoicePhase = "idle";

function openPanel() {
  patchStore({ view: "chat" });
  Navigation.OpenQuickAccessMenu(QuickAccessTab.Decky);
}

function shorten(text: string, limit: number) {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}

function onVoice(voice: VoiceState) {
  const previous = lastVoicePhase;
  lastVoicePhase = voice.phase;
  setVoice(voice);
  if (getStore().panelOpen || voice.origin !== "pad") return;
  if (voice.phase === "recording" && previous !== "recording") {
    toaster.toast({
      title: "Claude is listening",
      body: "Release to send · tap once for hands-free",
      icon,
      duration: 3500,
      playSound: false,
    });
  } else if (voice.phase === "error" || (voice.phase === "idle" && voice.error && previous !== "idle")) {
    toaster.toast({ title: "Claude voice", body: voice.error, icon });
  }
}

function onNotice(notice: Notice) {
  if (getStore().panelOpen && notice.kind !== "error") return;
  toaster.toast({ title: notice.title, body: shorten(notice.body, 160), icon, duration: 4000 });
}

function onReply(reply: string) {
  if (getStore().panelOpen) return;
  toaster.toast({
    title: "Claude",
    body: shorten(reply || "Done", 220),
    icon,
    duration: 12000,
    onClick: openPanel,
  });
}

function TitleView() {
  const store = useStore();
  const settings = store.view === "settings";
  const hasMessages = (store.app?.chat.messages.length ?? 0) > 0;
  const buttonStyle = { height: "28px", width: "40px", minWidth: 0, padding: "0", display: "flex", alignItems: "center", justifyContent: "center" };
  return (
    <Focusable style={{ display: "flex", alignItems: "center", gap: "6px", width: "100%" }} flow-children="horizontal">
      <div className={staticClasses.Title} style={{ flex: 1, paddingTop: 0, boxShadow: "none" }}>
        {settings ? "Settings" : "Claude"}
      </div>
      {!settings && hasMessages && (
        <DialogButton style={buttonStyle} onClick={() => newChat().then(setChat)} onOKActionDescription="New chat">
          <RiAddLine size={18} />
        </DialogButton>
      )}
      <DialogButton
        style={buttonStyle}
        onClick={() => patchStore({ view: settings ? "chat" : "settings" })}
        onOKActionDescription={settings ? "Back to chat" : "Settings"}
      >
        {settings ? <RiChat3Line size={18} /> : <RiSettings3Line size={18} />}
      </DialogButton>
    </Focusable>
  );
}

function SignInHint() {
  return (
    <PanelSectionRow>
      <div style={{ ...theme.card, display: "flex", flexDirection: "column", gap: "8px" }}>
        <div style={{ ...theme.base, fontSize: "13px" }}>Sign in to your Claude account to start asking.</div>
        <DialogButton onClick={() => patchStore({ view: "settings" })}>Sign in</DialogButton>
      </div>
    </PanelSectionRow>
  );
}

function Content() {
  const store = useStore();
  const visible = useQuickAccessVisible();

  useEffect(() => {
    if (!getStore().app) getState().then(setApp);
    return () => {
      patchStore({ panelOpen: false });
      setVisible(false);
    };
  }, []);

  useEffect(() => {
    patchStore({ panelOpen: visible });
    setVisible(visible).then((state) => {
      if (visible && "chat" in state) setApp(state as AppState);
    });
  }, [visible]);

  const app = store.app;
  if (!app) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <div style={theme.meta}>Loading…</div>
        </PanelSectionRow>
      </PanelSection>
    );
  }
  if (store.view === "settings") return <SettingsView app={app} />;

  const signedOut = !app.auth.status.loggedIn && !app.auth.status.guess;
  const needsSignIn = signedOut || !app.auth.status.installed || app.chat.authNeeded;
  const talk = app.voice.ready;
  return (
    <Focusable
      onButtonDown={(event: GamepadEvent) => talk && isTalkButton(event) && talkDown()}
      onButtonUp={(event: GamepadEvent) => talk && event.detail.button === GamepadButton.SECONDARY && talkUp()}
      actionDescriptionMap={talk ? { [GamepadButton.SECONDARY]: "Hold to talk" } : {}}
    >
      <PanelSection>
        {needsSignIn && <SignInHint />}
        <PanelSectionRow>
          <Composer app={app} />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title={app.chat.messages.length ? "Conversation" : "Try asking"}>
        <PanelSectionRow>
          <Conversation app={app} partial={store.partial} />
        </PanelSectionRow>
      </PanelSection>
    </Focusable>
  );
}

export default definePlugin(() => {
  const handlers: [string, (...args: any[]) => void][] = [
    ["chat_state", (chat: ChatState) => setChat(chat)],
    ["chat_partial", (partial: string) => setPartial(partial)],
    ["voice_state", (voice: VoiceState) => onVoice(voice)],
    ["auth_state", (auth: AuthState) => setAuth(auth)],
    ["notify", (notice: Notice) => onNotice(notice)],
    ["reply", (reply: string) => onReply(reply)],
  ];
  const listeners = handlers.map(([name, handler]) => [name, addEventListener(name, handler)] as const);

  return {
    name: "Claude",
    titleView: <TitleView />,
    content: <Content />,
    icon: <RiSparkling2Fill />,
    onDismount() {
      listeners.forEach(([name, listener]) => removeEventListener(name, listener));
    },
  };
});
