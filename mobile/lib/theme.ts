/** Shared look: paper, ink, Nepal crimson accent. */

import { StyleSheet, TextStyle } from "react-native";

export const C = {
  paper: "#faf9f7",
  card: "#ffffff",
  ink: "#1a1a2e",
  muted: "#6c757d",
  line: "#e6e2da",
  accent: "#c1121f",
  accentSoft: "#fdebec",
  good: "#1a7f37",
  goodSoft: "#dcf5e3",
  warn: "#9a6a00",
  warnSoft: "#fff3cd",
  bad: "#b42318",
  badSoft: "#fde4e2",
  info: "#0b7285",
  infoSoft: "#d0ebff",
  neutralSoft: "#e9ecef",
};

export const CERT_STYLE: Record<string, { bg: string; fg: string }> = {
  high: { bg: C.goodSoft, fg: C.good },
  medium: { bg: C.warnSoft, fg: C.warn },
  low: { bg: C.badSoft, fg: C.bad },
  unassessed: { bg: C.neutralSoft, fg: C.muted },
};

export function certaintyColors(label: string): { bg: string; fg: string } {
  return CERT_STYLE[label] ?? CERT_STYLE.unassessed;
}

/** "42s", "3m 12s", "1h 04m" from two ISO timestamps (null-safe). */
export function latencyBetween(fromIso: string | null, toIso: string | null): string {
  if (!fromIso || !toIso) return "—";
  const ms = Date.parse(toIso) - Date.parse(fromIso);
  if (!Number.isFinite(ms) || ms < 0) return "—";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

const baseFont: TextStyle = { color: C.ink };

export const T = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.paper, padding: 16, gap: 10 } as const,
  h1: { ...baseFont, fontSize: 22, fontWeight: "800" } as const,
  label: { ...baseFont, fontWeight: "700", fontSize: 13, textTransform: "uppercase", letterSpacing: 0.5, color: C.muted } as const,
  input: {
    backgroundColor: C.card,
    borderWidth: 1,
    borderColor: C.line,
    borderRadius: 10,
    padding: 10,
    fontSize: 15,
    color: C.ink,
  } as const,
  card: {
    backgroundColor: C.card,
    borderWidth: 1,
    borderColor: C.line,
    borderRadius: 12,
    padding: 14,
    gap: 6,
    shadowColor: "#000",
    shadowOpacity: 0.05,
    shadowRadius: 6,
    shadowOffset: { width: 0, height: 2 },
    elevation: 2,
  } as const,
  title: { ...baseFont, fontSize: 17, fontWeight: "700" } as const,
  body: { ...baseFont, fontSize: 14, lineHeight: 20 } as const,
  small: { color: C.muted, fontSize: 12 } as const,
  mono: { fontFamily: "monospace", fontSize: 11, color: C.muted } as const,
  badge: {
    fontSize: 12,
    fontWeight: "700",
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 3,
    overflow: "hidden",
  } as const,
  row: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" } as const,
  note: {
    ...baseFont,
    fontStyle: "italic",
    backgroundColor: "#f1f3f5",
    padding: 10,
    borderRadius: 8,
    fontSize: 13,
  } as const,
});
