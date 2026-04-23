export const config = { runtime: "nodejs", maxDuration: 60 };

const OWNER = "ellyfd";
const REPO  = "stytrix-techpack";
const BRANCH = "main";

export default async function handler(req, res) {
  if (req.method !== "POST") return res.status(405).end();

  // Auth: same shared token as admin POM editor
  const adminToken = process.env.ADMIN_TOKEN;
  if (adminToken) {
    const provided = req.headers["x-admin-token"] || "";
    if (provided !== adminToken) return res.status(401).json({ error: "unauthorized" });
  }

  const { filename, content_b64 } = req.body || {};
  if (!filename || !content_b64)
    return res.status(400).json({ error: "missing filename or content_b64" });

  const ext = filename.split(".").pop().toLowerCase();
  if (!["pdf", "pptx"].includes(ext))
    return res.status(400).json({ error: "only PDF/PPTX accepted" });

  const githubPat = process.env.GITHUB_PAT;
  if (!githubPat) return res.status(500).json({ error: "server missing GITHUB_PAT" });

  const safeName = filename.replace(/[^a-zA-Z0-9._-]/g, "_");
  const filePath = `data/ingest/uploads/${safeName}`;
  const apiUrl     = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${filePath}`;

  const ghHeaders = {
    Authorization: `token ${githubPat}`,
    Accept: "application/vnd.github.v3+json",
    "Content-Type": "application/json",
    "User-Agent": "stytrix-ingest-upload/1.0",
  };

  // Check if file already exists to get current SHA (required for update)
  let sha;
  try {
    const getResp = await fetch(apiUrl, { headers: ghHeaders });
    if (getResp.ok) {
      const existing = await getResp.json();
      sha = existing.sha;
    } else if (getResp.status !== 404) {
      const t = await getResp.text();
      return res.status(502).json({ error: `GitHub check error: ${getResp.status}`, detail: t });
    }
  } catch (e) {
    return res.status(502).json({ error: "GitHub API unreachable", detail: e.message });
  }

  // Create or update file
  const body = {
    message: `chore(ingest): upload ${safeName}`,
    content: content_b64,
    branch: BRANCH,
  };
  if (sha) body.sha = sha;

  let putResp;
  try {
    putResp = await fetch(apiUrl, { method: "PUT", headers: ghHeaders, body: JSON.stringify(body) });
  } catch (e) {
    return res.status(502).json({ error: "GitHub API unreachable", detail: e.message });
  }

  if (!putResp.ok) {
    const errText = await putResp.text();
    return res.status(502).json({ error: `GitHub API error: ${putResp.status}`, detail: errText });
  }

  const result = await putResp.json();
  return res.status(200).json({
    ok: true,
    path: filePath,
    sha: result.content?.sha,
    updated: !!sha,
    message: "Pipeline will rebuild in ~2 minutes",
  });
}
