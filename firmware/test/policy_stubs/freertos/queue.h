#pragma once
#include <Arduino.h>
#include <deque>
#include <memory>
#include <vector>
struct FakeQueue {
  size_t capacity, item_size;
  std::deque<std::vector<uint8_t>> items;
};
using QueueHandle_t = FakeQueue*;
inline QueueHandle_t xQueueCreate(int capacity, size_t item_size) {
  static std::vector<std::unique_ptr<FakeQueue>> queues;
  queues.push_back(std::make_unique<FakeQueue>(FakeQueue{size_t(capacity), item_size, {}}));
  return queues.back().get();
}
inline void xQueueReset(QueueHandle_t queue) { queue->items.clear(); }
inline int xQueueReceive(QueueHandle_t queue, void* out, int) {
  if (queue->items.empty()) return 0;
  std::memcpy(out, queue->items.front().data(), queue->item_size);
  queue->items.pop_front();
  return pdTRUE;
}
inline int xQueueSend(QueueHandle_t queue, const void* item, int) {
  if (queue->items.size() >= queue->capacity) return 0;
  const auto* first = static_cast<const uint8_t*>(item);
  queue->items.emplace_back(first, first + queue->item_size);
  return pdTRUE;
}
