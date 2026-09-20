<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN">
    <n-message-provider>
      <n-dialog-provider>
        <div v-if="auth.token" class="topbar">
          <div class="brand">科学实验溯源工作台</div>
          <div class="nav-links">
            <router-link to="/runs">Run 列表</router-link>
            <router-link v-if="auth.role === 'researcher'" to="/runs/new">新建 Run</router-link>
            <router-link to="/projection-health" class="health-link">
              投影健康
              <n-badge
                v-if="unhealthyCount > 0"
                :value="unhealthyCount"
                :max="99"
                type="error"
                :show="true"
                style="margin-left: 4px"
              />
            </router-link>
            <span class="muted">{{ auth.username }}（{{ roleLabel }}）</span>
            <n-button size="small" quaternary @click="logout">退出</n-button>
          </div>
        </div>
        <router-view />
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { zhCN, dateZhCN } from 'naive-ui'
import { useAuthStore } from './stores/auth'
import { getAllProjectionHealth } from './api/client'

const auth = useAuthStore()
const router = useRouter()

const roleLabel = computed(() => (auth.role === 'researcher' ? '研究员' : '审计员'))
const unhealthyCount = ref(0)
let timer = null

async function refreshHealthBadge() {
  if (!auth.token) {
    unhealthyCount.value = 0
    return
  }
  try {
    const rows = await getAllProjectionHealth()
    unhealthyCount.value = rows.filter((r) => r.state !== 'aligned').length
  } catch {
    // 角标仅辅助提示，静默失败
  }
}

watch(
  () => auth.token,
  (token) => {
    if (token) refreshHealthBadge()
    else unhealthyCount.value = 0
  },
)

onMounted(() => {
  refreshHealthBadge()
  timer = window.setInterval(refreshHealthBadge, 30000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})

function logout() {
  auth.logout()
  router.push('/login')
}
</script>
