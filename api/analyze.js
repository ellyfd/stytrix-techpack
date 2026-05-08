export const config = { runtime: "nodejs", maxDuration: 300 };

import { readFileSync } from "node:fs";
import { join } from "node:path";

// Load L2 guide + decision trees + L1 code table from deployment filesystem
// at module init. Previous version used fetch("/data/*.json") against
// request.url, which on Vercel Node.js runtime + Fluid Compute caused the
// handler to hang for the full maxDuration without issuing a single outgoing
// request. vercel.json includeFiles bundles data/*.json into the function
// so fs works.
const DATA_DIR = join(process.cwd(), "data", "runtime");
let GUIDE = null, TREES = null, L1_CODES = {};
try { GUIDE = JSON.parse(readFileSync(join(DATA_DIR, "l2_visual_guide.json"), "utf8")); }
catch (e) { console.warn("[analyze] guide not loaded:", e.message); }
try { TREES = JSON.parse(readFileSync(join(DATA_DIR, "l2_decision_trees.json"), "utf8")); }
catch (e) { console.warn("[analyze] trees not loaded:", e.message); }
try {
  const std = JSON.parse(readFileSync(join(DATA_DIR, "l1_standard_38.json"), "utf8"));
  for (const [k, v] of Object.entries(std.codes || {})) L1_CODES[k] = v.zh;
} catch (e) { console.warn("[analyze] l1_standard_38 not loaded:", e.message); }

let STYLE_GUIDE_TERMS = '';
try {
  const raw = readFileSync(join(process.cwd(), 'docs', 'spec', 'techpack-translation-style-guide.md'), 'utf8');
  // Extract Part A1 (ISO terms table) and Part C1 (L1 code table) for prompt injection
  const partA1 = raw.match(/### A1\..*?(?=### A2\.)/s)?.[0] || '';
  const partC1 = raw.match(/### C1\..*?(?=### C2\.)/s)?.[0] || '';
  STYLE_GUIDE_TERMS = [partA1, partC1].filter(Boolean).join('\n\n');
} catch (e) { console.warn('[analyze] style guide not loaded:', e.message); }

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "method not allowed" });
  }
  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (!apiKey) return res.status(500).json({ error: "Server missing ANTHROPIC_API_KEY env var" });

  // Vercel Node.js runtime auto-parses application/json into req.body.
  const body = req.body;
  if (!body || typeof body !== "object") {
    return res.status(400).json({ error: "invalid JSON body" });
  }

  const { image, brand, fabric, gender, department, garment_type, mode } = body;
  if (!image) return res.status(400).json({ error: "missing image" });
  // mode=universal → Path 2: 只跑 Pass 1 (L1)，前端用 iso_lookup_factory_v4.2 + v4 雙表查 ISO，不需 L2。
  const skipPass2 = mode === "universal";

  const m = image.match(/^data:image\/(\w+);base64,(.+)$/);
  const mediaType = m ? `image/${m[1]}` : "image/png";
  const b64 = m ? m[2] : image;

  // ── Pass 1: identify which of the 38 L1 parts are in the sketch ──
  const detected = await identifyL1(apiKey, mediaType, b64, { brand, fabric, gender, department, garment_type }, GUIDE);
  if (detected.error) return res.status(502).json(detected);

  // Path 2 通用模型只需要 L1 偵測結果即可；省掉 Pass 2 的 decision-tree 推論。
  if (skipPass2) {
    return res.status(200).json({ detected: detected.list, usage_l1: detected.usage, model: detected.model, mode: "universal" });
  }

  // ── Pass 2: for each detected L1, walk the decision tree to identify L2. ──
  const l2Map = await identifyL2(apiKey, mediaType, b64, detected.list, GUIDE, TREES);
  if (l2Map.error) {
    // Soft-fail: L2 couldn't be identified but L1 detection is still useful.
    return res.status(200).json({ detected: detected.list, l2_error: l2Map.error, usage: detected.usage });
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
  return res.status(200).json({
    detected: merged,
    usage_l1: detected.usage,
    usage_l2: l2Map.usage,
    model: l2Map.model || detected.model,
  });
}

async function identifyL1(apiKey, mediaType, b64, ctxObj, guide) {
  // Each L1 line: "  CODE = 中文名 — sketch 視覺定義（含 ↔ 兄弟對比）"
  const partList = Object.entries(L1_CODES).map(([k, v]) => {
    const def = guide?.l1?.[k]?.sketch_def || "";
    return def ? `  ${k} = ${v} — ${def}` : `  ${k} = ${v}`;
  }).join("\n");
  const ctx = [
    ctxObj.brand && `Brand: ${ctxObj.brand}`,
    ctxObj.fabric && `Fabric: ${ctxObj.fabric}`,
    ctxObj.gender && `Gender: ${ctxObj.gender}`,
    ctxObj.department && `Department: ${ctxObj.department}`,
    ctxObj.garment_type && `Garment Type: ${ctxObj.garment_type}`
  ].filter(Boolean).join("\n");

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

  const userText = `${ctx ? "Context:\n" + ctx + "\n\n" : ""}Return ONLY valid JSON (no markdown fences, no prose) in this exact shape:
{"detected":[{"code":"WB","side":"front","x":50,"y":10,"confidence":92}]}`;

  const data = await callClaude(apiKey, mediaType, b64, { system, userText }, 2000);
  if (data.error) return { error: data.error, detail: data.detail };

  const parsed = parseJson(data.text);
  if (!parsed) return { error: "non-JSON response from Claude (L1)", raw: data.text };
  const list = (parsed.detected || []).filter(d => d && L1_CODES[d.code]);
  return { list, usage: data.usage, model: data.model };
}

