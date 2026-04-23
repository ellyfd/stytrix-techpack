export const config = { runtime: "nodejs" };

// Returns GITHUB_PAT to an authenticated admin so the browser can upload
// large files (>4.5 MB) directly to GitHub API, bypassing Vercel body limits.
export default function handler(req, res) {
  if (req.method !== "POST") return res.status(405).end();

  const adminToken = process.env.ADMIN_TOKEN;
  if (adminToken) {
    const provided = req.headers["x-admin-token"] || "";
    if (provided !== adminToken) return res.status(401).json({ error: "unauthorized" });
  }

  const githubPat = process.env.GITHUB_PAT;
  if (!githubPat) return res.status(500).json({ error: "server missing GITHUB_PAT" });

  res.setHeader("Cache-Control", "no-store");
  return res.status(200).json({ github_pat: githubPat });
}
