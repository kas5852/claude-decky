import { ConfirmModal, DialogButton, Focusable, TextField, showModal } from "@decky/ui";
import { useMemo, useState } from "react";
import { encode } from "uqr";
import { AuthState, ProviderInfo, authCancel, authLogin, authLogout, authRefresh, authSubmit, installAgent } from "../api";
import { theme } from "../theme";

function QrCode({ text, size }: { text: string; size: number }) {
  const path = useMemo(() => {
    const qr = encode(text, { ecc: "L", border: 2 });
    let d = "";
    qr.data.forEach((row, y) =>
      row.forEach((dark, x) => {
        if (dark) d += `M${x} ${y}h1v1h-1z`;
      }),
    );
    return { d, count: qr.size };
  }, [text]);
  return (
    <svg
      viewBox={`0 0 ${path.count} ${path.count}`}
      width={size}
      height={size}
      shapeRendering="crispEdges"
      style={{ background: "#fff", borderRadius: "8px", display: "block", margin: "0 auto" }}
    >
      <path d={path.d} fill="#000" />
    </svg>
  );
}

const METHOD_LABELS: Record<string, string> = {
  CLAUDE_CODE_OAUTH_TOKEN: "Long-lived token",
  oauth_token: "Long-lived token",
  ANTHROPIC_API_KEY: "API key",
  OPENAI_API_KEY: "API key",
  GEMINI_API_KEY: "API key",
  api_key: "API key",
  "claude.ai": "Claude account",
  chatgpt: "ChatGPT account",
  google: "Google account",
};

function methodLabel(method: string) {
  return METHOD_LABELS[method] ?? method;
}

function DeviceCode({ auth }: { auth: AuthState }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <QrCode text={auth.url} size={168} />
      <div style={{ ...theme.base, fontSize: "13px" }}>Scan with your phone, sign in, then enter this code:</div>
      <div
        style={{
          fontFamily: "ui-monospace, 'DejaVu Sans Mono', monospace",
          fontSize: "22px",
          letterSpacing: "0.12em",
          textAlign: "center",
          color: theme.colors.strong,
          background: "rgba(255,255,255,0.06)",
          borderRadius: "8px",
          padding: "6px",
        }}
      >
        {auth.userCode}
      </div>
      <div style={theme.meta}>This screen updates by itself once you're signed in.</div>
      <DialogButton onClick={() => authCancel()}>Cancel</DialogButton>
    </div>
  );
}

function SignInFlow({ auth }: { auth: AuthState }) {
  const [direct, setDirect] = useState(false);
  const [code, setCode] = useState("");
  const [notice, setNotice] = useState("");
  const keyFlow = auth.flow === "api_key";
  const usePhone = Boolean(auth.phoneUrl) && !direct;
  const qrText = usePhone ? auth.phoneUrl : auth.url;

  const submit = async () => {
    const result = await authSubmit(code);
    setNotice(result.ok ? "" : result.error ?? "Could not send the code");
    if (result.ok) setCode("");
  };

  if (auth.phase === "starting") return <div style={theme.meta}>Starting sign-in…</div>;
  if (auth.phase === "checking" || auth.phase === "finishing")
    return <div style={{ ...theme.base, fontSize: "13px" }}>Checking…</div>;
  if (auth.userCode && !auth.wantsCode) return <DeviceCode auth={auth} />;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      {auth.error && <div style={{ fontSize: "12px", color: theme.colors.danger }}>{auth.error}</div>}
      <QrCode text={qrText} size={usePhone ? 168 : 200} />
      <div style={{ ...theme.base, fontSize: "13px" }}>
        {usePhone
          ? keyFlow
            ? "Scan with your phone (same Wi-Fi). Create an API key there and paste it on that page."
            : "Scan with your phone (same Wi-Fi). Sign in there, copy the code, then paste it on that page."
          : keyFlow
            ? "Scan to open the API key page. Then type the key below."
            : "Scan with your phone and sign in. Then type the code it shows below."}
      </div>
      {!usePhone && (
        <>
          <TextField value={code} bIsPassword={keyFlow} onChange={(event) => setCode(event.target.value)} />
          <DialogButton disabled={!code.trim()} onClick={submit}>
            {keyFlow ? "Save key" : "Submit code"}
          </DialogButton>
        </>
      )}
      {notice && <div style={{ fontSize: "12px", color: theme.colors.danger }}>{notice}</div>}
      <Focusable style={theme.row} flow-children="horizontal">
        {auth.phoneUrl && (
          <DialogButton style={{ ...theme.smallButton, flex: 1 }} onClick={() => setDirect(!direct)}>
            {usePhone ? (keyFlow ? "Type key here" : "Type code here") : "Use phone page"}
          </DialogButton>
        )}
        <DialogButton style={{ ...theme.smallButton, flex: 1 }} onClick={() => authCancel()}>
          Cancel
        </DialogButton>
      </Focusable>
    </div>
  );
}

