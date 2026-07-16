<template>
  <div class="tab-card">
    <div class="tab-toolbar">
      <span class="toolbar-hint">写作与修订时自动注入到提示词最前部</span>
      <div class="toolbar-actions">
        <el-button size="small" @click="doGenerateStyle" :loading="generating">
          <el-icon><MagicStick /></el-icon> 从已写章节反推
        </el-button>
        <el-button size="small" type="primary" @click="saveStyle" :loading="saving">
          <el-icon><Check /></el-icon> 保存
        </el-button>
      </div>
    </div>
    <el-input
      v-model="styleText" type="textarea" :rows="22" class="style-input"
      placeholder="风格圣经：叙事视角、语言风格、禁用词、对白习惯等。留空则不注入。"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { useProjectStore } from '../../stores/project'
import { getStyle, updateStyle, generateStyle } from '../../api'
import './narrative.css'

const store = useProjectStore()
const styleText = ref('')
const generating = ref(false)
const saving = ref(false)

async function fetchStyle() {
  if (!store.currentId) return
  try { styleText.value = (await getStyle(store.currentId)).text } catch {}
}

async function saveStyle() {
  if (!store.currentId) return
  saving.value = true
  try {
    await updateStyle(store.currentId, styleText.value)
    ElMessage.success('风格指南已保存')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '保存失败') }
  finally { saving.value = false }
}

async function doGenerateStyle() {
  if (!store.currentId) return
  generating.value = true
  try {
    const r = await generateStyle(store.currentId)
    styleText.value = r.text
    ElMessage.success('已根据近期章节反推风格指南（已自动保存，可继续修改）')
  } catch (e: any) { ElMessage.error(e?.response?.data?.detail || '生成失败') }
  finally { generating.value = false }
}

onMounted(fetchStyle)
</script>

<style scoped>
.style-input :deep(textarea) {
  font-size: 14px;
  line-height: 1.8;
  font-family: var(--rb-font);
}
</style>
