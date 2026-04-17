/**
 * Techpack Creation Step 1 — Construction 做工部位卡片頁
 *
 * 這是一個完整可運行的 React component 範例，
 * 展示 know-how 規則引擎如何驅動 UI。
 *
 * 決策鏈：
 * 1. User 選 Filter (Brand→Fabric→Gender→Dept→GT→IT)
 * 2. Engine 回傳 L1 部位列表 + 每個部位的 ISO 推薦
 * 3. UI 依信心度渲染：綠(自動)→黃(推薦+備選)→灰(人選)
 * 4. User 確認後 → L1+ISO → Glossary → L3
 * 5. L3→L4：一對一直帶，非一對一 IE 選
 * 6. L4 + Knit/Woven → L5 秒值（全自動）
 */

import { useState, useEffect, useMemo } from 'react'
import { TechpackEngine, ISO_REFERENCE, CONFIDENCE_COLORS } from '@/lib/techpack-engine'

// 直接 import JSON（Vercel build 時會打包，不需要 API call）
import partPresenceData from '@/data/l1_part_presence_v1.json'
import isoRecommendData from '@/data/l1_iso_recommendations_v1.json'

const engine = new TechpackEngine(partPresenceData, isoRecommendData)

export default function TechpackStep1() {
  // ── Filter State ──
  const [gt, setGT] = useState('')
  const [it, setIT] = useState('')

  // ── 規則引擎輸出 ──
  const [cards, setCards] = useState(null)

  // ── User 修改追蹤 ──
  const [userSelections, setUserSelections] = useState({})
  // key: l1, value: { iso: string, confirmed: boolean }

  // GT 選項
  const gtOptions = useMemo(() => engine.getAvailableGT(), [])

  // IT 選項（依 GT 動態變）
  const itOptions = useMemo(() => gt ? engine.getAvailableIT(gt) : [], [gt])

  // ── Filter 改變 → 重新計算 ──
  useEffect(() => {
    if (!gt) {
      setCards(null)
      return
    }
    const result = engine.getStep1Cards({ gt, it })
    setCards(result)
    // 重設 user selections
    setUserSelections({})
  }, [gt, it])

  // ── 分組顯示 ──
  const grouped = useMemo(() => {
    if (!cards) return null
    return {
      always:     cards.cards.filter(c => c.show === 'always'),
      defaultOn:  cards.cards.filter(c => c.show === 'default_on'),
      expandable: cards.cards.filter(c => c.show === 'expandable'),
      manualAdd:  cards.cards.filter(c => c.show === 'manual_add'),
    }
  }, [cards])

  // ── User 選 ISO ──
  const handleISOSelect = (l1, iso) => {
    setUserSelections(prev => ({
      ...prev,
      [l1]: { iso, confirmed: true },
    }))
  }

  // ── 取得某 L1 目前的 ISO（user override 或 engine 推薦）──
  const getCurrentISO = (card) => {
    if (userSelections[card.l1]?.confirmed) {
      return userSelections[card.l1].iso
    }
    if (card.iso.action === 'auto_recommend') {
      return card.iso.recommended_iso
    }
    return null // 需要 user 選
  }

  // ── 渲染 ──
  return (
    <div className="p-6 max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">Techpack Creation — Step 1: Construction</h1>

      {/* ── Filter Bar ── */}
      <div className="flex gap-4 mb-8 p-4 bg-gray-50 rounded-lg">
        <FilterSelect
          label="Garment Type"
          value={gt}
          options={gtOptions}
          onChange={v => { setGT(v); setIT('') }}
        />
        <FilterSelect
          label="Item Type"
          value={it}
          options={itOptions}
          onChange={setIT}
          disabled={!gt}
        />
        {cards && (
          <div className="ml-auto text-sm text-gray-500 self-end">
            基於 {cards.totalDesigns} 款歷史設計
            {cards.fallbackUsed && ` (fallback: ${cards.fallbackUsed})`}
          </div>
        )}
      </div>

      {/* ── Summary ── */}
      {cards && (
        <div className="flex gap-3 mb-6 text-sm">
          <span className="px-3 py-1 bg-green-100 rounded">
            ✅ AI 自動推薦 {cards.summary.auto_recommend} 個部位
          </span>
          <span className="px-3 py-1 bg-yellow-100 rounded">
            🟡 建議+備選 {cards.summary.recommend_with_alt} 個
          </span>
          <span className="px-3 py-1 bg-gray-100 rounded">
            ⚪ 需要選擇 {cards.summary.user_select} 個
          </span>
        </div>
      )}

      {/* ── Part Cards ── */}
      {grouped && (
        <>
          {/* 必備（always show） */}
          <Section title="必備部位" subtitle="≥80% 設計都有，已自動開啟">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {grouped.always.map(card => (
                <PartCard
                  key={card.l1}
                  card={card}
                  currentISO={getCurrentISO(card)}
                  onISOSelect={handleISOSelect}
                />
              ))}
            </div>
          </Section>

          {/* 常見（default on） */}
          {grouped.defaultOn.length > 0 && (
            <Section title="常見部位" subtitle="50-79%，可關閉">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {grouped.defaultOn.map(card => (
                  <PartCard
                    key={card.l1}
                    card={card}
                    currentISO={getCurrentISO(card)}
                    onISOSelect={handleISOSelect}
                  />
                ))}
              </div>
            </Section>
          )}

          {/* 偶爾（expandable） */}
          {grouped.expandable.length > 0 && (
            <ExpandableSection title="更多部位" count={grouped.expandable.length}>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {grouped.expandable.map(card => (
                  <PartCard
                    key={card.l1}
                    card={card}
                    currentISO={getCurrentISO(card)}
                    onISOSelect={handleISOSelect}
                  />
                ))}
              </div>
            </ExpandableSection>
          )}
        </>
      )}
    </div>
  )
}

