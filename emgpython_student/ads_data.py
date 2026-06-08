"""EMG 串口数据解包与滤波，对齐 C# 代码 RunE_Module/ADS1292_Data.cs"""
# 导入未来版本的注解支持，让类型提示更规范
from __future__ import annotations

# 导入数值计算库，用于数据处理和滤波
import numpy as np

# 导入指令生成类，用于解析设备地址、指令类型
from ads_cmd import AdsCmd
# 导入滤波相关类和默认采样率常量
from ads_filter import DEFAULT_SAMPLE_RATE, EmgFilter

# 设备支持的采样率列表，对应索引 0~5 分别为 125、250、500、1000、2000、4000 Hz
SAMPLE_RATES = [125, 250, 500, 1000, 2000, 4000]


# EMG 数据解析核心类：负责串口数据接收、帧校验、指令解析、原始数据提取、滤波
class AdsData:
    # 初始化方法：配置采样率、调试模式、滤波开关
    # rate: 采样率，默认使用滤波类的默认采样率
    # debug: 是否打印调试日志
    # filter_switch: 是否开启滤波，默认开启
    def __init__(self, rate: int = DEFAULT_SAMPLE_RATE, debug: bool = False, filter_switch: bool = True):
        # 串口数据缓存区：存储未解析完的字节流
        self.data_cache = bytearray()
        # 存储设备软件版本号
        self.software_version = ""
        # 存储设备硬件版本号
        self.hardware_version = ""
        # 有效数据帧计数
        self.frame_count = 0
        # 存储滤波后的双通道 EMG 数据（二维数组：[点数, 通道2]）
        self.chx_val = np.empty((0, 2))
        # 存储原始双通道 EMG 数据（未滤波）
        self.chx_raw = np.empty((0, 2))
        # 当前使用的采样率
        self.rate = rate
        # 滤波开关：True=开启滤波，False=关闭
        self.filter_switch = filter_switch
        # 调试模式开关
        self.debug = debug
        # 标记：是否已经打印过【首包原始数据】日志
        self._logged_first_packet = False
        # 标记：是否已经打印过【首次解析成功】日志
        self._logged_first_parse = False
        # 两个通道的 EMG 滤波器实例
        self._emg_filters = [EmgFilter(), EmgFilter()]

    # 清空所有数据：重置缓存、波形数据、计数器、滤波器
    def clear(self):
        # 清空串口缓存
        self.data_cache.clear()
        # 清空滤波后数据
        self.chx_val = np.empty((0, 2))
        # 清空原始数据
        self.chx_raw = np.empty((0, 2))
        # 帧计数归零
        self.frame_count = 0
        # 重置两个通道的滤波器
        self._emg_filters = [EmgFilter(), EmgFilter()]

    # 调试用：只打印【第一次】收到的串口原始数据，避免刷屏
    def _log_first_packet(self, data_in: bytes | bytearray):
        # 开启调试 + 未打印过首包 + 有数据进入
        if self.debug and not self._logged_first_packet and data_in:
            # 取前48字节预览
            preview = bytes(data_in[:48])
            # 打印长度 + 十六进制数据
            print(f"首包原始数据({len(data_in)}字节): {preview.hex(' ')}")
            # 标记已打印
            self._logged_first_packet = True

    # 尝试跳过指令帧（0xAA 开头的指令包），只解析 0xA5 开头的数据流帧
    # data: 完整数据缓存  addr_n: 当前解析位置  data_len: 缓存总长度
    # 返回：跳过的长度，None=不是指令帧
    def _try_skip_cmd_frame(self, data: bytearray, addr_n: int, data_len: int) -> int | None:
        # 不是 0xAA 开头，不是指令帧
        if data[addr_n] != 0xAA:
            return None

        # 计算帧总长度 = 第二个字节 + 3
        frame_len = data[addr_n + 1] + 3
        # 长度太短 或 超出缓存范围，无效帧
        if frame_len < 6 or frame_len > (data_len - addr_n):
            return None
        # 帧尾是 0xBB，确认是有效指令帧，返回长度用于跳过
        if data[addr_n + frame_len - 1] == 0xBB:
            return frame_len
        return None

    # 外部入口：传入串口数据，进行解包解析
    def data_unpack(self, data_in: bytes | bytearray | list):
        # 统一转为 bytes 类型
        data_in = bytes(data_in)
        # 打印首包调试日志
        self._log_first_packet(data_in)

        # 记录解析前的帧数，用于判断是否解析出新帧
        frames_before = self.frame_count
        # 旧缓存 + 新数据 = 完整待解析数据
        data = bytearray(self.data_cache) + bytearray(data_in)
        # 总长度
        data_len = len(data)
        # 当前解析指针
        addr_n = 0

        # 循环解析：剩余数据长度 > 5 才可能是有效帧
        while (data_len - addr_n) > 5:
            # 先尝试跳过指令帧（0xAA）
            skipped = self._try_skip_cmd_frame(data, addr_n, data_len)
            if skipped:
                addr_n += skipped
                continue

            # 不是 0xA5 开头的肌电数据帧，指针+1
            if data[addr_n] != 0xA5:
                addr_n += 1
                continue

            # 帧头校验：第1字节 ^ 第2字节 = 第3字节
            check_byte = data[addr_n + 1] ^ data[addr_n + 2]
            if data[addr_n + 3] != check_byte:
                # 校验失败，丢弃当前字节
                if self.debug:
                    print("帧头校验出错")
                addr_n += 1
                continue

            # 计算帧总长度
            frame_len = data[addr_n + 1] + 3
            # 帧不完整，等待后续数据
            if frame_len > (data_len - addr_n):
                break

            # 帧尾是 0x5A，有效肌电数据帧
            if data[addr_n + frame_len - 1] == 0x5A:
                # 解析这一帧
                self._frame_unpack(data[addr_n : addr_n + frame_len])
                # 指针跳过当前帧
                addr_n += frame_len
            else:
                # 帧尾错误
                if self.debug:
                    print("帧尾出错")
                addr_n += 1

        # 更新缓存：保留未解析完的剩余数据
        self.data_cache = data[addr_n:data_len]

        # 调试：第一次解析成功时，打印数据状态
        if self.frame_count > frames_before and not self._logged_first_parse:
            self._logged_first_parse = True
            # 计算原始信号标准差
            raw_std = float(np.std(self.chx_raw)) if self.chx_raw.size else 0.0
            print(
                f"数据解析正常: 累计 {self.frame_count} 帧, {len(self.chx_val)} 个采样点, "
                f"采样率={self.rate}Hz"
            )
            print(
                f"  原始信号: 均值={np.mean(self.chx_raw):.1f}, "
                f"标准差={raw_std:.4f}, 范围=[{np.min(self.chx_raw):.1f}, {np.max(self.chx_raw):.1f}]"
            )
            # 信号标准差过低，提示电极或连接异常
            if raw_std < 1.0:
                print("  提示: 原始信号几乎无变化，请检查电极接触与设备连接")

    # 内部帧解析：根据帧类型分发处理（版本、采样率、肌电原始数据）
    def _frame_unpack(self, frame: bytearray | bytes | list):
        # 帧类型：对应 AdsCmd 里的地址
        frame_type = frame[2]

        # 硬件版本帧
        if frame_type == AdsCmd.ADDRESS_BOARD:
            self._frame_hardware(frame)
        # 软件版本帧
        elif frame_type == AdsCmd.ADDRESS_SOFTWARE:
            self._frame_software(frame)
        # 肌电原始数据帧
        elif frame_type == AdsCmd.ADDRESS_EMG_START:
            self._frame_emg_raw(frame)
            # 有效肌电帧 +1
            self.frame_count += 1
        # 采样参数帧
        elif frame_type == AdsCmd.ADDRESS_SAMPLE_PAR:
            self._frame_sample_par(frame)

    # 解析硬件版本
    def _frame_hardware(self, frame):
        # 数据长度 = 帧长度字段 - 2
        length = frame[1] - 2
        # 从帧中提取字符串并解码
        self.hardware_version = bytes(frame[4 : 4 + length]).decode("ascii", errors="replace")
        print(f"硬件版本号：{self.hardware_version}")

    # 解析软件版本
    def _frame_software(self, frame):
        length = frame[1] - 2
        self.software_version = bytes(frame[4 : 4 + length]).decode("ascii", errors="replace")
        print(f"软件版本号：{self.software_version}")

    # 解析采样率参数并更新
    def _frame_sample_par(self, frame):
        # 采样率索引
        rate_index = frame[4]
        # 索引有效则更新采样率
        if rate_index < len(SAMPLE_RATES):
            self.rate = SAMPLE_RATES[rate_index]
            if self.debug:
                print(f"设备采样率: {self.rate} Hz")

    # 核心：解析肌电原始数据 + 滤波
    def _frame_emg_raw(self, frame):
        # 计算一帧里包含多少个采样点：(数据长度-2) // 4 （每个float占4字节）
        n = (frame[1] - 2) // 4
        # 从字节流中解析出 float32 类型的肌电数据
        emg_data = np.frombuffer(bytes(frame[4 : 4 + n * 4]), dtype=np.float32)

        # 临时存储本帧的原始数据和滤波数据
        raw_rows = []
        filtered_rows = []
        # 每2个float为一组（CH1 + CH2）
        for i in range(n // 2):
            raw_pair = []
            filt_pair = []
            # 遍历两个通道
            for ch in range(2):
                # 取出原始值
                raw_val = float(emg_data[i * 2 + ch])
                raw_pair.append(raw_val)
                # 判断是否滤波
                if self.filter_switch:
                    # 用对应通道的滤波器处理
                    filt_val = self._emg_filters[ch].process_sample(self.rate, raw_val)
                else:
                    # 关闭滤波，直接使用原始值
                    filt_val = raw_val
                filt_pair.append(filt_val)
            # 加入本帧临时列表
            raw_rows.append(raw_pair)
            filtered_rows.append(filt_pair)

        # 转为 numpy 数组，方便后续拼接
        raw_block = np.asarray(raw_rows, dtype=np.float64)
        filt_block = np.asarray(filtered_rows, dtype=np.float64)

        # 第一次数据：直接赋值
        if self.chx_raw.size == 0:
            self.chx_raw = raw_block
            self.chx_val = filt_block
        # 非第一次：垂直拼接（追加新数据）
        else:
            self.chx_raw = np.vstack([self.chx_raw, raw_block])
            self.chx_val = np.vstack([self.chx_val, filt_block])