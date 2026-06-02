# Setting Up chainmind.com.ng as the Update Mirror

This guide explains how to host `latest.json` and the install scripts on your
own server so they stay in sync with GitHub Releases automatically.

---

## What needs to live on your server

| URL path                              | File / purpose                                          |
|---------------------------------------|---------------------------------------------------------|
| `https://chainmind.com.ng/install.ps1`     | Windows 1-command installer (copy from `installer/install.ps1`) |
| `https://chainmind.com.ng/install.sh`      | macOS/Linux installer (copy from `installer/install.sh`) |
| `https://chainmind.com.ng/api/release/latest.json` | Update manifest (auto-updated by CI)           |

---

## Option A — GitHub Actions pushes to your server via SSH (recommended)

Add this step **at the end** of the `release` job in `.github/workflows/build.yml`:

```yaml
      - name: Sync manifest to chainmind.com.ng
        uses: appleboy/scp-action@v0.1.7
        with:
          host:     ${{ secrets.DEPLOY_HOST }}      # e.g. chainmind.com.ng
          username: ${{ secrets.DEPLOY_USER }}      # e.g. ubuntu
          key:      ${{ secrets.DEPLOY_SSH_KEY }}   # private key (paste in Repo → Settings → Secrets)
          source:   "release/latest.json,installer/install.ps1,installer/install.sh"
          target:   "/var/www/chainmind/"           # your web root
```

Then add three GitHub repository secrets:
- `DEPLOY_HOST` → `chainmind.com.ng`
- `DEPLOY_USER` → your SSH username
- `DEPLOY_SSH_KEY` → contents of your private SSH key (`cat ~/.ssh/id_rsa`)

Your nginx / Apache should serve `/var/www/chainmind/` at `https://chainmind.com.ng/`.

---

## Option B — GitHub Actions calls a webhook on your server

Add a deploy webhook endpoint to your server (any language). Then add:

```yaml
      - name: Notify mirror
        run: |
          curl -X POST https://chainmind.com.ng/api/deploy-hook \
            -H "Authorization: Bearer ${{ secrets.DEPLOY_WEBHOOK_SECRET }}" \
            -d '{"version":"${{ steps.ver.outputs.version }}"}'
```

Your server webhook pulls from the GitHub raw URL:
```
https://raw.githubusercontent.com/chainmind-network/chainmind-node/main/release/latest.json
```

---

## Option C — Cloudflare Worker (zero-infrastructure)

Deploy a tiny Worker that proxies the GitHub raw manifest:

```js
// cloudflare worker — deploy at chainmind.com.ng/api/release/latest.json
export default {
  async fetch(request, env) {
    const GITHUB_RAW =
      "https://raw.githubusercontent.com/chainmind-network/chainmind-node/main/release/latest.json";
    const resp = await fetch(GITHUB_RAW, { cf: { cacheTtl: 300 } });
    return new Response(await resp.text(), {
      headers: {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
        "Cache-Control": "public, max-age=300",
      },
    });
  },
};
```

This means your server only needs to host the install scripts (`install.ps1`, `install.sh`).
The manifest is always live from GitHub, with 5-minute Cloudflare caching.

---

## Nginx config snippet

```nginx
server {
    listen 443 ssl;
    server_name chainmind.com.ng;

    root /var/www/chainmind;

    # Serve install scripts
    location = /install.ps1 {
        default_type text/plain;
    }
    location = /install.sh {
        default_type text/plain;
        add_header Content-Disposition inline;
    }

    # Serve update manifest
    location = /api/release/latest.json {
        default_type application/json;
        add_header Access-Control-Allow-Origin *;
        add_header Cache-Control "public, max-age=300";
    }
}
```

---

## Testing the mirror

Once deployed, verify both URLs respond:

```bash
curl https://chainmind.com.ng/api/release/latest.json | python3 -m json.tool
curl -I https://chainmind.com.ng/install.sh
curl -I https://chainmind.com.ng/install.ps1
```

All three should return 200 with the correct content type.
