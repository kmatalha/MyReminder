import os
import struct
import wave
import io
import winsound

def generate_beep_wav():
    sample_rate = 44100
    freq = 440
    duration_ms = 800
    samples = int(sample_rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for i in range(samples):
            val = int(32767.0 * 0.5 * (
                __import__('math').sin(2 * __import__('math').pi * freq * i / sample_rate)
            ))
            wav_file.writeframesraw(struct.pack('<h', val))
    buf.seek(0)
    return buf.read()

BEEP_WAV = generate_beep_wav()

def play_alarm_sound(file_path=None):
    try:
        winsound.PlaySound(None, winsound.SND_ASYNC)
        if file_path and os.path.exists(file_path):
            winsound.PlaySound(file_path, winsound.SND_ASYNC | winsound.SND_LOOP)
        else:
            winsound.PlaySound(BEEP_WAV, winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_LOOP)
    except:
        pass

def stop_alarm_sound():
    try:
        winsound.PlaySound(None, winsound.SND_ASYNC)
    except:
        pass