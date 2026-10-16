/** Track screen: item status + badges + audit journey, with live SSE updates.
 *
 * Same data as the website's /track page (admin review-detail endpoint). While
 * "live" is on, the app holds the SSE delivery stream open: any `news` event
 * refetches the tracked item, so approvals and stage transitions appear
 * without pulling to refresh.
 */

import { useEffect, useRef, useState } from "react";
import { Button, FlatList, StyleSheet, Text, TextInput, View } from "react-native";
import {
  Settings,
  reviewDetail,
  subscribeDeliveries,
  type AuditEntry,
  type ReviewItem,
} from "../lib/api";

export default function TrackScreen({ settings }: { settings: Settings }) {
  const [itemId, setItemId] = useState("");
  const [item, setItem] = useState<ReviewItem | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [live, setLive] = useState(false);
  const [streamState, setStreamState] = useState("off");
  const [message, setMessage] = useState("");
  const stopRef = useRef<(() => void) | null>(null);

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
      setMessage("");
    } catch (error) {
      setMessage(`Failed: ${error instanceof Error ? error.message : error}`);
    }
  }

  // Live SSE: any delivery on this client key refetches the tracked item.
  useEffect(() => {
    if (!live) {
      stopRef.current?.();
      stopRef.current = null;
      setStreamState("off");
      return;
    }
    if (!settings.clientKey) {
      setMessage("Set the client key in Settings first.");
      setLive(false);
      return;
    }
    if (!item) {
      setMessage("Track an item first, then go live.");
      setLive(false);
      return;
    }
    setStreamState("connecting…");
    const id = item.id;
    stopRef.current = subscribeDeliveries(
      settings,
      () => {
        setStreamState("live — update received, refetching…");
        void track(id).then(() => setStreamState("live"));
      },
      (errorMessage) => setStreamState(`stream error: ${errorMessage}`),
    );
    setStreamState("live");
    return () => {
      stopRef.current?.();
      stopRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  return (
    <View style={styles.container}>
      <TextInput
        style={styles.input}
        value={itemId}
        onChangeText={setItemId}
        autoCapitalize="none"
        placeholder="Item id (from ingest response)"
      />
      <View style={styles.row}>
        <Button title="Track" onPress={() => void track(itemId)} />
        <Button
          title={live ? "Go static" : "Go live"}
          onPress={() => setLive((v) => !v)}
        />
      </View>
      {live ? <Text style={styles.stream}>● SSE: {streamState}</Text> : null}
      {message ? <Text>{message}</Text> : null}
      {item && (
        <View style={styles.card}>
          <Text style={styles.status}>{item.status}</Text>
          <Text>
            certainty {item.certainty_label}
            {item.editorially_reviewed ? " · ✓ editorially reviewed" : ""}
          </Text>
          <Text>
            score {item.credibility_score ?? "—"} · conf{" "}
            {item.credibility_confidence ?? "—"}
          </Text>
          {item.summary ? <Text>{item.summary}</Text> : null}
        </View>
      )}
      <FlatList
        data={audit}
        keyExtractor={(_, i) => String(i)}
        renderItem={({ item: entry }) => (
          <Text style={styles.audit}>
            {entry.event_type} <Text style={styles.stage}>· {entry.stage ?? "?"}</Text>
          </Text>
        )}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 16, gap: 8 },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 6, padding: 8 },
  row: { flexDirection: "row", justifyContent: "space-around" },
  stream: { color: "#1a7f37", fontWeight: "600" },
  card: { borderWidth: 1, borderColor: "#ddd", borderRadius: 8, padding: 12, gap: 4 },
  status: { fontSize: 18, fontWeight: "700" },
  audit: { fontFamily: "monospace", fontSize: 12, paddingVertical: 2 },
  stage: { color: "#666" },
});
