import json
import random
import subprocess
import logging
import threading
import time
from typing import Tuple, Callable, Optional
import psutil

cookies_file = 'cookies.txt'
last_settings_file = 'last_settings.json'
video_path_file = 'video_path.json'

class AutoPushStream:
    def __init__(self):
        self.video_paths = ""
        # 状态管理
        self.push_thread: Optional[threading.Thread] = None
        self.ffmpeg_process: Optional[subprocess.Popen] = None
        self.is_pushing = False
        self.stopbyuser = False
        self._lock = threading.Lock()
    
    def load_video_paths(self):
        """从video_path.json文件加载视频路径数据"""
        try:
            with open(video_path_file, 'r', encoding='utf-8') as f:
                self.video_paths =  json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"视频路径文件{video_path_file}不存在")
        except json.JSONDecodeError:
            raise ValueError(f"视频路径文件{video_path_file}格式错误")
    
    def getRandomVideoPath(self):
        try:
            with open(last_settings_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
            
            sub_area = settings.get('selected_sub_area')
            if not sub_area:
                raise ValueError("配置文件中未找到selected_sub_area")
            
            # 从加载的视频路径中获取对应分区的路径列表
            paths = self.video_paths.get(sub_area)
            if not paths:
                raise ValueError(f"未找到{sub_area}对应的视频路径")
            # 随机返回一个路径
            return random.choice(paths)
            
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件{last_settings_file}不存在")
        except json.JSONDecodeError:
            raise ValueError(f"配置文件{last_settings_file}格式错误")
        except Exception as e:
            raise Exception(f"获取随机视频路径失败: {str(e)}")


    def start_push(self, video_path: str, stream_url: str,stream_key: str ,callback: Callable[[bool, str], None]) -> bool:
        with self._lock:
            if self.is_pushing:
                print("已有推流任务正在运行，无法启动新任务")
                return False
            if not video_path:
                print("视频路径不能为空")
                return False

            self._push_thread = threading.Thread(
                target=self._push_worker,
                args=(video_path, stream_url,stream_key,callback),
                name="StreamWorker",
                daemon=True
            )
            self.is_pushing = True
            self.stopbyuser = False
            self._push_thread.start()
            print(f"推流线程已启动，视频路径: {video_path}")
            return True

    def _push_worker(self, video_path: str, stream_url: str,stream_key: str,callback: Callable[[bool, str], None]) -> None:
        """推流工作线程，在子线程中执行"""
        success = False
        message = ""
        try:
            # 执行实际推流
            success, message = self._execute_ffmpeg_push(video_path,stream_url,stream_key)
        except Exception as e:
            message = f"推流过程发生异常: {str(e)}"
            print(message, exc_info=True)
        finally:
            # 更新状态（线程安全）
            with self._lock:
                self.is_pushing = False
                self._ffmpeg_process = None
            
            # 调用回调函数传递结果
            try:
                if not self.stopbyuser:
                   callback(success, message)
            except Exception as e:
                print(f"回调函数执行失败: {str(e)}", exc_info=True)
            

    def _execute_ffmpeg_push(self, video_path: str,stream_url: str,stream_key: str) -> Tuple[bool, str]:
        """执行FFmpeg推流命令"""
        # 构建FFmpeg命令
        cmd = [
            'ffmpeg',
            '-re',  # 按实际帧率发送
            '-i', video_path,  # 输入文件
            '-c:a', 'aac',  
            '-b:a', '192k',
            '-ar', '48000',
            '-c:v', 'libx264',
            '-b:v','4000k',
            '-preset','veryfast',
            '-fps_mode','vfr',
            '-tune','zerolatency',
            '-g','20',
            '-crf','28',
            '-pix_fmt','yuv420p',
            '-s','1920x1080',
            '-f', 'flv',
            f"{stream_url}{stream_key}"  # 推流地址
        ]
        try:
            # 启动FFmpeg进程
            self._ffmpeg_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            # 等待进程结束（对于无限循环推流，会阻塞直到被终止）
            stdout, stderr = self._ffmpeg_process.communicate()

            # 检查返回码
            if self._ffmpeg_process.returncode == 0:
                return True, "推流正常结束"
            else:
                return False, f"FFmpeg执行失败 (返回码: {self._ffmpeg_process.returncode}): {stderr}"

        except FileNotFoundError:
            return False, "未找到ffmpeg，请确保已安装并添加到系统环境变量"
        except Exception as e:
            return False, f"FFmpeg推流失败: {str(e)}"

    def stop_push(self) -> Tuple[bool, str]:
        self.stopbyuser = True
        with self._lock:
            if not self.is_pushing:
                return False, "没有正在运行的推流任务"
            try:
                if self._ffmpeg_process:
                    self._ffmpeg_process.terminate()
                    timeout = 5
                    for _ in range(timeout):
                        if self._ffmpeg_process.poll() is not None:
                            return True, f"推流已成功停止 (PID: {self._ffmpeg_process.pid})"
                        time.sleep(1)
                    self._ffmpeg_process.kill()
                    return True, f"推流已强制停止 (PID: {self._ffmpeg_process.pid})"
                else:
                    # 找不到直接关联的进程，尝试通过关键字查找
                    current_pid = psutil.Process().pid
                    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                        if proc.info['pid'] == current_pid:
                            continue
                        if "ffmpeg" in proc.info['name'].lower() and \
                           self.stream_key in ' '.join(proc.info['cmdline'] or []):
                            proc.terminate()
                            return True, f"推流进程已停止 (PID: {proc.info['pid']})"
                    
                    return False, "未找到相关的ffmpeg推流进程"
                    
            except Exception as e:
                return False, f"停止推流失败: {str(e)}"

    def is_pushing(self) -> bool:
        """检查当前是否正在推流"""
        with self._lock:
            return self.is_pushing

    def get_stream_info(self) -> dict:
        """获取当前推流信息"""
        with self._lock:
            return {
                "is_pushing": self.is_pushing,
                "stream_url": self.stream_url,
                "stream_key_masked": self.stream_key[:4] + "*" * (len(self.stream_key) - 4) if self.stream_key else None,
                "ffmpeg_pid": self._ffmpeg_process.pid if self._ffmpeg_process else None
            }


        
# if __name__ == "__main__":
#     aAutoPushStream = AutoPushStream()
#     randompath = aAutoPushStream.getRandomVideoPath()
#     print(randompath)