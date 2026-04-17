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

  const partList = Object.entries(L1_CODES).map(([k, v]) => `  ${k} = ${v}`).join("\n");
  const ctx = [
    brand && `Brand: ${brand}`,
    fabric && `Fabric: ${fabric}`,
    gender && `Gender: ${gender}`,
    garment_type && `Garment Type: ${garment_type}`,
    item_type && `Item Type: ${item_type}`
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

  const resp = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01"
    },
    body: JSON.stringify({
      model: "claude-opus-4-7",
      max_tokens: 2000,
      messages: [{
        role: "user",
        content: [
          { type: "image", source: { type: "base64", media_type: mediaType, data: b64 } },
          { type: "text", text: prompt }
        ]
      }]
    })
  });

  if (!resp.ok) {
    const detail = await resp.text();
    return json({ error: `Claude API ${resp.status}`, detail }, 502);
  }

  const data = await resp.json();
  const text = data.content?.[0]?.text || "";
  const clean = text.replace(/^```(?:json)?\s*/i, "").replace(/```\s*$/, "").trim();

  let parsed;
  try { parsed = JSON.parse(clean); }
  catch { return json({ error: "non-JSON response from Claude", raw: text }, 502); }

  const detected = Array.isArray(parsed.detected) ? parsed.detected : [];
  const valid = detected.filter(d => d && L1_CODES[d.code]);
  return json({ detected: valid, usage: data.usage || null });
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" }
  });
}
