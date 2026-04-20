export const config = { runtime: "edge" };

const L1_CODES = {
  AE: "袖孔", AH: "袖圍", BM: "下襬", BN: "貼合", BP: "襬叉",
  BS: "釦鎖", DC: "繩類", DP: "裝飾片", FP: "袋蓋", FY: "前立",
  HD: "帽子", HL: "釦環", KH: "Keyhole", LB: "商標", LI: "裡布",
  LO: "褲口", LP: "帶絆", NK: "領", NP: "領襟", NT: "領貼條",
  OT: "其它", PD: "褶", PK: "口袋", PL: "門襟", PS: "褲合身",
  QT: "行縫(固定棉)", RS: "褲襠", SA: "剪接線_上身類", SB: "剪接線_下身類",
  SH: "肩", SL: "袖口", SP: "袖叉", SR: "裙合身", SS: "脅邊",
  ST: "肩帶", TH: "拇指洞", WB: "腰頭", ZP: "拉鍊"
};

export default async function handler(request) {
  if (request.method !== "POST") {
    return json({ error: "method not allowed" }, 405);
  }
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return json({ error: "Server missing ANTHROPIC_API_KEY env var" }, 500);

  let body;
  try { body = await request.json(); }
  catch { return json({ error: "invalid JSON body" }, 400); }

  const { image, brand, fabric, gender, garment_type, item_type, mode } = body;
  if (!image) return json({ error: "missing image" }, 400);
  // mode=universal → Path 2: 只跑 Pass 1 (L1)，前端走 iso_lookup_factory_v3 查表，不需 L2。
  const skipPass2 = mode === "universal";

  const m = image.match(/^data:image\/(\w+);base64,(.+)$/);
  const mediaType = m ? `image/${m[1]}` : "image/png";
  const b64 = m ? m[2] : image;

  // Load visual guide + decision trees once — both passes use them.
  // guide: L1 sketch_def (Pass 1) + L2 metadata (l2_name lookup).
  // trees: §0 common prompt + per-L1 decision tree (Pass 2).
  let guide = null, trees = null;
  try { guide = await loadGuide(request); }
  catch (e) { /* Pass 1 falls back to bare code=name list */ }
  try { trees = await loadTrees(request); }
  catch (e) { /* Pass 2 will hard-fail below if trees missing */ }

  // ── Pass 1: identify which of the 38 L1 parts are in the sketch ──
  const detected = await identifyL1(apiKey, mediaType, b64, { brand, fabric, gender, garment_type, item_type }, guide);
  if (detected.error) return json(detected, 502);

  // Path 2 通用模型只需要 L1 偵測結果即可；省掉 Pass 2 的 decision-tree 推論。
  if (skipPass2) {
    return json({ detected: detected.list, usage_l1: detected.usage, model: CLAUDE_MODEL, mode: "universal" });
  }

  // ── Pass 2: for each detected L1, walk the decision tree to identify L2.
  //    Output may mark needs_text=true with merged_candidates for L2s that
  //    the VLM cannot distinguish from the sketch alone (hard-negative pairs). ──
  const l2Map = await identifyL2(apiKey, mediaType, b64, detected.list, guide, trees);
  if (l2Map.error) {
    // Soft-fail: L2 couldn't be identified but L1 detection is still useful.
    return json({ detected: detected.list, l2_error: l2Map.error, usage: detected.usage });
  }

  const merged = detected.list.map(d => {
    const l2info = l2Map.byCode[d.code];
    if (!l2info) return d;
    return {
      ...d,
      l2_code: l2info.l2_code || null,
      l2_name: l2info.l2_name || null,
      l2_confidence: l2info.confidence ?? null,
      l2_explanation: l2info.explanation || null,
      l2_needs_text: !!l2info.needs_text,
      l2_merged_candidates: l2info.merged_candidates || [],
      l2_alternatives: l2info.alternatives || []
    };
  });
  return json({
    detected: merged,
    usage_l1: detected.usage,
    usage_l2: l2Map.usage,
    model: CLAUDE_MODEL,
  });
}

