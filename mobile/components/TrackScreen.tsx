/** Track screen: the whole pipeline as a live board of rows.
 *
 * Every item in the system is one row carrying a 6-stage rail
 * (Ingest→Extract→Validate→Review→Enrich→Deliver) drawn as `.---.---.---`
 * so you see at a glance where each story sits. Rows are collapsible: tap to
 * expand badges, latencies, editor note, media and the full audit journey.
 *
 * Always live: the SSE delivery stream is open the whole time and every
 * `news` frame refetches the board, so approvals and stage transitions walk
 * their dots forward on their own.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import {
  Settings,
  listTrackBoard,
  subscribeDeliveries,
  type TrackEntry,
} from "../lib/api";
import { C, T, certaintyColors, latencyBetween } from "../lib/theme";

const TERMINAL = new Set(["delivered", "duplicate", "rejected", "failed"]);

/** The six board columns. `key` matches an audit event that marks completion. */
const STAGES: { name: string; short: string; done: (e: Set<string>) => boolean }[] = [
  { name: "Ingest", short: "ING", done: (e) => e.has("received") },
  { name: "Extract", short: "EXT", done: (e) => e.has("extracted") || e.has("media_extracted") },
  { name: "Validate", short: "VAL", done: (e) => e.has("validated") || e.has("needs_review") },
  {
    name: "Review",
    short: "REV",
    done: (e) => e.has("review_approved") || e.has("review_rejected"),
  },
  { name: "Enrich", short: "ENR", done: (e) => e.has("enriched") },
  { name: "Deliver", short: "DEL", done: (e) => e.has("delivered") },
];

type StageState = "done" | "current" | "todo" | "skip";

/** Map an item's audit stream + status onto per-stage states for the rail. */
function stageStates(events: string[], status: string): StageState[] {
  const has = new Set(events);
  const reviewNeeded = has.has("needs_review");
  const states: StageState[] = STAGES.map((stage) => {
    if (stage.name === "Review" && !reviewNeeded) return "skip";
    return stage.done(has) ? "done" : "todo";
  });
  // Mark "eligible" as the pre-delivery holding pen (Deliver is current, not done).
  if (has.has("eligible") && !has.has("delivered")) {
    states[STAGES.length - 1] = "current";
  }
  // First non-done, non-skip stage is where the item actually is right now.
  if (!TERMINAL.has(status)) {
    const idx = states.findIndex((s) => s === "todo");
    if (idx >= 0) states[idx] = "current";
  }
  return states;
}

const DOT: Record<StageState, { glyph: string; color: string }> = {
  done: { glyph: "●", color: C.good },
  current: { glyph: "◉", color: C.accent },
  todo: { glyph: "○", color: C.line },
  skip: { glyph: "–", color: C.muted },
};

/** The `.---.---.---` rail: dots joined by dashes, one per stage. */
function StageRail({ states }: { states: StageState[] }) {
  return (
    <View style={styles.rail}>
      {states.map((state, i) => (
        <View key={STAGES[i].name} style={styles.railCell}>
          <Text style={[styles.dot, { color: DOT[state].color }]}>{DOT[state].glyph}</Text>
          <Text
            style={[
              styles.railLabel,
              state === "done" && { color: C.good },
              state === "current" && { color: C.accent, fontWeight: "800" },
            ]}
          >
            {STAGES[i].short}
          </Text>
          {i < states.length - 1 && <Text style={styles.dash}>–</Text>}
        </View>
      ))}
    </View>
  );
}

function Row({
  entry,
  expanded,
  onToggle,
}: {
  entry: TrackEntry;
  expanded: boolean;
  onToggle: () => void;
}) {
  const { item, events } = entry;
  const states = stageStates(events, item.status);
  const cert = certaintyColors(item.certainty_label);
  const approval = events.includes("review_approved");
  const rejection = events.includes("review_rejected");

  return (
    <Pressable onPress={onToggle} style={[T.card, expanded && styles.expanded]}>
      <View style={T.row}>
        <Text style={[T.badge, { backgroundColor: "#e9ecef", color: C.ink }]}>
          {item.status}
        </Text>
        <Text style={[T.badge, { backgroundColor: cert.bg, color: cert.fg }]}>
          {item.certainty_label} · {item.credibility_score ?? "—"}
        </Text>
        {item.editorially_reviewed ? (
          <Text style={[T.badge, { backgroundColor: C.infoSoft, color: C.info }]}>
            ✓ reviewed
          </Text>
        ) : null}
        <Text style={T.small}>{expanded ? "▲" : "▼"}</Text>
      </View>

      <StageRail states={states} />

      <Text style={T.title} numberOfLines={expanded ? undefined : 1}>
        {item.title || item.body.slice(0, 80)}
      </Text>
      <Text style={T.small}>
        {(item.topics || []).join(", ") || "no topics"} · {item.urgency}
      </Text>

      {expanded && (
        <View style={styles.detail}>
          <Text style={T.body}>{item.body}</Text>
          <Text style={T.small}>
            AI confidence {item.credibility_confidence ?? "—"} · ingest→eligible{" "}
            {latencyBetween(item.created_at, item.eligible_at)} · eligible→delivered{" "}
            {latencyBetween(item.eligible_at, item.delivered_at)}
          </Text>
          {item.validation_rationale ? (
            <Text style={T.note}>AI: {item.validation_rationale}</Text>
          ) : null}
          {approval ? (
            <Text style={T.note}>✓ Editorially approved{item.reviewed_at ? ` · ${item.reviewed_at}` : ""}</Text>
          ) : null}
          {rejection ? <Text style={T.note}>✗ Rejected by an editor</Text> : null}
          <Text style={T.label}>Audit journey</Text>
          {events.map((event, i) => (
            <Text key={`${event}-${i}`} style={T.mono}>
              {event}
            </Text>
          ))}
        </View>
      )}
    </Pressable>
  );
}

