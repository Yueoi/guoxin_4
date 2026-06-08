# 定义一个命令指令类 AdsCmd，用于生成硬件通信的指令数据包
class AdsCmd:
    # 硬件通信地址常量：硬件版本地址
    ADDRESS_BOARD = 0x01
    # 软件通信地址常量：软件版本地址
    ADDRESS_SOFTWARE = 0x02
    # 设备LH001关闭地址（保留/特定功能）
    ADDRESS_LH001_LOFF = 0x08
    # 连接状态通信地址
    ADDRESS_CONN_STATUS = 0x10
    # 肌电信号采集启动/停止地址
    ADDRESS_EMG_START = 0x11
    # 采样参数设置地址（采样率、量程）
    ADDRESS_SAMPLE_PAR = 0x12

    # 支持的采样率列表，单位：样本/秒
    RATES = ["125sps", "250sps", "500sps", "1000sps", "2000sps", "4000sps"]
    # 支持的电压量程列表
    RANGES = ["±2.4V", "±1.2V", "±800mV", "±600mV", "±400mV", "±300mV", "±200mV"]

    # 指令数据打包函数：将地址、读写标志、数据组装成通信协议格式
    # address：通信地址  is_write：1=写操作 0=读操作  data：要发送的数据
    def cmd_data_pack(self, address: int, is_write: int, data: list | bytes | None) -> bytes:
        # 如果传入数据为空，默认设置为空列表
        if data is None:
            data = []
        # 统一将数据转为列表格式，方便后续拼接
        data = list(data)

        # 初始化指令帧：帧头0xAA + 数据长度(数据长度+3)
        cmd = [0xAA, len(data) + 3]
        # 添加读写标志：0x80=写指令  0x81=读指令
        cmd.append(0x80 if is_write else 0x81)
        # 添加通信地址
        cmd.append(address)
        # 追加用户数据
        cmd.extend(data)

        # 计算校验值（异或校验），从第2个字节开始到数据结束
        xor_val = 0
        for i in range(1, len(cmd)):
            xor_val ^= cmd[i]

        # 追加异或校验值 + 帧尾0xBB
        cmd.extend([xor_val, 0xBB])
        # 转换为bytes类型返回（硬件通信标准格式）
        return bytes(cmd)

    # 读取硬件版本指令：调用打包函数，读操作，无数据
    def read_hardware_version(self) -> bytes:
        return self.cmd_data_pack(self.ADDRESS_BOARD, 0, [])

    # 读取软件版本指令：调用打包函数，读操作，无数据
    def read_software_version(self) -> bytes:
        return self.cmd_data_pack(self.ADDRESS_SOFTWARE, 0, [])

    # 开始采集指令：写操作，发送0x01启动
    def start_collect_cmd(self) -> bytes:
        return self.cmd_data_pack(self.ADDRESS_EMG_START, 1, [0x01])

    # 停止采集指令：写操作，发送0x00停止
    def stop_collect_cmd(self) -> bytes:
        return self.cmd_data_pack(self.ADDRESS_EMG_START, 1, [0x00])

    # 更新连接状态指令
    # status：0=断开 1=已连接 2=保持连接
    def conn_status_update(self, status: int) -> bytes:
        """0=断开, 1=已连接, 2=保持连接"""
        # 只取低8位数据，防止数值越界
        return self.cmd_data_pack(self.ADDRESS_CONN_STATUS, 1, [status & 0xFF])

    # 设置采样参数指令：采样率 + 电压量程
    # rate：采样率  range_str：量程
    def set_sample_par_cmd(self, rate: str = "500sps", range_str: str = "±200mV") -> bytes:
        # 获取采样率索引，不存在则默认使用500sps（索引2）
        rate_index = self.RATES.index(rate) if rate in self.RATES else 2
        # 获取量程索引，不存在则默认使用±200mV（索引6）
        range_index = self.RANGES.index(range_str) if range_str in self.RANGES else 6
        # 打包指令：采样率索引 + 量程索引 + 保留位0x00
        return self.cmd_data_pack(self.ADDRESS_SAMPLE_PAR, 1, [rate_index, range_index, 0x00])