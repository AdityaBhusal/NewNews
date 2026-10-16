/** NewNews field app: ingest stories + editorial review, same API as the website. */

import { useEffect, useState } from "react";
import { Button, StyleSheet, Text, TextInput, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import IngestScreen from "./components/IngestScreen";
import ReviewScreen from "./components/ReviewScreen";
import TrackScreen from "./components/TrackScreen";
import { DEFAULT_SETTINGS, Settings } from "./lib/api";

const STORAGE_KEY = "newnews-settings-v1";

type Tab = "ingest" | "review" | "track" | "settings";

export default function App() {
  const [tab, setTab] = useState<Tab>("ingest");
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [draft, setDraft] = useState<Settings>(DEFAULT_SETTINGS);

  useEffect(() => {
    void AsyncStorage.getItem(STORAGE_KEY).then((raw) => {
      if (!raw) return;
      try {
        const saved = { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
        setSettings(saved);
        setDraft(saved);
      } catch {
        // Corrupt prefs: keep defaults.
      }
    });
  }, []);

  function save() {
    const cleaned = {
      baseUrl: draft.baseUrl.trim().replace(/\/$/, ""),
      clientKey: draft.clientKey.trim(),
      adminKey: draft.adminKey.trim(),
    };
    setSettings(cleaned);
    setDraft(cleaned);
    void AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(cleaned));
  }

  return (
    <View style={styles.root}>
      <View style={styles.tabs}>
        {(["ingest", "review", "track", "settings"] as Tab[]).map((t) => (
          <Text
            key={t}
            onPress={() => setTab(t)}
            style={[styles.tab, tab === t && styles.active]}
          >
            {t === "ingest"
              ? "Ingest"
              : t === "review"
                ? "Review"
                : t === "track"
                  ? "Track"
                  : "Settings"}
          </Text>
        ))}
      </View>
      <View style={styles.body}>
        {tab === "ingest" && <IngestScreen settings={settings} />}
        {tab === "review" && <ReviewScreen settings={settings} />}
        {tab === "track" && <TrackScreen settings={settings} />}
        {tab === "settings" && (
          <View style={styles.form}>
            <Text style={styles.label}>API base URL</Text>
            <TextInput
              style={styles.input}
              value={draft.baseUrl}
              onChangeText={(v) => setDraft({ ...draft, baseUrl: v })}
              autoCapitalize="none"
              placeholder="https://newnews-t54x.onrender.com"
            />
            <Text style={styles.hint}>Local dev? Use your machine LAN IP, e.g. http://192.168.1.5:8000 (localhost means the phone itself).</Text>
            <Text style={styles.label}>Client key (ingest)</Text>
            <TextInput
              style={styles.input}
              value={draft.clientKey}
              onChangeText={(v) => setDraft({ ...draft, clientKey: v })}
              autoCapitalize="none"
              secureTextEntry
              placeholder="nn_…"
            />
            <Text style={styles.label}>Admin key (review)</Text>
            <TextInput
              style={styles.input}
              value={draft.adminKey}
              onChangeText={(v) => setDraft({ ...draft, adminKey: v })}
              autoCapitalize="none"
              secureTextEntry
            />
            <Button title="Save" onPress={save} />
          </View>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, paddingTop: 48 },
  tabs: { flexDirection: "row", justifyContent: "space-around", paddingVertical: 10, borderBottomWidth: 1, borderColor: "#ddd" },
  tab: { fontSize: 16, padding: 6, color: "#666" },
  active: { fontWeight: "700", color: "#000" },
  body: { flex: 1 },
  form: { padding: 16, gap: 4 },
  label: { fontWeight: "600", marginTop: 8 },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 6, padding: 8 },
  hint: { fontSize: 12, color: "#666" },
});
