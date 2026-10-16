/** Editorial screen: review queue → detail (AI assessment + audit) → approve/reject. */

import { useCallback, useState } from "react";
import {
  Button,
  FlatList,
  RefreshControl,
  StyleSheet,
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
  type ReviewItem,
} from "../lib/api";

export default function ReviewScreen({ settings }: { settings: Settings }) {
  const [queue, setQueue] = useState<ReviewItem[]>([]);
  const [selected, setSelected] = useState<ReviewItem | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
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
          ? `Approved → ${updated.status}. Pipeline resumes at enrichment; watch /live.`
          : "Rejected (terminal).",
      );
      setSelected(null);
      setAudit([]);
      await load();
    } catch (error) {
      setMessage(`Failed: ${error instanceof Error ? error.message : error}`);
    }
  }

  if (selected) {
    return (
      <View style={styles.container}>
        <Button title="← Back to queue" onPress={() => setSelected(null)} />
        <Text style={styles.title}>{selected.title ?? "(untitled)"}</Text>
        <Text style={styles.badges}>
          certainty {selected.certainty_label} · score {selected.certainty_label === "unassessed" ? "—" : selected.credibility_score}
          {selected.editorially_reviewed ? " · ✓ reviewed" : ""}
        </Text>
        <Text>{selected.body}</Text>
        {selected.validation_rationale ? (
          <Text style={styles.rationale}>AI: {selected.validation_rationale}</Text>
        ) : null}
        <Text style={styles.sub}>Audit trail</Text>
        <FlatList
          data={audit}
          keyExtractor={(_, i) => String(i)}
          renderItem={({ item }) => (
            <Text style={styles.audit}>
              {item.stage ?? "?"} · {item.event_type}
            </Text>
          )}
        />
        <TextInput
          style={styles.input}
          value={note}
          onChangeText={setNote}
          placeholder="Note (approve) or reason (reject, required)"
        />
        <View style={styles.row}>
          <Button title="Approve" onPress={() => void decide("approve")} />
          <Button title="Reject" color="#c92a2a" onPress={() => void decide("reject")} />
        </View>
        {message ? <Text>{message}</Text> : null}
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Button title="Reload queue" onPress={() => void load()} />
      {message ? <Text>{message}</Text> : null}
      <FlatList
        data={queue}
        keyExtractor={(item) => item.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => void load()} />}
        renderItem={({ item }) => (
          <Text style={styles.row_item} onPress={() => void open(item)}>
            {item.certainty_label} · {(item.body ?? "").slice(0, 90)}…
          </Text>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16, gap: 8 },
  title: { fontSize: 18, fontWeight: "700" },
  badges: { color: "#495057" },
  rationale: { fontStyle: "italic", backgroundColor: "#f1f3f5", padding: 8, borderRadius: 6 },
  sub: { fontWeight: "700", marginTop: 8 },
  audit: { fontFamily: "monospace", fontSize: 12 },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 6, padding: 8 },
  row: { flexDirection: "row", justifyContent: "space-around" },
  row_item: { paddingVertical: 12, borderBottomWidth: 1, borderColor: "#eee" },
});
