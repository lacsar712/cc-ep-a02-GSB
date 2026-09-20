<template>
  <div class="page">
    <div style="display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap">
      <div>
        <h1 style="margin-bottom: 4px">实验血缘</h1>
        <p class="muted" style="margin-top: 0">
          <template v-if="lineage">
            {{ lineage.project }} / {{ lineage.name }} · {{ lineage.status }} · 投影 v{{ lineage.version }}
            <template v-if="health"> / 事件 v{{ health.event_version }}</template>
          </template>
          <template v-else>投影缺失</template>
        </p>
      </div>
      <div style="display: flex; gap: 8px">
        <n-button @click="$router.push(`/runs/${id}`)">返回详情</n-button>
        <n-button @click="$router.push(`/runs/${id}/events`)">事件</n-button>
      </div>
    </div>

    <n-alert
      v-if="health"
      :type="health.state === 'aligned' ? 'success' : 'error'"
      style="margin-bottom: 16px"
      :show-icon="true"
      :title="
        health.state === 'aligned'
          ? `投影与事件流已对齐：均为 v${health.event_version}`
          : `投影${health.state === 'missing' ? '缺失' : '滞后'}：事件最高 v${health.event_version}，投影 ${
              health.state === 'missing' ? '缺失' : `v${health.projection_version}`
            }（落后 ${health.lag}），血缘数据可能不完整`
      "
    >
      <template #action>
        <n-button size="small" @click="$router.push('/projection-health')">前往投影健康</n-button>
      </template>
    </n-alert>

    <div v-if="!lineage" class="card">
      <n-spin v-if="loading" />
      <n-result
        v-else
        status="warning"
        title="血缘不可读：投影缺失"
        description="event_store 中仍有事件，但读模型投影已被清空。"
      >
        <template #footer>
          <n-space>
            <n-button @click="$router.push(`/runs/${id}/events`)">查看事件时间线</n-button>
            <n-button type="warning" @click="$router.push('/projection-health')">前往投影健康</n-button>
          </n-space>
        </template>
      </n-result>
    </div>

    <template v-else>
      <div class="card" style="margin-bottom: 16px">
        <h3 style="margin-top: 0">血缘字段</h3>
        <div class="grid-2">
          <div>
            <div class="muted">code_commit_sha</div>
            <div class="mono">{{ lineage.code_commit_sha }}</div>
          </div>
          <div>
            <div class="muted">dataset_content_sha256</div>
            <div class="mono">{{ lineage.dataset_content_sha256 }}</div>
          </div>
          <div>
            <div class="muted">started_by / started_at</div>
            <div>{{ lineage.started_by }} · {{ formatTime(lineage.started_at) }}</div>
          </div>
          <div>
            <div class="muted">finished_at</div>
            <div>{{ lineage.finished_at ? formatTime(lineage.finished_at) : '—' }}</div>
          </div>
        </div>
        <p v-if="lineage.result_summary"><strong>结果：</strong>{{ lineage.result_summary }}</p>
        <p v-if="lineage.abort_reason"><strong>中止：</strong>{{ lineage.abort_reason }}</p>
      </div>

      <div class="grid-2" style="margin-bottom: 16px">
        <div class="card">
          <h3 style="margin-top: 0">Artifacts</h3>
          <ul v-if="lineage.artifacts?.length">
            <li v-for="(a, i) in lineage.artifacts" :key="i">
              <strong>{{ a.name }}</strong>
              <div class="mono muted" style="font-size: 12px">{{ a.content_sha256 }}</div>
              <div class="muted" style="font-size: 12px">{{ a.uri }}</div>
            </li>
          </ul>
          <p v-else class="muted">无产物</p>
        </div>
        <div class="card">
          <h3 style="margin-top: 0">Metrics 汇总</h3>
          <ul v-if="lineage.metrics?.length">
            <li v-for="(m, i) in lineage.metrics" :key="i">
              {{ m.name }} = {{ m.value }} @ step {{ m.step }}
            </li>
          </ul>
          <p v-else class="muted">无指标</p>
        </div>
      </div>

      <div class="card" v-if="chartSeries.length">
        <h3 style="margin-top: 0">指标折线（辅助）</h3>
        <svg class="metric-chart" viewBox="0 0 400 180" preserveAspectRatio="none">
          <polyline
            v-for="(series, idx) in chartSeries"
            :key="series.name"
            fill="none"
            :stroke="colors[idx % colors.length]"
            stroke-width="2"
            :points="series.points"
          />
        </svg>
        <div style="display: flex; gap: 12px; flex-wrap: wrap">
          <span v-for="(s, idx) in chartSeries" :key="s.name" class="muted">
            <span :style="{ color: colors[idx % colors.length] }">■</span> {{ s.name }}
          </span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useMessage } from 'naive-ui'
import { getLineage, getRunProjectionHealth } from '../api/client'

const route = useRoute()
const message = useMessage()
const lineage = ref(null)
const health = ref(null)
const loading = ref(true)
const id = computed(() => route.params.id)
const colors = ['#0f766e', '#b45309', '#1d4ed8', '#be123c']

function formatTime(v) {
  return new Date(v).toLocaleString()
}

const chartSeries = computed(() => {
  const metrics = lineage.value?.metrics || []
  if (!metrics.length) return []
  const byName = {}
  for (const m of metrics) {
    if (!byName[m.name]) byName[m.name] = []
    byName[m.name].push(m)
  }
  return Object.entries(byName).map(([name, items]) => {
    const sorted = [...items].sort((a, b) => a.step - b.step)
    const values = sorted.map((x) => x.value)
    const min = Math.min(...values)
    const max = Math.max(...values)
    const span = max - min || 1
    const points = sorted
      .map((x, i) => {
        const px = sorted.length === 1 ? 200 : (i / (sorted.length - 1)) * 380 + 10
        const py = 160 - ((x.value - min) / span) * 140
        return `${px},${py}`
      })
      .join(' ')
    return { name, points }
  })
})

onMounted(async () => {
  try {
    const [lin, h] = await Promise.allSettled([
      getLineage(id.value),
      getRunProjectionHealth(id.value),
    ])
    if (lin.status === 'fulfilled') lineage.value = lin.value
    if (h.status === 'fulfilled') health.value = h.value
  } finally {
    loading.value = false
  }
})
</script>
