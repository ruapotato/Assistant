import os
import time
import numpy as np
import torch
from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

# Whisper model configuration
device = "cuda:0" if torch.cuda.is_available() else "cpu"
torch_dtype = torch.float16 if torch.cuda.is_available() else torch.float32
model_id = "openai/whisper-large-v3-turbo"

model = AutoModelForSpeechSeq2Seq.from_pretrained(
    model_id, torch_dtype=torch_dtype, low_cpu_mem_usage=True, use_safetensors=True
)
model.to(device)

processor = AutoProcessor.from_pretrained(model_id)

pipe = pipeline(
    "automatic-speech-recognition",
    model=model,
    tokenizer=processor.tokenizer,
    feature_extractor=processor.feature_extractor,
    torch_dtype=torch_dtype,
    device=device,
)

def process_audio(audio_path):
    audio_data = np.frombuffer(open(audio_path, "rb").read(), dtype=np.float32)
    result = pipe(audio_data)
    return result['text']

def main():
    while True:
        if os.path.exists("./whisper_input"):
            with open("./whisper_input", "r") as f:
                audio_path = f.read().strip()
            
            if audio_path and os.path.exists(audio_path):
                transcription = process_audio(audio_path)
                
                with open("./heard", "w") as f:
                    f.write(transcription)
                
                os.remove("./whisper_input")
                os.remove(audio_path)
            
        time.sleep(0.1)  # Check for input every 100ms

if __name__ == "__main__":
    main()