async function identifyL1(apiKey, mediaType, b64, ctxObj, guide) {
  // Each L1 line: "  CODE = 中文名 — sketch 視覺定義（含 ↔ 兄弟對比）"
  // sketch_def 來自 L1_部位定義_Sketch視覺指引.md，給 VLM 做兄弟消歧用
  // （AE/AH、BM/LO/BP、PL/FY/ZP 等位置/語意接近的組合最受益）。
  const partList = Object.entries(L1_CODES).map(([k, v]) => {
    const def = guide?.l1?.[k]?.sketch_def || "";
    return def ? `  ${k} = ${v} — ${def}` : `  ${k} = ${v}`;
  }).join("\n");
  const ctx = [
    ctxObj.brand && `Brand: ${ctxObj.brand}`,
    ctxObj.fabric && `Fabric: ${ctxObj.fabric}`,
    ctxObj.gender && `Gender: ${ctxObj.gender}`,
    ctxObj.garment_type && `Garment Type: ${ctxObj.garment_type}`,
    ctxObj.item_type && `Item Type: ${ctxObj.item_type}`
  ].filter(Boolean).join("\n");

  // System block: stable across every call (same 38 L1 list + sketch defs).
  // Gets cache_control=ephemeral so repeat calls hit prompt cache.
  const system = `You are a garment manufacturing expert. Analyze a clothing sketch and identify which of the 38 construction parts are visible in the drawing.

Each entry below is "code = 中文名 — sketch visual definition with sibling contrasts (↔ marks comparisons against sibling L1s you must distinguish from)". Use the sketch definition to ground your judgment in what the artist actually drew, and use the ↔ contrasts to break ties between siblings (e.g. AE 無袖開口 vs AH 有袖接合線; BM 上衣底邊 vs LO 褲腳 vs BP 側邊開叉).

Part codes:
${partList}

Rules:
- code: one of the 38 codes above (exact).
- side: "front" or "back" based on which view the part is visible in.
- x, y: approximate position on the whole sketch as percentages 0-100 (x from left, y from top).
- confidence: 0-100, your certainty that this part is actually in the sketch.
- Include every part you can clearly see. Do NOT guess parts that are not drawn.
- For parts marked "幾乎不可見" / "通常不可見" (BN, NT, LI, etc.), only include if a callout/text annotation in the sketch explicitly mentions them.
- If the sketch shows both front and back views side-by-side, x for a back part should be in the right half.`;

  // User block: per-call (context + return-format reminder).
  const userText = `${ctx ? "Context:\n" + ctx + "\n\n" : ""}Return ONLY valid JSON (no markdown fences, no prose) in this exact shape:
{"detected":[{"code":"WB","side":"front","x":50,"y":10,"confidence":92}]}`;

  const data = await callClaude(apiKey, mediaType, b64, { system, userText }, 2000);
  if (data.error) return { error: data.error, detail: data.detail };

  const parsed = parseJson(data.text);
  if (!parsed) return { error: "non-JSON response from Claude (L1)", raw: data.text };
  const list = (parsed.detected || []).filter(d => d && L1_CODES[d.code]);
  return { list, usage: data.usage };
}

let _guideCache = null;
async function loadGuide(request) {
  if (_guideCache) return _guideCache;
  const res = await fetch(new URL("/data/l2_visual_guide.json", request.url));
  if (!res.ok) throw new Error(`L2 guide fetch ${res.status}`);
  _guideCache = await res.json();
  return _guideCache;
}

let _treesCache = null;
async function loadTrees(request) {
  if (_treesCache) return _treesCache;
  const res = await fetch(new URL("/data/l2_decision_trees.json", request.url));
  if (!res.ok) throw new Error(`L2 decision trees fetch ${res.status}`);
  _treesCache = await res.json();
  return _treesCache;
}

// Accept 0-100 integer OR 0.0-1.0 float; normalize to 0-100 clamped integer.
function clampConfidence(raw) {
  const n = Number(raw);
  if (!Number.isFinite(n)) return 0;
  const scaled = n <= 1 ? n * 100 : n;
  return Math.max(0, Math.min(100, Math.round(scaled)));
}