export function Account({ auth, provider }: { auth: AuthState; provider: ProviderInfo }) {
  const { status } = auth;
  const waiting = ["starting", "waiting", "checking", "finishing"].includes(auth.phase);

  const logout = () =>
    showModal(
      <ConfirmModal
        strTitle={`Sign out of ${provider.label}?`}
        strDescription={`${provider.label} on this handheld will be signed out, including in the terminal. Saved tokens and keys are removed, and a backup is kept next to them.`}
        strOKButtonText="Sign out"
        onOK={() => authLogout()}
      />,
    );

  if (waiting) return <SignInFlow auth={auth} />;

  if (!status.installed) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        <div style={{ ...theme.base, fontSize: "13px" }}>
          {provider.label} isn't installed for this user yet. {provider.installHint}
        </div>
        <DialogButton disabled={auth.phase === "installing"} onClick={() => installAgent()}>
          {auth.phase === "installing" ? "Installing…" : `Install ${provider.label}`}
        </DialogButton>
        {auth.error && <div style={{ fontSize: "12px", color: theme.colors.danger }}>{auth.error}</div>}
        {auth.installLog && auth.phase !== "installing" && <pre style={theme.codeBlock}>{auth.installLog}</pre>}
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px" }}>
        <span
          style={{
            width: "8px",
            height: "8px",
            borderRadius: "50%",
            background: status.loggedIn ? theme.colors.good : theme.colors.danger,
          }}
        />
        <span style={{ color: theme.colors.text }}>
          {status.loggedIn
            ? status.email ?? `Signed in · ${methodLabel(status.method)}`
            : "Not signed in"}
        </span>
      </div>
      {status.loggedIn && (status.subscriptionType || status.orgName) && (
        <div style={theme.meta}>{[status.subscriptionType, status.orgName].filter(Boolean).join(" · ")}</div>
      )}
      {auth.phase === "done" && <div style={{ fontSize: "12px", color: theme.colors.good }}>Signed in.</div>}
      {auth.phase === "failed" && auth.error && (
        <div style={{ fontSize: "12px", color: theme.colors.danger }}>{auth.error}</div>
      )}
      {status.loggedIn ? (
        <Focusable style={theme.row} flow-children="horizontal">
          <DialogButton style={{ ...theme.smallButton, flex: 1 }} onClick={() => authRefresh()}>
            Check
          </DialogButton>
          <DialogButton style={{ ...theme.smallButton, flex: 1 }} onClick={logout}>
            Sign out
          </DialogButton>
        </Focusable>
      ) : (
        <>
          {Object.entries(provider.loginFlows).map(([flow, label], index) => (
            <DialogButton
              key={flow}
              style={index === 0 ? undefined : { fontSize: "12px", padding: "6px" }}
              onClick={() => authLogin(flow)}
            >
              {label}
            </DialogButton>
          ))}
        </>
      )}
    </div>
  );
}
