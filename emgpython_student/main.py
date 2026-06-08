"""EMG 多串口采集主程序，实时显示波形并在关闭窗口后保留最终图像。"""

# 启用未来版本类型注解，让代码类型提示更规范
#延迟类型注解解析，解决类自引用报错
from __future__ import annotations

# 导入系统平台模块，用于适配不同操作系统字体
import platform
# 导入时间模块，用于延时控制
import time
# 导入警告模块，屏蔽无关警告
import warnings

# 导入绘图库
import matplotlib
# 指定绘图后端为 TkAgg，保证跨平台兼容性
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
# 导入数值计算库
import numpy as np

# 导入多串口管理工具函数
from ads_multi_uart import (
    DEFAULT_RATE,          # 默认采样率
    DEFAULT_RANGE,         # 默认量程
    close_uarts,           # 关闭串口
    init_devices,          # 初始化设备
    start_acquisition,     # 启动采集
    stop_acquisition,      # 停止采集
    uarts_read_parse,      # 读取并解析数据
)
# 导入指令生成类
from ads_cmd import AdsCmd
# 导入数据解析类与采样率列表
from ads_data import SAMPLE_RATES
# 导入肌电等级分析器
from emg_envelope import EmgLevelAnalyzer
# 导入低通滤波函数
from emg_lpf import lowpass_curve

# ===================== 配置区 =====================
# 串口号列表，根据实际设备修改（Windows:COM3, Linux:/dev/ttyUSB0）
PORTS = ["COM5"]
# 采样率：建议 500sps（自带 50Hz 陷波滤波）
SAMPLE_RATE = DEFAULT_RATE
# 电压量程
SAMPLE_RANGE = DEFAULT_RANGE
# 绘图窗口显示的最大点数
WIN_LEN = 2500
# 调试模式开关
DEBUG = True
# 绘图模式：filtered=滤波后数据，raw=原始数据
PLOT_MODE = "filtered"

# 第二子图：肌电包络低通滤波参数（1~5Hz）
LPF_CUTOFF_HZ = 3.0    # 截止频率 3Hz
LPF_ORDER = 4          # 4阶巴特沃斯
LPF_YMAX = 80.0        # 第二子图纵轴固定上限

# 肌电强度等级分析参数
LEVEL_SLOW_SEC = 0.4     # 慢平滑时间
LEVEL_CALIB_SEC = 10.0   # 自动标定时间（10秒）

# ===================== 工具函数 =====================
# 设置 Matplotlib 中文字体，解决中文乱码问题
def setup_matplotlib_font():
    # Windows 系统字体
    if platform.system() == "Windows":
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "sans-serif"]
    # Mac/Linux 系统字体
    else:
        plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "PingFang SC", "sans-serif"]
    # 解决负号显示异常
    plt.rcParams["axes.unicode_minus"] = False
    # 屏蔽字体缺失警告
    warnings.filterwarnings("ignore", message="Glyph .* missing from font")

