/**
 * GET /api/techpack/parts?gt=TOP&it=TOPS&dept=Active
 *
 * 回傳該 filter 組合下的所有 L1 部位卡片 + ISO 推薦。
 * 這是 Techpack Creation Step 1 頁面載入時唯一需要呼叫的 API。
 */

import partPresenceData from '@/data/l1_part_presence_v1.json'
import isoRecommendData from '@/data/l1_iso_recommendations_v1.json'
import { TechpackEngine } from '@/lib/techpack-engine'

const engine = new TechpackEngine(partPresenceData, isoRecommendData)

export default function handler(req, res) {
  const { gt, it, dept } = req.query

  if (!gt) {
    return res.status(400).json({ error: 'gt is required' })
  }

  const result = engine.getStep1Cards({
    gt,
    it: it || '',
    department: dept,
  })

  // 加上決策鏈說明，讓前端知道每個欄位怎麼用
  res.status(200).json({
    ...result,
    _usage: {
      'cards[].show': {
        always:     'UI 必開此卡片，不能關（≥80% 設計都有）',
        default_on: 'UI 預設開，用戶可關（50-79%）',
        expandable: 'UI 收合區，用戶點開才看到（20-49%）',
        manual_add: 'UI 不顯示，用戶手動 + 新增（<20%）',
      },
      'cards[].iso.action': {
        auto_recommend:            '綠色，AI 自動填 ISO，用戶可改（信心高）',
        recommend_with_alternatives: '黃色，推薦 ISO + 下拉備選（信心中）',
        user_select:               '灰色，列出選項讓用戶選（信心低或無資料）',
      },
      decision_chain: [
        'Step 1: Filter (GT×IT) → 決定顯示哪些 L1 部位',
        'Step 2: 每個 L1 → 推薦 ISO 縫法（含信心度）',
        'Step 3: 用戶確認/修改 L1 + ISO 組合',
        'Step 4: L1+ISO → 查 Glossary → 得到 L3 形狀',
        'Step 5: L3 → L4 工法（一對一直帶；非一對一 IE 選）',
        'Step 6: L4 + Knit/Woven → L5 秒值（全自動）',
      ],
    },
  })
}
