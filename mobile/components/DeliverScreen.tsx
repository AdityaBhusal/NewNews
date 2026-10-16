/** Deliver screen: the client's own news — Live (SSE push) or Reload (REST pull). */

import { useEffect, useRef, useState } from "react";
import { Button, FlatList, StyleSheet, Text, View } from "react-native";
import {
  Settings,
  listNews,
  subscribeDeliveries,
  type Delivery,
} from "../lib/api";
import { C, T, certaintyColors, latencyBetween } from "../lib/theme";

function Card({ delivery }: { delivery: Delivery }) {
  const i = delivery.item;
  const cert = certaintyColors(i.certainty_label);
  return (
    <View style={T.card}>
      <View style={T.row}>
        <Text style={[T.badge, { backgroundColor: cert.bg, color: cert.fg }]}>
          {i.certainty_label} · {i.credibility_score ?? "—"}
        </Text>
        {i.editorially_reviewed ? (
          <Text style={[T.badge, { backgroundColor: C.infoSoft, color: C.info }]}>
            ✓ reviewed
          </Text>
        ) : null}
      </View>
      <Text style={T.title}>{i.title || "(untitled)"}</Text>
      {i.summary ? <Text style={T.body}>{i.summary}</Text> : null}
      <Text style={T.small}>
        #{delivery.delivery_id} · {(i.topics || []).join(", ")} · ingest→eligible{" "}
        {latencyBetween(i.created_at, i.eligible_at)}
      </Text>
    </View>
  );
}

export default function DeliverScreen({ settings }: { settings: Settings }) {
  const [items, setItems] = useState<Delivery[]>([]);
  const [live, setLive] = useState(false);
  const [stream, setStream] = useState("off");
  const [message, setMessage] = useState("");
  const stopRef = useRef<(() => void) | null>(null);

  async function reload() {
    if (!settings.clientKey) {
      setMessage("Set the client key in Settings first.");
      return;
    }
    try {
      const data = await listNews(settings, true);
      // Newest first; drop duplicates already on screen.
      setItems((prev) => {
        const seen = new Set(prev.map((d) => d.delivery_id));
        const fresh = data.items.filter((d) => !seen.has(d.delivery_id));
        return [...fresh, ...prev];
      });
      if (data.items.length === 0 && items.length === 0) setMessage("No deliveries yet.");
      else setMessage("");
    } catch (error) {
      setMessage(`Failed: ${error instanceof Error ? error.message : error}`);
    }
  }

  useEffect(() => {
    if (!live) {
      stopRef.current?.();
      stopRef.current = null;
      setStream("off");
      return;
    }
    setStream("connecting…");
    stopRef.current = subscribeDeliveries(
      settings,
      () => {
        setStream("live — update received, reloading…");
        void reload().then(() => setStream("live"));
      },
      (errorMessage) => setStream(`stream error: ${errorMessage}`),
    );
    setStream("live");
    return () => {
      stopRef.current?.();
      stopRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live]);

  return (
    <View style={T.screen}>
      <Text style={T.h1}>Deliveries</Text>
      <View style={T.row}>
        <Button title={live ? "Stop live" : "Go live (SSE)"} onPress={() => setLive((v) => !v)} />
        <Button title="Reload (REST)" onPress={() => void reload()} />
      </View>
      {live ? <Text style={styles.stream}>● {stream}</Text> : null}
      {message ? <Text style={T.small}>{message}</Text> : null}
      <FlatList
        data={items}
        keyExtractor={(d) => String(d.delivery_id)}
        renderItem={({ item }) => <Card delivery={item} />}
        contentContainerStyle={{ gap: 10, paddingBottom: 24 }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  stream: { color: C.good, fontWeight: "700" },
});
