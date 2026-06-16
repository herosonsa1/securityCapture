import ctypes
import time
from pynput import keyboard

# API 선언
GetAsyncKeyState = ctypes.windll.user32.GetAsyncKeyState
GetAsyncKeyState.argtypes = [ctypes.c_int]
GetAsyncKeyState.restype = ctypes.c_short

win_pressed_state = False
shift_pressed_state = False

def win32_filter(msg, data):
    global win_pressed_state, shift_pressed_state
    
    # 윈도우 키 감지 (LWIN: 0x5B, RWIN: 0x5C)
    if data.vkCode in (0x5B, 0x5C):
        if msg in (0x0100, 0x0104):  # WM_KEYDOWN, WM_SYSKEYDOWN
            win_pressed_state = True
        elif msg in (0x0101, 0x0105):  # WM_KEYUP, WM_SYSKEYUP
            win_pressed_state = False
            
    # 쉬프트 키 감지 (SHIFT: 0x10, LSHIFT: 0xA0, RSHIFT: 0xA1)
    if data.vkCode in (0x10, 0xA0, 0xA1):
        if msg in (0x0100, 0x0104):
            shift_pressed_state = True
        elif msg in (0x0101, 0x0105):
            shift_pressed_state = False

    # 디버깅 출력
    if msg in (0x0100, 0x0104):
        # 비동기 API 방식과 내부 훅 변수 추적 방식을 동시에 로깅
        api_win = (GetAsyncKeyState(0x5B) < 0) or (GetAsyncKeyState(0x5C) < 0)
        api_shift = (GetAsyncKeyState(0x10) < 0) or (GetAsyncKeyState(0xA0) < 0) or (GetAsyncKeyState(0xA1) < 0)
        
        print(f"[Key Down] VK: {hex(data.vkCode)} | "
              f"API_Win: {api_win}, API_Shift: {api_shift} | "
              f"Hook_Win: {win_pressed_state}, Hook_Shift: {shift_pressed_state}")
              
        # 만약 S 키가 눌렸고 Win + Shift 조합이 성립되면 감지 성공 알림
        if data.vkCode == 0x53:  # 'S' 키
            is_win = api_win or win_pressed_state
            is_shift = api_shift or shift_pressed_state
            if is_win and is_shift:
                print(">>> 감지 성공! Windows + Shift + S 조합 차단 대상!! <<<")
                return False  # S 키 차단 실험

    return True

if __name__ == "__main__":
    print("키보드 후킹 감시 시작 (아무 키나 누르거나 Win+Shift+S를 입력해 보세요...)")
    print("종료하려면 Ctrl+C 또는 콘솔창을 닫으세요.")
    listener = keyboard.Listener(win32_event_filter=win32_filter)
    listener.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        listener.stop()