// ============================================================
// Sub-components
// ============================================================

function FilterSelect({ label, value, options, onChange, disabled }) {
  return (
    <div>
      <label className="block text-xs text-gray-500 mb-1">{label}</label>
      <select
        className="border rounded px-3 py-2 min-w-[140px]"
        value={value}
        onChange={e => onChange(e.target.value)}
        disabled={disabled}
      >
        <option value="">— 選擇 —</option>
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  )
}

function Section({ title, subtitle, children }) {
  return (
    <div className="mb-8">
      <h2 className="text-lg font-semibold mb-1">{title}</h2>
      {subtitle && <p className="text-sm text-gray-500 mb-3">{subtitle}</p>}
      {children}
    </div>
  )
}

function ExpandableSection({ title, count, children }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="mb-8">
      <button
        className="text-lg font-semibold text-blue-600 hover:underline"
        onClick={() => setOpen(!open)}
      >
        {open ? '▼' : '▶'} {title} ({count})
      </button>
      {open && <div className="mt-3">{children}</div>}
    </div>
  )
}

/**
 * 單張部位卡片 — 這是核心 UI 元件
 *
 * 呈現：
 * - L1 部位名稱 + code
 * - 出現率 %
 * - ISO 推薦（依信心度用不同顏色）
 * - ISO 備選下拉
 */
function PartCard({ card, currentISO, onISOSelect }) {
  const colors = CONFIDENCE_COLORS[card.iso.confidence] || CONFIDENCE_COLORS.none
  const isoInfo = currentISO ? ISO_REFERENCE[currentISO] : null

  return (
    <div
      className="border rounded-lg p-4 shadow-sm"
      style={{ borderLeftWidth: 4, borderLeftColor: colors.border }}
    >
      {/* Header */}
      <div className="flex justify-between items-start mb-2">
        <div>
          <span className="text-lg font-bold">{card.l1}</span>
          <span className="ml-2 text-xs text-gray-400 font-mono">{card.l1_code}</span>
        </div>
        <span className="text-xs px-2 py-0.5 rounded" style={{ background: colors.bg }}>
          {card.presence_pct}%
        </span>
      </div>

      {/* ISO 推薦 */}
      <div className="mt-2 p-2 rounded" style={{ background: colors.bg }}>
        <div className="text-xs text-gray-500 mb-1">{colors.label}</div>

        {card.iso.action === 'auto_recommend' && isoInfo ? (
          // ✅ 高信心：直接顯示推薦，可改
          <div className="flex items-center gap-2">
            <span className="font-mono font-bold">{currentISO}</span>
            <span className="text-sm">{isoInfo.zh}</span>
            <span className="text-xs text-gray-400">({card.iso.recommended_iso_pct}%)</span>
          </div>
        ) : (
          // 🟡 / ⚪：下拉選單
          <select
            className="w-full border rounded px-2 py-1 text-sm"
            value={currentISO || ''}
            onChange={e => onISOSelect(card.l1, e.target.value)}
          >
            <option value="">— 選擇縫法 —</option>
            {(card.iso.options || []).map(opt => (
              <option key={opt.iso} value={opt.iso}>
                {opt.iso} {opt.zh} ({opt.percentage}%)
              </option>
            ))}
          </select>
        )}
      </div>

      {/* 快速切換（高信心也可以改） */}
      {card.iso.action === 'auto_recommend' && card.iso.options?.length > 1 && (
        <details className="mt-2 text-xs">
          <summary className="cursor-pointer text-gray-400">其他選項</summary>
          <div className="mt-1 space-y-1">
            {card.iso.options.slice(1).map(opt => (
              <button
                key={opt.iso}
                className="block w-full text-left px-2 py-1 hover:bg-gray-50 rounded"
                onClick={() => onISOSelect(card.l1, opt.iso)}
              >
                {opt.iso} {opt.zh} ({opt.percentage}%)
              </button>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}
