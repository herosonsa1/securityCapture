"""
화면 획득 모듈 - DLP 환경 다중 폴백 지원
우선순위:
  1. DXGI Desktop Duplication (dxcam) - GPU 레벨, WDA_EXCLUDEFROMCAPTURE 우회
  2. MSS (mss 라이브러리) - Windows Desktop Duplication API
  3. Win+PrintScreen → 파일 읽기 - OS 신뢰 프로세스 활용 (DLP 프로세스 기반 차단 우회)
  4. PrintScreen → 클립보드 읽기 - OS 신뢰 프로세스 활용
  5. GDI BitBlt (ImageGrab) - 최후 폴백

※ DLP가 "프로세스 신뢰도 기반"으로 동작하는 경우 3~4번이 가장 효과적입니다.
   Windows 기본 캡처도구(Snipping Tool, Win+PrintScreen)가 허용된 환경에서 유효합니다.

※ 이 기능을 사용하기 전에 반드시 정보보안 담당부서의 사용 승인을 받으십시오.
"""

import ctypes
import io
import os
import glob
import time
from pathlib import Path
from PIL import Image

# dxcam은 선택적 의존성
try:
    import dxcam
    _DXCAM_AVAILABLE = True
except ImportError:
    _DXCAM_AVAILABLE = False

# mss
try:
    import mss as _mss_module
    _MSS_AVAILABLE = True
except ImportError:
    _MSS_AVAILABLE = False

# ImageGrab (GDI 폴백)
try:
    from PIL import ImageGrab
    _IMAGEGRAB_AVAILABLE = True
except ImportError:
    _IMAGEGRAB_AVAILABLE = False

# pyautogui (키보드 시뮬레이션)
try:
    import pyautogui
    _PYAUTOGUI_AVAILABLE = True
except ImportError:
    _PYAUTOGUI_AVAILABLE = False

# win32clipboard (클립보드 읽기)
try:
    import win32clipboard
    import win32con
    _WIN32CLIP_AVAILABLE = True
except ImportError:
    _WIN32CLIP_AVAILABLE = False



def _grab_via_dxgi(region=None):
    """
    dxcam 라이브러리를 사용하여 DXGI Desktop Duplication으로 화면을 획득합니다.
    region: (left, top, right, bottom) 픽셀 좌표 또는 None (전체 화면)
    반환값: PIL.Image 또는 None
    """
    if not _DXCAM_AVAILABLE:
        return None
    try:
        cam = dxcam.create(output_color="RGB")
        # dxcam은 한 번 grab() 호출로 최신 프레임 1장을 즉시 반환
        frame = cam.grab(region=region)
        del cam
        if frame is None:
            return None
        return Image.fromarray(frame)
    except Exception as e:
        print(f"[DXGI] 획득 실패: {e}")
        return None


def _grab_via_winrt(region=None):
    """
    Windows.Graphics.Capture (WinRT) API를 사용한 화면 획득.
    Windows 10 1803+ 환경에서 일부 DLP 방어 우회 가능.
    region: (left, top, right, bottom) 또는 None
    """
    try:
        import winrt.windows.graphics.capture as wgc
        import winrt.windows.graphics.directx.direct3d11 as d3d11
        # WinRT Graphics Capture는 COM 초기화 필요
        # 간단한 구현을 위해 mss 라이브러리를 먼저 시도
        raise NotImplementedError("WinRT 직접 구현 복잡 - mss 폴백 우선")
    except Exception:
        return None


def _grab_via_mss(region=None):
    """
    mss(Multiple Screen Shot) 라이브러리를 사용한 화면 획득.
    mss는 내부적으로 Windows Desktop Duplication API를 사용하여 GDI보다 DLP 회피 가능성이 높음.
    region: (left, top, right, bottom) 또는 None
    """
    try:
        import mss
        with mss.mss() as sct:
            if region:
                left, top, right, bottom = region
                mon = {"left": left, "top": top, "width": right - left, "height": bottom - top}
            else:
                # 전체 가상 스크린
                mon = sct.monitors[0]  # monitors[0] = 전체 가상 스크린 합산
            frame = sct.grab(mon)
            return Image.frombytes("RGB", frame.size, frame.bgra, "raw", "BGRX")
    except Exception as e:
        print(f"[MSS] 획득 실패: {e}")
        return None


