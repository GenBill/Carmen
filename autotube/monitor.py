import os
import json
import glob
import time
import logging
import datetime
from typing import Optional, Dict, List
import tempfile

import requests
import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from openai import OpenAI
import whisper
import torch
import warnings

# 抑制 PyTorch TypedStorage 弃用警告
warnings.filterwarnings("ignore", message=".*TypedStorage is deprecated.*", category=UserWarning)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("autotube/monitor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 配置
CHANNEL_URL = "https://www.youtube.com/@Cash88888"
DEEPSEEK_TOKEN_PATH = "../agent/deepseek.token" # 相对路径，假设脚本在 autotube 目录下运行
CACHE_DIR = "autotube/.cache"
DAYS_TO_MONITOR = 30

def load_api_key(path: str) -> str:
    """加载 DeepSeek API Key"""
    try:
        # 尝试绝对路径
        if os.path.exists(path):
            with open(path, 'r') as f:
                return f.read().strip()
        # 尝试相对于当前文件的路径
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        abs_path = os.path.join(base_dir, path.lstrip('../')) # 简单的路径拼接
        if os.path.exists(abs_path):
            with open(abs_path, 'r') as f:
                return f.read().strip()
        
        # 最后的尝试：直接拼接
        direct_path = os.path.join(os.getcwd(), path)
        if os.path.exists(direct_path):
            with open(direct_path, 'r') as f:
                 return f.read().strip()
                 
        raise FileNotFoundError(f"Could not find token file at {path}")
    except Exception as e:
        logger.error(f"无法读取 API Key: {e}")
        raise

def init_directories():
    """初始化缓存目录"""
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def get_video_list(channel_url: str, days: int) -> List[Dict]:
    """获取最近 N 天的视频列表（包含普通视频和直播回放）"""
    logger.info(f"正在抓取频道视频列表: {channel_url}")
    
    cutoff_date = datetime.datetime.now() - datetime.timedelta(days=days)
    cutoff_str = cutoff_date.strftime('%Y%m%d')
    
    ydl_opts = {
        'quiet': True,      
        'extract_flat': False, 
        'playlistend': 20,    
        'ignoreerrors': True,
        # 既然都有警告，不如完全禁用警告输出，只关注我们需要的元数据
        # 我们只拿 id 和 title，不需要视频流，所以这些下载相关的警告可以安全忽略
        'noprogress': True,
        'no_warnings': True, 
    }

    # 明确扫描 视频 和 直播 两个 Tab
    target_urls = [
        f"{channel_url}/videos",
        f"{channel_url}/streams"
    ]
    
    all_videos = {} # 使用字典去重: id -> video_info

    logger.info(f"过滤日期基准: {cutoff_str}")

    for url in target_urls:
        logger.info(f"正在深度扫描: {url}")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 注意：extract_flat=False 时，extract_info 会对列表中的每个视频进行解析
                # 这会比之前慢，但能拿到准确的 upload_date
                info = ydl.extract_info(url, download=False)
                
                if 'entries' in info:
                    for entry in info['entries']:
                        if not entry: continue
                        
                        title = entry.get('title', 'No Title')
                        # 尝试获取多种日期字段
                        upload_date = entry.get('upload_date') or entry.get('release_date')
                        video_id = entry.get('id')
                        
                        # logger.info(f"  [解析] {upload_date} | {title}")

                        # 双重检查日期
                        if upload_date and upload_date >= cutoff_str:
                            # 过滤短视频 (< 5分钟)
                            duration = entry.get('duration')
                            if duration and duration < 300:
                                logger.info(f"  -> 跳过短视频: {title} ({duration}s)")
                                continue

                            if video_id and video_id not in all_videos:
                                all_videos[video_id] = {
                                    'id': video_id,
                                    'title': title,
                                    'url': entry.get('webpage_url', entry.get('url', f"https://www.youtube.com/watch?v={video_id}")),
                                    'upload_date': upload_date,
                                    'duration': duration
                                }
                                logger.info(f"  -> 纳入列表: {title} ({upload_date})")
                        else:
                            pass
                            # logger.info(f"    -> [跳过] 日期不符或缺失")

        except Exception as e:
            logger.error(f"扫描 URL 失败 {url}: {e}")
    
    videos = list(all_videos.values())
    # 按日期排序
    videos.sort(key=lambda x: x['upload_date'], reverse=True)
    
    logger.info(f"共发现 {len(videos)} 个最近 {days} 天内的视频/直播")
    return videos

def download_audio(video_url: str, output_path: str) -> bool:
    """下载视频音频"""
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'outtmpl': output_path,
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
        return True
    except Exception as e:
        logger.error(f"下载音频失败: {e}")
        return False

def get_whisper_model_size(device: str) -> str:
    """根据可用显存自动选择 Whisper 模型量级
    
    Args:
        device: 设备类型 ("cuda" 或 "cpu")
    
    Returns:
        模型名称: "large", "medium", "small", "base", "tiny"
    """
    if device == "cpu":
        # CPU 模式使用较小的模型以保证速度
        logger.info("CPU 模式，使用 base 模型")
        return "base"
    
    try:
        # 获取 GPU 显存信息（单位：字节）
        free_memory, total_memory = torch.cuda.mem_get_info(0)
        free_memory_gb = free_memory / (1024 ** 3)  # 转换为 GB
        total_memory_gb = total_memory / (1024 ** 3)
        
        logger.info(f"GPU 显存: 总计 {total_memory_gb:.2f}GB, 可用 {free_memory_gb:.2f}GB")
        
        # 根据可用显存选择模型（保留 1GB 缓冲）
        if free_memory_gb >= 9:
            model_size = "large"  # 需要约 10GB
        elif free_memory_gb >= 4:
            model_size = "medium"  # 需要约 5GB
        elif free_memory_gb >= 1.5:
            model_size = "small"   # 需要约 2GB
        elif free_memory_gb >= 0.5:
            model_size = "base"    # 需要约 1GB
        else:
            model_size = "tiny"    # 需要约 0.5GB
        
        logger.info(f"根据可用显存自动选择模型: {model_size}")
        return model_size
        
    except Exception as e:
        logger.warning(f"无法获取 GPU 显存信息: {e}，使用 medium 模型作为默认值")
        return "medium"

def transcribe_audio(audio_path: str) -> Optional[str]:
    """使用 Whisper 转录音频"""
    try:
        # 检查 CUDA 可用性
        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Whisper 将运行在设备: {device.upper()}")
        
        # 根据显存自动选择模型量级
        model_size = get_whisper_model_size(device)
        logger.info(f"正在加载 Whisper 模型 ({model_size})... 设备: {device}")
        model = whisper.load_model(model_size, device=device)
        
        logger.info(f"正在转录音频: {audio_path}")
        
        # 显式使用 no_grad 减少显存占用
        with torch.no_grad():
            # fp16=True 在 GPU 上默认开启，能显著提速（除非是古老的 GPU）
            # beam_size=1 可以牺牲极少量的准确率换取更快的速度
            # best_of=1 也是同样的道理
            result = model.transcribe(
                audio_path, 
                language='zh',
                fp16=True,
                beam_size=5, # 默认是 5，降低它能提速，比如改为 1
                best_of=5    # 默认是 5
            ) 
            
        return result["text"]
    except Exception as e:
        logger.error(f"Whisper 转录失败: {e}")
        return None

def get_transcript(video_id: str, video_url: str, save_dir: str = None) -> Optional[str]:
    """获取视频字幕文本 (优先 API，失败则使用 Whisper)"""
    # 1. 尝试 YouTube 原生字幕
    try:
        if hasattr(YouTubeTranscriptApi, 'list_transcripts'):
            try:
                ts_list = YouTubeTranscriptApi.list_transcripts(video_id)
                try:
                    t = ts_list.find_transcript(['zh-Hans', 'zh-Hant', 'zh', 'en'])
                except:
                    t = ts_list.find_generated_transcript(['zh-Hans', 'zh-Hant', 'zh', 'en'])
                return " ".join([i['text'] for i in t.fetch()])
            except Exception:
                pass # 继续尝试下面的方法

        transcript_data = YouTubeTranscriptApi.get_transcript(video_id, languages=['zh-Hans', 'zh-Hant', 'zh', 'en'])
        return " ".join([t['text'] for t in transcript_data])

    except (TranscriptsDisabled, NoTranscriptFound, Exception) as e:
        logger.warning(f"无法获取原生字幕 ({e})，尝试下载音频并使用 Whisper 转录...")
        
        # 2. Whisper 转录回退方案
        # 使用传入的 save_dir 或者默认的 audio 目录
        if save_dir:
            audio_dir = save_dir
        else:
            audio_dir = os.path.join(CACHE_DIR, "audio")
            
        if not os.path.exists(audio_dir):
            os.makedirs(audio_dir)
            
        # 实际文件可能是 audio.mp3
        expected_audio_file = os.path.join(audio_dir, f"{video_id}.mp3")
        
        # 检查是否已经存在音频文件，如果存在直接转录，不再下载
        if os.path.exists(expected_audio_file):
            logger.info(f"发现已下载音频: {expected_audio_file}，直接转录")
            return transcribe_audio(expected_audio_file)

        if download_audio(video_url, os.path.join(audio_dir, video_id)): # yt-dlp 会自动加后缀
             # 再次检查文件存在性（因为yt-dlp可能加了扩展名）
            if os.path.exists(expected_audio_file):
                return transcribe_audio(expected_audio_file)
            else:
                # 尝试模糊匹配
                files = glob.glob(os.path.join(audio_dir, f"{video_id}.*"))
                if files:
                    return transcribe_audio(files[0])
                logger.error("找不到下载的音频文件")
        
        return None

def rewrite_text(text: str, api_key: str) -> Optional[str]:
    """阶段 1: 文本重写"""
    logger.info("正在调用 DeepSeek API 进行文本重写...")
    
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    
    rewrite_prompt = f"""
    以下是一段YouTube直播视频的语音转录文本。
    该金融博主在开播之前可能会放音乐，正式开播后他会关闭音乐，因此转录的前几句话可能会出现乱码。
    文本可能包含同音字识别错误和断句错误，例如“个股“被识别为“个古“。
    
    你的任务是修复这些转录错误，并严谨记录博主输出的所有信息。
    记得换行，确保文本有足够的可读性。
    
    原始文本：
    {text[:30000]}
    (如果文本过长已截断)
    """
    
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个专业的文字编辑，擅长将口语转录文本整理为高质量的书面文章。"},
                {"role": "user", "content": rewrite_prompt},
            ],
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek API (重写阶段) 调用失败: {e}")
        return None

