from __future__ import annotations

from emg_stream_adapter import EMGStream


def main():
    ports = ["COM5"]

    with EMGStream(ports=ports, rate="500sps", use_filtered=True) as stream:
        block = stream.read_samples(250, timeout_sec=3.0)
        print(f"type={type(block)}")
        print(f"shape={block.shape}")
        print(f"dtype={block.dtype}")
        print("first_5_rows=")
        print(block[:5])


if __name__ == "__main__":
    main()
