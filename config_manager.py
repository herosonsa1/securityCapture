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
