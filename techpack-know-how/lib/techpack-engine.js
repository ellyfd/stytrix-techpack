/**
 * Techpack Creation — Know-How 規則引擎
 *
 * 純函式，不依賴 React。可在前端 component 直接 import，
 * 也可在 Vercel API route 中使用。
 *
 * 使用方式：
 *   import { TechpackEngine } from '@/lib/techpack-engine'
 *   const engine = new TechpackEngine(partPresenceData, isoRecommendData)
 *   const result = engine.getPartsForFilter({ gt: 'TOP', it: 'TOPS' })
 */

// ============================================================
// 核心類別
// ============================================================

export class TechpackEngine {
  /**
   * @param {object} partPresence  - l1_part_presence_v1.json 的內容
   * @param {object} isoRecommend  - l1_iso_recommendations_v1.json 的內容
   */
  constructor(partPresence, isoRecommend) {
    this.partPresence = partPresence
    this.isoRecommend = isoRecommend
  }

  // ----------------------------------------------------------
  // Step 1-A: 給定 filter → 回傳該顯示哪些 L1 部位
  // ----------------------------------------------------------
  /**
   * @param {object} filter - { gt, it, department? }
   * @returns {object} { parts: [...], totalDesigns, fallbackUsed }
   *
   * 每個 part: {
   *   l1, l1_code, presence_pct, tier, tier_en,
   *   show: 'always' | 'default_on' | 'expandable' | 'manual_add'
   * }
   */
  getPartsForFilter({ gt, it, department }) {
    const key = `${gt}|${it}`
    let data = this.partPresence.by_gt_it?.[key]
    let fallbackUsed = null

    // Fallback 1: 試 GT×IT×Dept
    if (!data && department) {
      const deptKey = `${gt}|${it}|${department}`
      data = this.partPresence.by_gt_it_dept?.[deptKey]
      if (data) fallbackUsed = 'gt_it_dept'
    }

    // Fallback 2: 只用 GT
    if (!data) {
      data = this.partPresence.by_gt?.[gt]
      fallbackUsed = 'gt_only'
    }

    if (!data) {
      return { parts: [], totalDesigns: 0, fallbackUsed: 'no_data' }
    }

    const parts = data.parts.map(p => ({
      ...p,
      show: this._presenceTierToShow(p.tier_en),
    }))

    return {
      parts,
      totalDesigns: data.total_designs,
      fallbackUsed,
    }
  }

  // ----------------------------------------------------------
  // Step 1-B: 給定 filter + L1 → 回傳 ISO 推薦
  // ----------------------------------------------------------
  /**
   * @param {object} params - { gt, it, l1 }
   * @returns {object} {
   *   recommended_iso, recommended_iso_pct, confidence, action,
   *   options: [{ iso, en, zh, percentage }],
   *   fallbackUsed
   * }
   */
  getISORecommendation({ gt, it, l1 }) {
    const key = `${gt}|${it}`
    let rec = this.isoRecommend.by_gt_it?.[key]
    let fallbackUsed = null

    // Fallback: GT level
    if (!rec) {
      rec = this.isoRecommend.by_gt?.[gt]
      fallbackUsed = 'gt_only'
    }

    if (!rec) {
      return {
        recommended_iso: null,
        confidence: 'none',
        action: 'user_select',
        options: [],
        fallbackUsed: 'no_data',
      }
    }

    // 找到對應的 L1 part
    const part = rec.parts.find(p => p.l1 === l1)
    if (!part) {
      return {
        recommended_iso: null,
        confidence: 'none',
        action: 'user_select',
        options: [],
        fallbackUsed: fallbackUsed || 'l1_not_found',
      }
    }

    return {
      recommended_iso: part.recommended_iso,
      recommended_iso_pct: part.recommended_iso_pct,
      confidence: part.confidence,
      action: part.action,
      options: part.options,
      n_designs: part.n_designs,
      total_mentions: part.total_mentions,
      fallbackUsed,
    }
  }

