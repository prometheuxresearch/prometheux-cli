<#
.SYNOPSIS
  Install the Prometheux CLI (`px`) on Windows.

.DESCRIPTION
  Self-serve installer. Channel order (design §9): uv (primary) -> pipx -> pip --user.
  uv brings its own Python, so there is no per-platform build matrix; if uv is
  absent we offer to bootstrap it (skip with $env:PROMETHEUX_NO_BOOTSTRAP = '1').

  This is the SELF-SERVE path, NOT the enterprise path — banks install the signed
  wheel from their internal PyPI mirror with their sanctioned Python.

  Usage:
    irm https://raw.githubusercontent.com/prometheuxresearch/prometheux-cli/main/install.ps1 | iex

  Env:
    PROMETHEUX_VERSION       pin a release (e.g. 0.1.0)
    PROMETHEUX_NO_BOOTSTRAP  set to '1' to never auto-install uv
#>

$ErrorActionPreference = 'Stop'

$pkg = 'prometheux'
$spec = if ($env:PROMETHEUX_VERSION) { "$pkg==$($env:PROMETHEUX_VERSION)" } else { $pkg }

function Test-Command($name) {
  return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Install-WithUv {
  Write-Host "Installing $spec with uv…"
  uv tool install $spec
}

function Install-WithPipx {
  Write-Host "Installing $spec with pipx…"
  pipx install $spec
}

function Install-WithPip {
  Write-Warning "uv and pipx not found — falling back to 'pip install --user'."
  Write-Warning "(Tip: install uv — https://docs.astral.sh/uv/ — for an isolated, updatable install.)"
  python -m pip install --user $spec
}

function Bootstrap-Uv {
  if ($env:PROMETHEUX_NO_BOOTSTRAP -eq '1') { return $false }
  Write-Host "uv not found — bootstrapping it from https://astral.sh/uv …"
  try {
    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
  } catch {
    return $false
  }
  # uv installs to %USERPROFILE%\.local\bin; make it visible in this session.
  $uvBin = Join-Path $env:USERPROFILE '.local\bin'
  if (Test-Path $uvBin) { $env:PATH = "$uvBin;$env:PATH" }
  return (Test-Command 'uv')
}

if (Test-Command 'uv') {
  Install-WithUv
} elseif (Test-Command 'pipx') {
  Install-WithPipx
} elseif (Bootstrap-Uv) {
  Install-WithUv
} elseif (Test-Command 'python') {
  Install-WithPip
} else {
  Write-Error "Need uv, pipx, or Python 3.9+. Install one and retry. Recommended: irm https://astral.sh/uv/install.ps1 | iex"
  exit 1
}

Write-Host ""
if (Test-Command 'px') {
  $ver = (px --version 2>$null); if (-not $ver) { $ver = 'px' }
  Write-Host "Installed: $ver"
  Write-Host "Next: px skill install   (add the agent skill for Claude Code / Cursor)"
  Write-Host "Then: px login   (or set JARVISPY_URL + PMTX_TOKEN), then px --help"
} else {
  Write-Host "Installed, but 'px' is not on your PATH yet."
  Write-Host "uv:   restart your shell (uv puts tools on PATH), or add %USERPROFILE%\.local\bin to PATH."
  Write-Host "pipx: run 'pipx ensurepath' and restart your shell."
}
