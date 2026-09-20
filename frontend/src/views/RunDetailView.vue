<template>
  <div class="page">
    <n-spin :show="loading">
      <n-alert
        v-if="health && !health.healthy"
        type="error"
        style="margin-bottom: 16px"
        :title="health.projection_present ? '投影滞后于事件流' : '投影缺失（run_projections 中无此行）'"
      >
        <div style="display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; align-items: center">
          <div>
            事件最高 version：<strong class="mono">v{{ health.event_version }}</strong>
            ，投影 version：
            <strong class="mono" style="color: #b91c1c">
              {{ health.projection_present ? `v${health.projection_version}（滞后 ${health.lag}）` : '缺失' }}
            </strong>
            。下方查询侧内容可能停留在旧状态。
            <div style="margin-top: 4px">
              <router-link :to="`/runs/${runId}/events`">查看事件时间线</router-link>
              ·
              <router-link to="/projection-health">投影健康总览</router-link>
            </div>
          </div>
          <n-button
            v-if="auth.role === 'researcher'"
            type="warning"
            :loading="rebuilding"
            @click="askRebuild"
          >
            按 event_store 全量重放重建
          </n-button>
          <span v-else class="muted" style="font-size: 12px">审计员只读：请联系研究员重建</span>
        </div>
      </n-alert>

      <n-alert
        v-else-if="health && health.healthy"
        type="success"
        style="margin-bottom: 16px"
      >
        投影已对齐：事件最高 version 与投影 version 均为
        <strong class="mono">v{{ health.event_version }}</strong>
        <router-link to="/projection-health" style="margin-left: 8px; font-size: 12px">投影健康</router-link>
      </n-alert>

      <div v-if="run">
        <div style="display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap">
          <div>
            <h1 style="margin-bottom: 4px">{{ run.name }}</h1>
            <p class="muted" style="margin-top: 0">
              {{ run.project }} ·
              <n-tag size="small" :type="statusType">{{ statusLabel }}</n-tag>
              · 投影 version <strong class="mono">{{ run.version }}</strong>
              <template v-if="health"> · 事件最高 version <strong class="mono">{{ health.event_version }}</strong></template>
            </p>
          </div>
          <div style="display: flex; gap: 8px">
            <n-button @click="$router.push(`/runs/${run.id}/events`)">事件时间线</n-button>
            <n-button @click="$router.push(`/runs/${run.id}/lineage`)">血缘</n-button>
          </div>
        </div>

        <div class="card" style="margin-bottom: 16px">
          <div class="grid-2">
            <div>
              <div class="muted">dataset_content_sha256</div>
              <div class="mono">{{ run.dataset_content_sha256 }}</div>
            </div>
            <div>
              <div class="muted">code_commit_sha</div>
              <div class="mono">{{ run.code_commit_sha }}</div>
            </div>
            <div>
              <div class="muted">started_by / started_at</div>
              <div>{{ run.started_by }} · {{ formatTime(run.started_at) }}</div>
            </div>
            <div>
              <div class="muted">finished_at</div>
              <div>{{ run.finished_at ? formatTime(run.finished_at) : '—' }}</div>
            </div>
          </div>
          <p v-if="run.description" style="margin-top: 12px">{{ run.description }}</p>
          <p v-if="run.result_summary"><strong>结果：</strong>{{ run.result_summary }}</p>
          <p v-if="run.abort_reason"><strong>中止原因：</strong>{{ run.abort_reason }}</p>
        </div>

        <div class="grid-2" style="margin-bottom: 16px">
          <div class="card">
            <h3 style="margin-top: 0">指标（投影）</h3>
            <n-data-table
              size="small"
              :columns="metricCols"
              :data="run.metrics_json || []"
              :bordered="false"
            />
          </div>
          <div class="card">
            <h3 style="margin-top: 0">产物（投影）</h3>
            <n-data-table
              size="small"
              :columns="artifactCols"
              :data="run.artifacts_json || []"
              :bordered="false"
            />
          </div>
        </div>

        <div v-if="canWrite" class="card">
          <h3 style="margin-top: 0">命令操作区（乐观锁 expected_version = {{ run.version }}）</h3>
          <n-alert v-if="lagging" type="warning" style="margin-bottom: 12px">
            投影滞后期间发送命令会触发 409 版本冲突，请先按 event_store 重建投影后再操作。
          </n-alert>
          <n-form :disabled="lagging">
            <div class="grid-2">
              <div>
                <h4>RecordMetric</h4>
                <n-input v-model:value="metric.name" placeholder="指标名" style="margin-bottom: 8px" />
                <n-input-number v-model:value="metric.value" style="width: 100%; margin-bottom: 8px" />
                <n-input-number v-model:value="metric.step" :min="0" style="width: 100%; margin-bottom: 8px" />
                <n-button type="primary" :loading="busy" :disabled="lagging" @click="doMetric">记录指标</n-button>
              </div>
              <div>
                <h4>AttachArtifact</h4>
                <n-input v-model:value="artifact.name" placeholder="产物名" style="margin-bottom: 8px" />
                <n-input v-model:value="artifact.uri" placeholder="URI" style="margin-bottom: 8px" />
                <n-input v-model:value="artifact.content_sha256" placeholder="content sha256" class="mono" style="margin-bottom: 8px" />
                <n-button text type="primary" @click="artifact.content_sha256 = randomHex(32)">随机指纹</n-button>
                <div style="margin-top: 8px">
                  <n-button type="primary" :loading="busy" :disabled="lagging" @click="doArtifact">挂载产物</n-button>
                </div>
              </div>
            </div>
            <div style="margin-top: 20px; display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end">
              <div style="flex: 1; min-width: 220px">
                <n-input v-model:value="completeSummary" type="textarea" placeholder="完成摘要" :rows="2" />
              </div>
              <n-button type="success" :loading="busy" :disabled="lagging" @click="doComplete">CompleteRun</n-button>
              <div style="flex: 1; min-width: 220px">
                <n-input v-model:value="abortReason" type="textarea" placeholder="中止原因" :rows="2" />
              </div>
              <n-button type="warning" :loading="busy" :disabled="lagging" @click="doAbort">AbortRun</n-button>
            </div>
          </n-form>
        </div>
        <div v-else class="card muted">审计员只读：可查看事件与血缘，不可发送命令。</div>
      </div>

      <div v-else-if="health" class="card">
        <h2 style="margin-top: 0">该 Run 的投影已丢失</h2>
        <p class="muted">
          event_store 中仍保留 <strong class="mono">{{ health.event_version }}</strong>
          个事件（最高 version <strong class="mono">v{{ health.event_version }}</strong>），
          但 run_projections 中没有对应行，详情与血缘暂不可读。
        </p>
        <div style="display: flex; gap: 8px">
          <n-button
            v-if="auth.role === 'researcher'"
            type="warning"
            :loading="rebuilding"
            @click="askRebuild"
          >
            按 event_store 全量重放重建投影
          </n-button>
          <n-button @click="$router.push(`/runs/${runId}/events`)">查看事件时间线</n-button>
          <n-button @click="$router.push('/projection-health')">投影健康</n-button>
        </div>
        <p v-if="auth.role !== 'researcher'" class="muted" style="font-size: 12px">
          审计员为只读角色，重建操作需研究员执行。
        </p>
      </div>
    </n-spin>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useDialog, useMessage } from 'naive-ui'
