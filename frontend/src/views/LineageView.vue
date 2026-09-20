<template>
  <div class="page">
    <n-spin :show="loading">
      <n-alert
        v-if="health && !health.healthy"
        type="error"
        style="margin-bottom: 16px"
        title="投影滞后：血缘数据可能不完整"
      >
        <div style="display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: center">
          <div>
            事件最高 version：<strong class="mono">v{{ health.event_version }}</strong>
            ，投影 version：
            <strong class="mono" style="color: #b91c1c">
              {{ health.projection_present ? `v${health.projection_version}（滞后 ${health.lag}）` : '缺失' }}
            </strong>
            。请重建投影后再查看血缘。
          </div>
          <n-button
            v-if="auth.role === 'researcher'"
            type="warning"
            size="small"
            @click="$router.push(`/runs/${id}`)"
          >
            前往重建
          </n-button>
        </div>
      </n-alert>

      <div v-if="lineage">
        <div style="display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap">
          <div>
            <h1 style="margin-bottom: 4px">实验血缘</h1>
            <p class="muted" style="margin-top: 0">
              {{ lineage.project }} / {{ lineage.name }} · {{ lineage.status }} ·
              投影 v{{ lineage.version }}
              <template v-if="health"> · 事件最高 v{{ health.event_version }}</template>
            </p>
          </div>
          <div style="display: flex; gap: 8px">
            <n-button @click="$router.push(`/runs/${id}`)">返回详情</n-button>
            <n-button @click="$router.push(`/runs/${id}/events`)">事件</n-button>
          </div>
        </div>

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
      </div>

      <div v-else-if="health" class="card">
        <h2 style="margin-top: 0">血缘暂不可读：投影缺失</h2>
        <p class="muted">
          event_store 中保留 {{ health.event_version }} 个事件，但 run_projections 无此行。
          <template v-if="auth.role === 'researcher'">请在详情页按事件全量重放重建。</template>
          <template v-else>审计员只读，请联系研究员重建。</template>
        </p>
        <n-button
          v-if="auth.role === 'researcher'"
          type="warning"
          @click="$router.push(`/runs/${id}`)"
        >
          前往详情页重建
        </n-button>
      </div>
    </n-spin>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useMessage } from 'naive-ui'
import { getLineage, getProjectionHealth } from '../api/client'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const message = useMessage()
const auth = useAuthStore()
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
    try {
      lineage.value = await getLineage(id.value)
    } catch (e) {
      if (!e.response || e.response.status !== 404) throw e
    }
    try {
      health.value = await getProjectionHealth(id.value)
    } catch (e) {
      // 健康接口 404 仅说明事件也不存在，交由页面空态处理
    }
  } catch (e) {
    message.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
})
</script>
