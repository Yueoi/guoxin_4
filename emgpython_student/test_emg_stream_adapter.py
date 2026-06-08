from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from ads_cmd import AdsCmd
from ads_data import AdsData
from emg_stream_adapter import EMGStream, get_latest_emg_block, get_new_emg_block


def make_emg_frame(sample_pairs: list[list[float]]) -> bytes:
    payload = np.asarray(sample_pairs, dtype=np.float32).reshape(-1).tobytes()
    payload_len = len(payload)
    frame_len_byte = payload_len + 2
    address = AdsCmd.ADDRESS_EMG_START
    check_byte = frame_len_byte ^ address
    return bytes([0xA5, frame_len_byte, address, check_byte]) + payload + bytes([0x5A])


class FakeSerial:
    def __init__(self, frames: list[bytes], chunk_size: int = 128):
        self._buffer = bytearray().join(frames)
        self._chunk_size = chunk_size
        self.is_open = True

    @property
    def in_waiting(self) -> int:
        return min(len(self._buffer), self._chunk_size)

    def read(self, size: int) -> bytes:
        n = min(size, self._chunk_size, len(self._buffer))
        data = bytes(self._buffer[:n])
        del self._buffer[:n]
        return data

    def close(self):
        self.is_open = False


class EmgStreamAdapterTests(unittest.TestCase):
    def test_block_helpers_return_nx2_numpy_arrays(self):
        ads_data = AdsData(rate=500, filter_switch=False)
        ads_data.data_unpack(
            make_emg_frame(
                [
                    [1.0, 10.0],
                    [2.0, 20.0],
                    [3.0, 30.0],
                ]
            )
        )

        latest = get_latest_emg_block(ads_data, use_filtered=False)
        new_block, next_cursor = get_new_emg_block(ads_data, start_index=1, use_filtered=False)

        self.assertIsInstance(latest, np.ndarray)
        self.assertEqual(latest.shape, (3, 2))
        self.assertEqual(new_block.shape, (2, 2))
        self.assertEqual(next_cursor, 3)
        np.testing.assert_allclose(latest[0], [1.0, 10.0])
        np.testing.assert_allclose(new_block[0], [2.0, 20.0])

    def test_stream_reads_250_samples_as_numpy_array_at_500hz(self):
        samples = [[float(i), float(i + 1000)] for i in range(250)]
        frames = [make_emg_frame(samples[i : i + 10]) for i in range(0, len(samples), 10)]
        fake_uart = FakeSerial(frames, chunk_size=96)
        fake_ads_data = AdsData(rate=500, filter_switch=False)

        with (
            patch("emg_stream_adapter.init_devices", return_value=([fake_uart], [fake_ads_data], AdsCmd())),
            patch("emg_stream_adapter.start_acquisition"),
            patch("emg_stream_adapter.stop_acquisition"),
            patch("emg_stream_adapter.close_uarts"),
        ):
            with EMGStream(
                ports=["COM5"],
                rate="500sps",
                use_filtered=False,
                poll_interval_sec=0.0,
            ) as stream:
                block = stream.read_samples(250, timeout_sec=0.2)

        self.assertEqual(stream.sample_rate_hz, 500)
        self.assertIsInstance(block, np.ndarray)
        self.assertEqual(block.shape, (250, 2))
        self.assertEqual(block.dtype, np.float64)
        np.testing.assert_allclose(block[0], [0.0, 1000.0])
        np.testing.assert_allclose(block[-1], [249.0, 1249.0])


if __name__ == "__main__":
    unittest.main()
