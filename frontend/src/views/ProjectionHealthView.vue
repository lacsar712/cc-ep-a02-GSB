<template>
  <div class="page">
    <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px">
      <div>
        <h1 style="margin-bottom: 4px">投影健康</h1>
        <p class="muted" style="margin-top: 0">
          以 event_store 最高 version 为基准对比 run_projections；滞后或缺失的投影可在此按 Run 全量重放重建
        </p>
      </div>
      <n-button :loading="loading" @click="load">刷新</n-button>
    </div>

    <div class="card" style="margin-bottom: 16px; display: flex; gap: 24px; flex-wrap: wrap">
      <div>
        <div class="muted" style="font-size: 12px">Run 总数</div>
        <strong>{{ rows.length }}</strong>
      </div>
      <div>
        <div class="muted" style="font-size: 12px">健康对齐</div>
        <strong style="color: #15803d">{{ healthyCount }}</strong>
      </div>
      <div>
        <div class="muted" style="font-size: 12px">滞后</div>
        <strong style="color: #b45309">{{ lagCount }}</strong>
      </div>
      <div>
        <div class="muted" style="font-size: 12px">投影缺失</div>
        <strong style="color: #b91c1c">{{ missingCount }}</strong>
      </div>
      <div v-if="auth.role !== 'researcher'" class="muted" style="align-self: center; font-size: 12px">
        审计员为只读角色：可查看健康状态，重建操作需研究员执行
      </div>
    </div>

    <n-alert
      v-if="!loading && unhealthyCount > 0"
      type="error"
      style="margin-bottom: 16px"
      :title="`检测到 ${unhealthyCount} 个 Run 的投影与事件流不一致`"
    >
      事件最高 version 大于投影 version（或投影行已丢失）。查询侧详情 / 血缘可能停留在旧状态，
      研究员可点击对应行的「按事件重放重建」恢复。
    </n-alert>
    <n-alert
      v-else-if="!loading && rows.length"
      type="success"
      style="margin-bottom: 16px"
      title="全部 Run 的投影 version 已与 event_store 对齐"
    />

    <div class="card">
      <n-data-table :columns="columns" :data="rows" :loading="loading" :bordered="false" />
    </div>
  </div>
</template>

<script setup>
import { computed, h, onMounted, ref } from 'vue'
import { NButton, NTag, useDialog, useMessage } from 'naive-ui'
import { useRouter } from 'vue-router'
import { listProjectionHealth, rebuildProjection } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const rows = ref([])
const loading = ref(false)
const rebuilding = ref({})

const healthyCount = computed(() => rows.value.filter((r) => r.healthy).length)
const missingCount = computed(() => rows.value.filter((r) => !r.projection_present).length)
const lagCount = computed(
  () => rows.value.filter((r) => r.projection_present && r.lag > 0).length,
)
const unhealthyCount = computed(() => rows.value.length - healthyCount.value)

const columns = [
  {
    title: '项目 / 名称',
    key: 'name',
    render(row) {
      return h('div', [
        h('div', { style: 'font-weight:600' }, row.name || '（投影缺失，名称未知）'),
        h('div', { class: 'muted', style: 'font-size:12px' }, row.project || '—'),
      ])
    },
  },
  {
    title: '事件最高 version',
    key: 'event_version',
    width: 140,
    render(row) {
      return h('span', { class: 'mono' }, `v${row.event_version}`)
    },
  },
  {
    title: '投影 version',
    key: 'projection_version',
    width: 130,
    render(row) {
      if (!row.projection_present) {
        return h(NTag, { type: 'error', size: 'small' }, { default: () => '投影缺失' })
      }
      return h('span', { class: 'mono' }, `v${row.projection_version}`)
    },
  },
  {
    title: '滞后',
    key: 'lag',
    width: 90,
    render(row) {
      if (row.healthy) {
        return h(NTag, { type: 'success', size: 'small' }, { default: () => '已对齐' })
      }
      return h(
        NTag,
        { type: 'error', size: 'small', bordered: false },
        { default: () => (row.projection_present ? `滞后 ${row.lag}` : `缺失 v${row.event_version}`) },
      )
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 300,
    render(row) {
      const buttons = [
        h(
          NButton,
          { size: 'tiny', onClick: () => router.push(`/runs/${row.run_id}`) },
          { default: () => '详情' },
        ),
        h(
          NButton,
          { size: 'tiny', quaternary: true, onClick: () => router.push(`/runs/${row.run_id}/events`) },
          { default: () => '事件' },
        ),
      ]
      if (!row.healthy && auth.role === 'researcher') {
        buttons.push(
          h(
            NButton,
            {
              size: 'tiny',
              type: 'warning',
              loading: !!rebuilding.value[row.run_id],
              onClick: () => askRebuild(row),
            },
            { default: () => '按事件重放重建' },
          ),
        )
      }
      return h('div', { style: 'display:flex;gap:8px;flex-wrap:wrap' }, buttons)
    },
  },
]

async function load() {
  loading.value = true
  try {
    rows.value = await listProjectionHealth()
  } catch (e) {
    message.error(e.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function askRebuild(row) {
  dialog.warning({
    title: '按 event_store 全量重放重建投影？',
    content: `将删除并重建「${row.name || row.run_id}」的查询侧投影（不会改动任何事件）。重放 ${row.event_version} 个事件后投影 version 将对齐到 v${row.event_version}。`,
    positiveText: '重建',
    negativeText: '取消',
    onPositiveClick: () => doRebuild(row),
  })
}

async function doRebuild(row) {
  rebuilding.value = { ...rebuilding.value, [row.run_id]: true }
  try {
    const proj = await rebuildProjection(row.run_id)
    message.success(`重建完成：投影 version 已对齐到 v${proj.version}`)
    await load()
  } catch (e) {
    message.error(e.message || '重建失败')
  } finally {
    const next = { ...rebuilding.value }
    delete next[row.run_id]
    rebuilding.value = next
  }
}

onMounted(load)
</script>
