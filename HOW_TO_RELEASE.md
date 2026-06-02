# How to Cut a ChainMind Node Release

Everything is automated. Here's the exact sequence to publish a new version.

---

## Prerequisites (one-time setup)

1. **Push this repo to GitHub** under `chainmind-network/chainmind-node`
   (adjust the repo path in `build.yml` if different).

2. **Enable GitHub Actions** — Actions tab → Enable.

3. **Add deploy secrets** if using the SSH mirror option (see `MIRROR_SETUP_GUIDE.md`).

4. That's it. No manual PyInstaller needed.

---

## Release workflow

```
┌─────────────────────────────────────────────┐
│  1. Commit your code changes + bump VERSION  │
│  2. git tag v1.2.3                           │
│  3. git push origin main --tags              │
│                                              │
│  GitHub Actions automatically:               │
│  ├── Builds .exe on Windows runner           │
│  ├── Builds .zip on macOS Intel runner       │
│  ├── Builds .zip on macOS Apple Silicon      │
│  ├── Builds binary on Linux runner           │
│  ├── Computes SHA-256 for each binary        │
│  ├── Creates a GitHub Release with assets    │
│  └── Commits updated release/latest.json     │
└─────────────────────────────────────────────┘
```

### Step-by-step

```bash
# 1. Make sure you're on main and everything is committed
git checkout main
git pull

# 2. Bump the version in VERSION file
echo "1.2.3" > VERSION
git add VERSION
git commit -m "chore: bump version to 1.2.3"

# 3. Tag and push
git tag v1.2.3
git push origin main --tags
```

That's it. Watch the build at:
`https://github.com/chainmind-network/chainmind-node/actions`

---

## Manual / emergency build (without CI)

If you need to build locally:

```bash
# Install build deps
pip install pyinstaller httpx streamlit fastapi uvicorn
pip install -r requirements.txt

# Build
pyinstaller chainmind.spec --clean --noconfirm

# Output is at dist/ChainMind-Node  (or dist/ChainMind-Node.exe on Windows)
```

After building locally, compute the checksum and update `release/latest.json` manually:

```bash
sha256sum dist/ChainMind-Node-linux-x64
# Then paste the hex into release/latest.json under checksums.linux_x64
```

---

## After the release — what users see

| Platform | 1-command install |
|----------|-------------------|
| Windows  | `iwr https://chainmind.com.ng/install.ps1 \| iex` |
| macOS / Linux | `curl -fsSL https://chainmind.com.ng/install.sh \| bash` |

Users already running ChainMind Node will get the update **silently in the
background** at next launch. They'll see a green notice: `✔ Updated to 1.2.3. Restart to apply.`

---

## Verifying the update manifest

```bash
curl https://chainmind.com.ng/api/release/latest.json | python3 -m json.tool
```

Should show the new version + correct download URLs + SHA-256 checksums.
