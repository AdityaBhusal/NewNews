/** Deliver screen: the client's own news — LIVE by default (SSE), REST reload as fallback.
 *
 * The stream opens automatically whenever a client key is configured; every
 * `news` frame carries the full item, which is appended straight to the list —
 * no REST refetch per event. If the socket drops (Render proxy, phone sleep),
 * the shared reconnecting stream restores it; Reload remains for a manual
 * full refresh (ack=true).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, FlatList, StyleSheet, Text, View } from "react-native";
import {
  Settings,
  listNews,
  subscribeDeliveries,
  type Delivery,
  type ReviewItem,
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
  const [live, setLive] = useState(true);
  const [stream, setStream] = useState("connecting…");
  const [message, setMessage] = useState("");
  const seenRef = useRef<Set<number>>(new Set());

  const merge = useCallback((incoming: Delivery[]) => {
    setItems((prev) => {
      const fresh = incoming.filter((d) => !seenRef.current.has(d.delivery_id));
      if (fresh.length === 0) return prev;
      for (const d of fresh) seenRef.current.add(d.delivery_id);
      // Incoming is newest-first (delivery ids are monotonic desc order).
      return [...fresh, ...prev];
    });
  }, []);

  const reload = useCallback(async () => {
    if (!settings.clientKey) {
      setMessage("Set the client key in Settings first.");
      return;
    }
    try {
      const data = await listNews(settings, true);
      merge(data.items);
      setMessage(data.count === 0 && seenRef.current.size === 0 ? "No deliveries yet." : "");
    } catch (error) {
      setMessage(`Failed: ${error instanceof Error ? error.message : error}`);
    }
  }, [settings, merge]);

  // Key change (or cleared) resets the list — during render, per the React
  // prop-change pattern; the seen-set clears in the load effect below. The
  // "no key" hint is derived at render.
  const [prevKey, setPrevKey] = useState(settings.clientKey);
  if (settings.clientKey !== prevKey) {
    setPrevKey(settings.clientKey);
    setItems([]);
  }

  // Initial population (REST, ack) — after that SSE drives everything.
  useEffect(() => {
    if (!settings.clientKey) return;
    seenRef.current = new Set();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [settings.clientKey, settings.baseUrl]);

  // Live stream: on by default, reconnects on its own, appends directly from
  // the frame payload (delivery_id + item — no REST roundtrip per event).
  useEffect(() => {
    if (!live || !settings.clientKey) return;
    const stop = subscribeDeliveries(
      settings,
      (deliveryId: number, item?: ReviewItem) => {
        if (!item) {
          void reload(); // payload shape without item: fall back to REST pull
          return;
        }
        if (seenRef.current.has(deliveryId)) return;
        seenRef.current.add(deliveryId);
        setItems((prev) => [{ delivery_id: deliveryId, item }, ...prev]);
        setStream("live");
      },
      (errorMessage) => setStream(errorMessage),
      () => setStream("live"),
    );
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, settings.clientKey, settings.baseUrl]);

  const hint = !settings.clientKey ? "Set the client key in Settings first." : message;

  return (
    <View style={T.screen}>
      <Text style={T.h1}>Deliveries</Text>
      <View style={T.row}>
        <Button
          title={live ? "Pause live" : "Go live (SSE)"}
          onPress={() => {
            if (!live) setStream("connecting…");
            setLive((v) => !v);
          }}
        />
        <Button title="Reload (REST)" onPress={() => void reload()} />
      </View>
      <Text style={styles.stream}>
        ● {settings.clientKey ? stream : "off (no client key)"}
      </Text>
      {hint ? <Text style={T.small}>{hint}</Text> : null}
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
