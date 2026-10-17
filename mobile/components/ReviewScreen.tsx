/** Editorial screen: review queue → detail (AI assessment + media + audit) → approve/reject. */

import { useCallback, useState } from "react";
import {
  Button,
  FlatList,
  RefreshControl,
  Text,
  TextInput,
  View,
} from "react-native";
import {
  Settings,
  approveItem,
  listReview,
  rejectItem,
  reviewDetail,
  type AuditEntry,
  type MediaAsset,
  type ReviewItem,
} from "../lib/api";
import { C, T, certaintyColors } from "../lib/theme";

function ScoreCard({ item }: { item: ReviewItem }) {
  const cert = certaintyColors(item.certainty_label);
  return (
    <View style={T.card}>
      <View style={T.row}>
        <Text style={[T.badge, { backgroundColor: cert.bg, color: cert.fg }]}>
          {item.certainty_label} · {item.credibility_score ?? "—"}
        </Text>
        <Text style={T.small}>confidence {item.credibility_confidence ?? "—"}</Text>
      </View>
      <Text style={T.body}>{item.body}</Text>
      {item.validation_rationale ? (
        <Text style={T.note}>AI: {item.validation_rationale}</Text>
      ) : null}
    </View>
  );
}

export default function ReviewScreen({ settings }: { settings: Settings }) {
  const [queue, setQueue] = useState<ReviewItem[]>([]);
  const [selected, setSelected] = useState<ReviewItem | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [media, setMedia] = useState<MediaAsset[]>([]);
  const [note, setNote] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    if (!settings.adminKey) {
      setMessage("Set the admin key in Settings first.");
      return;
    }
    setRefreshing(true);
    try {
      const data = await listReview(settings);
      setQueue(data.items);
      setMessage(data.count === 0 ? "Queue is empty — nothing uncertain right now." : "");
    } catch (error) {
      setMessage(`Failed: ${error instanceof Error ? error.message : error}`);
    } finally {
      setRefreshing(false);
    }
  }, [settings]);

  async function open(item: ReviewItem) {
    try {
      const detail = await reviewDetail(settings, item.id);
      setSelected(detail.item);
      setAudit(detail.audit);
      setMedia(detail.media ?? []);
      setNote("");
    } catch (error) {
      setMessage(`Failed: ${error instanceof Error ? error.message : error}`);
    }
  }

  async function decide(kind: "approve" | "reject") {
    if (!selected) return;
    if (kind === "reject" && note.trim().length < 3) {
      setMessage("Rejections need a reason (≥ 3 chars) — it is audited.");
      return;
    }
    try {
      const updated =
        kind === "approve"
          ? await approveItem(settings, selected.id, note.trim() || undefined)
          : await rejectItem(settings, selected.id, note.trim());
      setMessage(
        kind === "approve"
          ? `Approved → ${updated.status}. Pipeline resumes at enrichment; watch Deliver or /live.`
          : "Rejected (terminal).",
      );
      setSelected(null);
      setAudit([]);
      setMedia([]);
      await load();
    } catch (error) {
      setMessage(`Failed: ${error instanceof Error ? error.message : error}`);
    }
  }

  if (selected) {
    return (
      <View style={T.screen}>
        <Button title="← Back to queue" onPress={() => setSelected(null)} />
        <Text style={T.h1}>{selected.title ?? "(untitled)"}</Text>
        <ScoreCard item={selected} />
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
        <View style={T.card}>
          <Text style={T.label}>Audit trail</Text>
          <FlatList
            data={audit}
            keyExtractor={(_, i) => String(i)}
            renderItem={({ item }) => (
              <Text style={T.mono}>
                {item.event_type} · {item.stage ?? "?"}
              </Text>
            )}
          />
        </View>
        <TextInput
          style={T.input}
          value={note}
          onChangeText={setNote}
          placeholder="Note (approve) or reason (reject, required)"
        />
        <View style={T.row}>
          <Button title="Approve" onPress={() => void decide("approve")} />
          <Button title="Reject" color={C.accent} onPress={() => void decide("reject")} />
        </View>
        {message ? <Text style={T.small}>{message}</Text> : null}
      </View>
    );
  }

  return (
    <View style={T.screen}>
      <Text style={T.h1}>Review queue</Text>
      <Text style={T.small}>
        State: needs_review — the AI wasn&apos;t confident enough (score &lt; 0.75 or
        confidence &lt; 0.4), so a human must approve (→ delivered) or reject
        (terminal). Demo/seed data never lands here.
      </Text>
      <Button title="Reload queue" onPress={() => void load()} />
      {message ? <Text style={T.small}>{message}</Text> : null}
      <FlatList
        data={queue}
        keyExtractor={(item) => item.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void load()} />}
        contentContainerStyle={{ gap: 10 }}
        renderItem={({ item }) => {
          const cert = certaintyColors(item.certainty_label);
          return (
            <View style={T.card}>
              <Text onPress={() => void open(item)}>
                <Text style={[T.badge, { backgroundColor: cert.bg, color: cert.fg }]}>
                  {item.certainty_label}
                </Text>
                {"  "}
                <Text style={T.body}>{(item.body ?? "").slice(0, 110)}…</Text>
              </Text>
            </View>
          );
        }}
      />
    </View>
  );
}
