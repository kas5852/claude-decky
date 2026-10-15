import { ReactNode } from "react";
import { theme } from "./theme";

export type Block =
  | { kind: "paragraph"; text: string }
  | { kind: "heading"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "code"; text: string }
  | { kind: "quote"; text: string };

const LIST_ITEM = /^\s*(?:[-*•]|\d+[.)])\s+/;
const ORDERED_ITEM = /^\s*\d+[.)]\s+/;
const HEADING = /^#{1,6}\s+/;
const INLINE = /(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*\s][^*]*\*|_[^_\s][^_]*_|\[[^\]]+\]\([^)]+\)|https?:\/\/[^\s)]+)/g;

export function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r/g, "").split("\n");
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length) {
      blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
      paragraph = [];
    }
  };
  for (let index = 0; index < lines.length; index++) {
    const line = lines[index];
    if (line.trim().startsWith("```")) {
      flush();
      const code: string[] = [];
      index++;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        code.push(lines[index]);
        index++;
      }
      blocks.push({ kind: "code", text: code.join("\n") });
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    if (HEADING.test(line)) {
      flush();
      blocks.push({ kind: "heading", text: line.replace(HEADING, "").replace(/\s*#+\s*$/, "") });
      continue;
    }
    if (LIST_ITEM.test(line)) {
      flush();
      const ordered = ORDERED_ITEM.test(line);
      const items = [line.replace(LIST_ITEM, "")];
      while (index + 1 < lines.length) {
        const next = lines[index + 1];
        if (LIST_ITEM.test(next) && ORDERED_ITEM.test(next) === ordered) {
          items.push(next.replace(LIST_ITEM, ""));
        } else if (next.trim() && /^\s{2,}/.test(next)) {
          items[items.length - 1] += " " + next.trim();
        } else {
          break;
        }
        index++;
      }
      blocks.push({ kind: "list", ordered, items });
      continue;
    }
    if (line.startsWith(">")) {
      flush();
      blocks.push({ kind: "quote", text: line.replace(/^>\s?/, "") });
      continue;
    }
    paragraph.push(line.trim());
  }
  flush();
  return blocks;
}

export function renderInline(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const match of text.matchAll(INLINE)) {
    const token = match[0];
    const start = match.index ?? 0;
    if (start > last) nodes.push(text.slice(last, start));
    if (token.startsWith("`")) {
      nodes.push(<code key={key++} style={theme.inlineCode}>{token.slice(1, -1)}</code>);
    } else if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push(<strong key={key++} style={{ color: theme.colors.strong }}>{token.slice(2, -2)}</strong>);
    } else if (token.startsWith("[")) {
      const label = token.slice(1, token.indexOf("]"));
      nodes.push(<span key={key++} style={theme.link}>{label}</span>);
    } else if (token.startsWith("http")) {
      nodes.push(<span key={key++} style={theme.link}>{token}</span>);
    } else {
      nodes.push(<em key={key++}>{token.slice(1, -1)}</em>);
    }
    last = start + token.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

export function BlockView({ block }: { block: Block }) {
  switch (block.kind) {
    case "heading":
      return <div style={theme.heading}>{renderInline(block.text)}</div>;
    case "code":
      return <pre style={theme.codeBlock}>{block.text}</pre>;
    case "quote":
      return <div style={theme.quote}>{renderInline(block.text)}</div>;
    case "list":
      return (
        <div style={{ display: "flex", flexDirection: "column", gap: "3px" }}>
          {block.items.map((item, index) => (
            <div key={index} style={{ display: "flex", gap: "6px" }}>
              <span style={{ color: theme.colors.accent, minWidth: block.ordered ? "16px" : "8px", flexShrink: 0 }}>
                {block.ordered ? `${index + 1}.` : "•"}
              </span>
              <span style={{ minWidth: 0 }}>{renderInline(item)}</span>
            </div>
          ))}
        </div>
      );
    default:
      return <div>{renderInline(block.text)}</div>;
  }
}
