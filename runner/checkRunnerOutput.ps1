# Taken from psake https://github.com/psake/psake

<#
.SYNOPSIS
  This is for checking all the test worked correctly by reading in an XML file 
#>
 param (
    [string]$outputFilePath
 )
$xml = [xml](Get-Content $outputFilePath)

if($outputFilePath -eq ""){
	Write-Output "No output file given"
	exit 1 
}

Write-Output "loading path $outputFilePath"
IF($xml.testsuite.failures -eq "0")
{
	$convertedTime = [timespan]::fromseconds($xml.testsuite.time).tostring()
 	Write-Output "All tests passed in $convertedTime"
 	Write-Output "Exiting with exit code 0"
 	exit 0
}
ELSE
{
	 Write-Output 'Runner failed'
	 Write-Output "Number of failed jobs $($xml.testsuite.failures) out of $($xml.testsuite.tests)"
	 Write-Output 'Please check the full log for more info'
	 Write-Output "Exiting with exit code 1"
	 exit 1
}

exit 1