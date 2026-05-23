import React, { useCallback, useEffect, useState } from "react";
import {
  Alert,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from "react-native";
import { getEvents, labelEvent, EventSummary, LabelValue } from "../api";
import { useAuth } from "../context";

/**
 * Last 7 days of events. Tap any unlabeled row to label it.
 */
export default function HistoryScreen() {
  const { auth } = useAuth();
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    if (!auth) return;
    setRefreshing(true);
    try {
      const list = await getEvents(auth.homeId, 100);
      setEvents(list);
    } catch (err: any) {
      Alert.alert("Couldn't load events", String(err?.message ?? err));
    } finally {
      setRefreshing(false);
    }
  }, [auth]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function onLabel(eventId: number, label: LabelValue) {
    try {
      await labelEvent(eventId, label);
      // Optimistically update locally
      setEvents((prev) =>
        prev.map((e) =>
          e.id === eventId
            ? { ...e, label, label_source: "user", labeled_at: new Date().toISOString() }
            : e
        )
      );
    } catch (err: any) {
      Alert.alert("Couldn't save label", String(err?.message ?? err));
    }
  }

  function promptLabel(eventId: number) {
    Alert.alert("Was this a real fall?", "Your answer helps us improve detection.", [
      { text: "Real fall", onPress: () => onLabel(eventId, "real_fall") },
      { text: "False alarm", onPress: () => onLabel(eventId, "false_alarm") },
      { text: "Not sure", onPress: () => onLabel(eventId, "unsure") },
      { text: "Cancel", style: "cancel" },
    ]);
  }

  return (
    <FlatList
      data={events}
      keyExtractor={(e) => String(e.id)}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={refresh} />}
      contentContainerStyle={{ padding: 16, gap: 8 }}
      ListEmptyComponent={
        !refreshing ? (
          <Text style={styles.empty}>No events recorded yet.</Text>
        ) : null
      }
      renderItem={({ item }) => {
        const unlabeled = item.label === null;
        return (
          <TouchableOpacity
            style={[styles.row, unlabeled && styles.rowUnlabeled]}
            onPress={() => promptLabel(item.id)}
          >
            <View style={{ flex: 1 }}>
              <Text style={styles.rowTime}>
                {new Date(item.detected_at).toLocaleString()}
              </Text>
              <Text style={styles.rowConf}>
                Confidence: {item.confidence !== null ? item.confidence.toFixed(2) : "—"}
              </Text>
            </View>
            <Text
              style={[
                styles.rowLabel,
                item.label === "real_fall" && styles.labelRed,
                item.label === "false_alarm" && styles.labelGreen,
              ]}
            >
              {item.label === "real_fall"
                ? "Real fall"
                : item.label === "false_alarm"
                ? "False alarm"
                : item.label === "test"
                ? "Test"
                : item.label === "unsure"
                ? "Unsure"
                : "Tap to label →"}
            </Text>
          </TouchableOpacity>
        );
      }}
    />
  );
}

const styles = StyleSheet.create({
  empty: { color: "#666", fontStyle: "italic", textAlign: "center", marginTop: 32 },
  row: {
    backgroundColor: "#f6f6f8",
    padding: 14,
    borderRadius: 10,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  rowUnlabeled: { backgroundColor: "#fff8e1", borderColor: "#ffd54f", borderWidth: 1 },
  rowTime: { fontSize: 14, fontWeight: "600" },
  rowConf: { fontSize: 12, color: "#666", marginTop: 2 },
  rowLabel: { fontSize: 13, fontWeight: "600", color: "#444" },
  labelRed: { color: "#b71c1c" },
  labelGreen: { color: "#1b5e20" },
});
