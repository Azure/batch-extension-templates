param (
    [string]$fairSaasUsername,
    [string]$fairSaasPassword,
    [string]$source
)
$source = $source.ToUpper()
$current_path = Split-Path -Parent -Path $MyInvocation.MyCommand.Definition
Start-Transcript -Path (Join-Path $current_path "corona-install.log")
cd $current_path
Write-Host "Environment:"
gci env: | sort name


$3dsmax2021Source = "$source/Autodesk/3dsMax 2021 Plugin"
$3dsmax2021Destination = $env:3DSMAX_2021
if (Test-Path $3dsmax2021Destination -ErrorAction Continue) {
    Write-Host "Copying files from $3dsmax2021Source to $3dsmax2021Destination"
    xcopy $3dsmax2021Source $3dsmax2021Destination /Y /S
} else {
    Write-Host "Destination $3dsmax2021Destination not found"
}

$coronaProgramFilesSource = "$source/Corona"
$coronaProgramFilesDestination = "%PROGRAMFILES%/Corona"

new-item $coronaProgramFilesDestination -itemtype directory -force
if (Test-Path $coronaProgramFilesDestination -ErrorAction Continue) {
    Write-Host "Copying files from $coronaProgramFilesSource to $coronaProgramFilesDestination"
    xcopy $coronaProgramFilesSource $coronaProgramFilesDestination /Y /S
} else {
    Write-Host "Destination $coronaProgramFilesDestination not found"
}

new-item $env:LOCALAPPDATA/CoronaRenderer -itemtype directory -force
$fairSaasUsername + ":" + $fairSaasPassword > $env:LOCALAPPDATA/CoronaRenderer/CoronaActivation.txt
Stop-Transcript