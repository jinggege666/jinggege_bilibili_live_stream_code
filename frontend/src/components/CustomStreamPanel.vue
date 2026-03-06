<!-- frontend/src/components/CustomStreamPanel.vue -->
<script setup>
import { ref, reactive, inject, onMounted, watch } from 'vue';
import { useBridge } from '@/api/bridge';

// props liveState is used in template and logic


const showModal = inject('showModal');
const bridge = useBridge();
const emit = defineEmits(['stream-start', 'stream-stop']);

const props = defineProps(['liveState']);

const form = reactive({
  rtmpUrl: '',
  streamKey: ''
});

const isStreaming = ref(false);
const loading = ref(false);
const mode = ref('bili'); // 默认方式1
const videoPath = ref('');
const autopushRunning = ref(false);
const autopushLoading = ref(false);

const toggleStream = async () => {
  if (autopushRunning.value) {
    await stopAutopush();
  } else {
    await startAutopushManual();
  }
};

const copyFullUrl = async () => {
  if (!form.rtmpUrl || !form.streamKey) {
    return showModal('提示', '请先填写地址和密钥', 'info');
  }
  const full = `${form.rtmpUrl}${form.streamKey}`;
  await navigator.clipboard.writeText(full);
  showModal('成功', '完整推流地址已复制到剪贴板', 'success');
};

// 监听后端自动推流完成事件
onMounted(() => {
  try {
    window.onAutoPushFinished = async (data) => {
      try {
        autopushRunning.value = false;
        // 通知用户完成状态（不显示具体消息）
        showModal('自动推流完成', success ? '推流成功' : '推流失败', success ? 'success' : 'error');
        // 推流结束后尝试关闭直播（无论方式1还是2），不弹窗
        try {
          await bridge.toggleLive(false);
          emit('stream-stop');
        } catch (e) {
          console.error('关闭直播失败', e);
        }
      } catch (e) {
        console.error(e);
      }
    };
  } catch (e) {
    console.warn('无法注册 onAutoPushFinished', e);
  }

  // 如果已经有直播状态，则填充地址
  if (props.liveState && props.liveState.isLive) {
    const r1 = props.liveState.rtmp1 || {};
    form.rtmpUrl = r1.addr || '';
    form.streamKey = r1.code || '';
  }
});

// 监听 liveState 变化以自动填充
watch(
  () => props.liveState,
  (ns) => {
    if (mode.value === 'bili' && ns && ns.isLive) {
      const r1 = ns.rtmp1 || {};
      form.rtmpUrl = r1.addr || '';
      form.streamKey = r1.code || '';
    }
  },
  { deep: true }
);

const onSelectFile = async () => {
  try {
    const res = await bridge.openFileDialog();
    if (res && res.path) {
      videoPath.value = res.path;
    } else {
      showModal('提示', '未选择文件', 'info');
    }
  } catch (e) {
    console.error(e);
    showModal('异常', '文件对话出错：' + e.message, 'error');
  }
};

// helper for the custom bili button action
const biliButtonAction = async () => {
  if (!props.liveState.isLive) {
    // not streaming yet, show hint to start live
    showModal('提示', '请先在直播界面开始直播', 'info');
    return;
  }

  if (autopushRunning.value) {
    await stopAutopush();
    // also stop live
    try {
      await bridge.toggleLive(false);
      emit('stream-stop');
    } catch (e) {
      console.error('停止直播失败', e);
    }
  } else {
    await startAutopushBili();
  }
};

const startAutopushManual = async () => {
  if (!videoPath.value) return showModal('错误', '请先选择或填写本地视频路径', 'error');
  if (!form.rtmpUrl.trim() || !form.streamKey.trim()) return showModal('错误', '请填写完整的 RTMP 地址和推流密钥', 'error');

  autopushLoading.value = true;
  try {
    const res = await bridge.startAutopush(videoPath.value, form.rtmpUrl, form.streamKey);
    if (res.success) {
      autopushRunning.value = true;
      showModal('开始推流', '自动推流已启动，后台将使用 ffmpeg 推送视频', 'success');
    } else {
      showModal('错误', '启动失败：' + (res.msg || '未知错误'), 'error');
    }
  } catch (e) {
    console.error(e);
    showModal('异常', e.message || '启动出错', 'error');
  } finally {
    autopushLoading.value = false;
  }
};

const startAutopushBili = async () => {
  if (!videoPath.value) return showModal('错误', '请先选择或填写本地视频路径', 'error');
  if (!props.liveState || !props.liveState.isLive) {
    return showModal('提示', '请先在直播界面开始直播', 'info');
  }

  autopushLoading.value = true;
  try {
    // 使用当前 liveState 中的推流地址
    const data = props.liveState;
    const rtmp1 = data.rtmp1 || {};
    let addr = rtmp1.addr || (data.rtmp && data.rtmp.addr) || '';
    let key = rtmp1.code || (data.rtmp && data.rtmp.code) || '';
    if ((!addr || !key) && Array.isArray(data.protocols)) {
      for (const p of data.protocols) {
        if (p.protocol === 'rtmp' && p.addr && p.code) {
          addr = p.addr; key = p.code; break;
        }
      }
    }

    form.rtmpUrl = addr;
    form.streamKey = key;

    if (!addr || !key) {
      showModal('错误', '未能从 liveState 获取到有效推流地址', 'error');
      return;
    }

    const startRes = await bridge.startAutopush(videoPath.value, addr, key);
    if (startRes.success) {
      autopushRunning.value = true;
      showModal('开始推流', '已开始使用本工具分配的推流地址进行自动推流', 'success');
    } else {
      showModal('错误', '启动失败：' + (startRes.msg || '未知错误'), 'error');
    }
  } catch (e) {
    console.error(e);
    showModal('异常', e.message || '启动出错', 'error');
  } finally {
    autopushLoading.value = false;
  }
};

