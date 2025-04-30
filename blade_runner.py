import uiautomation as auto
import time


def print_control_tree(control, depth=0):
    print("  " * depth + f"Name: {control.Name}, Type: {control.ControlTypeName}, AutomationId: {control.AutomationId}")
    for child in control.GetChildren():
        print_control_tree(child, depth + 1)

def monitor_wechat():
    wechat_window = auto.WindowControl(searchDepth=1, Name='天天去旅行')
    chat_list = wechat_window.ListControl(Name='消息')
    while True:
        for item in chat_list.GetChildren():
            print(item.Name)  # 打印消息内容
        time.sleep(2)  # 每 2 秒检查一次

if __name__ == '__main__':
    # monitor_wechat()
    wechat_window = auto.WindowControl(searchDepth=1, Name='天天去旅行')
    chat_list = wechat_window.ListControl(Name='消息')
    print_control_tree(chat_list)
