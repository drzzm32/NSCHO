# 烧录 NSCLK (ESP32-S2) 的 MicroPython 固件
# 用法： .\firmware\flash.ps1 -Port COM7 [-Build E:\Works\esp-mpy\ports\esp32\build] [-Erase]
param(
    [Parameter(Mandatory = $true)][string]$Port,
    [string]$Build = "E:\Works\esp-mpy\ports\esp32\build",
    [switch]$Erase
)
$ErrorActionPreference = "Stop"

$files = @{
    "0x1000"  = Join-Path $Build "bootloader\bootloader.bin"
    "0x8000"  = Join-Path $Build "partition_table\partition-table.bin"
    "0x10000" = Join-Path $Build "micropython.bin"
}
foreach ($k in $files.Keys) {
    if (-not (Test-Path $files[$k])) { throw "缺文件: $($files[$k])" }
}

Write-Host "目标芯片 esp32s2, 端口 $Port" -ForegroundColor Cyan
if ($Erase) {
    Write-Host "擦除整片 flash..." -ForegroundColor Yellow
    python -m esptool --chip esp32s2 --port $Port erase_flash
}

$args = @("--chip", "esp32s2", "--port", $Port, "write_flash", "-z",
          "0x1000", $files["0x1000"], "0x8000", $files["0x8000"], "0x10000", $files["0x10000"])
Write-Host "烧录中（约 1.2 MB）..." -ForegroundColor Yellow
python -m esptool @args
Write-Host "完成。按 RST 重启，串口应看到 MicroPython REPL。" -ForegroundColor Green
