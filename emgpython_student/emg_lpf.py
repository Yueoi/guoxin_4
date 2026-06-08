"""EMG 低通滤波（1~5Hz）；调用方通常先对信号取 |x| 再滤波。"""

# 启用未来版本类型注解，让代码类型提示更规范
from __future__ import annotations

# 导入数值计算库
import numpy as np
# 从 scipy 导入滤波器设计与滤波函数
from scipy.signal import butter, filtfilt, lfilter, lfilter_zi


# 设计巴特沃斯低通滤波器
# rate: 采样率(Hz)  cutoff_hz: 截止频率  order: 滤波器阶数
# 返回: 滤波器系数 b(分子), a(分母)
def design_lowpass(rate: int, cutoff_hz: float, order: int = 4) -> tuple[np.ndarray, np.ndarray]:
    # 计算奈奎斯特频率 = 采样率的一半
    nyq = rate / 2.0
    # 限制截止频率范围：0.1Hz ~ 奈奎斯特频率*0.99（防止无效）
    wc = min(max(cutoff_hz, 0.1), nyq * 0.99)
    # 设计4阶巴特沃斯低通滤波器，返回系数
    return butter(order, wc / nyq, btype="low")


# 流式低通滤波器类：适合实时处理（逐点/逐帧），保持历史状态
class LowPassFilterStream:
    """流式低通，与采样率绑定。"""

    # 初始化滤波器
    # rate: 采样率  cutoff_hz: 截止频率  order: 阶数
    def __init__(self, rate: int, cutoff_hz: float = 3.0, order: int = 4):
        self.rate = rate                  # 采样率
        self.cutoff_hz = cutoff_hz        # 低通截止频率（默认3Hz）
        self.order = order                # 滤波器阶数（默认4阶）
        # 设计滤波器，获取系数 b, a
        self.b, self.a = design_lowpass(rate, cutoff_hz, order)
        # 初始化滤波器初始状态 zi（用于流式滤波，保证连续）
        self.zi = lfilter_zi(self.b, self.a)

    # 重置滤波器：可更新采样率、截止频率，清空历史状态
    def reset(self, rate: int | None = None, cutoff_hz: float | None = None):
        # 如果传入新采样率，更新
        if rate is not None:
            self.rate = rate
        # 如果传入新截止频率，更新
        if cutoff_hz is not None:
            self.cutoff_hz = cutoff_hz
        # 重新设计滤波器
        self.b, self.a = design_lowpass(self.rate, self.cutoff_hz, self.order)
        # 重置初始状态
        self.zi = lfilter_zi(self.b, self.a)

    # 批量处理一帧数据（实时流式）
    # samples: 输入信号数组  返回: 滤波后数组
    def process_block(self, samples: np.ndarray) -> np.ndarray:
        # 空数据直接返回空
        if samples.size == 0:
            return np.array([], dtype=np.float64)
        # 流式滤波：使用 lfilter + 状态 zi，保证连续不跳变
        y, self.zi = lfilter(self.b, self.a, np.asarray(samples, dtype=np.float64), zi=self.zi)
        return y

    # 处理单个采样点（实时逐点滤波）
    # sample: 单个浮点值  返回: 滤波后浮点值
    def process_sample(self, sample: float) -> float:
        # 把单个点包装成数组，调用批量处理
        return float(self.process_block(np.array([sample]))[0])


# 离线整段低通滤波（零相位滤波，无延迟，适合回放绘图）
# signal: 整段信号  rate: 采样率  cutoff_hz: 截止频率  order: 阶数
# 返回: 零相位滤波后的信号
def lowpass_curve(
    signal: np.ndarray,
    rate: int,
    cutoff_hz: float = 3.0,
    order: int = 4,
) -> np.ndarray:
    """离线低通（零相位 filtfilt），用于整段回放显示。"""
    # 空数据返回空
    if signal.size == 0:
        return np.array([], dtype=np.float64)
    # 数据太短时，改用流式滤波（避免 filtfilt 异常）
    if signal.size < order * 3:
        stream = LowPassFilterStream(rate, cutoff_hz, order)
        return stream.process_block(np.asarray(signal, dtype=np.float64))
    # 设计滤波器
    b, a = design_lowpass(rate, cutoff_hz, order)
    # 零相位滤波（正反各滤一次，无相位偏移，适合离线处理）
    return filtfilt(b, a, np.asarray(signal, dtype=np.float64))