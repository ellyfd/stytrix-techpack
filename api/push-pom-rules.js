export const config = { runtime: "edge" };

const ALLOWED_DIR = "pom_rules/";
const MAX_FILES = 200;
const MAX_TOTAL_BYTES = 5 * 1024 * 1024;

export default async function handler(req) {
  if (req.method !== "POST") return json({ error: "method not allowed" }, 405);

  const adminToken = req.headers.get("x-admin-token");
  if (!process.env.ADMIN_TOKEN) return json({ error: "Server 未設 ADMIN_TOKEN" }, 500);
  if (adminToken !== process.env.ADMIN_TOKEN) return json({ error: "未授權:管理 Token 錯誤" }, 401);

  const githubToken = process.env.GITHUB_TOKEN;
  const repo = process.env.GITHUB_REPO;
  if (!githubToken || !repo) return json({ error: "Server 未設 GITHUB_TOKEN / GITHUB_REPO" }, 500);

  let body;
  try { body = await req.json(); }
  catch { return json({ error: "invalid JSON body" }, 400); }

  const { files, message } = body || {};
  if (!Array.isArray(files) || !files.length) return json({ error: "files 空" }, 400);
  if (files.length > MAX_FILES) return json({ error: `檔案過多 (>${MAX_FILES})` }, 400);

  let totalBytes = 0;
  for (const f of files) {
    if (typeof f?.path !== "string" || typeof f?.content !== "string") {
      return json({ error: "每個檔案需有 path + content" }, 400);
    }
    if (!f.path.startsWith(ALLOWED_DIR) || !f.path.endsWith(".json") || f.path.includes("..")) {
      return json({ error: `路徑不允許: ${f.path}` }, 400);
    }
    try { JSON.parse(f.content); }
    catch (e) { return json({ error: `${f.path} JSON 解析失敗: ${e.message}` }, 400); }
    totalBytes += f.content.length;
  }
  if (totalBytes > MAX_TOTAL_BYTES) {
    return json({ error: `總大小超限 (${(totalBytes/1024/1024).toFixed(2)}MB > 5MB)` }, 400);
  }

  const branch = "main";
  const apiBase = `https://api.github.com/repos/${repo}`;
  const h = {
    "authorization": `Bearer ${githubToken}`,
    "accept": "application/vnd.github+json",
    "content-type": "application/json",
    "user-agent": "stytrix-admin-push",
    "x-github-api-version": "2022-11-28"
  };

  try {
    const refRes = await fetch(`${apiBase}/git/ref/heads/${branch}`, { headers: h });
    if (!refRes.ok) throw new Error(`取得 main ref 失敗 (${refRes.status}): ${await refRes.text()}`);
    const refData = await refRes.json();
    const parentSha = refData.object.sha;

    const commitRes = await fetch(`${apiBase}/git/commits/${parentSha}`, { headers: h });
    if (!commitRes.ok) throw new Error(`取得 parent commit 失敗 (${commitRes.status})`);
    const commitData = await commitRes.json();
    const baseTreeSha = commitData.tree.sha;

    const blobResults = await Promise.all(files.map(async (f) => {
      const res = await fetch(`${apiBase}/git/blobs`, {
        method: "POST", headers: h,
        body: JSON.stringify({ content: f.content, encoding: "utf-8" })
      });
      if (!res.ok) throw new Error(`創建 blob 失敗 ${f.path} (${res.status}): ${await res.text()}`);
      const data = await res.json();
      return { path: f.path, sha: data.sha };
    }));

    const treeRes = await fetch(`${apiBase}/git/trees`, {
      method: "POST", headers: h,
      body: JSON.stringify({
        base_tree: baseTreeSha,
        tree: blobResults.map(b => ({ path: b.path, mode: "100644", type: "blob", sha: b.sha }))
      })
    });
    if (!treeRes.ok) throw new Error(`創建 tree 失敗 (${treeRes.status}): ${await treeRes.text()}`);
    const treeData = await treeRes.json();

    const msg = typeof message === "string" && message.trim()
      ? message.trim().slice(0, 300)
      : `admin: 更新 pom_rules (${files.length} files)`;

    const newCommitRes = await fetch(`${apiBase}/git/commits`, {
      method: "POST", headers: h,
      body: JSON.stringify({ message: msg, tree: treeData.sha, parents: [parentSha] })
    });
    if (!newCommitRes.ok) throw new Error(`創建 commit 失敗 (${newCommitRes.status}): ${await newCommitRes.text()}`);
    const newCommit = await newCommitRes.json();

    const updateRes = await fetch(`${apiBase}/git/refs/heads/${branch}`, {
      method: "PATCH", headers: h,
      body: JSON.stringify({ sha: newCommit.sha, force: false })
    });
    if (!updateRes.ok) throw new Error(`更新 ref 失敗 (${updateRes.status}): ${await updateRes.text()}`);

    return json({
      ok: true,
      commit: {
        sha: newCommit.sha,
        url: newCommit.html_url,
        message: msg,
        fileCount: files.length
      }
    });
  } catch (e) {
    return json({ error: e.message || String(e) }, 502);
  }
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" }
  });
}
