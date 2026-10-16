/** Ingest screen: text story + optional photo → POST /items → POST /media. */

import { useState } from "react";
import {
  ActivityIndicator,
  Button,
  Image,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import * as ImagePicker from "expo-image-picker";
import * as Clipboard from "expo-clipboard";
import { Settings, createItem, uploadMedia } from "../lib/api";
import { randomEntry } from "../lib/catalog";
import { T } from "../lib/theme";

interface Picked {
  uri: string;
  name: string;
  mimeType: string;
}

export default function IngestScreen({
  settings,
  onAccepted,
}: {
  settings: Settings;
  onAccepted: (id: string) => void;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [sourceKey, setSourceKey] = useState("");
  const [photo, setPhoto] = useState<Picked | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState("");
  const [lastId, setLastId] = useState<string | null>(null);

  function dice() {
    const entry = randomEntry();
    setTitle(entry.title);
    setBody(entry.body);
    setSourceKey(`app-${Date.now()}`);
    setResult(
      `Dice rolled: stub predicts ${entry.certainty} certainty → ` +
        (entry.expect === "auto" ? "auto-validates." : "goes to human review."),
    );
  }

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
      message += "\nOpen Track (prefilled) or watch /live.";
      setResult(message);
      setLastId(item.id);
      onAccepted(item.id);
      setSourceKey(`app-${Date.now()}`);
    } catch (error) {
      setResult(`Failed: ${error instanceof Error ? error.message : error}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ScrollView contentContainerStyle={T.screen}>
      <Text style={T.h1}>New story</Text>
      <View style={T.row}>
        <Button title="🎲 Random news" onPress={dice} />
      </View>
      <Text style={T.label}>Title (optional)</Text>
      <TextInput style={T.input} value={title} onChangeText={setTitle} />
      <Text style={T.label}>Body *</Text>
      <TextInput
        style={[T.input, { minHeight: 120, textAlignVertical: "top" }]}
        value={body}
        onChangeText={setBody}
        multiline
        placeholder="Kathmandu, …"
      />
      <Text style={T.label}>Source key (blank = auto)</Text>
      <TextInput
        style={T.input}
        value={sourceKey}
        onChangeText={setSourceKey}
        placeholder="auto-generated on submit"
      />
      <View style={T.row}>
        <Button title="Camera" onPress={() => void pick(true)} />
        <Button title="Gallery" onPress={() => void pick(false)} />
        {photo && <Button title="Remove" onPress={() => setPhoto(null)} />}
      </View>
      {photo && (
        <Image source={{ uri: photo.uri }} style={{ height: 200, borderRadius: 12 }} resizeMode="cover" />
      )}
      {busy ? (
        <ActivityIndicator />
      ) : (
        <Button title="Submit story" onPress={() => void submit()} />
      )}
      {result ? (
        <View style={T.card}>
          <Text style={T.body}>{result}</Text>
        </View>
      ) : null}
      {lastId && !busy ? (
        <View style={T.row}>
          <Button
            title="Copy item ID"
            onPress={() => {
              void Clipboard.setStringAsync(lastId).then(() =>
                setResult((m) => m + "\nID copied — Track is already prefilled."),
              );
            }}
          />
        </View>
      ) : null}
    </ScrollView>
  );
}
