export const config = { runtime: "nodejs", maxDuration: 30 };

/* Admin endpoint: 寫 data/pom_dictionary.json 回 GitHub main 分支。
   需要 env:
     - ADMIN_TOKEN        前端送來的 x-admin-token 必須與此相等
     - GITHUB_TOKEN       有 repo:contents write 權限的 PAT
     - GITHUB_REPO        owner/name, 例: ellyfd/stytrix-techpack
     - GITHUB_BRANCH      預設 main */

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).json({ error: "method not allowed" });

  const tokenIn = req.headers["x-admin-token"];
  const tokenEnv = process.env.ADMIN_TOKEN;
  if (!tokenEnv) return res.status(500).json({ error: "Server missing ADMIN_TOKEN env var" });
  if (!tokenIn || tokenIn !== tokenEnv) return res.status(401).json({ error: "invalid admin token" });

  const ghToken = process.env.GITHUB_TOKEN;
  const repo = process.env.GITHUB_REPO;
  const branch = process.env.GITHUB_BRANCH || "main";
  if (!ghToken || !repo) return res.status(500).json({ error: "Server missing GITHUB_TOKEN or GITHUB_REPO env" });

  const body = req.body;
  if (!body || typeof body !== "object") return res.status(400).json({ error: "invalid JSON body" });

  const { data, message } = body;
  if (!data || typeof data !== "object") return res.status(400).json({ error: "missing data object" });

  const codes = Object.keys(data);
  if (codes.length < 10) return res.status(400).json({ error: `too few codes (${codes.length})` });
  for (const k of codes) {
    const v = data[k];
    if (!v || typeof v !== "object" || typeof v.en !== "string" || typeof v.zh !== "string") {
      return res.status(400).json({ error: `invalid entry for "${k}"` });
    }
  }

  const path = "data/pom_dictionary.json";
  const content = JSON.stringify(data, null, 2) + "\n";
  const base64 = Buffer.from(content, "utf8").toString("base64");

  const ghHeaders = {
    authorization: `Bearer ${ghToken}`,
    accept: "application/vnd.github+json",
    "x-github-api-version": "2022-11-28",
  };

  try {
    const getRes = await fetch(`https://api.github.com/repos/${repo}/contents/${path}?ref=${encodeURIComponent(branch)}`, {
      headers: ghHeaders,
    });
    let sha;
    if (getRes.ok) {
      const meta = await getRes.json();
      sha = meta.sha;
    } else if (getRes.status !== 404) {
      const txt = await getRes.text();
      return res.status(502).json({ error: `GitHub GET ${getRes.status}: ${txt.slice(0, 200)}` });
    }

    const putRes = await fetch(`https://api.github.com/repos/${repo}/contents/${path}`, {
      method: "PUT",
      headers: { ...ghHeaders, "content-type": "application/json" },
      body: JSON.stringify({
        message: message || `admin: update pom_dictionary (${codes.length} codes)`,
        content: base64,
        branch,
        sha,
      }),
    });
    const putBody = await putRes.json().catch(() => ({}));
    if (!putRes.ok) {
      return res.status(502).json({ error: `GitHub PUT ${putRes.status}: ${putBody.message || "(unknown)"}` });
    }
    return res.status(200).json({
      ok: true,
      commit: {
        sha: putBody.commit?.sha,
        url: putBody.commit?.html_url,
        codeCount: codes.length,
      },
    });
  } catch (e) {
    return res.status(500).json({ error: `unexpected: ${e.message || String(e)}` });
  }
}
