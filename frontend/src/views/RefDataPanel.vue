<template>
  <section class="code-panel" data-testid="code-table-panel">
    <header class="panel-head">
      <h3>码表版本化（JSON 条目格式）</h3>
      <div class="runtime-box" data-testid="runtime-box">
        <span>运行时：<strong :data-testid="'runtime-mode'">{{ runtimeLabel }}</strong></span>
        <button
          class="btn"
          type="button"
          data-testid="switch-new"
          :disabled="runtimeMode === 'new_runtime'"
          @click="switchMode('new_runtime')"
        >
          模拟新版部署
        </button>
        <button
          class="btn"
          type="button"
          data-testid="switch-legacy"
          :disabled="runtimeMode === 'legacy_runtime'"
          @click="switchMode('legacy_runtime')"
        >
          模拟旧版回滚
        </button>
      </div>
    </header>

    <p v-if="message" class="panel-msg" :class="messageKind" data-testid="panel-message">{{ message }}</p>

    <!-- 登记区：普通值与特殊字符（A=B、逗号）都可提交 -->
    <form class="register-box" @submit.prevent="submitRegister">
      <h4>登记码表（新版 JSON 条目 / 旧版逗号等号文本）</h4>
      <div class="form-grid">
        <label class="create-field">
          <span>数据集编码</span>
          <input v-model="form.dataset_code" data-testid="reg-code" required placeholder="如 REF-NEW-01" />
        </label>
        <label class="create-field">
          <span>数据集名称</span>
          <input v-model="form.dataset_name" data-testid="reg-name" required />
        </label>
        <label class="create-field">
          <span>条目格式</span>
          <select v-model="form.entry_format" data-testid="reg-format">
            <option value="json_entries">JSON 条目（支持 A=B 等特殊字符）</option>
            <option value="legacy_csv">旧版 码=值,码=值（自动迁移+坏行拒收）</option>
          </select>
        </label>
      </div>
      <label class="create-field">
        <span>码值条目原文</span>
        <textarea
          v-model="form.entry_text"
          data-testid="reg-entries"
          rows="6"
          required
          placeholder='JSON: [{"code":"A=B","value":"完整业务值"}] 或旧版: CN=中国,US=美国'
        ></textarea>
      </label>
      <div class="page-actions">
        <button class="btn primary" type="submit" data-testid="reg-submit" :disabled="submitting">
          {{ submitting ? '提交中…' : '提交登记' }}
        </button>
        <button class="btn ghost" type="button" data-testid="reg-sample" @click="fillSample">
          填入特殊值样例
        </button>
      </div>
    </form>

    <!-- 数据集与迁移报告 -->
    <h4>码表登记与迁移报告</h4>
    <table class="data-table" data-testid="dataset-table">
      <thead>
        <tr>
          <th>数据集编码</th>
          <th>名称</th>
          <th>来源格式</th>
          <th>有效条目</th>
          <th>拒收坏行</th>
          <th>状态</th>
          <th>当前版次</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="item in datasets" :key="item.id" :data-testid="`ds-${item.数据集编码}`">
          <td>{{ item.数据集编码 }}</td>
          <td>{{ item.数据集名称 }}</td>
          <td>{{ item.entry_format }}</td>
          <td>{{ item.entry_count }}</td>
          <td>
            <button
              class="link"
              type="button"
              :data-testid="`reject-${item.数据集编码}`"
              @click="toggleRejections(item)"
            >
              {{ item.rejected_count }} 条
            </button>
          </td>
          <td>{{ item.status }}</td>
          <td>{{ item.current_version ?? '—' }}</td>
          <td class="row-actions">
            <button
              class="link"
              type="button"
              :data-testid="`publish-${item.数据集编码}`"
              @click="publish(item.数据集编码)"
            >
              发布新版本
            </button>
            <button
              class="link"
              type="button"
              :data-testid="`versions-${item.数据集编码}`"
              @click="loadVersions(item.数据集编码)"
            >
              版本/回滚
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 坏行明细：保留原文与原因，可单独排查 -->
    <div v-if="rejectionDetail" class="detail-box" data-testid="rejection-detail">
      <h4>
        迁移拒收明细 {{ rejectionDetail.dataset_code }}
        <button class="link" type="button" @click="rejectionDetail = null">关闭</button>
      </h4>
      <p class="panel-msg">已转换 {{ rejectionDetail.converted }} 条，拒收 {{ rejectionDetail.rejected.length }} 条（原文完整保留）</p>
      <table class="data-table">
        <thead>
          <tr><th>原文位置</th><th>坏行原文</th><th>拒收原因</th></tr>
        </thead>
        <tbody>
          <tr v-for="line in rejectionDetail.rejected" :key="line.index">
            <td>#{{ line.index }}</td>
            <td><code>{{ line.raw }}</code></td>
            <td>{{ line.reason }}</td>
          </tr>
          <tr v-if="!rejectionDetail.rejected.length">
            <td colspan="3" class="empty-state">该版本无拒收条目</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 版本列表与回滚 -->
    <div v-if="versionDetail.length" class="detail-box" data-testid="version-detail">
      <h4>
        发布版本 {{ versionDataset }}（历史版本原编号保留，可供旧批次复算）
        <button class="link" type="button" @click="versionDetail = []">关闭</button>
      </h4>
      <table class="data-table">
        <thead>
          <tr>
            <th>版次</th><th>状态</th><th>条目数</th><th>旧结构兼容</th>
            <th>来源格式</th><th>发布时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ver in versionDetail" :key="ver.id" :data-testid="`ver-${ver.version_no}`">
            <td>{{ ver.version_no }}</td>
            <td>{{ ver.status }}</td>
            <td>{{ ver.entry_count }}</td>
            <td>{{ ver.legacy_compatible ? '兼容' : '含特殊字符·不可回退旧结构' }}</td>
            <td>{{ ver.source_format }}</td>
            <td>{{ ver.published_at }}</td>
            <td class="row-actions">
              <button
                v-if="ver.status !== '生效中'"
                class="link"
                type="button"
                :data-testid="`rollback-${ver.version_no}`"
                @click="rollback(ver.version_no)"
              >
                回滚到此版
              </button>
              <button class="link" type="button" @click="showVersionRejections(ver)">查拒收</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { codeTableApi, type CodeTableDataset, type CodeTableVersion, type RejectedLine } from '@/api/code-table'

