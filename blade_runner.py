import time
import os
import winsound # 导入 winsound 模块
import multiprocessing # 导入 multiprocessing 模块
import uiautomation as auto
from colorama import Style

from key_words import key_word_check
from get_stock_list import get_nasdaq_stock_symbols

MASTER = '卡门卡'
MASTER_GROUP = '天天去旅行'

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_control_tree(control, depth=0):
    if MASTER in control.Name:
        print("  " * depth + f"Depth: {depth}, Name: {control.Name}, Type: {control.ControlTypeName}, AutomationId: {control.AutomationId}")
    else:
        print("  " * depth + f"Depth: {depth}, Name: {control.Name}, Type: {control.ControlTypeName}, AutomationId: {control.AutomationId}")
    
    for child in control.GetChildren():
        print_control_tree(child, depth + 1)

def call_alert_sound(times=10):
    """在子进程中播放警报声"""
    try:
        if os.name == 'nt': # 检查是否为 Windows 系统
            # 参数：frequency (Hz), duration (ms)
            frequency = 1000
            duration_ms = 1000 * times
            winsound.Beep(frequency, duration_ms)
        else:
            # 对于非 Windows 系统，尝试打印 BEL 字符
            for _ in range(times):
                print('\a', end='', flush=True) # 尝试发出哔声
                time.sleep(1) # 非 Windows 下可能需要间隔
            print() # 换行
    except Exception as e:
        # 子进程中的错误最好记录到日志或通过其他方式传递，这里简化处理
        print(f"Error playing sound in subprocess: {e}")
        # 不再在这里打印主要警报信息

def add_this_message_list_to_all_message_list(this_message_list, all_message_list):
    newly_added_messages = [] # Track newly added messages in this call
    for message in this_message_list:
        if message not in all_message_list:
            # Print the new message first
            # print(f' ****** {MASTER} ****** ') # Indicate the sender - Old format
            print(Style.BRIGHT + f"\n---- New Message from: {MASTER} ----", Style.RESET_ALL) # New, cleaner format
            sub_message_list = message.split('\n引用')
            print(sub_message_list[0])
            if len(sub_message_list) > 1:
                print(Style.DIM + f'引用{sub_message_list[1]}', Style.RESET_ALL)
            
            all_message_list.append(message)
            newly_added_messages.append(message) # Add to newly added list for this run

            # Check for alerts only on new messages
            alert_score = key_word_check(message)
            if alert_score >= 1:
                print(f"ALERT! Message detected! BUY BUY BUY! Score: {alert_score}") # 在主进程中立即打印提示
                # 创建并启动一个新进程来播放声音
                alert_process = multiprocessing.Process(target=call_alert_sound, args=(10*alert_score,)) # 使用默认10秒
                alert_process.start() # 启动进程，不会阻塞主进程
    # Optional: return newly_added_messages if needed elsewhere, currently not used

def monitor_wechat(DELAY_TIME = 10):
    wechat_window = auto.WindowControl(searchDepth=1, Name=MASTER_GROUP)
    chat_list = wechat_window.ListControl(Name='消息')

    all_message_list = []
    start_time = time.time()
    animation_chars = ['|', '/', '-', '\\'] # Animation characters
    animation_index = 0

    while True:
        
        try:
            this_message_list = []
            for item in chat_list.GetChildren():
                try:
                    this_user = item.GetChildren()[0].GetChildren()[0].Name
                except Exception as e: # Catch specific exceptions if known, otherwise broad except
                    # print(f"Could not get username for item: {item.Name}, Error: {e}") # Optional debug print
                    this_user = 'None'

                # Get message content (assuming item.Name is correct as per original logic)
                message_content = item.Name

                if this_user == MASTER and message_content:
                    # Don't print here, handled by add_this_message_list_to_all_message_list
                    this_message_list.append(message_content)

        except Exception as e: # Catch specific exceptions if possible, e.g., auto.errors.NoWindowControl
            SECONDS_WAITING = int(time.time() - start_time)
            # Clear potential animation character before printing error
            print(f'\r窗口"{MASTER_GROUP}"未找到或访问出错 ({e})...已等待{SECONDS_WAITING}秒', end='')
            time.sleep(2) # Keep the short sleep for error retry
            print('\r' + ' ' * 80 + '\r', end='') # Clear the error line after waiting
            continue # Go back to the start of the loop

        # Reset start_time only after successful message retrieval
        start_time = time.time()
        add_this_message_list_to_all_message_list(this_message_list, all_message_list)

        # --- Waiting Animation ---
        wait_interval = 0.25 # How often to update the animation (in seconds)
        steps = int(DELAY_TIME / wait_interval)
        for i in range(steps):
            print(f'\rWaiting for new messages {animation_chars[animation_index]} ', end='')
            animation_index = (animation_index + 1) % len(animation_chars)
            time.sleep(wait_interval)
        # Clear the animation line after waiting is done
        print('\r' + ' ' * 30 + '\r', end='')
        # --- End Waiting Animation ---



if __name__ == '__main__':

    # 更新股票代码列表
    get_nasdaq_stock_symbols()
    
    # 对于 Windows 打包或冻结应用时需要
    multiprocessing.freeze_support()

    # wechat_window = auto.WindowControl(searchDepth=1, Name='天天去旅行')
    # chat_list = wechat_window.ListControl(Name='消息')
    # print_control_tree(chat_list)

    monitor_wechat(DELAY_TIME=10) # 启动微信监控

