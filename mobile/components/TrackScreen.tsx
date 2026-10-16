/** Track screen: any item's status, badges, latency, editor notes and journey.
 *
 * Always live: tracking opens the SSE delivery stream and every `news` frame
 * refetches the item — approvals and stage transitions appear on their own.
 * Same data as the website's /track page (admin review-detail endpoint).
 */

import { useEffect, useRef, useState } from "react";
import { Button, FlatList, StyleSheet, Text, TextInput, View } from "react-native";
import {
  Settings,
  reviewDetail,
  subscribeDeliveries,
  type AuditEntry,
  type MediaAsset,
  type ReviewItem,
} from "../lib/api";
import { C, T, certaintyColors, latencyBetween } from "../lib/theme";

const TERMINAL = new Set(["delivered", "duplicate", "rejected", "failed"]);

interface Step {
  name: string;
  state: "done" | "current" | "todo" | "skip";
}

function stepper(events: string[], status: string): Step[] {
  const has = new Set(events);
  const reviewNeeded = has.has("needs_review");
  const steps: Step[] = [
    { name: "Ingest", state: has.has("received") ? "done" : "todo" },
    {
      name: "Extract",
      state: has.has("extracted") || has.has("media_extracted") ? "done" : "todo",
    },
    {
      name: "Validate",
      state: has.has("validated") || has.has("needs_review") ? "done" : "todo",
    },
    {
      name: "Review",
      state: !reviewNeeded
        ? "skip"
        : has.has("review_approved") || has.has("review_rejected")
          ? "done"
          : "todo",
    },
    { name: "Enrich", state: has.has("enriched") ? "done" : "todo" },
    {
      name: "Deliver",
      state: has.has("delivered") ? "done" : has.has("eligible") ? "current" : "todo",
    },
  ];
  if (!TERMINAL.has(status)) {
    const firstOpen = steps.findIndex((s) => s.state === "todo");
    if (firstOpen >= 0 && steps[firstOpen].state === "todo") {
      steps[firstOpen] = { ...steps[firstOpen], state: "current" };
    }
  }
  return steps;
}

function StepDot({ state }: { state: Step["state"] }) {
  const glyph = state === "done" ? "●" : state === "current" ? "◉" : state === "skip" ? "–" : "○";
  const color =
    state === "done" ? C.good : state === "current" ? C.accent : C.muted;
  return <Text style={{ color, fontSize: 16 }}>{glyph}</Text>;
}

export default function TrackScreen({
  settings,
  suggestedId,
}: {
  settings: Settings;
  suggestedId: string;
}) {
  const [itemId, setItemId] = useState(suggestedId);
  const [item, setItem] = useState<ReviewItem | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [media, setMedia] = useState<MediaAsset[]>([]);
  const [stream, setStream] = useState("off");
  const [message, setMessage] = useState("");
  const stopRef = useRef<(() => void) | null>(null);
  const seenRef = useRef("");

  async function track(id: string) {
    const clean = id.trim();
    if (!clean) return;
    if (!settings.adminKey) {
      setMessage("Set the admin key in Settings first.");
      return;
    }
    try {
      const detail = await reviewDetail(settings, clean);
      setItem(detail.item);
      setAudit(detail.audit);
      setMedia(detail.media ?? []);
      setMessage("");
    } catch (error) {
      setMessage(`Failed: ${error instanceof Error ? error.message : error}`);
    }
  }

  // Latest ingest pre-fills and auto-tracks once per new id.
  useEffect(() => {
    if (suggestedId && suggestedId !== seenRef.current) {
      seenRef.current = suggestedId;
      setItemId(suggestedId);
      void track(suggestedId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestedId]);

  // Always live while an item is tracked: any delivery refetches it.
  useEffect(() => {
    stopRef.current?.();
    stopRef.current = null;
    if (!item || !settings.clientKey) {
      setStream(item ? "off (no client key)" : "off");
      return;
    }
    if (TERMINAL.has(item.status)) {
      setStream("terminal — no further stages");
      return;
    }
    const id = item.id;
    setStream("connecting…");
    stopRef.current = subscribeDeliveries(
      settings,
      () => {
        setStream("update received, refetching…");
        void track(id).then(() => setStream("live"));
      },
      (errorMessage) => setStream(`stream error: ${errorMessage}`),
    );
    setStream("live");
    return () => {
      stopRef.current?.();
      stopRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [item?.id, settings.clientKey]);

  const events = audit.map((e) => e.event_type);
  const steps = item ? stepper(events, item.status) : [];
  const approval = audit.find((e) => e.event_type === "review_approved");
  const approvalNote =
    approval && typeof approval.detail?.note === "string" ? approval.detail.note : null;
  const cert = item ? certaintyColors(item.certainty_label) : null;

  return (
    <View style={T.screen}>
      <Text style={T.h1}>Track</Text>
      <View style={T.row}>
        <TextInput
          style={[T.input, { flex: 1 }]}
          value={itemId}
          onChangeText={setItemId}
          autoCapitalize="none"
          placeholder="Item id (from ingest response)"
        />
        <Button title="Track" onPress={() => void track(itemId)} />
      </View>
      <Text style={styles.stream}>● SSE: {stream}</Text>
      {message ? <Text style={T.small}>{message}</Text> : null}
      {item && cert && (
        <View style={T.card}>
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
          </View>
          <Text style={T.small}>
            AI confidence {item.credibility_confidence ?? "—"} · ingest→eligible{" "}
            {latencyBetween(item.created_at, item.eligible_at)} · eligible→delivered{" "}
            {latencyBetween(item.eligible_at, item.delivered_at)}
          </Text>
          {item.editorially_reviewed ? (
            <Text style={T.note}>
              ✓ Editorially approved{item.reviewed_at ? ` · ${item.reviewed_at}` : ""}
              {approvalNote ? `\n“${approvalNote}”` : ""}
            </Text>
          ) : null}
        </View>
      )}
      {steps.length > 0 && (
        <View style={T.card}>
          <Text style={T.label}>Pipeline position</Text>
          {steps.map((s) => (
            <View key={s.name} style={T.row}>
              <StepDot state={s.state} />
              <Text style={s.state === "skip" ? T.small : T.body}>
                {s.name}
                {s.state === "skip" ? " (not needed)" : ""}
              </Text>
            </View>
          ))}
        </View>
      )}
      {media.length > 0 && (
        <View style={T.card}>
          <Text style={T.label}>Attached media</Text>
          {media.map((m) => (
            <Text key={m.id} style={T.small}>
              {m.kind} · {m.filename ?? "(no name)"} · {m.extraction_status}
              {m.size_bytes ? ` · ${Math.round(m.size_bytes / 1024)} KB` : ""}
            </Text>
          ))}
        </View>
      )}
      <FlatList
        data={audit}
        keyExtractor={(_, i) => String(i)}
        renderItem={({ item: entry }) => (
          <Text style={T.mono}>
            {entry.event_type} · {entry.stage ?? "?"} · {entry.created_at}
          </Text>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  stream: { color: C.good, fontWeight: "700", fontSize: 12 },
});
