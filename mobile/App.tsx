/** NewNews field app: ingest, deliver, review, track — same API as the website. */

import { useEffect, useState } from "react";
import { Button, Text, TextInput, View } from "react-native";
import AsyncStorage from "@react-native-async-storage/async-storage";
import DeliverScreen from "./components/DeliverScreen";
import IngestScreen from "./components/IngestScreen";
import ReviewScreen from "./components/ReviewScreen";
import TrackScreen from "./components/TrackScreen";
import { DEFAULT_SETTINGS, Settings } from "./lib/api";
import { C, T } from "./lib/theme";

const STORAGE_KEY = "newnews-settings-v1";

type Tab = "ingest" | "deliver" | "review" | "track" | "settings";

const TABS: { id: Tab; emoji: string; name: string }[] = [
  { id: "ingest", emoji: "✏️", name: "Ingest" },
  { id: "deliver", emoji: "📻", name: "Deliver" },
  { id: "review", emoji: "⚖️", name: "Review" },
  { id: "track", emoji: "🔍", name: "Track" },
  { id: "settings", emoji: "⚙️", name: "Settings" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("ingest");
  const [settings, setSettings] = useState<Settings>(DEFAULT_SETTINGS);
  const [draft, setDraft] = useState<Settings>(DEFAULT_SETTINGS);
  const [lastItemId, setLastItemId] = useState("");

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
    <View style={{ flex: 1, backgroundColor: C.paper, paddingTop: 44 }}>
      <View
        style={{
          flexDirection: "row",
          backgroundColor: C.card,
          borderBottomWidth: 1,
          borderColor: C.line,
        }}
      >
        {TABS.map((t) => (
          <Text
            key={t.id}
            onPress={() => setTab(t.id)}
            style={{
              flex: 1,
              textAlign: "center",
              paddingVertical: 12,
              fontSize: 12,
              fontWeight: tab === t.id ? "800" : "400",
              color: tab === t.id ? C.accent : C.muted,
              borderBottomWidth: 3,
              borderColor: tab === t.id ? C.accent : "transparent",
            }}
          >
            {t.emoji}{"\n"}
            {t.name}
          </Text>
        ))}
      </View>
      <View style={{ flex: 1 }}>
        {tab === "ingest" && <IngestScreen settings={settings} onAccepted={setLastItemId} />}
        {tab === "deliver" && <DeliverScreen settings={settings} />}
        {tab === "review" && <ReviewScreen settings={settings} />}
        {tab === "track" && <TrackScreen settings={settings} suggestedId={lastItemId} />}
        {tab === "settings" && (
          <View style={T.screen}>
            <Text style={T.h1}>Settings</Text>
            <Text style={T.label}>API base URL</Text>
            <TextInput
              style={T.input}
              value={draft.baseUrl}
              onChangeText={(v) => setDraft({ ...draft, baseUrl: v })}
              autoCapitalize="none"
              placeholder="https://newnews-t54x.onrender.com"
            />
            <Text style={T.small}>Local dev? Use your machine LAN IP, e.g. http://192.168.1.5:8000 (localhost means the phone itself).</Text>
            <Text style={T.label}>Client key (ingest · deliver · live)</Text>
            <TextInput
              style={T.input}
              value={draft.clientKey}
              onChangeText={(v) => setDraft({ ...draft, clientKey: v })}
              autoCapitalize="none"
              secureTextEntry
              placeholder="nn_…"
            />
            <Text style={T.label}>Admin key (review · track)</Text>
            <TextInput
              style={T.input}
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
