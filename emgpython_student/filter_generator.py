import numpy as np
from scipy import signal
import matplotlib.pyplot as plt

# ======================
# 250Hz 专用参数
# ======================
fs = 250         # 采样率 250Hz
fc_hp = 20       # 高通截止 20Hz
fn_50 = 50       # 陷波 50Hz
order_hp = 6     # 6阶高通

# 1. 6阶巴特沃斯高通（250Hz专用）
b_hp, a_hp = signal.butter(order_hp, fc_hp, fs=fs, btype='high')

# 2. 50Hz陷波（250Hz专用）
b_notch, a_notch = signal.iirnotch(fn_50, Q=30, fs=fs)

# 3. 滤波函数（最终可用）
def emg_filter_250hz(raw_emg):
    # 先高通，后陷波（标准顺序）
    s = signal.lfilter(b_hp, a_hp, raw_emg)
    s = signal.lfilter(b_notch, a_notch, s)
    return s

# ======================
# 测试信号
# ======================
t = np.linspace(0, 2, fs*2)
raw = 0.8*np.random.randn(len(t)) + 0.5*np.sin(2*np.pi*50*t) + 0.2*np.sin(2*np.pi*2*t)
filtered = emg_filter_250hz(raw)

# 绘图
plt.figure(figsize=(12,6))
plt.subplot(211)
plt.plot(t, raw, label='原始信号')
plt.title('250Hz采样 - 原始EMG（基线漂移+50Hz工频）')
plt.legend()

plt.subplot(212)
plt.plot(t, filtered, color='r', label='滤波后')
plt.title('6阶20Hz高通 + 50Hz陷波（250Hz专用）')
plt.legend()
plt.tight_layout()
plt.show()