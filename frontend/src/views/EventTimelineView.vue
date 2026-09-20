<template>
  <div class="page">
    <div style="display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap">
      <div>
        <h1 style="margin-bottom: 4px">事件时间线</h1>
        <p class="muted" style="margin-top: 0">按 version 展示 event_store 原始事件</p>
      </div>
      <div style="display: flex; gap: 8px">
        <n-button @click="$router.push(`/runs/${id}`)">返回详情</n-button>
        <n-button @click="$router.push(`/runs/${id}/lineage`)">血缘</n-button>
      </div>
    </div>

    <div class="card">
      <n-alert
        v-if="health"
        :type="health.state === 'aligned' ? 'success' : 'error'"
        class="health-alert"
        :show-icon="true"
        :title="
          health.state === 'aligned'
            ? `投影已对齐：事件与投影均为 v${health.event_version}`
            : `投影${health.state === 'missing' ? '缺失' : '滞后'}：事件最高 v${health.event_version}，投影 ${
                health.state === 'missing' ? '缺失' : `v${health.projection_version}`
              }（落后 ${health.lag}）`
        "
      >
        <template #action>
          <n-button size="small" @click="$router.push('/projection-health')">前往投影健康</n-button>
        </template>
      </n-alert>

      <n-timeline v-if="events.length" style="margin-top: 12px">
        <n-timeline-item
          v-for="ev in events"
          :key="ev.id"
          :type="itemType(ev.event_type)"
          :title="`v${ev.version} · ${ev.event_type}`"
          :time="formatTime(ev.occurred_at)"
        >
          <div class="muted" style="margin-bottom: 6px">actor: {{ ev.actor }}</div>
          <pre class="mono" style="white-space: pre-wrap; margin: 0; font-size: 12px">{{
            JSON.stringify(ev.payload_json, null, 2)
          }}</pre>
        </n-timeline-item>
      </n-timeline>
      <n-spin v-else :show="loading" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useMessage } from 'naive-ui'
import { getEvents, getRunProjectionHealth } from '../api/client'

const route = useRoute()
const message = useMessage()
const events = ref([])
const health = ref(null)
const loading = ref(true)
const id = computed(() => route.params.id)

function formatTime(v) {
  return new Date(v).toLocaleString()
}

function itemType(t) {
  if (t === 'RunCompleted') return 'success'
  if (t === 'RunAborted') return 'warning'
  if (t === 'RunStarted') return 'info'
  return 'default'
}

onMounted(async () => {
  try {
    const [evs, h] = await Promise.allSettled([
      getEvents(id.value),
      getRunProjectionHealth(id.value),
    ])
    if (evs.status === 'fulfilled') events.value = evs.value
    else message.error(evs.reason?.message || '加载失败')
    if (h.status === 'fulfilled') health.value = h.value
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.health-alert {
  margin-bottom: 4px;
}
</style>
