import ctypes
from io import BytesIO
from PIL import Image

def copy_image_to_clipboard(image, signature_text="PrivacyMasker_Signature_829cf3"):
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    # 64비트 환경 대응을 위해 argtypes, restype을 명시적으로 설정
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p

    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p

    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = ctypes.c_bool

    user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    user32.OpenClipboard.restype = ctypes.c_bool

    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = ctypes.c_bool

    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p

    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = ctypes.c_bool

    GHND = 0x0042  # GMEM_MOVEABLE | GMEM_ZEROINIT
    CF_DIB = 8
    CF_UNICODETEXT = 13

    # 1. PIL 이미지를 BMP 포맷으로 변환하여 DIB 바이너리 추출
    try:
        output = BytesIO()
        image.convert("RGB").save(output, "BMP")
        dib_data = output.getvalue()[14:]  # BMP 헤더 14바이트를 제외하면 DIB 데이터임
    except Exception as e:
        print(f"[클립보드] 이미지 DIB 변환 실패: {e}")
        return False

    # 2. 클립보드 트랜잭션 시작
    if not user32.OpenClipboard(None):
        print("[클립보드] OpenClipboard 실패")
        return False

    try:
        user32.EmptyClipboard()

        # 3. DIB 데이터 쓰기
        h_dib = kernel32.GlobalAlloc(GHND, len(dib_data))
        if not h_dib:
            print("[클립보드] GlobalAlloc(DIB) 실패")
            return False
            
        p_dib = kernel32.GlobalLock(h_dib)
        if p_dib:
            ctypes.memmove(p_dib, dib_data, len(dib_data))
            kernel32.GlobalUnlock(h_dib)
            res1 = user32.SetClipboardData(CF_DIB, h_dib)
            if not res1:
                print("[클립보드] SetClipboardData(CF_DIB) 실패")
        else:
            print("[클립보드] GlobalLock(DIB) 실패")
            return False

        # 4. 시그니처 텍스트 쓰기
        sig_bytes = signature_text.encode('utf-16le') + b'\x00\x00'
        h_txt = kernel32.GlobalAlloc(GHND, len(sig_bytes))
        if not h_txt:
            print("[클립보드] GlobalAlloc(Text) 실패")
            return False
            
        p_txt = kernel32.GlobalLock(h_txt)
        if p_txt:
            ctypes.memmove(p_txt, sig_bytes, len(sig_bytes))
            kernel32.GlobalUnlock(h_txt)
            res2 = user32.SetClipboardData(CF_UNICODETEXT, h_txt)
            if not res2:
                print("[클립보드] SetClipboardData(CF_UNICODETEXT) 실패")
        else:
            print("[클립보드] GlobalLock(Text) 실패")
            return False

        print("[클립보드] 복사 로직 정상 성공!")
        return True
    except Exception as e:
        print(f"[클립보드] 데이터 탑재 중 오류: {e}")
        return False
    finally:
        user32.CloseClipboard()

if __name__ == "__main__":
    # 테스트용 빨간색 이미지 생성
    img = Image.new("RGB", (200, 200), color="red")
    copy_image_to_clipboard(img)
