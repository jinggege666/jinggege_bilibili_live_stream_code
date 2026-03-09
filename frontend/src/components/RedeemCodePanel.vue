<!-- frontend/src/components/RedeemCodePanel.vue -->
<script setup>
import { ref, inject, onMounted } from 'vue';
import { useBridge } from '@/api/bridge';

const showModal = inject('showModal', () => {});
const bridge = useBridge();

const taskId = ref('');
const loading = ref(false);
const redeemList = ref([]);
const redeemInfo = ref(null);
const historyList = ref([]);
const showHistory = ref(false);

// 获取兑换码信息
const fetchRedeemInfo = async () => {
  if (!taskId.value.trim()) {
    return showModal('提示', '请输入 Task ID', 'info');
  }

  loading.value = true;
  try {
    const res = await bridge.getRedeemInfo(taskId.value);
    
    if (res.code === 0) {
      redeemInfo.value = res.data;
      redeemList.value = [res.data];
      showModal('成功', '获取兑换码信息成功，请点击保存按钮保存到历史记录', 'success');
      
      // 清空输入框
      taskId.value = '';
      
      // 不自动重新加载历史记录
    } else {
      showModal('错误', res.msg || '获取失败', 'error');
      redeemList.value = [];
    }
  } catch (e) {
    console.error(e);
    showModal('异常', e.message || '请求出错', 'error');
    redeemList.value = [];
  } finally {
    loading.value = false;
  }
};

// 保存兑换码信息（支持传入数据或使用当前数据）
const saveRedeemInfo = async (data) => {
  const payload = data || redeemInfo.value;
  if (!payload) {
    return showModal('提示', '没有可保存的信息', 'info');
  }

  try {
    const res = await bridge.saveRedeemInfo(payload);
    if (res.code === 0) {
      showModal('成功', '保存成功', 'success');
      // 重新加载历史记录
      await loadHistory();
    } else {
      showModal('错误', res.msg || '保存失败', 'error');
    }
  } catch (e) {
    console.error(e);
    showModal('异常', e.message || '保存出错', 'error');
  }
};

// 删除兑换码信息
const deleteRedeemInfo = async (taskId) => {
  if (!confirm('确定要删除这条记录吗？')) {
    return;
  }

  try {
    const res = await bridge.deleteRedeemInfo(taskId);
    if (res.code === 0) {
      showModal('成功', '删除成功', 'success');
      // 重新加载历史记录
      await loadHistory();
    } else {
      showModal('错误', res.msg || '删除失败', 'error');
    }
  } catch (e) {
    console.error(e);
    showModal('异常', e.message || '删除出错', 'error');
  }
};

// 检测兑换码状态
const checkRedeemStatus = async (taskId, item) => {
  try {
    const res = await bridge.checkRedeemStatus(taskId);
    if (res.code === 0) {
      // 更新历史记录中的状态
      item.check_status = res.data.status;
      item.check_status_text = res.data.status_text;
      item.last_check_time = new Date().toLocaleString();
      
      // 保存到缓存
      checkStatusCache.value.set(taskId, {
        check_status: res.data.status,
        check_status_text: res.data.status_text,
        last_check_time: item.last_check_time
      });
      
      showModal('成功', `检测完成: ${res.data.status_text}`, 'success');
    } else {
      showModal('错误', res.msg || '检测失败', 'error');
    }
  } catch (e) {
    console.error(e);
    showModal('异常', e.message || '检测出错', 'error');
  }
};

// 检测状态缓存
const checkStatusCache = ref(new Map());

// 提取天数信息
const extractDays = (item) => {
  // 优先从alias字段提取
  if (item.alias) {
    const aliasMatch = item.alias.match(/(\d+)天/);
    if (aliasMatch) return parseInt(aliasMatch[1]);
  }
  
  // 如果alias没有，从task_name字段提取
  if (item.task_name) {
    const taskMatch = item.task_name.match(/(\d+)天/);
    if (taskMatch) return parseInt(taskMatch[1]);
  }
  
  return 0;
};

