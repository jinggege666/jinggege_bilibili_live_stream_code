import json
import random
import subprocess
import logging
import threading
import time
import socket
from typing import Tuple, Callable, Optional
import psutil

cookies_file = 'cookies.txt'
last_settings_file = 'last_settings.json'
video_path_file = 'video_path.json'

class AutoPushStream:
    def __init__(self):
        self.video_paths = ""
        self.push_thread: Optional[threading.Thread] = None
        self.ffmpeg_process: Optional[subprocess.Popen] = None
        self.is_pushing = False
        self.stopbyuser = False
        self._lock = threading.Lock()
    
    def load_video_paths(self):
        try:
            with open(video_path_file, 'r', encoding='utf-8') as f:
                self.video_paths = json.load(f)
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
            paths = self.video_paths.get(sub_area)
            if not paths:
                raise ValueError(f"未找到{sub_area}对应的视频路径")
            return random.choice(paths)
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件{last_settings_file}不存在")
        except json.JSONDecodeError:
            raise ValueError(f"配置文件{last_settings_file}格式错误")
        except Exception as e:
            raise Exception(f"获取随机视频路径失败: {str(e)}")

    def start_push(self, video_path: str, stream_url: str, stream_key: str, callback: Callable[[bool, str], None]) -> bool:
        with self._lock:
            if self.is_pushing:
                print("已有推流任务正在运行，无法启动新任务")
                return False
            if not video_path:
                print("视频路径不能为空")
                return False

            self.push_thread = threading.Thread(
                target=self._push_worker,
                args=(video_path, stream_url, stream_key, callback),
                name="StreamWorker",
                daemon=True
            )
            self.is_pushing = True
            self.stopbyuser = False
            self.push_thread.start()
            print(f"推流线程已启动，视频路径: {video_path}")
            return True

    def _push_worker(self, video_path: str, stream_url: str, stream_key: str, callback: Callable[[bool, str], None]) -> None:
        """带自动重试 + 90分钟总时长限制的推流工作线程"""
        start_time = time.time()
        MAX_DURATION = 90 * 60  # 90分钟（秒）
        max_retries = 10
        retry_count = 0

        success = False
        final_message = ""

        try:
            while True:
                # 检查用户是否手动停止
                if self.stopbyuser:
                    final_message = "用户主动停止推流"
                    break

                # 检查总时长是否超限
                if time.time() - start_time >= MAX_DURATION:
                    final_message = "达到最大推流时长限制（90分钟），自动停止"
                    break

                # 非首次尝试：等待 + 网络检测
                if retry_count > 0:
                    wait_sec = min(10 * retry_count, 60)  # 退避重试
                    print(f"第 {retry_count} 次重试，等待 {wait_sec} 秒...")
                    for _ in range(wait_sec):
                        if self.stopbyuser or (time.time() - start_time) >= MAX_DURATION:
                            break
                        time.sleep(1)
                    
                    # 检查 B站推流服务器是否可达
                    try:
                        with socket.create_connection(("live-push.bilivideo.com", 1935), timeout=5):
                            pass
                    except (OSError, socket.timeout):
                        print("网络不可达，跳过本次重试")
                        continue

                # 执行一次推流
                print(f"启动推流（尝试 #{retry_count + 1}）")
                success, stderr_or_msg = self._execute_ffmpeg_push(video_path, stream_url, stream_key)
                print(f"_execute_ffmpeg_push status : {stderr_or_msg}")

                # 成功则退出
                if success:
                    final_message = "推流正常完成"
                    break

                # 判断是否为可恢复的临时网络错误
                returncode = self.ffmpeg_process.returncode if self.ffmpeg_process else -1
                is_recoverable = (
                    returncode in (146, 152) or
                    any(kw in stderr_or_msg.lower() for kw in [
                        "connection timed out",
                        "connection reset by peer",
                        "broken pipe",
                        "no route to host",
                        "network is unreachable",
                        "operation timed out"
                    ])
                )

                if not is_recoverable:
                    final_message = f"不可恢复错误，停止重试: {stderr_or_msg}"
                    break

                # 可恢复，准备重试
                retry_count += 1
                if retry_count >= max_retries:
                    final_message = f"达到最大重试次数（{max_retries}），停止推流"
                    break

        except Exception as e:
            final_message = f"推流线程异常: {str(e)}"
            success = False
            print(final_message, exc_info=True)
        finally:
            with self._lock:
                self.is_pushing = False
                self.ffmpeg_process = None

            if not self.stopbyuser:
                try:
                    callback(success, final_message)
                except Exception as e:
                    print(f"回调函数执行失败: {str(e)}", exc_info=True)

    def _execute_ffmpeg_push(self, video_path: str, stream_url: str, stream_key: str) -> Tuple[bool, str]:
        cmd = [
            'ffmpeg',
            '-re',
            '-i', video_path,
            '-c:a', 'aac',
            '-b:a', '192k',
            '-ar', '48000',
            '-c:v', 'libx264',
            '-b:v', '4000k',
            '-preset', 'veryfast',
            '-fps_mode', 'vfr',
            '-tune', 'zerolatency',
            '-g', '20',
            '-crf', '28',
            '-pix_fmt', 'yuv420p',
            '-s', '1920x1080',
            '-f', 'flv',
            '-rw_timeout', '20000000',  # 20秒超时
            f"{stream_url}{stream_key}"
        ]
        try:
            self.ffmpeg_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = self.ffmpeg_process.communicate()

            if self.ffmpeg_process.returncode == 0:
                return True, "推流正常结束"
            else:
                return False, stderr  # 返回原始 stderr 用于判断

        except FileNotFoundError:
            return False, "未找到ffmpeg，请确保已安装并添加到系统环境变量"
        except Exception as e:
            return False, str(e)

    def stop_push(self) -> Tuple[bool, str]:
        self.stopbyuser = True
        with self._lock:
            if not self.is_pushing:
                return False, "没有正在运行的推流任务"
            try:
                if self.ffmpeg_process:
                    self.ffmpeg_process.terminate()
                    for _ in range(5):
                        if self.ffmpeg_process.poll() is not None:
                            return True, f"推流已成功停止 (PID: {self.ffmpeg_process.pid})"
                        time.sleep(1)
                    self.ffmpeg_process.kill()
                    return True, f"推流已强制停止 (PID: {self.ffmpeg_process.pid})"
                else:
                    current_pid = psutil.Process().pid
                    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                        if proc.info['pid'] == current_pid:
                            continue
                        cmdline = ' '.join(proc.info['cmdline'] or [])
                        if "ffmpeg" in proc.info['name'].lower() and stream_key in cmdline:
                            proc.terminate()
                            return True, f"推流进程已停止 (PID: {proc.info['pid']})"
                    return False, "未找到相关的ffmpeg推流进程"
            except Exception as e:
                return False, f"停止推流失败: {str(e)}"

    def is_pushing(self) -> bool:
        with self._lock:
            return self.is_pushing