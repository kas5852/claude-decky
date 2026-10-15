import { CSSProperties } from "react";

const colors = {
  accent: "#d97757",
  accentSoft: "rgba(217, 119, 87, 0.16)",
  accentLine: "rgba(217, 119, 87, 0.55)",
  text: "#e6e3dc",
  strong: "#ffffff",
  muted: "#8f96a0",
  faint: "#5f6670",
  card: "rgba(255, 255, 255, 0.045)",
  cardLine: "rgba(255, 255, 255, 0.08)",
  danger: "#ff8a80",
  warn: "#ffcf70",
  good: "#8fd19e",
  listening: "#ff6b6b",
};

const base: CSSProperties = {
  fontSize: "14px",
  lineHeight: "1.45",
  color: colors.text,
  wordBreak: "break-word",
  overflowWrap: "anywhere",
};

export const theme = {
  colors,
  base,
  card: {
    background: colors.card,
    border: `1px solid ${colors.cardLine}`,
    borderRadius: "10px",
    padding: "10px 12px",
  } as CSSProperties,
  userBubble: {
    ...base,
    background: colors.accentSoft,
    borderLeft: `3px solid ${colors.accent}`,
    borderRadius: "8px",
    padding: "7px 10px",
    color: colors.strong,
  } as CSSProperties,
  assistantBlock: {
    ...base,
    padding: "2px 0",
  } as CSSProperties,
  meta: {
    fontSize: "11px",
    color: colors.muted,
    letterSpacing: "0.02em",
  } as CSSProperties,
  heading: {
    fontWeight: 700,
    color: colors.strong,
    fontSize: "14px",
  } as CSSProperties,
  inlineCode: {
    fontFamily: "ui-monospace, 'DejaVu Sans Mono', monospace",
    fontSize: "12px",
    background: "rgba(255, 255, 255, 0.08)",
    borderRadius: "4px",
    padding: "0 4px",
  } as CSSProperties,
  codeBlock: {
    fontFamily: "ui-monospace, 'DejaVu Sans Mono', monospace",
    fontSize: "12px",
    lineHeight: "1.4",
    background: "rgba(0, 0, 0, 0.35)",
    border: `1px solid ${colors.cardLine}`,
    borderRadius: "6px",
    padding: "6px 8px",
    margin: 0,
    whiteSpace: "pre-wrap",
    wordBreak: "break-all",
    color: "#d6dde6",
  } as CSSProperties,
  quote: {
    borderLeft: `2px solid ${colors.faint}`,
    paddingLeft: "8px",
    color: colors.muted,
  } as CSSProperties,
  link: {
    color: "#9ecbff",
    textDecoration: "underline",
  } as CSSProperties,
  row: {
    display: "flex",
    gap: "6px",
    alignItems: "stretch",
  } as CSSProperties,
  smallButton: {
    minWidth: 0,
    padding: "8px 6px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "5px",
    fontSize: "13px",
  } as CSSProperties,
};
