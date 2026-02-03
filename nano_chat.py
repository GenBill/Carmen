from google_api_launcher import call_gemini_chat
from auto_proxy import setup_proxy_if_needed
from rich.console import Console
from rich.markdown import Markdown

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout

# 设置代理
setup_proxy_if_needed(clash_port=7897)

def main():
    console = Console()
    chat = None
    client = None
    
    console.print("-" * 60, style="blue")
    console.print("Gemini 交互式会话已启动", style="bold blue")
    console.print("-" * 60, style="blue")

    # 配置 prompt_toolkit 的按键绑定
    kb = KeyBindings()

    @kb.add('c-c')
    def _(event):
        """
        处理 Ctrl+C：
        - 如果有内容：保留当前行，打印 ^C 并跳过本次交互
        - 如果没内容：退出程序
        """
        buffer = event.app.current_buffer
        if buffer.text:
            # 模仿 shell 行为：在当前行末尾打印 ^C 并换行
            # 这里直接通过 sys.stdout 打印，避开 buffer 的修改
            import sys
            sys.stdout.write("^C\n")
            sys.stdout.flush()
            # 退出当前 prompt 会话，result 为 None
            event.app.exit(result=None)
        else:
            # 内容为空时，Ctrl+C 视为退出
            event.app.exit(exception=EOFError)

    session = PromptSession(key_bindings=kb)

    try:
        while True:
            console.print("\n[bold green][User][/bold green]")
            
            with patch_stdout():
                try:
                    # session.prompt 会在按下 Ctrl+C 且有内容时返回 None
                    user_input = session.prompt("> ")
                except EOFError:
                    # 捕获 Ctrl+D 或空内容时的 Ctrl+C
                    break
            
            # 如果 user_input 为 None，说明是 Ctrl+C 跳过的，直接开始下一次循环
            if user_input is None:
                continue
                
            user_input = user_input.strip()
            if not user_input:
                continue
                
            # 调用接口
            with console.status("[bold cyan]Gemini 正在思考...[/bold cyan]", spinner="dots"):
                try:
                    response, chat, client = call_gemini_chat(user_input, chat=chat, client=client)
                except Exception as e:
                    console.print(f"[bold red]API 调用失败: {e}[/bold red]")
                    continue
            
            # 渲染 Markdown
            console.print(f"\n[bold magenta][Gemini][/bold magenta]")
            md = Markdown(response)
            console.print(md)
            console.print("\n" + "." * 30, style="dim")
            
    except Exception as e:
        console.print(f"\n[bold red]发生程序错误: {e}[/bold red]")
    finally:
        console.print("\n[bold blue]会话结束，感谢使用！[/bold blue]")

if __name__ == "__main__":
    main()
