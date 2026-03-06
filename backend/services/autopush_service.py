import threading
import subprocess
import time
import socket
import logging
from typing import Optional, Callable, Tuple

logger = logging.getLogger("AutoPushService")


class AutoPushService:
    def __init__(self):
        self._lock = threading.Lock()
        self.push_thread: Optional[threading.Thread] = None
        self.ffmpeg_process: Optional[subprocess.Popen] = None
        self._is_pushing = False
        self.stopbyuser = False

    def start_push(self, video_path: str, stream_url: str, stream_key: str, callback: Optional[Callable[[bool, str], None]] = None) -> Tuple[bool, str]:
        with self._lock:
            if self._is_pushing:
                return False, "已有推流任务正在运行"
            if not video_path:
                return False, "视频路径不能为空"

            self.push_thread = threading.Thread(target=self._push_worker, args=(video_path, stream_url, stream_key, callback), daemon=True)
            self._is_pushing = True
            self.stopbyuser = False
            self.push_thread.start()
            return True, "推流线程已启动"

    def _push_worker(self, video_path: str, stream_url: str, stream_key: str, callback: Optional[Callable[[bool, str], None]]):
        start_time = time.time()
        MAX_DURATION = 90 * 60
        max_retries = 10
        retry_count = 0
        success = False
        final_message = ""

        try:
            while True:
                if self.stopbyuser:
                    final_message = "用户主动停止推流"
                    break

                if time.time() - start_time >= MAX_DURATION:
                    final_message = "达到最大推流时长限制（90分钟），自动停止"
                    break

                if retry_count > 0:
                    wait_sec = min(10 * retry_count, 60)
                    for _ in range(wait_sec):
                        if self.stopbyuser or (time.time() - start_time) >= MAX_DURATION:
                            break
                        time.sleep(1)

                    try:
                        with socket.create_connection(("live-push.bilivideo.com", 1935), timeout=5):
                            pass
                    except Exception:
                        logger.warning("网络不可达，跳过本次重试")
                        retry_count += 1
                        if retry_count >= max_retries:
                            final_message = "网络不可达，达到最大重试次数"
                            break
                        continue

                logger.info(f"启动推流（尝试 #{retry_count + 1}）")
                success, stderr_or_msg = self._execute_ffmpeg_push(video_path, stream_url, stream_key)
                logger.info(f"_execute_ffmpeg_push status : {stderr_or_msg}")

                if success:
                    final_message = "推流正常完成"
                    break

                returncode = self.ffmpeg_process.returncode if self.ffmpeg_process else -1
                is_recoverable = (
                    returncode in (146, 152) or
                    any(kw in (stderr_or_msg or "").lower() for kw in [
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

                retry_count += 1
                if retry_count >= max_retries:
                    final_message = f"达到最大重试次数（{max_retries}），停止推流"
                    break

        except Exception as e:
            final_message = f"推流线程异常: {str(e)}"
            success = False
            logger.exception(final_message)
        finally:
            with self._lock:
                self._is_pushing = False
                self.ffmpeg_process = None

            if callback:
                try:
                    callback(success, final_message)
                except Exception:
                    logger.exception("回调函数执行失败")

    def _execute_ffmpeg_push(self, video_path: str, stream_url: str, stream_key: str) -> Tuple[bool, str]:
        cmd = [
            'ffmpeg', '-re', '-i', video_path,
            '-c:a', 'aac', '-b:a', '192k', '-ar', '48000',
            '-c:v', 'libx264', '-b:v', '4000k', '-preset', 'veryfast',
            '-fps_mode', 'vfr', '-tune', 'zerolatency', '-g', '20',
            '-crf', '28', '-pix_fmt', 'yuv420p', '-s', '1920x1080',
            '-f', 'flv', '-rw_timeout', '20000000', f"{stream_url}{stream_key}"
        ]
        try:
            self.ffmpeg_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            stdout, stderr = self.ffmpeg_process.communicate()
            if self.ffmpeg_process.returncode == 0:
                return True, "推流正常结束"
            return False, stderr
        except FileNotFoundError:
            return False, "未找到ffmpeg，请确保已安装并添加到系统环境变量"
        except Exception as e:
            return False, str(e)

    def stop_push(self) -> Tuple[bool, str]:
        self.stopbyuser = True
        with self._lock:
            if not self._is_pushing:
                return False, "没有正在运行的推流任务"
            try:
                if self.ffmpeg_process:
                    pid = self.ffmpeg_process.pid
                    self.ffmpeg_process.terminate()
                    for _ in range(5):
                        if self.ffmpeg_process.poll() is not None:
                            return True, f"推流已成功停止 (PID: {pid})"
                        time.sleep(1)
                    self.ffmpeg_process.kill()
                    return True, f"推流已强制停止 (PID: {pid})"
                return False, "未找到正在运行的 ffmpeg 进程"
            except Exception as e:
                return False, f"停止推流失败: {str(e)}"

    def is_pushing(self) -> bool:
        with self._lock:
            return self._is_pushing
