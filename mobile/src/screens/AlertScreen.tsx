import React, { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { labelEvent, LabelValue } from "../api";

interface Props {
  eventId: number;
  detectedAt?: string;
  ownerName?: string;
  onDone: () => void;
}

/**
 * Full-screen modal shown when a fall alert push is tapped. Three giant
 * label buttons — one tap, done. Designed to be usable while panicking.
 */
export default function AlertScreen({ eventId, detectedAt, ownerName, onDone }: Props) {
  const [busy, setBusy] = useState<LabelValue | null>(null);

  async function onPick(label: LabelValue) {
    setBusy(label);
    try {
      await labelEvent(eventId, label);
      onDone();
    } catch (err: any) {
      Alert.alert("Couldn't save", String(err?.message ?? err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <View style={styles.root}>
      <Text style={styles.emoji}>⚠️</Text>
      <Text style={styles.title}>Possible fall detected</Text>
      <Text style={styles.subtitle}>
        at {ownerName || "your home"}
        {detectedAt ? ` — ${new Date(detectedAt).toLocaleTimeString()}` : ""}
      </Text>
      <Text style={styles.hint}>
        Please check on them. Then tell us:
      </Text>

      <TouchableOpacity
        style={[styles.button, styles.realFall]}
        onPress={() => onPick("real_fall")}
        disabled={busy !== null}
      >
        {busy === "real_fall" ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Real fall</Text>}
      </TouchableOpacity>

      <TouchableOpacity
        style={[styles.button, styles.falseAlarm]}
        onPress={() => onPick("false_alarm")}
        disabled={busy !== null}
      >
        {busy === "false_alarm" ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>False alarm</Text>}
      </TouchableOpacity>

      <TouchableOpacity
        style={[styles.button, styles.unsure]}
        onPress={() => onPick("unsure")}
        disabled={busy !== null}
      >
        {busy === "unsure" ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Not sure</Text>}
      </TouchableOpacity>

      <TouchableOpacity style={styles.dismiss} onPress={onDone}>
        <Text style={styles.dismissText}>Decide later</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, padding: 24, backgroundColor: "#fff", justifyContent: "center", gap: 12 },
  emoji: { fontSize: 80, textAlign: "center", marginBottom: 8 },
  title: { fontSize: 28, fontWeight: "800", textAlign: "center", color: "#b71c1c" },
  subtitle: { fontSize: 16, textAlign: "center", color: "#555", marginBottom: 16 },
  hint: { fontSize: 15, textAlign: "center", color: "#222", marginBottom: 16 },
  button: { paddingVertical: 22, borderRadius: 14, alignItems: "center" },
  realFall: { backgroundColor: "#b71c1c" },
  falseAlarm: { backgroundColor: "#1b5e20" },
  unsure: { backgroundColor: "#6c757d" },
  buttonText: { color: "#fff", fontSize: 20, fontWeight: "700" },
  dismiss: { alignItems: "center", padding: 16, marginTop: 8 },
  dismissText: { color: "#666", fontSize: 14 },
});
