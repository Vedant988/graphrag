Enable-WindowsOptionalFeature -Online -FeatureName Microsoft-Windows-Subsystem-Linux -All -NoRestart
Enable-WindowsOptionalFeature -Online -FeatureName VirtualMachinePlatform -All -NoRestart
Write-Host ""
Write-Host "WSL feature enablement finished. If Windows says a restart is required, restart the PC before continuing Docker setup."
Read-Host "Press Enter to close this window"