# ===================== 实时绘图类 =====================
class EmgPlotter:
    # 初始化绘图器
    # device_num：设备数量 level_analyzers：每个设备的等级分析器
    def __init__(self, device_num: int, level_analyzers: list[EmgLevelAnalyzer]):
        self.is_exit_collect = False       # 退出采集标志
        self.device_num = device_num       # 设备数量
        self.level_analyzers = level_analyzers  # 等级分析器列表
        self._processed_len = [0] * device_num  # 记录每个设备已处理的数据长度,创建一个长度为 device_num 的列表，里面全部填 0

        # 创建画布：每个设备 2 个子图（原始波形 + 低通包络）
        self.fig, self.axes = plt.subplots(
            device_num * 2, 1,
            figsize=(12, 3 * device_num * 2),
            sharex=True  # 共享X轴
        )
        # 单设备时，把 axes 转为列表，统一处理
        if device_num * 2 == 1:
            self.axes = [self.axes]

        # 设置窗口标题
        self.fig.canvas.manager.set_window_title("EMG Data")
        # 设置子图间距
        self.fig.subplots_adjust(hspace=0.35)

        self.lines = []  # 存储每条曲线对象
        # 子图标签：通道1波形、通道1绝对值低通
        channel_names = ["CH1", f"|CH1| LPF {LPF_CUTOFF_HZ:g}Hz"]

        # 遍历初始化所有子图
        for idx, ax in enumerate(self.axes):
            dev = idx // 2 + 1          # 设备编号
            label = channel_names[idx % 2]  # 子图标签
            # 创建曲线，设置颜色
            (line,) = ax.plot([], [], lw=1.2, color="#1f77b4" if idx % 2 == 0 else "#ff7f0e")
            self.lines.append(line)
            # 设置Y轴标签
            ax.set_ylabel(f"Dev{dev} {label}")
            # 显示网格
            ax.grid(True, alpha=0.3)
            if idx % 2 == 1:
                ax.set_ylim(0.0, LPF_YMAX)

        # 最后一个子图设置X轴标签
        self.axes[-1].set_xlabel("Sample")
        # 绑定窗口关闭事件
        self.fig.canvas.mpl_connect("close_event", self._on_close)

    # 窗口关闭触发函数：设置退出标志
    def _on_close(self, _event):
        if not self.is_exit_collect:
            self.is_exit_collect = True

    # 更新单个设备的波形数据
    def update_device(self, device_idx: int, chx_data: np.ndarray, chx_raw: np.ndarray, rate: int):
        # 已退出 或 无数据，直接返回
        if self.is_exit_collect or chx_data.size == 0:
            return 0, 0.0, False

        # 获取当前设备的等级分析器
        analyzer = self.level_analyzers[device_idx]
        # 采样率变化，重置分析器
        if analyzer.rate != rate:
            analyzer.reset(rate=rate)
            self._processed_len[device_idx] = 0

        # 选择数据源：原始/滤波后
        source = chx_raw if PLOT_MODE == "raw" else chx_data
        prev = self._processed_len[device_idx]

        # 有新数据，进行等级分析
        if source.shape[0] > prev:
            analyzer.feed_block(source[prev:, 0])  # 只处理CH1
            self._processed_len[device_idx] = source.shape[0]

        n = len(source)
        # 数据不足窗口长度，显示全部
        if n <= WIN_LEN:
            x = np.arange(n)
            start = 0
        # 数据超长，只显示最新 WIN_LEN 点
        else:
            start = n - WIN_LEN
            x = np.arange(start, n)

        # 取出通道1数据
        ch1 = source[start:, 0]

        # ---------- 绘制第一个子图：原始/滤波波形 ----------
        line_idx = device_idx * 2
        y1 = ch1 - np.mean(ch1)  # 去均值，基线归零
        self.lines[line_idx].set_data(x, y1)
        ax1 = self.axes[line_idx]
        if len(y1) > 0:
            margin1 = max(float(np.std(y1)) * 4, 1.0)  # 自适应Y轴范围
            ax1.set_xlim(x[0], x[-1] if len(x) > 1 else x[0] + 1)
            ax1.set_ylim(float(np.min(y1)) - margin1, float(np.max(y1)) + margin1)

        # ---------- 绘制第二个子图：绝对值 + 低通包络 ----------
        line_idx = device_idx * 2 + 1
        y2 = lowpass_curve(np.abs(ch1), rate, LPF_CUTOFF_HZ, LPF_ORDER)
        y2 = np.clip(y2, 0.0, LPF_YMAX)
        self.lines[line_idx].set_data(x, y2)
        ax2 = self.axes[line_idx]
        if len(y2) > 0:
            ax2.set_xlim(x[0], x[-1] if len(x) > 1 else x[0] + 1)
            ax2.set_ylim(0.0, LPF_YMAX)

        # 返回当前等级、包络值、标定状态
        return analyzer.level, analyzer.activity_slow, analyzer.calib_done

    # 设置图表总标题
    def set_title(self, title: str):
        self.fig.suptitle(title, fontsize=11)

    # 刷新画布
    def refresh(self):
        if self.is_exit_collect:
            return
        self.fig.canvas.draw()
        self.fig.canvas.flush_events()