async function identifyL2(apiKey, mediaType, b64, detectedL1s, guide, trees) {
  if (!detectedL1s.length) return { byCode: {}, usage: null };
  if (!trees || !trees.common || !trees.l1) {
    return { error: "L2 decision trees not loaded (data/l2_decision_trees.json)" };
  }

  // Concat only the decision-tree blocks for L1s actually detected in Pass 1.
  // Keeps prompt bounded on small sketches; full tree set is 38 blocks.
  const blocks = [];
  for (const d of detectedL1s) {
    const entry = trees.l1[d.code];
    if (!entry || !entry.tree) continue;
    blocks.push(`## §${d.code} — ${L1_CODES[d.code] || ""}\n\n${entry.tree}`);
  }
  if (!blocks.length) return { error: "no decision tree matched any detected L1" };

  // System block: §0 通用 prompt is invariant across every call, so caching it gives
  // the biggest savings. The per-L1 tree blocks vary per sketch (based on Pass 1
  // output) so they stay in user content.
  const system = trees.common;

  const detectedCodes = detectedL1s.map(d => d.code).join(", ");
  const userText = `以下是本次 sketch 偵測到的 ${detectedL1s.length} 個 L1 部位（${detectedCodes}）的判定邏輯樹。針對 **每個** L1 套用其 decision tree 找出最可能的 L2 零件。

${blocks.join("\n\n---\n\n")}

---

Return ONLY valid JSON (no markdown fences, no prose) in this exact shape:
{"l2_by_l1":{"AE":{"l2_code":"AE_004","confidence":85,"reasoning":"袖孔處見大U型剪接線","needs_text":false,"merged_candidates":[]}, ...}}

Rules:
- 每個偵測到的 L1 都要回一筆，l2_code 必須是該 L1 下的有效 code（格式：XX_NNN）。
- confidence：0-100 整數。decision tree 文字若用 0.0-1.0，請自行乘 100 回報整數。
- reasoning：<80 字繁中，引述命中的 decision tree 節點（例如「袖孔處見大U型剪接線」）。
- needs_text=true 代表這一 L1 的 L2 在 sketch 上無法獨斷，需靠 callout 文字定案；此時 l2_code 填「merged_candidates 裡最可能的那個」，merged_candidates 陣列列出所有無法區分的 L2 code。
- needs_text=false 時 merged_candidates 可為空陣列。
- 只回 JSON，不要 markdown code fence、不要任何其他文字。`;

  const data = await callClaude(apiKey, mediaType, b64, { system, userText }, 4000);
  if (data.error) return { error: data.error, detail: data.detail };

  const parsed = parseJson(data.text);
  if (!parsed) return { error: "non-JSON response from Claude (L2)", raw: data.text };

  const byCode = {};
  const map = parsed.l2_by_l1 || {};
  for (const [l1Code, v] of Object.entries(map)) {
    if (!v || !v.l2_code) continue;
    const section = guide?.l1?.[l1Code];
    const entry = section?.l2?.[v.l2_code];
    const mergedCandidates = Array.isArray(v.merged_candidates)
      ? v.merged_candidates
          .filter(c => typeof c === "string" && /^[A-Z]{2}_\d{3}$/.test(c))
          .slice(0, 5)
      : [];
    byCode[l1Code] = {
      l2_code: v.l2_code,
      l2_name: entry?.name || v.l2_code,
      confidence: clampConfidence(v.confidence),
      // Accept either "reasoning" (new) or "explanation" (legacy prompt); prefer reasoning.
      explanation: typeof v.reasoning === "string"
        ? v.reasoning.slice(0, 80)
        : (typeof v.explanation === "string" ? v.explanation.slice(0, 80) : null),
      needs_text: !!v.needs_text,
      merged_candidates: mergedCandidates,
      alternatives: [], // legacy field kept empty; merged_candidates supersedes it
    };
  }
  return { byCode, usage: data.usage };
}

// Production-tunable knob: claude-opus-4-7 (~76% L2) vs claude-sonnet-4-6 (~5× cheaper).
// Sonnet is good enough once the decision-tree prompt infrastructure guides reasoning.
const CLAUDE_MODEL = "claude-sonnet-4-6";

// system + image + user text: system holds the stable, cache-hittable prompt block;
// user holds image + per-call varying context. Image gets ephemeral cache too so
// Pass 1 and Pass 2 on the same sketch share the image tokenization.
async function callClaude(apiKey, mediaType, b64, { system, userText }, maxTokens = 2000) {
  const body = {
    model: CLAUDE_MODEL,
    max_tokens: maxTokens,
    messages: [{
      role: "user",
      content: [
        {
          type: "image",
          source: { type: "base64", media_type: mediaType, data: b64 },
          cache_control: { type: "ephemeral" }
        },
        { type: "text", text: userText }
      ]
    }]
  };
  if (system) {
    // Array form lets us attach cache_control to the stable block so repeated
    // analyses across different sketches share the system-prompt cache.
    body.system = [{ type: "text", text: system, cache_control: { type: "ephemeral" } }];
  }
  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "anthropic-beta": "prompt-caching-2024-07-31"
    },
    body: JSON.stringify(body)
  });
  if (!resp.ok) {
    const detail = await resp.text();
    return { error: `Claude API ${resp.status}`, detail };
  }
  const data = await resp.json();
  return { text: data.content?.[0]?.text || "", usage: data.usage || null, model: CLAUDE_MODEL };
}

function parseJson(text) {
  const clean = (text || "").replace(/^```(?:json)?\s*/i, "").replace(/```\s*$/, "").trim();
  try { return JSON.parse(clean); } catch { return null; }
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" }
  });
}
