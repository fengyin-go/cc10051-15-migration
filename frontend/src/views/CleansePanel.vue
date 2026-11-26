<template>
  <section class="cleanse-panel" data-testid="cleanse-panel">
    <header class="panel-head">
      <h3>清洗码表领用（按服务端发布版次领取完整版本）</h3>
      <span class="runtime-tag" data-testid="cleanse-runtime">运行时：{{ runtimeLabel }}</span>
    </header>

    <p v-if="message" class="panel-msg" :class="messageKind" data-testid="cleanse-message">{{ message }}</p>

    <form class="claim-box" @submit.prevent="claim">
      <label class="create-field">
        <span>码表编号（数据集编码）</span>
        <input v-model="datasetCode" data-testid="claim-dataset" required placeholder="如 REF-COUNTRY" />
      </label>
      <label class="create-field">
        <span>清洗批次号</span>
        <input v-model="batchNo" data-testid="claim-batch" required placeholder="如 BATCH-20261126-01" />
      </label>
      <button class="btn primary" type="submit" data-testid="claim-submit">领取当前批次码表</button>
    </form>

    <!-- 阻断回执：旧版应用无法承载特殊字符版本时明确提示，不静默丢值 -->
    <div v-if="blocked" class="block-box" data-testid="claim-blocked">
      <h4>领用阻断回执</h4>
      <p>{{ blocked.message }}</p>
      <ul v-if="blocked.incompatible_entries?.length">
        <li v-for="entry in blocked.incompatible_entries" :key="entry.code">
          <code>{{ entry.code }}</code> → <code>{{ entry.value }}</code>
        </li>
      </ul>
      <p class="hint">阻断版次：{{ blocked.blocked_version }} ｜ 原因码：{{ blocked.reason }}</p>
    </div>

    <!-- 领用成功：展示整版快照，确认未拼装新旧条目 -->
    <div v-if="claimResult" class="detail-box" data-testid="claim-result">
      <h4>已领用完整码表版本</h4>
      <p class="hint">
        码表 {{ claimResult.dataset_code }} ｜ 版次 <strong>{{ claimResult.version_no }}</strong>
        ｜ 条目格式 {{ claimResult.entry_format }} ｜ 运行时 {{ claimResult.runtime_mode }}
        <span v-if="claimResult.reused">（批次已锁定，返回原快照）</span>
      </p>
      <table class="data-table">
        <thead>
          <tr><th>码（code）</th><th>标准值（value）</th></tr>
        </thead>
        <tbody>
          <tr v-for="entry in claimResult.entries" :key="entry.code">
            <td><code>{{ entry.code }}</code></td>
            <td>{{ entry.value }}</td>
          </tr>
        </tbody>
      </table>

      <form class="normalize-box" @submit.prevent="normalizeValue">
        <label class="create-field">
          <span>待归一化原始值（试试 CN 或 A=B）</span>
          <input v-model="rawValue" data-testid="normalize-input" required />
        </label>
        <button class="btn primary" type="submit" data-testid="normalize-submit">归一化</button>
      </form>
      <p v-if="normalized" class="panel-msg ok" data-testid="normalize-result">
        「{{ normalized.raw }}」→「{{ normalized.normalized }}」
        （{{ normalized.mapped ? '命中码表映射' : '未命中，按规则回退大写' }}，版次 {{ normalized.version_no }}）
      </p>
    </div>

    <!-- 历史批次：信息记录复算 -->
    <div class="history-box">
      <h4>历史批次复算与领用记录</h4>
      <form class="claim-box" @submit.prevent="recompute">
        <label class="create-field">
          <span>历史批次号</span>
          <input v-model="historyBatch" data-testid="recompute-batch" required placeholder="如 BATCH-20260901-01" />
        </label>
        <button class="btn" type="submit" data-testid="recompute-submit">按原有效版复算</button>
      </form>
      <div v-if="recomputeResult" class="detail-box" data-testid="recompute-result">
        <p class="hint">
          复算版次 {{ recomputeResult.version_no }} ｜
          与原结果{{ recomputeResult.all_consistent ? '完全一致' : '存在差异' }}
        </p>
        <table class="data-table">
          <thead>
            <tr><th>原始值</th><th>原结果</th><th>复算结果</th><th>一致</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in recomputeResult.reruns" :key="row.raw">
              <td>{{ row.raw }}</td>
              <td>{{ row.original }}</td>
              <td>{{ row.recomputed }}</td>
              <td>{{ row.consistent ? '是' : '否' }}</td>
            </tr>
            <tr v-if="!recomputeResult.reruns?.length">
              <td colspan="4" class="empty-state">该批次暂无归一化记录</td>
            </tr>
          </tbody>
        </table>
      </div>

      <h5>全部领用记录（批次 ↔ 完整版次锁定）</h5>
      <table class="data-table" data-testid="claims-table">
        <thead>
          <tr><th>批次号</th><th>码表编号</th><th>领用版次</th><th>下发格式</th><th>运行时</th><th>条目数</th></tr>
        </thead>
        <tbody>
          <tr v-for="claim in claims" :key="claim.id">
            <td>{{ claim.batch_no }}</td>
            <td>{{ claim.dataset_code }}</td>
            <td>{{ claim.version_no }}</td>
            <td>{{ claim.entry_format }}</td>
            <td>{{ claim.runtime_mode }}</td>
            <td>{{ claim.entry_count }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  codeTableApi,
  type ClaimResult,
  type CodeTableClaim,
} from '@/api/code-table'