const stopAutopush = async () => {
  try {
    const res = await bridge.stopAutopush();
    autopushRunning.value = false;
    if (!res || res.code !== 0) {
      console.error('Stop failed:', res?.msg);
    }
  } catch (e) {
    console.error(e);
  } finally {
    // 停止推流后尝试关闭直播（无论方式1还是2）
    try {
      await bridge.toggleLive(false);
      emit('stream-stop');
    } catch (e) {
      console.error('关闭直播失败', e);
    }
  }
};
</script>

<template>
  <div class="panel fade-in">
    <div class="header-section">
      <h2 class="title">FFmpeg 推流</h2>
      <p class="subtitle">使用本地 ffmpeg 推流工具，支持两种推流模式</p>
    </div>

    <div class="card config-card">
      <div style="display:flex; gap:12px; align-items:center; margin-bottom:12px;">
        <label><input type="radio" v-model="mode" value="bili" /> 本工具开播并推流</label>
        <label><input type="radio" v-model="mode" value="manual" /> 直播姬推流</label>
      </div>
      <div class="input-group">
        <label class="label">RTMP 推流地址</label>
        <input
          v-model="form.rtmpUrl"
          class="gemini-input"
          placeholder="例如：rtmp://live-push.bilibili.com/live-bvc/"
        />
      </div>

      <div class="input-group" style="margin-top: 20px;">
        <label class="label">推流密钥（Stream Key）</label>
        <input
          v-model="form.streamKey"
          class="gemini-input"
          placeholder="你的推流码"
          type="password"
        />
      </div>

      <div class="input-group" style="margin-top: 12px;">
        <label class="label">本地视频路径</label>
        <div class="row" style="gap:8px; align-items:center;">
          <input
            class="gemini-input"
            readonly
            :value="videoPath"
            placeholder="点击选择视频文件"
            style="flex:1;"
          />
          <button class="btn btn-secondary" @click="onSelectFile">选择文件</button>
        </div>
      </div>

      <div class="action-section" style="margin-top: 28px;">
        <template v-if="mode === 'manual'">
          <button
            class="btn"
            :class="autopushRunning ? 'btn-stop' : 'btn-start'"
            @click="toggleStream"
            :disabled="loading"
            style="width: 100%; max-width: 240px; height: 48px; font-size: 16px;"
          >
            <span v-if="loading" class="loader"></span>
            <template v-else>
              <span class="icon">{{ autopushRunning ? '⏹' : '▶' }}</span>
              {{ autopushRunning ? '停止推流' : '开始推流' }}
            </template>
          </button>
          <p class="hint" style="margin-top: 12px;">
            <span class="info-icon">i</span> 启动后，后台将使用 ffmpeg 推送视频到填写的 RTMP 地址
          </p>
        </template>

        <template v-else>
          <button
            class="btn"
            :class="!props.liveState.isLive ? 'btn-start' : autopushRunning ? 'btn-stop' : 'btn-start'"
            @click="biliButtonAction"
            :disabled="autopushLoading"
            style="width: 100%; max-width: 240px; height: 48px; font-size: 16px;"
          >
            <span v-if="autopushLoading" class="loader"></span>
            <template v-else>
              <span class="icon">{{
                !props.liveState.isLive ? '🔴' : autopushRunning ? '⏹' : '⏯'
              }}</span>
              {{ !props.liveState.isLive ? '去开启直播' : autopushRunning ? '停止推流' : '开始推流' }}
            </template>
          </button>
          <p class="hint" style="margin-top: 12px;" v-if="props.liveState.isLive">
            <span class="info-icon">i</span> 如果未开播，会自动跳转到直播界面进行开始直播操作
          </p>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.panel {
  max-width: 560px;
  margin: 0 auto;
}

.header-section {
  margin-bottom: 24px;
}

.title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text-main);
  margin: 0 0 4px 0;
}

.subtitle {
  font-size: 14px;
  color: var(--text-sub);
  margin: 0;
}

.config-card {
  padding: 24px;
  border: 1px solid #e0e3e7;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.input-group {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-sub);
  margin-left: 4px;
}

.row {
  display: flex;
  gap: 12px;
  align-items: center;
}

.action-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.btn-start {
  background-color: #669DF6;
  box-shadow: 0 4px 14px rgba(102, 157, 246, 0.3);
}

.btn-start:hover {
  background-color: #5189E0;
  transform: translateY(-1px);
}

.btn-stop {
  background-color: #F28B82;
  box-shadow: 0 4px 14px rgba(242, 139, 130, 0.3);
}

.btn-stop:hover {
  background-color: #EE675C;
  transform: translateY(-1px);
}

.icon {
  font-size: 18px;
}

.hint {
  font-size: 12px;
  color: var(--text-sub);
  display: flex;
  align-items: center;
  gap: 6px;
}

.info-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border: 1px solid currentColor;
  border-radius: 50%;
  font-size: 10px;
  font-style: normal;
}

.loader {
  width: 20px;
  height: 20px;
  border: 3px solid rgba(255,255,255,0.3);
  border-radius: 50%;
  border-top-color: #fff;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>