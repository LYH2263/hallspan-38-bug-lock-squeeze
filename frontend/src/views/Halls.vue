<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
const rows = ref<any[]>([])
const drafts = ref<Record<number, number>>({})
const saving = ref<number | null>(null)
const tip = ref<{ id: number; kind: 'ok' | 'err'; text: string } | null>(null)

onMounted(load)
async function load() {
  rows.value = await api('/halls')
  drafts.value = Object.fromEntries(rows.value.map(r => [r.id, r.min_manhattan]))
}
async function save(r: any) {
  const v = Number(drafts.value[r.id])
  if (!Number.isInteger(v) || v < 1) {
    tip.value = { id: r.id, kind: 'err', text: '最小间距必须为 >=1 的整数' }
    return
  }
  saving.value = r.id
  try {
    const updated = await api(`/halls/${r.id}`, { method: 'PUT', body: JSON.stringify({ min_manhattan: v }) })
    const idx = rows.value.findIndex(x => x.id === r.id)
    if (idx >= 0) rows.value[idx] = updated
    tip.value = { id: r.id, kind: 'ok', text: '已保存；若锁位在新间距下违法，下次排座将整场失败' }
  } catch (e: any) {
    tip.value = { id: r.id, kind: 'err', text: '保存失败：' + (e.message || '') }
  } finally {
    saving.value = null
  }
}
</script>
<template>
  <h1>考室</h1>
  <p class="sub">考室网格与最小曼哈顿间距 · 调大间距后请到「排座图」重新排座验证锁位</p>
  <div class="card">
    <table>
      <thead><tr><th>编码</th><th>名称</th><th>行</th><th>列</th><th>最小间距</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id ?? JSON.stringify(r)">
          <td>{{ r.code }}</td><td>{{ r.name }}</td><td>{{ r.rows }}</td><td>{{ r.cols }}</td>
          <td>
            <input v-model.number="drafts[r.id]" type="number" min="1" style="width:5rem"
                   :aria-label="'最小间距 ' + r.code" />
          </td>
          <td>
            <button class="btn" :disabled="saving === r.id || drafts[r.id] === r.min_manhattan" @click="save(r)">
              {{ saving === r.id ? '保存中…' : '保存' }}
            </button>
          </td>
        </tr>
      </tbody>
    </table>
    <p v-if="tip" :style="{ color: tip.kind === 'err' ? 'var(--hs-bad)' : 'var(--hs-ok)', marginBottom: 0 }">
      {{ tip.text }}
    </p>
  </div>
</template>
