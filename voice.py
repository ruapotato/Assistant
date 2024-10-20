import os
import time
import subprocess
import logging

VOICE_DIR = "./voice/"
TRIGGER_FILE = "./trigger"

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def speak(text):
    try:
        subprocess.run(['espeak', text], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        logging.info(f"Spoke: {text}")
    except subprocess.CalledProcessError:
        logging.error("Failed to run espeak. Make sure it's installed.")
    except Exception as e:
        logging.error(f"Error in speak function: {e}")

def read_trigger_file():
    try:
        with open(TRIGGER_FILE, "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None
    except Exception as e:
        logging.error(f"Error reading trigger file: {e}")
        return None

def process_voice_files():
    if not os.path.exists(VOICE_DIR):
        os.makedirs(VOICE_DIR)
        logging.info(f"Created directory: {VOICE_DIR}")

    while True:
        trigger_state = read_trigger_file()
        if trigger_state == "START":
            logging.info("Recording in progress. Pausing speech.")
            time.sleep(0.5)
            continue

        try:
            voice_files = sorted([f for f in os.listdir(VOICE_DIR) if f.endswith('.txt')])
        except FileNotFoundError:
            logging.error(f"Directory not found: {VOICE_DIR}")
            time.sleep(1)
            continue

        for file_name in voice_files:
            file_path = os.path.join(VOICE_DIR, file_name)
            try:
                with open(file_path, 'r') as file:
                    text = file.read().strip()
                
                speak(text)
                
                os.remove(file_path)
                logging.info(f"Processed and removed file: {file_name}")
            except Exception as e:
                logging.error(f"Error processing file {file_name}: {e}")

        time.sleep(0.1)  # Small delay to prevent excessive CPU usage

if __name__ == "__main__":
    logging.info("Starting voice processing...")
    process_voice_files()