export default function TrackScreen({
  settings,
  suggestedId,
}: {
  settings: Settings;
  suggestedId: string;
}) {
  const [entries, setEntries] = useState<TrackEntry[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [stream, setStream] = useState("connecting…");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const stopRef = useRef<(() => void) | null>(null);
  const seenRef = useRef("");

  const load = useCallback(async () => {
    if (!settings.adminKey) {
      setMessage("Set the admin key in Settings first.");
      return;
    }
    setLoading(true);
    try {
      const board = await listTrackBoard(settings);
      setEntries(board.items);
      setMessage(board.count === 0 ? "Pipeline is empty — ingest something." : "");
    } catch (error) {
      setMessage(`Failed: ${error instanceof Error ? error.message : error}`);
    } finally {
      setLoading(false);
    }
  }, [settings]);

  // Load once on mount / settings change. The `await` is the boundary: every
  // setState below runs in a promise callback after the effect body has returned,
  // never synchronously inside the effect.
  useEffect(() => {
    (async () => {
      if (!settings.adminKey) {
        setMessage("Set the admin key in Settings first.");
        return;
      }
      setLoading(true);
      try {
        const board = await listTrackBoard(settings);
        setEntries(board.items);
        setMessage(board.count === 0 ? "Pipeline is empty — ingest something." : "");
      } catch (error) {
        setMessage(`Failed: ${error instanceof Error ? error.message : error}`);
      } finally {
        setLoading(false);
      }
    })();
  }, [settings]);

  // A freshly ingested id auto-expands its row. Adjusting state during render
  // (the React-documented prop-change pattern) — not in an effect body.
  const [prevSuggested, setPrevSuggested] = useState(suggestedId);
  if (suggestedId !== prevSuggested) {
    setPrevSuggested(suggestedId);
    if (suggestedId) setExpandedId(suggestedId);
  }

  // Fetch board data when a fresh ingest arrives (expansion is set during
  // render above; this effect only triggers the network read).
  useEffect(() => {
    if (suggestedId && suggestedId !== seenRef.current) {
      seenRef.current = suggestedId;
      void load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestedId]);

  // Always live: every delivery refetches the whole board so dots walk forward.
  useEffect(() => {
    if (!settings.clientKey) return;
    const stop = subscribeDeliveries(
      settings,
      () => {
        setStream("update received, refetching…");
        void load().then(() => setStream("live"));
      },
      (errorMessage) => setStream(`stream error: ${errorMessage}`),
      () => setStream("live"),
    );
    stopRef.current = stop;
    return () => {
      stop();
      stopRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.clientKey]);

  const active = entries.filter((e) => !TERMINAL.has(e.item.status)).length;

  return (
    <View style={T.screen}>
      <View style={T.row}>
        <Text style={T.h1}>Pipeline</Text>
        {loading ? <ActivityIndicator /> : null}
      </View>
      <Text style={T.small}>
        {entries.length} items · {active} in flight ·{" "}
        <Text style={styles.stream}>
          ● SSE: {settings.clientKey ? stream : "off (no client key)"}
        </Text>
      </Text>
      {message ? <Text style={T.small}>{message}</Text> : null}
      <FlatList
        data={entries}
        keyExtractor={(entry) => entry.item.id}
        contentContainerStyle={{ gap: 10, paddingBottom: 24 }}
        renderItem={({ item: entry }) => (
          <Row
            entry={entry}
            expanded={expandedId === entry.item.id}
            onToggle={() =>
              setExpandedId((cur) => (cur === entry.item.id ? null : entry.item.id))
            }
          />
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  stream: { color: C.good, fontWeight: "700", fontSize: 12 },
  expanded: { borderColor: C.accent },
  rail: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 2 },
  railCell: { flexDirection: "row", alignItems: "center" },
  dot: { fontSize: 14 },
  dash: { color: C.line, fontSize: 12, marginHorizontal: 1 },
  railLabel: { fontSize: 9, color: C.muted, fontWeight: "600", marginRight: 4 },
  detail: { gap: 6, borderTopWidth: 1, borderColor: C.line, paddingTop: 8, marginTop: 4 },
});
