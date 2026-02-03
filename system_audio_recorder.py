"""
系统声音记录器
"""

import time
import threading
import numpy as np
import soundcard as sc
import wave
from collections import deque
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import warnings

warnings.filterwarnings("ignore", category=sc.SoundcardRuntimeWarning)

# ================= 参数 =================
SAMPLE_RATE = 44100
CHANNELS = 2
BLOCK = 2048

START_RMS = 0.03  # 判定“有音乐”
SILENCE_RMS = 0.006  # 判定“无声”
SILENCE_TIME = 20.0  # 10 秒无声结束

SAVE_DIR = "songs"
TEMP_DIR = "temp"
# =======================================

Path(SAVE_DIR).mkdir(exist_ok=True)
Path(TEMP_DIR).mkdir(exist_ok=True)


def rms(x):
    return np.sqrt(np.mean(x**2))


class RecorderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("系统声音记录器")

        self.running = False
        self.thread = None
        self.song_index = 1

        # 状态
        self.recording = False
        self.has_started_song = False
        self.silence_start = None
        self.start_time = None

        self.temp_wav = None
        self.tail_buffer = deque(maxlen=int(SILENCE_TIME * SAMPLE_RATE / BLOCK) + 2)

        # UI
        self.status_var = tk.StringVar(value="未开始")
        self.rms_var = tk.StringVar(value="RMS: 0.00000")
        self.device_var = tk.StringVar(value="设备: 未初始化")
        self.count_var = tk.StringVar(value="已保存: 0")
        self.path_var = tk.StringVar(value=f"保存路径: {Path(SAVE_DIR).absolute()}")

        ttk.Label(
            root,
            text="点击开始后系统会自动检测声音，有声音则自动开始;20秒无声则自动结束",
        ).pack(pady=10)
        ttk.Label(root, textvariable=self.device_var).pack(pady=4)
        ttk.Label(root, textvariable=self.status_var, font=("Arial", 14)).pack(pady=6)
        ttk.Label(root, textvariable=self.rms_var).pack(pady=4)
        ttk.Label(root, textvariable=self.count_var).pack(pady=4)
        ttk.Label(root, textvariable=self.path_var, wraplength=420).pack(pady=4)

        self.btn = ttk.Button(root, text="▶ 开始监听", command=self.toggle)
        self.btn.pack(pady=10)

    # ================= 控制 =================

    def toggle(self):
        if not self.running:
            self._reset_state()
            self.running = True
            self.btn.config(text="⏹ 停止")
            self.thread = threading.Thread(target=self.record_loop, daemon=True)
            self.thread.start()
        else:
            self.running = False
            self.btn.config(text="▶ 开始监听")
            self._finalize_if_needed()
            self.status_var.set("已停止")

    # ================= 主循环 =================

    def record_loop(self):
        speaker = sc.default_speaker()
        mic = sc.get_microphone(speaker.name, include_loopback=True)
        self.device_var.set(f"🎧 Loopback: {mic.name}")
        self.status_var.set("监听中...")

        with mic.recorder(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            blocksize=BLOCK,
        ) as rec:
            while self.running:
                data = rec.record(BLOCK)
                level = rms(data)
                self.rms_var.set(f"RMS: {level:.5f}")

                # ---------- 检测开始 ----------
                if level >= START_RMS:
                    if not self.recording:
                        self._start_new_song()
                        print("🎶 新歌曲开始")

                    self._write_block(data)
                    self.silence_start = None
                    continue

                # ---------- 尚未开始 ----------
                if not self.has_started_song:
                    continue

                # ---------- 已开始 ----------
                self._write_block(data)

                if level < SILENCE_RMS:
                    if self.silence_start is None:
                        self.silence_start = time.time()
                    elif time.time() - self.silence_start >= SILENCE_TIME:
                        self._finalize_and_save()
                else:
                    self.silence_start = None

    # ================= 录制逻辑 =================

    def _start_new_song(self):
        self.recording = True
        self.has_started_song = True
        self.silence_start = None
        self.start_time = time.time()
        self.tail_buffer.clear()

        temp_path = Path(TEMP_DIR) / "current.wav"
        self.temp_wav = wave.open(str(temp_path), "wb")
        self.temp_wav.setnchannels(CHANNELS)
        self.temp_wav.setsampwidth(2)
        self.temp_wav.setframerate(SAMPLE_RATE)

        self.status_var.set("🎶 录制中...")

    def _write_block(self, data):
        pcm = np.clip(data, -1.0, 1.0)
        pcm = (pcm * 32767).astype(np.int16)

        self.temp_wav.writeframes(pcm.tobytes())
        self.tail_buffer.append(pcm.copy())

    # ================= 保存 =================

    def _finalize_if_needed(self):
        if self.has_started_song:
            self._finalize_and_save()

    def _finalize_and_save(self):
        if not self.temp_wav:
            self._reset_state()
            return

        self.temp_wav.close()

        temp_path = Path(TEMP_DIR) / "current.wav"
        save_path = (
            Path(SAVE_DIR)
            / f"song_{self.song_index:03d}_{time.strftime('%Y%m%d_%H%M%S')}.wav"
        )

        self._trim_and_save(temp_path, save_path)

        duration = time.time() - self.start_time
        print(f"💾 保存：{save_path} ({duration:.1f}s)")

        self.song_index += 1
        self.count_var.set(f"已保存: {self.song_index - 1}")
        self.status_var.set("监听中...")

        self._reset_state()

    def _trim_and_save(self, src, dst):
        with wave.open(str(src), "rb") as r:
            frames = r.readframes(r.getnframes())

        trim_bytes = len(self.tail_buffer) * BLOCK * CHANNELS * 2
        final_data = frames[:-trim_bytes] if trim_bytes < len(frames) else frames

        with wave.open(str(dst), "wb") as w:
            w.setnchannels(CHANNELS)
            w.setsampwidth(2)
            w.setframerate(SAMPLE_RATE)
            w.writeframes(final_data)

    # ================= 清理 =================

    def _reset_state(self):
        self.recording = False
        self.has_started_song = False
        self.silence_start = None
        self.start_time = None
        self.tail_buffer.clear()
        self.temp_wav = None


# ================= 入口 =================

if __name__ == "__main__":
    root = tk.Tk()
    app = RecorderGUI(root)
    root.mainloop()
