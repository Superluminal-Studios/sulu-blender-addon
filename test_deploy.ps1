<#
.SYNOPSIS
    Test the GitHub deployment workflow locally.
.DESCRIPTION
    Replicates the GitHub Actions workflow that creates release zips.
.PARAMETER Version
    Version tag to use (e.g., "1.2.3"). Defaults to "0.0.0-local".
.PARAMETER Output
    Output path for the zip. Defaults to ~/Downloads/SuperluminalRender-<version>.zip
.EXAMPLE
    .\test_deploy.ps1
.EXAMPLE
    .\test_deploy.ps1 -Version "1.2.3"
#>

param(
    [string]$Version = "0.0.0-local",
    [string]$Output
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Stage = Join-Path $env:TEMP "SuperluminalRender"
$SafeVersion = $Version -replace '[^0-9A-Za-z._-]', '_'

if (-not $Output) {
    $Downloads = Join-Path $env:USERPROFILE "Downloads"
    $Output = Join-Path $Downloads "SuperluminalRender-$SafeVersion.zip"
}

Write-Host "=== Test Deploy ===" -ForegroundColor Cyan
Write-Host "Source:  $ScriptDir"
Write-Host "Stage:   $Stage"
Write-Host "Version: $Version"
Write-Host "Output:  $Output"
Write-Host ""

# Step 1: Clean and create staging folder
Write-Host "[1/4] Preparing staging folder..." -ForegroundColor Yellow
if (Test-Path $Stage) {
    Remove-Item -Recurse -Force $Stage
}
New-Item -ItemType Directory -Path $Stage | Out-Null

# Step 2: Copy files using robocopy (simple and fast)
Write-Host "[2/4] Copying files to staging..." -ForegroundColor Yellow

# Robocopy: exclude directories that contain binaries/dev stuff
# The Python-level should_exclude() handles fine-grained filtering
robocopy $ScriptDir $Stage /E /NFL /NDL /NJH /NJS /NC /NS `
    /XD .git .github .claude tests reports __pycache__ rclone `
    /XF session.json dev_config.json dev_config.example.json .gitignore .gitkeep rclone.exe | Out-Null

# Step 3: Run deploy.py in release mode
Write-Host "[3/4] Running deploy.py..." -ForegroundColor Yellow
$DeployScript = Join-Path $Stage "deploy.py"

# Patch deploy.py to use Windows temp path instead of /tmp
$DeployContent = Get-Content $DeployScript -Raw
$PatchedContent = $DeployContent -replace 'addon_directory = f"/tmp/\{ADDON_NAME\}"', "addon_directory = r`"$Stage`""
Set-Content -Path $DeployScript -Value $PatchedContent -NoNewline

python $DeployScript --version $Version --output $Output

if ($LASTEXITCODE -ne 0) {
    Write-Host "=== Failed ===" -ForegroundColor Red
    Write-Host "deploy.py exited with code $LASTEXITCODE"
    exit 1
}

# Step 4: Verify output
Write-Host "[4/4] Verifying output..." -ForegroundColor Yellow
if (Test-Path $Output) {
    $ZipInfo = Get-Item $Output
    Write-Host ""
    Write-Host "=== Success ===" -ForegroundColor Green
    Write-Host "Created: $Output"
    Write-Host "Size:    $([math]::Round($ZipInfo.Length / 1KB, 2)) KB"
    Write-Host ""

    # List zip contents
    Write-Host "Zip contents:" -ForegroundColor Cyan
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip = [System.IO.Compression.ZipFile]::OpenRead($Output)
    try {
        $Zip.Entries | Select-Object -First 50 | ForEach-Object {
            Write-Host "  $($_.FullName)"
        }
        $Total = $Zip.Entries.Count
        if ($Total -gt 50) {
            Write-Host "  ... and $($Total - 50) more files"
        }
        Write-Host ""
        Write-Host "Total files: $Total" -ForegroundColor Cyan

        # Check for rclone binaries (should not exist)
        $RcloneBinaries = $Zip.Entries | Where-Object { $_.Name -match '^rclone(\.exe)?$' }
        if ($RcloneBinaries) {
            Write-Host ""
            Write-Host "WARNING: rclone binaries found in zip!" -ForegroundColor Red
            $RcloneBinaries | ForEach-Object { Write-Host "  $($_.FullName)" -ForegroundColor Red }
        }
    } finally {
        $Zip.Dispose()
    }
} else {
    Write-Host "=== Failed ===" -ForegroundColor Red
    Write-Host "Output zip was not created!"
    exit 1
}
