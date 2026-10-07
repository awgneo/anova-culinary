# Anova protocol

How Anova's official Android apps talk to Anova's cloud, read from the apps themselves (`flow build apk`): the Anova Oven app (`.apks/oven`) and the Anova app (`.apks/culinary`). This is the only protocol reference for `anova_api`; Anova's public developer API is a different, reduced API and is not used.

Both apps are React Native and share one device-protocol library, whose TypeScript types ship inside the bundles as JSON schemas. Those schemas are copied to `test/fixtures/schemas/` and the tests validate every payload `anova_api` builds against them. Citations are byte offsets or line numbers in `.apks/*/bundle.js` (Hermes-decompiled), with a grep-able identifier; each claim is marked SEEN (read in the code), SCHEMA (from the embedded types) or INFERRED.

The integration supports the newest protocol of each family only: Precision Oven 2.0 (`oven_v2`) and the third-generation cookers (`a6`, `a7`, `a8`, `a9`). Older shapes are documented only so they can be recognised.

1. [Connection and authentication](#part-1-connection-and-authentication)
2. [Precision Oven](#part-2-precision-oven)
3. [Precision Cooker](#part-3-precision-cooker)

# Part 1: Connection and authentication

## How the Anova Android apps authenticate and talk to the cloud

Sources analysed (read-only, no network calls were made):

| Tag | App | Package | Version | Bundle format |
|---|---|---|---|---|
| **CUL** | Anova (sous vide / Precision Cooker) | `com.anovaculinary.android` | 3.6.7 | `.apks/culinary/bundle.js`, which is **also Hermes-decompiled pseudo-JS**, not plain minified JS |
| **OVN** | Anova Oven | `com.anovaculinary.anovaoven` | 1.2.11 | `.apks/oven/bundle.js` (Hermes-decompiled) |

Citations use `CUL@<byte offset>` / `OVN@<byte offset>` plus a short snippet you can grep for. To read a citation, run
`python3 -c "print(open('bundle.js','rb').read()[OFF-1500:OFF+1500].decode())"`. `grep -o` with large `{0,N}` bounds fails here, because `grep` is ugrep and it hits its complexity limits.

Evidence labels: **[seen]** means read directly in code. **[inferred]** means a reasoned conclusion that the code does not show explicitly. **[schema]** means the item is defined in an embedded ajv JSON schema or protocol library but has no app call site.

The shared protocol schemas I decompiled are in `test/fixtures/schemas/` (the oven command, oven state and user command schemas; the rest can be rebuilt from the bundles): `IOvenCommand`, `IUserCommand`, `IMultiUserCommand`, `OvenStateV1/V2` and `OvenRecipeV1/V2`. Each comes as `*.schema.json` (full) and `*.compact.txt` (one line per definition).

---

### TL;DR for the Home Assistant integration

1. **Auth is only Firebase Auth (project `anova-app`).** There is **no** Anova-issued session/JWT exchange. Every Anova backend takes the **raw Firebase ID token**:
   * WebSocket: `?token=<idToken>`
   * REST: `Authorization: Bearer <idToken>`, or `Firebase-Token: <idToken>`, or a `firebaseJWT` body field
   * Firestore: native SDK

   Your current flow (signInWithPassword, then the securetoken refresh, then WS `?token=`) is the same thing the apps do. The one difference is the API key (see 1.2).
2. The oven app opens: `wss://devices.anovaculinary.io?token=<idToken>&supportedAccessories=APO&platform=android` with **WebSocket subprotocol `ANOVA_V2`**. The sous-vide app uses `supportedAccessories=APC`, has no subprotocol, and its URL contains a harmless `&&`.
3. **Cook history, saved recipes, favorites and user preferences for the oven live in Cloud Firestore (`anova-app`), not on a REST API.** The app reads and writes them directly with the user's ID token:
   * `users/{uid}/oven-cooks`: cook history, written server-side
   * `users/{uid}/favorite-oven-recipes`: bookmarks
   * `oven-recipes` where `userProfileRef == user-profiles/{uid}`: "My recipes"

   Home Assistant can sync with these through the Firestore REST API using the same ID token. This is the "sync with the official app" path.
4. The sous-vide app keeps cook history on REST: `GET https://anovaculinary.io/identities/{uid}/connected-cooks`. Its recipes and favorites are on `https://anovaculinary.io/v1/...`. All of these use `Authorization: Bearer <firebase idToken>`.
5. Personal Access Tokens are created **over this same WebSocket** with `CMD_CREATE_TOKEN` and related commands, using the same Firebase-authenticated session.

---

### 1. Authentication

#### 1.1 Sign-in methods (both apps use `@react-native-firebase/auth` on the native Firebase SDK)

| Method | CUL | OVN | Evidence |
|---|---|---|---|
| Email + password (`signInWithEmailAndPassword`) | yes | yes | OVN@32021363, OVN@32081681; CUL@9741272 (lib) [seen] |
| Sign-up (`createUserWithEmailAndPassword`) | yes | yes | OVN@31963124, CUL@29653805 [seen] |
| Password reset (`sendPasswordResetEmail`) | yes | yes | OVN@31947985 [seen] |
| Google (`@react-native-google-signin`, then `GoogleAuthProvider.credential(idToken)`, then `signInWithCredential`) | yes | yes | `webClientId = '322173998509-vsa6hecaqqp5cjsaja9h3cds1bhgrq3f.apps.googleusercontent.com'` at OVN@85271 and CUL@89731; `signInWithGoogle` / `useSignInWithGoogle` near OVN@31710555 [seen] |
| Facebook (`react-native-fbsdk-next` `LoginManager`, then `FacebookAuthProvider.credential`) | yes | yes | OVN@31547993, `public_profile`, `/me` email lookup; FB app id `837352106284675` (strings.xml) [seen] |
| Apple (`@invertase/react-native-apple-authentication` `appleAuth.performRequest`, then `AppleAuthProvider.credential(identityToken, nonce)`) | yes | yes | OVN@31766808 `apple sign in failed: no identity token` [seen]. `appleAuth` is the iOS module, so on Android this is effectively iOS-only [inferred] |
| Account linking (`auth/account-exists-with-different-credential`, then `fetchSignInMethodsForEmail` and `linkWithCredential`) | yes | yes | OVN@32011500, OVN@32084264; strings `pendingCredential`, `setPendingCredential` [seen] |
| Anonymous, phone, email-link, custom token | library code only | library code only | only inside the RNFirebase module tables (CUL@97xxxxx, OVN@81xxxxx), no app call sites [seen] |

Extra steps after sign-in [seen]:

* **OVN and CUL:** after account creation, `user-profiles/{uid}` is written with `set({accountCreatedAppId: <bundleId>, accountCreatedAppPlatform: 'android'}, {merge:true})`. This is `setAccountCreatedAppInfo` (OVN@31532133, CUL@29645672).
* **Facebook users:** the app calls `POST https://anovaculinary.io/ali/force-verify-email-for-facebook-user` with JSON body `{firebaseJWT: <idToken>}` and a timeout (OVN@31535196, CUL@29628635).
* **CUL only:** `registerFirebaseTokenWithAnova(idToken)` sends `POST https://anovaculinary.io/authenticate` with header **`Firebase-Token: <idToken>`**, body `null` (CUL@29649155, `'Firebase-Token'`). The response is not used for auth; errors are only `console.warn`ed. It registers or creates the Anova identity [inferred].
* **CUL:** `logInWithCredential` returns `{firebaseJWT, isNewUser, emailVerified}` (CUL@29645700). Here `firebaseJWT` is just `user.getIdToken()`.
* Email-verification continue URLs: OVN `https://anovaculinary.com?access_token=…`, CUL `https://recipes.anovaculinary.com?access_token=…` (actionCodeSettings, `handleCodeInApp`). These only matter for UX.

#### 1.2 Firebase project configuration

From `source/resources/res/values/strings.xml`, plus `default_web_client_id` [seen]:

| key | CUL | OVN |
|---|---|---|
| `project_id` | `anova-app` | `anova-app` |
| `google_api_key` / `google_crash_reporting_api_key` | `AIzaSyCGJwHXUhkNBdPkH3OAkjc9-3xMMjvanfU` | **same** |
| `google_app_id` | `1:322173998509:android:a9e5de76bee92127` | `1:322173998509:android:ea694bec308287f4c07d24` |
| `gcm_defaultSenderId` | `322173998509` | `322173998509` |
| `default_web_client_id` | `322173998509-vsa6hecaqqp5cjsaja9h3cds1bhgrq3f.apps.googleusercontent.com` | same |
| `firebase_database_url` | `https://anova-app.firebaseio.com` | same (no RTDB usage found in app JS) |
| `google_storage_bucket` | `anova-app.appspot.com` | same |
| Auth domains in manifest | `anova-app.firebaseapp.com`, **`anova-app-staging-8068f.firebaseapp.com`** | `anova-app.firebaseapp.com`; deep-link hosts `ovenapp.anovaculinary.com`, `ovenapp-staging.anovaculinary.com`, `oven.anovaculinary.com` |
| firebase-auth SDK | 24.0.1 | 23.2.0 |

* The only `AIza…` string inside the JS bundles is `AIzaSyDdVgKwhZl0sTTTLZ7iTmt1r3N2cJLnaDk`. It is the **example text in RNFirebase's type docs**, not a real config (CUL@12640278: `e.g.\n"AIzaSyDdVg…"`).
* The integration's key `AIzaSyB0VNqmJVAeR1fn_NbqqhwSytyMOZ_JO9c` appears **nowhere** in either APK. It probably comes from the iOS app or a web client [inferred]. Both Android apps use `AIzaSyCGJwHX…`.
* Because Firebase Auth runs in the native SDK, its identitytoolkit/securetoken requests carry these headers [seen in `oven/source/sources/com/google/android/gms/internal/p002firebaseauthapi/zzaef.java`]:
  * `X-Android-Package`
  * `X-Android-Cert` (SHA-1 of the signing cert)
  * `X-Client-Version` (`Android/Fallback/X…/FirebaseCore-Android`)
  * `X-Firebase-GMPID` (google_app_id)
  * `X-Firebase-Client`
  * `X-Firebase-Locale`
  * `Accept-Language`
  * `X-Firebase-AppCheck`, only when App Check is active

  If `AIzaSyCGJwHX…` is restricted to Android apps, the request must carry the matching package and cert headers. The signing-cert fingerprints, computed locally from the APK signing block (v2/v3), are:
  * CUL: SHA-1 `826E0D4C041DF7BDE2F94446226FDA57160472A9`
  * OVN: SHA-1 `CBDEEEE8460457C57EFEBCA5C0207A8FC2F03D66`
* **App Check:** no `initializeAppCheck` or provider setup in either app (only RNFirebase's namespace table, OVN@7887969). App Check is not enforced on these calls [inferred].

#### 1.3 Tokens after Firebase: there is no exchange

* There is **no** call that trades the Firebase ID token for an Anova token, at any URL or over the WS [seen: every backend call site listed below passes `getIdToken()` output directly].
* Token refresh is handled by the native SDK's `user.getIdToken()`, called with no `forceRefresh` [seen: OVN `firebaseTokenQueryParam` @~26428883, CUL @15108764]. The SDK uses the refresh token at `securetoken.googleapis.com` when the ID token is near expiry. This matches what `auth.py` does by hand.
* The WS gets a token **only at connect time**. Neither app re-sends a token on an open socket or reconnects on a timer. The token refreshes only on the next reconnect (app foregrounding, Wi-Fi change, or close). What the server does when a connected token expires is unknown. Reconnecting proactively before the 1-hour expiry, as `client.py` does, is the safe approach [inferred].

#### 1.4 `CMD_AUTH_TOKEN` / `AUTH_TOKEN_V2` / `RESPONSE_AUTH`: in-band auth, defined but unused by the apps

The same shared protocol library is bundled in both apps (CUL@12020540, OVN@18425953) and defines:

* `APCCommandType.CMD_AUTH_TOKEN = 'CMD_AUTH_TOKEN'`. Class `CommandAuthToken` with `isValid` requiring `requestId`, `payload.token` and `payload.userId` [seen CUL@12036500].
* `APCCommandType.CMD_AUTH_TOKEN_V2 = 'AUTH_TOKEN_V2'` (**the wire string has no `CMD_` prefix**). Class `CommandAuthTokenV2`: `payload.token` and `payload.supportedAccessories` (array; `areAccessoriesValid` checks it includes `'APC'`).
* APO schema `AuthTokenV2 = {id, type:'AUTH_TOKEN_V2', payload:{token: string, platform: string, supportedAccessories: string[]}}` [schema, IOvenCommand], plus `AuthTokenV2CommandFactory` (OVN@18980714). The factory is exported but **never called** [seen: only the 3 definition/export occurrences].
* OVN legacy constants module (OVN@26541412):

  ```
  CMD_AUTH_TOKEN      = 'AUTH_TOKEN'
  CMD_SEND_OVEN       = 'SEND_OVEN_COMMAND'
  RESPONSE_OVEN_CMD   = 'OVEN_COMMAND_RESPONSE'
  RESPONSE_OVEN_STATE = 'OVEN_STATE'
  RESPONSE_AUTH       = 'AUTH_TOKEN_RESPONSE'
  COMMAND_TIMEOUT_SECONDS = 10
  ```

  Only `COMMAND_TIMEOUT_SECONDS` is referenced. The rest are leftovers from an older oven protocol [seen: no `.CMD_SEND_OVEN;` / `.RESPONSE_AUTH;` references].
* The classes have a `fromDevicesRedisMessage` parser, so this is the server-side/devices library. It shows the server likely also accepts **in-band auth**: connect without `token=`, then send `{"command":"AUTH_TOKEN_V2","requestId":…,"payload":{"token":…,"platform":"android","supportedAccessories":["APO"]}}` [inferred, untested]. **The apps always use the query-string token.**

---

### 2. WebSocket

#### 2.1 URL, query, headers and subprotocol

| | CUL (APC) | OVN (APO) |
|---|---|---|
| Base URL (only one, no env switch in JS) | `wss://devices.anovaculinary.io` (CUL@14978294) | `wss://devices.anovaculinary.io` (OVN@26419600) |
| Built URL | `base + '?' + 'token=<idToken>&' + '&supportedAccessories=APC&platform=' + platform` | `base + '?' + 'token=<idToken>&' + 'supportedAccessories=APO&platform=' + 'android'` |
| Example | `wss://devices.anovaculinary.io?token=eyJ…&&supportedAccessories=APC&platform=android` (note `&&`) | `wss://devices.anovaculinary.io?token=eyJ…&supportedAccessories=APO&platform=android` |
| `platform` | `DeviceSource.IOS='ios'` / `DeviceSource.ANDROID='android'`, else `'UNKNOWN'` (CUL@12009740) | hard-coded `'android'` |
| Subprotocol (`Sec-WebSocket-Protocol`) | none: `new WebSocket(url)` | **`ANOVA_V2`**: `new WebSocket(url, 'ANOVA_V2')` |
| Token missing | connect aborted (`firebaseTokenQueryParam` returns `''`, then return) | same |

Snippets: CUL `'&supportedAccessories=APC&platform='`; OVN `'supportedAccessories=APO&platform='` and `r14 = 'ANOVA_V2'`; both `r4 = 'token='; r3 = '&'` inside `firebaseTokenQueryParam` [seen].

`supportedAccessories` is comma-separated in your integration (`APC,APO`). The apps send exactly one value. The server-side `CommandAuthTokenV2` treats it as a list, so `APC,APO` is plausible [inferred]; your existing client already relies on it.

HTTP layer, from React Native's `WebSocketModule` (jadx `com/facebook/react/modules/websocket/WebSocketModule.java`) [seen]:

* OkHttp (`okhttp/4.12.0` in OVN, `okhttp/4.7.2` in CUL), so `User-Agent: okhttp/<ver>`.
* `connectTimeout` 10 s, `writeTimeout` 10 s, `readTimeout` 0. **No `pingInterval`**, so there are no client WebSocket pings.
* Adds `origin: https://devices.anovaculinary.io` (`getDefaultOrigin`: `wss` maps to `https`) when no origin header is supplied. The JS passes no custom headers.
* Adds a `Cookie` header if the RN cookie jar holds one for that origin (normally none).

#### 2.2 Lifecycle

**OVN `OvenWebsocket`** (OVN@~26400000–26430000) [seen]:

* `useWebsocketListener` listens with `auth().onAuthStateChanged`:
  * signed out: `disconnectIfConnected()`
  * signed in: `setUser(user)`, set `processMessage`, then `connect()`
* `connect()` returns early when the socket is already CONNECTING/OPEN, when `isInitializing` is set, or when there is no user. Otherwise it resets `lastOvenState = {}`, gets the ID token, opens the socket, and wires the handlers:
  * `onopen`: drain the command queue now, then again after `setTimeout(…, 500)`.
  * `onmessage`: if `typeof data === 'string'`, `JSON.parse` it and call `processMessage`.
  * `onclose`: if the close was not requested by the app, call `reconnect()`, which does `sleep(5)` (5 s) and then `connect()`. **Fixed 5 s delay, no backoff, no retry cap.** Then stop the BackgroundTimer.
* `AppState`:
  * `'active'`: `connect()`
  * `'background'`: `BackgroundTimer.start()`, then `disconnectIfConnected()`. **The app holds no socket in the background.**
* NetInfo: on `type==='wifi' && isConnected`, call `connect()`.
* **The client sends nothing on open**: no hello, no subscribe, no heartbeat. Only queued commands go out. `CMD_APO_HEALTHCHECK` / `HealthCheckCommandFactory` exist but are never called [seen].

**CUL `APCWebsocket`** (CUL@15058000–15125000) [seen]:

* Same pattern:
  * `onopen`: log, then `commandProcessor.checkForTasks()`
  * `onclose`: if not requested, `reconnect()` (`sleep(5)`, then `connect()`); also try a BLE fallback for BTLE-only cookers
  * `AppState 'active'`: disconnect, then connect
  * Wi-Fi up: `connect()`
* No pings, no initial message.

**What the server sends.** These are the messages the apps handle; the exact order is not visible client-side [inferred]:

| command | Payload, as consumed by the app | Notes |
|---|---|---|
| `EVENT_APO_WIFI_LIST` | **array** of `{cookerId, name, type, pairedAt}` | OVN `processDeviceList` maps each to `{deviceId: cookerId, deviceName: name, deviceType: type, pairedAt: new Date(pairedAt), connectedTo: 'aws-gen-3'}` (OVN@30283000). An empty list resets the BLE pairing state. This acts as the "device list on connect" [seen] |
| `EVENT_APO_STATE` | `{cookerId, type, state}` | `type` is the oven version (`oven_v1`/`oven_v2`, OVN@18666685). `state` is parsed by `CommonOvenStateModel`; full schema in `test/fixtures/schemas/OvenStateV1/V2`. The app caches it per device in `lastOvenState[cookerId]` [seen] |
| `EVENT_APO_WIFI_ADDED` / `EVENT_APO_WIFI_REMOVED` | `{cookerId, …}` | `isValid` requires `payload.cookerId` [seen] |
| `EVENT_APO_WIFI_FIRMWARE_UPDATE` | `{cookerId, version}` | [seen] |
| `EVENT_USER_STATE` | `{isConnectedToAlexa, isConnectedToGoogleHome, sousVideSubscription, ovenSubscription}` | Class `EventUserState` (OVN@19922000). The app dispatches `setWebsocketUserState`. `ovenSubscription` gates premium features (`hasValidSubscription`) [seen] |
| `EVENT_RECIPE_CONVERTED` `{recipeId}`, `EVENT_RECIPE_CONVERSION_PROGRESS_INFO`, `EVENT_RECIPE_CONVERSION_FAILED`, `EVENT_AI_ASSISTANT_STREAM` | various | Async results of the iot-api REST calls in §4 [seen] |
| `RESPONSE` | `{command:'RESPONSE', requestId, payload:{status, …data}, error?}` | see §2.3 |
| APC side (CUL): `EVENT_APC_WIFI_LIST` (`pairedDevices` with `secret` stripped by the server lib, `omit(['secret'])`), `EVENT_APC_STATE`, `EVENT_APC_WIFI_VERSION`, `EVENT_APC_WIFI_ADDED` (`cookerId,type,pairedAt`), `EVENT_APC_WIFI_REMOVED` | | CUL@12222324 [seen] |

#### 2.3 Requests, `requestId` correlation, responses, timeouts

**OVN wire format** (`formatCommand`, OVN@~26402500) [seen]:

```js
send({
  command:   payloadData.type,                 // e.g. "CMD_APO_START"
  payload:   Object.assign({}, payloadData, { id: deviceId }),
  requestId: uuidv4()
})
// payloadData comes from a *CommandFactory: { id: uuidv4(), type: 'CMD_APO_…', payload: {...} }
// The factory's own `id` is overwritten by deviceId, so payload.id == cookerId.
```

Concrete example:

```json
{"command":"CMD_APO_SET_LAMP","requestId":"8b0…","payload":{"id":"<cookerId>","type":"CMD_APO_SET_LAMP","payload":{"on":true}}}
```

* Account-level commands (tokens and similar) pass `deviceId: null`, which gives `payload.id: null`. `CMD_ADD_USER_WITH_PAIRING` passes `deviceId: ''`. Push-token registration passes the **mobile client id** (§5) as `deviceId` [seen].
* Responses: `processMessage` treats `command === 'RESPONSE'` as a reply and reads:
  * `requestId`
  * `payload.status`; success means `=== 'ok'`
  * the error, from `msg.error || msg.payload.error`

  It then calls `processResponseCommand(requestId, ok, payload, error)`. That resolves with the **whole `payload` object** (e.g. `payload.tokens`, `payload.data`, `payload.userIds`) or rejects with the error string, or `'Unknown error occurred'` if no string is present (OVN@30284426, OVN@26535000) [seen].
* Queue and timeout:
  * `CommandProcessor.queueCommand` pushes onto a FIFO queue that drains only while the socket is OPEN.
  * Commands that have waited more than **`COMMAND_TIMEOUT_SECONDS = 10`** (`differenceInSeconds`) are dropped.
  * `enqueueCommand` races the send against `timeout(10)`, which raises `'timeout error after …'`. On failure it calls `drainOutstandingRequests()` to clear the queue [seen].
* Before stage-related commands (`START_STAGE`, `SET_TIMER`, `SET_PROBE`, `SET_HEATING_ELEMENTS`, `SET_TEMPERATURE_BULBS`, `SET_STEAM_GENERATORS`, `SET_FAN`, `UPDATE_COOK_STAGE(S)`), the app records `markUserInteraction()` as a local timestamp. Nothing is sent for it.

**CUL wire format** (`CommandProcessor.sendCommand`, CUL@15126000) [seen]:

```js
send({ command, requestId: <uuid A>, payload: Object.assign({}, payload, { requestId: <uuid B, freshly generated> }) })
```

* APC payloads are flat: `{cookerId, type, …}`, for example:
  * `CMD_APC_START {cookerId,type,targetTemperature,unit,timer(seconds),cookable}`
  * `CMD_NAME_WIFI_DEVICE {type,name,cookerId}`
* User commands in CUL nest the UserCommand inside `payload`. For example, setSubscription sends `{command:'CMD_USER_SET_SUBSCRIPTION', payload:{id:uuid, type:'CMD_USER_SET_SUBSCRIPTION', payload:{productId, appType: Platform.OS, transactionReceipt}}}`.
* The reply is matched on top-level `requestId`. `payload.status === 'ok'` resolves the promise with the **string `'ok'`**; anything else rejects with `payload.error`. Timeout is 10 s (CUL@16437782 `COMMAND_TIMEOUT_SECONDS = 10`).

**Error/status codes.** The only status value the clients interpret is `'ok'`. Error strings are free text. No numeric codes or rate-limit fields are handled client-side [seen].

**Report rate.** `CMD_APO_SET_REPORT_STATE_RATE {cooking:number, idle:number}` and `CMD_APO_SET_REPORT_STATE_RATE_DEFAULT {}` exist (schema plus `SetReportStateRateCommandFactory`, OVN@18995067) but **the app never sends them** [seen]. Units are probably seconds [inferred].

---

### 3. Account / pairing / token commands

All of these go over the same WebSocket in the OVN envelope from §2.3. The shapes below are the `payloadData` part; the server sees it as `payload` with `id` replaced by `deviceId`. They come from `test/fixtures/schemas/IUserCommand` and `test/fixtures/schemas/IMultiUserCommand`, plus the call sites listed.

| command | payloadData | deviceId used by the app | Response used by the app | Call site |
|---|---|---|---|---|
| `CMD_GENERATE_NEW_PAIRING` | `{id, type}` | the oven's `cookerId` | `payload.data`, a pairing code shown as a QR code (`loadQRCode`) | OVN@58096497 [seen] |
| `CMD_ADD_USER_WITH_PAIRING` | `{id:'', type, payload:{data:<scanned QR string>}}` | `''` | `status` | `ScanQRCode`, OVN@58011674 [seen] |
| `CMD_LIST_USERS` | `{id, type}` | `cookerId` | `payload.userIds[]`. The app then loads `user-profiles/{uid}` for each (`useDeviceOwnersListener`) | OVN@52861851 [seen] |
| `CMD_APO_DISCONNECT` (remove a user from an oven) | `{id, type, payload:{userId}}` | `cookerId` | status | OVN@52840539 [seen] |
| `CMD_USER_PAIR_ALEXA` | `{id, type, payload:{code}}` | `cookerId` | status, then the "Alexa Linked!" alert | OVN@52571020. `code` comes from Amazon LWA: client `amzn1.application-oa2-client.a8de913d559f4f04aa1e608fcd033235`, redirect `https://oven.anovaculinary.com` (OVN@52555867) [seen] |
| `CMD_USER_UNPAIR_ALEXA` | `{id, type}` | `cookerId` | status | OVN@52565671 [seen] |
| `CMD_NAME_WIFI_DEVICE` (APC) / `CMD_APO_NAME_WIFI_DEVICE` (APO) | APC: `{cookerId, type, name}`; APO: `{id,type,payload:{name}}` | — / cookerId | status | CUL `nameDevice`; OVN `NameWifiDeviceCommandFactory` (OVN@31294586) [seen] |
| `CMD_LIST_TOKENS` | `{id:uuid, type}` | `null` | `payload.tokens[]`, each mapped to `{…, createdAt: new Date(createdAt)}` | OVN@57462858 [seen] |
| `CMD_CREATE_TOKEN` | `{id:uuid, type, payload:{name}}`; name trimmed, 1–32 chars | `null` | `payload.{id, name, token, createdAt}`. `token` is the secret, shown once | OVN@57472043 [seen] |
| `CMD_RENAME_TOKEN` | `{id:uuid, type, payload:{id:<tokenId>, name}}` | `null` | `status==='ok'` | OVN@57481159 [seen] |
| `CMD_DELETE_TOKEN` | `{id:uuid, type, payload:{id:<tokenId>}}` | `null` | status | OVN@57489488 [seen] |
| `CMD_USER_SET_SUBSCRIPTION` | `{id, type, payload:{productId, appType:'android'|'ios', transactionReceipt}}` | OVN: `deviceId` key present (value not resolved); CUL: nested | `'ok'`, else "Unable to save subscription." | OVN@29654311, CUL@15072000 `setSubscription` [seen] |
| `CMD_EXPORT_TELEMETRY` | `{id, type, payload:{deviceId, startTime, endTime}}` (strings) | — | — | [schema only] no call site |
| `CMD_APO_REGISTER_PUSH_TOKEN` | `{id, type, payload:{token:<FCM token>, platform:'android', appId:<bundleId>}}` | **mobile clientId** (`DeviceInfo.getUniqueId()`) | status | OVN `_setPushNotificationToken` @~26399644 [seen]. Also mirrored to Firestore (§4.3) |
| `CMD_APC_REGISTER_PUSH_TOKEN` (CUL) | flat `{firebaseMessagingToken, platform: Platform.OS, appId:'com.anovaculinary.anova'}` | — | — | CUL `registerPushNotificationToken` [seen]. Note the hard-coded iOS bundle id |
| `CMD_SEND_OVEN` (`SEND_OVEN_COMMAND`) | — | — | — | legacy constant only, not used (§1.4) |
| `CMD_APO_SET_SUBSCRIPTION` | `{expirationUnixTimestamp:number, subscribed:boolean}` | — | — | [schema only]; probably server-to-oven [inferred] |

Other APO commands, from `test/fixtures/schemas/IOvenCommand.compact.txt` [schema]; the factories are used by the app UI:

```
CMD_APO_START                 payload StartCookCommandPayloadV2 {cookId?, cookerId, cookableId?, cookableType:'guide'|'manual'|'recipe', originSource:'android'|'api'|'hardware'|'ios', stages:StageV2[], title?, description?, coverPhotoUrl?, coverVideoUrl?, type:'oven_v1'|'oven_v2'}
CMD_APO_STOP                  {}
CMD_APO_START_STAGE           {stageId}
CMD_APO_UPDATE_COOK_STAGE     Stage
CMD_APO_UPDATE_COOK_STAGES    {stages[]}
CMD_APO_SET_TIMER             {initial:number}
CMD_APO_SET_PROBE             {setpoint:{celsius}}            (V2)
CMD_APO_SET_LAMP              {on}
CMD_APO_SET_LAMP_PREFERENCE   {on}
CMD_APO_SET_FAN               {speed}
CMD_APO_SET_VENT              {open}
CMD_APO_SET_TEMPERATURE_UNIT  {temperatureUnit}
CMD_APO_SET_BOILER_TIME       {time}
CMD_APO_START_DESCALE / CMD_APO_ABORT_DESCALE
CMD_APO_OTA                   {downloadLink}
CMD_APO_SET_TIME_ZONE         {time_zone:{code, gmt_offset, id}}
CMD_APO_GET_CONFIGURATION     {}
CMD_APO_SET_CONFIGURATION     {token, expiresAt}
CMD_APO_SET_METADATA          {metadata}
CMD_APO_REQUEST_DIAGNOSTIC    {command}
CMD_APO_REPORT_LOGS
CMD_APO_START_LIVE_STREAM     {srt:{url,streamId,passphrase}, webRTC:{url}}?
CMD_APO_STOP_LIVE_STREAM
CMD_APO_SET_IMAGE_ANALYSIS    ImageAnalysis
CMD_APO_HEALTHCHECK
```

The OVN app builds `CMD_APO_START` in `buildStartCookV2Command` (OVN@26645110) [seen]:

```js
{
  stages: transformRawStagesToV2(stages),
  cookId, cookerId: ovenId,
  cookableId: cookable?.recipeId || '',
  title: cookable?.recipeTitle || '',
  description, coverPhotoUrl, coverVideoUrl,
  type: 'oven_v2',
  originSource: 'android',
  cookableType: cookable?.type ?? 'manual'   // 'quick_start' is mapped to 'recipe'
}
```

---

### 4. Backend endpoints other than the WebSocket

#### 4.1 REST (HTTP)

| Base | Method & path | Auth | Body / params | App | Purpose |
|---|---|---|---|---|---|
| `https://iot-api-prod.anovaculinary.io` | `POST /ai_assistant` | `Authorization: Bearer <idToken>`, `Content-Type: application/json` | `{requestId: Date.now().toString(), type:'question', payload:{conversationId, userMessage, userMessageId, assistantMessageId, domains, language, temperatureUnit, isNewConversation}}`. Feedback variant: `{type:'feedback', payload:{conversationId, messageId, feedback}}` | OVN@28518586 [seen] | AI assistant. The answer streams back over the WS as `EVENT_AI_ASSISTANT_STREAM`, and history lives in Firestore `users/{uid}/ai_conversations/{id}/messages` |
| `https://iot-api-prod.anovaculinary.io` | `POST /convert_recipe` | Bearer idToken | `{requestId, recipeUrl? , image?, quickConvert}` | OVN@30327680, OVN@46438504 [seen] | Recipe import from URL or photo. Results come back as WS `EVENT_RECIPE_CONVERTED {recipeId}` / `…PROGRESS_INFO` / `…FAILED` |
| `https://anovaculinary.io` | `POST /ali/force-verify-email-for-facebook-user` | none (token in body) | `{firebaseJWT}` | both [seen] | |
| `https://anovaculinary.io` | `POST /authenticate` | `Firebase-Token: <idToken>` | null | CUL@29649155 [seen] | identity registration |
| `https://anovaculinary.io` (CUL `apiClient`, 10 s timeout) | `GET /identities/{uid}/connected-cooks?archived=false&limit=20&offset=N` | `Authorization: Bearer <idToken>` (set by `setAuthToken` on `onAuthStateChanged`; CUL@13640199, CUL@51703325) | — | CUL@26434839 [seen] | **sous-vide cook history** (`CookHistoryCursor`) |
| same | `POST /identities/{uid}/connected-cooks/{uuid}` | Bearer | `CookHistoryItem.toJSON()` (has `recipeID`, `guideID`, `id`, …) | CUL@16615395 [seen] | save a cook |
| same | `POST /identities/{uid}/connected-cooks/{id}` | Bearer | `{...item, archived:true}` | CUL@16616870 [seen] | archive (delete) a cook |
| same | `POST /images/` | Bearer | base64 PNG | CUL@16880062 [seen] | image upload |
| same | `GET /recipes/browse`, `GET /recipes/search` (`page, limit, categoryID, creatorID, query`) | Bearer | — | CUL@41616927 [seen] | |
| same | `POST /devices-ota-current` `{device-type:'pro', git-sha:'hybrid'}` | Bearer | — | CUL@49341716 [seen] | |
| same | `GET /devices/{id}/states/?limit=1&max-age=10s` | Bearer | — | CUL@49733507 (`checkCookerStatusAPI`) [seen] | legacy Wi-Fi setup check |
| `https://anovaculinary.io/v1` (CUL `recipesAPIClient`) | `GET /recipes/{id}`, `GET /recipes/slugs/{slug}`, `GET /recipes?…` (`user_id, page, limit, sort_by_created`), `POST /recipes`, `PUT /recipes/{id}`, `DELETE /recipes/{id}`, `POST /recipes/{id}/ratings {rating}` | Bearer | | CUL@16747818–16805536 [seen] | sous-vide recipes |
| same | `GET /users/{uid}`, `PUT /users/{uid}`; `GET /users/{uid}/favorite-recipes`; `PUT /users/{uid}/favorite-recipes/{recipeId}`; `DELETE /users/{uid}/favorite-recipes/{recipeId}` | Bearer | | CUL@16766433–16794146 [seen] | **sous-vide favorites / profile** |
| `https://s3-us-west-2.amazonaws.com/app.anovacontent.com/production` | `GET /index.json` | none | | CUL@16757697 [seen] | static content |
| `https://api.anovaculinary.com` (CUL `a3WiFiClient`) | `GET /cookers/{id}?secret=…` | — | | CUL@10706432 [seen] | legacy A3 |
| `http://10.123.45.1` | `/api/1/wlan/profile_add`, `/api/1/wlan/en_ap_scan`, `/__SL_G_MCH`, `/get-device-identity`, `/add-user-identity`, `/api/1/wlan/confirm_req` | — | | CUL@49731648 [seen] | local Wi-Fi provisioning of the cooker (SimpleLink AP) |
| `https://anovaculinary.io` | `GET /devices-ota/?device-type=oven`; `POST /devices-ota-current {device-type:'oven' or 'oven_v2.<x>.production', firmware-version}` | none (plain fetch) | | OVN@28311013, OVN@28317941 [seen] | oven firmware lookup |
| `https://kit.openiap.dev` | `/v1/subscriptions/status/{…}?userId=`, `/v1/subscriptions/entitlements/{…}?userId=`, `/v1/products/…`, `/client-payload?platform=`, `POST /v1/subscriptions/bind-user/ {purchaseToken,userId}` | `apiKey` | | OVN@29949815 (also in CUL) [seen] | third-party IAP service |
| `https://manage.kmail-lists.com/ajax/subscriptions/subscribe` | | | | | Klaviyo marketing opt-in (`API_OVENAPP`) |
| Cloudinary `https://api.cloudinary.com/v1_1/…` (`/image/upload`, `/video/upload`, `/delete_by_token`) | | | | OVN | media for recipes and comments |
| Algolia (`ALGOLIA_APP_ID` / `ALGOLIA_SEARCH_API_KEY` constants, OVN@15248044; index `oven_recipes`) | | | | OVN | public recipe search |

**There is no oven REST endpoint for recipes, cook history or favorites.** For the oven these live entirely in Firestore (§4.3) [seen: no such paths exist; every oven recipe or cook access is `firestore().collection(...)`].

#### 4.2 Firebase Cloud Functions (callable, default region)

`httpsCallable` names [seen]:

* OVN: `deleteCloudinaryAsset {url, resourceType}` (OVN@19989507), `incrementNumberOfCooksForRecipe {recipeId}` (OVN@26697726), `deleteUserInAuth` (OVN@52822553)
* CUL: `updateUserEmail`, `deleteUserInAuth` (CUL@46712282)

Endpoint: `https://us-central1-anova-app.cloudfunctions.net/<name>`, with no region override seen [inferred].

#### 4.3 Cloud Firestore (project `anova-app`, database `(default)`): the sync surface for the oven

Collection constants: OVN@15867231 `{Devices:'devices', FavoriteOvenRecipes:'favorite-oven-recipes', Users:'users', UserProfiles:'user-profiles', Owners:'owners'}`; CUL@31169002 `{Users, UserProfiles, Owners}`.

| Path | Ops by the app | Fields / notes | Evidence |
|---|---|---|---|
| `users/{uid}/oven-cooks/{cookId}` | **read**: `orderBy('endedTimestamp','desc').limit(n)`, paginate with `startAfter`. `onSnapshot` on one cook. **delete** (`deleteOvenCook`). `set({recipeRef: oven-recipes/{recipeId}}, {merge:true})` when the user saves a cook as a recipe | `{id, stages[], slideshowMp4Url, slideshowGifUrl, createdTimestamp, endedTimestamp, recipeRef?}`. `stages[0].type` present means OV1, `stages[0].do` present means OV2. Docs are **not created by the app**, so they are written server-side when a cook ends [inferred] | OVN@25939840, OVN@26017024, OVN@26021792, OVN@26545420, OVN@26608507; model `OvenCook` OVN@25949839 [seen] |
| `users/{uid}/favorite-oven-recipes/{recipeId}` | `get` (isRecipeFavorited), `set({recipeRef: oven-recipes/{recipeId}, addedTimestamp})`, `delete`, list `orderBy('addedTimestamp','desc')` + `startAfter` | bookmarks / "saved recipes" | OVN@15873062, OVN@25936325, OVN@26023323 [seen] |
| `oven-recipes/{recipeId}` | `get`. Query **"My recipes"**: `where('userProfileRef','==', doc('user-profiles/'+uid)).where('draft', …).orderBy('createdTimestamp','desc').limit/startAfter`. Published feed: `where('published','==',true).orderBy('publishedTimestamp','desc')`. Quick starts: `where('isQuickStart','==',true)`. `update` (updateOvenRecipe). **create** via `collection('oven-recipes').doc()` + `set(OvenRecipe.fromCookSettings({cookSettings, recipeId, userId}).toFirestoreObject())` (`saveCookSettingsToRecipe`) | Schema in `test/fixtures/schemas/OvenRecipeV1/V2`: `{id, title, description, ingredients[], steps[], servings, preparationTimeSeconds, cookTimeSeconds, coverPhotoUrl, coverVideoUrl, coverVideoThumbnailUrl, coverVideoHasAudio, draft, published, publishedTimestamp, createdTimestamp, updatedTimestamp, userProfileRef, averageRating, numberOfRatings, numberOfComments, numberOfCooks?, utility?, isQuickStart?, iconType?, ai?}`. V1 steps use `CookingStage` (`type`, `heatingElements`, `temperatureBulbs`, …); V2 steps use `StageV2` (`do`, `entry`, `exit`) | OVN@26656324, OVN@26670555, OVN@26680538, OVN@26001465 [seen] |
| `oven-recipes/{id}/ratings/{uid}` | set `{rating}` / get / delete | | OVN@26688878 |
| `oven-recipes/{id}/comments/{cid}` (+ `/likes/{uid}`, `/comment-reports`) | social | `{text, commenterProfileRef, createdTimestamp, numberOfLikes, parentCommentRef, replyToUserProfileRef, media, …}` | OVN@28163195 |
| `users/{uid}` | `onSnapshot` (`updateOnUserSnapshot`); `update({isCollectionDismissed})`, `update({'isVideoWatched.<x>.<y>': …})`, `set({preferences}, {mergeFields:['preferences']})` | `preferences`, `notificationsMetadata`, `isCollectionDismissed`, `isVideoWatched` | OVN@26554054, OVN@26397816 |
| `users/{uid}/devices/{deviceId}` | `delete` (`removeDevice`) | per-user device docs exist (fields not read by the app) | OVN@25938040 |
| `users/{uid}/oven-mobile-clients/{clientId}` | `set({pushNotificationToken, platform:'android'})`, `delete` | `clientId = DeviceInfo.getUniqueId()` | OVN@26400878, OVN@26542807 |
| `users/{uid}/notifications` | list `orderBy('createdTimestamp','desc')` | | OVN@43560126 |
| `users/{uid}/ai_conversations[/{id}/messages]` | listen, delete; feedback `update` | | OVN@28546064 |
| `user-profiles/{uid}` | `get`, `set(..., {merge:true})` | profile name/photo, `accountCreatedAppId`, `accountCreatedAppPlatform` | OVN@15270527 |
| `oven-mobile-app/home-feed` | `get` | curated collections | OVN@35988711 |
| CUL: `users/{uid}` | `onSnapshot` (`Wrapped`, `[firestore/permission-denied]` handling) | | CUL@51704981 |

**Using this from Home Assistant [inferred, standard Firestore REST semantics].** The app's access is the user's own identity under Firestore security rules. The REST API with the same ID token gets the same access:

```
GET https://firestore.googleapis.com/v1/projects/anova-app/databases/(default)/documents/users/{uid}/oven-cooks?orderBy=endedTimestamp%20desc&pageSize=20
GET  …/documents/users/{uid}/favorite-oven-recipes?orderBy=addedTimestamp%20desc
POST …/documents:runQuery   (structuredQuery on oven-recipes where userProfileRef == projects/anova-app/databases/(default)/documents/user-profiles/{uid})
Authorization: Bearer <firebase idToken>
```

The uid is `localId` from `signInWithPassword`, or the `user_id` claim in the ID token.

---

### 5. Client-identifying values the server may see

| Value | Where | Evidence |
|---|---|---|
| `platform=android` (WS query) | both apps; CUL derives it from `Platform.OS` through `DeviceSource` (`ios`/`android`/`hardware`; the schema also allows `api`) | [seen] |
| `supportedAccessories=APO` (OVN) / `APC` (CUL) | WS query | [seen] |
| Subprotocol `ANOVA_V2` | OVN WS only | [seen] |
| `originSource: 'android'` in `CMD_APO_START` payload (enum `android/api/hardware/ios`); oven state echoes `originSource` | OVN@26645110 | [seen] |
| `appType: 'android'` in `CMD_USER_SET_SUBSCRIPTION` | both | [seen] |
| Push registration `{platform:'android', appId:'com.anovaculinary.anovaoven'}`, with `deviceId`/`payload.id` = `DeviceInfo.getUniqueId()` | OVN | [seen] |
| CUL push registration `appId: 'com.anovaculinary.anova'` (hard-coded) | CUL | [seen] |
| Firestore `user-profiles/{uid}.accountCreatedAppId/accountCreatedAppPlatform` | both | [seen] |
| HTTP `User-Agent: okhttp/4.12.0` (OVN) / `okhttp/4.7.2` (CUL); WS `origin: https://devices.anovaculinary.io` | RN networking | [seen in jadx] |
| Firebase Auth headers `X-Android-Package`, `X-Android-Cert`, `X-Firebase-GMPID`, `X-Client-Version` (native SDK) | identitytoolkit/securetoken only | [seen in jadx] |
| **No** app-version header, device id or user-agent string is sent on the WS or the Anova REST calls (only `Authorization`/`Content-Type`) | | [seen] |

---

### 6. Practical notes for `client.py`

Each point below is a comparison with what the apps do; all are [inferred].

* Keep `token=<idToken>` in the query. Adding `&platform=android` and the `ANOVA_V2` subprotocol matches the oven app exactly. The CUL app connects without a subprotocol, so the server evidently accepts both.
* Use the OVN envelope for commands: `{command: type, requestId: uuid4, payload: {id: <cookerId or null>, type, payload: {...}}}`. Correlate `RESPONSE` on top-level `requestId`; success is `payload.status == "ok"`; the error is in `error` or `payload.error`.
* The apps do not heartbeat and reconnect after a flat 5 s. They also hold no background connection, so a long-lived HA socket is a different usage pattern from the official clients.
* Cook history and recipes for the oven: use Firestore REST (§4.3). For sous vide, use `https://anovaculinary.io/identities/{uid}/connected-cooks` and `https://anovaculinary.io/v1/users/{uid}/favorite-recipes` with `Bearer <idToken>`.
* The API key the apps use is `AIzaSyCGJwHXUhkNBdPkH3OAkjc9-3xMMjvanfU`. It is the same Firebase project, so users and uids are identical across keys.

# Part 2: Precision Oven

## Anova Precision Oven (APO) cloud WebSocket protocol — reference for an `oven_v2`-only integration

Sources analysed:

- `.apks/oven/bundle.js` (Anova Oven app 1.2.11): the real APO client. Everything about connection, UI behaviour and validation comes from here.
- `.apks/culinary/bundle.js` (Anova app 3.6.7): this one is **also Hermes register-machine pseudo-JS, not plain JS**. It opens the WebSocket with `supportedAccessories=APC` only (`culinary/bundle.js:417268 '&supportedAccessories=APC&platform='`), so it never talks to ovens. It does bundle the same shared device-protocol library (`@anova/...` JSON schemas and `EventAPO*` classes).

Line numbers (`file:LINE`) are for these exact decompiled files. Every citation also gives a grep-able identifier or string.

**Legend.** **SEEN** means read directly in code. **SCHEMA** means taken from an embedded ajv JSON schema (authoritative TS types compiled to JSON-schema; see §0). **INFERRED** means my interpretation, not literally present.

---

### 0. How the schemas were obtained (high-confidence source)

Both bundles embed ajv JSON-Schema-draft-07 documents generated from the TypeScript types of Anova's shared library. I rebuilt each one with a small register interpreter that replays the straight-line `rN = {...}; rA['k'] = rB` code. Both apps produce byte-identical schemas.

| Schema export | culinary lines | oven lines |
|---|---|---|
| `IOvenCommandSchema` (all `CMD_APO_*`) | 339867–342642 | 515480–518255 |
| `OvenStateV2Schema` (`oven_v2` state) | 337675–339430 | 513288–515043 |
| `OvenStateV1Schema` | 336152–337576 | 511765–513189 |
| `OvenRecipeV2Schema` (Firestore recipe docs) | 348860–349731 | 524473–525344 |
| `IUserCommandSchema` (CMD_CREATE_TOKEN etc.) | 375372–375769 | 550963–551360 |

Grep anchor: `r2['IOvenCommandSchema'] = r3;`, `r2['OvenStateV2Schema'] = r3;`.

The schemas declare no `additionalProperties: false`. Extra fields such as `fahrenheit` are therefore tolerated by validators. Full TypeScript-style dumps are in Appendices A and B.

---

### 1. Transport

#### 1.1 Connection (SEEN, oven `OvenWebsocket.connect`, `oven/bundle.js:738935` area)

```
wss://devices.anovaculinary.io?token=<firebase ID token>&supportedAccessories=APO&platform=android
WebSocket sub-protocol: "ANOVA_V2"
```

- The token comes from `firebaseTokenQueryParam` (`oven/bundle.js:739108`): `'token=' + await user.getIdToken() + '&'`. This is a Firebase ID token for the Anova Firebase project.
  - INFERRED (not in this app): the public Anova developer flow uses a personal access token (`anova-…`) in the same `token=` slot. The shared lib defines `CMD_CREATE_TOKEN / CMD_LIST_TOKENS / CMD_RENAME_TOKEN / CMD_DELETE_TOKEN`, which create such tokens (Appendix C).
- `supportedAccessories=APO` selects oven events. The culinary app uses `APC`. Both may be comma-joined (INFERRED).
- On close, the client reconnects unless the close was requested. On open it drains the queued commands (`sendCommandProcessor.commandQueue.checkForTasks`).
- Messages are text JSON. The client does `JSON.parse(e.data)` and then calls `processMessage`.

#### 1.2 Outgoing command envelope (SEEN, `formatCommand`, `oven/bundle.js:738651`)

```js
formatCommand(deviceId, cmd, requestId) {
  return { command: cmd.type,
           payload: Object.assign({}, cmd, { id: deviceId }),
           requestId };
}
```

The `cmd` objects come from the `*CommandFactory` functions (`oven/bundle.js:518696–522750`), all shaped `{ id: uuidv4(), type: 'CMD_APO_…', payload }`. `formatCommand` **overwrites the inner `id` with the cookerId**. The wire format is therefore:

```json
{
  "command":   "CMD_APO_SET_FAN",
  "requestId": "6f1c…-uuid-v4",
  "payload": {
    "id":      "<cookerId, e.g. anova012300000000000000>",
    "type":    "CMD_APO_SET_FAN",
    "payload": { "speed": 100 }
  }
}
```

- `requestId` is a fresh `uuid.v4()` per send (`queueCommand → _send`, `oven/bundle.js:741700`).
- Commands with no payload (STOP, START_DESCALE, ABORT_DESCALE, HEALTHCHECK, REPORT_LOGS, STOP_LIVE_STREAM, SET_REPORT_STATE_RATE_DEFAULT) omit the inner `payload` key entirely, for example `{"id": cookerId, "type": "CMD_APO_STOP"}` (SCHEMA + factories).
- The app also has a module-level `sendCommand({deviceId, payloadData})` (`oven/bundle.js:739290` area). It marks "user interaction" for START_STAGE, SET_TIMER, SET_PROBE, SET_HEATING_ELEMENTS, SET_TEMPERATURE_BULBS, SET_STEAM_GENERATORS, SET_FAN, UPDATE_COOK_STAGE and UPDATE_COOK_STAGES, then calls `enqueueCommand`.
- The command queue (`CommandProcessor`, `oven/bundle.js:741500`) is FIFO. A queued command is dropped if it waited more than `COMMAND_TIMEOUT_SECONDS = 10` (`oven/bundle.js:742111`) before the socket became writable. Callers also race the response against a 10 s timeout. The error text matched elsewhere is `/timeout error after \d+ seconds/`.

#### 1.3 Responses / acks (SEEN, `useProcessWebsocketMessage`, `oven/bundle.js:840712`; `processResponseCommand`, `oven/bundle.js:741857`)

```json
{ "command": "RESPONSE",
  "requestId": "<same uuid>",
  "payload": { "status": "ok", ... } }
```

- Success is exactly `payload.status === "ok"`. The pending promise is then resolved with the whole `payload` object.
- On failure the error is `msg.error` if present, otherwise `msg.payload.error`. A string becomes the `Error` message. Anything else gives `"Unknown error occurred"`.
- Correlation is by `requestId` only (`commandReturnResponses[requestId] = {resolve, reject}`). The entry is deleted after the response.
- Response data, for example START_LIVE_STREAM, is read from `payload.data` (`r1.data.webRTCPlayback.url`, `oven/bundle.js:1340048`). So the shape is `{"status":"ok","data":{…}}`. The `data` nesting is SEEN; other commands' `data` is unknown.
- `state.processedCommandIds: string[]` in EVENT_APO_STATE (SCHEMA). INFERRED: it holds the requestIds the oven has applied. The app reads it into its common model but has no logic on it.

#### 1.4 Legacy constants `CMD_SEND_OVEN`, `RESPONSE_OVEN_CMD`, `RESPONSE_OVEN_STATE` (SEEN, `oven/bundle.js:742096–742112`)

```
CMD_AUTH_TOKEN      = 'AUTH_TOKEN'
CMD_SEND_OVEN       = 'SEND_OVEN_COMMAND'
RESPONSE_OVEN_CMD   = 'OVEN_COMMAND_RESPONSE'
RESPONSE_OVEN_STATE = 'OVEN_STATE'
RESPONSE_AUTH       = 'AUTH_TOKEN_RESPONSE'
COMMAND_TIMEOUT_SECONDS = 10
```

Only `COMMAND_TIMEOUT_SECONDS` is referenced. The other four have **no readers** in either bundle; they are dead legacy constants. The live protocol uses `command:"RESPONSE"` and `command:"EVENT_APO_STATE"`. An integration can ignore them, but it should tolerate and drop unknown `command` values.

#### 1.5 Incoming events dispatched by the oven app (SEEN, `oven/bundle.js:840602–841050`)

`EVENT_APO_STATE`, `EVENT_APO_WIFI_LIST`, `EVENT_USER_STATE`, `EVENT_RECIPE_CONVERTED`, `EVENT_RECIPE_CONVERSION_PROGRESS_INFO`, `EVENT_RECIPE_CONVERSION_FAILED`, `EVENT_AI_ASSISTANT_STREAM`, `RESPONSE`.

The shared lib also defines `EVENT_APO_WIFI_ADDED`, `EVENT_APO_WIFI_REMOVED` and `EVENT_APO_WIFI_FIRMWARE_UPDATE` (`EventAPOType`, `culinary/bundle.js:350135`, parser `fromDevicesRedisMessage`). The oven app's handler does not act on them. The culinary app has the APC equivalents (`EVENT_APC_*`).

---

### 2. Events

#### 2.1 EVENT_APO_STATE

Envelope (SEEN, class `EventAPOState`, `culinary/bundle.js:350333`; consumer `oven/bundle.js:840880`):

```json
{ "command": "EVENT_APO_STATE",
  "payload": { "cookerId": "anova…", "type": "oven_v2", "state": { …OvenStateV2… } } }
```

- `type` is the device type string: `oven_v1` or `oven_v2` (`APODeviceVersion`, `oven/bundle.js:511104`).
- The app does not trust `type` for parsing. It discriminates on the state itself:
  - `isOvenStateV2` (`oven/bundle.js:515162`)
  - `isOvenStateV1(s) = s.state && !('cavityOverheated' in s.state)` (`oven/bundle.js:515118`)
- `state.version` is `1` for v1 and `2` for v2 (SEEN in `createOvenStateV1/V2` test builders, `oven/bundle.js:526700`). `Oven.deviceVersion` returns V1 iff `version === 1` (`oven/bundle.js:867705`).
- **For a v2-only integration:** accept `payload.type == "oven_v2"` and `"cavityOverheated" in state.state` (equivalently `state.version == 2`). Ignore everything else.

##### OvenStateV2 (SCHEMA, `OvenStateV2Schema`; full dump in Appendix A)

```
{
  version: number                      // 2
  updatedTimestamp: string             // ISO-8601
  systemInfo: SystemInfoV2
  state: StateV2
  nodes: NodesV2
  cook?: CookV2                        // present while a cook exists
}
```

**`systemInfo`**

```
deviceId: string                       // "anova0123…" (sample)
firmwareVersion: string
firmwareUpdatedTimestamp: string
hardwareVersion: string                // sample "Universal"; used in OTA device-type
releaseTrack: string                   // "production" or beta track; app sets betaFeature = releaseTrack if != "production"
online: boolean
lastConnectedTimestamp: string
lastDisconnectedTimestamp: string
powerHertz: number                     // 50/60
powerMains: number                     // 120/230
triacsFailed?: boolean
flashFree?: number
ramFree?: number
otaUpdate?: { mode: OtaUpdateMode, progress?: number }
```

`OtaUpdateMode` is one of `default`, `downloading`, `downloading_partial`, `error`, `power_board_updating`, `reboot`, `rollback`, `update`, `update_partial`.

The app collapses these (`convertOtaUpdate`, `oven/bundle.js:864222`): `reboot` and `error` are kept, and everything else is shown as `update`. This is SEEN; the decompiled branch reads `mode!='reboot' && mode!='error' → 'update'`.

Sample from the test builder (`createSystemInfoV2`, `oven/bundle.js:526873`):

```json
{"online":true,"deviceId":"anova012300000000000000","firmwareVersion":"1.0.0","releaseTrack":"prod",
 "firmwareUpdatedTimestamp":null,"hardwareVersion":"Universal","triacsFailed":false,"powerHertz":60,
 "powerMains":120,"lastConnectedTimestamp":null,"lastDisconnectedTimestamp":null,"flashFree":0,"ramFree":0}
```

**`state`**

```
mode: "idle" | "cook" | "descale"
temperatureUnit: "C" | "F"             // oven display unit
processedCommandIds: string[]
cavityOverheated: boolean              // v2-only; the v1/v2 discriminator
```

**`nodes`** (every key; all are required in the schema)

| node | shape | notes |
|---|---|---|
| `temperatureBulbs` | `{mode:"dry"\|"wet", dry:{current:{celsius}, setpoint?:{celsius}, numberOfOverCurrent}, wet:{current:{celsius}, setpoint?:{celsius}, dosed:bool, dc12VInletStatus:string, ntcConnected:bool, numberOfOverCurrent}, dryTop:{current:{celsius}, ntcConnected, numberOfOverCurrent}, dryBottom:{same}}` | The setpoint sits under the active mode only: `dry.setpoint` when mode is dry, `wet.setpoint` when mode is wet. `wet.dosed` means the wet-bulb wick has water. |
| `heatingElements` | `{top:{on,failed,watts}, bottom:{…}, rear:{…}}` | |
| `fan` | `{speed: string, failed: bool}` | Speed is a **string** in state: `"off"`, `"min"`, `"mid"`, `"max"`. The app maps these to 0/33/66/100 (`convertFan`, `oven/bundle.js:864840`). Commands use numbers (§3). |
| `exhaustVent` | `{state:"closed"\|"open-mid"\|"open-max", dc12VStatus, numberOfOverCurrent}` | |
| `steamGenerators` | one of `{mode:"idle"}`, `{mode:"relative-humidity", relativeHumidity:{current, setpoint}}` or `{mode:"steam-percentage", steamPercentage:{current?, setpoint}}`, each **plus** `evaporator:{celsius, watts, failed, ntcConnected}` and `boiler:{celsius, watts, failed, dosed, descaleRequired, usageHours, ntcConnected, dc12VInletPumpStatus, dc12VOutletValveDescaleStatus, numberOfOverCurrentInletPump, numberOfOverCurrentOutletValveDescale}` | `boiler.descaleRequired` drives the descale prompt. `boiler.usageHours` is steam usage; the UI says to descale after 30 h. |
| `temperatureProbe` | `{connected:true, current:{celsius}, ntcConnected, setpoint?:{celsius}}` or `{connected:false, ntcConnected, setpoint?:{celsius}}` | |
| `timer` | `{mode: TimerMode, initial?: number, startedAtTimestamp?: string}` | `TimerMode` is `idle`, `running`, `paused` or `completed`. Remaining time = `initial - floor(now - startedAtTimestamp)` (`convertTimer`, `oven/bundle.js:864564`). The app treats "`initial` missing" as manual timer completed (`hasManualTimerCompleted`). |
| `door` | `{closed: bool}` | |
| `doorLamp` | `{on: bool, failed?: bool, preferences: string}` | `preferences` is `"on"` or `"off"` (Settings → Oven Light, `oven/bundle.js:1453869`). This is the "light on while cooking" preference. |
| `cavityLamp` | `{on: bool, failed?: bool}` | |
| `cavityCamera` | `{enabled: bool, streaming: bool, isEmpty: bool, detection: [{type: string, categoryId: string, confidence: number, details?: object}]}` | `isEmpty` is used by food-detection stage logic (§4.4). The `detection[].type` and `categoryId` vocabularies are not enumerated in the app. |
| `waterTank` | `{empty, low, removed}` (bools) | |
| `wasteWaterTank` | `{full, removed}` | v2-only |
| `displayBoard` | `{celsius}` | |
| `exhaustFan`, `displayFan`, `ledFan` | `{speed: string, dc12VStatus: string, numberOfOverCurrent}` | Sample speed `"max"`, status `"no-error"` |
| `powerBoardFan` | `{on: bool, dc12VStatus, numberOfOverCurrent}` | |
| `dc12VLine` | `{numberOfFaults, numberOfRejections}` | |

All temperatures in v2 state are **Celsius only**. The app computes Fahrenheit locally with `convertCtoF`. Its display helper is `celsiusToFahrenheit = round((c*9/5+32)*10)/10` (`oven/bundle.js:726694`).

**`cook` (CookV2)**

```
cookId: string
stages: StageV2[]                      // same stage object as sent in CMD_APO_START (§4)
activeStageId: string
activeStageIndex: number
activeStageMode: string                // not enumerated in schema/app
activeStageStartedTimestamp: string
startedTimestamp: string
cookableType: string                   // echoes start payload
originSource: string
```

The app derives elapsed times as `now - activeStageStartedTimestamp` and `now - startedTimestamp` (`convertCook`, `oven/bundle.js:865246`).

**App-derived booleans worth reproducing** (SEEN, `CommonOvenStateModel` getters, `oven/bundle.js:864950–865150`):

- `hasPreheatCompleted`: `nodes.temperatureBulbs[mode].current.celsius >= nodes.temperatureBulbs[mode].setpoint.celsius`.
- `manualTimerSet`: the active stage's `do.timer.entry.conditions.and.userAction["="]` is truthy.
- `immediateTimerSet`: the active stage has `do.timer` with no `entry`.
- `probeComplete`: `nodes.temperatureProbe.current.celsius >= stage.exit.conditions.and["nodes.temperatureProbe.current.celsius"][">="]`.
- `timerComplete`: `"timer" in stage.do` and `!("initial" in nodes.timer)`.
- `isStageTransitionPendingUserAction`: a manual timer is set and (timer completed, or preheated with timer idle), or else timer/probe complete.

##### Sample v2 `nodes` (SEEN, test builder `createNodesV2`, `oven/bundle.js:527000–527160`)

```json
{
  "temperatureBulbs": {"mode":"dry",
    "dry":{"current":{"celsius":176.7},"setpoint":{"celsius":176.7},"numberOfOverCurrent":0},
    "dryTop":{"current":{"celsius":176.7},"numberOfOverCurrent":0,"ntcConnected":false},
    "dryBottom":{"current":{"celsius":176.7},"numberOfOverCurrent":0,"ntcConnected":false},
    "wet":{"current":{"celsius":100},"dosed":false,"dc12VInletStatus":"no-error","numberOfOverCurrent":0,"ntcConnected":false}},
  "steamGenerators": {"mode":"idle",
    "evaporator":{"failed":false,"ntcConnected":false,"celsius":170.1,"watts":0},
    "boiler":{"descaleRequired":false,"failed":false,"ntcConnected":false,"celsius":105.2,"usageHours":0,"watts":200,
              "dosed":false,"dc12VInletPumpStatus":"no-error","dc12VOutletValveDescaleStatus":"no-error", "...":"..."}},
  "timer": {"mode":"idle"},
  "temperatureProbe": {"connected":false,"ntcConnected":false,"setpoint":{"celsius":54}},
  "heatingElements": {"top":{"on":false,"failed":false,"watts":0},"bottom":{"on":false,"failed":false,"watts":0},"rear":{"on":true,"failed":false,"watts":0}},
  "fan": {"speed":"mid","failed":false},
  "waterTank": {"low":false,"empty":false,"removed":false},
  "exhaustVent": {"state":"closed","dc12VStatus":"no-error","numberOfOverCurrent":0},
  "door": {"closed":true},
  "doorLamp": {"on":false,"failed":false,"preferences":"on"},
  "cavityLamp": {"on":false,"failed":false},
  "cavityCamera": {"enabled":true,"streaming":false,"isEmpty":true,"detection":[]},
  "displayBoard": {"celsius":30},
  "exhaustFan": {"speed":"max","dc12VStatus":"no-error","numberOfOverCurrent":0},
  "dc12VLine": {"numberOfFaults":0,"numberOfRejections":0},
  "displayFan": {"speed":"max","dc12VStatus":"no-error","numberOfOverCurrent":0},
  "ledFan": {"speed":"max","dc12VStatus":"no-error","numberOfOverCurrent":0},
  "powerBoardFan": {"on":false,"dc12VStatus":"no-error","numberOfOverCurrent":0},
  "wasteWaterTank": {"full":false,"removed":false}
}
```

Sample `state` (`createStateV2`, `oven/bundle.js:548632`): `{"mode":"idle","temperatureUnit":"F","processedCommandIds":[],"cavityOverheated":false}`.

##### How to recognise v1 and ignore it

v1 state has a different shape:

- `fan.speed` is a number.
- `vent:{open}` instead of `exhaustVent`.
- `lamp:{on, preference}` instead of `doorLamp`.
- `userInterfaceCircuit` is present.
- Temperatures carry `{celsius, fahrenheit}`.
- There is no `cavityOverheated`.
- `cook` has `secondsElapsed`, `activeStageSecondsElapsed` and `stageTransitionPendingUserAction`.

See `OvenStateV1Schema` and `createNodesV1` (`oven/bundle.js:526980`).

#### 2.2 EVENT_APO_WIFI_LIST (SEEN, `processDeviceList`, `oven/bundle.js:840790`)

```json
{ "command": "EVENT_APO_WIFI_LIST",
  "payload": [ { "cookerId": "anova…", "name": "My Oven", "type": "oven_v2", "pairedAt": "2024-…Z" }, … ] }
```

- The app maps each entry to `{deviceId: cookerId, deviceName: name, deviceType: type, pairedAt: new Date(pairedAt), connectedTo: 'aws-gen-3'}`.
- An empty list clears devices.
- This is the device discovery message for an integration. Filter `type === "oven_v2"`.
- Product names (`APOProductName`, `oven/bundle.js:511117`): `oven_v1` is "Anova Precision Oven 1.0" and `oven_v2` is "Anova Precision Oven 2.0".

#### 2.3 EVENT_APO_WIFI_ADDED, REMOVED and FIRMWARE_UPDATE (SEEN in shared lib only, `culinary/bundle.js:350150–350700`; oven app has no handler)

- `EVENT_APO_WIFI_ADDED`: `{command, payload:{cookerId, …}}`. `isValid` requires `payload.cookerId`. INFERRED: the remaining fields mirror a WIFI_LIST entry (`name`, `type`, `pairedAt`).
- `EVENT_APO_WIFI_REMOVED`: `{command, payload:{cookerId, …}}`. `isValid` requires `payload.cookerId`.
- `EVENT_APO_WIFI_FIRMWARE_UPDATE`: `{command, payload:{cookerId, version}}`. `isValid` requires both.
- Any other command becomes `EventAPOUnknown{command, payload}`.

Recommended handling: treat ADDED and REMOVED as triggers to refresh devices. A fresh WIFI_LIST also arrives on connect.

---

### 3. Commands (`CMD_APO_*`)

Common rules for every command below:

- Wire form is `{"command": T, "requestId": uuid, "payload": {"id": cookerId, "type": T, "payload": P}}`.
- The tables give the inner `P` (SCHEMA unless noted).
- "App use" is SEEN in the Oven model methods (`oven/bundle.js:866380–867720`, `r2['updateFan']` etc.) or the listed call site.
- **v2 note:** temperatures are `{celsius}`. The Temperature class's `toJSON()` (`oven/bundle.js:503944`) emits `{celsius, fahrenheit}`, so the app actually sends both for SET_TEMPERATURE_BULBS. Sending celsius only matches the v2 schema variant.

#### 3.1 Cook control

| Command | Inner payload `P` | v1/v2 | When the app sends it |
|---|---|---|---|
| `CMD_APO_START` | v2: `StartCookCommandPayloadV2` (§4.1). v1: `{cookId?, stages: CookingStage[] \| StopStage[]}` | both, different payloads | "Start cook" (manual, quick-start, recipe). `buildStartCookCommand` picks v1 iff `state.version===1` (`oven/bundle.js:744846`). |
| `CMD_APO_STOP` | none | both | Stop cook button (`stopCook`). Also used by "temporary stop with legacy state". |
| `CMD_APO_START_STAGE` | `{stageId: string}` | both | (a) "Start Stage" / "Start this cook stage will stop your current cook stage" jumps to a stage (`StageStartButton`, `oven/bundle.js:1238100`; `oven/bundle.js:1512895`). (b) **Manual timer start**: when the active stage waits for the user (`timerStartType==='manual'`, `isWaitingForUserStageState`), the timer button sends START_STAGE with the **current** stage id (`StageStateTimerButtonControl`, `oven/bundle.js:1238265`). INFERRED: this satisfies the `userAction` condition. |
| `CMD_APO_UPDATE_COOK_STAGES` | `{stages: StageV2[]}` (whole list) | **v2 path** | Editing a non-active/future stage, adding or removing stages (`deleteStage` filters by id then calls this). For v2 the app always rebuilds the list with `transformRawStagesToV2` (`oven/bundle.js:1256990`: `if deviceVersion===V2 → updateCookStages(cookSettings.stages) else updateCookStage(stage)`). |
| `CMD_APO_UPDATE_COOK_STAGE` | one `Stage` (v1 `CookingStage`/`StopStage` or `StageV2`) | **v1 path** in app | Same UI as above on v1 ovens. The schema accepts StageV2 too, but the app does not use it for v2. |

#### 3.2 Live adjustments of the *active* stage (the app sends these directly while cooking; hooks `useUpdate*OnOvenIfActiveStage`, `oven/bundle.js:1246700–1248020`)

| Command | Inner payload `P` | Notes |
|---|---|---|
| `CMD_APO_SET_TEMPERATURE_BULBS` | `{mode:"dry", dry:{setpoint:{celsius}}}` or `{mode:"wet", wet:{setpoint:{celsius}}}` | v2 variant is celsius only. v1 variants allow `{fahrenheit}` or `{celsius}`. `updateTemperatureBulbAndValue(mode, temp)`. Changing mode dry↔wet = sous-vide on/off. |
| `CMD_APO_SET_FAN` | `{speed: number}` | 0–100. The app only uses `0, 33, 67, 100` (OFF/LOW/MED/HIGH; `mapCanonicalFanSpeedToNumber`, `oven/bundle.js:570816`). |
| `CMD_APO_SET_HEATING_ELEMENTS` | `{top:{on}, bottom:{on}, rear:{on}}` | All three required. |
| `CMD_APO_SET_STEAM_GENERATORS` | `{mode:"relative-humidity", relativeHumidity:{setpoint: 0..100}}` or `{mode:"steam-percentage", steamPercentage:{setpoint: 0..100}}` | **Steam off = same command with setpoint 0** (`updateSteamGenerators(mode, 0)`, `oven/bundle.js:1247110`). Mode choice is in §5.3. |
| `CMD_APO_SET_TIMER` | `{initial: seconds}` | Max 359940 s (99:59:00, `MAX_TIMER_SECONDS`). Sets or changes the timer length. |
| `CMD_APO_SET_PROBE` | v2: `{setpoint:{celsius}}`. v1: `{setpoint:{celsius, fahrenheit}}` | **Clear probe target = `{setpoint:{celsius:0}}`** on v2 (`updateProbe(undefined)` → `{celsius:0}`, SEEN `oven/bundle.js:866650–866743`). Range 1–100 °C. |
| `CMD_APO_SET_VENT` | `{open: boolean}` | Exists in the schema and Oven model (`updateVent`), but **no UI caller** was found. v2 stages carry `do.exhaustVent.state` instead, and the v1→v2 transformer always writes `{"state":"closed"}`. INFERRED: legacy/v1 style. On v2, prefer the stage field. |

#### 3.3 Device settings

| Command | Inner payload `P` | When |
|---|---|---|
| `CMD_APO_SET_LAMP` | `{on: boolean}` | Oven light toggle on the cook screen (`updateLamp`, `oven/bundle.js:1263191`). Maps to `nodes.cavityLamp`/`doorLamp.on` (INFERRED which). |
| `CMD_APO_SET_LAMP_PREFERENCE` | `{on: boolean}` | Settings → "Oven Light" On/Off (`updateLampPreference`, reducer at `oven/bundle.js:742996`). Reflected in `nodes.doorLamp.preferences` as `"on"`/`"off"`. |
| `CMD_APO_SET_TEMPERATURE_UNIT` | `{temperatureUnit: "C"\|"F"}` | When the user changes the app's preferred unit, the app pushes it to the oven display (`oven/bundle.js:743005`). Reflected in `state.temperatureUnit`. |
| `CMD_APO_NAME_WIFI_DEVICE` | `{name: string}` | Rename oven (`setName`, `useOvenNameInputControl`, `oven/bundle.js:1452382`). |
| `CMD_APO_SET_TIME_ZONE` | `{time_zone:{id: string, code: string, gmt_offset: number}}` | SCHEMA only. No factory or call site in the app. Units of `gmt_offset` are unknown. |
| `CMD_APO_SET_CONFIGURATION` | `{token: string, expiresAt: date-time string}` | SCHEMA + factory. No UI caller. **Not** a sound/brightness config; INFERRED to be device credential provisioning. |
| `CMD_APO_GET_CONFIGURATION` | `{}` | Factory only, no caller. |
| `CMD_APO_SET_METADATA` | `{metadata: object}` | Factory only, no caller. |
| `CMD_APO_SET_REPORT_STATE_RATE` | `{cooking: number, idle: number}` | Factory only. Sets state-push interval while cooking or idle. Units are unknown (INFERRED seconds). |
| `CMD_APO_SET_REPORT_STATE_RATE_DEFAULT` | none | Factory only (the factory is misnamed `SetReportStateRateCommandFactory` at `oven/bundle.js:522110`). |

The schema has **no sound, volume, brightness or keep-warm configuration commands**.

#### 3.4 Maintenance

| Command | Inner payload `P` | When |
|---|---|---|
| `CMD_APO_START_DESCALE` | none | "Start Descaling" button in Settings → Descale (`startDescale`, `oven/bundle.js:1441006`). The UI says the oven firmware must be new enough ("You will need to upgrade your oven firmware in order to run descaling from the app."). `state.mode` becomes `"descale"`. |
| `CMD_APO_ABORT_DESCALE` | none | Factory exists (`oven/bundle.js:518696`). No UI caller found. |
| `CMD_APO_SET_BOILER_TIME` | `{time: number}` | Factory only. INFERRED: sets or resets the boiler usage counter (`boiler.usageHours`). |
| `CMD_APO_OTA` | `{downloadLink: string}` | Firmware update screen (`startFirmwareUpdate(downloadLink, from, to)`, `oven/bundle.js:788818`). The link comes from §6.4. |
| `CMD_APO_HEALTHCHECK` | none | Factory only. |
| `CMD_APO_REQUEST_DIAGNOSTIC` | `{command: string}` | SCHEMA only. |
| `CMD_APO_REPORT_LOGS` | none | SCHEMA only. |

#### 3.5 Account, cloud and camera

| Command | Inner payload `P` | When |
|---|---|---|
| `CMD_APO_REGISTER_PUSH_TOKEN` | `{token, platform:"android", appId}` | On app start, registers the FCM token (`oven/bundle.js:738387`). Not needed by HA. |
| `CMD_APO_DISCONNECT` | `{userId?: string}` | "Disconnect my oven" **unpairs the oven from the account** (`DisconnectMyOvenRow`, `oven/bundle.js:1446646`, payload `{userId: currentUser.uid}`). An integration must never send this. |
| `CMD_APO_SET_SUBSCRIPTION` | `{subscribed: boolean, expirationUnixTimestamp: number}` | SCHEMA only. INFERRED: cloud→oven premium flag. |
| `CMD_APO_START_LIVE_STREAM` | optional `{srt:{url, streamId, passphrase}, webRTC:{url}}` (`CloudflareSrtPayload`) | The app sends it **without payload**. The response is `payload.data.webRTCPlayback.url` (a Cloudflare WHEP URL), played with WebRTC (STUN `stun.cloudflare.com:3478`). It is re-sent every 60 s as a keep-alive (`setupLivestreamKeepAlive`, `setInterval(…, 60000)`, `oven/bundle.js:1338880`). The SRT/WebRTC payload variant is INFERRED to be cloud→oven. UI string: "Live Camera Feed (2.0 only)". |
| `CMD_APO_STOP_LIVE_STREAM` | none | Leaving the live view (`stopLiveStream`, `oven/bundle.js:1340349`). |
| `CMD_APO_SET_IMAGE_ANALYSIS` | `{categories:[{category, categoryId: number, confidence}], food_detected, is_empty, is_dirty, is_obstructed, condensation: boolean, rack_position: number}` | SCHEMA only. INFERRED: cloud vision results pushed to the oven. |
| `AUTH_TOKEN_V2` | `{token, platform, supportedAccessories: string[]}` | Present in `APOCommandType`. Not used by the app, which authenticates via the URL query. |

---

### 4. v2 cook / stage schema

#### 4.1 CMD_APO_START payload (v2) (SCHEMA `StartCookCommandPayloadV2` + SEEN `buildStartCookV2Command`, `oven/bundle.js:744870`)

| field | type | value used by app |
|---|---|---|
| `cookerId` | string, **required** | oven id |
| `type` | string, **required** | `"oven_v2"` (`APODeviceVersion.V2`) |
| `originSource` | `"android"\|"ios"\|"api"\|"hardware"`, **required** | `"android"`. Use `"api"` for an integration (INFERRED appropriate). |
| `cookableType` | `"manual"\|"recipe"\|"guide"`, **required** | `"manual"` if no cookable. A `quick_start` cookable is sent as `"recipe"`. Otherwise `cookable.type`. |
| `stages` | `StageV2[]`, **required** | |
| `cookId` | string | app-generated id (INFERRED uuid v4) |
| `cookableId` | string | recipe id or `""` |
| `title` | string | recipe title or `""` |
| `description` | string | recipe description (may be undefined) |
| `coverPhotoUrl`, `coverVideoUrl` | string | recipe media |

#### 4.2 StageV2 (SCHEMA)

```
StageV2 = {
  id: string                       // required (uuid)
  do: StageDo                      // required
  exit: { conditions?: StageConditions }   // required (may be {conditions:{and:{}}} = run until stopped/advanced)
  entry?: { conditions: StageConditions }  // gate before the stage's "do" counts as reached (preheat)
  title?: string
  description?: string
  rackPosition?: number            // v1 schema enum 1..5; UI rack positions 1-5
  photoUrl?: string
  preset?: string                  // free string; no enumerated values found
}
StageDo = {
  type: "cook" | "stop"            // app always "cook"; there is NO "preheat" type in v2
  fan: { speed: number }           // 0..100 (app: 0/33/67/100)
  heatingElements: { top:{on}, bottom:{on}, rear:{on} }
  temperatureBulbs: {mode:"dry", dry:{setpoint:{celsius}}} | {mode:"wet", wet:{setpoint:{celsius}}}
  exhaustVent?: { state: "closed" | "open-mid" | "open-max" }
  steamGenerators?: {mode:"relative-humidity", relativeHumidity:{setpoint}} | {mode:"steam-percentage", steamPercentage:{setpoint}}
  timer?: { initial: seconds, entry?: {conditions: StageConditions}, startType?: "manual"|"when-preheated"|"on-detection" }
  temperatureProbe?: { setpoint: {celsius} }
}
```

v1, for recognition only: `CookingStage` has a flat `fan`, `heatingElements`, `temperatureBulbs`, `vent:{open}`, `type: "preheat"|"cook"`, `userActionRequired`, `probeAdded`, and temperatures with celsius + fahrenheit. `StopStage` is `{type:"stop", userActionRequired, timer?}`.

#### 4.3 Conditions grammar (SCHEMA `StageConditions`, `Conditions`)

```
StageConditions = { and?: StageConditions, or?: StageConditions }   // recursive
               | { [nodePath: string]: Conditions }
Conditions      = { "=" | "<" | "<=" | ">" | ">=" | "equals" | "exists" : string|number|boolean }
```

Paths and operators the app actually emits (SEEN in `transformStagesV1ToV2`, `oven/bundle.js:549240–549700`, and `transformRawStagesToV2`, `oven/bundle.js:571775`):

| Path | Operator / value | Meaning |
|---|---|---|
| `nodes.temperatureBulbs.dry.current.celsius` | `">=": setpoint` | preheat reached (dry) — built as `'nodes.temperatureBulbs.' + mode + '.current.celsius'` |
| `nodes.temperatureBulbs.wet.current.celsius` | `">=": setpoint` | preheat reached (wet / sous-vide) |
| `nodes.temperatureProbe.connected` | `"=": true` | entry gate when stage uses probe |
| `nodes.temperatureProbe.current.celsius` | `">=": probeSetpoint` | exit on probe target |
| `nodes.timer.mode` | `"=": "completed"` | exit on timer |
| `userAction` | `"=": true` | wait for user (button / START_STAGE) |
| `nodes.cavityCamera.isEmpty` | `"=": false` | food detected (timer entry, "on-detection") |
| `nodes.cavityCamera.isEmpty` | `"=": true` | food removed (exit, "on-food-removal") |

The app reads conditions back with `includesAnyCondition(conditions, ['nodes.temperatureBulbs.dry.current.celsius','nodes.temperatureBulbs.wet.current.celsius'])` to decide whether a v2 stage has a preheat phase (`convertStages`, `oven/bundle.js:865444`).

#### 4.4 How UI concepts map to v2 stages (SEEN, `transformStagesV1ToV2` and `transformRawStagesToV2`)

The app's editor still models v1-style "preheat stage + cook stage". On send, they are folded into one v2 stage:

1. **Preheat.** There is no preheat stage type in v2. A cook stage that follows a preheat stage gets a stage-level `entry`:
   - without probe: `{conditions:{and:{"nodes.temperatureBulbs.<mode>.current.celsius":{">=": setpoint}}}}`
   - with probe: `{conditions:{and:{"nodes.temperatureProbe.connected":{"=":true}}}}`

   The entry is **omitted** when the stage type is `immediate-timer`.
2. **Stage "type"** (`getCookStageType`, `oven/bundle.js:549241`):
   - no timer + probe → `probe`
   - no timer, no probe → `default`
   - timer and not after preheat → `immediate-timer`
   - timer after preheat → `manual-timer` if `userActionRequired`, else `preheat-timer`
3. **Exit** (`transformStageExit`):
   - `probe` → `{and:{"nodes.temperatureProbe.current.celsius":{">=":probeC}}}`
   - any timer type → `{and:{"nodes.timer.mode":{"=":"completed"}}}`
   - `default` → `{and:{}}` (cook indefinitely)
   - if the **next** stage requires user action → `{and:{"userAction":{"=":true}}}`, overriding the above
4. **Timer** (`transformTimer`): `do.timer = {initial}`. After a preheat:
   - manual start: `do.timer.entry = {conditions:{and:{userAction:{"=":true}}}}`
   - "when preheated": `do.timer.entry` is a copy of the stage entry (timer starts when the temperature is reached)
5. **Food detection** (`transformRawStagesToV2`, `oven/bundle.js:571800`):
   - `timerStartOnDetect`: `do.timer = {initial: (timer.initial || 300), entry:{conditions:{or:{userAction:{"=":true}, "nodes.cavityCamera.isEmpty":{"=":false}}}}}`
   - `stageTransitionType === "on-food-removal"`: adds `"nodes.cavityCamera.isEmpty":{"=":true}` to the **previous** stage's `exit.conditions.and`
   - `StageTransitionType` (`oven/bundle.js:568592`) is `automatic`, `manual` or `on-food-removal`
6. `do.exhaustVent` is always `{"state":"closed"}` from the transformer. `do.type` is always `"cook"`. `title` defaults to `""`. `rackPosition`, `description` and `photoUrl` are copied when present.
7. UI timer start types (`timerStartType`, `oven/bundle.js:870640`): `immediately`, `when-preheated`, `manual`, `on-detection`. The schema field `do.timer.startType` exists (`manual|when-preheated|on-detection`), but the app encodes the behaviour with `entry` conditions rather than setting `startType`.

#### 4.5 Realistic CMD_APO_START (assembled from the code paths above)

This is a two-stage cook:

- Stage 1: preheat to 200 °C with the rear element, fan HIGH and 30 % steam, then a 20 min timer that starts when preheated.
- Stage 2: hold at 60 °C wet-bulb ("sous vide") with 100 % relative humidity until a probe reads 57 °C.

```json
{
  "command": "CMD_APO_START",
  "requestId": "b3c5f6a2-7d7e-4c1e-9a52-2f7f1f0d9e11",
  "payload": {
    "id": "anova012300000000000000",
    "type": "CMD_APO_START",
    "payload": {
      "cookId": "e4f5c1d0-7a32-4b84-8f3e-3a1d2b6c9f00",
      "cookerId": "anova012300000000000000",
      "type": "oven_v2",
      "originSource": "api",
      "cookableType": "manual",
      "cookableId": "",
      "title": "",
      "stages": [
        {
          "id": "1d9f6c3e-5b1a-4a9e-9d42-0c7b1f2e3a01",
          "title": "",
          "rackPosition": 3,
          "entry": { "conditions": { "and": {
            "nodes.temperatureBulbs.dry.current.celsius": { ">=": 200 } } } },
          "do": {
            "type": "cook",
            "fan": { "speed": 100 },
            "heatingElements": { "top": { "on": false }, "bottom": { "on": false }, "rear": { "on": true } },
            "exhaustVent": { "state": "closed" },
            "temperatureBulbs": { "mode": "dry", "dry": { "setpoint": { "celsius": 200 } } },
            "steamGenerators": { "mode": "steam-percentage", "steamPercentage": { "setpoint": 30 } },
            "timer": { "initial": 1200, "entry": { "conditions": { "and": {
              "nodes.temperatureBulbs.dry.current.celsius": { ">=": 200 } } } } }
          },
          "exit": { "conditions": { "and": { "nodes.timer.mode": { "=": "completed" } } } }
        },
        {
          "id": "8a2b4c6d-0e1f-4a3b-8c5d-7e9f0a1b2c3d",
          "title": "",
          "do": {
            "type": "cook",
            "fan": { "speed": 100 },
            "heatingElements": { "top": { "on": false }, "bottom": { "on": false }, "rear": { "on": true } },
            "exhaustVent": { "state": "closed" },
            "temperatureBulbs": { "mode": "wet", "wet": { "setpoint": { "celsius": 60 } } },
            "steamGenerators": { "mode": "relative-humidity", "relativeHumidity": { "setpoint": 100 } },
            "temperatureProbe": { "setpoint": { "celsius": 57 } }
          },
          "exit": { "conditions": { "and": {
            "nodes.temperatureProbe.current.celsius": { ">=": 57 } } } }
        }
      ]
    }
  }
}
```

Assumptions in this example:

- The entry/exit construction is SEEN.
- `originSource:"api"` is a schema-allowed value; the app itself sends `"android"`.
- The app would also add `entry: nodes.temperatureProbe.connected = true` to stage 2 only if it followed a preheat stage.
- Stage 2 values satisfy §5: wet bulb with steam allows ≤ 98 °C, rear element, fan HIGH, relative-humidity mode because temp < 100 °C.

---

### 5. Limits and validation (v2)

#### 5.1 Constants (SEEN, `oven/bundle.js:409640–409750`)

| name | °C | °F |
|---|---|---|
| dry bulb | 25–250 | 77–482 |
| dry, bottom element only (OV1) | 25–180 | 77–356 |
| dry, bottom element only (**OV2**) `…BOTTOM_HEATING_OV2` | 25–230 | 77–446 |
| wet bulb (sous vide) | 25–100 | 77–212 |
| probe | 1–100 | 33–212 |
| default dry / wet | 180 / 55 | 350 / 130 |
| `MAX_TIMER_SECONDS` | 359940 (99 h 59 min) | |

These come from the `temperatureRanges` table, keyed `wet`, `dry`, `dryBottomHeat`, `dryBottomHeatOv2` and `probe`, with `getTemperatureRange` at `oven/bundle.js:726629`.

#### 5.2 OV2 manual-cook rule table (SEEN, `MANUAL_COOK_VALIDATION_RULES`, `oven/bundle.js:727000–727161`)

The key is `${elements}_${wetBulb ON|OFF}_${steamBand}`:

- `elements` is one of `TOP_ONLY`, `BOTTOM_ONLY`, `REAR_ONLY`, `TOP_BOTTOM`, `TOP_REAR` or `BOTTOM_REAR` (`getElementCombination`; all three elements on is not a listed key).
- `steamBand` is `ZERO_PERCENT` when steam = 0, otherwise `ONE_TO_HUNDRED_PERCENT`.

Each rule is `createRule(25, maxC, allowedFans)`. Exact °F values come from `getExactFahrenheit`: 25→77, 45→113, 92→197.6, 98→208.4, 230→446, 250→482.

| elements | dry, 0 % steam | dry, steam 1–100 % | wet bulb, 0 % | wet bulb + steam |
|---|---|---|---|---|
| TOP_BOTTOM | 25–250, fans OFF/LOW/MED/HIGH | 25–250, HIGH | 25–92, HIGH | 25–98, HIGH |
| TOP_ONLY | 25–250, OFF/LOW/MED/HIGH | 25–250, HIGH | 25–92, HIGH | 25–98, HIGH |
| BOTTOM_ONLY | 25–230, OFF/LOW/MED/HIGH (*) | 25–230, HIGH | 25–92, HIGH | 25–98, HIGH |
| REAR_ONLY | 25–250, HIGH | 25–250, HIGH | 25–92, HIGH | 25–98, HIGH |
| TOP_REAR | 25–250, HIGH | 25–250, HIGH | 25–92, HIGH | 25–98, HIGH |
| BOTTOM_REAR | 25–250, HIGH | 25–250, HIGH | 25–92, HIGH | 25–98, HIGH |

(*) Bottom-only, dry, no steam: fan OFF is only allowed at ≤ 45 °C. With fan OFF the temperature range is 25–45 °C (77–113 °F); with LOW/MED/HIGH it is 25–230 °C. This is the proofing case (`getBottomOnlyAllowedFans`, `getManualCookTemperatureRange`, `isValidTemperature`).

Consequences:

- Any steam or sous-vide (wet bulb) forces fan HIGH (100).
- Any rear-element use forces fan HIGH.
- Fan speed values: `OFF=0, LOW=33, MED=67, HIGH=100` (`mapCanonicalFanSpeedToNumber`). Reverse mapping: `0→OFF, 33→LOW, 67→MED, 100→HIGH, anything else→HIGH` (`mapFanSpeedToCanonical`, `oven/bundle.js:570779`).
- Steam setpoint must be 0–100 (`isValidTargetSteamGeneratorValue`).

#### 5.3 Steam mode selection (SEEN, `updateSteamGenerators` helper, `oven/bundle.js:1247160`)

`mode = targetBulbTemperatureC < 100 ? "relative-humidity" : "steam-percentage"`.

- Relative humidity is used below 100 °C (any bulb mode).
- Steam percentage is used at or above 100 °C.
- Turning steam off sends the current mode with setpoint 0. In a stage, omit `steamGenerators` (`clearSteamGenerators`).
- UI label: `{{steamValue}}%`.

#### 5.4 Units

- v2 wire format is Celsius only: setpoints in commands and stages, and all state temperatures.
- Fahrenheit is UI-only. The validator converts `(F-32)*5/9` before checking °C ranges.
- `state.temperatureUnit` / `CMD_APO_SET_TEMPERATURE_UNIT` affect only the oven's display.
- v1 used `{celsius, fahrenheit}` pairs. That is one way to recognise v1.

---

### 6. Other capabilities an integration could expose

1. **Live state entities.**
   - Cavity dry/wet bulb temperatures plus `dryTop` and `dryBottom`.
   - Setpoint, probe current/setpoint/connected, timer (mode, initial, remaining via `startedAtTimestamp`).
   - Elements on and watts, fan speed string, vent state, steam mode and setpoints (current RH or steam %).
   - Door closed, lamps, water tank (`empty`/`low`/`removed`), waste-water tank (`full`/`removed`).
   - `boiler.descaleRequired` and `usageHours`.
   - `cavityOverheated`, `systemInfo.online`, firmware and `otaUpdate` progress.
   - `cavityCamera.isEmpty` (food present) and `detection[]`.
   - `cook.activeStageIndex`/`stages`/start timestamps.
2. **Manual cook.** CMD_APO_START with one stage (`exit:{conditions:{and:{}}}` means run until stopped). While cooking, use the direct SET_* commands for live changes, and UPDATE_COOK_STAGES to restructure stages.
3. **Preheat then hold or timer.** Use a stage `entry` with a bulb-temperature `>=` condition, plus `do.timer.entry` copying it (§4.4).
4. **"Keep warm."** There is no dedicated command or feature in the app (no keep-warm strings). Model it as a final stage with a low dry setpoint and empty exit conditions (INFERRED).
5. **Sous vide mode.** Use `temperatureBulbs.mode="wet"` with 25–100 °C. The UI validates ≤ 92 °C without steam and ≤ 98 °C with steam. Use relative-humidity steam below 100 °C.
6. **Food detection (2.0 camera).**
   - Timer "on-detection": `do.timer.entry.or{userAction, "nodes.cavityCamera.isEmpty"=false}`, default 300 s.
   - Stage transition "on-food-removal": exit when `isEmpty=true`.
   - Live camera: START_LIVE_STREAM returns `data.webRTCPlayback.url` (WHEP), re-sent every 60 s; STOP_LIVE_STREAM ends it.
7. **Presets / quick start.** These are Firestore recipe documents (`OvenRecipeV2Schema`), not device commands:
   - `isQuickStart`, `utility`, `iconType` ∈ `airFry`, `convectionBake`, `heatingElementBottom`, `heatingElementRear`, `heatingElementTop`, `heatingElementTopRear`, `heatingElementTopRearBottom`, `proof`, `steamIcon`, `threeHorizontalWavyLines`
   - `steps[]` of `{stepType:"direction"}` or `{stepType:"stage"} & StageV2`

   The app starts them with `cookableType:"recipe"` (quick_start → recipe) and `cookableId` = recipe id. The `StageV2.preset` string field exists but no values were found.
8. **Descale workflow** (UI strings, `oven/bundle.js` "Descale your Oven" etc.):
   - It is recommended after 30 h of steam. It takes about 45 min. You need 1 L water + 250 mL descaling solution in the tank, and a solid pan under the descale drain.
   - Start it with CMD_APO_START_DESCALE (or the handle button). Phase 1 runs with fans and elements off.
   - Then "EMPTY TRAY AND RETURN" and refill. Press play on the handle or the indicator to run the 10-min phase 2 flush.
   - Observe `state.mode=="descale"` and `boiler.descaleRequired`.
   - CMD_APO_ABORT_DESCALE exists but is unused by the app.
9. **Firmware** (`getLatestAvailableFirmwareUpdate`, `oven/bundle.js:789082`):
   - `POST https://anovaculinary.io/devices-ota-current` with body `{"device-type":"oven_v2.<hardwareVersion>.production"` (or `.<releaseTrack>` for beta)`, "firmware-version": "<current>"}`.
   - The response has `download-link`. If that ends in `.json`, fetch it and use its `download-link-full-ota`.
   - Then send `CMD_APO_OTA {downloadLink}`. The UI blocks this while cooking ("Firmware can't be updated while cooking.").
   - Progress arrives in `systemInfo.otaUpdate`. The response also carries `latestFirmwareVersion`-style fields (INFERRED).
10. **Oven light.** Use SET_LAMP for immediate on/off and SET_LAMP_PREFERENCE for the persistent on-during-cook setting.
11. **Display unit.** SET_TEMPERATURE_UNIT.
12. **Rename.** NAME_WIFI_DEVICE.
13. **Avoid:** DISCONNECT (unpairs), REGISTER_PUSH_TOKEN, SET_SUBSCRIPTION, SET_CONFIGURATION, SET_IMAGE_ANALYSIS. These are account/cloud-side.
14. **Personal access tokens** (user commands, Appendix C): `CMD_CREATE_TOKEN {name}`, `CMD_LIST_TOKENS`, `CMD_RENAME_TOKEN {id,name}`, `CMD_DELETE_TOKEN {id}`, plus `CMD_EXPORT_TELEMETRY {deviceId, startTime, endTime}`. They use the same `{command, requestId, payload:{id,type,payload}}` envelope.

App-derived stage status vocabulary, useful for a status sensor (SEEN, `oven/bundle.js:871694`). States are grouped as follows:

- not-cooking: `not-cooking-no-target`, `-timer-set`, `-probe-set`, …
- queued: `queued-standalone-cook-stage`, `queued-preheat-stage-*`, `queued-cook-stage-with-preheat-*`
- waiting for user: `preheat-stage-awaiting-manual-start-*`, `preheat-stage-preheated-awaiting-manual-transition…`
- preheating: `preheat-stage-preheating-before-*`
- cooking: `cook-stage-cooking-no-target`, `-with-timer`, `-with-probe`
- holding and completed (prefix lists truncated)

---

### 7. Enumerations summary (v2)

| Enum | Values | Source |
|---|---|---|
| device type | `oven_v1`, `oven_v2` | `APODeviceVersion` (`oven/bundle.js:511104`) |
| `state.mode` | `idle`, `cook`, `descale` | SCHEMA StateV2 |
| `temperatureUnit` | `C`, `F` | SCHEMA |
| `temperatureBulbs.mode` | `dry`, `wet` | SCHEMA |
| `nodes.timer.mode` | `idle`, `running`, `paused`, `completed` | SCHEMA TimerMode |
| `nodes.fan.speed` (state) | `off`, `min`, `mid`, `max` (→0/33/66/100) | `convertFan` (`oven/bundle.js:864840`) |
| fan speed (commands/stages) | number 0–100; app uses 0/33/67/100 | `mapCanonicalFanSpeedToNumber` |
| `exhaustVent.state` | `closed`, `open-mid`, `open-max` | SCHEMA |
| `steamGenerators.mode` | `idle` (state only), `relative-humidity`, `steam-percentage` | SCHEMA |
| `doorLamp.preferences` | `on`, `off` | sample + settings UI |
| `otaUpdate.mode` | `default`, `downloading`, `downloading_partial`, `error`, `power_board_updating`, `reboot`, `rollback`, `update`, `update_partial` | SCHEMA |
| `dc12V*Status` | `no-error` (others unknown) | sample |
| `do.type` | `cook`, `stop` (v1 also `preheat`) | SCHEMA |
| `timer.startType` | `manual`, `when-preheated`, `on-detection` | SCHEMA |
| `cookableType` | `manual`, `recipe`, `guide` | SCHEMA |
| `originSource` | `android`, `ios`, `api`, `hardware` | SCHEMA |
| StageTransitionType (UI) | `automatic`, `manual`, `on-food-removal` | `oven/bundle.js:568592` |
| camera `detection[].type/categoryId` | not enumerated in app | — |
| door | `closed: bool` | — |
| water tank | `empty`, `low`, `removed` (bools) | — |
| waste tank | `full`, `removed` (bools) | — |

---

# Part 3: Precision Cooker

## Anova Precision Cooker (APC) WebSocket protocol: reverse-engineered reference

Sources:
- **C** = `.apks/culinary/bundle.js` (Anova app 3.6.7)
- **O** = `.apks/oven/bundle.js` (Anova Oven 1.2.11)

Both files are **Hermes-decompiled pseudo-JS**. The culinary bundle is *not* plain minified JS, even though the task description said it was. Byte offsets (`@NNN`) are approximate positions in **C** for `grep -b`/Python lookup. All snippets in backticks are literal strings from the bundle, so you can grep them.

The shared protocol library (`APCCommand`, `APCCookerType`, `EventAPC*`, `SousVideStateSchema`, …) is the same npm package in both apps. **O** contains the same command and event set, the same `isTemperatureValid` (99.5/211.5) and `359940` timer check, the same cooker-type list, and the same schema (`processedCommandIds`, `triacsFailed`). Only **C** contains the app-side APC client (`APCWebsocket`, `EventProcessor`, `CookerState`).

Legend: **[seen]** means read directly in code. **[inferred]** means deduced, not verified on the wire.

---

### 0. TL;DR for the HA integration

- **Endpoint [seen]:** `wss://devices.anovaculinary.io?token=<TOKEN>&supportedAccessories=APC&platform=android`
  - Snippets: `'wss://devices.anovaculinary.io'` @14978288, `'&supportedAccessories=APC&platform='`, `'token='` in `firebaseTokenQueryParam`.
  - The app passes the **Firebase ID token** (`user.getIdToken`) as `token`. The oven app uses `supportedAccessories=APO`.
  - [inferred] The public "personal access token" (`anova-…`) that Anova documents for developers should work on the same endpoint (community clients do this), but the app itself uses Firebase.
- **Latest generation = "Gen 3" / `isThirdGenerationWifiCooker`:** the types `a6`, `a7`, `a8`, `a9`.
  - `a6` = Precision Cooker Nano 3.0
  - `a7` = Precision Cooker 3.0
  - `a8` = Precision Cooker Mini
  - `a9` = Precision Cooker Pro 3.0
  - Their `EVENT_APC_STATE.payload.state` is a **`SousVideState`** document (`version`, `updatedTimestamp`, `systemInfo`, `state`, `nodes`, `cook`, `metadata`), described by a JSON schema shipped in the app (§3).
- **Legacy, to drop:**
  - Gen 2 Wi-Fi (`a4`, `honey-badger`, `a5`, `pro`) uses kebab-case `WifiCookerState` bodies.
  - A3 Wi-Fi (`a3`) uses `A3FullState` and the secret-based `CMD_APC_A3_SET_CREDENTIALS`.
  - `a2a3` and `nano` are BLE only (Nano uses protobuf over BLE).
- **Gen 3 commands use the same flat JSON envelope as older generations.** The app does not send stage graphs; it sends `{targetTemperature, unit, timer, cookable}`, and the server builds the Gen 3 cook.

---

### 1. Device generations and types

#### 1.1 `APCCookerType` enum [seen] (C @~12010000 module 826, "`r4['HONEY_BADGER'] = r3`"; O @18455361)

| key | wire `type` | Product name (`APCProductName`) | Generation (lib helper) | Connectivity |
|---|---|---|---|---|
| A2A3 | `a2a3` | Anova Precision Cooker | none (`isAPCDevice` only) | BLE only (`'A2A3 - Bluetooth'`) |
| A3 | `a3` | Anova Precision Cooker | "A3 Wi-Fi", `isWifiCooker` via special case | Wi-Fi (legacy cloud via secret, proxied by devices WS) + BLE |
| A4 | `a4` | Anova Precision Cooker | `isSecondGenerationWifiCooker` | Wi-Fi 2.0 |
| HONEY_BADGER | `honey-badger` | Anova Precision Cooker | Gen 2 | Wi-Fi 2.0 (A4 variant; routed to `A4Device`) |
| A5 | `a5` | Anova Precision Cooker | Gen 2 | Wi-Fi 2.0 |
| PRO | `pro` | Anova Precision Cooker Pro | Gen 2 | Wi-Fi 2.0 (+ `'Pro - Bluetooth'`) |
| **A6** | `a6` | **Anova Precision Cooker Nano 3.0** | **`isThirdGenerationWifiCooker`** | Wi-Fi (BLE only for provisioning) |
| **A7** | `a7` | **Anova Precision Cooker 3.0** | **Gen 3** | Wi-Fi |
| **A8** | `a8` | **Anova Precision Cooker Mini** | **Gen 3** | Wi-Fi + **BLE fallback** (`isBTLEFallbackDevice` returns true only for `a8`) |
| **A9** | `a9` | **Anova Precision Cooker Pro 3.0** | **Gen 3** | Wi-Fi |
| NANO | `nano` | Anova Precision Cooker Nano | none | BLE only (protobuf: `SysAlertBitVector`, `SensorValueList`, …) |

Helpers [seen] (C module 826, `isSecondGenerationWifiCooker` / `isThirdGenerationWifiCooker` / `isWifiCooker` / `isAPCDevice`):
- Gen 2 = {a4, honey-badger, a5, pro}.
- Gen 3 = {a6, a7, a8, a9}.
- `isWifiCooker` = Gen 2 ∪ Gen 3 ∪ {a3}.
- `isAPCDevice` = Gen 2 ∪ Gen 3 ∪ {a2a3, a3, nano}.
- All comparisons call `toLowerCase()`.

The UI labels (`DeviceTypeID`) are `'A6 - Wi-Fi'`, `'A7 - Wi-Fi'`, `'A8 - Wi-Fi'`, `'A9 - Wi-Fi'`, `'A3 - Wi-Fi'`, `'A2A3 - Bluetooth'`, `'Nano - Bluetooth'`, `'ProBluetooth'`/`'ProWifi'` (C @~10806000).

#### 1.2 How the app distinguishes them [seen]

The `type` string is the discriminator. It arrives in:
- every `EVENT_APC_WIFI_LIST` entry and every `EVENT_APC_WIFI_ADDED` payload, as `type`;
- every `EVENT_APC_STATE` payload, as `payload.type`;
- pairing REST responses, as `body['device-type'].toLowerCase()` (`APCPairing.fromAPIResponse`).

The app uses it in these places:
- `WifiDevice.forCookerIdAndType` (C @~28050000) creates `A3WifiDevice | ProDevice | A4Device (a4 + honey-badger) | A5Device | A6Device | A7Device | A8Device | A9Device`, and otherwise throws `'Invalid Wifi device type'`.
- `CookerState.fromAPCStatePayload` (C @27787241) picks the parser:
  - `a3` → `new CookerState(payload.state)` (A3FullState-shaped, camelCase)
  - `a6|a7|a8|a9` → `CookerState.fromSousVideState(payload.state)` ← **latest**
  - anything else (Gen 2) → `new CookerState(new WifiCookerState({body: payload.state}))`

Firmware and model fields:
- **Gen 3:** `state.systemInfo.firmwareVersion`, `hardwareVersion`, `releaseTrack` (the app shows a "variant" when the track is not `prod`/`production`), and `otaUpdate`.
- **Gen 2:** `system-info.class/type/firmware-version`, `system-info-nxp.version-string`. The app derives the model 'A4'/'A5'/'Pro' from the firmware prefix `'VM178'`.
- **Latest available firmware:** `EVENT_APC_WIFI_VERSION` (§4.4).

#### 1.3 Which code is legacy

| Code path | Status |
|---|---|
| `fromSousVideState`, `SousVideStateSchema`, `isThirdGenerationWifiCooker` | **Latest. Implement this.** |
| `WifiCookerState*`, `WifiJobModes`, `WifiJobStatusStates`, `WifiPinInfo`, `A4Device`/`A5Device`/`ProDevice` | Gen 2 legacy |
| `A3FullState` (`fromDB`/`fromAPI` with `jobtype`, `jobstage`, `temperature_monitor`), `A3WifiDevice`, `CMD_APC_A3_SET_CREDENTIALS`, `APCSecret` (GoogleCloudKMS) | A3 legacy |
| `FallbackCommands`/`BluetoothFallback` (`SET_CLOCK`, `SYSTEM_INFO`, `SET_TEMPERATURE`, `CURRENT_TEMPERATURE`, `TIMER`, `STATE` characteristics, base64 JSON over BLE) | A8-only BLE fallback, out of scope for WS |
| Nano protobuf (`BluetoothCommunicator`, `SysAlertBitVector`: `WATER_LOW=32`, `WATER_LEAK=16`, `MOTOR_STUCK=64`, `HEATER_OVER_TEMP=128`, …) | BLE legacy |

---

### 2. Commands (client → server)

#### 2.1 `APCCommandType` enum [seen] (C @12021000, module 821)

The **key** is the JS name. The **value** is what goes on the wire.

| JS key | **wire `command`** |
|---|---|
| RESPONSE | `RESPONSE` |
| CMD_AUTH_TOKEN | `CMD_AUTH_TOKEN` |
| CMD_AUTH_TOKEN_V2 | `AUTH_TOKEN_V2` (note: no `CMD_` prefix) |
| CMD_APC_START | `CMD_APC_START` |
| CMD_APC_STOP | `CMD_APC_STOP` |
| CMD_APC_SET_METADATA | `CMD_APC_SET_METADATA` |
| **CMD_APC_SET_TARGET_TEMPERATURE** | **`CMD_APC_SET_TARGET_TEMP`** |
| CMD_APC_SET_TEMPERATURE_UNIT | `CMD_APC_SET_TEMPERATURE_UNIT` |
| **CMD_APC_OTA_UPDATE_FIRMWARE** | **`CMD_APC_OTA`** |
| CMD_NAME_WIFI_DEVICE | `CMD_NAME_WIFI_DEVICE` |
| CMD_APC_SET_TIMER | `CMD_APC_SET_TIMER` |
| CMD_APC_A3_SET_CREDENTIALS | `CMD_APC_A3_SET_CREDENTIALS` |
| CMD_APC_REGISTER_PUSH_TOKEN | `CMD_APC_REGISTER_PUSH_TOKEN` |
| CMD_APC_START_ICEBATH_MONITORING | `CMD_APC_START_ICEBATH_MONITORING` |
| CMD_APC_DISCONNECT | `CMD_APC_DISCONNECT` |
| CMD_APC_HEALTHCHECK | `CMD_APC_HEALTHCHECK` |

Snippets: `r3 = 'CMD_APC_SET_TARGET_TEMP';\n r4['CMD_APC_SET_TARGET_TEMPERATURE'] = r3;` and `r3 = 'CMD_APC_OTA';\n r4['CMD_APC_OTA_UPDATE_FIRMWARE'] = r3;`.

`SET_TARGET_TEMP` and `SET_TARGET_TEMPERATURE` are therefore the same command, and the wire string is `CMD_APC_SET_TARGET_TEMP`. Likewise, `CMD_APC_OTA` is the wire string for `OTA_UPDATE_FIRMWARE`. The app's own client enum (C @16437583) uses the key `CMD_APC_SET_TARGET_TEMP` and has `COMMAND_TIMEOUT_SECONDS = 10`.

Each command class's `isValid()` lives in the shared lib and is the **server-side validator** (the same lib contains `GoogleCloudKMS`, `fromDevicesRedisMessage`, `A3FullState.fromDB`). The rules below come from those validators.

#### 2.2 Envelope and transport [seen] (C @~15030000, `APCWebsocket`, `CommandProcessor`)

What the app sends (`CommandProcessor.sendCommand`):
```json
{
  "command": "CMD_APC_SET_TIMER",
  "requestId": "<uuid v4 A>",
  "payload": { "cookerId": "...", "type": "a7", "timer": 3600, "requestId": "<uuid v4 B>" }
}
```
- `requestId` (A) is generated in `queueCommand` (`generateUUID`).
- The payload is cloned with an extra, *different* `requestId` (B): `Object.assign({}, payload, {requestId: generateUUID()})`.
- [inferred] B is probably what gets echoed into the Gen 3 `state.processedCommandIds[]`.
- Commands go through a FIFO queue and are sent only while `ws.readyState === OPEN`. Otherwise the client throws `'Websocket connection is closed.'`.
- A queued command older than `COMMAND_TIMEOUT_SECONDS` (10 s) is dropped (`differenceInSeconds(now, queuedAt) <= COMMAND_TIMEOUT_SECONDS`).

Responses (`processMessage` → `processResponseCommand`):
- Any inbound message whose `command` is not one of the `EVENT_APC_*` or `EVENT_USER_STATE` types is treated as a response.
- Responses are correlated by the **top-level `requestId`**.
- Shape [seen fields; command name inferred from the `RESPONSE` enum]:
  ```json
  { "command": "RESPONSE", "requestId": "<uuid A>", "payload": { "status": "ok" } }
  { "command": "RESPONSE", "requestId": "<uuid A>", "payload": { "status": "<not ok>", "error": "<message>" } }
  ```
  - `payload.status === 'ok'` resolves the promise.
  - Anything else rejects it with `payload.error`.
  - The response carries no device state. State arrives separately as `EVENT_APC_STATE`.

Connection lifecycle [seen]:
- `onopen` logs `' connected to Client State Websocket Server '` and drains the queue.
- `onclose` triggers `reconnect()`, which sleeps 5 s and calls `connect()`, unless `requestingDisconnect` was set.
- Inbound frames must be strings (`"Websocket message received wasn't a string"`) and are `JSON.parse`d.
- The first messages after connect are pushed by the server unsolicited: `EVENT_APC_WIFI_LIST`, then `EVENT_APC_STATE` per cooker, `EVENT_APC_WIFI_VERSION`, and `EVENT_USER_STATE`. [inferred from the handlers; no explicit subscribe command exists.]

#### 2.3 Per-command reference

All cooker commands carry `cookerId` (string, from `WIFI_LIST`) and `type` (lowercase cooker type).

##### `CMD_APC_START` [seen] (`startCooker`, C @15083268; validator `CommandStart`, `isCommandStartGen3Payload`)

App payload:
```json
{
  "cookerId": "…",
  "type": "a7",
  "targetTemperature": 56.5,
  "unit": "C",
  "timer": 5400,
  "cookable": { … optional … }
}
```
- `targetTemperature`: a number in `unit`. The app uses the cooker's current display unit (`cookerStateSource.current.unit`) when the caller omits `unit`.
- `unit`: `"C"` or `"F"`.
- `timer`: **seconds** (the app sends `timerInMinutes * 60`; `0` = no timer [inferred]).
- `cookable` [seen fields of `Cookable.toJSON`]: `{name, minutes, temperatureInC, recipeID, guideID, imageURL, type}`. For a manual cook it can be omitted. The BLE path maps it to `cookableId = recipeID || guideID || ''` and `cookableType = cookable.type || 'manual'`.

Validation:
- For **Gen 3 types, `isValid()` always returns true** (no field checks).
- For other types, `targetTemperature` and `unit` must be truthy.
- `isCommandStartGen3Payload(p)` = `p.stages?.length > 0`. The lib therefore *accepts* a Gen 3 payload with an explicit `stages[]` array (the `SousVideStage` shape in §3.4) [inferred: an alternative "native" Gen 3 start format]. The app never sends `stages`; it sends the flat payload above for every generation.

Applies to all Wi-Fi types. The app sends it when the user starts a cook (manual, recipe, or guide).

##### `CMD_APC_STOP` [seen] (`stopCooker`)
- Payload: `{cookerId, type}`.
- Validator: always true.
- Applies to all types.

##### `CMD_APC_SET_TARGET_TEMP` (= `SET_TARGET_TEMPERATURE`) [seen] (`setTargetTemperature`, C @15089009)
- Payload: `{cookerId, type, targetTemperature, unit}`. `unit` is the cooker's current unit (`cookerStateSource.current.unit`).
- Validator `isTemperatureValid(t, unit)`:
  - unit falsy → valid;
  - `unit !== 'F'` → `0 <= t <= 99.5` (°C);
  - `'F'` → `32 <= t <= 211.5`.
- The app sends it while a cook is running and the user changes the setpoint (`TargetTemperatureChange` undo action).

##### `CMD_APC_SET_TIMER` [seen] (`setTimer`, C @15093540)
- Payload: `{cookerId, type, timer}`, where `timer` is seconds (`minutes * 60`).
- Validator: `0 <= timer <= 359940` (99 h 59 min; matches `Time.MAX_MINUTES = 5999`).
- The app sends it to change or add the timer during a cook.

##### `CMD_APC_SET_TEMPERATURE_UNIT` [seen]
- Payload: `{cookerId, type, unit}`.
- Validator: `unit.toLowerCase()` must be `'c'` or `'f'`. The app sends uppercase `C`/`F`.
- Changes the cooker's display unit. In Gen 3 this is `state.state.temperatureUnit`.

##### `CMD_APC_START_ICEBATH_MONITORING` [seen] (`startIceBathMonitor`)
- Payload: `{cookerId, type}`.
- Validator: `cookerId` must be present, and `type === 'a3'` or `type` is Gen 3. **Gen 2 is rejected.**
- [inferred] Typically sent after a cook finishes, to monitor an ice bath.
- Gen 3 reports it as a cook with `cookableType: 'ice-bath'` (§3.5).
- App ice-bath default threshold: `Temperature.forIceBath()` = 40 °F.

##### `CMD_APC_SET_METADATA` [seen in lib only; the app never sends it]
- Payload: `{type, …}`.
- Validator: `type` must be Gen 3.
- [inferred] Schema `Metadata` = `{[k: string]: string}` → `state.metadata`. Probably server-internal or for other clients.

##### `CMD_APC_HEALTHCHECK` [seen in lib only; the app never sends it]
- Envelope: `{command, requestId}`. The constructor does not copy `payload`, but `isValid` reads `payload.cookerId` (non-empty).
- [inferred] Server or device internal.

##### `CMD_APC_OTA` (= `OTA_UPDATE_FIRMWARE`) [seen] (`OTA`, `WifiDevice.startOTAUpdate`)
- Payload: `{cookerId, type, url}`.
- Validator: Gen 2 or Gen 3 type, and `url` truthy.
- `url` comes from `EVENT_APC_WIFI_VERSION[].ota.url`.
- Progress is reported in Gen 3 `systemInfo.otaUpdate` (§3).

##### `CMD_NAME_WIFI_DEVICE` [seen] (`nameDevice`; not in the task list but useful)
- Payload: `{type, name, cookerId}`.
- Validator: `requestId` and `cookerId` must be present.
- Renames the device (pairing `name`).

##### `CMD_APC_DISCONNECT` [seen] (`disconnect`)
- Payload: `{cookerId, type}`.
- Validator: `cookerId` and `type` must be present.
- [inferred] Unpairs or removes the Wi-Fi pairing from the account. The server then emits `EVENT_APC_WIFI_REMOVED`. **Do not expose it as a casual button.**

##### `CMD_APC_REGISTER_PUSH_TOKEN` [seen]
- Payload: `{firebaseMessagingToken, platform: Platform.OS, appId: 'com.anovaculinary.anova'}`. No `cookerId`.
- Validator: `requestId` and `firebaseMessagingToken` must be present.
- Phone push only. Not relevant to HA.

##### `CMD_APC_A3_SET_CREDENTIALS` [seen] (legacy, A3 only)
- Payload: `{type: 'a3', cookerId, secret}`.
- Validator: `type` must be `a3`, and `cookerId` and `secret` must be present.
- Drop.

##### Auth commands (lib) [seen]
- `CMD_AUTH_TOKEN`: `{token, userId}`.
- `AUTH_TOKEN_V2`: `{token, supportedAccessories: ['APC', …]}`, which must include `'APC'` and have fewer than 3 entries.
- The app authenticates through the query string instead and never sends these. [inferred] They are an alternative in-band auth.

##### User command (same socket) [seen]
- `CMD_USER_SET_SUBSCRIPTION` (`setSubscription`), with response `status 'ok'` and a 30 s race. Not relevant to HA.

---

### 3. `EVENT_APC_STATE`

#### 3.1 Envelope [seen] (`EventAPCState`, C @~12200000)
```json
{ "command": "EVENT_APC_STATE",
  "payload": { "cookerId": "…", "type": "a7", "state": { … generation-specific … } } }
```

#### 3.2 Gen 3 `state` = `SousVideState` [seen: full JSON schema in C @10866628, `SousVideStateSchema`, compiled by Ajv into `isSousVideState`]

Root `required`: `nodes`, `state`, `systemInfo`, `updatedTimestamp`, `version`.

```text
version: number
updatedTimestamp: Date (ISO date-time string)
metadata?: { [key: string]: string }
state (required: mode, processedCommandIds, temperatureUnit):
  mode: SousVideCookerMode = 'idle' | 'cook' | 'lowWater' | 'waterLeak' | 'highTemp' | 'motorStuck'
  temperatureUnit: 'C' | 'F'
  processedCommandIds: string[]
  resumeAfterPowerInterruption?: boolean
nodes (required: timer, waterTemperatureSensor):
  waterTemperatureSensor (TemperatureSensorNode; required current, setpoint):
     current:  { celsius: number }
     setpoint: { celsius: number }
     enabled?: boolean
  timer (TimerNode; required mode):
     mode: 'idle' | 'running' | 'paused' | 'completed'
     initial?: number (seconds)
     startedAtTimestamp?: Date
  lowWater? (LowWaterNode; required empty, warning): { empty: boolean, warning: boolean }
  probe? (ProbeNode; required connected, current, setpoint):
     { connected: boolean, current: {celsius}, setpoint: {celsius} }
cook? (Cook; required activeStageId, activeStageIndex, activeStageMode,
       activeStageStartedTimestamp, cookId, originSource,
       stageTransitionPendingUserAction, startedTimestamp):
  cookId: string
  activeStageId: string
  activeStageIndex: number
  activeStageMode: 'entering' | 'running'
  activeStageStartedTimestamp: Date
  startedTimestamp: Date
  stageTransitionPendingUserAction: boolean
  originSource: '' | 'android' | 'api' | 'hardware' | 'ios' | 'unknown'
  cookableId?: string
  cookableType?: 'guide' | 'ice-bath' | 'manual' | 'recipe' | 'sous-vide-express'
  stages?: SousVideStage[]
systemInfo (required all except otaUpdate):
  deviceId: string
  firmwareVersion: string
  hardwareVersion: string
  releaseTrack: string
  online: boolean
  triacsFailed: boolean
  firmwareUpdatedTimestamp: Date
  lastConnectedTimestamp: Date
  lastDisconnectedTimestamp: Date
  otaUpdate?: { mode: 'download'|'update', progress: number } | { mode: 'reboot' } | { mode: 'rollback' }
```

#### 3.3 Enumerations (lib) [seen]

| Enum | Values |
|---|---|
| `SousVideCookerMode` (C @11998559) | `IDLE='idle'`, `COOK='cook'`, `LOW_WATER='lowWater'`, `WATER_LEAK='waterLeak'`, `HIGH_TEMP='highTemp'`, `MOTOR_STUCK='motorStuck'` |
| `APCTimerMode` / `TimerMode` | `idle`, `paused`, `running`, `completed` |
| `APCStageMode` / `StageMode` (C @12011867) | `entering`, `running` |
| `StageType` | `cook`, `stop` |
| `APCCookableType` / `CookableType` | `guide`, `recipe`, `manual`, `ice-bath`, `sous-vide-express` |
| `DeviceSource` | `ios`, `android`, `hardware`, `api`, `unknown`, `''` (NONE) |
| App `CookerJobTypes` | `Idle`, `Cooking`, `Heating`, `KeepingWarm`, `MonitoringIceBath` |

#### 3.4 `SousVideStage` (inside `cook.stages`, and accepted by START per `isCommandStartGen3Payload`) [seen schema]

```text
SousVideStage (required do, id, title):
  id: string
  title: string
  do (required type, waterTemperatureSensor):
     type: 'cook' | 'stop'
     waterTemperatureSensor: { setpoint: { celsius } }
     timer?: { initial: number (s), entry?: StageEntry }
  entry?: { conditions: StageConditionsList }
  exit?:  { conditions: StageConditionsList }
StageConditionsList = { and?: {[path]: Conditions} | StageConditionsList,
                        or?:  {[path]: Conditions} | StageConditionsList }
Conditions = { '<'?, '<='?, '='?, '>'?, '>='?, equals?, exists? }   (values untyped)
```

[inferred] Condition keys are flattened node paths. The lib flattens or unflattens state with the delimiter `'_._'` (`flattenSousVideState`), so a path looks like `nodes_._waterTemperatureSensor_._current_._celsius`.

#### 3.5 How the app interprets Gen 3 state [seen] (`CookerState.fromSousVideState`, C @~27760000)

| App field | Derivation |
|---|---|
| `firmwareVersion` | `systemInfo.firmwareVersion` |
| `firmwareVariant` | `systemInfo.releaseTrack`, unless it is `'prod'` or `'production'` (then `''`) |
| `firmwareUpdateProgress` | `otaUpdate.progress` when `mode` is `'update'` or `'download'`, else 0 |
| `firmwareDownloading` / `firmwareUpdating` / `firmwareUpdateRebooting` | `otaUpdate.mode` equals `'download'` / `'update'` / `'reboot'`. `otaActive` = any of the three. |
| `isCooking` | `state.mode === 'cook'` |
| `isKeepingWarm` | `mode==='cook' && nodes.timer.mode==='completed' && cook.activeStageMode==='running' && cook.stages.length === cook.activeStageIndex+1` (the last stage is the hold stage after the timer ends) |
| `temperatureEnabled` | `nodes.waterTemperatureSensor.enabled`, default true |
| `targetTemperature` | `waterTemperatureSensor.setpoint.celsius`, converted to `state.temperatureUnit` |
| `currentTemperature` | `waterTemperatureSensor.current.celsius`, converted to `state.temperatureUnit` |
| `unit` | `state.temperatureUnit` |
| `timerInSeconds` | `getSousVideStateTimerSeconds` (see below) |
| `isWaterLow` | `nodes.lowWater.empty \|\| state.mode==='lowWater'` (`lowWater.warning` exists but the app ignores it) |
| `isWaterLeak` | `mode==='waterLeak'` |
| `isHighTemp` | `mode==='highTemp'` |
| `isMotorStuck` | `mode==='motorStuck'` |
| `isMonitoringIcebath` | `mode==='cook' && cook.cookableType==='ice-bath' && cook.activeStageIndex===0` |
| `isCheckingTemperatureForIceBath` | always false on Gen 3 |
| `isConnected` | `systemInfo.online` |
| `currentJobID` | `getJobIdFromSousVideState`: `'g-'+cookableId` for a guide, `'r-'+cookableId` for a recipe, else `''` |
| `cookerId` | `systemInfo.deviceId` |
| `isHeating` | `isCooking && current + δ < target`, with δ = 0.3 (°C) or 0.54 (°F) |
| `jobType` | priority order: MonitoringIceBath > Heating > Cooking > KeepingWarm > Idle |

`getSousVideStateTimerSeconds` works as follows:
- `timer.mode==='idle'` → `initial || 0`.
- Otherwise, no `startedAtTimestamp` → 0.
- Otherwise, mode not `'running'` → 0. This is an app quirk: paused or completed shows 0.
- Otherwise → `initial - (now - startedAtTimestamp)/1000`.

For HA, compute remaining time from `initial` and `startedAtTimestamp` yourself, and expose `timer.mode` directly.

Other side effects:
- If `systemInfo.online === false` for an `a8`, the app tries a BLE fallback connection.
- When `online` becomes true again, the app closes the BLE link.

#### 3.6 Legacy state shapes (for recognition only; drop)

**Gen 2** (`payload.state` = body, kebab-case; `WifiCookerStateBody`):
- `audio-control`, `boot-id`, `cap-touch`, `heater-control`, `motor-control`, `network-info`
- `job{id, cook-time-seconds, target-temperature, temperature-unit, mode, ota-url}`
- `job-status{cook-time-remaining, state}`
- `pin-info{device-safe, water-leak, water-level-critical, water-level-low}`
- `system-info{class, type, firmware-version}`, or the 3220 variant `{firmware-version, has-real-cert-catalog, firmware-version-raw}`
- `system-info-nxp{version-string}`
- `temperature-info{water-temperature}`

Gen 2 enums:
- `WifiJobModes`: `STARTUP`, `IDLE`, `COOK`, `OTA`, `PROVISIONING`, `HIGH TEMP`, `DEVICE FAILURE`, `LOW WATER`.
- `WifiJobStatusStates`: `PREHEATING`, `COOKING`, `MAINTAINING`, `TIMER EXPIRED`, `SET TIMER`.

**A3** (`A3FullState`):
- Fields: `firmwareVersion`, `isCooking`, `currentTemperature`, `targetTemperature`, `timerInSeconds`, `unit`, `isTimerRunning`, `isSpeakerOn`, `isAlarmActive`, `currentJobID`, `currentJob{jobType, jobStage, targetTemperature, timerLength, tempUnit, thresholdTemperature}`, `isKeepingWarm` (jobStage `'maintaining'`), `isCheckingTemperatureForIceBath` / `isMonitoringIcebath` (jobType `'temperature_monitor'` with stage `'checking_temperature'` / `'monitoring'`), and `isConnected`.

---

### 4. Device-list events [seen] (lib `Event.fromDevicesRedisMessage` + app `EventProcessor.processEvent`, C @27887856)

#### 4.1 `EVENT_APC_WIFI_LIST`
```json
{ "command": "EVENT_APC_WIFI_LIST",
  "payload": [ { "cookerId": "…", "type": "a7", "name": "My cooker", "pairedAt": "<ISO>" }, … ] }
```
- Elements are `APCPairing` objects `{cookerId, secret, type, pairedAt, name}`. The server removes `secret` (`stripSecrets`).
- `name` defaults to `getAPCProductName(type)`.
- The app calls `anovaDeviceStateStore.setPairedDeviceList(payload)`, which replaces the list and merges by `cookerId`.

#### 4.2 `EVENT_APC_WIFI_ADDED`
- Payload: one pairing `{cookerId, type, pairedAt, name?}`.
- Valid only if `cookerId` and `pairedAt` are present and `type` is Gen 3, Gen 2, `a3`, or `nano`.
- The app calls `addPairedDevice`.

#### 4.3 `EVENT_APC_WIFI_REMOVED`
- Payload: `{cookerId}` (required).
- The app calls `removePairedDevice(cookerId)`.

#### 4.4 `EVENT_APC_WIFI_VERSION`
```json
{ "command": "EVENT_APC_WIFI_VERSION",
  "payload": [ { "cookerId": "…", "version": "<current fw>",
                 "ota": { "available": true, "required": false, "url": "<fw url>",
                          "version": "<new fw>", "description": "<notes>" } } ] }
```
- `APCOTADetails` = `{available, required, url, version, description}`.
- The app's `setFirmwareVersionsForPairings` does `forEach` and reads `{cookerId, version → firmwareVersion, ota}`.
- `OTAUpdateInfo.fromPairing` maps `ota` to `{downloadLink:url, isUpdateAvailable:available, firmwareVersion:version, required, releaseDescription:description}`.
- This feeds `CMD_APC_OTA`.

#### 4.5 `EVENT_USER_STATE` (same socket)
- Payload: `{sousVideSubscription:{hasValidSubscription, isLegacyAccount, productId, renewalPeriod}}`.
- Not relevant to HA.

---

### 5. Limits and HA feature notes

#### 5.1 Limits [seen]

| Limit | Value | Source |
|---|---|---|
| Server/lib temperature validation | 0–99.5 °C; 32–211.5 °F | `isTemperatureValid`: `r1 = 99.5` / `r1 = 211.5` |
| Generic `Temperature` bounds | MIN_C 0, MAX_C 99.5, MIN_F 32, MAX_F 211.5, placeholder 54.4 °C / 130 °F, `clampC`/`clampF` | C @16693898 |
| Per-device UI bounds | Pro: 0–92 °C / 32–197.5 °F. A4 and Nano: 0–92 °C / 32–197 °F. A3 and A2A3: 0–99.5 °C / 32–211.5 °F. | `ProDevice`, `A4Device`, `NanoDevice`, `A3WifiDevice` |
| Gen 3 bounds | A5Device–A9Device set no `MIN_*`/`MAX_*` | [inferred] Use the generic 0–99.5 °C / 32–211.5 °F and let the server reject. Check against the device. |
| Timer | 0–359940 s (99:59) | `CommandSetTimer.isValid`; `Time.MAX_MINUTES = 5999` |
| Timer granularity | UI is whole minutes (`timerInMinutes*60`); the wire is seconds | |
| Temperature step | No explicit step constant found | [inferred] Display 0.1 °C / 0.5 °F as other Anova clients do. Values are sent as floats. |
| Heating hysteresis | 0.3 °C / 0.54 °F | `isHeating` |
| Ice-bath default | 40 °F | `forIceBath` |

#### 5.2 Suggested HA entities for Gen 3 (a6–a9)

**Climate / water heater:**
- `current_temperature` ← `nodes.waterTemperatureSensor.current.celsius`
- `target_temperature` ← `setpoint.celsius`
- HVAC on/off ← `state.mode == 'cook'`
- Set target → `CMD_APC_SET_TARGET_TEMP` while cooking, otherwise `CMD_APC_START`
- Off → `CMD_APC_STOP`

**Sensors:**
- `state.mode` (enum: idle/cook/lowWater/waterLeak/highTemp/motorStuck)
- `timer.mode`
- Timer remaining, computed from `initial` and `startedAtTimestamp`
- Timer end timestamp
- `cook.activeStageIndex` / `activeStageMode`
- `cook.cookableType`
- `systemInfo.firmwareVersion`, `hardwareVersion`
- Probe `current` / `setpoint`, if `nodes.probe.connected`

**Binary sensors:**
- `systemInfo.online` (connectivity)
- `nodes.lowWater.warning` and `.empty`, plus mode `lowWater` (problem)
- Water leak (`mode==waterLeak`)
- High temp (`mode==highTemp`)
- Motor stuck (`mode==motorStuck`)
- `systemInfo.triacsFailed` (problem)
- Heating (derived)
- Keeping warm (derived)
- Ice-bath monitoring (derived)

**Number:**
- Timer in minutes (0–5999) → `CMD_APC_SET_TIMER` with seconds.

**Select:** unit C/F → `CMD_APC_SET_TEMPERATURE_UNIT`.

**Button:** "Start ice bath monitoring" → `CMD_APC_START_ICEBATH_MONITORING` (Gen 3 and a3 only).

**Update entity:**
- Installed version ← `systemInfo.firmwareVersion`.
- Latest version ← `EVENT_APC_WIFI_VERSION[].ota.version`.
- Install → `CMD_APC_OTA {url}`.
- Progress ← `systemInfo.otaUpdate.progress`, with `mode` download/update/reboot/rollback.

**Rename** (optional service): `CMD_NAME_WIFI_DEVICE`.

**Not found:**
- No "delayed start" or scheduled-start command exists in the APC protocol (no command or field for it).
- [inferred] A Gen 3 multi-stage `stages[]` START might enable it through `entry.conditions`, but this is unverified.
- There is no speaker/alarm control for Gen 3. `isSpeakerOn` / `isAlarmActive` exist only in A3 state.

#### 5.3 Native/jadx

The JS reaches native code only for BLE (`react-native-ble-plx`-style `Device`, `writeCharacteristicWithoutResponseForService`), protobuf (Nano, Wi-Fi provisioning `WlanConnectionParams`, proof-of-possession), and Firebase. The WebSocket protocol is pure JS, so the jadx sources were not needed for the Wi-Fi protocol.
