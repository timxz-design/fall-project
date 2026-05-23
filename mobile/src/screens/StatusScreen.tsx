import React, { useCallback, useEffect, useState } from "react";
import {
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { getEvents, EventSummary } from "../api";
import { useAuth } from "../context";

/**
 * The "everything OK / something happened" screen.
 *
 * - If the most recent event is recent AND unlabeled → red alert state.
 * - Otherwise → green "all good" state with last-check timestamp.
 *
 * When a push notification arrives, AlertScreen takes over (modal). This
 * screen reflects whatever's stored on the backend.
 */
export default function StatusScreen() {
  const { auth } = useAuth();
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!auth) return;
    setRefreshing(true);
    setError(null);
    try {
      const list = await getEvents(auth.homeId, 5);
      setEvents(list);
    } catch (err: any) {
      setError(String(err?.message ?? err));
    } finally {
      setRefreshing(false);
    }
  }, [auth]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [refresh]);

  // "Active alert" = newest event, unlabeled, within the last 10 minutes
  const latest = events[0];
  const isActiveAlert =
    latest &&
    latest.label === null &&
    Date.now() - new Date(latest.detected_at).getTime() < 10 * 60 * 1000;

  return (
    <ScrollView
      contentContainerStyle={styles.root}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}
    >
      {isActiveAlert ? (
        <View style={[styles.statusCard, styles.alertCard]}>
          <Text style={styles.alertEmoji}>⚠️</Text>
          <Text style={styles.alertTitle}>Possible fall detected</Text>
          <Text style={styles.alertSub}>
            at {auth?.ownerName || "your linked home"} —{" "}
            {new Date(latest.detected_at).toLocaleTimeString()}
          </Text>
          <Text style={styles.alertHint}>Tap the notification or pull down to refresh after checking on them.</Text>
        </View>
      ) : (
        <View style={[styles.statusCard, styles.okCard]}>
          <Text style={styles.alertEmoji}>✅</Text>
          <Text style={styles.okTitle}>Everything's OK</Text>
          <Text style={styles.okSub}>
            Monitoring {auth?.ownerName || "your home"}.
          </Text>
        </View>
      )}

      {error && <Text style={styles.errorText}>Connection issue: {error}</Text>}

      <Text style={styles.sectionTitle}>Recent events</Text>
      {events.length === 0 && !refreshing && (
        <Text style={styles.empty}>No events in the last 7 days. That's a good thing.</Text>
      )}
      {events.map((e) => (
        <View key={e.id} style={styles.eventRow}>
          <Text style={styles.eventTime}>
            {new Date(e.detected_at).toLocaleString()}
          </Text>
          <Text style={styles.eventLabel}>
            {e.label === "real_fall"
              ? "Real fall"
              : e.label === "false_alarm"
              ? "False alarm"
              : e.label === "test"
              ? "Test"
              : e.label === "unsure"
              ? "Marked unsure"
              : "Unlabeled — tap History to label"}
          </Text>
        </View>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { padding: 16, gap: 12 },
  statusCard: { padding: 24, borderRadius: 16, alignItems: "center", marginTop: 12 },
  okCard: { backgroundColor: "#e8f5e9" },
  alertCard: { backgroundColor: "#ffebee" },
  alertEmoji: { fontSize: 56, marginBottom: 8 },
  okTitle: { fontSize: 22, fontWeight: "700", color: "#1b5e20" },
  okSub: { fontSize: 15, color: "#33691e", marginTop: 6 },
  alertTitle: { fontSize: 22, fontWeight: "700", color: "#b71c1c" },
  alertSub: { fontSize: 15, color: "#c62828", marginTop: 6 },
  alertHint: { fontSize: 13, color: "#444", marginTop: 12, textAlign: "center" },
  errorText: { color: "#b71c1c", fontSize: 13, paddingHorizontal: 4 },
  sectionTitle: { fontSize: 16, fontWeight: "700", marginTop: 12, marginBottom: 4 },
  empty: { color: "#666", fontStyle: "italic", padding: 8 },
  eventRow: {
    padding: 12,
    borderRadius: 10,
    backgroundColor: "#f6f6f8",
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  eventTime: { fontSize: 13, color: "#444" },
  eventLabel: { fontSize: 13, fontWeight: "600" },
});