# ===================== 主运行函数 =====================
def run():
    # 初始化中文字体
    setup_matplotlib_font()
    # 设备数量 = 串口号数量
    device_num = len(PORTS)
    # 初始化串口设备
    uarts, ads_data_list, ads_cmd = init_devices(PORTS, debug=DEBUG)

    # 获取初始采样率
    rate_idx = AdsCmd.RATES.index(SAMPLE_RATE) if SAMPLE_RATE in AdsCmd.RATES else 2
    init_rate = SAMPLE_RATES[rate_idx]

    # 创建绘图器，为每个设备创建等级分析器
    plotter = EmgPlotter(
        device_num,
        [
            EmgLevelAnalyzer(
                rate=init_rate,
                lpf_cutoff_hz=LPF_CUTOFF_HZ,
                slow_sec=LEVEL_SLOW_SEC,
                calib_sec=LEVEL_CALIB_SEC,
            )
            for _ in range(device_num)
        ],
    )
    # 开启交互模式，实时绘图
    plt.ion()
    plt.show(block=False)

    try:
        # 启动采集
        start_acquisition(uarts, ads_cmd, ads_data_list, SAMPLE_RATE, SAMPLE_RANGE)
        # 重置所有等级分析器
        for analyzer in plotter.level_analyzers:
            analyzer.reset(rate=init_rate, lpf_cutoff_hz=LPF_CUTOFF_HZ)
        # 重置已处理数据长度
        plotter._processed_len = [0] * device_num

        # 循环采集：直到关闭窗口
        while not plotter.is_exit_collect:
            time.sleep(0.2)  # 200ms 读取一次
            uarts_read_parse(uarts, ads_data_list)  # 读取并解析串口数据

            has_data = False
            # 遍历所有设备更新绘图
            for i in range(device_num):
                chx_data = ads_data_list[i].chx_val    # 滤波后数据
                chx_raw = ads_data_list[i].chx_raw     # 原始数据
                if chx_data.size == 0:
                    continue

                has_data = True
                # 更新设备波形
                level, act_slow, calib_done = plotter.update_device(
                    i, chx_data, chx_raw, ads_data_list[i].rate
                )
                # 计算原始信号标准差
                raw_std = float(np.std(chx_raw))
                # 标定提示文字
                calib_txt = "标定中(请保持放松)" if not calib_done else "已标定"
                # 更新标题，显示实时信息
                plotter.set_title(
                    f"EMG Dev{i + 1} | {ads_data_list[i].rate}Hz | "
                    f"Level {level}/5 | LPF={act_slow:.0f} | {calib_txt} | raw std={raw_std:.1f}"
                )

            # 有数据则刷新画布
            if has_data:
                plotter.refresh()

            plt.pause(0.05)

    # 无论是否异常，最终都会执行
    finally:
        stop_acquisition(uarts, ads_cmd)   # 停止采集
        close_uarts(uarts, ads_cmd)        # 关闭串口

    # ===================== 关闭窗口后，显示完整数据回放 =====================
    fig2, axes2 = plt.subplots(device_num * 2, 1, figsize=(12, 3 * device_num * 2), sharex=True)
    if device_num * 2 == 1:
        axes2 = [axes2]

    # 遍历所有设备绘制完整数据
    for i in range(device_num):
        chx_val = ads_data_list[i].chx_val
        chx_raw = ads_data_list[i].chx_raw
        if chx_val.size == 0:
            continue
        source = chx_raw if PLOT_MODE == "raw" else chx_val
        ch1 = source[:, 0]

        # 绘制通道1波形
        ax = axes2[i * 2]
        y1 = ch1 - np.mean(ch1)
        ax.plot(y1, lw=0.8, label=f"Dev{i + 1} CH1")
        ax.set_ylabel(f"Dev{i + 1} CH1")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right")

        # 绘制低通包络波形
        ax = axes2[i * 2 + 1]
        y2 = lowpass_curve(np.abs(ch1), ads_data_list[i].rate, LPF_CUTOFF_HZ, LPF_ORDER)
        y2 = np.clip(y2, 0.0, LPF_YMAX)
        ax.plot(y2, lw=0.8, color="#ff7f0e", label=f"Dev{i + 1} LPF {LPF_CUTOFF_HZ:g}Hz")
        ax.set_ylabel(f"Dev{i + 1} LPF")
        ax.set_ylim(0.0, LPF_YMAX)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right")

    axes2[-1].set_xlabel("Sample")
    fig2.suptitle("EMG Recorded Data (demeaned)")
    plt.tight_layout()
    plt.ioff()
    plt.show()

# 程序入口
if __name__ == "__main__":
    run()