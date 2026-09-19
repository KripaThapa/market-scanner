# Image releases and deployment ownership

## Application repository: implemented

`GitHub Actions → GHCR images → SHA release tag`

`.github/workflows/build-images.yml` runs on pushes to `main`, pushes of tags
matching `v*`, and manual `workflow_dispatch`. It does not deploy anything or
connect to the Raspberry Pi. No cluster credentials are required here.

Python tests, both frontend formatting checks and production builds, and both
Playwright suites must pass before publishing. The three Dockerfiles build for
`linux/amd64` and `linux/arm64` using Buildx/QEMU. Each pushed manifest is checked
for both architectures before the release is advertised as ready.

Each frontend runs setup and tests in its own working directory. Setup uses
`npm ci --include=dev --bin-links` so the lockfile's Playwright test runner and
local executable are installed even when npm defaults omit development tools or
binary links. `npm ls` and a local CLI version check fail immediately if setup
is incomplete. Each frontend's installed CLI runs
`playwright install --with-deps chromium` to install its matching browser and
Ubuntu system dependencies. No global Playwright or implicit `npx` download is
used. Browser installation alone cannot fix a missing Node CLI.

Keep both `node_modules` directories independent and untracked. A previously
tracked `strategy-lab-frontend/node_modules → ../frontend/node_modules` symlink
caused the second `npm ci` to clear the public frontend's installed executables,
producing `playwright: not found`. The symlink is removed, ignore rules cover
both directories and symlinks, and CI rejects symlinked dependency directories
before installation. Both manifests and lockfiles already declare Playwright;
no dependency version change is needed for this fix.

The release tag is `sha-` followed by the first seven characters of the full
commit SHA. The repository name is lowercased. For this repository the images are:

```text
ghcr.io/kripathapa/market-scanner/application:sha-XXXXXXX
ghcr.io/kripathapa/market-scanner/frontend:sha-XXXXXXX
ghcr.io/kripathapa/market-scanner/strategy-lab:sha-XXXXXXX
```

There is no deployment dependency on `latest`. The application image is shared
by backend, internal-backend, scanner, research worker, migration Job, and
historical baseline Job; each selects its existing command. Both frontend images
serve compiled assets through unprivileged Nginx on port 8080.

Publishing workflows are serialized across refs. Before building each image,
the workflow refuses an existing release tag and fails closed on registry errors
other than an explicitly missing manifest. This prevents this workflow from
replacing published content, including short-SHA collisions. It is not a GHCR
registry-wide immutability policy: other authorized publishers must also preserve
release tags. Base images/dependency ranges are not fully digest-pinned, so this
does not claim reproducible rebuilds.

After a partial release, use **Re-run failed jobs** to retain successful build
jobs. If a failed job already pushed its image (for example, verification failed
afterward), use a new commit/release rather than overwriting or deleting the old
image. A fully successful release also requires a new commit to republish.

## Finding the release

Open **Actions → Test and build immutable images → successful run → Summary**.
The `summary` job writes **DEPLOYMENT READY**, the release tag, and all three
image references. This happens only after all tests, image pushes, architecture
checks, and release artifact upload succeed. The same run's **Artifacts** section
contains `deployment-release-tag`; download it to obtain `release-tag.txt`.
The `release` job also retains its `tag` and `repository` outputs for downstream
jobs. A failed build does not publish the release artifact or readiness summary.
This is an image release, not a Git tag or GitHub Release creation step.

## GitHub permissions and package visibility

The workflow defaults to `contents: read`; only the image build job receives
`packages: write`. GHCR login uses GitHub's automatic `GITHUB_TOKEN`, not a PAT,
SSH key, kubeconfig, or Pi credential. Repository/organization policy must allow
these actions and package publishing. If packages already exist, grant this
repository Actions access to those packages.

New GHCR packages are private by default. The workflow does not change package
visibility; existing packages retain their settings. Keep application and private
UI images private because they contain private strategy/research implementation.
Registry pull access for the homelab belongs to the separate deployment setup.
See [GitHub's Container registry documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## Separate homelab-k3s repository

`Successful GHCR release tag → Kubernetes manifests → manual Raspberry Pi k3s deployment`

`homelab-k3s` owns namespaces, PostgreSQL/storage, Deployments, Services, Ingress,
registry pull credentials, migration Jobs, and the explicitly requested historical
baseline Job. Kubernetes manifests and deployment scripts do not live in this
application repository. Copy a successful release tag into that repository's
deployment configuration; this workflow does not edit or trigger it.

No 20-trading-day baseline is run by this workflow. Preserve the private API/UI
boundary when configuring deployment: application authentication and role checks
remain unimplemented. See [security](security.md).