def _grab_via_gdi(region=None):
    """
    GDI BitBlt 기반 전통 방식 (ImageGrab).
    DLP WDA_EXCLUDEFROMCAPTURE 에 의해 차단될 수 있음 (폴백 최후 수단).
    region: (left, top, right, bottom) 또는 None
    """
    if not _IMAGEGRAB_AVAILABLE:
        return None
    try:
        return ImageGrab.grab(bbox=region, all_screens=(region is None))
    except Exception as e:
        print(f"[GDI] 획득 실패: {e}")
        return None


def _grab_via_win_printscreen(region=None):
    r"""
    Win+PrintScreen 키를 시뮬레이션하여 Windows가 자동 저장하는
    %USERPROFILE%\Pictures\Screenshots\ 폴더의 최신 PNG 파일을 읽습니다.

    DLP가 프로세스 신뢰도 기반으로 차단하는 환경에서 가장 효과적입니다.
    Windows 시스템 프로세스(스니핑 툴 등)가 허용된 환경에서만 동작합니다.
    """
    if not _PYAUTOGUI_AVAILABLE:
        return None
    try:
        # Screenshots 폴더 경로
        screenshots_dir = Path.home() / "Pictures" / "Screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)

        # 저장 전 기존 파일 목록
        before = set(glob.glob(str(screenshots_dir / "*.png")))

        # Win+PrintScreen 시뮬레이션 (Windows가 스크린샷을 찍어 파일로 저장)
        pyautogui.hotkey('win', 'printscreen')
        time.sleep(0.8)  # 파일 저장 대기

        # 새로 생성된 파일 찾기
        after = set(glob.glob(str(screenshots_dir / "*.png")))
        new_files = after - before

        if not new_files:
            print("[Win+PrtSc] 새 파일 없음")
            return None

        # 가장 최신 파일
        latest = max(new_files, key=os.path.getmtime)
        img = Image.open(latest).convert("RGB")

        # 영역 크롭
        if region:
            left, top, right, bottom = region
            img = img.crop((left, top, right, bottom))

        print(f"[Win+PrtSc] 파일 읽기 성공: {latest}")
        return img
    except Exception as e:
        print(f"[Win+PrtSc] 획득 실패: {e}")
        return None


def _grab_via_clipboard_printscreen(region=None):
    """
    PrintScreen 키를 시뮬레이션하여 클립보드에서 화면 이미지를 가져옵니다.
    
    DLP가 프로세스 신뢰도 기반으로 차단하는 환경에서가장 효과적입니다.
    """
    if not (_PYAUTOGUI_AVAILABLE and _WIN32CLIP_AVAILABLE):
        return None
    try:
        # 현재 클립보드 내용 저장 (변경 감지용)
        win32clipboard.OpenClipboard()
        try:
            seq_before = win32clipboard.GetClipboardSequenceNumber()
        finally:
            win32clipboard.CloseClipboard()

        # PrintScreen 시뮬레이션
        pyautogui.press('printscreen')
        time.sleep(0.5)

        # 클립보드 변경 확인 (DLP가 클립보드에 작성을 허용한 경우)
        win32clipboard.OpenClipboard()
        try:
            seq_after = win32clipboard.GetClipboardSequenceNumber()
            if seq_after == seq_before:
                print("[PrtSc] 클립보드 미변경 (DLP 차단 가능성)")
                return None

            # CF_DIB (Device Independent Bitmap) 포맷으로 읽기
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                dib_data = win32clipboard.GetClipboardData(win32con.CF_DIB)
                img = Image.open(io.BytesIO(dib_data))
                img = img.convert("RGB")
            # CF_BITMAP 시도
            elif win32clipboard.IsClipboardFormatAvailable(win32con.CF_BITMAP):
                dib_data = win32clipboard.GetClipboardData(win32con.CF_BITMAP)
                img = Image.open(io.BytesIO(dib_data)).convert("RGB")
            else:
                print("[PrtSc] 클립보드에 이미지 없음")
                return None
        finally:
            win32clipboard.CloseClipboard()

        if region:
            left, top, right, bottom = region
            img = img.crop((left, top, right, bottom))

        return img
    except Exception as e:
        print(f"[PrtSc] 획득 실패: {e}")
        return None


