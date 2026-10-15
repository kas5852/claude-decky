import { callable } from "@decky/api";

export type Role = "user" | "assistant" | "tool" | "error" | "note";

export interface Message {
  role: Role;
  text: string;
  time: number;
  via?: "voice";
  image?: boolean;
  agent?: string;
}

export interface ChatState {
  messages: Message[];
  status: "idle" | "working" | "error";
  error: string;
  authNeeded: boolean;
  partial: string;
  started: number;
  resumable: boolean;
  attachment: { thumb: string } | null;
}

export type VoicePhase = "idle" | "recording" | "stopping" | "transcribing" | "error";

export interface VoiceState {
  phase: VoicePhase;
  error: string;
  engine: boolean;
  installed: string[];
  ready: boolean;
  download: { model: string; done: number; total: number; error: string } | null;
  started: number;
  origin: "panel" | "pad";
  tap: boolean;
  sizes: Record<string, number>;
}

export interface AuthStatus {
  installed: boolean;
  loggedIn: boolean;
  method: string;
  guess?: boolean;
  email?: string;
  orgName?: string;
  subscriptionType?: string;
}

export interface AuthState {
  provider: string;
  status: AuthStatus;
  phase: "idle" | "starting" | "waiting" | "checking" | "finishing" | "done" | "failed" | "installing";
  flow: string;
  url: string;
  userCode: string;
  wantsCode: boolean;
  phoneUrl: string;
  error: string;
  installLog: string;
}

export interface Settings {
  provider: string;
  model: string;
  codex_model: string;
  gemini_model: string;
  workdir: string;
  voice_model: string;
  shortcut: string;
  shortcut_screen: boolean;
  allow_tools: boolean;
  low_priority: boolean;
}

export interface ProviderInfo {
  id: string;
  label: string;
  short: string;
  models: Record<string, string>;
  modelKey: "model" | "codex_model" | "gemini_model";
  loginFlows: Record<string, string>;
  installHint: string;
  toolsOffHint: string;
}

export interface AppState {
  chat: ChatState;
  voice: VoiceState;
  auth: AuthState;
  settings: Settings;
  providers: ProviderInfo[];
  padDevices: string[];
}

export function currentProvider(app: AppState | null): ProviderInfo | undefined {
  return app?.providers.find((provider) => provider.id === app.settings.provider);
}

export function agentName(app: AppState | null, id?: string): string {
  const provider = app?.providers.find((item) => item.id === (id ?? app?.settings.provider));
  return provider?.short ?? "Claude";
}

export interface Result {
  ok: boolean;
  error?: string;
  text?: string;
  thumb?: string;
}

export interface Notice {
  kind: "busy" | "heard" | "error";
  title: string;
  body: string;
}

export const getState = callable<[], AppState>("get_state");
export const setVisible = callable<[visible: boolean], AppState | Record<string, never>>("set_visible");
export const send = callable<[prompt: string], Result>("send");
export const cancel = callable<[], boolean>("cancel");
export const newChat = callable<[], ChatState>("new_chat");
export const captureScreen = callable<[], Result>("capture_screen");
export const clearAttachment = callable<[], boolean>("clear_attachment");
export const voiceStart = callable<[], Result>("voice_start");
export const voiceStop = callable<[], Result>("voice_stop");
export const voiceTap = callable<[], Result>("voice_tap");
export const voiceCancel = callable<[], Result>("voice_cancel");
export const voiceDownload = callable<[name: string], Result>("voice_download");
export const voiceDelete = callable<[name: string], VoiceState>("voice_delete");
export const updateSettings = callable<[patch: Partial<Settings>], AppState>("update_settings");
export const authRefresh = callable<[], AuthState>("auth_refresh");
export const authLogin = callable<[flow: string], AuthState>("auth_login");
export const authSubmit = callable<[code: string], Result>("auth_submit");
export const authCancel = callable<[], AuthState>("auth_cancel");
export const authLogout = callable<[], AuthState>("auth_logout");
export const installAgent = callable<[], AuthState>("install_agent");

export const SHORTCUT_LABELS: Record<string, string> = {
  off: "Off",
  l3_r3: "L3 + R3",
  view_menu: "View + Menu",
  lb_rb_y: "LB + RB + Y",
};

export const VOICE_MODEL_LABELS: Record<string, string> = {
  "tiny.en": "Tiny",
  "base.en": "Base",
  "small.en": "Small",
  base: "Multilingual",
};

export const VOICE_MODEL_DETAILS: Record<string, string> = {
  "tiny.en": "English, fastest, makes more mistakes.",
  "base.en": "English, fast and accurate. Recommended.",
  "small.en": "English, most accurate, about 3x slower.",
  base: "Any language, same speed as Base.",
};
