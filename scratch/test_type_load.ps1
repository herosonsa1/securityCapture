$t = [Type]::GetType("Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime")
Write-Output "Type loaded: $($null -ne $t)"
if ($null -ne $t) {
    Write-Output "Accessing directly: $([Windows.Storage.StorageFile])"
}