def summarize_text(text: str, api_key: str) -> Optional[str]:
    """阶段 2: 核心总结"""
    logger.info("正在调用 DeepSeek API 进行核心总结...")
    
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
    
    summary_prompt = f"""
    请基于以下整理好的财经视频文本进行深度分析。
    
    任务：
    1. 核心观点：总结视频的3-5个核心逻辑或观点。
    2. 关键数据：提取所有提到的股票代码、价格预测、具体数据指标。
    3. 多空立场：明确博主对特定资产（美股、个股、加密货币等）是看多、看空还是中立。
    
    整理后的文本：
    {text}
    """
    
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "你是一个专业的金融财经内容分析师。"},
                {"role": "user", "content": summary_prompt},
            ],
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"DeepSeek API (总结阶段) 调用失败: {e}")
        return None

def clean_old_cache(days: int):
    """清理过期的缓存文件"""
    logger.info("正在清理过期缓存...")
    cutoff_time = time.time() - (days * 86400)
    
    # 遍历 cache 目录下的 json 文件
    cache_files = glob.glob(os.path.join(CACHE_DIR, "*.json"))
    for file_path in cache_files:
        # 检查文件修改时间
        if os.path.getmtime(file_path) < cutoff_time:
            try:
                os.remove(file_path)
                logger.info(f"已删除过期缓存: {file_path}")
            except OSError as e:
                logger.error(f"删除文件失败 {file_path}: {e}")

