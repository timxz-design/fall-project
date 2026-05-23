/**
 * Entry point — navigation root + push notification wiring.
 *
 * Navigation shape:
 *   - Not logged in → LoginScreen (full screen)
 *   - Logged in    → bottom tabs (Status, History, Settings)
 *   - Push received → AlertScreen pushed on top as modal
 */
import "react-native-gesture-handler";
import React, { useEffect, useState } from "react";
import { ActivityIndicator, View } from "react-native";
import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import * as Notifications from "expo-notifications";

import { AuthProvider, useAuth } from "./src/context";
import LoginScreen from "./src/screens/LoginScreen";
import StatusScreen from "./src/screens/StatusScreen";
import HistoryScreen from "./src/screens/HistoryScreen";
import SettingsScreen from "./src/screens/SettingsScreen";
import AlertScreen from "./src/screens/AlertScreen";
import {
  addForegroundNotificationListener,
  addNotificationResponseListener,
} from "./src/notifications";

const RootStack = createNativeStackNavigator();
const Tabs = createBottomTabNavigator();

function MainTabs() {
  return (
    <Tabs.Navigator
      screenOptions={{
        headerShown: true,
        tabBarActiveTintColor: "#0066cc",
      }}
    >
      <Tabs.Screen name="Status" component={StatusScreen} />
      <Tabs.Screen name="History" component={HistoryScreen} />
      <Tabs.Screen name="Settings" component={SettingsScreen} />
    </Tabs.Navigator>
  );
}

function Root() {
  const { auth, loading } = useAuth();
  const [pendingAlert, setPendingAlert] = useState<{
    eventId: number;
    detectedAt?: string;
  } | null>(null);

  useEffect(() => {
    if (!auth) return;

    // Foreground: a push came in while the app is open.
    const fgSub = addForegroundNotificationListener((n) => {
      const data = n.request.content.data as Record<string, any>;
      const eventId = Number(data?.event_id);
      if (eventId) setPendingAlert({ eventId, detectedAt: data?.detected_at });
    });

    // Background/closed: user tapped a notification.
    const tapSub = addNotificationResponseListener((r) => {
      const data = r.notification.request.content.data as Record<string, any>;
      const eventId = Number(data?.event_id);
      if (eventId) setPendingAlert({ eventId, detectedAt: data?.detected_at });
    });

    return () => {
      fgSub.remove();
      tapSub.remove();
    };
  }, [auth]);

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: "center", alignItems: "center" }}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <NavigationContainer>
      <RootStack.Navigator screenOptions={{ headerShown: false }}>
        {!auth ? (
          <RootStack.Screen name="Login" component={LoginScreen} />
        ) : (
          <RootStack.Screen name="Main" component={MainTabs} />
        )}
      </RootStack.Navigator>

      {pendingAlert && (
        <View
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: "#fff",
          }}
        >
          <AlertScreen
            eventId={pendingAlert.eventId}
            detectedAt={pendingAlert.detectedAt}
            ownerName={auth?.ownerName}
            onDone={() => setPendingAlert(null)}
          />
        </View>
      )}
    </NavigationContainer>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Root />
    </AuthProvider>
  );
}
