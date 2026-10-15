import { ConfirmModal, DialogButton, Focusable, TextField, showModal } from "@decky/ui";
import { useMemo, useState } from "react";
import { encode } from "uqr";
import { AuthState, authCancel, authLogin, authLogout, authRefresh, authSubmit, installClaude } from "../api";
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

function methodLabel(method: string) {
  if (method === "CLAUDE_CODE_OAUTH_TOKEN" || method === "oauth_token") return "Long-lived token";
  if (method === "ANTHROPIC_API_KEY" || method === "api_key") return "API key";
  if (method === "claude.ai") return "Claude account";
  return method;
}

function SignInFlow({ auth }: { auth: AuthState }) {
  const [direct, setDirect] = useState(false);
  const [code, setCode] = useState("");
  const [notice, setNotice] = useState("");
  const usePhone = Boolean(auth.phoneUrl) && !direct;
  const qrText = usePhone ? auth.phoneUrl : auth.url;

  const submit = async () => {
    const result = await authSubmit(code);
    setNotice(result.ok ? "" : result.error ?? "Could not send the code");
    if (result.ok) setCode("");
  };

  if (auth.phase === "starting") return <div style={theme.meta}>Starting sign-in…</div>;
  if (auth.phase === "checking") return <div style={{ ...theme.base, fontSize: "13px" }}>Checking the code…</div>;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
      <QrCode text={qrText} size={usePhone ? 168 : 200} />
      <div style={{ ...theme.base, fontSize: "13px" }}>
        {usePhone ? (
          <>
            Scan with your phone (same Wi-Fi). Sign in there, tap <b>Copy Code</b>, then paste it on that page.
          </>
        ) : (
          <>Scan with your phone and sign in. Then type the code it shows below.</>
        )}
      </div>
      {!usePhone && (
        <>
          <TextField value={code} onChange={(event) => setCode(event.target.value)} />
          <DialogButton disabled={!code.trim()} onClick={submit}>
            Submit code
          </DialogButton>
        </>
      )}
      {notice && <div style={{ fontSize: "12px", color: theme.colors.danger }}>{notice}</div>}
      <Focusable style={theme.row} flow-children="horizontal">
        {auth.phoneUrl && (
          <DialogButton style={{ ...theme.smallButton, flex: 1 }} onClick={() => setDirect(!direct)}>
            {usePhone ? "Type code here" : "Use phone page"}
          </DialogButton>
        )}
        <DialogButton style={{ ...theme.smallButton, flex: 1 }} onClick={() => authCancel()}>
          Cancel
        </DialogButton>
      </Focusable>
    </div>
  );
}

export function Account({ auth }: { auth: AuthState }) {
  const { status } = auth;
  const waiting = ["starting", "waiting", "checking"].includes(auth.phase);

  const logout = () =>
    showModal(
      <ConfirmModal
        strTitle="Sign out of Claude?"
        strDescription="Claude Code on this handheld will be signed out, including the terminal. Saved tokens in ~/.claude/settings.json are removed (a backup is kept next to it)."
        strOKButtonText="Sign out"
        onOK={() => authLogout()}
      />,
    );

  if (waiting) return <SignInFlow auth={auth} />;

  if (!status.installed) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
        <div style={{ ...theme.base, fontSize: "13px" }}>
          Claude Code isn't installed for this user yet. It installs to ~/.local/bin, no admin rights needed.
        </div>
        <DialogButton disabled={auth.phase === "installing"} onClick={() => installClaude()}>
          {auth.phase === "installing" ? "Installing…" : "Install Claude Code"}
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
          <DialogButton onClick={() => authLogin(false)}>Sign in with Claude</DialogButton>
          <DialogButton style={{ fontSize: "12px", padding: "6px" }} onClick={() => authLogin(true)}>
            Use an Anthropic Console account instead
          </DialogButton>
        </>
      )}
    </div>
  );
}
