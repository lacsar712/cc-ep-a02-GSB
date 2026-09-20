<template>
  <div class="page" v-if="run">
    <div style="display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap">
      <div>
        <h1 style="margin-bottom: 4px">{{ run.name }}</h1>
        <p class="muted" style="margin-top: 0">
          {{ run.project }} ·
          <n-tag size="small" :type="statusType">{{ statusLabel }}</n-tag>
          ·
          <span :style="health && health.state !== 'aligned' ? 'color:#d03050;font-weight:700' : ''">
            投影 v{{ run.version }}
          </span>
          / 事件 v{{ health ? health.event_version : '…' }}
        </p>
      </div>
      <div style="display: flex; gap: 8px">
        <n-button @click="$router.push(`/runs/${run.id}/events`)">事件时间线</n-button>
        <n-button @click="$router.push(`/runs/${run.id}/lineage`)">血缘</n-button>
      </div>
    </div>

    <n-alert
      v-if="health && health.state !== 'aligned'"
      type="error"
      class="health-alert"
      :show-icon="true"
      title="投影滞后于 event_store"
    >
      <div>
        事件最高 <strong>v{{ health.event_version }}</strong>，投影仅
        <strong>v{{ health.projection_version }}</strong>
        （落后 {{ health.lag }} 个事件{{ health.state === 'corrupt' ? '，版本异常' : '' }}）。当前详情与血缘是旧数据，事件时间线为准。
      </div>
      <template #action>
        <n-button
          v-if="auth.role === 'researcher'"
          size="small"
          type="warning"
          :loading="rebuilding"
          @click="confirmRebuild"
        >
          按 event_store 全量重建投影
        </n-button>
        <span v-else class="muted" style="font-size: 12px">审计员只读，请由研究员重建</span>
      </template>
    </n-alert>
    <n-alert
      v-else-if="health"
      type="success"
      class="health-alert"
      :show-icon="false"
    >
      投影与事件流已对齐：均为 v{{ health.event_version }}
    </n-alert>

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
      <div class="grid-2">
        <div>
          <h4>RecordMetric</h4>
          <n-input v-model:value="metric.name" placeholder="指标名" style="margin-bottom: 8px" />
          <n-input-number v-model:value="metric.value" style="width: 100%; margin-bottom: 8px" />
          <n-input-number v-model:value="metric.step" :min="0" style="width: 100%; margin-bottom: 8px" />
          <n-button type="primary" :loading="busy" @click="doMetric">记录指标</n-button>
        </div>
        <div>
          <h4>AttachArtifact</h4>
          <n-input v-model:value="artifact.name" placeholder="产物名" style="margin-bottom: 8px" />
          <n-input v-model:value="artifact.uri" placeholder="URI" style="margin-bottom: 8px" />
          <n-input v-model:value="artifact.content_sha256" placeholder="content sha256" class="mono" style="margin-bottom: 8px" />
          <n-button text type="primary" @click="artifact.content_sha256 = randomHex(32)">随机指纹</n-button>
          <div style="margin-top: 8px">
            <n-button type="primary" :loading="busy" @click="doArtifact">挂载产物</n-button>
          </div>
        </div>
      </div>
      <div style="margin-top: 20px; display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end">
        <div style="flex: 1; min-width: 220px">
          <n-input v-model:value="completeSummary" type="textarea" placeholder="完成摘要" :rows="2" />
        </div>
        <n-button type="success" :loading="busy" @click="doComplete">CompleteRun</n-button>
        <div style="flex: 1; min-width: 220px">
          <n-input v-model:value="abortReason" type="textarea" placeholder="中止原因" :rows="2" />
        </div>
        <n-button type="warning" :loading="busy" @click="doAbort">AbortRun</n-button>
      </div>
    </div>
    <div v-else class="card muted">审计员只读：可查看事件与血缘，不可发送命令。</div>
  </div>

  <div class="page" v-else-if="missing">
    <n-result status="warning" title="该 Run 的投影缺失" :description="`event_store 中仍有事件，但读模型投影已被清空。可查看事件时间线，或${
      auth.role === 'researcher' ? '由研究员重建投影。' : '请研究员重建投影。'
    }`">
      <template #footer>
        <n-space>
          <n-button @click="$router.push(`/runs/${route.params.id}/events`)">查看事件时间线</n-button>
          <n-button
            v-if="auth.role === 'researcher'"
            type="warning"
            :loading="rebuilding"
            @click="confirmRebuildMissing"
          >
            按 event_store 全量重建投影
          </n-button>
          <n-button @click="$router.push('/projection-health')">前往投影健康页</n-button>
        </n-space>
      </template>
    </n-result>
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
  getRun,
  getRunProjectionHealth,
  recordMetric,
  rebuildProjection,
} from '../api/client'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const auth = useAuthStore()
const message = useMessage()
const dialog = useDialog()
const run = ref(null)
const health = ref(null)
const missing = ref(false)
const busy = ref(false)
const rebuilding = ref(false)
const completeSummary = ref('')
const abortReason = ref('')

const metric = reactive({ name: 'loss', value: 0.5, step: 1 })
const artifact = reactive({
  name: 'checkpoint.pt',
  uri: 's3://lab-artifacts/checkpoint.pt',
  content_sha256: '',
  media_type: 'application/octet-stream',
})

const canWrite = computed(() => auth.role === 'researcher' && run.value?.status === 'running')
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
  missing.value = false
  health.value = null
  try {
    run.value = await getRun(route.params.id)
  } catch (e) {
    if (e.response?.status === 404) {
      run.value = null
      missing.value = true
    } else {
      throw e
    }
  }
  try {
    health.value = await getRunProjectionHealth(route.params.id)
  } catch {
    // 健康信息加载失败不阻塞详情渲染
  }
}

function confirmRebuild() {
  const h = health.value
  dialog.warning({
    title: '重建投影',
    content: `将读取 event_store 全量重放并覆盖当前投影（事件 v${h.event_version}，投影 v${h.projection_version}）。事件流不会被修改。是否继续？`,
    positiveText: '重建',
    negativeText: '取消',
    onPositiveClick: doRebuild,
  })
}

function confirmRebuildMissing() {
  dialog.warning({
    title: '重建投影',
    content: '投影当前缺失，将读取 event_store 全量重放以恢复读模型。事件流不会被修改。是否继续？',
    positiveText: '重建',
    negativeText: '取消',
    onPositiveClick: doRebuild,
  })
}

async function doRebuild() {
  rebuilding.value = true
  try {
    const result = await rebuildProjection(route.params.id)
    message.success(
      `重建完成：重放 ${result.replayed_events} 个事件，事件 v${result.event_version} = 投影 v${result.projection_version}`,
    )
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

onMounted(async () => {
  try {
    await load()
  } catch (e) {
    message.error(e.message || '加载失败')
  }
})
</script>

<style scoped>
.health-alert {
  margin: 12px 0 16px;
}
</style>
