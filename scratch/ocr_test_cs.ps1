$OutputEncoding = [System.Text.Encoding]::UTF8

$Source = @"
using System;
using System.IO;
using System.Threading.Tasks;
using System.Collections.Generic;
using Windows.Storage;
using Windows.Graphics.Imaging;
using Windows.Media.Ocr;

public class OcrService {
    public static string Recognize(string imagePath) {
        try {
            var task = Task.Run(async () => {
                var file = await StorageFile.GetFileFromPathAsync(imagePath);
                using (var stream = await file.OpenAsync(FileAccessMode.Read)) {
                    var decoder = await BitmapDecoder.CreateAsync(stream);
                    var bitmap = await decoder.GetSoftwareBitmapAsync();
                    var engine = OcrEngine.TryCreateFromUserProfileLanguages();
                    if (engine == null) {
                        // 기본 유저 프로필 언어로 안되면 명시적으로 ko-KR 생성 시도
                        try {
                            var lang = new Windows.Globalization.Language("ko-KR");
                            engine = OcrEngine.TryCreateFromLanguage(lang);
                        } catch {}
                    }
                    if (engine == null) return "{\"status\":\"error\",\"message\":\"No OCR Engine\"}";
                    
                    var result = await engine.RecognizeAsync(bitmap);
                    var words = new List<string>();
                    foreach (var line in result.Lines) {
                        foreach (var word in line.Words) {
                            var r = word.BoundingRect;
                            words.Add(string.Format("{{\"text\":\"{0}\",\"x\":{1},\"y\":{2},\"width\":{3},\"height\":{4}}}",
                                word.Text.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\n", " ").Replace("\r", ""),
                                (int)r.X, (int)r.Y, (int)r.Width, (int)r.Height));
                        }
                    }
                    return "{\"status\":\"success\",\"words\":[" + string.Join(",", words) + "]}";
                }
            });
            return task.GetAwaiter().GetResult();
        } catch (Exception ex) {
            var inner = ex.InnerException != null ? ex.InnerException.Message : "";
            return "{\"status\":\"error\",\"message\":\"" + ex.Message.Replace("\"", "\\\"") + " " + inner.Replace("\"", "\\\"") + "\"}";
        }
    }
}
"@

# C# 코드 컴파일 및 로드
# 개별 WinRT 메타데이터 (.winmd) 파일들을 참조합니다.
$winMetadataDir = "C:\Windows\System32\WinMetadata"
$references = @(
    "System.Runtime.WindowsRuntime",
    "$winMetadataDir\Windows.Foundation.winmd",
    "$winMetadataDir\Windows.Storage.winmd",
    "$winMetadataDir\Windows.Graphics.winmd",
    "$winMetadataDir\Windows.Media.winmd"
)

# 모든 필수 winmd 파일이 존재하는지 확인
foreach ($ref in $references) {
    if ($ref -like "*.winmd" -and -not (Test-Path $ref)) {
        Write-Output "{\`"status\`":\`"error\`", \`"message\`":\`"Required reference metadata not found: $($ref.Replace('\', '\\'))\`"}"
        exit 1
    }
}

try {
    Add-Type -TypeDefinition $Source -ReferencedAssemblies $references -ErrorAction Stop
} catch {
    $err = $_.Exception.Message
    Write-Output "{\`"status\`":\`"error\`", \`"message\`":\`"Compilation failed: $($err.Replace('"', '\"'))\`"}"
    exit 1
}

# OCR 실행
$absolutePath = [System.IO.Path]::GetFullPath($args[0])
if (-not (Test-Path $absolutePath)) {
    Write-Output "{\`"status\`":\`"error\`", \`"message\`":\`"Image path not found: $($absolutePath.Replace('\', '\\'))\`"}"
    exit 1
}

$result = [OcrService]::Recognize($absolutePath)
Write-Output $result