// 排序历史记录
const sortHistory = (history) => {
  return history.sort((a, b) => {
    const daysA = extractDays(a);
    const daysB = extractDays(b);
    
    // 如果都有天数，按天数升序排列（天数少的排前面）
    if (daysA > 0 && daysB > 0) {
      return daysA - daysB;
    }
    
    // 如果只有一个有天数，有天数的排在前面
    if (daysA > 0 && daysB === 0) return -1;
    if (daysA === 0 && daysB > 0) return 1;
    
    // 如果都没有天数，按游戏类型排序
    const typeOrder = { 'zzk': 1, 'bengtie': 2, 'unknown': 3 };
    const typeA = typeOrder[a.game_type] || 3;
    const typeB = typeOrder[b.game_type] || 3;
    if (typeA !== typeB) return typeA - typeB;
    
    // 最后按任务名称排序
    return (a.task_name || '').localeCompare(b.task_name || '');
  });
};

const loadHistory = async () => {
  try {
    const res = await bridge.getRedeemHistory();
    if (res.code === 0) {
      const newHistory = res.data || [];
      // 恢复检测状态
      newHistory.forEach(item => {
        const cached = checkStatusCache.value.get(item.task_id);
        if (cached) {
          item.check_status = cached.check_status;
          item.check_status_text = cached.check_status_text;
          item.last_check_time = cached.last_check_time;
        }
      });
      // 排序历史记录
      historyList.value = sortHistory(newHistory);
    }
  } catch (e) {
    console.error(e);
  }
};

// 获取游戏类型显示
const getGameTypeLabel = (gameType) => {
  if (!gameType) return '未知';
  return gameType === 'zzk' ? '绝区零' : gameType === 'bengtie' ? '崩铁' : '其他';
};

// 获取游戏类型颜色
const getGameTypeClass = (gameType) => {
  if (!gameType) return 'type-unknown';
  return gameType === 'zzk' ? 'type-zzk' : gameType === 'bengtie' ? 'type-bengtie' : 'type-unknown';
};

// 获取兑换码类型显示
const getRedeemTypeLabel = (type) => {
  if (!type) return '其他';
  return type === '直播' ? '直播' : type === '投稿' ? '投稿' : '其他';
};

// 获取兑换码类型颜色
const getRedeemTypeClass = (type) => {
  if (!type) return 'type-other';
  return type === '直播' ? 'type-live' : type === '投稿' ? 'type-post' : 'type-other';
};

// 根据类型返回默认首发时间
const getFirstPublishTime = (type) => {
  if (type === '直播') return '01:00';
  if (type === '投稿') return '18:00';
  return '';
};

// 当历史项的日期改变时保存
const updateHistoryDate = async (item) => {
  // item.first_publish_date 已由 v-model 更新
  try {
    const res = await bridge.saveRedeemInfo(item);
    if (res.code === 0) {
      showModal('成功', '首发日期已保存', 'success');
      await loadHistory();
    } else {
      showModal('错误', res.msg || '保存失败', 'error');
    }
  } catch (e) {
    console.error(e);
    showModal('异常', e.message || '保存出错', 'error');
  }
};



// 组件挂载时加载历史记录
onMounted(() => {
  loadHistory();
});
</script>

