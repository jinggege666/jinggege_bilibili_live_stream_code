import logging
import asyncio
import threading
import requests
import json
from backend.bilibili_api import BilibiliApi
from backend.config import Config
from backend.state import SessionState
from backend.services.window_service import WindowService
from backend.services.user_service import UserService
from backend.services.live_service import LiveService
from backend.services.auth_service import AuthService
from backend.services.danmu_service import DanmuService
from backend.services.autopush_service import AutoPushService
from backend.get_wbi import get_w_rid_and_wts

logger = logging.getLogger("ApiService")

class FrontendLogHandler(logging.Handler):
    """自定义日志处理器，将日志发送到前端"""
    def __init__(self, window_service):
        super().__init__()
        self.window_service = window_service

    def emit(self, record):
        try:
            msg = self.format(record)
            # 避免在主线程阻塞或死循环，这里简单直接调用
            # 注意：如果日志量巨大，可能需要缓冲或限流
            self.window_service.send_to_frontend("onBackendLog", msg)
        except Exception:
            self.handleError(record)

class ApiService:
    def __init__(self):
        self.api_client = BilibiliApi()
        self.config_manager = Config()
        self.session_state = SessionState()
        # 自定义第三方推流地址（仅内存保存，供前端显示/复制）
        self.custom_stream_url = None
        
        # Initialize services
        self.window_service = WindowService()
        self.user_service = UserService(self.api_client, self.config_manager, self.session_state)
        self.live_service = LiveService(self.api_client, self.config_manager, self.session_state)
        self.auth_service = AuthService(self.api_client, self.user_service, self.live_service, self.session_state)
        self.danmu_service = DanmuService(self.api_client, self.session_state)
        # 自动推流服务
        self.autopush_service = AutoPushService()
        
        # 设置弹幕回调
        self.danmu_service.set_callback(self._on_danmu_message)
        # self.danmu_service.set_log_callback(self._on_backend_log) # 不再需要单独的回调，统一走 logging
        
        # 配置日志转发到前端
        self._setup_logging()

        # Initial setup
        self.user_service.init_current_user()
        
        # Asyncio loop for danmu
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._start_loop, args=(self.loop,), daemon=True)
        self.loop_thread.start()

    def _setup_logging(self):
        """配置日志处理器，将 INFO 及以上级别的日志转发到前端"""
        root_logger = logging.getLogger()
        frontend_handler = FrontendLogHandler(self.window_service)
        frontend_handler.setLevel(logging.INFO) # 只转发 INFO 及以上
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        frontend_handler.setFormatter(formatter)
        root_logger.addHandler(frontend_handler)

    def _start_loop(self, loop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _on_danmu_message(self, data):
        """处理弹幕消息回调，推送到前端"""
        # 注意：这里可能在子线程中被调用，webview 的 evaluate_js 应该是线程安全的
        # 前端挂载的函数名为 onDanmuMessage
        self.window_service.send_to_frontend("onDanmuMessage", data)

    # def _on_backend_log(self, msg):
    #     """处理后端日志回调，推送到前端"""
    #     self.window_service.send_to_frontend("onBackendLog", msg)

    # --- Window Proxy Methods ---
    def window_min(self): return self.window_service.window_min()
    def window_max(self): return self.window_service.window_max()
    def window_close(self): 
        # 只有在直播状态下才尝试停止直播
        if self.session_state.is_live:
            self.live_service.stop_live()

        asyncio.run_coroutine_threadsafe(self.danmu_service.stop(), self.loop)
        return self.window_service.window_close(lambda: self.config_manager.save())
    def get_window_position(self): return self.window_service.get_window_position()
    def window_drag(self, target_x, target_y): return self.window_service.window_drag(target_x, target_y)

    # --- User Proxy Methods ---
    def load_saved_config(self): return self.user_service.load_saved_config()
    def refresh_current_user(self): return self.user_service.refresh_current_user()
    def get_account_list(self): return self.user_service.get_account_list()
    def switch_account(self, uid): return self.user_service.switch_account(uid)
    def logout(self, uid): return self.user_service.logout(uid)

    # --- Auth Proxy Methods ---
    def get_login_qrcode(self): return self.auth_service.get_login_qrcode()
    def poll_login_status(self, key): return self.auth_service.poll_login_status(key)

    # --- Live Proxy Methods ---
    def get_partitions(self): return self.live_service.get_partitions()
    def update_title(self, title): return self.live_service.update_title(title)
    def update_area(self, p_name, s_name): return self.live_service.update_area(p_name, s_name)
    def start_live(self, p_name=None, s_name=None): 
        res = self.live_service.start_live(p_name, s_name)
        # if res['code'] == 0:
        #      # 开启直播成功后，连接弹幕
        #      room_id = self.session_state.room_id
        #      if room_id:
        #          asyncio.run_coroutine_threadsafe(self.danmu_service.connect(room_id), self.loop)
        return res
        
    def stop_live(self): 
        res = self.live_service.stop_live()
        if res['code'] == 0:
            asyncio.run_coroutine_threadsafe(self.danmu_service.stop(), self.loop)
        return res

    # --- Danmu Methods ---
    def start_danmu_monitor(self):
        """手动开启弹幕监听（用于测试或非开播状态）"""
        room_id = self.session_state.room_id
        if not room_id:
             return {"code": -1, "msg": "未获取到房间ID"}
        asyncio.run_coroutine_threadsafe(self.danmu_service.connect(room_id), self.loop)
        return {"code": 0}

    def stop_danmu_monitor(self):
        asyncio.run_coroutine_threadsafe(self.danmu_service.stop(), self.loop)
        return {"code": 0}

    def send_danmu(self, msg):
        """发送弹幕"""
        return self.danmu_service.send_danmu(msg)

    # --- App Config Methods ---
    def get_app_config(self):
        import sys
        # 使用实际托盘运行状态（由 main.py 设置）
        has_tray = getattr(self, 'tray_active', False)
        config = {
            "min_to_tray": self.config_manager.data.get("min_to_tray", True),
            "is_win32": sys.platform == 'win32',
            "has_tray": has_tray
        }
        return {"code": 0, "data": config}

    def set_app_config(self, key, value):
        if key == "min_to_tray":
            self.config_manager.data["min_to_tray"] = bool(value)
            self.config_manager.save()
            return {"code": 0}
        return {"code": -1, "msg": "Unknown config key"}


    # --- File Dialog ---
    def open_file_dialog(self):
        """打开原生文件对话，返回选择的视频文件路径。
        会记住上一次选择的目录，并在下次打开时作为初始目录。"""
        try:
            import os
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()  # 隐藏主窗口
            options = {
                "title": "选择视频文件",
                "filetypes": [("视频文件", "*.mp4 *.avi *.mkv *.mov *.flv"), ("所有文件", "*.*")]
            }
            if hasattr(self, 'last_file_dir') and self.last_file_dir:
                options['initialdir'] = self.last_file_dir
            file_path = filedialog.askopenfilename(**options)
            root.destroy()
            if file_path:
                # 保存目录
                self.last_file_dir = os.path.dirname(file_path)
                return {"code": 0, "data": {"path": file_path}}
            return {"code": -1, "msg": "未选择文件"}
        except ImportError:
            return {"code": -1, "msg": "tkinter 不可用"}
        except Exception as e:
            return {"code": -1, "msg": str(e)}

    # --- Auto Push (ffmpeg based automated push) ---
    def start_autopush(self, video_path, stream_url, stream_key):
        """启动基于 ffmpeg 的自动推流。"""
        try:
            def cb(success, msg):
                try:
                    self.window_service.send_to_frontend('onAutoPushFinished', {'success': success, 'msg': msg})
                except Exception:
                    logger.exception('Failed to send autopush finished event')

            ok, msg = self.autopush_service.start_push(video_path, stream_url, stream_key, callback=cb)
            if ok:
                return {"code": 0, "msg": msg}
            return {"code": -1, "msg": msg}
        except Exception as e:
            logger.error(f"start_autopush failed: {e}")
            return {"code": -1, "msg": str(e)}

    def stop_autopush(self):
        try:
            ok, msg = self.autopush_service.stop_push()
            return {"code": 0 if ok else -1, "msg": msg}
        except Exception as e:
            logger.error(f"stop_autopush failed: {e}")
            return {"code": -1, "msg": str(e)}

    def autopush_status(self):
        try:
            return {"code": 0, "data": {"is_pushing": bool(self.autopush_service.is_pushing())}}
        except Exception as e:
            logger.error(f"autopush_status failed: {e}")
            return {"code": -1, "msg": str(e)}

    def get_redeem_info(self, task_id):
        """获取兑换码信息"""
        try:
            if not task_id or not task_id.strip():
                return {"code": -1, "msg": "Task ID 不能为空"}
            
            # 获取当前用户的 Cookie
            uid = self.config_manager.data.get("current_uid")
            if not uid:
                return {"code": -1, "msg": "用户未登录，请先登录"}
            
            uid = str(uid)
            user_data = self.config_manager.data.get("users", {}).get(uid, {})
            cookie = user_data.get('cookie', '')
            
            if not cookie:
                return {"code": -1, "msg": "用户 Cookie 无效，请重新登录"}
            
            # 准备请求参数
            params = {
                "task_id": task_id.strip(),
                "web_location": "888.126558"
            }
            
            # 获取 w_rid 和 wts
            signed_params, query_string = get_w_rid_and_wts(params)
            
            # 构建请求 URL
            url = f"https://api.bilibili.com/x/activity_components/mission/info?{query_string}"
            
            # 准备请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
                'Referer': f'https://www.bilibili.com/blackboard/era/award-exchange.html?task_id={task_id.strip()}',
                'Cookie': cookie,
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            }
            
            # 发送请求
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # 解析响应
            data = response.json()
            
            if data.get('code') != 0:
                return {
                    "code": -1, 
                    "msg": data.get('message', '获取兑换码信息失败')
                }
            
            # 提取兑换码信息
            mission_data = data.get('data', {})
            
            # 判断类型（根据 act_name 关键字）
            act_name = mission_data.get('act_name', '')
            if '绝区零' in act_name:
                game_type = 'zzk'  # 绝区零
            elif '星穹铁道' in act_name or '崩坏' in act_name:
                game_type = 'bengtie'  # 崩铁
            else:
                game_type = 'unknown'
            
            # 判断兑换码类型（根据 task_name 关键字）
            task_name = mission_data.get('task_name', '')
            if '直播' in task_name:
                redeem_type = '直播'
            elif '投稿' in task_name:
                redeem_type = '投稿'
            else:
                redeem_type = '其他'
            
            # 根据类型设置默认首发时间（时分）
            # 直播 → 01:00，投稿 → 18:00，其它则空
            if redeem_type == '直播':
                default_time = '01:00'
            elif redeem_type == '投稿':
                default_time = '18:00'
            else:
                default_time = ''
            
            # 提取关键数据
            reward_info = mission_data.get('reward_info', {})
            stock_info = mission_data.get('stock_info', {})
            status = mission_data.get('status', 0)
            message = mission_data.get('message', '')
            
            # 获取库存和剩余数据
            # total_stock 是百分比，total_remain_num/day_remain_num 是真实剩余数
            total_remain = stock_info.get('total_remain_num', 0)
            day_remain = stock_info.get('day_remain_num', 0)
            total_stock_percentage = stock_info.get('total_stock', 0)  # 百分比
            day_stock_percentage = stock_info.get('day_stock', 0)  # 百分比
            
            # 根据 status 和 message 判断库存状态
            # status: 0=正常, 1=库存不足, 2=已售罄
            if '每日库存已达上限' in message or (day_remain == 0 and total_remain > 0):
                stock_status = 'day_limit'  # 今日库存已达上限
            elif '总库存已达上限' in message or (total_remain == 0 and day_remain == 0):
                stock_status = 'total_limit'  # 总库存已达上限/已售罄
            elif status == 2:
                stock_status = 'sold_out'  # 已售罄
            elif status == 1:
                stock_status = 'low'  # 库存不足
            else:
                stock_status = 'available'  # 可用
            
            redeem_data = {
                "act_id": mission_data.get('act_id', ''),
                "act_name": act_name,
                "task_id": mission_data.get('task_id', ''),
                "task_name": mission_data.get('task_name', ''),
                "award_name": reward_info.get('award_name', ''),
                "alias": mission_data.get('task_desc', ''),  # 任务描述/别名
                "type": redeem_type,  # 兑换码类型：直播/投稿/其他
                "first_publish_time": default_time,  # 固定时分
                "first_publish_date": '',  # 用户可选日期
                "status": status,
                "message": message,
                "game_type": game_type,
                # 临时字段，用于前端显示，不保存
                "total_remain": total_remain,
                "day_remain": day_remain,
                "total_stock_percentage": total_stock_percentage,
                "day_stock_percentage": day_stock_percentage,
                "stock_status": stock_status
            }
            
            # 不自动保存，等待手动保存
            return {
                "code": 0,
                "msg": "获取成功",
                "data": redeem_data
            }
        except requests.exceptions.Timeout:
            logger.error(f"get_redeem_info timeout: {task_id}")
            return {"code": -1, "msg": "请求超时，请检查网络连接"}
        except requests.exceptions.RequestException as e:
            logger.error(f"get_redeem_info request failed: {e}")
            return {"code": -1, "msg": f"网络请求失败: {str(e)}"}
        except Exception as e:
            logger.error(f"get_redeem_info failed: {e}")
            return {"code": -1, "msg": f"获取失败: {str(e)}"}
    
    def _save_redeem_info(self, redeem_data, uid):
        """保存兑换码信息到本地"""
        try:
            if "redeem_info" not in self.config_manager.data:
                self.config_manager.data["redeem_info"] = {}
            
            uid = str(uid)
            if uid not in self.config_manager.data["redeem_info"]:
                self.config_manager.data["redeem_info"][uid] = []
            
            # 检查是否已存在（根据 task_id）
            existing_list = self.config_manager.data["redeem_info"][uid]
            found = False
            for item in existing_list:
                if item.get("task_id") == redeem_data.get("task_id"):
                    # 更新现有记录
                    item.update(redeem_data)
                    found = True
                    break
            
            if not found:
                # 添加新记录
                existing_list.append(redeem_data)
            
            self.config_manager.save()
            logger.info(f"Redeem info saved: {redeem_data['task_id']}")
        except Exception as e:
            logger.error(f"Save redeem info failed: {e}")
    
    def get_redeem_history(self):
        """获取本地保存的兑换码历史"""
        try:
            uid = self.config_manager.data.get("current_uid")
            if not uid:
                return {"code": -1, "msg": "用户未登录", "data": []}
            
            uid = str(uid)
            history = self.config_manager.data.get("redeem_info", {}).get(uid, [])
            
            return {
                "code": 0,
                "msg": "获取成功",
                "data": history
            }
        except Exception as e:
            logger.error(f"get_redeem_history failed: {e}")
            return {"code": -1, "msg": f"获取失败: {str(e)}", "data": []}
    
    def save_redeem_info(self, redeem_data):
        """手动保存兑换码信息"""
        try:
            uid = self.config_manager.data.get("current_uid")
            if not uid:
                return {"code": -1, "msg": "用户未登录"}
            
            uid = str(uid)
            
            # 移除临时字段，只保存需要的字段
            clean_data = {
                "act_id": redeem_data.get('act_id', ''),
                "act_name": redeem_data.get('act_name', ''),
                "task_id": redeem_data.get('task_id', ''),
                "task_name": redeem_data.get('task_name', ''),
                "award_name": redeem_data.get('award_name', ''),
                "alias": redeem_data.get('alias', ''),
                "type": redeem_data.get('type', '其他'),  # 兑换码类型
                "first_publish_time": redeem_data.get('first_publish_time', ''),
                "first_publish_date": redeem_data.get('first_publish_date', ''),
                "total_stock": redeem_data.get('total_stock_percentage', 0),  # 保存总库存百分比
                "status": redeem_data.get('status', 0),
                "message": redeem_data.get('message', ''),
                "game_type": redeem_data.get('game_type', '')
            }
            
            if "redeem_info" not in self.config_manager.data:
                self.config_manager.data["redeem_info"] = {}
            
            if uid not in self.config_manager.data["redeem_info"]:
                self.config_manager.data["redeem_info"][uid] = []
            
            # 检查是否已存在（根据 task_id）
            existing_list = self.config_manager.data["redeem_info"][uid]
            found = False
            for item in existing_list:
                if item.get("task_id") == clean_data.get("task_id"):
                    # 更新现有记录
                    item.update(clean_data)
                    found = True
                    break
            
            if not found:
                # 添加新记录
                existing_list.append(clean_data)
            
            self.config_manager.save()
            logger.info(f"Redeem info saved: {clean_data['task_id']}")
            return {"code": 0, "msg": "保存成功"}
        except Exception as e:
            logger.error(f"Save redeem info failed: {e}")
            return {"code": -1, "msg": f"保存失败: {str(e)}"}
    
    def delete_redeem_info(self, task_id):
        """删除兑换码信息"""
        try:
            uid = self.config_manager.data.get("current_uid")
            if not uid:
                return {"code": -1, "msg": "用户未登录"}
            
            uid = str(uid)
            if "redeem_info" not in self.config_manager.data or uid not in self.config_manager.data["redeem_info"]:
                return {"code": -1, "msg": "没有找到兑换记录"}
            
            existing_list = self.config_manager.data["redeem_info"][uid]
            for i, item in enumerate(existing_list):
                if item.get("task_id") == task_id:
                    existing_list.pop(i)
                    self.config_manager.save()
                    logger.info(f"Redeem info deleted: {task_id}")
                    return {"code": 0, "msg": "删除成功"}
            
            return {"code": -1, "msg": "未找到指定的兑换记录"}
        except Exception as e:
            logger.error(f"Delete redeem info failed: {e}")
            return {"code": -1, "msg": f"删除失败: {str(e)}"}
    
    def check_redeem_status(self, task_id):
        """检测兑换码状态"""
        try:
            if not task_id or not task_id.strip():
                return {"code": -1, "msg": "Task ID 不能为空"}
            
            # 获取当前用户的 Cookie
            uid = self.config_manager.data.get("current_uid")
            if not uid:
                return {"code": -1, "msg": "用户未登录，请先登录"}
            
            uid = str(uid)
            user_data = self.config_manager.data.get("users", {}).get(uid, {})
            cookie = user_data.get('cookie', '')
            
            if not cookie:
                return {"code": -1, "msg": "用户 Cookie 无效，请重新登录"}
            
            # 准备请求参数
            params = {
                "task_id": task_id.strip(),
                "web_location": "888.126558"
            }
            
            # 获取 w_rid 和 wts
            signed_params, query_string = get_w_rid_and_wts(params)
            
            # 构建请求 URL
            url = f"https://api.bilibili.com/x/activity_components/mission/info?{query_string}"
            
            # 准备请求头
            headers = {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36',
                'Referer': f'https://www.bilibili.com/blackboard/era/award-exchange.html?task_id={task_id.strip()}',
                'Cookie': cookie,
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Accept-Language': 'zh-CN,zh;q=0.9',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site'
            }
            
            # 发送请求
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # 解析响应
            data = response.json()
            
            if data.get('code') != 0:
                return {
                    "code": -1, 
                    "msg": data.get('message', '检测兑换码状态失败')
                }
            
            # 提取状态信息
            mission_data = data.get('data', {})
            message = mission_data.get('message', '')
            stock_info = mission_data.get('stock_info', {})
            total_stock_percentage = stock_info.get('total_stock', 0)
            
            # 根据参考代码的逻辑判断状态
            if message == "查看奖励":
                status = "claimed"  # 已领取
                status_text = "已领取"
            elif total_stock_percentage == 0:
                status = "gone"  # 彻底没有了
                status_text = "没有了"
            elif message == "领取奖励":
                status = "available"  # 可以领取
                status_text = "可领取"
            else:
                status = "unknown"  # 未知状态
                status_text = f"未知状态: {message}"
            
            return {
                "code": 0,
                "msg": "检测成功",
                "data": {
                    "task_id": task_id.strip(),
                    "status": status,
                    "status_text": status_text,
                    "message": message,
                    "total_stock": total_stock_percentage
                }
            }
        except requests.exceptions.Timeout:
            logger.error(f"check_redeem_status timeout: {task_id}")
            return {"code": -1, "msg": "请求超时，请检查网络连接"}
        except requests.exceptions.RequestException as e:
            logger.error(f"check_redeem_status request failed: {e}")
            return {"code": -1, "msg": f"网络请求失败: {str(e)}"}
        except Exception as e:
            logger.error(f"check_redeem_status failed: {e}")
            return {"code": -1, "msg": f"检测失败: {str(e)}"}
