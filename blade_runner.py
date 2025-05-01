
import time
import os
import winsound # 导入 winsound 模块
import multiprocessing # 导入 multiprocessing 模块
import uiautomation as auto

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
    for message in this_message_list:
        if message not in all_message_list:
            all_message_list.append(message)
            alert_score = key_word_check(message)
            if alert_score >= 1:
                print(f"ALERT! Message detected! BUY BUY BUY! Score: {alert_score}") # 在主进程中立即打印提示
                # 创建并启动一个新进程来播放声音
                alert_process = multiprocessing.Process(target=call_alert_sound, args=(10*alert_score,)) # 使用默认10秒
                alert_process.start() # 启动进程，不会阻塞主进程

def monitor_wechat():
    wechat_window = auto.WindowControl(searchDepth=1, Name=MASTER_GROUP)
    chat_list = wechat_window.ListControl(Name='消息')

    all_message_list = []
    
    while True:
        
        try:
            main_children = chat_list.GetChildren()
        except:
            print(f'窗口未找到...请确保"{MASTER_GROUP}"窗口存在')
            time.sleep(2)
            continue
        
        clear_screen()
        
        this_message_list = []
        for item in main_children:
            try:
                this_user = item.GetChildren()[0].GetChildren()[0].Name
            except:
                this_user = 'None'
            if this_user == MASTER:
                print(f' ****** {this_user} ****** ')
                print(item.Name)
                this_message_list.append(item.Name)

        add_this_message_list_to_all_message_list(this_message_list, all_message_list)
        time.sleep(10)  # 每 10 秒检查一次

if __name__ == '__main__':

    # 更新股票代码列表
    get_nasdaq_stock_symbols()
    
    # 对于 Windows 打包或冻结应用时需要
    multiprocessing.freeze_support()

    # wechat_window = auto.WindowControl(searchDepth=1, Name='天天去旅行')
    # chat_list = wechat_window.ListControl(Name='消息')
    # print_control_tree(chat_list)

    monitor_wechat() # 启动微信监控

