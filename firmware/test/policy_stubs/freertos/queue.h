#pragma once
#include <Arduino.h>
using QueueHandle_t = void*;
inline QueueHandle_t xQueueCreate(int, size_t) { return reinterpret_cast<void*>(1); }
inline void xQueueReset(QueueHandle_t) {}
inline int xQueueReceive(QueueHandle_t, void*, int) { return 0; }
inline int xQueueSend(QueueHandle_t, const void*, int) { return 1; }
