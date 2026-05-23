/**
 * Persisted local state. Two values: install code and home_id.
 * If both are present on boot, the user skips the login screen.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";

const K_INSTALL_CODE = "install_code";
const K_HOME_ID = "home_id";
const K_OWNER_NAME = "owner_name";
const K_PUSH_TOKEN = "push_token";

export interface StoredAuth {
  installCode: string;
  homeId: number;
  ownerName: string;
}

export async function saveAuth(a: StoredAuth): Promise<void> {
  await AsyncStorage.multiSet([
    [K_INSTALL_CODE, a.installCode],
    [K_HOME_ID, String(a.homeId)],
    [K_OWNER_NAME, a.ownerName],
  ]);
}

export async function loadAuth(): Promise<StoredAuth | null> {
  const values = await AsyncStorage.multiGet([K_INSTALL_CODE, K_HOME_ID, K_OWNER_NAME]);
  const map = Object.fromEntries(values);
  if (!map[K_INSTALL_CODE] || !map[K_HOME_ID]) return null;
  return {
    installCode: map[K_INSTALL_CODE]!,
    homeId: Number(map[K_HOME_ID]),
    ownerName: map[K_OWNER_NAME] ?? "",
  };
}

export async function clearAuth(): Promise<void> {
  await AsyncStorage.multiRemove([K_INSTALL_CODE, K_HOME_ID, K_OWNER_NAME, K_PUSH_TOKEN]);
}

export async function savePushToken(token: string): Promise<void> {
  await AsyncStorage.setItem(K_PUSH_TOKEN, token);
}

export async function loadPushToken(): Promise<string | null> {
  return AsyncStorage.getItem(K_PUSH_TOKEN);
}
