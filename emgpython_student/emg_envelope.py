# 启用未来版本类型注解，让代码类型提示更规范
from __future__ import annotations

# 导入低通滤波器类，用于肌电信号平滑
from emg_lpf import LowPassFilterStream


# 肌电信号等级分析器：将滤波后的肌电信号转为 0~5 共6个强度等级
# 处理流程：取绝对值 → 低通滤波 → 慢平滑 → 自动标定 → 滞回分级 → 输出等级
class EmgLevelAnalyzer:
    """
    等级 0~5：CH1 滤波信号 → |x| → 低通(1~5Hz) → 慢 EMA → 标定 → 滞回。
    """

    # 等级划分阈值（百分比）
    RATIO_LEVEL_1 = 12    # 12% 以下 → 等级1
    RATIO_LEVEL_2 = 28    # 12~28% → 等级2
    RATIO_LEVEL_3 = 45    # 28~45% → 等级3
    RATIO_LEVEL_4 = 65    # 45~65% → 等级4
    # 65% 以上 → 等级5

    MIN_SPAN = 40.0               # 信号最小动态范围，防止标定区间过小
    REST_ZERO_RATIO = 0.75        # 放松状态归零阈值比例
    REST_EXIT_RATIO = 0.82        # 退出放松状态的阈值比例

    # 初始化分析器
    # rate: 采样率(Hz) | lpf_cutoff_hz: 低通截止频率 | slow_sec: 慢平滑时间 | calib_sec: 自动标定时间
    def __init__(
        self,
        rate: int = 500,
        lpf_cutoff_hz: float = 3.0,
        slow_sec: float = 0.4,
        calib_sec: float = 10.0,
    ):
        self.rate = rate                          # 采样率
        self.lpf_cutoff_hz = lpf_cutoff_hz        # 低通截止频率（默认3Hz）
        self.slow_sec = slow_sec                  # 慢平滑时间（默认0.4秒）
        self.calib_sec = calib_sec                # 自动标定时间（默认10秒）

        # 创建低通滤波器，用于平滑肌电绝对值
        self.lpf = LowPassFilterStream(rate, lpf_cutoff_hz)
        # 标定需要的总采样点数
        self.calib_samples = max(1, int(rate * calib_sec))
        # 计算 EMA（指数移动平均）系数，用于慢平滑
        self._alpha = 1.0 - pow(2.718281828, -1.0 / max(1.0, rate * slow_sec))

        # 当前输出等级 0~5
        self.level = 0
        # 低通滤波后的值
        self.lpf_val = 0.0
        # 当前活动强度（低通后）
        self.activity = 0.0
        # 慢平滑后的活动强度（最终用于分级）
        self.activity_slow = 0.0

        # 标定参数：信号最小值、最大值
        self.calib_min = 0.0
        self.calib_max = 0.0
        # 标定是否完成
        self.calib_done = False
        # 采样点计数（用于标定）
        self._sample_count = 0
        # 标定过程中累计的最小值、最大值
        self._calib_min_acc = float("inf")
        self._calib_max_acc = 0.0
        # 滞回控制：等级下降保持计数，防止抖动
        self._drop_hold = 0

    # 重置分析器：可重新设置采样率、截止频率，清空所有状态
    def reset(self, rate: int | None = None, lpf_cutoff_hz: float | None = None):
        # 更新采样率（如果传入新值）
        if rate is not None:
            self.rate = rate
        # 更新低通截止频率（如果传入新值）
        if lpf_cutoff_hz is not None:
            self.lpf_cutoff_hz = lpf_cutoff_hz

        # 重新计算标定点数和EMA系数
        self.calib_samples = max(1, int(self.rate * self.calib_sec))
        self._alpha = 1.0 - pow(2.718281828, -1.0 / max(1.0, self.rate * self.slow_sec))
        # 重置滤波器
        self.lpf.reset(self.rate, self.lpf_cutoff_hz)

        # 清空所有状态变量
        self.level = 0
        self.lpf_val = 0.0
        self.activity = 0.0
        self.activity_slow = 0.0
        self.calib_min = 0.0
        self.calib_max = 0.0
        self.calib_done = False
        self._sample_count = 0
        self._calib_min_acc = float("inf")
        self._calib_max_acc = 0.0
        self._drop_hold = 0

    # 结束标定：计算最终的最小/最大值，保证有效范围
    def _finish_calib(self):
        # 如果标定期间没有采集到有效最小值，设为0
        if self._calib_min_acc == float("inf"):
            self._calib_min_acc = 0.0

        self.calib_min = self._calib_min_acc
        span = self._calib_max_acc - self.calib_min

        # 如果信号范围太小，强制使用最小范围，避免分级异常
        if span < self.MIN_SPAN:
            self.calib_max = self.calib_min + self.MIN_SPAN
        else:
            self.calib_max = self._calib_max_acc

        # 标记标定完成
        self.calib_done = True

    # 根据百分比映射等级：输入百分比，输出 1~5 级
    def _map_ratio(self, ratio: float) -> int:
        if ratio < self.RATIO_LEVEL_1:
            return 1
        if ratio < self.RATIO_LEVEL_2:
            return 2
        if ratio < self.RATIO_LEVEL_3:
            return 3
        if ratio < self.RATIO_LEVEL_4:
            return 4
        return 5

    # 等级平滑/滞回处理：防止等级跳变抖动，上升快、下降慢
    def _smooth_level(self, target: int, ratio: float) -> int:
        # 等级上升：立即提升，最多一次+1
        if target > self.level:
            self._drop_hold = 0
            if ratio >= 85 and target > self.level + 1:
                return min(5, self.level + 1)
            return min(5, self.level + 1)

        # 等级下降：增加滞回，防止抖动
        if target < self.level:
            gap = self.level - target
            # 差距≥2且信号弱，直接降2级
            if gap >= 2 and ratio < 50:
                self._drop_hold = 0
                return max(0, self.level - 2)
            # 否则需要保持1帧再降1级
            self._drop_hold += 1
            if self._drop_hold < 2:
                return self.level
            self._drop_hold = 0
            return max(0, self.level - 1)

        # 等级不变
        self._drop_hold = 0
        return self.level

    # 根据信号幅度更新最终等级（包含放松归零逻辑）
    def _update_level(self, amp: float) -> int:
        span = self.calib_max - self.calib_min
        # 防止除以0
        if span <= 0:
            span = self.MIN_SPAN

        # 计算放松状态的阈值
        rest_zero = max(self.calib_min * self.REST_ZERO_RATIO, self.calib_max * 0.45 * self.REST_ZERO_RATIO)
        rest_exit = max(self.calib_min * self.REST_EXIT_RATIO, self.calib_max * 0.52 * self.REST_EXIT_RATIO)

        # 放松状态归零逻辑
        if self.level == 0:
            if amp < rest_exit:
                return 0
        elif amp < rest_zero:
            return 0

        # 信号低于最小值，按最小等级处理
        if amp <= self.calib_min:
            return self._smooth_level(1, 0.0)

        # 计算信号占总范围的百分比
        activity = amp - self.calib_min
        ratio = min(100.0, activity * 100.0 / span)
        # 映射目标等级
        target = self._map_ratio(ratio)
        # 经过滞回平滑后输出
        return self._smooth_level(target, ratio)

    # 核心处理函数：输入单个滤波后的肌电值，输出 平滑值、慢值、等级
    def process_sample(self, filtered: float) -> tuple[float, float, int]:
        # 1. 取绝对值 + 低通滤波
        self.lpf_val = self.lpf.process_sample(abs(filtered))
        # 2. 当前活动强度 = 低通输出
        self.activity = self.lpf_val
        # 采样计数+1
        self._sample_count += 1

        # ================= 标定阶段 =================
        if not self.calib_done:
            # 累计标定期间的最大/最小值
            self._calib_min_acc = min(self._calib_min_acc, self.activity)
            self._calib_max_acc = max(self._calib_max_acc, self.activity)
            # 标定期间慢值 = 当前值
            self.activity_slow = self.activity
            # 标定期间等级保持0
            self.level = 0

            # 达到标定点数，结束标定
            if self._sample_count >= self.calib_samples:
                self._finish_calib()
            return self.lpf_val, self.activity_slow, self.level

        # ================= 标定完成，正常分析 =================
        # 3. 慢平滑 EMA
        self.activity_slow += self._alpha * (self.activity - self.activity_slow)

        # 动态上限：如果信号超过最大值，缓慢提升最大值
        if self.activity_slow > self.calib_max * 0.98:
            self.calib_max += 0.05 * (self.activity_slow - self.calib_max)

        # 4. 根据慢平滑值计算最终等级
        self.level = self._update_level(self.activity_slow)
        return self.lpf_val, self.activity_slow, self.level

    # 批量处理一帧数据：输入一组采样点，输出最后状态
    def feed_block(self, samples) -> tuple[float, float, int]:
        lpf_v = self.lpf_val
        act_s = self.activity_slow
        lvl = self.level

        # 遍历逐个处理
        for s in samples:
            lpf_v, act_s, lvl = self.process_sample(float(s))

        # 返回最后一帧的结果
        return lpf_v, act_s, lvl