<template>
  <div class="panel fade-in">
    <div class="header-section">
      <h2 class="title">兑换码获取</h2>
      <p class="subtitle">输入 Task ID 获取兑换码信息</p>
    </div>

    <div class="card config-card">
      <!-- 输入框和按钮 -->
      <div class="input-group">
        <label class="label">Task ID</label>
        <div class="row" style="gap: 8px;">
          <input
            v-model="taskId"
            class="gemini-input"
            placeholder="请输入 Task ID"
            style="flex: 1;"
            @keyup.enter="fetchRedeemInfo"
          />
          <button
            class="btn btn-start"
            @click="fetchRedeemInfo"
            :disabled="loading"
            style="min-width: 100px; height: 40px;"
          >
            <span v-if="loading" class="loader"></span>
            <template v-else>获取信息</template>
          </button>
        </div>
      </div>

      <!-- 标签页 -->
      <div class="tabs" style="margin-top: 20px;">
        <button 
          class="tab-btn" 
          :class="{ active: !showHistory }"
          @click="showHistory = false"
        >
          当前信息
        </button>
        <button 
          class="tab-btn" 
          :class="{ active: showHistory }"
          @click="showHistory = true"
        >
          历史记录 ({{ historyList.length }})
        </button>
      </div>

      <!-- 当前信息区域 -->
      <div v-if="!showHistory" class="list-section" style="margin-top: 16px;">
        <label class="label">兑换码信息</label>
        <div class="list-container">
          <div v-if="redeemList.length === 0" class="empty-state">
            暂无兑换码信息
          </div>
          <div v-else v-for="(item, index) in redeemList" :key="index" class="list-item">
            <div class="item-content">
              <!-- 顶部：游戏类型和状态 -->
              <div class="item-header">
                <span :class="['game-type', getGameTypeClass(item.game_type)]">
                  {{ getGameTypeLabel(item.game_type) }}
                </span>
                <span class="item-status" :class="item.status === 0 ? 'available' : item.status === 1 ? 'partial' : 'sold-out'">
                  {{ item.status === 0 ? '有货' : item.status === 1 ? '库存不足' : '' }}
                </span>
              </div>
              
              <!-- 详细信息 -->
              <div class="item-details">
                <div class="detail-row">
                  <span class="label">活动:</span>
                  <span class="value">{{ item.act_name }}</span>
                </div>
                <div class="detail-row">
                  <span class="label">任务:</span>
                  <span class="value">{{ item.task_name }}</span>
                </div>
                <div class="detail-row" v-if="item.alias">
                  <span class="label">别名:</span>
                  <span class="value alias">{{ item.alias }}</span>
                </div>
                <div class="detail-row">
                  <span class="label">奖励:</span>
                  <span class="value award">{{ item.award_name }}</span>
                </div>
                <div class="detail-row">
                  <span class="label">库存:</span>
                  <span class="value">
                    <span v-if="item.stock_status === 'day_limit'" class="stock-info day-limit">
                      ⚠️ 今日库存已达上限 (整体剩余 {{ item.total_stock_percentage }}%)
                    </span>
                    <span v-else-if="item.stock_status === 'low'" class="stock-info low">
                      ⚠️ 库存不足 (整体剩余 {{ item.total_stock_percentage }}% | 今日{{ item.day_remain }}份)
                    </span>
                    <span v-else class="stock-info available">
                      ✓ 整体剩余库存: {{ item.total_stock_percentage }}%
                    </span>
                  </span>
                </div>
                <div class="detail-row" v-if="item.message">
                  <span class="label">备注:</span>
                  <span class="value message">{{ item.message }}</span>
                </div>
                <!-- 首发日期/时间 -->
                <div class="detail-row">
                  <span class="label">首发:</span>
                  <span class="value">
                    <input type="date" v-model="item.first_publish_date" style="margin-right:8px;" />
                    <span>{{ item.first_publish_time || getFirstPublishTime(item.type) }}</span>
                  </span>
                </div>
              </div>
              
              <!-- 保存按钮 -->
              <div class="item-actions" style="margin-top: 16px; text-align: center;">
                <button
                  class="btn btn-save"
                  @click="saveRedeemInfo"
                  style="min-width: 120px; height: 36px; font-size: 14px;"
                >
                  💾 保存到历史
                </button>
              </div>
              
              <!-- 底部：ID信息 -->
              <div class="item-footer">
                <div class="id-info">
                  <span class="id-label">Act:</span>
                  <span class="id-value">{{ item.act_id }}</span>
                </div>
                <div class="id-info">
                  <span class="id-label">Task:</span>
                  <span class="id-value">{{ item.task_id }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 历史记录区域 -->
      <div v-else class="list-section" style="margin-top: 16px;">
        <label class="label">查询历史 (按天数排序)</label>
        <div class="list-container">
          <div v-if="historyList.length === 0" class="empty-state">
            暂无查询历史
          </div>
          <div v-else v-for="(item, index) in historyList.slice(0, 30)" :key="index" class="history-item">
            <div class="history-header">
              <span :class="['game-type-small', getGameTypeClass(item.game_type)]">
                {{ getGameTypeLabel(item.game_type) }}
              </span>
              <span :class="['redeem-type-small', getRedeemTypeClass(item.type)]">
                {{ getRedeemTypeLabel(item.type) }}
              </span>
              <span class="history-title">{{ item.alias || item.task_name }}</span>
              <div class="history-actions">
                <button
                  class="btn-check"
                  @click="checkRedeemStatus(item.task_id, item)"
                  title="检测状态"
                >
                  🔍
                </button>
                <button
                  class="btn-delete"
                  @click="deleteRedeemInfo(item.task_id)"
                  title="删除记录"
                >
                  🗑️
                </button>
              </div>
            </div>
            <div class="history-meta">
              <span class="meta-item">{{ item.award_name }}</span>              <span class="meta-item">
                首发: 
                <input type="date" v-model="item.first_publish_date" @change="updateHistoryDate(item)" style="margin:0 4px;" />
                {{ item.first_publish_time || getFirstPublishTime(item.type) }}
              </span>              <span class="meta-item stock">库存: {{ item.total_stock }}%</span>
              <span class="meta-item status" :class="item.status === 0 ? 'available' : item.status === 1 ? 'partial' : 'sold-out'">
                {{ item.status === 0 ? '有货' : item.status === 1 ? '库存不足' : '' }}
              </span>
              <span v-if="item.check_status" class="meta-item check-result" :class="'check-' + item.check_status">
                检测: {{ item.check_status_text }}
                <span v-if="item.last_check_time" class="check-time">({{ item.last_check_time }})</span>
              </span>
            </div>
          </div>
        </div>
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

.btn-start {
  background-color: #669DF6;
  box-shadow: 0 4px 14px rgba(102, 157, 246, 0.3);
}

.btn-start:hover:not(:disabled) {
  background-color: #5189E0;
  transform: translateY(-1px);
}

.tabs {
  display: flex;
  gap: 8px;
  border-bottom: 1px solid #e0e3e7;
}

.tab-btn {
  padding: 8px 12px;
  border: none;
  background: transparent;
  color: var(--text-sub);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: 0.2s;
  border-bottom: 2px solid transparent;
}

.tab-btn.active {
  color: var(--primary-color);
  border-bottom-color: var(--primary-color);
}

.list-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.list-container {
  border: 1px solid #e0e3e7;
  border-radius: 8px;
  min-height: 200px;
  max-height: 500px;
  overflow-y: auto;
  background: #fafbfc;
}

.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 200px;
  color: var(--text-sub);
  font-size: 14px;
}

