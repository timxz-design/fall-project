/**
 * Push notification setup using expo-notifications.
 *
 * For development we use Expo's push service (free, no Firebase needed for
 * dev builds). For production / TestFlight builds, configure FCM and APNs
 * credentials in your Expo project per:
 *   https://docs.expo.dev/push-notifications/fcm-credentials/
 *
 * What this module does:
 * - Requests permission
 * - Gets a push token (Expo or device token, depending on build profile)
 * - Sets up foreground notification handling
 * - Returns a hook for attaching to notification taps
 */
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";
import { savePushToken } from "./storage";

// Show notifications even while the app is foregrounded
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

export async function registerForPushNotifications(): Promise<string | null> {
  if (!Device.isDevice) {
    console.warn("[notifications] running in simulator — push tokens are not real");
  }

  // Android needs an explicit channel so notifications appear at high priority
  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("fall-alerts", {
      name: "Fall alerts",
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#d93025",
      sound: "default",
    });
  }

  const existing = await Notifications.getPermissionsAsync();
  let status = existing.status;
  if (status !== "granted") {
    const result = await Notifications.requestPermissionsAsync();
    status = result.status;
  }
  if (status !== "granted") {
    console.warn("[notifications] permission denied");
    return null;
  }

  // Get the Expo push token. For production with native FCM/APNs creds
  // configured, this will be backed by a real platform token.
  try {
    const token = await Notifications.getExpoPushTokenAsync();
    await savePushToken(token.data);
    return token.data;
  } catch (err) {
    console.error("[notifications] getExpoPushTokenAsync failed", err);
    return null;
  }
}

// Re-export the listeners so screens can subscribe to notification taps.
export const addNotificationResponseListener = Notifications.addNotificationResponseReceivedListener;
export const addForegroundNotificationListener = Notifications.addNotificationReceivedListener;