const runtimeMode = ref('new_runtime')
const datasets = ref<CodeTableDataset[]>([])
const versionDetail = ref<CodeTableVersion[]>([])
const versionDataset = ref('')
const rejectionDetail = ref<{
  dataset_code: string
  converted: number
  rejected: RejectedLine[]
} | null>(null)
const message = ref('')
const messageKind = ref('ok')
const submitting = ref(false)

const form = ref({
  dataset_code: '',
  dataset_name: '',
  entry_format: 'json_entries',
  entry_text: '',
})

const runtimeLabel = computed(() =>
  runtimeMode.value === 'new_runtime' ? '新版部署（JSON 条目生效）' : '旧版应用回滚（仅旧结构兼容）',
)

function flash(text: string, ok = true) {
  message.value = text
  messageKind.value = ok ? 'ok' : 'fail'
}

async function loadRuntime() {
  const data = await codeTableApi.runtime()
  runtimeMode.value = data.runtime_mode
}

async function loadDatasets() {
  const data = await codeTableApi.datasets()
  datasets.value = data.items
}

async function switchMode(mode: string) {
  const reason = mode === 'legacy_runtime' ? '上线校验未结束，模拟部署回滚' : '模拟重新切回新版部署'
  const result = await codeTableApi.switchRuntime(mode, reason)
  flash(result.message, result.ok)
  await loadRuntime()
}

function fillSample() {
  form.value.dataset_code = form.value.dataset_code || 'REF-SPECIAL-01'
  form.value.dataset_name = form.value.dataset_name || '特殊字符码表'
  form.value.entry_format = 'json_entries'
  form.value.entry_text = JSON.stringify(
    [
      { code: 'PLAIN', value: '普通值' },
      { code: 'A=B', value: '公式型业务值 X=Y*2' },
      { code: 'K,M', value: '带逗号的码' },
    ],
    null,
    2,
  )
}

async function submitRegister() {
  submitting.value = true
  try {
    const result = await codeTableApi.register({ ...form.value })
    flash(result.message, result.ok)
    if (result.ok) {
      form.value = { dataset_code: '', dataset_name: '', entry_format: 'json_entries', entry_text: '' }
      await loadDatasets()
    }
  } finally {
    submitting.value = false
  }
}

async function publish(code: string) {
  const result = await codeTableApi.publish(code)
  flash(result.message, result.ok)
  await loadDatasets()
  if (versionDataset.value === code) await loadVersions(code)
}

async function loadVersions(code: string) {
  versionDataset.value = code
  const data = await codeTableApi.versions(code)
  versionDetail.value = data.items
}

async function rollback(versionNo: string) {
  const result = await codeTableApi.rollback(versionDataset.value, versionNo, '页面模拟回滚')
  flash(result.message, result.ok)
  await Promise.all([loadVersions(versionDataset.value), loadDatasets()])
}

async function toggleRejections(item: CodeTableDataset) {
  const versionNo = item.current_version
  if (!versionNo) {
    // 草稿未发布：直接展示登记时的迁移报告
    rejectionDetail.value = {
      dataset_code: item.数据集编码,
      converted: item.migration_report.converted,
      rejected: item.migration_report.rejected,
    }
    return
  }
  await showVersionRejections({
    dataset_code: item.数据集编码,
    version_no: versionNo,
  } as CodeTableVersion)
}

async function showVersionRejections(ver: { dataset_code: string; version_no: string }) {
  const data = await codeTableApi.rejections(ver.dataset_code, ver.version_no)
  if (!data.ok) {
    flash('拒收条目查询失败', false)
    return
  }
  rejectionDetail.value = {
    dataset_code: `${ver.dataset_code}@${ver.version_no}`,
    converted: data.converted,
    rejected: data.rejected,
  }
}

onMounted(async () => {
  await Promise.all([loadRuntime(), loadDatasets()])
})
</script>

<style scoped>
.code-panel {
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
.runtime-box {
  display: flex;
  gap: 8px;
  align-items: center;
  font-size: 13px;
}
.register-box,
.detail-box {
  border: 1px dashed var(--border);
  border-radius: 8px;
  padding: 12px;
  margin: 12px 0;
  background: #fafbfc;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
textarea,
select {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px;
  font-family: inherit;
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
code {
  background: #f2f4f7;
  padding: 1px 4px;
  border-radius: 4px;
}
</style>
