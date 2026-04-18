export const config = { runtime: "edge" };

const L1_CODES = {
  AE: "袖孔", AH: "袖圍", BM: "下襬", BN: "貼合", BP: "襬叉",
  BS: "釦鎖", DC: "繩類", DP: "裝飾片", FP: "袋蓋", FY: "前立",
  HD: "帽子", HL: "釦環", KH: "Keyhole", LB: "商標", LI: "裡布",
  LO: "褲口", LP: "帶絆", NK: "領", NP: "領襟", NT: "領貼條",
  OT: "其它", PD: "褶", PK: "口袋", PL: "門襟", PS: "褲合身",
  QT: "行縫固定棉", RS: "褲襠", SA: "剪接線_上身類", SB: "剪接線_下身類",
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

  const { image, brand, fabric, gender, garment_type, item_type } = body;
  if (!image) return json({ error: "missing image" }, 400);

  const m = image.match(/^data:image\/(\w+);base64,(.+)$/);
  const mediaType = m ? `image/${m[1]}` : "image/png";
  const b64 = m ? m[2] : image;

  // ── Pass 1: identify which of the 38 L1 parts are in the sketch ──
  const detected = await identifyL1(apiKey, mediaType, b64, { brand, fabric, gender, garment_type, item_type });
  if (detected.error) return json(detected, 502);

  // ── Pass 2: for each detected L1, identify the most likely L2
  //    using its subset from data/l2_visual_guide.json (dynamic
  //    subset keeps the prompt cost bounded). ──
  const l2Map = await identifyL2(apiKey, mediaType, b64, detected.list, request);
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
      l2_alternatives: l2info.alternatives || []
    };
  });
  return json({ detected: merged, usage_l1: detected.usage, usage_l2: l2Map.usage });
}

async function identifyL1(apiKey, mediaType, b64, ctxObj) {
  const partList = Object.entries(L1_CODES).map(([k, v]) => `  ${k} = ${v}`).join("\n");
  const ctx = [
    ctxObj.brand && `Brand: ${ctxObj.brand}`,
    ctxObj.fabric && `Fabric: ${ctxObj.fabric}`,
    ctxObj.gender && `Gender: ${ctxObj.gender}`,
    ctxObj.garment_type && `Garment Type: ${ctxObj.garment_type}`,
    ctxObj.item_type && `Item Type: ${ctxObj.item_type}`
  ].filter(Boolean).join("\n");

  const prompt = `You are a garment manufacturing expert. Analyze this clothing sketch and identify which of the 38 construction parts below are visible in the drawing.

Part codes (code = Chinese name):
${partList}

${ctx ? "Context:\n" + ctx + "\n" : ""}
Return ONLY valid JSON (no markdown fences, no prose) in this exact shape:
{"detected":[{"code":"WB","side":"front","x":50,"y":10,"confidence":92}]}

Rules:
- code: one of the 38 codes above (exact).
- side: "front" or "back" based on which view the part is visible in.
- x, y: approximate position on the whole sketch as percentages 0-100 (x from left, y from top).
- confidence: 0-100, your certainty that this part is actually in the sketch.
- Include every part you can clearly see. Do NOT guess parts that are not drawn.
- If the sketch shows both front and back views side-by-side, x for a back part should be in the right half.`;

  const data = await callClaude(apiKey, mediaType, b64, prompt, 2000);
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

async function identifyL2(apiKey, mediaType, b64, detectedL1s, request) {
  if (!detectedL1s.length) return { byCode: {}, usage: null };

  let guide;
  try {
    guide = await loadGuide(request);
  } catch (e) {
    return { error: `L2 guide load failed: ${e?.message || e}` };
  }

  // Build a compact subset: only the detected L1s' L2 options (+ features).
  const subsetLines = [];
  for (const d of detectedL1s) {
    const section = guide.l1?.[d.code];
    if (!section || !section.l2) continue;
    const opts = Object.entries(section.l2)
      .sort((a, b) => (b[1].freq || 0) - (a[1].freq || 0))
      .slice(0, 25); // cap at 25 L2s per L1 to keep prompt bounded
    if (!opts.length) continue;
    subsetLines.push(`${d.code} (${L1_CODES[d.code]}):`);
    for (const [key, v] of opts) {
      const tierTag = v.tier === "red" ? "[sketch 上難分,仍請選最可能]" : "";
      const feat = v.feature || "(無視覺描述)";
      subsetLines.push(`  ${key}: ${v.name} — ${feat} ${tierTag}`.trim());
    }
    subsetLines.push("");
  }
  const subsetText = subsetLines.join("\n");

  const prompt = `I previously identified these L1 construction parts in this sketch: ${detectedL1s.map(d => d.code).join(", ")}.

For EACH of those L1s, pick the ONE most likely L2 (sub-type) using the visual features below. Prefer shape/position/structure over stitching detail. If the sketch genuinely can't tell one from another (common for stitching-only differences), still pick the visually closest one but set confidence low (≤40).

L2 options:
${subsetText}

Return ONLY valid JSON (no markdown fences, no prose) in this shape:
{"l2_by_l1":{"NK":{"l2_code":"NK_006","confidence":80,"alternatives":[{"l2_code":"NK_007","confidence":10}]}, ...}}

Rules:
- l2_code: must be an exact key from the options list for that L1.
- confidence: 0-100, your certainty.
- alternatives: up to 3 runner-ups with their confidence. Omit if none.`;

  const data = await callClaude(apiKey, mediaType, b64, prompt, 3000);
  if (data.error) return { error: data.error, detail: data.detail };

  const parsed = parseJson(data.text);
  if (!parsed) return { error: "non-JSON response from Claude (L2)", raw: data.text };

  const byCode = {};
  const map = parsed.l2_by_l1 || {};
  for (const [l1Code, v] of Object.entries(map)) {
    if (!v || !v.l2_code) continue;
    const section = guide.l1?.[l1Code];
    const entry = section?.l2?.[v.l2_code];
    byCode[l1Code] = {
      l2_code: v.l2_code,
      l2_name: entry?.name || v.l2_code,
      confidence: Number(v.confidence) || 0,
      alternatives: Array.isArray(v.alternatives) ? v.alternatives.slice(0, 3).map(a => ({
        l2_code: a.l2_code,
        l2_name: section?.l2?.[a.l2_code]?.name || a.l2_code,
        confidence: Number(a.confidence) || 0
      })) : []
    };
  }
  return { byCode, usage: data.usage };
}

async function callClaude(apiKey, mediaType, b64, prompt, maxTokens = 2000) {
  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "anthropic-beta": "prompt-caching-2024-07-31"
    },
    body: JSON.stringify({
      model: "claude-opus-4-7",
      max_tokens: maxTokens,
      messages: [{
        role: "user",
        content: [
          {
            type: "image",
            source: { type: "base64", media_type: mediaType, data: b64 },
            cache_control: { type: "ephemeral" }
          },
          { type: "text", text: prompt }
        ]
      }]
    })
  });
  if (!resp.ok) {
    const detail = await resp.text();
    return { error: `Claude API ${resp.status}`, detail };
  }
  const data = await resp.json();
  return { text: data.content?.[0]?.text || "", usage: data.usage || null };
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
