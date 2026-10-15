import {
  ButtonItem,
  DialogButton,
  Focusable,
  PanelSection,
  PanelSectionRow,
  TextField,
  staticClasses,
} from "@decky/ui";
import {
  addEventListener,
  callable,
  definePlugin,
  removeEventListener,
  toaster,
} from "@decky/api";
import { CSSProperties, useEffect, useState } from "react";
import { RiTerminalBoxLine } from "react-icons/ri";

type Role = "user" | "assistant" | "tool" | "error";

interface Message {
  role: Role;
  text: string;
  time: number;
}

interface ChatState {
  messages: Message[];
  status: "idle" | "working" | "error";
  error: string;
  partial: string;
  elapsed: number;
  resumable: boolean;
}

interface SendResult {
  ok: boolean;
  error?: string;
}

const send = callable<[prompt: string], SendResult>("send");
const getState = callable<[], ChatState>("get_state");
const newChat = callable<[], ChatState>("new_chat");
const cancel = callable<[], boolean>("cancel");

const QUICK_PROMPTS = [
  "What's using my battery?",
  "Check temps and TDP",
  "Why did my last game crash?",
  "Anything wrong in the logs since boot?",
];

const POLL_MS = 1000;

const EMPTY_STATE: ChatState = {
  messages: [],
  status: "idle",
  error: "",
  partial: "",
  elapsed: 0,
  resumable: false,
};

let draft = "";

const textStyle: CSSProperties = {
  whiteSpace: "pre-wrap",
  wordBreak: "break-word",
  fontSize: "13px",
  lineHeight: "1.4",
  padding: "4px 0",
};

const roleStyles: Record<Role, CSSProperties> = {
  user: { ...textStyle, color: "#9ecbff", fontWeight: 600 },
  assistant: { ...textStyle, color: "#e8e8e8" },
  tool: { ...textStyle, color: "#8b929a", fontSize: "11px", padding: "1px 0" },
  error: { ...textStyle, color: "#ff8a80" },
};

function paragraphs(text: string): string[] {
  return text
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
}

function groupExchanges(messages: Message[]): Message[][] {
  const exchanges: Message[][] = [];
  for (const message of messages) {
    if (message.role === "user" || exchanges.length === 0) {
      exchanges.push([]);
    }
    exchanges[exchanges.length - 1].push(message);
  }
  return exchanges.reverse();
}

function statusLine(state: ChatState): { text: string; color: string } {
  if (state.status === "working") {
    return { text: `Working… ${state.elapsed}s`, color: "#ffd479" };
  }
  if (state.status === "error") {
    return { text: `Error: ${state.error}`, color: "#ff8a80" };
  }
  return { text: state.resumable ? "Idle, follow-ups continue this chat" : "Idle", color: "#8b929a" };
}

function MessageView({ message, onReuse }: { message: Message; onReuse: (text: string) => void }) {
  if (message.role === "tool") {
    return <div style={roleStyles.tool}>• ran {message.text}</div>;
  }
  if (message.role === "user") {
    return (
      <Focusable
        style={roleStyles.user}
        onActivate={() => onReuse(message.text)}
        onOKActionDescription="Edit and ask again"
      >
        {message.text}
      </Focusable>
    );
  }
  return (
    <>
      {paragraphs(message.text).map((part, index) => (
        <Focusable key={index} style={roleStyles[message.role]} onActivate={() => {}}>
          {part}
        </Focusable>
      ))}
    </>
  );
}

function Content() {
  const [state, setState] = useState<ChatState>(EMPTY_STATE);
  const [prompt, setPrompt] = useState(draft);
  const [notice, setNotice] = useState("");

  const refresh = async () => {
    try {
      setState(await getState());
    } catch (error) {
      setNotice(String(error));
    }
  };

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, []);

  const updatePrompt = (value: string) => {
    draft = value;
    setPrompt(value);
  };

  const ask = async (text: string) => {
    const result = await send(text);
    if (result.ok) {
      updatePrompt("");
      setNotice("");
    } else {
      setNotice(result.error ?? "Could not send");
    }
    await refresh();
  };

  const startOver = async () => {
    setState(await newChat());
    setNotice("");
  };

  const working = state.status === "working";
  const status = statusLine(state);
  const exchanges = groupExchanges(state.messages);

  return (
    <>
      <PanelSection title="Ask">
        <PanelSectionRow>
          <TextField
            value={prompt}
            disabled={working}
            bShowClearAction={true}
            onChange={(event) => updatePrompt(event.target.value)}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <Focusable style={{ display: "flex", gap: "6px" }} flow-children="horizontal">
            <DialogButton
              style={{ flex: 2, minWidth: 0 }}
              disabled={working || prompt.trim().length === 0}
              onClick={() => ask(prompt)}
            >
              Send
            </DialogButton>
            <DialogButton style={{ flex: 1, minWidth: 0 }} disabled={!working} onClick={() => cancel().then(refresh)}>
              Stop
            </DialogButton>
            <DialogButton style={{ flex: 1, minWidth: 0 }} onClick={startOver}>
              New
            </DialogButton>
          </Focusable>
        </PanelSectionRow>
        <PanelSectionRow>
          <div style={{ fontSize: "12px", color: status.color, wordBreak: "break-word" }}>{status.text}</div>
          {notice && <div style={{ fontSize: "12px", color: "#ff8a80" }}>{notice}</div>}
        </PanelSectionRow>
      </PanelSection>
      <PanelSection title="Chat">
        {exchanges.length === 0 && !working && (
          <PanelSectionRow>
            <div style={roleStyles.tool}>No messages yet. Pick a quick question below or type one.</div>
          </PanelSectionRow>
        )}
        {exchanges.map((exchange, index) => (
          <PanelSectionRow key={`${exchange[0].time}-${index}`}>
            <div style={{ borderBottom: "1px solid #ffffff1a", paddingBottom: "6px", marginBottom: "4px" }}>
              {exchange.map((message, messageIndex) => (
                <MessageView key={messageIndex} message={message} onReuse={updatePrompt} />
              ))}
              {index === 0 && working && state.partial && <div style={roleStyles.assistant}>{state.partial}</div>}
            </div>
          </PanelSectionRow>
        ))}
      </PanelSection>
      <PanelSection title="Quick questions">
        {QUICK_PROMPTS.map((quick) => (
          <PanelSectionRow key={quick}>
            <ButtonItem layout="below" disabled={working} onClick={() => ask(quick)}>
              {quick}
            </ButtonItem>
          </PanelSectionRow>
        ))}
      </PanelSection>
    </>
  );
}

export default definePlugin(() => {
  const listener = addEventListener<[reply: string]>("claude_done", (reply) => {
    toaster.toast({
      title: "Claude replied",
      body: reply.length > 120 ? `${reply.slice(0, 117)}…` : reply || "Done",
      icon: <RiTerminalBoxLine />,
    });
  });

  return {
    name: "Claude",
    titleView: <div className={staticClasses.Title}>Claude</div>,
    content: <Content />,
    icon: <RiTerminalBoxLine />,
    onDismount() {
      removeEventListener("claude_done", listener);
    },
  };
});
