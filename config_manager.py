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

def copy_image_to_clipboard(image):
    """
    ctypes를 활용하여 PIL Image 객체를 윈도우 클립보드에 삽입합니다.
    외부 프로세스(powershell 등) 호출이 없어 속도가 매우 빠르고 Blocker와의 경합을 방지합니다.
    """
    import ctypes
    from io import BytesIO

    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32

    # 64비트 환경 대응을 위해 argtypes 및 restype 명시적 정의
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

    # 상수 정의
    GHND = 0x0042  # GMEM_MOVEABLE | GMEM_ZEROINIT
    CF_DIB = 8

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

        return True
    except Exception as e:
        print(f"[클립보드] 데이터 탑재 중 오류: {e}")
        return False
    finally:
        user32.CloseClipboard()

