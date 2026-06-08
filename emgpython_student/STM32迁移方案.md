# emgpython_student 基于 STM32 的 S-EMG 功能迁移方案

## 1. 目标

本文档用于指导将 `S-EMG-main` 中的手势识别能力迁移到当前工程 `emgpython_student` 中。

迁移目标不是简单复制代码，而是基于当前工程已经具备的 `STM32 + ADS1292 + Python 上位机` 采集链路，补齐以下能力：

1. 手势训练数据采集
2. 固定窗口切片
3. EMG 特征提取
4. 手势分类模型训练
5. 模型保存与加载
6. 实时在线识别

---

## 2. 两个工程的定位差异

### 2.1 S-EMG-main 的定位

`S-EMG-main` 是一个完整的手势识别原型，核心流程为：

```text
Arduino采集 -> 串口文本输出 -> Python读取 -> 按手势采集数据
-> 切片 -> 特征提取 -> 随机森林训练 -> 实时预测
```

其核心能力已经覆盖了训练和识别闭环。

### 2.2 emgpython_student 的定位

`emgpython_student` 当前更像一个 `STM32/ADS1292 实时采集与显示平台`，已经具备：

1. 串口连接与设备初始化
2. ADS1292 二进制协议解析
3. 两通道 EMG 原始/滤波数据缓存
4. 实时波形显示
5. 包络与活动等级分析

当前工程的关键入口和数据链路：

