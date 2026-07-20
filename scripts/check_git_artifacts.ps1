param(
    [int64]$MaximumBytes = 10MB
)

$ErrorActionPreference = "Stop"
$forbiddenPath = '(?i)(^|/)(backend/workspace|workspace|runtime|data|models|reports|\.downloads|\.venv|venv|node_modules|dist)(/|$)'
$forbiddenName = '(?i)(^|/)\.env(?:\..+)?$'
$forbiddenExtension = '(?i)\.(db|sqlite|sqlite3|safetensors|ckpt|pt|pth|onnx|wav|mp3|flac|m4a|mp4|mov|mkv|avi)$'
$errors = [System.Collections.Generic.List[string]]::new()

$files = @(& git diff --cached --name-only --diff-filter=ACMR)
foreach ($file in $files) {
    $normalized = $file -replace '\\', '/'
    if ($normalized -match $forbiddenPath -or $normalized -match $forbiddenName -or $normalized -match $forbiddenExtension) {
        $errors.Add("Forbidden generated, secret, model, or media file: $file")
        continue
    }

    $objectSize = & git cat-file -s ":$file" 2>$null
    if ($LASTEXITCODE -eq 0 -and [int64]$objectSize -gt $MaximumBytes) {
        $errors.Add("File exceeds $MaximumBytes bytes: $file ($objectSize bytes)")
    }
}

if ($errors.Count -gt 0) {
    Write-Error ("Commit blocked:`n" + ($errors -join "`n"))
    exit 1
}

Write-Host "Git artifact check passed ($($files.Count) staged files)."
