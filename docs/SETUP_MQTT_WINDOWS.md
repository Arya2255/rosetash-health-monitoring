# راهنمای نصب MQTT Broker برای برنامه Motosel Employee Health Monitoring

## مرحله ۱: دانلود Mosquitto

۱. مرورگر باز کنید و بروید به:
   https://mosquitto.org/download/

۲. روی **"Windows"** کلیک کنید

۳. فایل installer رو دانلود کنید (مثلاً `mosquitto-2.0.18-install-windows-x64.exe`)

---

## مرحله ۲: نصب Mosquitto

۱. فایل دانلود شده رو اجرا کنید

۲. **Next** → **I Agree** → **Next**

۳. مسیر نصب رو انتخاب کنید (پیش‌فرض `C:\Program Files\mosquitto`)

۴. **Install**

۵. **Finish**

---

## مرحله ۳: کانفیگ Mosquitto

۱. Notepad رو باز کنید

۲. کد زیر رو کپی کنید:

```
# Mosquitto config for Roztash
listener 1884 0.0.0.0
allow_anonymous true
max_connections -1

# Log to file
log_dest file C:\Program Files\mosquitto\mosquitto.log
log_type all
```

۳. فایل رو ذخیره کنید با اسم `mosquitto.conf` توی:
   ```
   C:\Program Files\mosquitto\mosquitto.conf
   ```

---

## مرحله ۴: استارت سرویس

توی CMD (Run as Administrator):

```cmd
cd "C:\Program Files\mosquitto"
mosquitto -c mosquitto.conf
```

یا به عنوان Windows service:

```cmd
"net start mosquitto"
```

---

## مرحله ۵: تست

توی CMD:

```cmd
netstat -an | findstr 1884
```

باید ببینید:
```
TCP    0.0.0.0:1884    0.0.0.0:0    LISTENING
```

---

## نکات مهم:

- اگه می‌خواهید برنامه خودش Mosquitto رو استارت کنه، باید کد رو عوض کنیم
- ESP32 داره به `192.168.137.1:1884` وصل میشه
- برنامه داره به `127.0.0.1:1884` گوش میده

---

اگه مشکلی خوردید، بگید تا کمک کنم.
