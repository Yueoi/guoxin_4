from __future__ import annotations

from time import monotonic, sleep

import numpy as np

from ads_cmd import AdsCmd
from ads_data import AdsData, SAMPLE_RATES
from ads_multi_uart import (
    DEFAULT_RANGE,
    DEFAULT_RATE,
    close_uarts,
    init_devices,
    start_acquisition,
    stop_acquisition,
    uarts_read_parse,
)


def get_latest_emg_block(ads_data: AdsData, use_filtered: bool = True) -> np.ndarray:
    """Return the current EMG buffer as an Nx2 numpy array."""
    source = ads_data.chx_val if use_filtered else ads_data.chx_raw
    return np.asarray(source, dtype=np.float64).copy()


def get_new_emg_block(
    ads_data: AdsData,
    start_index: int = 0,
    use_filtered: bool = True,
) -> tuple[np.ndarray, int]:
    """Return unread EMG samples plus the updated cursor."""
    source = ads_data.chx_val if use_filtered else ads_data.chx_raw
    cursor = max(0, min(start_index, source.shape[0]))
    block = np.asarray(source[cursor:], dtype=np.float64).copy()
    return block, source.shape[0]


class EMGStream:
    """Hide UART protocol details and expose EMG blocks as numpy arrays."""

    def __init__(
        self,
        ports: list[str],
        rate: str = DEFAULT_RATE,
        range_str: str = DEFAULT_RANGE,
        use_filtered: bool = True,
        device_index: int = 0,
        poll_interval_sec: float = 0.01,
        debug: bool = False,
    ):
        if not ports:
            raise ValueError("ports must contain at least one serial port")

        self.ports = ports
        self.rate = rate if rate in AdsCmd.RATES else DEFAULT_RATE
        self.range_str = range_str
        self.use_filtered = use_filtered
        self.device_index = device_index
        self.poll_interval_sec = max(0.0, poll_interval_sec)
        self.debug = debug
        self.sample_rate_hz = SAMPLE_RATES[AdsCmd.RATES.index(self.rate)]

        self._uarts = None
        self._ads_data_list = None
        self._ads_cmd = None
        self._cursors: list[int] = []

    def start(self) -> "EMGStream":
        if self._uarts is not None:
            return self

        self._uarts, self._ads_data_list, self._ads_cmd = init_devices(
            self.ports,
            debug=self.debug,
            filter_switch=self.use_filtered,
        )
        start_acquisition(
            self._uarts,
            self._ads_cmd,
            self._ads_data_list,
            self.rate,
            self.range_str,
        )
        self._cursors = [0] * len(self._ads_data_list)
        return self

    def close(self):
        if self._uarts is None:
            return

        try:
            stop_acquisition(self._uarts, self._ads_cmd)
        finally:
            close_uarts(self._uarts, self._ads_cmd)
            self._uarts = None
            self._ads_data_list = None
            self._ads_cmd = None
            self._cursors = []

    def __enter__(self) -> "EMGStream":
        return self.start()

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _require_started(self):
        if self._ads_data_list is None or self._uarts is None:
            raise RuntimeError("EMGStream.start() must be called before reading data")

    def _resolve_device_index(self, device_index: int | None) -> int:
        self._require_started()
        index = self.device_index if device_index is None else device_index
        if not 0 <= index < len(self._ads_data_list):
            raise IndexError(f"device_index {index} is out of range")
        return index

    def _pump_once(self):
        self._require_started()
        uarts_read_parse(self._uarts, self._ads_data_list)

    def available_samples(self, device_index: int | None = None) -> int:
        index = self._resolve_device_index(device_index)
        self._pump_once()
        source = self._ads_data_list[index].chx_val if self.use_filtered else self._ads_data_list[index].chx_raw
        return max(0, source.shape[0] - self._cursors[index])

    def read_available(self, device_index: int | None = None) -> np.ndarray:
        index = self._resolve_device_index(device_index)
        self._pump_once()
        block, new_cursor = get_new_emg_block(
            self._ads_data_list[index],
            start_index=self._cursors[index],
            use_filtered=self.use_filtered,
        )
        self._cursors[index] = new_cursor
        return block

    def read_samples(
        self,
        n_samples: int,
        device_index: int | None = None,
        timeout_sec: float = 3.0,
    ) -> np.ndarray:
        if n_samples <= 0:
            raise ValueError("n_samples must be positive")

        index = self._resolve_device_index(device_index)
        deadline = monotonic() + timeout_sec
        chunks: list[np.ndarray] = []
        collected = 0

        while collected < n_samples:
            self._pump_once()
            ads_data = self._ads_data_list[index]
            source = ads_data.chx_val if self.use_filtered else ads_data.chx_raw
            cursor = self._cursors[index]
            available = source.shape[0] - cursor

            if available > 0:
                take = min(n_samples - collected, available)
                block = np.asarray(source[cursor : cursor + take], dtype=np.float64).copy()
                self._cursors[index] = cursor + take
                chunks.append(block)
                collected += take
                continue

            if monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out while waiting for {n_samples} EMG samples at {self.sample_rate_hz}Hz"
                )

            sleep(self.poll_interval_sec)

        return np.vstack(chunks)

    def read_for_duration(
        self,
        duration_sec: float,
        device_index: int | None = None,
        timeout_sec: float | None = None,
    ) -> np.ndarray:
        if duration_sec <= 0:
            raise ValueError("duration_sec must be positive")

        n_samples = int(round(duration_sec * self.sample_rate_hz))
        timeout = timeout_sec if timeout_sec is not None else max(duration_sec * 2.0, 1.0)
        return self.read_samples(n_samples, device_index=device_index, timeout_sec=timeout)