- 主程序入口：[main.py](C:\Users\yikuz\Desktop\work2\emgpython_student\main.py#L201)
- 串口与设备管理：[ads_multi_uart.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_multi_uart.py#L95)
- 串口读包解析：[ads_multi_uart.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_multi_uart.py#L32)
- EMG 数据解析类：[ads_data.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_data.py#L18)
- 原始/滤波后的双通道缓存：[ads_data.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_data.py#L33) 与 [ads_data.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_data.py#L35)
- 当前默认采样率配置：[ads_multi_uart.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_multi_uart.py#L17)
- 当前支持采样率列表：[ads_data.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_data.py#L14)
- 当前数字滤波实现：[ads_filter.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_filter.py#L45)

结论：

`emgpython_student` 已经解决了底层采集问题，但还没有形成“训练和分类识别”的完整流程。

因此，迁移重点应当是：

`保留现有STM32采集链路，接入S-EMG-main的识别链`

---

## 3. 必须正视的硬件差异

这是本次迁移最关键的部分。

### 3.1 采集硬件不同

`S-EMG-main`：

1. Arduino
2. 文本串口数据
3. 每行逗号分隔
4. 主脚本直接 `readline()` 解析

`emgpython_student`：

1. STM32 + ADS1292
2. 二进制帧协议
3. Python 侧通过 `AdsData.data_unpack()` 解包
4. 解包后形成 `numpy` 数组

这意味着：

`S-EMG-main` 中“串口读取层”不能直接迁移，必须由当前工程已有的 ADS 数据链替代。

### 3.2 通道数不同

`S-EMG-main` 的训练与识别流程默认基于 `3 通道` 输入。

而当前工程 `AdsData` 中缓存的数据是 `2 通道`：

- `self.chx_val = np.empty((0, 2))`：[ads_data.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_data.py#L33)
- `self.chx_raw = np.empty((0, 2))`：[ads_data.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_data.py#L35)

这会带来两个直接后果：

1. 原工程训练好的模型不能直接复用
2. 特征维度会变化，必须重新训练模型

### 3.3 采样率约束不同

当前工程默认采样率是 `500sps`：[ads_multi_uart.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_multi_uart.py#L17)

并支持：

`125 / 250 / 500 / 1000 / 2000 / 4000 Hz`

而 `S-EMG-main` 的部分频域特征在原始实现中将 `fs` 写死为 `2000`。

因此迁移时必须改成：

`特征提取函数从外部传入采样率`

否则频域特征会失真。

### 3.4 滤波位置不同

`S-EMG-main` 的硬件端使用 Arduino `EMGFilters` 做前处理。

当前工程则是在 Python 解析后，通过 `EmgFilter` 按采样率做数字滤波：[ads_filter.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_filter.py#L147)

这意味着迁移时必须统一一个原则：

1. 训练和预测都使用 `raw` 数据，再在特征层统一处理
2. 或训练和预测都使用 `filtered` 数据

推荐方案：

`训练与识别统一使用 filtered 数据（即 chx_val）`

理由：

1. 与当前上位机显示链路一致
2. 能减少实时识别阶段的输入噪声
3. 无需重复在特征模块再做一套高通/陷波

---

## 4. 迁移总策略

本次迁移建议采用：

`保留底层，插入中层，新增上层`

具体含义如下：

### 4.1 保留底层

以下模块原则上不改或少改：

1. [ads_multi_uart.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_multi_uart.py)
2. [ads_data.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_data.py)
3. [ads_filter.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_filter.py)
4. 当前 `STM32/ADS1292` 设备通信协议

这些模块已经承担了“设备采集层”的职责，不建议再混入训练和识别逻辑。

### 4.2 插入中层

新增一层“EMG 数据适配层”，把当前工程的 `AdsData` 输出转换成手势识别所需的窗口数据。

这一层建议新增：

1. `emg_stream_adapter.py`
2. `emg_window.py`
3. `emg_dataset.py`

### 4.3 新增上层

新增模型相关流程：

1. 特征提取
2. 训练
3. 模型保存
4. 模型加载
5. 实时推理

建议新增：

1. `emg_features.py`
2. `emg_train.py`
3. `emg_predict.py`
4. `model_io.py`
5. `gesture_session.py`

---

## 5. 推荐的迁移后工程结构

建议在 `emgpython_student` 中逐步演化为如下结构：

```text
emgpython_student/
├─ main.py                      # 现有实时采集/显示入口
├─ ads_multi_uart.py            # 保留
├─ ads_data.py                  # 保留
├─ ads_filter.py                # 保留
├─ emg_envelope.py              # 保留
├─ emg_lpf.py                   # 保留
├─ emg_stream_adapter.py        # 新增：从AdsData取出实时EMG流
├─ emg_window.py                # 新增：窗口切片
├─ emg_dataset.py               # 新增：手势数据采集与标签组织
├─ emg_features.py              # 新增：从S-EMG-main迁移并改造
├─ emg_train.py                 # 新增：训练与评估
├─ emg_predict.py               # 新增：在线推理
├─ model_io.py                  # 新增：模型保存/加载
├─ gesture_session.py           # 新增：采集一轮手势训练数据
├─ models/                      # 新增：保存训练模型
└─ data/                        # 新增：保存原始手势数据
```

---

## 6. 逐模块迁移建议

## 6.1 串口读取层

### 结论

`不迁移 S-EMG-main 的串口读取代码`

### 原因

原工程的串口读取建立在：

1. 文本协议
2. `readline()`
3. `split(",")`
4. `float()` 转换

而当前工程已经有成熟的二进制协议解析能力：

- [ads_multi_uart.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_multi_uart.py#L32)
- [ads_data.py](C:\Users\yikuz\Desktop\work2\emgpython_student\ads_data.py#L92)

### 要做的事

只新增一个轻量适配接口，例如：

```python
def get_latest_emg_block(ads_data, use_filtered=True) -> np.ndarray:
    ...
```

输出统一为：

```python
shape = (N, C)
```

其中：

- `N` 为当前缓存点数
- `C` 为通道数，当前为 `2`

---

## 6.2 训练数据采集层

### 迁移来源

迁移 `S-EMG-main` 重构版中的以下职责：

1. 读一段数据
2. 按手势类别收集
3. 重复多轮
4. 组织成训练样本

### 在 STM32 工程中的实现方式

当前工程不再通过“读串口一行就是一个样本点”的方式采集。

建议改为：

1. 启动设备采集
2. 连续缓存数据
3. 用户执行指定手势
4. 在固定时间窗内截取一段稳定 EMG 数据
5. 将该段数据标记为当前手势

### 推荐采集方式

每个手势一轮采集建议按“秒数”而不是“点数”驱动。

例如：

1. 倒计时 1 秒准备
2. 连续保持动作 2 到 3 秒
3. 自动截取中间稳定区间

这样比直接数点更适合 STM32 实时链路。

### 建议新增接口

```python
def collect_gesture_segment(
    ads_data,
    gesture_name: str,
    duration_sec: float,
    use_filtered: bool = True,
) -> np.ndarray:
    ...
```

---

## 6.3 滑窗切片层

### 迁移来源

迁移 `S-EMG-main` 中“按固定窗口切分 EMG”的逻辑。

### 但不能原样照搬

原工程写法更像“固定块切分”，对通用滑窗支持一般。

迁移到当前项目时建议重写为标准接口：

```python
def sliding_window(data, window_size, stride):
    ...
```

### 推荐参数

如果当前采样率采用 `500Hz`：

1. `window_size = 200`
2. `stride = 100`

对应含义：

1. 每窗约 `0.4s`
2. 每 `0.2s` 输出一次识别结果

这比原工程的 `stride=200` 响应更快，更适合实时识别。

---

## 6.4 特征提取层

### 迁移来源

优先迁移 `S-EMG-main/feature_utils.py` 中的特征函数。

### 迁移原则

不是“直接复制”，而是“参数化重构”。

必须改造的点：

1. 采样率 `fs` 不能写死
2. 支持 `2 通道` 输入
3. 特征拼接逻辑不要假设固定 3 通道
4. 异常处理不能再使用 `except: pass`

### 推荐保留的特征

优先保留以下稳定且解释性较强的特征：

1. RMS
2. MAV
3. WL
4. ZC
5. SSC
6. VAR
7. WA
8. AR
9. MPF
10. SM2
11. 小波包特征

### 推荐暂缓迁移的特征

以下特征建议先不作为第一阶段必做项：

1. 所有不易解释且收益不明确的高维特征
2. 可能与当前两通道数据耦合不稳定的特征

建议分两阶段：

1. 第一阶段先做“轻量特征集”
2. 第二阶段再扩展全特征集

### 第一阶段建议特征集

推荐先实现：

```text
RMS + MAV + WL + ZC + SSC + VAR + AR + MPF
```

原因：

1. 实现简单
2. 训练速度快
3. 便于排查问题
4. 足够验证整条识别链路

---

## 6.5 模型训练层

### 迁移来源

迁移 `S-EMG-main` 中的随机森林训练思路。

### 推荐保留

第一阶段仍然使用：

`RandomForestClassifier`

原因：

1. 对小样本友好
2. 对特征缩放不敏感
3. 调试成本低
4. 很适合先把流程跑通

### 必须修改

当前模型训练逻辑必须从“脚本内部顺序执行”改为“独立训练模块”。

建议提供接口：

```python
def train_gesture_model(feature_data, feature_label):
    ...
```

以及：

```python
def evaluate_model(model, test_x, test_y):
    ...
```

### 输出内容

训练模块应输出：

1. 模型对象
2. 类别映射表
3. 训练精度
4. 测试精度
5. 特征维度
6. 采样率
7. 窗口参数

这样后续在线推理时才能做一致性校验。

---

## 6.6 模型保存与加载层

### 现状

`S-EMG-main` 已经有简单的 `joblib` 保存能力，但当前工程没有完整的模型加载链。

### 建议

保存的不应只有分类器，还应保存完整元信息：

```python
{
    "model": ...,
    "labels": ...,
    "sample_rate": 500,
    "window_size": 200,
    "stride": 100,
    "channel_count": 2,
    "feature_names": [...],
    "use_filtered": True,
}
```

### 原因

STM32 版本的项目比 Arduino 版本更需要“配置一致性校验”。

否则容易出现：

1. 训练时是 2 通道
2. 推理时变成 1 通道或 3 通道
3. 训练时用 `500Hz`
4. 推理时设备切到 `1000Hz`

这会直接让模型失效。

---

## 6.7 实时预测层

### 当前工程已有基础

当前主循环已经能持续读取数据并更新图形：

- [main.py](C:\Users\yikuz\Desktop\work2\emgpython_student\main.py#L242)

### 迁移目标

在现有主循环上增加：

1. 实时滑窗
2. 特征提取
3. 模型推理
4. 分类结果显示

### 推荐接入方式

不要把识别逻辑硬塞进绘图代码里。

建议新增一个实时预测器对象，例如：

```python
class EmgOnlinePredictor:
    def update(self, emg_block: np.ndarray) -> str | None:
        ...
```

主循环只负责：

1. 取当前设备数据
2. 将新数据喂给预测器
3. 如果有新预测结果，则更新标题或日志

### 推荐显示方式

将当前类别附加到现有标题里，例如：

```text
EMG Dev1 | 500Hz | Gesture=front | Conf=0.82
```

---

## 7. 当前工程最适合的迁移路线

## 阶段 1：先打通“离线训练”

目标：

1. 保持现有 `main.py` 不大改
2. 新增手势采集脚本
3. 新增特征提取模块
4. 新增训练脚本

产出：

1. 能采集 STM32 的手势数据
2. 能训练一个两通道模型
3. 能保存模型

### 推荐完成项

1. `emg_dataset.py`
2. `emg_window.py`
3. `emg_features.py`
4. `emg_train.py`
5. `model_io.py`

---

## 阶段 2：接入“在线推理”

目标：

1. 在现有实时显示主循环中接入预测
2. 不破坏原来的可视化能力

产出：

1. 运行 `main.py` 时可实时显示预测结果

### 推荐完成项

1. `emg_predict.py`
2. `EmgOnlinePredictor`
3. 在 [main.py](C:\Users\yikuz\Desktop\work2\emgpython_student\main.py) 中增加轻量集成

---

## 阶段 3：再优化识别效果

目标：

1. 比较 `raw` 与 `filtered` 输入效果
2. 比较 `200/100`、`250/125` 等窗口参数
3. 扩展特征集
4. 尝试更强模型

候选方向：

1. `SVM`
2. `XGBoost`
3. `LightGBM`
4. 小型 `1D CNN`

第一版不建议直接上深度学习，先把可复现的数据链和标签体系做好更重要。

---

## 8. 核心兼容性决策

这几个决策建议在方案里先固定。

### 决策 1：保留 STM32 数据入口，不迁移 Arduino 串口读取代码

理由：

当前工程已有完整设备协议链，重复迁移 Arduino 串口层没有价值。

### 决策 2：模型重新训练，不复用旧模型

理由：

1. 通道数不同
2. 采样链路不同
3. 滤波链路不同

### 决策 3：优先使用两通道模型

理由：

当前工程天然输出 2 通道数据。

如果后续一定要复现原项目的 3 通道方案，应单独评估：

1. 是否接入第二块 ADS 设备
2. 多设备是否能稳定同步
3. 是否有必要为了 3 通道显著增加系统复杂度

默认建议：

`先做2通道版本`

### 决策 4：第一版继续用随机森林

理由：

比起换模型，当前更大的风险来自：

1. 采集一致性
2. 标签质量
3. 滑窗设计
4. 特征参数化

---

## 9. 建议新增的接口定义

下面是一组建议的稳定接口，方便后续模块化实现。

### 9.1 数据采集

```python
def collect_gesture_dataset(
    ports: list[str],
    gesture_names: list[str],
    rounds: int,
    seconds_per_round: float,
    sample_rate: str = "500sps",
    use_filtered: bool = True,
):
    ...
```

### 9.2 滑窗

```python
def make_windows(data: np.ndarray, window_size: int, stride: int) -> np.ndarray:
    ...
```

### 9.3 特征提取

```python
def extract_window_features(window: np.ndarray, fs: int) -> np.ndarray:
    ...
```

### 9.4 训练

```python
def train_model(
    feature_data: np.ndarray,
    feature_label: np.ndarray,
):
    ...
```

### 9.5 在线推理

```python
class EmgOnlinePredictor:
    def push_samples(self, samples: np.ndarray):
        ...

    def predict_latest(self):
        ...
```

---

## 10. 主要风险与应对

## 风险 1：两通道特征不足，精度低于原项目

应对：

1. 先验证 2 通道是否足够
2. 优化电极贴附位置
3. 增加训练轮次
4. 调整窗口长度和步长
5. 再考虑多设备扩展

## 风险 2：训练和实时数据分布不一致

应对：

1. 训练和预测统一使用 `filtered` 或统一使用 `raw`
2. 固定采样率
3. 固定手势采集流程
4. 保存完整模型元数据

## 风险 3：实时主循环被识别逻辑拖慢

应对：

1. 只对新增样本做增量缓存
2. 每次仅预测最新窗口
3. 先使用轻量特征集
4. 必要时将预测频率限制为每 `100~200ms` 一次

## 风险 4：协议层与模型层耦合过深

应对：

1. 严格把 `ads_*` 模块视作设备层
2. 识别逻辑只读取 `numpy` 数据，不直接操作串口

---

## 11. 推荐实施顺序

按下面顺序做，风险最低：

1. 从 `S-EMG-main` 迁移 `feature_utils.py`，重构为 `emg_features.py`
2. 编写 `emg_window.py`，实现标准滑窗
3. 编写 `emg_dataset.py`，基于 `AdsData` 采集训练样本
4. 编写 `emg_train.py`，实现两通道模型训练
5. 编写 `model_io.py`，保存和加载带元数据的模型
6. 编写 `emg_predict.py`，实现实时预测器
7. 最后再把预测结果接入 [main.py](C:\Users\yikuz\Desktop\work2\emgpython_student\main.py)

---

## 12. 一句话总结

这次迁移的正确思路不是把 `S-EMG-main` 整个搬过来，而是：

`保留 emgpython_student 的 STM32/ADS1292 采集与解析层，把 S-EMG-main 的“窗口 + 特征 + 训练 + 预测”能力重构接入`

尤其要注意：

1. 当前工程是 `2 通道`
2. 当前工程是 `二进制协议`
3. 当前工程采样率可配置
4. 因此旧模型不能直接用，必须基于 STM32 数据重新训练

---

## 13. 建议的第一阶段交付物

如果按最小可用版本推进，第一阶段建议把目标定为：

1. 采集 4 类手势数据
2. 生成两通道窗口样本
3. 提取基础特征
4. 训练随机森林模型
5. 保存模型
6. 离线验证分类准确率

在这一步完成之前，不建议急着把所有实时显示、等级分析、界面联动都和识别深度耦合到一起。

先把数据链和模型链跑通，后面的在线识别会顺很多。