.list-item {
  padding: 16px;
  border-bottom: 1px solid #e0e3e7;
}

.list-item:last-child {
  border-bottom: none;
}

.item-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.game-type {
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.game-type.type-zzk {
  background-color: #E3F2FD;
  color: #1565C0;
}

.game-type.type-bengtie {
  background-color: #FCE4EC;
  color: #C2185B;
}

.game-type.type-unknown {
  background-color: #F5F5F5;
  color: #666;
}

.item-status {
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.item-status.available {
  background-color: #E8F5E9;
  color: #2E7D32;
}

.item-status.partial {
  background-color: #FFF3E0;
  color: #E65100;
}

.item-status.sold-out {
  background-color: #FFEBEE;
  color: #C62828;
}

.item-details {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: white;
  border-radius: 6px;
  font-size: 12px;
}

.detail-row {
  display: flex;
  gap: 8px;
}

.detail-row .label {
  color: var(--text-sub);
  font-weight: 600;
  min-width: 50px;
  margin: 0;
}

.detail-row .value {
  color: var(--text-main);
  flex: 1;
  word-break: break-word;
}

.detail-row .award {
  color: #C2185B;
  font-weight: 600;
}

.detail-row .alias {
  color: #1976D2;
  font-weight: 500;
}

.detail-row .message {
  color: #F57C00;
  font-size: 11px;
}

.stock-info {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 500;
}

.stock-info.available {
  background-color: #E8F5E9;
  color: #2E7D32;
}

.stock-info.day-limit {
  background-color: #FFF3E0;
  color: #E65100;
}

.stock-info.total-limit {
  background-color: #FFEBEE;
  color: #C62828;
}

.stock-info.sold-out {
  background-color: #FFEBEE;
  color: #C62828;
}

.stock-info.low {
  background-color: #FFF3E0;
  color: #E65100;
}

.item-footer {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--text-sub);
}

.id-info {
  display: flex;
  gap: 4px;
  align-items: center;
}

.id-label {
  font-weight: 600;
}

.id-value {
  font-family: 'Courier New', monospace;
  background-color: #f5f5f5;
  padding: 2px 6px;
  border-radius: 3px;
}

/* 历史记录样式 */
.history-item {
  padding: 12px 16px;
  border-bottom: 1px solid #e0e3e7;
  cursor: pointer;
  transition: 0.2s;
}

.history-item:hover {
  background-color: #f9f9f9;
}

.history-item:last-child {
  border-bottom: none;
}

.history-header {
  display: flex;
  gap: 10px;
  align-items: center;
  margin-bottom: 6px;
}

.game-type-small {
  padding: 3px 8px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}

.game-type-small.type-zzk {
  background-color: #E3F2FD;
  color: #1565C0;
}

.game-type-small.type-bengtie {
  background-color: #FCE4EC;
  color: #C2185B;
}

.redeem-type-small {
  padding: 3px 8px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}

.redeem-type-small.type-live {
  background-color: #E8F5E9;
  color: #2E7D32;
}

.redeem-type-small.type-post {
  background-color: #FFF3E0;
  color: #E65100;
}

.redeem-type-small.type-other {
  background-color: #F5F5F5;
  color: #666;
}

.history-title {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-main);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-stock {
  font-size: 11px;
  color: var(--text-sub);
  min-width: 40px;
  text-align: right;
}

.history-meta {
  font-size: 11px;
  color: var(--text-sub);
}

.meta-item {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.stock-badge {
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}

.stock-badge.day-limit {
  background-color: #FFF3E0;
  color: #E65100;
}

.stock-badge.total-limit {
  background-color: #FFEBEE;
  color: #C62828;
}

.loader {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-radius: 50%;
  border-top-color: #fff;
  animation: spin 0.8s linear infinite;
}

.btn-save {
  background-color: #4CAF50;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
  transition: 0.2s;
  box-shadow: 0 2px 8px rgba(76, 175, 80, 0.3);
}

.btn-save:hover:not(:disabled) {
  background-color: #45A049;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(76, 175, 80, 0.4);
}

.history-actions {
  margin-left: auto;
  display: flex;
  gap: 4px;
}

.btn-delete {
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  border-radius: 3px;
  font-size: 14px;
  transition: 0.2s;
  opacity: 0.6;
}

.btn-delete:hover {
  opacity: 1;
  background-color: #ffebee;
}

.btn-check {
  background: none;
  border: none;
  cursor: pointer;
  padding: 4px;
  border-radius: 3px;
  font-size: 14px;
  transition: 0.2s;
  opacity: 0.6;
  margin-right: 4px;
}

.btn-check:hover {
  opacity: 1;
  background-color: #e3f2fd;
}

.history-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.meta-item {
  font-size: 12px;
  color: var(--text-sub);
}

.meta-item.status {
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
}

.meta-item.status.available {
  background-color: #E8F5E9;
  color: #2E7D32;
}

.meta-item.status.partial {
  background-color: #FFF3E0;
  color: #E65100;
}

.meta-item.stock {
  color: var(--text-main);
  font-weight: 600;
}

.meta-item.check-result {
  font-weight: 600;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 11px;
  margin-top: 4px;
}

.meta-item.check-result.check-claimed {
  background-color: #E8F5E9;
  color: #2E7D32;
}

.meta-item.check-result.check-gone {
  background-color: #FFEBEE;
  color: #C62828;
}

.meta-item.check-result.check-available {
  background-color: #FFF3E0;
  color: #E65100;
}

.meta-item.check-result.check-unknown {
  background-color: #F5F5F5;
  color: #666;
}

.check-time {
  font-size: 10px;
  opacity: 0.7;
  margin-left: 4px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
