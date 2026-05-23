# Mobile — Fall Detection MVP

Expo (React Native) app with four screens:

- **Login** — enter install code, register for push, get linked to a home
- **Status** — green "all OK" or red "possible fall" card; auto-refreshes
- **History** — last 100 events; tap any to label
- **Settings** — CSI consent toggle, test alert, debug info, sign out

Plus an **Alert** modal that takes over the whole screen when a push tap
hits the app — three giant buttons (Real fall / False alarm / Not sure).

## Why Expo (and not bare React Native)

You're on Windows, which means no Mac to build native iOS apps. Expo +
EAS Build lets you ship to TestFlight from Windows — the build runs on
Expo's servers and you upload from there. That's the only realistic
iOS path on Windows.

## One-time setup

### 1. Install Node

Download Node 20 LTS from <https://nodejs.org>. Verify:

```powershell
node --version   # should be v20.x or v22.x
npm --version
```

### 2. Install Expo CLI and EAS CLI

```powershell
npm install -g expo eas-cli
```

### 3. Install dependencies

```powershell
cd "C:\Users\nikni\Desktop\fall detect\mobile"
npm install
```

(First install takes a few minutes — lots of native modules.)

### 4. Pick a backend URL

Open `app.json` and find the `extra.backendUrl` field. Set it based on
how you'll test:

- **iOS simulator on a Mac**: `http://localhost:8000`
- **Android emulator on Windows**: `http://10.0.2.2:8000` (the Android
  emulator can't reach `localhost` because that's its own loopback)
- **Real phone on your WiFi**: your laptop's LAN IP, e.g.
  `http://192.168.1.42:8000`. Find it with `ipconfig`.

Make sure the backend (`backend/app.py`) is binding to `0.0.0.0` not
`127.0.0.1` if you want to reach it from another device on your LAN —
edit the `uvicorn.run(..., host=...)` call at the bottom of `app.py`.

## Running in development

For UI iteration (no real push notifications):

```powershell
npm start
```

Press `a` for Android emulator, `i` for iOS simulator (Mac only), or
scan the QR code with the Expo Go app on your phone.

**Caveat:** push notifications don't work in Expo Go on iOS in SDK 53+.
For real push testing you need a development build (see next section).

## Running with real push notifications

Push tokens require a custom dev client, not Expo Go. Build one once
with EAS:

```powershell
eas login                              # log in with your Expo account
eas build:configure                    # one-time, picks Android/iOS
eas build --profile development --platform android
# or for iOS (you'll need your Apple Developer credentials):
eas build --profile development --platform ios
```

Install the resulting .apk (Android) or use TestFlight (iOS).

Once installed, run `npm start` on your laptop — the dev client connects
to it and supports push notifications.

## Project layout

```
mobile/
├── App.tsx                       # navigation + push wiring
├── app.json                      # Expo config (bundle ID, plugins, etc.)
├── package.json
├── tsconfig.json
└── src/
    ├── api.ts                    # backend client
    ├── context.tsx               # AuthProvider, useAuth hook
    ├── notifications.ts          # expo-notifications setup
    ├── storage.ts                # AsyncStorage helpers
    └── screens/
        ├── LoginScreen.tsx
        ├── StatusScreen.tsx
        ├── HistoryScreen.tsx
        ├── SettingsScreen.tsx
        └── AlertScreen.tsx
```

## Known TODOs

1. **Production push notifications.** Currently uses Expo's push service.
   For TestFlight / Play Store, configure native FCM + APNs credentials
   on the Expo project — Expo's docs:
   <https://docs.expo.dev/push-notifications/fcm-credentials/>
2. **Wire up the consent toggle.** UI exists in Settings but there's no
   backend endpoint yet to update `home.consent_csi_capture`. Add a
   `PATCH /home/consent` route in `backend/app.py` in Phase 1.
3. **Real "test alert" via backend.** Settings → Test alert currently
   shows a local notification only. To test the full chain, hit the
   backend webhook with curl (see `RUNNING.md`) — or add a
   `POST /events/test` route that creates a server-side event with
   `event_type=test` and fans out the FCM stub.
4. **Owner name display.** The Status screen says "your linked home" by
   default; consider adding nickname/room selection during onboarding.
5. **Background label submission.** Right now labels submit while the
   app is in the foreground. If the network is flaky, queue the label
   in AsyncStorage and retry on next foreground.

## Testing the integrated chain (laptop)

Once the app is running on a real device or emulator AND the backend
is running on your laptop (see `RUNNING.md`):

1. Create a home via the backend admin API — note the install code.
2. Open the app, enter the install code on the Login screen, allow
   notifications.
3. The Login screen should disappear and Status should show "Everything's OK".
4. Trigger a fall event via curl (see `RUNNING.md` Path B).
5. The backend logs `[FCM stub] would send to ExponentPushToken[...]`
   — but in dev with Expo's push service connected, the push will
   actually arrive on the device after a few seconds.
6. Tap the notification → AlertScreen takes over → tap "False alarm"
   → check the History screen, event is labeled.

Sources cited: [Expo docs — push notifications](https://docs.expo.dev/push-notifications/overview/), [Expo docs — FCM credentials](https://docs.expo.dev/push-notifications/fcm-credentials/).
