import uiautomation as auto
import time
import os

MASTER = '卡门卡'

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_control_tree(control, depth=0):
    if MASTER in control.Name:
        print("  " * depth + f"Depth: {depth}, Name: {control.Name}, Type: {control.ControlTypeName}, AutomationId: {control.AutomationId}")
    else:
        print("  " * depth + f"Depth: {depth}, Name: {control.Name}, Type: {control.ControlTypeName}, AutomationId: {control.AutomationId}")
    
    for child in control.GetChildren():
        print_control_tree(child, depth + 1)

def monitor_wechat():
    wechat_window = auto.WindowControl(searchDepth=1, Name='天天去旅行')
    chat_list = wechat_window.ListControl(Name='消息')
    
    while True:
        clear_screen()
        for item in chat_list.GetChildren():
            try:
                this_user = item.GetChildren()[0].GetChildren()[0].Name
            except:
                this_user = 'None'
            if this_user == MASTER:
                print(f' ****** {this_user} ****** ')
                print(item.Name)  # 打印消息内容
        time.sleep(10)  # 每 10 秒检查一次

if __name__ == '__main__':

    monitor_wechat()
    
