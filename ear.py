import time
import os
import sounddevice as sd
import numpy as np
import threading

SAMPLE_RATE = 16000
recording = False
audio_data = []
TRIGGER_FILE = "./trigger"

def record_audio():
    global recording, audio_data
    audio_data = []
    
    def callback(indata, frames, time, status):
        if recording:
            audio_data.append(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=callback):
        while recording:
            sd.sleep(100)

def save_audio(filename):
    if audio_data:
        audio = np.concatenate(audio_data, axis=0)
        with open(filename, 'wb') as f:
            f.write(audio.tobytes())
        return True
    return False

def read_trigger_file():
    try:
        with open(TRIGGER_FILE, "r") as f:
            content = f.read().strip()
        print(f"Read trigger file. Content: '{content}'")
        return content
    except FileNotFoundError:
        print(f"Trigger file not found: {TRIGGER_FILE}")
        return None
    except Exception as e:
        print(f"Error reading trigger file: {e}")
        return None

def main():
    global recording
    last_trigger_state = None
    record_thread = None
    
    while True:
        trigger_state = read_trigger_file()
        
        if trigger_state and trigger_state != last_trigger_state:
            print(f"Trigger state changed from '{last_trigger_state}' to '{trigger_state}'")
            
            if trigger_state == "START" and not recording:
                print("Recording started...")
                recording = True
                record_thread = threading.Thread(target=record_audio)
                record_thread.start()
            elif trigger_state == "STOP" and recording:
                print("Recording stopped.")
                recording = False
                if record_thread:
                    record_thread.join()
                if save_audio("./audio.raw"):
                    with open("./whisper_input", "w") as f:
                        f.write("./audio.raw")
                    print("Audio saved and whisper_input created.")
                else:
                    print("No audio data recorded.")
            
            last_trigger_state = trigger_state
        
        time.sleep(0.1)  # Check for trigger changes every 100ms

if __name__ == "__main__":
    main()