import {
  abortRun,
  attachArtifact,
  completeRun,
  getProjectionHealth,
  getRun,
  rebuildProjection,
  recordMetric,
} from '../api/client'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const auth = useAuthStore()
const message = useMessage()
const dialog = useDialog()
const run = ref(null)
const health = ref(null)
const loading = ref(false)
const rebuilding = ref(false)
const busy = ref(false)
const completeSummary = ref('')
const abortReason = ref('')

const runId = computed(() => route.params.id)
const lagging = computed(() => health.value != null && !health.value.healthy)

const metric = reactive({ name: 'loss', value: 0.5, step: 1 })
const artifact = reactive({
  name: 'checkpoint.pt',
  uri: 's3://lab-artifacts/checkpoint.pt',
  content_sha256: '',
  media_type: 'application/octet-stream',
})

const canWrite = computed(
  () => auth.role === 'researcher' && run.value?.status === 'running',
)
const statusLabel = computed(() => {
  const m = { running: '进行中', completed: '已完成', aborted: '已中止' }
  return m[run.value?.status] || run.value?.status
})
const statusType = computed(() => {
  const m = { running: 'info', completed: 'success', aborted: 'warning' }
  return m[run.value?.status] || 'default'
})

const metricCols = [
  { title: 'name', key: 'name' },
  { title: 'value', key: 'value' },
  { title: 'step', key: 'step' },
]
const artifactCols = [
  { title: 'name', key: 'name' },
  { title: 'uri', key: 'uri', ellipsis: { tooltip: true } },
]

function formatTime(v) {
  return v ? new Date(v).toLocaleString() : '—'
}

function randomHex(n) {
  const bytes = new Uint8Array(n)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

async function load() {
  loading.value = true
  run.value = null
  try {
    try {
      run.value = await getRun(runId.value)
    } catch (e) {
      // 投影可能被清空：404 时降级到健康检查，仍可引导重建
      if (!e.response || e.response.status !== 404) throw e
    }
    health.value = await getProjectionHealth(runId.value)
  } catch (e) {
    message.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function askRebuild() {
  dialog.warning({
    title: '按 event_store 全量重放重建投影？',
    content: `将删除并重建该 Run 的查询侧投影（不会改动任何事件），重放 ${health.value?.event_version ?? ''} 个事件后 version 对齐到 v${health.value?.event_version ?? ''}。`,
    positiveText: '重建',
    negativeText: '取消',
    onPositiveClick: doRebuild,
  })
}

async function doRebuild() {
  rebuilding.value = true
  try {
    const proj = await rebuildProjection(runId.value)
    message.success(`重建完成：投影 version 已对齐到 v${proj.version}`)
    await load()
  } catch (e) {
    message.error(e.message || '重建失败')
  } finally {
    rebuilding.value = false
  }
}

async function withBusy(fn) {
  busy.value = true
  try {
    await fn()
    message.success('命令已接受')
    await load()
  } catch (e) {
    message.error(e.message || '命令失败')
  } finally {
    busy.value = false
  }
}

function doMetric() {
  return withBusy(async () => {
    await recordMetric(run.value.id, {
      name: metric.name,
      value: metric.value,
      step: metric.step,
      expected_version: run.value.version,
    })
    metric.step += 1
  })
}

function doArtifact() {
  if (!artifact.content_sha256 || artifact.content_sha256.length !== 64) {
    message.warning('请填写 64 位 content_sha256')
    return
  }
  return withBusy(() =>
    attachArtifact(run.value.id, {
      ...artifact,
      expected_version: run.value.version,
    }),
  )
}

function doComplete() {
  if (!completeSummary.value.trim()) {
    message.warning('请填写完成摘要')
    return
  }
  return withBusy(() =>
    completeRun(run.value.id, {
      result_summary: completeSummary.value,
      expected_version: run.value.version,
    }),
  )
}

function doAbort() {
  if (!abortReason.value.trim()) {
    message.warning('请填写中止原因')
    return
  }
  return withBusy(() =>
    abortRun(run.value.id, {
      reason: abortReason.value,
      expected_version: run.value.version,
    }),
  )
}

onMounted(load)
</script>
