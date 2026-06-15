Add-Type -AssemblyName System.Runtime.WindowsRuntime

$StorageFileType = [Type]::GetType("Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime")

function Wait-WinRT($asyncOp, $resultType) {
    $asTaskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | 
        Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -like "IAsyncOperation`*" } | 
        Select-Object -First 1
        
    $genericAsTask = $asTaskMethod.MakeGenericMethod($resultType)
    $task = $genericAsTask.Invoke($null, @($asyncOp))
    
    while (-not $task.IsCompleted) {
        Start-Sleep -Milliseconds 5
    }
    return $task.Result
}

$absolutePath = [System.IO.Path]::GetFullPath("test_target.png")
$op = [Windows.Storage.StorageFile]::GetFileFromPathAsync($absolutePath)
$file = Wait-WinRT $op $StorageFileType
Write-Output "File loaded successfully: $($file.Name)"
