import os

code = """Param(
    [string]$ImagePath
)

$OutputEncoding = [System.Text.Encoding]::UTF8

# 1. 모든 WinRT 타입 캐싱 로드
$StorageFileType = [Type]::GetType("Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime")
$FileAccessModeType = [Type]::GetType("Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime")
$RandomAccessStreamType = [Type]::GetType("Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime")
$StreamWithContentTypeType = [Type]::GetType("Windows.Storage.Streams.IRandomAccessStreamWithContentType, Windows.Storage.Streams, ContentType=WindowsRuntime")
$BitmapDecoderType = [Type]::GetType("Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime")
$SoftwareBitmapType = [Type]::GetType("Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime")
$OcrEngineType = [Type]::GetType("Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime")
$OcrResultType = [Type]::GetType("Windows.Media.Ocr.OcrResult, Windows.Media.Ocr, ContentType=WindowsRuntime")
$LanguageType = [Type]::GetType("Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime")

Add-Type -AssemblyName System.Runtime.WindowsRuntime

# WinRT 비동기 작업을 대기하고 결과를 반환하는 헬퍼 함수
function Wait-WinRT($asyncOp, $resultType) {
    if ($null -eq $asyncOp) {
        throw "WinRT async operation is null"
    }
    
    # System.WindowsRuntimeSystemExtensions.AsTask[TResult](IAsyncOperation[TResult]) 메서드 가져오기
    $asTaskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | 
        Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -like "IAsyncOperation`*" } | 
        Select-Object -First 1
        
    $genericAsTask = $asTaskMethod.MakeGenericMethod($resultType)
    $task = $genericAsTask.Invoke($null, @($asyncOp))
    
    # Task 대기
    while (-not $task.IsCompleted) {
        Start-Sleep -Milliseconds 5
    }
    
    if ($task.IsFaulted) {
        if ($null -ne $task.Exception.InnerException) {
            throw $task.Exception.InnerException.Message
        }
        throw $task.Exception.Message
    }
    
    return $task.Result
}

try {
    $absolutePath = [System.IO.Path]::GetFullPath($ImagePath)
    if (-not (Test-Path $absolutePath)) {
        Write-Output '{"status":"error", "message": "Image file not found."}'
        exit 1
    }
    
    # 1. 파일 가져오기
    $fileOp = [Windows.Storage.StorageFile]::GetFileFromPathAsync($absolutePath)
    $file = Wait-WinRT $fileOp $StorageFileType
    
    # 2. 스트림 열기
    $streamOp = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
    $stream = Wait-WinRT $streamOp $RandomAccessStreamType
    
    # 3. 디코더 생성
    $decoderOp = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
    $decoder = Wait-WinRT $decoderOp $BitmapDecoderType
    
    # 4. 소프트웨어 비트맵 가져오기
    $bitmapOp = $decoder.GetSoftwareBitmapAsync()
    $bitmap = Wait-WinRT $bitmapOp $SoftwareBitmapType
    
    # 5. OCR 엔진 생성
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) {
        try {
            $lang = New-Object Windows.Globalization.Language("ko-KR")
            $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
        } catch {}
    }
    
    if ($null -eq $engine) {
        Write-Output '{"status":"error", "message": "OCR Engine could not be created."}'
        exit 1
    }
    
    # 6. OCR 인식 진행
    $ocrOp = $engine.RecognizeAsync($bitmap)
    $result = Wait-WinRT $ocrOp $OcrResultType
    
    $words = @()
    foreach ($line in $result.Lines) {
        foreach ($word in $line.Words) {
            $rect = $word.BoundingRect
            $wordObj = [PSCustomObject]@{
                text   = $word.Text
                x      = [int]$rect.X
                y      = [int]$rect.Y
                width  = [int]$rect.Width
                height = [int]$rect.Height
            }
            $words += $wordObj
        }
    }
    
    $response = [PSCustomObject]@{
        status = "success"
        words  = $words
    }
    
    $response | ConvertTo-Json -Depth 5 -Compress
} catch {
    $errObj = [PSCustomObject]@{
        status = "error"
        message = $_.Exception.Message
        trace   = $_.ScriptStackTrace
    }
    $errObj | ConvertTo-Json -Compress
}
"""

target_path = os.path.abspath("scratch/ocr_test.ps1")
with open(target_path, "w", encoding="utf-8-sig") as f:
    f.write(code)

print(f"ocr_test.ps1 파일이 UTF-8 BOM 인코딩으로 저장되었습니다: {target_path}")