const runtimeMode = ref('new_runtime')
const datasetCode = ref('REF-COUNTRY')
const batchNo = ref('')
const historyBatch = ref('BATCH-20260901-01')
const rawValue = ref('')
const claimResult = ref<ClaimResult | null>(null)
const blocked = ref<ClaimResult | null>(null)
const normalized = ref<{ raw: string; normalized: string; mapped: boolean; version_no: string } | null>(null)
const recomputeResult = ref<{
  ok: boolean
  message?: string
  version_no?: string
  all_consistent?: boolean
  reruns?: { raw: string; original: string; recomputed: string; consistent: boolean }[]
} | null>(null)
const claims = ref<CodeTableClaim[]>([])
const message = ref('')
const messageKind = ref('ok')

const runtimeLabel = computed(() =>
  runtimeMode.value === 'new_runtime' ? '新版部署' : '旧版应用回滚',
)

function flash(text: string, ok = true) {
  message.value = text
  messageKind.value = ok ? 'ok' : 'fail'
}

async function loadRuntime() {
  runtimeMode.value = (await codeTableApi.runtime()).runtime_mode
}

async function loadClaims() {
  claims.value = (await codeTableApi.claims()).items
}

async function claim() {
  blocked.value = null
  claimResult.value = null
  normalized.value = null
  const result = await codeTableApi.claim(datasetCode.value, batchNo.value)
  if (result.blocked) {
    blocked.value = result
    flash(result.message, false)
  } else if (result.ok) {
    claimResult.value = result
    flash(result.message, true)
  } else {
    flash(result.message, false)
  }
  await loadClaims()
  await loadRuntime()
}

async function normalizeValue() {
  const result = await codeTableApi.normalize(batchNo.value, rawValue.value)
  if (!result.ok || result.blocked) {
    flash(result.message ?? '归一化失败', false)
    return
  }
  normalized.value = {
    raw: result.raw ?? '',
    normalized: result.normalized ?? '',
    mapped: Boolean(result.mapped),
    version_no: result.version_no ?? '',
  }
}

async function recompute() {
  recomputeResult.value = await codeTableApi.recompute(historyBatch.value)
  if (!recomputeResult.value.ok) {
    flash(recomputeResult.value.message ?? '复算失败', false)
  }
}

onMounted(async () => {
  await Promise.all([loadRuntime(), loadClaims()])
})
</script>

<style scoped>
.cleanse-panel {
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 14px 16px;
  margin: 16px 0;
}
.panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.runtime-tag {
  font-size: 13px;
  color: var(--muted);
}
.claim-box,
.normalize-box,
.detail-box,
.history-box,
.block-box {
  border: 1px dashed var(--border);
  border-radius: 8px;
  padding: 12px;
  margin: 12px 0;
  background: #fafbfc;
}
.claim-box,
.normalize-box {
  display: flex;
  gap: 12px;
  align-items: flex-end;
  flex-wrap: wrap;
}
.claim-box .create-field,
.normalize-box .create-field {
  flex: 1;
  min-width: 200px;
}
.block-box {
  border-color: #fda29b;
  background: #fef3f2;
}
.block-box h4 {
  margin: 0 0 6px;
  color: #b42318;
}
.panel-msg {
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 13px;
}
.panel-msg.ok {
  background: #ecfdf3;
  color: #027a48;
}
.panel-msg.fail {
  background: #fef3f2;
  color: #b42318;
}
.hint {
  font-size: 13px;
  color: var(--muted);
}
code {
  background: #f2f4f7;
  padding: 1px 4px;
  border-radius: 4px;
}
h5 {
  margin: 10px 0 6px;
}
</style>
