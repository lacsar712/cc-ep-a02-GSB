<template>
  <div class="page">
    <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap">
      <div>
        <h1 style="margin-bottom: 4px">投影健康</h1>
        <p class="muted" style="margin-top: 0">
          对比每个 Run 在 event_store 的最高 version 与读模型投影 version；研究员可按事件流全量重放重建。
        </p>
      </div>
      <n-button :loading="loading" @click="load">刷新</n-button>
    </div>

    <n-alert
      v-if="!loading && summary.unhealthy > 0"
      type="error"
      class="health-banner"
      :show-icon="true"
      title="检测到投影与事件流不一致"
    >
      <div>
        共 {{ summary.total }} 个 Run：
        <strong>{{ summary.lagging }}</strong> 个滞后、
        <strong>{{ summary.missing }}</strong> 个投影缺失、
        <strong>{{ summary.corrupt }}</strong> 个版本异常。
        请研究员在下方对受影响 Run 执行「重建投影」；审计员为只读，可查看但不能重建。
      </div>
    </n-alert>
    <n-alert
      v-else-if="!loading"
      type="success"
      class="health-banner"
      :show-icon="true"
      title="全部投影已与 event_store 对齐"
    />

    <div class="card">
      <n-data-table :columns="columns" :data="rows" :loading="loading" :bordered="false" />
    </div>
  </div>
</template>

<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { NAlert, NButton, NTag, useDialog, useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import { getAllProjectionHealth, rebuildProjection } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()

const rows = ref([])
const loading = ref(false)
const rebuilding = ref(new Set())

const STATE_MAP = {
  aligned: { type: 'success', label: '已对齐' },
  lagging: { type: 'error', label: '滞后' },
  missing: { type: 'error', label: '投影缺失' },
  corrupt: { type: 'error', label: '版本异常' },
}

const summary = computed(() => ({
  total: rows.value.length,
  unhealthy: rows.value.filter((r) => r.state !== 'aligned').length,
  lagging: rows.value.filter((r) => r.state === 'lagging').length,
  missing: rows.value.filter((r) => r.state === 'missing').length,
  corrupt: rows.value.filter((r) => r.state === 'corrupt').length,
}))

function linkButtons(row) {
  return h(
    'div',
    { style: 'display:flex;gap:6px;flex-wrap:wrap' },
    [
      h(NButton, { size: 'tiny', onClick: () => router.push(`/runs/${row.run_id}`) }, { default: () => '详情' }),
      h(NButton, { size: 'tiny', quaternary: true, onClick: () => router.push(`/runs/${row.run_id}/events`) }, { default: () => '事件' }),
      h(NButton, { size: 'tiny', quaternary: true, onClick: () => router.push(`/runs/${row.run_id}/lineage`) }, { default: () => '血缘' }),
    ],
  )
}

const columns = computed(() => [
  { title: '项目', key: 'project', render: (row) => row.project || '—' },
  { title: '名称', key: 'name', render: (row) => row.name || '（投影缺失）' },
  {
    title: '事件最高 version',
    key: 'event_version',
    width: 140,
    render: (row) => h('span', { class: 'mono' }, `v${row.event_version}`),
  },
  {
    title: '投影 version',
    key: 'projection_version',
    width: 120,
    render: (row) =>
      h(
        'span',
        { class: 'mono', style: row.state === 'aligned' ? '' : 'color:#d03050;font-weight:600' },
        row.state === 'missing' ? '缺失' : `v${row.projection_version}`,
      ),
  },
  {
    title: '滞后量',
    key: 'lag',
    width: 80,
    render: (row) =>
      h(
        'span',
        { style: row.lag > 0 ? 'color:#d03050;font-weight:700' : 'color:#18a058' },
        row.lag,
      ),
  },
  {
    title: '状态',
    key: 'state',
    width: 110,
    render(row) {
      const m = STATE_MAP[row.state] || { type: 'default', label: row.state }
      return h(NTag, { type: m.type, size: 'small' }, { default: () => m.label })
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 300,
    render(row) {
      const kids = [linkButtons(row)]
      if (auth.role === 'researcher') {
        kids.push(
          h(
            NButton,
            {
              size: 'tiny',
              type: row.state === 'aligned' ? 'default' : 'warning',
              loading: rebuilding.value.has(row.run_id),
              onClick: () => confirmRebuild(row),
            },
            { default: () => '重建投影' },
          ),
        )
      } else {
        kids.push(h('span', { class: 'muted', style: 'font-size:12px' }, '审计员只读'))
      }
      return h('div', { style: 'display:flex;gap:6px;flex-wrap:wrap;align-items:center' }, kids)
    },
  },
])

async function load() {
  loading.value = true
  try {
    rows.value = await getAllProjectionHealth()
  } catch (e) {
    message.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function confirmRebuild(row) {
  dialog.warning({
    title: '重建投影',
    content: `将读取 event_store 全量重放并覆盖「${row.name || row.run_id}」当前的投影（事件 v${row.event_version}，投影 ${
      row.state === 'missing' ? '缺失' : `v${row.projection_version}`
    }）。事件流不会被修改。是否继续？`,
    positiveText: '重建',
    negativeText: '取消',
    onPositiveClick: () => doRebuild(row),
  })
}

async function doRebuild(row) {
  const next = new Set(rebuilding.value)
  next.add(row.run_id)
  rebuilding.value = next
  try {
    const result = await rebuildProjection(row.run_id)
    message.success(
      `重建完成：重放 ${result.replayed_events} 个事件，事件 v${result.event_version} = 投影 v${result.projection_version}`,
    )
    await load()
  } catch (e) {
    message.error(e.message || '重建失败')
  } finally {
    const rest = new Set(rebuilding.value)
    rest.delete(row.run_id)
    rebuilding.value = rest
  }
}

onMounted(load)
</script>

<style scoped>
.health-banner {
  margin: 12px 0 16px;
}
</style>
