/** Ingest screen: text story + optional photo → POST /items → POST /media. */

import { useState } from "react";
import {
  ActivityIndicator,
  Button,
  Image,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import { Settings, createItem, uploadMedia } from "../lib/api";

interface Picked {
  uri: string;
  name: string;
  mimeType: string;
}

export default function IngestScreen({ settings }: { settings: Settings }) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [sourceKey, setSourceKey] = useState(`app-${Date.now()}`);
  const [photo, setPhoto] = useState<Picked | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<string>("");

  async function pick(fromCamera: boolean) {
    const permission = fromCamera
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      setResult("Permission denied.");
      return;
    }
    const launch = fromCamera
      ? ImagePicker.launchCameraAsync
      : ImagePicker.launchImageLibraryAsync;
    const picked = await launch({ quality: 0.8 });
    if (picked.canceled || picked.assets.length === 0) return;
    const asset = picked.assets[0];
    const name = asset.fileName ?? `photo-${Date.now()}.jpg`;
    setPhoto({ uri: asset.uri, name, mimeType: asset.mimeType ?? "image/jpeg" });
  }

  async function submit() {
    if (!settings.clientKey) {
      setResult("Set the client key in Settings first.");
      return;
    }
    if (!body.trim()) {
      setResult("Body is required.");
      return;
    }
    setBusy(true);
    setResult("");
    try {
      const item = await createItem(settings, {
        title: title.trim() || undefined,
        body: body.trim(),
        source_key: sourceKey.trim() || `app-${Date.now()}`,
        source: "expo-app",
      });
      let message = `Accepted: ${item.id} (${item.status})`;
      if (item.duplicate) message += " — duplicate of an existing item";
      if (photo) {
        try {
          const media = await uploadMedia(settings, item.id, photo);
          message += `\nMedia attached: ${media.kind}, ${media.size_bytes} bytes — extraction runs before assessment.`;
        } catch (error) {
          // Worker may have claimed extract_media already (attach-while-received race).
          message += `\nMedia upload failed: ${error instanceof Error ? error.message : error}`;
        }
      }
      message += "\nWatch it arrive on the /live website page.";
      setResult(message);
      setSourceKey(`app-${Date.now()}`);
    } catch (error) {
      setResult(`Failed: ${error instanceof Error ? error.message : error}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.label}>Title (optional)</Text>
      <TextInput style={styles.input} value={title} onChangeText={setTitle} />
      <Text style={styles.label}>Body *</Text>
      <TextInput
        style={[styles.input, styles.body]}
        value={body}
        onChangeText={setBody}
        multiline
        placeholder="Kathmandu, …"
      />
      <Text style={styles.label}>Source key</Text>
      <TextInput style={styles.input} value={sourceKey} onChangeText={setSourceKey} />
      <View style={styles.row}>
        <Button title="Camera" onPress={() => void pick(true)} />
        <Button title="Gallery" onPress={() => void pick(false)} />
        {photo && <Button title="Remove" onPress={() => setPhoto(null)} />}
      </View>
      {photo && (
        <Image source={{ uri: photo.uri }} style={styles.preview} resizeMode="contain" />
      )}
      {busy ? (
        <ActivityIndicator />
      ) : (
        <Button title="Submit story" onPress={() => void submit()} />
      )}
      {result ? <Text style={styles.result}>{result}</Text> : null}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, gap: 4 },
  label: { fontWeight: "600", marginTop: 8 },
  input: { borderWidth: 1, borderColor: "#ccc", borderRadius: 6, padding: 8 },
  body: { minHeight: 120, textAlignVertical: "top" },
  row: { flexDirection: "row", justifyContent: "space-around", marginVertical: 8 },
  preview: { height: 200, marginVertical: 8 },
  result: { marginTop: 12, backgroundColor: "#f1f3f5", padding: 10, borderRadius: 6 },
});
