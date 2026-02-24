# Setup script to recreate symlink after cloning the repository
# Run this script after cloning: .\setup_symlink.ps1

Write-Host "Setting up symlink for mcp_tools..." -ForegroundColor Cyan

$symlinkPath = "godcomet\backend\mcp_tools"
$targetPath = "..\..\mcp-automation\src\tools"

# Check if symlink already exists
if (Test-Path $symlinkPath) {
    $item = Get-Item $symlinkPath -Force
    if ($item.LinkType -eq "SymbolicLink") {
        Write-Host "Symlink already exists at $symlinkPath" -ForegroundColor Green
        exit 0
    } else {
        Write-Host "Removing existing file/directory at $symlinkPath" -ForegroundColor Yellow
        Remove-Item $symlinkPath -Recurse -Force
    }
}

# Check if target exists
$fullTargetPath = Join-Path (Split-Path $symlinkPath) $targetPath
if (-not (Test-Path $fullTargetPath)) {
    Write-Host "ERROR: Target path does not exist: $fullTargetPath" -ForegroundColor Red
    Write-Host "Make sure you're in the root of the GodComet repository" -ForegroundColor Yellow
    exit 1
}

# Create the symlink
try {
    New-Item -ItemType SymbolicLink -Path $symlinkPath -Target $targetPath -Force | Out-Null
    Write-Host "✅ Symlink created successfully!" -ForegroundColor Green
    Write-Host "   $symlinkPath -> $targetPath" -ForegroundColor Gray
} catch {
    Write-Host "❌ Failed to create symlink: $_" -ForegroundColor Red
    Write-Host "You may need to run PowerShell as Administrator or enable Developer Mode" -ForegroundColor Yellow
    exit 1
}


