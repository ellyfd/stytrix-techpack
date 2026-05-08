export const config = { runtime: "nodejs", maxDuration: 30 };

// Admin endpoint to push data/runtime/pom_dictionary.json back to GitHub.
//
// Auth: requires `x-admin-token` header to match process.env.ADMIN_TOKEN
//       (a shared password the team sets in Vercel env vars).
// Commit: uses process.env.GITHUB_PAT (a GitHub Personal Access Token with
//       `contents: write` scope on this repo).
//
// Body: { dict: { code: { en, zh } }, message?: string }
// Returns: { ok, commit, commit_url, entries } | { error, detail? }
//
// The server sorts keys alphabetically and writes JSON.stringify(... , null, 2)
// for a diff-friendly commit.
export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "method not allowed" });
  }

  const adminToken = req.headers["x-admin-token"];
  const expected = process.env.ADMIN_TOKEN;
  if (!expected) {
    return res.status(500).json({ error: "Server missing ADMIN_TOKEN env var" });
  }
  if (!adminToken || adminToken !== expected) {
    return res.status(401).json({ error: "invalid admin token" });
  }

  const githubPat = process.env.GITHUB_PAT;
  if (!githubPat) {
    return res.status(500).json({ error: "Server missing GITHUB_PAT env var" });
  }

  const body = req.body;
  if (!body || typeof body !== "object" || !body.dict || typeof body.dict !== "object") {
    return res.status(400).json({ error: "body must be { dict: { code: {en, zh} }, message? }" });
  }
  const { dict, message } = body;

  // Validate structure: every entry must be {en?: string, zh?: string}
  const codePattern = /^[A-Z]{1,3}\d{0,3}$/;
  for (const [k, v] of Object.entries(dict)) {
    if (typeof k !== "string" || !codePattern.test(k)) {
      return res.status(400).json({ error: `invalid code key: ${k!=null?JSON.stringify(k):"null"}` });
    }
    if (!v || typeof v !== "object") {
      return res.status(400).json({ error: `entry ${k} must be an object` });
    }
    if (v.en != null && typeof v.en !== "string") {
      return res.status(400).json({ error: `entry ${k}.en must be string` });
    }
    if (v.zh != null && typeof v.zh !== "string") {
      return res.status(400).json({ error: `entry ${k}.zh must be string` });
    }
  }

  const OWNER = "ellyfd";
  const REPO = "stytrix-techpack";
  const FILE_PATH = "data/runtime/pom_dictionary.json";
  const BRANCH = "main";

  // Fetch current file to get its SHA (required by GitHub contents PUT).
  const getUrl = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE_PATH}?ref=${BRANCH}`;
  let getResp;
  try {
    getResp = await fetch(getUrl, {
      headers: {
        "Authorization": `Bearer ${githubPat}`,
        "Accept": "application/vnd.github+json",
        "User-Agent": "stytrix-techpack-admin",
      },
    });
  } catch (e) {
    return res.status(502).json({ error: "github fetch failed", detail: String(e) });
  }
  if (!getResp.ok) {
    const detail = await getResp.text();
    return res.status(502).json({ error: `github get ${getResp.status}`, detail });
  }
  const current = await getResp.json();
  const sha = current.sha;

  // Build sorted JSON for stable commits.
  const sortedDict = {};
  Object.keys(dict).sort().forEach((k) => {
    const v = dict[k];
    sortedDict[k] = { en: v.en || "", zh: v.zh || "" };
  });
  const newContent = JSON.stringify(sortedDict, null, 2) + "\n";
  const b64 = Buffer.from(newContent, "utf8").toString("base64");

  // If content hasn't changed, short-circuit.
  const currentB64 = (current.content || "").replace(/\s/g, "");
  if (b64.replace(/\s/g, "") === currentB64) {
    return res.status(200).json({
      ok: true, unchanged: true,
      commit: null, commit_url: null,
      entries: Object.keys(sortedDict).length,
    });
  }

  const putUrl = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE_PATH}`;
  const commitMessage = (typeof message === "string" && message.trim())
    ? message.trim()
    : `Update data/runtime/pom_dictionary.json via admin (${Object.keys(sortedDict).length} entries)`;
  let putResp;
  try {
    putResp = await fetch(putUrl, {
      method: "PUT",
      headers: {
        "Authorization": `Bearer ${githubPat}`,
        "Accept": "application/vnd.github+json",
        "User-Agent": "stytrix-techpack-admin",
        "content-type": "application/json",
      },
      body: JSON.stringify({
        message: commitMessage,
        content: b64,
        sha,
        branch: BRANCH,
      }),
    });
  } catch (e) {
    return res.status(502).json({ error: "github put failed", detail: String(e) });
  }
  if (!putResp.ok) {
    const detail = await putResp.text();
    return res.status(502).json({ error: `github put ${putResp.status}`, detail });
  }
  const putData = await putResp.json();
  return res.status(200).json({
    ok: true,
    commit: putData.commit?.sha || null,
    commit_url: putData.commit?.html_url || null,
    entries: Object.keys(sortedDict).length,
  });
}
