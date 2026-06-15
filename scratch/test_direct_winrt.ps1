Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Type]::GetType("Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime")

$absolutePath = [System.IO.Path]::GetFullPath("test_target.png")
$op = [Windows.Storage.StorageFile]::GetFileFromPathAsync($absolutePath)
while ($op.Status -eq 'Started') {
    Start-Sleep -Milliseconds 5
}
$file = $op.GetResults()
Write-Output "File loaded directly: $($file.Name)"