def grab_screen(region=None):
    """
    우선순위에 따라 최적의 화면 획득 방법을 시도합니다.

    우선순위:
      1. DXGI Desktop Duplication (dxcam)
      2. MSS (Windows Duplication API)
      3. Win+PrintScreen → Screenshots 폴더 파일 읽기  ← DLP 프로세스 기반 차단 우회
      4. PrintScreen → 클립보드 읽기          ← DLP 프로세스 기반 차단 우회
      5. GDI BitBlt (최후 폴백)

    region: (left, top, right, bottom) 픽셀 좌표 또는 None (전체 화면)
    반환값: PIL.Image (RGB 모드) 또는 None
    """
    # 1순위: DXGI
    if _DXCAM_AVAILABLE:
        img = _grab_via_dxgi(region)
        if img is not None and _is_not_black(img):
            _log_method("DXGI Desktop Duplication")
            return img
        elif img is not None:
            print("[DXGI] 겨미 화면 감지 - 다음 방법 시도")

    # 2순위: MSS
    if _MSS_AVAILABLE:
        img = _grab_via_mss(region)
        if img is not None and _is_not_black(img):
            _log_method("MSS (Windows Duplication API)")
            return img
        elif img is not None:
            print("[MSS] 겨미 화면 감지 - 다음 방법 시도")

    # 3순위: Win+PrintScreen → 파일 (시스템 신뢰 프로세스 활용)
    if _PYAUTOGUI_AVAILABLE:
        img = _grab_via_win_printscreen(region)
        if img is not None and _is_not_black(img):
            _log_method("Win+PrintScreen (OS 신뢰 프로세스)")
            return img

    # 4순위: PrintScreen → 클립보드 (시스템 신뢰 프로세스 활용)
    if _PYAUTOGUI_AVAILABLE and _WIN32CLIP_AVAILABLE:
        img = _grab_via_clipboard_printscreen(region)
        if img is not None and _is_not_black(img):
            _log_method("PrintScreen → 클립보드 (OS 신뢰 프로세스)")
            return img

    # 5순위: GDI 폴백
    img = _grab_via_gdi(region)
    if img is not None:
        _log_method("GDI BitBlt (DLP 차단 가능)")
        return img

    print("[화면획득] 모든 방법 실패. 화면을 가져올 수 없습니다.")
    return None


def _is_not_black(img, threshold=10, sample_ratio=0.01):
    """
    챕베진 화면(DLP 차단) 여부를 빠르게 판단합니다.
    이미지 픽셀의 평균 밝기가 threshold 이하이면 검은 화면으로 간주.
    """
    try:
        from PIL import ImageStat
        stat = ImageStat.Stat(img.convert("L"))
        return stat.mean[0] > threshold
    except Exception:
        return True  # 판단 불가 시 정상으로 간주


def _log_method(method_name):
    print(f"[화면획득] 방법: {method_name}")


def get_virtual_screen_bounds():
    """다중 모니터 포함 전체 가상 스크린 경계를 반환합니다."""
    left   = ctypes.windll.user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    top    = ctypes.windll.user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    width  = ctypes.windll.user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    height = ctypes.windll.user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    return left, top, width, height


def install_dependencies():
    """필요한 의존성 패키지를 설치합니다."""
    import subprocess, sys
    packages = ["dxcam", "mss"]
    for pkg in packages:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])
            print(f"  ✅ {pkg} 설치 완료")
        except Exception as e:
            print(f"  ⚠️  {pkg} 설치 실패: {e}")


if __name__ == "__main__":
    print("=== 화면 획득 방법 테스트 ===")
    print("dxcam 사용 가능:", _DXCAM_AVAILABLE)
    print()

    # 테스트: 전체 화면 획득
    img = grab_screen()
    if img:
        img.save("grab_test_result.png")
        print(f"결과 저장: grab_test_result.png ({img.size})")
    else:
        print("❌ 화면 획득 실패")
