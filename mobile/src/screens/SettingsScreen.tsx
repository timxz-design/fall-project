import React from "react";
import {
  Alert,
  ScrollView,
  StyleSheet,
  Switch,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import * as Notifications from "expo-notifications";
import { useAuth } from "../context";
import { __baseUrl } from "../api";

/**
 * Settings: consent toggle, test alert, sign out, debug info.
 *
 * The CSI capture consent toggle is currently UI-only — the backend has the
 * `consent_csi_capture` field on the Home record but no endpoint to update
 * it from the app yet. TODO: add PATCH /home/consent in Phase 1.
 */
export default function SettingsScreen() {
  const { auth, signOut } = useAuth();
  const [csiConsent, setCsiConsent] = React.useState(false);

  async function onTestAlert() {
    await Notifications.scheduleNotificationAsync({
      content: {
        title: "Test alert",
        body: "This is what a real fall alert looks like.",
        data: { test: true },
      },
      trigger: { seconds: 2 } as any,
    });
    Alert.alert(
      "Test scheduled",
      "You'll receive a sample alert in 2 seconds. This tests the on-device notification path. A full end-to-end test requires triggering an event in the backend."
    );
  }

  function onSignOut() {
    Alert.alert("Sign out?", "You'll need to re-enter your install code to use the app again.", [
      { text: "Cancel", style: "cancel" },
      { text: "Sign out", style: "destructive", onPress: signOut },
    ]);
  }

  return (
    <ScrollView contentContainerStyle={{ padding: 16, gap: 16 }}>
      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Linked home</Text>
        <Text style={styles.value}>{auth?.ownerName || "—"}</Text>
        <Text style={styles.value}>Install code: {auth?.installCode}</Text>
      </View>

      <View style={styles.section}>
        <View style={styles.toggleRow}>
          <View style={{ flex: 1, paddingRight: 12 }}>
            <Text style={styles.toggleLabel}>Help improve detection</Text>
            <Text style={styles.toggleHint}>
              Share anonymous sensor data around alerts to help us reduce false alarms over time. Never includes camera or microphone — only WiFi signal patterns.
            </Text>
          </View>
          <Switch value={csiConsent} onValueChange={setCsiConsent} />
        </View>
      </View>

      <TouchableOpacity style={styles.button} onPress={onTestAlert}>
        <Text style={styles.buttonText}>Send test alert</Text>
      </TouchableOpacity>

      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Debug</Text>
        <Text style={styles.value}>Backend: {__baseUrl}</Text>
        <Text style={styles.value}>Home ID: {auth?.homeId}</Text>
      </View>

      <TouchableOpacity style={[styles.button, styles.dangerButton]} onPress={onSignOut}>
        <Text style={[styles.buttonText, styles.dangerText]}>Sign out</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  section: { backgroundColor: "#f6f6f8", padding: 16, borderRadius: 12 },
  sectionLabel: { fontSize: 12, color: "#666", textTransform: "uppercase", marginBottom: 8 },
  value: { fontSize: 15, color: "#222", marginVertical: 2 },
  toggleRow: { flexDirection: "row", alignItems: "center" },
  toggleLabel: { fontSize: 15, fontWeight: "600" },
  toggleHint: { fontSize: 12, color: "#666", marginTop: 4, lineHeight: 16 },
  button: {
    backgroundColor: "#0066cc",
    paddingVertical: 14,
    borderRadius: 12,
    alignItems: "center",
  },
  buttonText: { color: "#fff", fontSize: 16, fontWeight: "600" },
  dangerButton: { backgroundColor: "#fff", borderColor: "#d93025", borderWidth: 1 },
  dangerText: { color: "#d93025" },
});