def main():
    init_directories()
    
    # 1. 加载 Key
    try:
        api_key = load_api_key(DEEPSEEK_TOKEN_PATH)
    except Exception:
        logger.error("无法启动：缺少 API Key")
        return

    # 2. 获取视频列表
    videos = get_video_list(CHANNEL_URL, DAYS_TO_MONITOR)
    
    # 3. 处理每个视频
    for video in videos:
        video_id = video['id']
        video_dir = os.path.join(CACHE_DIR, video_id)
        if not os.path.exists(video_dir):
            os.makedirs(video_dir)

        # 标记文件：如果 summary.txt 存在，说明整个流程已完成
        summary_path = os.path.join(video_dir, "summary.txt")
        if os.path.exists(summary_path):
            logger.info(f"视频 {video['title']} 已存在最终分析结果，跳过。")
            continue
            
        logger.info(f"开始处理视频: {video['title']}")
        
        # --------------------------
        # Step 1: 获取或读取原始文本 (prime.txt)
        # --------------------------
        prime_path = os.path.join(video_dir, "prime.txt")
        transcript = None
        
        if os.path.exists(prime_path):
            logger.info(f"发现已存原始文本: {prime_path}")
            with open(prime_path, 'r', encoding='utf-8') as f:
                transcript = f.read()
        else:
            # 传入 video_dir 用于保存音频
            transcript = get_transcript(video_id, video['url'], video_dir)
            if transcript:
                with open(prime_path, 'w', encoding='utf-8') as f:
                    f.write(transcript)
            else:
                logger.warning(f"无法获取视频文本: {video['title']}，跳过分析。")
                continue

        # --------------------------
        # Step 2: 重写文本 (refine.txt)
        # --------------------------
        refine_path = os.path.join(video_dir, "refine.txt")
        rewritten_text = None
        
        if os.path.exists(refine_path):
             logger.info(f"发现已重写文本: {refine_path}")
             with open(refine_path, 'r', encoding='utf-8') as f:
                 rewritten_text = f.read()
        else:
            rewritten_text = rewrite_text(transcript, api_key)
            if rewritten_text:
                with open(refine_path, 'w', encoding='utf-8') as f:
                    f.write(rewritten_text)
            else:
                logger.error(f"重写文本失败: {video['title']}")
                continue

        # --------------------------
        # Step 3: 总结分析 (summary.txt)
        # --------------------------
        # 注意：我们已经检查过 summary_path 是否存在，能走到这里说明不存在
        summary_text = summarize_text(rewritten_text, api_key)
        
        if summary_text:
            with open(summary_path, 'w', encoding='utf-8') as f:
                f.write(summary_text)
                
            # 保存元数据 json (最后一步)
            json_path = os.path.join(video_dir, f"{video_id}.json")
            result_data = {
                "id": video_id,
                "title": video['title'],
                "url": video['url'],
                "upload_date": video['upload_date'],
                "scraped_at": datetime.datetime.now().isoformat(),
            }
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2)
                
            logger.info(f"视频分析完成并保存: {video['title']}")
        else:
            logger.error(f"总结分析失败: {video['title']}")
        
        # 避免请求过快
        time.sleep(2)

    # 4. 清理过期缓存
    clean_old_cache(DAYS_TO_MONITOR)
    logger.info("任务完成。")

if __name__ == "__main__":
    main()
