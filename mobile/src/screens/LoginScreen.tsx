import React, { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from "react-native";
import { registerDevice } from "../api";
import { useAuth } from "../context";
import { registerForPushNotifications } from "../notifications";

export default function LoginScreen() {
  const { setAuth } = useAuth();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);

  async function onSubmit() {
    if (code.trim().length < 4) {
      Alert.alert("Install code looks too short", "Check the code in your welcome email.");
      return;
    }
    setBusy(true);
    try {
      const token = await registerForPushNotifications();
      if (!token) {
        Alert.alert(
          "Notifications denied",
          "Without notification permission we can't alert you about falls. Enable in Settings and try again."
        );
        return;
      }
      const platform = Platform.OS === "ios" ? "ios" : "android";
      const res = await registerDevice(code.trim().toUpperCase(), token, platform);
      await setAuth({
        installCode: code.trim().toUpperCase(),
        homeId: res.home_id,
        ownerName: res.owner_name,
      });
    } catch (err: any) {
      Alert.alert("Could not register", String(err?.message ?? err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={styles.root}
    >
      <Text style={styles.title}>Fall Detect</Text>
      <Text style={styles.subtitle}>
        Enter the install code that came with your sensor kit.
      </Text>
      <TextInput
        style={styles.input}
        placeholder="ABC123"
        placeholderTextColor="#aaa"
        value={code}
        onChangeText={setCode}
        autoCapitalize="characters"
        autoCorrect={false}
        maxLength={10}
      />
      <TouchableOpacity
        style={[styles.button, busy && styles.buttonDisabled]}
        onPress={onSubmit}
        disabled={busy}
      >
        {busy ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Continue</Text>}
      </TouchableOpacity>
      <View style={{ height: 24 }} />
      <Text style={styles.hint}>
        You'll be asked to allow notifications next. Allow them so we can let you know if a fall is detected.
      </Text>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, justifyContent: "center", padding: 24, backgroundColor: "#fff" },
  title: { fontSize: 32, fontWeight: "700", marginBottom: 8 },
  subtitle: { fontSize: 16, color: "#444", marginBottom: 24 },
  input: {
    borderWidth: 1,
    borderColor: "#ddd",
    borderRadius: 12,
    padding: 16,
    fontSize: 22,
    letterSpacing: 4,
    textAlign: "center",
    marginBottom: 16,
  },
  button: {
    backgroundColor: "#0066cc",
    paddingVertical: 16,
    borderRadius: 12,
    alignItems: "center",
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: "#fff", fontSize: 16, fontWeight: "600" },
  hint: { fontSize: 13, color: "#666", lineHeight: 18 },
});
