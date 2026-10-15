import { useEffect, useState } from "react";
import { AppState, AuthState, ChatState, VoiceState } from "./api";

type View = "chat" | "settings";

interface Store {
  app: AppState | null;
  partial: string;
  view: View;
  draft: string;
  panelOpen: boolean;
  busyAttaching: boolean;
}

const store: Store = {
  app: null,
  partial: "",
  view: "chat",
  draft: "",
  panelOpen: false,
  busyAttaching: false,
};

const listeners = new Set<() => void>();

function publish() {
  for (const listener of listeners) listener();
}

export function getStore(): Store {
  return store;
}

export function patchStore(patch: Partial<Store>) {
  Object.assign(store, patch);
  publish();
}

export function setApp(app: AppState) {
  store.app = app;
  store.partial = app.chat.partial;
  publish();
}

export function setChat(chat: ChatState) {
  if (!store.app) return;
  store.app = { ...store.app, chat };
  if (chat.status !== "working") store.partial = "";
  publish();
}

export function setVoice(voice: VoiceState) {
  if (!store.app) return;
  store.app = { ...store.app, voice };
  publish();
}

export function setAuth(auth: AuthState) {
  if (!store.app) return;
  store.app = { ...store.app, auth };
  publish();
}

export function setPartial(partial: string) {
  store.partial = partial;
  publish();
}

export function useStore(): Store {
  const [, setTick] = useState(0);
  useEffect(() => {
    const listener = () => setTick((tick) => tick + 1);
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return store;
}
