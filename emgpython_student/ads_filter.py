
# 启用未来版本注解语法，让类型提示更规范
from __future__ import annotations

# 导入数值计算库，用于滤波系数计算与数组操作
import numpy as np

# 默认采样率：
DEFAULT_SAMPLE_RATE = 500


# IIR 数字滤波器基类（直接 I 型实现）
# 作用：单个 IIR 滤波器的核心运算，逐点滤波
class IIRFilter:
    def __init__(self, numerator: list[float] | np.ndarray, denominator: list[float] | np.ndarray):
        self.b = np.asarray(numerator, dtype=np.float64)
        self.a = np.asarray(denominator, dtype=np.float64)

        if self.a.size == 0:
            raise ValueError("denominator must not be empty")

        self.x = np.zeros(len(self.b), dtype=np.float64)
        self.y = np.zeros(len(self.a) - 1, dtype=np.float64)

    # 注意：这里要和 __init__ 同级缩进
    def process_sample(self, sample: float | int) -> float:
        self.x[1:] = self.x[:-1]
        self.x[0] = sample

        output = float(np.dot(self.b, self.x))

        for i in range(len(self.y)):
            output -= self.a[i + 1] * self.y[i]

        output /= self.a[0]

        self.y[1:] = self.y[:-1]
        self.y[0] = output

        return output


# EMG 专用滤波器：根据采样率自动选择滤波组合
# 功能：20Hz 高通 + 50Hz 陷波（仅500Hz采样率带陷波）
class EmgFilter:
    """肌电滤波：6 阶 20Hz 高通 + 50Hz 陷波（仅 500Hz 含陷波）。"""

    # 构造：预存 500/1000/2000Hz 三种采样率的滤波器组
    def __init__(self):
        # 滤波器字典：key=采样率，value=IIRFilter 列表
        self._dict_filter: dict[int, list[IIRFilter]] = {}
        # 添加 500Hz 滤波配置
        self._add_filter_500()
        # 添加 1000Hz 滤波配置
        self._add_filter_1000()
        # 添加 2000Hz 滤波配置
        self._add_filter_2000()

    # 500Hz 配置：6阶高通 + 50Hz陷波（两个级联滤波器）
    def _add_filter_500(self):
        # 定义两个级联的 IIR 滤波器
        filters = [
            # 第一个：6阶20Hz高通滤波器
            IIRFilter(
                [
                    0.614371537726035,
                    -3.68622922635621,
                    9.21557306589052,
                    -12.2874307545207,
                    9.21557306589052,
                    -3.68622922635621,
                    0.614371537726035,
                ],
                [
                    1,
                    -5.02943835142161,
                    10.6070421837797,
                    -11.9993158162167,
                    7.67547454820020,
                    -2.63105512847395,
                    0.377452386374089,
                ],
            ),
            # 第二个：50Hz 工频陷波滤波器
            IIRFilter(
                [0.984260526926093, -1.59256698635130, 0.984260526926093],
                [1, -1.59256698635130, 0.968521053852186],
            ),
        ]
        # 存入字典：500Hz → 高通+陷波
        self._dict_filter[500] = filters

    # 1000Hz 配置：只有 6阶20Hz高通，无陷波
    def _add_filter_1000(self):
        filters = [
            IIRFilter(
                [
                    0.784297852893036,
                    -4.70578711735822,
                    11.7644677933955,
                    -15.6859570578607,
                    11.7644677933955,
                    -4.70578711735822,
                    0.784297852893036,
                ],
                [
                    1,
                    -5.51453512116617,
                    12.6891130565151,
                    -15.5936352107041,
                    10.7932966704854,
                    -3.98935940423088,
                    0.615123122052628,
                ],
            ),
        ]
        self._dict_filter[1000] = filters

    # 2000Hz 配置：只有 6阶20Hz高通，无陷波
    def _add_filter_2000(self):
        filters = [
            IIRFilter(
                [
                    0.885673290152356,
                    -5.31403974091414,
                    13.2850993522853,
                    -17.7134658030471,
                    13.2850993522853,
                    -5.31403974091414,
                    0.885673290152356,
                ],
                [
                    1,
                    -5.75724418624657,
                    13.8155108060580,
                    -17.6873761798940,
                    12.7416173292292,
                    -4.89692489143373,
                    0.784417176889300,
                ],
            ),
        ]
        self._dict_filter[2000] = filters

    # 外部调用接口：根据采样率自动滤波
    # rate：当前采样率   sample：原始采样点
    def process_sample(self, rate: int, sample: float) -> float:
        # 初始输出 = 原始值
        output = float(sample)
        # 获取当前采样率对应的滤波器组
        filters = self._dict_filter.get(rate)
        # 如果有对应滤波器，则依次级联滤波
        if filters:
            for filt in filters:
                output = filt.process_sample(output)
        # 返回最终滤波结果
        return output