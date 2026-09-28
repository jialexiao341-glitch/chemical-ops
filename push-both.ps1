param([switch]$ForceWithLease)

$ErrorActionPreference = 'Stop'

$repoRoot = (& git -C $PSScriptRoot rev-parse --show-toplevel)
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) {
  throw '无法定位 Git 仓库根目录。'
}

$branch = (& git -C $repoRoot branch --show-current)
if ($LASTEXITCODE -ne 0 -or -not $branch) {
  throw '当前处于分离 HEAD 状态，请切换到一个分支后再推送。'
}

$pushTargets = @(
  @{ Remote = 'github'; Label = 'GitHub' }
  @{ Remote = 'origin'; Label = 'Gitee' }
)

$failedTargets = @()

foreach ($target in $pushTargets) {
  & git -C $repoRoot remote get-url $target.Remote *> $null
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "未配置 $($target.Label) 远程仓库（remote: $($target.Remote)）。"
    $failedTargets += $target.Label
    continue
  }

  Write-Host "正在推送 $branch 到 $($target.Label)..."
  if ($ForceWithLease) {
    & git -C $repoRoot push --force-with-lease $target.Remote $branch
  } else {
    & git -C $repoRoot push $target.Remote $branch
  }
  if ($LASTEXITCODE -ne 0) {
    Write-Warning "$($target.Label) 推送失败。"
    $failedTargets += $target.Label
  }
}

if ($failedTargets.Count -gt 0) {
  throw "以下目标推送失败：$($failedTargets -join '、')。"
}

Write-Host "已将 $branch 推送到 GitHub 和 Gitee。"
