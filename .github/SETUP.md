# GitHub Repository Setup Guide

This guide explains how to configure your GitHub repository to enable all automated workflows.

## Required GitHub Settings

### 1. Enable GitHub Pages

**Path:** Settings → Pages

- **Source:** Deploy from a branch
- **Branch:** Select `gh-pages` (will be created automatically)
  - Or use "GitHub Actions" as the source (recommended)
- **Folder:** `/ (root)`

**Alternative (Recommended):**
- **Source:** GitHub Actions
- This allows the workflow to deploy directly without needing a gh-pages branch

### 2. Enable GitHub Packages (Container Registry)

**Path:** Settings → Actions → General → Workflow permissions

- ✅ Enable "Read and write permissions"
- ✅ Enable "Allow GitHub Actions to create and approve pull requests"

This allows the release workflow to push Docker images to `ghcr.io`.

### 3. Configure Package Visibility

After the first release is published:

**Path:** Packages (from your repository or profile)

- Find the `eerovista` package
- Click "Package settings"
- Set visibility to "Public" (or keep private if preferred)
- Link the package to your repository if not auto-linked

### 4. Branch Protection Rules (Recommended)

**Path:** Settings → Branches → Add rule

Branch name pattern: `main`

Enable:
- ✅ Require a pull request before merging
  - ✅ Require approvals: 1
- ✅ Require status checks to pass before merging
  - Search and add:
    - `Code Quality`
    - `Unit Tests`
    - `Validate Docker Build (linux/amd64)`
    - `Validate Docker Build (linux/arm64)`
    - `Validate Docker Build (linux/arm/v7)`
    - `Test docker-compose`
- ✅ Require conversation resolution before merging
- ✅ Do not allow bypassing the above settings

### 5. Enable Workflows

**Path:** Settings → Actions → General

- ✅ Allow all actions and reusable workflows
- ✅ Allow GitHub Actions to create and approve pull requests

## Workflow Overview

### 📄 GitHub Pages (`pages.yml`)
- **Triggers:** Push to `main` branch (changes in `docs/` only)
- **Purpose:** Deploy documentation to GitHub Pages
- **Deployment URL:** `https://<username>.github.io/eerovista/`

### ✅ PR Validation (`pr-validation.yml`)
- **Triggers:** Pull requests to `main`
- **Steps:**
  1. Code quality checks (ruff linter & formatter)
  2. Unit tests with pytest (if tests exist)
  3. Docker build validation for all platforms
  4. docker-compose validation

### 🚀 Release (`release.yml`)
- **Triggers:** Publishing a GitHub Release
- **Steps:**
  1. Build multi-arch Docker images (amd64, arm64, arm/v7)
  2. Push to GitHub Container Registry
  3. Tag with version and `latest`
  4. Update release notes with Docker pull instructions

## Creating a Release

### Using GitHub UI

1. Go to: Releases → Draft a new release
2. Click "Choose a tag" → Create new tag (e.g., `v1.0.0`)
3. Set as target: `main` branch
4. Fill in release title and description
5. Click "Publish release"

The workflow will automatically build and publish Docker images.

### Using GitHub CLI

```bash
# Create and publish a release
gh release create v1.0.0 \
  --title "eeroVista v1.0.0" \
  --notes "Release notes here" \
  --target main

# The workflow will run automatically
gh run watch
```

## Accessing Published Images

After a release is published, Docker images are available at:

```bash
# Pull specific version
docker pull ghcr.io/<username>/eerovista:v1.0.0

# Pull latest
docker pull ghcr.io/<username>/eerovista:latest

# Pull for specific architecture
docker pull --platform linux/arm64 ghcr.io/<username>/eerovista:latest
```

## Troubleshooting

### Workflow fails with "Resource not accessible by integration"

**Solution:** Check workflow permissions in Settings → Actions → General
- Enable "Read and write permissions"

### Docker push fails with "denied: permission_denied"

**Solution:**
1. Ensure workflow has `packages: write` permission
2. Check that GITHUB_TOKEN has the correct scopes

### GitHub Pages not deploying

**Solution:**
1. Verify Pages is enabled in Settings → Pages
2. Set source to "GitHub Actions"
3. Check workflow run logs for errors

### Tests are skipped in PR

**Solution:** This is expected if no tests exist yet.
- Add tests to a `tests/` directory
- Tests will run automatically on future PRs

## Workflow Status Badges

Add these to your README.md:

```markdown
[![Deploy Docs](https://github.com/<username>/eerovista/actions/workflows/pages.yml/badge.svg)](https://github.com/<username>/eerovista/actions/workflows/pages.yml)
[![PR Validation](https://github.com/<username>/eerovista/actions/workflows/pr-validation.yml/badge.svg)](https://github.com/<username>/eerovista/actions/workflows/pr-validation.yml)
[![Release](https://github.com/<username>/eerovista/actions/workflows/release.yml/badge.svg)](https://github.com/<username>/eerovista/actions/workflows/release.yml)
```

Replace `<username>` with your GitHub username.