  // ----------------------------------------------------------
  // Step 1-C: 組合呼叫 — 一次拿到完整 Step 1 資料
  // ----------------------------------------------------------
  /**
   * 給定 filter，回傳每個 L1 部位 + 其 ISO 推薦，
   * 這就是 UI 渲染一整頁卡片需要的全部資料。
   *
   * @param {object} filter - { gt, it, department? }
   * @returns {object} {
   *   filter, totalDesigns,
   *   cards: [{
   *     l1, l1_code, presence_pct, tier, show,
   *     iso: { recommended_iso, confidence, action, options }
   *   }]
   * }
   */
  getStep1Cards({ gt, it, department }) {
    const presence = this.getPartsForFilter({ gt, it, department })

    const cards = presence.parts.map(part => {
      const iso = this.getISORecommendation({ gt, it, l1: part.l1 })
      return {
        l1: part.l1,
        l1_code: part.l1_code,
        presence_pct: part.presence_pct,
        tier: part.tier,
        tier_en: part.tier_en,
        show: part.show,
        iso: {
          recommended_iso: iso.recommended_iso,
          recommended_iso_pct: iso.recommended_iso_pct,
          confidence: iso.confidence,
          action: iso.action,
          options: iso.options,
        },
      }
    })

    return {
      filter: { gt, it, department },
      totalDesigns: presence.totalDesigns,
      fallbackUsed: presence.fallbackUsed,
      cards,
      summary: {
        total: cards.length,
        auto_show: cards.filter(c => c.show === 'always' || c.show === 'default_on').length,
        auto_recommend: cards.filter(c => c.iso.action === 'auto_recommend').length,
        recommend_with_alt: cards.filter(c => c.iso.action === 'recommend_with_alternatives').length,
        user_select: cards.filter(c => c.iso.action === 'user_select').length,
      },
    }
  }

  // ----------------------------------------------------------
  // 可用的 filter 選項（給 UI 下拉選單）
  // ----------------------------------------------------------
  getAvailableGT() {
    return Object.keys(this.partPresence.by_gt || {}).sort()
  }

  getAvailableIT(gt) {
    const keys = Object.keys(this.partPresence.by_gt_it || {})
    return keys
      .filter(k => k.startsWith(`${gt}|`))
      .map(k => k.split('|')[1])
      .sort()
  }

  // ----------------------------------------------------------
  // Private helpers
  // ----------------------------------------------------------
  _presenceTierToShow(tierEn) {
    switch (tierEn) {
      case 'essential':  return 'always'        // ≥80% → 必開，不能關
      case 'common':     return 'default_on'    // 50-79% → 預設開，可關
      case 'occasional': return 'expandable'    // 20-49% → 收合區
      case 'rare':       return 'manual_add'    // <20% → 手動新增
      default:           return 'manual_add'
    }
  }
}

// ============================================================
// ISO 參考資料（靜態，不需要從 JSON 載入）
// ============================================================
export const ISO_REFERENCE = {
  '301': { en: 'Lockstitch',          zh: '平車',         icon: '━' },
  '304': { en: 'Zigzag',              zh: '曲折縫',       icon: '⌇' },
  '401': { en: 'Chainstitch',         zh: '鎖鍊',         icon: '⛓' },
  '406': { en: 'Coverstitch',         zh: '壓三本',       icon: '≡' },
  '407': { en: 'Coverstitch 3-needle', zh: '三本三針',    icon: '≡≡' },
  '504': { en: 'Safety Stitch',       zh: '安全縫',       icon: '⊞' },
  '512': { en: 'Mock Safety',         zh: '假安全縫',     icon: '⊟' },
  '514': { en: '4-thread Overlock',   zh: '四線拷克',     icon: '∿' },
  '514+401': { en: 'Overlock+Chain',  zh: '拷克+鏈縫',   icon: '∿⛓' },
  '514+605': { en: 'Overlock+Flatseam', zh: '拷克+爬網', icon: '∿≋' },
  '516': { en: '5-thread Overlock',   zh: '五線拷克',     icon: '∿∿' },
  '602': { en: 'Flatseam 2-needle',   zh: '併縫',         icon: '≋' },
  '605': { en: 'Flatseam Binding',    zh: '爬網',         icon: '≋≋' },
  '607': { en: 'Flatlock',            zh: '併縫車',       icon: '⋈' },
}

// ============================================================
// 信心等級 → UI 顏色映射
// ============================================================
export const CONFIDENCE_COLORS = {
  high:   { bg: '#E8F5E9', border: '#4CAF50', label: '✅ AI 推薦' },
  medium: { bg: '#FFF8E1', border: '#FFC107', label: '🟡 建議（可改）' },
  low:    { bg: '#F5F5F5', border: '#9E9E9E', label: '⚪ 請選擇' },
  none:   { bg: '#FAFAFA', border: '#E0E0E0', label: '— 無資料' },
}
