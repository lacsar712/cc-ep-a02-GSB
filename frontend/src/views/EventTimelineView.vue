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

    <n-alert
      v-if="health"
      :type="health.healthy ? 'success' : 'error'"
      style="margin: 12px 0 16px"
      :title="health.healthy ? '投影已对齐' : '投影滞后于事件流'"
    >
      <template v-if="health.healthy">
        事件最高 version 与投影 version 均为
        <strong class="mono">v{{ health.event_version }}</strong>
      </template>
      <template v-else>
        事件最高 version 为 <strong class="mono">v{{ health.event_version }}</strong>，投影
        <template v-if="health.projection_present">
          停留在 <strong class="mono" style="color: #b91c1c">v{{ health.projection_version }}</strong>
          （滞后 {{ health.lag }} 个事件）
        </template>
        <strong v-else style="color: #b91c1c">缺失</strong>。
        <n-button
          v-if="auth.role === 'researcher'"
          size="tiny"
          type="warning"
          style="margin-left: 10px"
          @click="$router.push(`/runs/${id}`)"
        >
          前往重建
        </n-button>
        <router-link v-else to="/projection-health" style="margin-left: 8px; font-size: 12px">投影健康</router-link>
      </template>
    </n-alert>

    <div class="card">
      <n-timeline v-if="events.length">
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
import { getEvents, getProjectionHealth } from '../api/client'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const message = useMessage()
const auth = useAuthStore()
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
    events.value = await getEvents(id.value)
    try {
      health.value = await getProjectionHealth(id.value)
    } catch {
      /* 健康信息为辅助展示，忽略失败 */
    }
  } catch (e) {
    message.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
})
</script>
