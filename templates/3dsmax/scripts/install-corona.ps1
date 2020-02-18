param (
    [string]$fairSaasUsername,
    [string]$fairSaasPassword,
    [string]$source,
    [string]$destination
)
$source = $source.ToUpper()
$current_path = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition
Start-Transcript -Path (Join-Path $current_path "corona-install.log")
cd $current_path
Write-Host "Environment:"
gci env: | sort name
if (!$destination) { 
    if ($env:3DSMAX_2019) {
        $destination = $env:3DSMAX_2019
    } elseif ($env:3DSMAX_2018) {
        $destination = $env:3DSMAX_2018
    } else {
        $destination = (Get-ChildItem -Path "C:\Autodesk\3DsMax*" | Select-Object -Last 1).FullName
    }
}
if (Test-Path $destination -ErrorAction Continue) {
    Write-Host "Copying files from $source to $destination"
    xcopy $source $destination /Y /S
} else {
    Write-Host "Destination $destination not found"
}
new-item $env:LOCALAPPDATA/CoronaRenderer -itemtype directory -force
$fairSaasUsername + ":" + $fairSaasPassword > $env:LOCALAPPDATA/CoronaRenderer/CoronaActivation.txt
Stop-Transcript