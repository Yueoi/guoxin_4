# 启用未来版本的类型注解语法，让代码类型提示更规范
from __future__ import annotations

# 导入时间模块，用于延时等待
import time
# 导入类型注解工具，用于标注可迭代对象类型
from typing import Iterable
# 导入串口通信库
import serial

# 导入指令生成类：负责打包串口发送的指令
from ads_cmd import AdsCmd
# 导入数据解析类：负责接收、解析、滤波肌电数据
from ads_data import AdsData, SAMPLE_RATES

# 默认采样率：500sps（该采样率下会启用 20Hz高通 + 50Hz工频陷波滤波）
DEFAULT_RATE = "500sps"
# 默认电压量程：±200mV（肌电信号常用量程）
DEFAULT_RANGE = "±200mV"


# 功能：向多个串口设备 发送指令
# uarts：多个串口对象列表  cmd：要发送的指令字节
def uarts_send_cmd(uarts: Iterable[serial.Serial], cmd: bytes):
    # 遍历所有串口，逐个发送指令
    for uart in uarts:
        uart.write(cmd)


# 功能：从多个串口 读取数据并解析
# uarts：串口列表  ads_data_list：每个串口对应的数据解析器
def uarts_read_parse(uarts: Iterable[serial.Serial], ads_data_list: Iterable[AdsData]):
    # 配对串口和对应的解析器
    for uart, ads_data in zip(uarts, ads_data_list):
        # 获取串口接收缓冲区中等待读取的字节数
        waiting = uart.in_waiting
        # 如果有数据
        if waiting > 0:
            # 读取所有数据并交给解析器解包
            ads_data.data_unpack(uart.read(waiting))


# 功能：打开多个串口并初始化参数
# ports：串口端口号列表  baudrate：波特率
# 返回：打开好的串口对象列表
def open_uarts(ports: list[str], baudrate: int = 256000) -> list[serial.Serial]:
    # 存储打开的所有串口
    uarts = []
    # 遍历要打开的串口
    for port in ports:
        # 创建串口对象并配置参数
        uart = serial.Serial(
            port=port,                  # 串口号
            baudrate=baudrate,          # 波特率 256000
            bytesize=serial.EIGHTBITS,  # 数据位 8位
            parity=serial.PARITY_NONE,  # 校验位 无
            stopbits=serial.STOPBITS_ONE,  # 停止位 1位
            timeout=0.1,                # 读取超时时间
        )
        # 关闭 DTR 信号（避免设备复位）
        uart.dtr = False
        # 关闭 RTS 信号
        uart.rts = False
        # 清空接收缓冲区
        uart.reset_input_buffer()
        # 清空发送缓冲区
        uart.reset_output_buffer()
        # 加入串口列表
        uarts.append(uart)
    return uarts


# 功能：清空所有串口的接收缓冲区
def flush_uarts(uarts: Iterable[serial.Serial]):
    for uart in uarts:
        uart.reset_input_buffer()


# 功能：安全关闭多个串口（先发送断开连接指令，再关闭串口）
def close_uarts(uarts: Iterable[serial.Serial], ads_cmd: AdsCmd | None = None):
    # 如果传入了指令对象
    if ads_cmd:
        # 发送连接状态=0（断开连接）
        uarts_send_cmd(uarts, ads_cmd.conn_status_update(0))
        # 等待指令发送完成
        time.sleep(0.05)
    # 遍历关闭所有串口
    for uart in uarts:
        if uart.is_open:
            uart.close()


# 功能：初始化设备（打开串口 + 创建解析器 + 发送连接成功指令）
# 返回：串口列表、解析器列表、指令对象
def init_devices(
    ports: list[str],
    debug: bool = False,
    filter_switch: bool = True,
) -> tuple[list[serial.Serial], list[AdsData], AdsCmd]:
    # 打开所有串口
    uarts = open_uarts(ports)
    # 为每个串口创建一个数据解析器
    ads_data_list = [AdsData(debug=debug, filter_switch=filter_switch) for _ in ports]
    # 创建指令生成对象
    ads_cmd = AdsCmd()
    # 发送指令：连接状态=1（已连接）
    uarts_send_cmd(uarts, ads_cmd.conn_status_update(1))
    time.sleep(0.05)
    # 返回三部分：串口、解析器、指令生成器
    return uarts, ads_data_list, ads_cmd


# 功能：启动肌电信号采集（配置采样率、量程、启停采集）
def start_acquisition(
    uarts: list[serial.Serial],
    ads_cmd: AdsCmd,
    ads_data_list: Iterable[AdsData] | None = None,
    rate: str = DEFAULT_RATE,
    range_str: str = DEFAULT_RANGE,
):
    # 如果传入了解析器列表
    if ads_data_list:
        # 获取采样率索引
        rate_index = AdsCmd.RATES.index(rate) if rate in AdsCmd.RATES else 2
        # 重置每个解析器
        for ads_data in ads_data_list:
            ads_data.clear()  # 清空历史数据
            ads_data.rate = SAMPLE_RATES[rate_index]  # 设置采样率

    # 清空串口接收缓存
    flush_uarts(uarts)
    # 先停止采集（防止设备正在运行）
    uarts_send_cmd(uarts, ads_cmd.stop_collect_cmd())
    time.sleep(0.1)
    # 发送采样率、量程配置指令
    uarts_send_cmd(uarts, ads_cmd.set_sample_par_cmd(rate, range_str))
    time.sleep(0.05)
    # 打印日志
    print(f"开始采集 ({rate}, {range_str})")
    # 发送启动采集指令
    uarts_send_cmd(uarts, ads_cmd.start_collect_cmd())


# 功能：停止肌电信号采集
def stop_acquisition(uarts: list[serial.Serial], ads_cmd: AdsCmd):
    # 发送停止采集指令
    uarts_send_cmd(uarts, ads_cmd.stop_collect_cmd())
    time.sleep(0.1)