#pragma once
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdarg>
#include <string>
inline uint32_t fake_ms = 0;
inline uint32_t millis() { return fake_ms; }
#define strlcpy host_strlcpy
inline size_t host_strlcpy(char* dst, const char* src, size_t cap) {
  const auto n = std::strlen(src);
  if (cap) { const auto copy = n < cap - 1 ? n : cap - 1; std::memcpy(dst, src, copy); dst[copy] = 0; }
  return n;
}
struct FakeSerial { void printf(const char*, ...) {} void println(const char*) {} };
inline FakeSerial Serial;
using portMUX_TYPE = int;
#define portMUX_INITIALIZER_UNLOCKED 0
#define portENTER_CRITICAL(mux) ((void)(mux))
#define portEXIT_CRITICAL(mux) ((void)(mux))
using TaskHandle_t = void*;
constexpr int pdPASS = 1, pdTRUE = 1;
constexpr uint32_t portMAX_DELAY = UINT32_MAX;
#define pdMS_TO_TICKS(ms) (ms)
inline void (*fake_worker)(void*) = nullptr;
inline void* fake_worker_arg = nullptr;
inline void (*fake_wait)() = nullptr;
inline void (*fake_delay)(uint32_t) = nullptr;
inline int xTaskCreate(void (*entry)(void*), const char*, uint32_t, void* arg, int, TaskHandle_t* handle) {
  if (handle) {
    *handle = reinterpret_cast<void*>(1);
    fake_worker = entry;
    fake_worker_arg = arg;
  }
  return pdPASS;
}
inline void xTaskNotifyGive(TaskHandle_t) {}
inline void ulTaskNotifyTake(int, uint32_t) { if (fake_wait) fake_wait(); }
inline void vTaskDelay(uint32_t ms) { if (fake_delay) fake_delay(ms); }
