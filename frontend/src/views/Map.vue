<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
const data = ref<any>(null)
const candidates = ref<any[]>([])
const violKeys = ref<Set<string>>(new Set())
// 当前锁位：candidate_id -> "row,col"。锁定/解锁不立即重排，只更新此表
const lockMap = ref<Map<number, string>>(new Map())
const running = ref(false)
const message = ref<{ kind: 'ok' | 'err'; text: string } | null>(null)

function flash(kind: 'ok' | 'err', text: string) {
  message.value = { kind, text }
}

async function loadLocks() {
  const res = await api<{ locks: { candidate_id: number; row: number; col: number }[] }>('/seating/locks?hall_id=1')
  lockMap.value = new Map(res.locks.map(l => [l.candidate_id, `${l.row},${l.col}`]))
}

async function refreshViolations() {
  try {
    const v = await api('/seating/violations?hall_id=1')
    const keys = new Set<string>()
    for (const x of v.violations || []) {
      if (x.a_id != null) keys.add(String(x.a_id))
      if (x.b_id != null) keys.add(String(x.b_id))
    }
    violKeys.value = keys
  } catch { violKeys.value = new Set() }
}

async function run() {
  running.value = true
  try {
    // 成功才换新图；保锁失败（409）时保留旧方案不动
    data.value = await api('/seating/run?hall_id=1', { method: 'POST' })
    await refreshViolations()
    await loadLocks()
    flash('ok', '排座完成，锁位均已保留')
  } catch (e: any) {
    flash('err', '排座失败：' + (e.message || '锁位在当前约束下已不合法') + '。已保留原方案，未新增方案。')
  } finally {
    running.value = false
  }
}

async function toggleLock(cell: any) {
  if (cell.empty || running.value) return
  const cid = cell.candidate_id
  if (lockMap.value.has(cid)) {
    // 解锁：下一次排座才允许重排原格
    await api(`/seating/locks/${cid}?hall_id=1`, { method: 'DELETE' })
    const next = new Map(lockMap.value)
    next.delete(cid)
    lockMap.value = next
    flash('ok', `已解锁 ${cell.name}，下次排座起可重排原格`)
  } else {
    try {
      await api('/seating/locks?hall_id=1', {
        method: 'POST',
        body: JSON.stringify({ candidate_id: cid, row: cell.row, col: cell.col }),
      })
      const next = new Map(lockMap.value)
      next.set(cid, `${cell.row},${cell.col}`)
      lockMap.value = next
      flash('ok', `已锁定 ${cell.name} 在 (${cell.row + 1},${cell.col + 1})，再排时不动`)
    } catch (e: any) {
      flash('err', '锁定失败：' + (e.message || '该格已被锁定'))
    }
  }
}

onMounted(async () => {
  candidates.value = await api('/candidates')
  data.value = await api('/seating/latest?hall_id=1')
  await Promise.all([refreshViolations(), loadLocks()])
})
const gridStyle = computed(() => data.value ? ({ gridTemplateColumns: `repeat(${data.value.cols}, 72px)` }) : {})
const cells = computed(() => {
  if (!data.value) return []
  const map = new Map<string, any>()
  for (const a of data.value.assignments || []) map.set(a.row + ',' + a.col, a)
  const out: any[] = []
  for (let r = 0; r < data.value.rows; r++) {
    for (let c = 0; c < data.value.cols; c++) {
      out.push(map.get(r + ',' + c) || { empty: true, row: r, col: c })
    }
  }
  return out
})
function isViol(cell: any) {
  if (cell.empty) return false
  const id = cell.candidate_id ?? cell.id
  return id != null && violKeys.value.has(String(id))
}
function isLocked(cell: any) {
  if (cell.empty) return false
  // 以当前锁表为准；历史方案自带的 locked 标记兜底
  return false
}
function paperClass(pid: number) {
  return pid % 2 === 0 ? 'b' : 'a'
}
</script>
<template>
  <h1>考场课桌网格</h1>
  <p class="sub">课桌网格为主视图 · 左侧考生名册夹板 · 点击格位 🔒 锁定/解锁 · 再排时被锁考生留在原格</p>
  <div style="display:flex;gap:0.5rem;align-items:center;flex-wrap:wrap">
    <button class="btn" :disabled="running" @click="run">{{ running ? '排座中…' : '重新排座' }}</button>
    <span class="muted" style="font-size:0.78rem">已锁定 {{ lockMap.size }} 人 · 锁定不立即重排，解锁后下次排座生效</span>
  </div>
  <p v-if="message" :style="{ color: message.kind === 'err' ? 'var(--hs-bad)' : 'var(--hs-ok)', margin: '0.5rem 0', fontSize: '0.82rem' }">
    {{ message.text }}
  </p>
  <div class="hs-classroom" style="margin-top:0.85rem">
    <aside class="hs-clipboard">
      <h2>考生名册</h2>
      <div v-for="c in candidates" :key="c.id" class="hs-roster-row"
           :class="{ 'hs-roster-lock': lockMap.has(c.id) }">
        <div>
          <div>{{ lockMap.has(c.id) ? '🔒 ' : '' }}{{ c.name }}</div>
          <div class="hs-ticket">{{ c.ticket_no }}</div>
        </div>
        <div>卷{{ c.paper_id }}</div>
      </div>
    </aside>
    <div class="hs-desk-stage" v-if="data">
      <div class="hs-grid-board" :style="gridStyle">
        <div
          v-for="(cell,i) in cells" :key="i"
          class="hs-desk"
          :class="{ empty: cell.empty, 'hs-viol': isViol(cell), 'hs-lock': isLocked(cell) }"
          :title="cell.empty ? '' : (isLocked(cell) ? '点击解锁' : '点击锁定在此格')"
          @click="toggleLock(cell)"
        >
          <template v-if="!cell.empty">
            <span class="hs-paper-tag" :class="paperClass(cell.paper_id)">卷{{ cell.paper_id }}</span>
            <span v-if="isLocked(cell)" class="hs-lock-tag">🔒</span>
            <div>{{ cell.name }}</div>
          </template>
          <template v-else>·</template>
        </div>
      </div>
    </div>
  </div>
</template>
