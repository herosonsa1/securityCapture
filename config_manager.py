import json
import os
import sys

CONFIG_FILE = "config.json"

def get_config_path():
    """
    실행 경로 기준 또는 임시 디렉토리가 아닌 실제 실행 파일의 영구 저장 디렉토리에 config.json 경로를 반환합니다.
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller로 빌드된 경우, sys.executable의 디렉토리를 씁니다 (sys._MEIPASS는 임시 폴더이므로 휘발됨)
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, CONFIG_FILE)

def load_config():
    """
    설정을 파일에서 읽어옵니다. 파일이 없거나 오류 발생 시 기본 설정을 반환합니다.
    """
    default_config = {
        "show_editor": True,
        "mask_type": "black",
        "name_mask_style": "surname",
        "block_other_captures": True
    }
    
    path = get_config_path()
    if not os.path.exists(path):
        return default_config
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
            # 기본값 누락 방지 보장
            for k, v in default_config.items():
                if k not in config:
                    config[k] = v
            return config
    except Exception as e:
        print(f"설정 파일 로드 실패: {e}")
        return default_config

def save_config(config):
    """
    설정을 파일에 저장합니다.
    """
    path = get_config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"설정 파일 저장 실패: {e}")
        return False

def copy_image_to_clipboard(image, signature_text="PrivacyMasker_Signature_829cf3"):
    """
    ctypes를 활용하여 PIL Image 객체와 고유 텍스트 시그니처를 윈도우 클립보드에 동시에 삽입합니다.
    외부 프로세스(powershell 등) 호출이 없어 속도가 매우 빠르고 Blocker와의 경합을 방지합니다.
    """
    import ctypes
    from io import BytesIO

    # Windows API 함수 정의
    GlobalAlloc = ctypes.windll.kernel32.GlobalAlloc
    GlobalLock = ctypes.windll.kernel32.GlobalLock
    GlobalUnlock = ctypes.windll.kernel32.GlobalUnlock
    SetClipboardData = ctypes.windll.user32.SetClipboardData
    EmptyClipboard = ctypes.windll.user32.EmptyClipboard
    OpenClipboard = ctypes.windll.user32.OpenClipboard
    CloseClipboard = ctypes.windll.user32.CloseClipboard

    # 상수 정의
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
    if not OpenClipboard(None):
        print("[클립보드] OpenClipboard 실패")
        return False

    try:
        EmptyClipboard()

        # 3. DIB 데이터 쓰기
        h_dib = GlobalAlloc(GHND, len(dib_data))
        if not h_dib:
            print("[클립보드] GlobalAlloc(DIB) 실패")
            return False
            
        p_dib = GlobalLock(h_dib)
        if p_dib:
            ctypes.memmove(p_dib, dib_data, len(dib_data))
            GlobalUnlock(h_dib)
            SetClipboardData(CF_DIB, h_dib)
        else:
            print("[클립보드] GlobalLock(DIB) 실패")
            return False

        # 4. 시그니처 텍스트 쓰기
        sig_bytes = signature_text.encode('utf-16le') + b'\x00\x00'
        h_txt = GlobalAlloc(GHND, len(sig_bytes))
        if not h_txt:
            print("[클립보드] GlobalAlloc(Text) 실패")
            return False
            
        p_txt = GlobalLock(h_txt)
        if p_txt:
            ctypes.memmove(p_txt, sig_bytes, len(sig_bytes))
            GlobalUnlock(h_txt)
            SetClipboardData(CF_UNICODETEXT, h_txt)
        else:
            print("[클립보드] GlobalLock(Text) 실패")
            return False

        return True
    except Exception as e:
        print(f"[클립보드] 데이터 탑재 중 오류: {e}")
        return False
    finally:
        CloseClipboard()

