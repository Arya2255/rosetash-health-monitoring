// gateway/setup_portal.cpp — see setup_portal.h.
//
// Endpoints:
//   GET  /        Persian setup form (prefilled from the current config)
//   GET  /scan    nearby 2.4 GHz networks as JSON  {"nets":[{"ssid","rssi"}]}
//   GET  /status  portal status JSON (ap, mac, sta_connected, ip, fw)
//   POST /save    writes /config.json to LittleFS and restarts the board
//
// The portal AP is an open network on purpose: it exists only while the
// gateway has no working wifi, carries no data, and disappears the moment a
// valid config takes over. See docs/gateway-provisioning.md.
#include "setup_portal.h"

#include <ArduinoJson.h>
#include <LittleFS.h>
#include <WebServer.h>
#include <WiFi.h>
#include <esp_mac.h>

static WebServer server(80);
static bool active = false;
static GatewayConfig cfg_;
static uint32_t last_sta_attempt_ms_ = 0;
static char ap_ssid_[24] = {0};
static char mac_str_[18] = {0};

// ── setup page (substitutions: {{AP}} {{SSID}} {{GW}} {{ZONE}} {{HOST}}
//    {{PORT}} {{MAC}}) ────────────────────────────────────────────────────────
static const char kPage[] = R"rawliteral(<!doctype html>
<html lang="fa" dir="rtl"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>آماده‌سازی گیت‌وی روزتاش</title>
<style>
body{font-family:Tahoma,Arial,sans-serif;background:#f2f3f5;margin:0;padding:14px;color:#1c1c1e}
.card{max-width:430px;margin:0 auto;background:#fff;border-radius:14px;padding:18px;box-shadow:0 2px 12px rgba(0,0,0,.08)}
h1{font-size:17px;margin:0 0 2px}
.sub{font-size:12px;color:#6b6f76;margin:0 0 10px}
label{display:block;font-size:13px;margin:11px 0 4px;font-weight:bold}
input,select{width:100%;box-sizing:border-box;padding:9px;border:1px solid #c9ccd1;border-radius:9px;font-size:14px;background:#fafbfc}
button{width:100%;margin-top:16px;padding:12px;border:0;border-radius:10px;background:#16181c;color:#fff;font-size:15px}
.note{font-size:11px;color:#6b6f76;margin-top:12px;line-height:1.7}
.mac{font-size:11px;color:#9aa0a6;direction:ltr;text-align:center;margin-top:10px}
</style></head><body>
<div class="card">
<h1>آماده‌سازی گیت‌وی روزتاش</h1>
<p class="sub">وای‌فای و مشخصات این گیت‌وی را وارد کنید؛ ذخیره که شد، برد خودش ری‌استارت می‌شود و به شبکه وصل می‌گردد.</p>
<form method="post" action="/save">
<label>انتخاب از شبکه‌های اطراف (اسکن خودکار)
<select id="nets" onchange="if(this.value)document.getElementById('ssid').value=this.value"><option value="">در حال اسکن…</option></select></label>
<label>نام وای‌فای (SSID)
<input id="ssid" name="ssid" value="{{SSID}}" required placeholder="مثلاً RoztashWiFi"></label>
<label>رمز وای‌فای
<input name="pass" value="" placeholder="رمز شبکه"></label>
<label>شناسهٔ گیت‌وی
<input name="gw" value="{{GW}}" placeholder="gw-filter-1"></label>
<label>منطقه / محل نصب
<input name="zone" value="{{ZONE}}" placeholder="سالن فیلتر"></label>
<label>آدرس سیستم HSE (بروکر MQTT)
<input name="host" value="{{HOST}}" placeholder="192.168.1.10"></label>
<label>پورت MQTT
<input name="port" value="{{PORT}}"></label>
<button type="submit">ذخیره و ری‌استارت</button>
</form>
<p class="note">
اگر رمز وای‌فای اشتباه باشد یا شبکه پیدا نشود، برد دوباره همین صفحه را باز می‌کند — با گوشی درستش کنید.
گیت‌وی فقط ۲.۴ گیگاهرتز را می‌بیند؛ اگر شبکه در فهرست نبود دستی وارد کنید.
</p>
<p class="mac">{{MAC}} — {{AP}}</p>
</div>
<script>
fetch('/scan').then(function(r){return r.json()}).then(function(d){
var s=document.getElementById('nets');
var o='<option value="">انتخاب از فهرست</option>';
(d.nets||[]).forEach(function(n){o+='<option value="'+n.ssid+'">'+n.ssid+' ('+n.rssi+' dBm)</option>'});
s.innerHTML=o;
}).catch(function(){document.getElementById('nets').innerHTML='<option value="">اسکن نشد — دستی وارد کنید</option>'});
</script>
</body></html>)rawliteral";

// Values come from json args typed on a phone — keep them attribute-safe.
static String esc(const char* s) {
  String out;
  if (!s) return out;
  for (; *s && out.length() < 120; ++s) {
    const char c = *s;
    if (c == '<' || c == '>' || c == '"' || c == '\'' || c == '&') continue;
    out += c;
  }
  return out;
}

static String buildPage() {
  String p(kPage);
  p.replace("{{AP}}", esc(ap_ssid_));
  p.replace("{{SSID}}", esc(cfg_.wifi_ssid));
  p.replace("{{GW}}", esc(cfg_.gw_id));
  p.replace("{{ZONE}}", esc(cfg_.zone));
  p.replace("{{HOST}}", esc(cfg_.mqtt_host));
  p.replace("{{PORT}}", String((unsigned)cfg_.mqtt_port));
  p.replace("{{MAC}}", mac_str_);
  return p;
}

// ── handlers ─────────────────────────────────────────────────────────────────

static void handleRoot() {
  server.send(200, "text/html; charset=utf-8", buildPage());
}

static void handleScan() {
  // Blocking scan; in AP+STA mode the AP pauses ~2 s — acceptable for setup.
  const int n = WiFi.scanNetworks(false, false);
  static String seen[24];
  static int seen_rssi[24];
  int cnt = 0;
  for (int i = 0; i < n && cnt < 24; ++i) {
    const String s = WiFi.SSID(i);
    if (!s.length()) continue;
    const int rssi = WiFi.RSSI(i);
    bool dup = false;
    for (int j = 0; j < cnt; ++j) {
      if (seen[j] == s) {
        dup = true;
        if (rssi > seen_rssi[j]) seen_rssi[j] = rssi;
        break;
      }
    }
    if (!dup) {
      seen[cnt] = s;
      seen_rssi[cnt] = rssi;
      ++cnt;
    }
  }
  // strongest first (selection sort — cnt is tiny)
  for (int i = 0; i < cnt; ++i) {
    for (int j = i + 1; j < cnt; ++j) {
      if (seen_rssi[j] > seen_rssi[i]) {
        const int ri = seen_rssi[i]; seen_rssi[i] = seen_rssi[j]; seen_rssi[j] = ri;
        const String si = seen[i]; seen[i] = seen[j]; seen[j] = si;
      }
    }
  }
  JsonDocument doc;
  JsonArray arr = doc["nets"].to<JsonArray>();
  for (int i = 0; i < cnt; ++i) {
    JsonObject o = arr.add<JsonObject>();
    o["ssid"] = seen[i];
    o["rssi"] = seen_rssi[i];
  }
  String out;
  serializeJson(doc, out);
  server.send(200, "application/json", out);
  WiFi.scanDelete();
}

static void handleStatus() {
  JsonDocument doc;
  doc["fw"] = kFwVersion;
  doc["ap"] = ap_ssid_;
  doc["mac"] = mac_str_;
  doc["sta_connected"] = (WiFi.status() == WL_CONNECTED);
  if (WiFi.status() == WL_CONNECTED) doc["ip"] = WiFi.localIP().toString();
  doc["ssid"] = cfg_.wifi_ssid;
  String out;
  serializeJson(doc, out);
  server.send(200, "application/json", out);
}

static bool saveConfigFromRequest() {
  String ssid = server.arg("ssid");
  ssid.trim();
  if (!ssid.length()) return false;

  String gw = server.arg("gw");
  gw.trim();
  gw.toLowerCase();
  String clean_gw;
  for (unsigned i = 0; i < gw.length() && clean_gw.length() < 23; ++i) {
    const char c = gw[i];
    if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || c == '.')
      clean_gw += c;
  }
  if (!clean_gw.length()) clean_gw = "gw-1";

  long port = server.arg("port").toInt();
  if (port <= 0 || port > 65535) port = 1883;

  JsonDocument doc;
  doc["gw_id"] = clean_gw;
  doc["zone"] = server.arg("zone").substring(0, 39);
  doc["wifi_ssid"] = ssid.substring(0, 39);
  doc["wifi_pass"] = server.arg("pass").substring(0, 79);
  doc["mqtt_host"] = server.arg("host").substring(0, 47);
  doc["mqtt_port"] = (uint16_t)port;
  doc["health_interval_s"] = cfg_.health_interval_s;
  doc["scan_interval_ms"] = cfg_.scan_interval_ms;
  doc["scan_window_ms"] = cfg_.scan_window_ms;
  doc["measure_timeout_s"] = cfg_.measure_timeout_s;

  if (!LittleFS.begin(true)) {
    Serial.println("[setup] LittleFS mount failed — cannot save");
    return false;
  }
  File f = LittleFS.open("/config.json", "w");
  if (!f) {
    Serial.println("[setup] cannot open /config.json for write");
    return false;
  }
  serializeJson(doc, f);
  f.close();
  Serial.printf("[setup] config saved: gw=%s ssid=%s broker=%s:%u\n",
                clean_gw.c_str(), ssid.c_str(), doc["mqtt_host"].as<const char*>(),
                (unsigned)port);
  return true;
}

static void handleSave() {
  if (!saveConfigFromRequest()) {
    server.send(400, "text/html; charset=utf-8",
                F("<!doctype html><meta charset='utf-8'><body style='font-family:Tahoma;direction:rtl'>"
                  "<h3>نام وای‌فای را وارد کنید</h3><p><a href='/'>بازگشت به فرم</a></p></body>"));
    return;
  }
  server.send(200, "text/html; charset=utf-8",
              F("<!doctype html><meta charset='utf-8'><body style='font-family:Tahoma;direction:rtl;padding:20px'>"
                "<h3>ذخیره شد ✓</h3><p>برد ری‌استارت می‌شود و به شبکهٔ شما وصل می‌گردد.</p>"
                "<p style='color:#666;font-size:13px'>اگر رمز اشتباه باشد یا شبکه پیدا نشود، "
                "بعد از چند ثانیه دوباره همین صفحهٔ تنظیمات بالا می‌آید.</p></body>"));
  delay(700);
  ESP.restart();
}

// ── public API ───────────────────────────────────────────────────────────────

bool setupPortalActive() { return active; }

void setupPortalBegin(const GatewayConfig& cfg) {
  if (active) return;
  cfg_ = cfg;
  active = true;

  uint8_t mac[6] = {0};
  // مک پایه از efuse — مستقل از وضعیت رادیو. خواندن WiFi.macAddress قبل از
  // روشن‌شدن WiFi صفر برمی‌گرداند و اسم AP «RoztashGw-000000» می‌شد.
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  snprintf(mac_str_, sizeof mac_str_, "%02X:%02X:%02X:%02X:%02X:%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
  snprintf(ap_ssid_, sizeof ap_ssid_, "RoztashGw-%02X%02X%02X",
           mac[3], mac[4], mac[5]);

  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(ap_ssid_);  // open network — config only, see header
  if (cfg_.wifi_ssid[0]) {
    WiFi.setAutoReconnect(true);
    WiFi.begin(cfg_.wifi_ssid, cfg_.wifi_pass);
  }

  server.on("/", HTTP_GET, handleRoot);
  server.on("/scan", HTTP_GET, handleScan);
  server.on("/status", HTTP_GET, handleStatus);
  server.on("/save", HTTP_POST, handleSave);
  server.onNotFound(handleRoot);  // any unknown path → the setup form
  server.begin();

  last_sta_attempt_ms_ = millis();
  Serial.printf("[setup] AP \"%s\" open — config at http://%s/ (mac %s)\n",
                ap_ssid_, WiFi.softAPIP().toString().c_str(), mac_str_);
  if (cfg_.wifi_ssid[0])
    Serial.printf("[setup] trying wifi \"%s\" while portal is open\n",
                  cfg_.wifi_ssid);
  else
    Serial.println("[setup] no wifi configured yet — waiting for phone");
}

bool setupPortalPoll() {
  if (!active) return false;
  server.handleClient();

  if (cfg_.wifi_ssid[0] && WiFi.status() == WL_CONNECTED) {
    server.stop();
    WiFi.softAPdisconnect(true);
    WiFi.mode(WIFI_STA);
    active = false;
    Serial.printf("[setup] wifi connected (%s) — leaving setup mode\n",
                  WiFi.localIP().toString().c_str());
    return true;
  }

  const uint32_t now = millis();
  if (now - last_sta_attempt_ms_ > 15000 && cfg_.wifi_ssid[0]) {
    last_sta_attempt_ms_ = now;
    WiFi.reconnect();
  }
  delay(2);
  return false;
}
