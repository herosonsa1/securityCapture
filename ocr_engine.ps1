Param(
    [string]$ImagePath
)

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# 1. 모든 WinRT 타입 캐싱 로드 (PowerShell 캐시 바인딩 유도)
$StorageFileType = [Type]::GetType("Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime")
$FileAccessModeType = [Type]::GetType("Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime")
$RandomAccessStreamType = [Type]::GetType("Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime")
$StreamWithContentTypeType = [Type]::GetType("Windows.Storage.Streams.IRandomAccessStreamWithContentType, Windows.Storage.Streams, ContentType=WindowsRuntime")
$BitmapDecoderType = [Type]::GetType("Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime")
$SoftwareBitmapType = [Type]::GetType("Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime")
$OcrEngineType = [Type]::GetType("Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime")
$OcrResultType = [Type]::GetType("Windows.Media.Ocr.OcrResult, Windows.Media.Ocr, ContentType=WindowsRuntime")
$LanguageType = [Type]::GetType("Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime")

# WinRT API와 상호 작용하기 위한 어셈블리 로드
Add-Type -AssemblyName System.Runtime.WindowsRuntime

# WinRT 비동기 작업을 대기하고 결과를 반환하는 헬퍼 함수 (리플렉션 기반 제네릭 AsTask 바인딩)
function Wait-WinRT($asyncOp, $resultType) {
    if ($null -eq $asyncOp) {
        throw "WinRT async operation is null"
    }
    
    # System.WindowsRuntimeSystemExtensions.AsTask[TResult](IAsyncOperation[TResult]) 메서드 로드
    $asTaskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() | 
        Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -like "IAsyncOperation`*" } | 
        Select-Object -First 1
        
    $genericAsTask = $asTaskMethod.MakeGenericMethod($resultType)
    $task = $genericAsTask.Invoke($null, @($asyncOp))
    
    # 작업이 완료될 때까지 슬립 대기
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
    
    # 1. 이미지 파일 로드
    $fileOp = [Windows.Storage.StorageFile]::GetFileFromPathAsync($absolutePath)
    $file = Wait-WinRT $fileOp $StorageFileType
    
    # 2. 이미지 파일로부터 읽기 전용 스트림 열기
    $streamOp = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
    $stream = Wait-WinRT $streamOp $RandomAccessStreamType
    
    # 3. 비트맵 디코더 생성
    $decoderOp = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
    $decoder = Wait-WinRT $decoderOp $BitmapDecoderType
    
    # 4. 이미지의 소프트웨어 비트맵 추출
    $bitmapOp = $decoder.GetSoftwareBitmapAsync()
    $bitmap = Wait-WinRT $bitmapOp $SoftwareBitmapType
    
    # 5. 로컬 사용자의 기본 설정 언어로 OCR 엔진 생성
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
    if ($null -eq $engine) {
        # 예외 상황을 대비해 한국어(ko-KR) 명시적 생성 시도
        try {
            $lang = New-Object Windows.Globalization.Language("ko-KR")
            $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
        } catch {}
    }
    
    if ($null -eq $engine) {
        Write-Output '{"status":"error", "message": "OCR Engine could not be created."}'
        exit 1
    }
    
    # 6. OCR 문자 인식 수행
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
