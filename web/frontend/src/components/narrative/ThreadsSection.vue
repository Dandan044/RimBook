<template>
  <div class="tab-card">
    <div class="tab-toolbar">
      <el-radio-group v-model="threadFilter" size="small">
        <el-radio-button value="open">未回收</el-radio-button>
        <el-radio-button value="all">全部</el-radio-button>
      </el-radio-group>
      <el-button size="small" @click="fetchThreads" :loading="loading">
        <el-icon><Refresh /></el-icon> 刷新
      </el-button>
    </div>
    <el-table :data="visibleThreads" v-loading="loading" empty-text="暂无线索（写作时自动抽取，或在设置中开启 track_threads）">
      <el-table-column label="类型" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="threadTypeTag(row.type)">{{ threadTypeLabel(row.type) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" min-width="240" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag size="small" :type="threadStatusTag(row.status)" effect="plain">{{ threadStatusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="埋设" width="70" align="center">
        <template #default="{ row }">第{{ row.planted_chapter }}章</template>
      </el-table-column>
      <el-table-column label="预期回收" width="90" align="center">
        <template #default="{ row }">
          <span v-if="row.expected_resolve_chapter">第{{ row.expected_resolve_chapter }}章</span>
          <span v-else class="dim-text">—</span>
        </template>
      </el-table-column>
      <el-table-column label="回收于" width="80" align="center">
        <template #default="{ row }">
          <span v-if="row.resolved_chapter">第{{ row.resolved_chapter }}章</span>
          <span v-else class="dim-text">—</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" align="center">
        <template #default="{ row }">
          <el-button size="small" text type="primary" @click="openThreadEditor(row)">编辑</el-button>
          <el-popconfirm title="确定删除该线索？" @confirm="removeThread(row)">
            <template #reference>
              <el-button size="small" text type="danger">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
      <el-table-column type="expand">
        <template #default="{ row }">
          <div class="thread-updates">
            <div v-if="!row.updates.length" class="dim-text">暂无进展记录</div>
            <div v-for="(u, i) in row.updates" :key="i" class="thread-update-item">
              <el-tag size="small" effect="plain">第{{ u.chapter }}章</el-tag>
              <span>{{ u.note }}</span>
            </div>
          </div>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="threadDialog" title="编辑线索" width="520px">
      <el-form label-width="80px" v-if="threadForm">
        <el-form-item label="描述">
          <el-input v-model="threadForm.description" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="threadForm.type" style="width:200px">
            <el-option value="foreshadow" label="伏笔" />
            <el-option value="suspense" label="悬念" />
            <el-option value="promise" label="承诺" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="threadForm.status" style="width:200px">
            <el-option value="open" label="未回收" />
            <el-option value="progressed" label="推进中" />
            <el-option value="resolved" label="已回收" />
          </el-select>
        </el-form-item>
        <el-form-item label="预期回收">
          <el-input-number v-model="threadForm.expected_resolve_chapter" :min="1" controls-position="right" />
          <span class="dim-text" style="margin-left:8px">章（可留空）</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="threadDialog = false">取消</el-button>
        <el-button type="primary" @click="saveThread" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../../stores/project'
import { listThreads, updateThread, deleteThread, type PlotThread } from '../../api'
import './narrative.css'

const store = useProjectStore()
const loading = ref(false)
const saving = ref(false)
const threads = ref<PlotThread[]>([])
const threadFilter = ref<'open' | 'all'>('open')
const visibleThreads = computed(() =>
  threadFilter.value === 'all' ? threads.value : threads.value.filter(t => t.status !== 'resolved'))

const threadTypeLabel = (t: string) => ({ foreshadow: '伏笔', suspense: '悬念', promise: '承诺' } as Record<string, string>)[t] || t
const threadTypeTag = (t: string) => ({ foreshadow: 'warning', suspense: 'danger', promise: 'success' } as Record<string, string>)[t] || 'info'
const threadStatusLabel = (s: string) => ({ open: '未回收', progressed: '推进中', resolved: '已回收' } as Record<string, string>)[s] || s
const threadStatusTag = (s: string) => ({ open: 'warning', progressed: 'primary', resolved: 'success' } as Record<string, string>)[s] || 'info'

async function fetchThreads() {
  if (!store.currentId) return
  loading.value = true
  try { threads.value = (await listThreads(store.currentId)).threads }
  catch (e: any) { ElMessage.error(e?.response?.data?.detail || '加载线索失败') }
  finally { loading.value = false }
}

const threadDialog = ref(false)
const threadForm = ref<{ id: string; description: string; type: string; status: string; expected_resolve_chapter: number | null } | null>(null)

function openThreadEditor(row: PlotThread) {
  threadForm.value = {
    id: row.id, description: row.description, type: row.type,
    status: row.status, expected_resolve_chapter: row.expected_resolve_chapter,
  }
  threadDialog.value = true
}

async function saveThread() {
  if (!store.currentId || !threadForm.value) return
  saving.value = true
  try {
    const f = threadForm.value
    await updateThread(store.currentId, f.id, {
      description: f.description, type: f.type, status: f.status,
      expected_resolve_chapter: f.expected_resolve_chapter,
    })
    threadDialog.value = false
    ElMessage.success('线索已更新')
    await fetchThreads()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
  finally { saving.value = false }
}

async function removeThread(row: PlotThread) {
  if (!store.currentId) return
  try {
    await deleteThread(store.currentId, row.id)
    ElMessage.success('已删除')
    await fetchThreads()
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '删除失败') }
}

onMounted(fetchThreads)
</script>
