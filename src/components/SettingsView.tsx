import { DialogButton, DropdownItem, PanelSection, PanelSectionRow, ToggleField } from "@decky/ui";
import {
  AppState,
  SHORTCUT_LABELS,
  Settings,
  VOICE_MODEL_DETAILS,
  VOICE_MODEL_LABELS,
  updateSettings,
  voiceDelete,
  voiceDownload,
  currentProvider,
} from "../api";
import { setApp } from "../store";
import { theme } from "../theme";
import { Account } from "./Account";

const megabytes = (bytes: number) => `${Math.round(bytes / 1e6)} MB`;

async function change(patch: Partial<Settings>) {
  setApp(await updateSettings(patch));
}

function VoiceModel({ app }: { app: AppState }) {
  const { voice, settings } = app;
  const name = settings.voice_model;
  const installed = voice.installed.includes(name);
  const download = voice.download;
  const downloading = download && !download.error;
  return (
    <>
      <PanelSectionRow>
        <DropdownItem
          label="Speech model"
          description={`${VOICE_MODEL_DETAILS[name]} Runs on this handheld, only while you talk.`}
          rgOptions={Object.entries(VOICE_MODEL_LABELS).map(([data, label]) => ({
            data,
            label: `${label}${voice.installed.includes(data) ? " ✓" : ""}`,
          }))}
          selectedOption={name}
          onChange={(option) => change({ voice_model: option.data })}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        {downloading ? (
          <div style={{ ...theme.meta, fontSize: "12px" }}>
            Downloading {VOICE_MODEL_LABELS[download.model]}… {megabytes(download.done)} / {megabytes(download.total)}
          </div>
        ) : installed ? (
          <DialogButton style={{ fontSize: "12px", padding: "6px" }} onClick={() => voiceDelete(name)}>
            Delete model ({megabytes(voice.sizes[name] ?? 0)})
          </DialogButton>
        ) : (
          <DialogButton onClick={() => voiceDownload(name)}>
            Download ({megabytes(voice.sizes[name] ?? 0)})
          </DialogButton>
        )}
      </PanelSectionRow>
      {download?.error && (
        <PanelSectionRow>
          <div style={{ fontSize: "12px", color: theme.colors.danger }}>{download.error}</div>
        </PanelSectionRow>
      )}
      {!voice.engine && (
        <PanelSectionRow>
          <div style={{ fontSize: "12px", color: theme.colors.danger }}>Speech engine missing from the plugin install.</div>
        </PanelSectionRow>
      )}
    </>
  );
}

export function SettingsView({ app }: { app: AppState }) {
  const { settings } = app;
  const provider = currentProvider(app) ?? app.providers[0];
  const busy = app.chat.status === "working";
  return (
    <>
      <PanelSection title="Assistant">
        <PanelSectionRow>
          <DropdownItem
            label="Answer with"
            description={busy ? "Wait for the current answer to finish to switch." : "Each assistant keeps its own conversation and sign-in."}
            rgOptions={app.providers.map((item) => ({ data: item.id, label: item.label }))}
            selectedOption={settings.provider}
            disabled={busy}
            onChange={(option) => change({ provider: option.data })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <Account auth={app.auth} provider={provider} />
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Voice">
        <VoiceModel app={app} />
        <PanelSectionRow>
          <DropdownItem
            label="Talk shortcut in game"
            description="Hold to talk, release to send. Tap once for hands-free: it stops when you pause."
            rgOptions={Object.entries(SHORTCUT_LABELS).map(([data, label]) => ({ data, label }))}
            selectedOption={settings.shortcut}
            disabled={!app.voice.ready}
            onChange={(option) => change({ shortcut: option.data })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Send the screen with the shortcut"
            description={`${provider.short} sees what you're looking at when you ask in game.`}
            checked={settings.shortcut_screen}
            onChange={(value) => change({ shortcut_screen: value })}
          />
        </PanelSectionRow>
        {app.voice.ready && settings.shortcut !== "off" && (
          <PanelSectionRow>
            <div style={{ ...theme.meta, fontSize: "11px" }}>
              Listening for the shortcut on: {app.padDevices.length ? app.padDevices.join(", ") : "no controller found"}
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>
      <PanelSection title={provider.label}>
        <PanelSectionRow>
          <DropdownItem
            label="Model"
            rgOptions={Object.entries(provider.models).map(([data, label]) => ({ data, label }))}
            selectedOption={settings[provider.modelKey]}
            onChange={(option) => change({ [provider.modelKey]: option.data })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Full access"
            description={`${provider.short} runs commands and changes settings without asking, so it can fix things, not just look. ${provider.toolsOffHint}`}
            checked={settings.allow_tools}
            onChange={(value) => change({ allow_tools: value })}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="Low priority"
            description="The assistant and speech run at lower CPU priority so games stay smooth."
            checked={settings.low_priority}
            onChange={(value) => change({ low_priority: value })}
          />
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}
