import os
import sys
import wave
import array
import shutil
import threading
import subprocess
from datetime import datetime
import tkinter as tk
from tkinter import messagebox

import soundcard as sc


def get_app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def find_ffmpeg() -> str | None:
    app_dir = get_app_dir()
    bundled_ffmpeg = os.path.join(app_dir, "ffmpeg.exe")
    if os.path.isfile(bundled_ffmpeg):
        return bundled_ffmpeg

    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        temp_ffmpeg = os.path.join(meipass, "ffmpeg.exe")
        if os.path.isfile(temp_ffmpeg):
            return temp_ffmpeg

    return shutil.which("ffmpeg")


def float_samples_to_pcm16_bytes(chunks: list[list[float]]) -> bytes:
    pcm = array.array("h")
    for row in chunks:
        for val in row:
            if val > 1.0:
                val = 1.0
            elif val < -1.0:
                val = -1.0
            pcm.append(int(val * 32767.0))
    return pcm.tobytes()


class SystemAudioRecorderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("บันทึกเสียงลำโพง MP3 - ลุงแจ่ม อารมณ์ดี")
        self.root.geometry("360x210")
        self.root.resizable(False, False)
        self.root.configure(bg="#111827")

        self.is_recording = False
        self.record_thread: threading.Thread | None = None
        self.audio_rows: list[list[float]] = []
        self.sample_rate = 48000
        self.channels = 2

        self.build_ui()

    def build_ui(self):
        title_label = tk.Label(
            self.root,
            text="บันทึกเสียงที่ดังจากลำโพง (MP3 320kbps)",
            font=("Tahoma", 11, "bold"),
            fg="#F9FAFB",
            bg="#111827",
        )
        title_label.pack(pady=(18, 6))

        self.status_label = tk.Label(
            self.root,
            text="พร้อมใช้งาน",
            font=("Tahoma", 11),
            fg="#9CA3AF",
            bg="#111827",
        )
        self.status_label.pack(pady=(0, 14))

        btn_frame = tk.Frame(self.root, bg="#111827")
        btn_frame.pack()

        self.record_btn = tk.Button(
            btn_frame,
            text="● บันทึก",
            font=("Tahoma", 13, "bold"),
            bg="#16A34A",
            fg="#FFFFFF",
            activebackground="#15803D",
            activeforeground="#FFFFFF",
            width=10,
            height=2,
            bd=0,
            cursor="hand2",
            command=self.start_recording,
        )
        self.record_btn.pack(side=tk.LEFT, padx=8)

        self.stop_btn = tk.Button(
            btn_frame,
            text="■ หยุด",
            font=("Tahoma", 13, "bold"),
            bg="#DC2626",
            fg="#FFFFFF",
            activebackground="#B91C1C",
            activeforeground="#FFFFFF",
            width=10,
            height=2,
            bd=0,
            cursor="hand2",
            state=tk.DISABLED,
            command=self.stop_recording,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=8)

    def start_recording(self):
        if self.is_recording:
            return

        ffmpeg_path = find_ffmpeg()
        if not ffmpeg_path:
            messagebox.showerror(
                "ไม่พบ ffmpeg.exe",
                "ไม่พบไฟล์ ffmpeg.exe ในโฟลเดอร์โปรแกรมหรือในระบบ\nกรุณาวาง ffmpeg.exe ไว้ข้างไฟล์โปรแกรมครับ",
            )
            return

        try:
            speaker = sc.default_speaker()
            loopback_mic = sc.get_microphone(id=str(speaker.id), include_loopback=True)
        except Exception as exc:
            messagebox.showerror("ข้อผิดพลาดอุปกรณ์เสียง", f"ไม่สามารถเข้าถึงเสียงลำโพงได้:\n{exc}")
            return

        self.audio_rows = []
        self.is_recording = True
        self.record_btn.config(state=tk.DISABLED, bg="#4B5563")
        self.stop_btn.config(state=tk.NORMAL, bg="#DC2626")
        self.status_label.config(text="กำลังบันทึกเสียง...", fg="#4ADE80")

        self.record_thread = threading.Thread(
            target=self._record_loop,
            args=(loopback_mic,),
            daemon=True,
        )
        self.record_thread.start()

    def _record_loop(self, loopback_mic):
        try:
            with loopback_mic.recorder(samplerate=self.sample_rate, channels=self.channels) as rec:
                while self.is_recording:
                    data = rec.record(numframes=4096)
                    if data is not None and len(data) > 0:
                        self.audio_rows.extend(data.tolist())
        except Exception as exc:
            self.root.after(0, lambda: self._on_record_error(str(exc)))

    def _on_record_error(self, err_msg: str):
        self.is_recording = False
        self.record_btn.config(state=tk.NORMAL, bg="#16A34A")
        self.stop_btn.config(state=tk.DISABLED, bg="#6B7280")
        self.status_label.config(text="เกิดข้อผิดพลาดระหว่างบันทึก", fg="#F87171")
        messagebox.showerror("ข้อผิดพลาดการบันทึก", err_msg)

    def stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        self.stop_btn.config(state=tk.DISABLED, bg="#6B7280")
        self.status_label.config(text="กำลังแปลงเป็น MP3 320kbps...", fg="#FACC15")

        threading.Thread(target=self._save_mp3, daemon=True).start()

    def _save_mp3(self):
        if self.record_thread and self.record_thread.is_alive():
            self.record_thread.join(timeout=3)

        if not self.audio_rows:
            self.root.after(0, lambda: self._finish_ui("ไม่มีข้อมูลเสียงที่บันทึกได้", "#F87171"))
            return

        try:
            pcm_bytes = float_samples_to_pcm16_bytes(self.audio_rows)

            out_dir = get_app_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_wav = os.path.join(out_dir, f"_temp_{timestamp}.wav")
            out_mp3 = os.path.join(out_dir, f"SpeakerAudio_{timestamp}.mp3")

            with wave.open(temp_wav, "wb") as wf:
                wf.setnchannels(self.channels)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(pcm_bytes)

            ffmpeg_path = find_ffmpeg()
            cmd = [
                ffmpeg_path,
                "-y",
                "-i",
                temp_wav,
                "-vn",
                "-ac",
                "2",
                "-ar",
                str(self.sample_rate),
                "-b:a",
                "320k",
                out_mp3,
            ]

            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=creationflags)

            if os.path.exists(temp_wav):
                os.remove(temp_wav)

            self.root.after(0, lambda: self._finish_ui(f"บันทึกสำเร็จ: SpeakerAudio_{timestamp}.mp3", "#4ADE80"))
        except Exception as exc:
            self.root.after(0, lambda: self._finish_ui(f"แปลง MP3 ไม่สำเร็จ: {exc}", "#F87171"))

    def _finish_ui(self, msg: str, color: str):
        self.record_btn.config(state=tk.NORMAL, bg="#16A34A")
        self.stop_btn.config(state=tk.DISABLED, bg="#6B7280")
        self.status_label.config(text=msg, fg=color)


if __name__ == "__main__":
    root = tk.Tk()
    app = SystemAudioRecorderApp(root)
    root.mainloop()