// Accept 0-100 integer OR 0.0-1.0 float; normalize to 0-100 clamped integer.
function clampConfidence(raw) {
  const n = Number(raw);
  if (!Number.isFinite(n)) return 0;
  const scaled = n <= 1 ? n * 100 : n;
  return Math.max(0, Math.min(100, Math.round(scaled)));
}

// VLM hallucinate fix: 從 sketch 讀字常把形似異體字或簡體誤字輸出
// (例如「襠底片」誤讀成「褶底片」/「檔底片」)
// 套用在所有 VLM 自由文字輸出 (reasoning / 說明 / Chinese zone names)
const ZH_NORMALIZE = {
  "褶底片": "襠底片",  // VLM hallucinate (襠 ↔ 褶 形似)
  "檔底片": "襠底片",  // 簡體誤字 (檔 ↔ 襠)
};
function normalizeZh(s) {
  if (typeof s !== "string" || !s) return s;
  let out = s;
  for (const [bad, good] of Object.entries(ZH_NORMALIZE)) {
    if (out.includes(bad)) out = out.split(bad).join(good);
  }
  return out;
}

async function identifyL2(apiKey, mediaType, b64, detectedL1s, guide, trees) {
  if (!detectedL1s.length) return { byCode: {}, usage: null };
  if (!trees || !trees.common || !trees.l1) {
    return { error: "L2 decision trees not loaded (data/l2_decision_trees.json)" };
  }

  const blocks = [];
  for (const d of detectedL1s) {
    const entry = trees.l1[d.code];
    if (!entry || !entry.tree) continue;
    blocks.push(`## §${d.code} — ${L1_CODES[d.code] || ""}\n\n${entry.tree}`);
  }
  if (!blocks.length) return { error: "no decision tree matched any detected L1" };

  const system = STYLE_GUIDE_TERMS
    ? `${trees.common}\n\n---\n**ISO Construction Terms Reference:**\n${STYLE_GUIDE_TERMS}`
    : trees.common;

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
      l2_name: normalizeZh(entry?.name || v.l2_code),
      confidence: clampConfidence(v.confidence),
      explanation: typeof v.reasoning === "string"
        ? normalizeZh(v.reasoning.slice(0, 80))
        : (typeof v.explanation === "string" ? normalizeZh(v.explanation.slice(0, 80)) : null),
      needs_text: !!v.needs_text,
      merged_candidates: mergedCandidates,
      alternatives: [],
    };
  }
  return { byCode, usage: data.usage, model: data.model };
}

// Sonnet 4.6 — ~2-3× faster and 5× cheaper than Opus 4.7 for this vision task.
// Sketch part identification isn't deep-reasoning; Sonnet handles it well.
const CLAUDE_MODEL = "claude-sonnet-4-6";

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
  const raw = (text || "").trim();
  if (!raw) return null;
  // Strip markdown code fences anywhere in the string (```json ... ``` or ``` ... ```)
  const unfenced = raw
    .replace(/^```(?:json)?\s*/i, "")
    .replace(/```\s*$/, "")
    .trim();
  // 1) Direct parse (covers the happy path: Claude obeyed "ONLY JSON").
  try { return JSON.parse(unfenced); } catch {}
  // 2) Best-effort extraction: grab the largest balanced {...} or [...] span.
  //    Scans for the first { or [ and finds its matching close while respecting
  //    string escapes — handles Claude prefixing/suffixing prose around JSON.
  const text2 = unfenced;
  const firstObj = text2.indexOf("{");
  const firstArr = text2.indexOf("[");
  let start = -1, opener = "";
  if (firstObj !== -1 && (firstArr === -1 || firstObj < firstArr)) { start = firstObj; opener = "{"; }
  else if (firstArr !== -1) { start = firstArr; opener = "["; }
  if (start === -1) return null;
  const closer = opener === "{" ? "}" : "]";
  let depth = 0, inStr = false, esc = false;
  for (let i = start; i < text2.length; i++) {
    const c = text2[i];
    if (esc) { esc = false; continue; }
    if (c === "\\" && inStr) { esc = true; continue; }
    if (c === '"') { inStr = !inStr; continue; }
    if (inStr) continue;
    if (c === opener) depth++;
    else if (c === closer) {
      depth--;
      if (depth === 0) {
        const candidate = text2.slice(start, i + 1);
        try { return JSON.parse(candidate); } catch { return null; }
      }
    }
  }
  return null;
}
